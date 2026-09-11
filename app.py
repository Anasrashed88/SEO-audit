import streamlit as st
import requests
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
import pandas as pd
import time
import io
import gzip
import re
import zipfile
import sqlite3
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse, urljoin, unquote
from concurrent.futures import ThreadPoolExecutor
from fpdf import FPDF
import arabic_reshaper
from bidi.algorithm import get_display

# ==============================================================
#  مركز عمليات السيو الشامل للمتاجر الإلكترونية
#  أنس راشد - anasrashed.com
# ==============================================================

st.set_page_config(page_title="مركز عمليات السيو | أنس راشد", layout="wide", page_icon="🚀")

# --------------------------------------------------------------
#  المسارات المحلية (الخط والشعار مرفوعان داخل المستودع)
# --------------------------------------------------------------
BASE_DIR = Path(__file__).parent
FONT_PATH = BASE_DIR / "Amiri-Regular.ttf"
LOGO_PATH = BASE_DIR / "brand_logo.png"
DB_FILE = str(BASE_DIR / "store_history.db")

# اختيار أسرع محلل متاح
try:
    import lxml  # noqa: F401
    PARSER = "lxml"
except Exception:
    PARSER = "html.parser"

MAX_PAGES_DEFAULT = 1500

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept-Language': 'ar,en;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
}

PAGE_TYPES = [
    'صفحة رئيسية', 'صفحة منتج', 'صفحة تصنيف', 'صفحة مدونة',
    'صفحة تعريفية', 'غير مصنفة', 'صفحة غير متاحة'
]


# ==============================================================
#  قاعدة البيانات
# ==============================================================
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS audits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        domain TEXT,
        scan_date TEXT,
        score REAL,
        total_pages INTEGER,
        products_count INTEGER,
        categories_count INTEGER,
        info_pages_count INTEGER,
        blog_pages_count INTEGER,
        data_json TEXT,
        images_json TEXT
    )''')
    # ترحيل آمن للقواعد القديمة (فحص فعلي بدل except فارغة)
    c.execute("PRAGMA table_info(audits)")
    existing_cols = {row[1] for row in c.fetchall()}
    for col, coltype in [("blog_pages_count", "INTEGER DEFAULT 0"), ("images_json", "TEXT")]:
        if col not in existing_cols:
            c.execute(f"ALTER TABLE audits ADD COLUMN {col} {coltype}")
    conn.commit()
    conn.close()


init_db()

for key, default in [
    ('audit_df', None), ('images_df', None), ('summary', None),
    ('current_url', ""), ('pdf_bytes', None), ('zip_bytes', None)
]:
    if key not in st.session_state:
        st.session_state[key] = default

st.markdown("""
    <style>
    .main { direction: rtl; text-align: right; }
    h1, h2, h3, h4, p, span, div { text-align: right; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
    .metric-card {
        background-color: #1e293b;
        border: 1px solid #334155;
        border-radius: 10px;
        padding: 12px;
        text-align: center;
        margin-bottom: 10px;
    }
    .metric-value { font-size: 24px; font-weight: bold; color: #38bdf8; }
    .metric-label { font-size: 13px; color: #94a3b8; }
    </style>
""", unsafe_allow_html=True)


# ==============================================================
#  أدوات مساعدة
# ==============================================================
def normalize_url(url):
    """تطبيع الرابط المُدخل: إضافة البروتوكول وإزالة الشرطة الأخيرة."""
    if not url:
        return ""
    url = url.strip()
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    return url.rstrip('/')


def clean_url(url):
    """توحيد شكل الرابط لأغراض المقارنة وإزالة التكرار."""
    if not url:
        return ""
    return url.split('#')[0].split('?')[0].rstrip('/')


def make_soup(markup):
    return BeautifulSoup(markup, PARSER)


# ==============================================================
#  اكتشاف الروابط (robots.txt + خرائط الموقع + الفوتر)
# ==============================================================
def discover_sitemaps_from_robots(base_url):
    """قراءة robots.txt لاكتشاف المسار الحقيقي لخرائط الموقع."""
    found = []
    try:
        res = requests.get(f"{base_url}/robots.txt", headers=HEADERS, timeout=10)
        if res.status_code == 200:
            for line in res.text.splitlines():
                if line.lower().strip().startswith('sitemap:'):
                    sm = line.split(':', 1)[1].strip()
                    if sm:
                        found.append(sm)
    except Exception:
        pass
    return found


def fetch_xml_root(url):
    """جلب ملف XML مع دعم النسخ المضغوطة (.gz)."""
    try:
        res = requests.get(url, headers=HEADERS, timeout=12)
        if res.status_code != 200:
            return None
        content = res.content
        if url.lower().endswith('.gz') or content[:2] == b'\x1f\x8b':
            try:
                content = gzip.decompress(content)
            except Exception:
                pass
        return ET.fromstring(content)
    except Exception:
        return None


def iter_locs(root):
    """استخراج جميع وسوم loc بغض النظر عن وجود namespace من عدمه."""
    for el in root.iter():
        tag = el.tag.split('}')[-1] if '}' in el.tag else el.tag
        if tag == 'loc' and el.text:
            yield el.text.strip()


def collect_from_sitemap(sitemap_url, base_netloc, all_urls, visited, depth=0, max_depth=3):
    if depth > max_depth or sitemap_url in visited:
        return
    visited.add(sitemap_url)

    root = fetch_xml_root(sitemap_url)
    if root is None:
        return

    for loc in iter_locs(root):
        if loc.lower().endswith('.xml') or loc.lower().endswith('.xml.gz'):
            collect_from_sitemap(loc, base_netloc, all_urls, visited, depth + 1, max_depth)
        else:
            u = clean_url(loc)
            if u and urlparse(u).netloc == base_netloc:
                all_urls.add(u)


def extract_footer_and_menu_urls(base_url):
    """صياد روابط الفوتر والقوائم لاكتشاف الصفحات القانونية والتعريفية."""
    found = set()
    try:
        res = requests.get(base_url, headers=HEADERS, timeout=12)
        if res.status_code == 200:
            soup = make_soup(res.text)
            target_keywords = [
                'سياسة', 'الشروط', 'الخصوصية', 'الاستبدال', 'الاسترجاع', 'الشحن',
                'الشكاوى', 'الأسئلة', 'من نحن', 'اتصل', 'توصيل', 'ضمان', 'مدونة',
                'faq', 'terms', 'privacy', 'return', 'shipping', 'about', 'contact', 'blog'
            ]
            base_netloc = urlparse(base_url).netloc
            for a in soup.find_all('a', href=True):
                href = a['href'].strip()
                text = a.get_text(strip=True).lower()
                if any(k in text for k in target_keywords) or any(k in href.lower() for k in target_keywords):
                    full_url = clean_url(urljoin(base_url, href))
                    if full_url and urlparse(full_url).netloc == base_netloc:
                        found.add(full_url)
    except Exception:
        pass
    return found


def get_all_store_urls(base_url, max_pages=MAX_PAGES_DEFAULT):
    base_url = normalize_url(base_url)
    base_netloc = urlparse(base_url).netloc
    all_urls = set()
    visited = set()

    candidates = discover_sitemaps_from_robots(base_url)
    candidates += [
        f"{base_url}/sitemap.xml",
        f"{base_url}/sitemap_index.xml",
        f"{base_url}/sitemap_products_1.xml",
        f"{base_url}/sitemap_categories.xml",
        f"{base_url}/sitemap_pages_1.xml",
    ]

    for s_url in candidates:
        collect_from_sitemap(s_url, base_netloc, all_urls, visited)

    all_urls.update(extract_footer_and_menu_urls(base_url))
    all_urls.add(base_url)

    urls = sorted(all_urls)
    truncated = len(urls) > max_pages
    return urls[:max_pages], truncated, len(urls)


# ==============================================================
#  تصنيف الصفحات
# ==============================================================
POLICY_KEYWORDS = [
    'سياسة', 'شروط', 'خصوصية', 'استبدال', 'استرجاع', 'شحن', 'توصيل', 'شكاوى',
    'اسئلة', 'أسئلة', 'من-نحن', 'اتصل', 'pages', 'policies', 'policy', 'privacy',
    'terms', 'about', 'about-us', 'contact', 'contact-us', 'faq', 'faqs',
    'shipping', 'complaint', 'complaints', 'returns', 'refund', 'payment'
]


def detect_page_type_advanced(url, base_url, soup):
    base_clean = normalize_url(base_url)
    url_clean = clean_url(url)

    # 1. الصفحة الرئيسية
    if url_clean == base_clean or urlparse(url_clean).path in ('', '/'):
        return 'صفحة رئيسية'

    path = unquote(urlparse(url_clean).path.lower())
    path_clean = path.strip('/')
    segments = [s for s in path_clean.split('/') if s]

    og_type = ""
    if soup:
        og_tag = soup.find('meta', attrs={'property': 'og:type'})
        if og_tag and og_tag.get('content'):
            og_type = og_tag['content'].lower()

    # 2. المنتجات أولاً (إشارات قاطعة قبل أي فحص بالكلمات المفتاحية)
    if 'product' in og_type:
        return 'صفحة منتج'
    if soup and soup.find(attrs={'itemtype': re.compile(r'schema\.org/Product', re.I)}):
        return 'صفحة منتج'
    if ('products' in segments or 'product' in segments) and len(segments) >= 2:
        return 'صفحة منتج'
    if re.search(r'/p\d+', path) or '-p-' in path:
        return 'صفحة منتج'
    if any(re.match(r'^p\d+$', s) for s in segments):
        return 'صفحة منتج'

    # 3. المدونة والمقالات
    if 'article' in og_type or 'blog' in og_type:
        return 'صفحة مدونة'
    if soup and soup.find(attrs={'itemtype': re.compile(r'schema\.org/(Article|BlogPosting|NewsArticle)', re.I)}):
        return 'صفحة مدونة'
    if any(s in ('blog', 'blogs', 'articles', 'article', 'post', 'posts') for s in segments):
        return 'صفحة مدونة'

    # 4. صفحات الكتالوج العامة
    if path_clean in ['products', 'product', 'all-products', 'catalog', 'collections/all', 'shop']:
        return 'صفحة تصنيف'

    # 5. الصفحات التعريفية والسياسات (مطابقة مقاطع لا احتواء نصي)
    for seg in segments:
        if any(seg == k or seg.startswith(k + '-') or k in seg.split('-') for k in POLICY_KEYWORDS):
            return 'صفحة تعريفية'

    # 6. التصنيفات والكولكشنات
    if soup and soup.find(attrs={'itemtype': re.compile(r'schema\.org/CollectionPage', re.I)}):
        return 'صفحة تصنيف'
    if any(s in ('category', 'categories', 'collection', 'collections') for s in segments):
        return 'صفحة تصنيف'
    if re.search(r'/c\d+', path) or any(re.match(r'^c\d+$', s) for s in segments):
        return 'صفحة تصنيف'

    # 7. ما تبقّى: غير مصنّفة صراحةً (لا يُنفخ به رقم الأقسام)
    return 'غير مصنفة'


# ==============================================================
#  فلترة صور المحتوى
# ==============================================================
JUNK_KEYWORDS = [
    'spinner', 'loader', 'loading', 'ajax', 'icon', 'badge',
    'payment', 'gateway', 'tamara', 'tabby', 'mada', 'visa', 'mastercard',
    'apple-pay', 'applepay', 'stc-pay', 'stcpay', 'vat', 'tax',
    'maroof', 'social', 'whatsapp', 'snapchat', 'instagram', 'tiktok',
    'twitter', 'pixel', 'spacer', 'avatar', 'arrow', 'placeholder', 'blank'
]


def get_image_src(img):
    """استخراج رابط الصورة الحقيقي مع دعم التحميل الكسول و srcset."""
    for attr in ['data-src', 'data-original', 'data-lazy', 'data-lazy-src',
                 'data-image', 'data-large_image']:
        val = img.get(attr)
        if val and val.strip():
            return val.strip()

    for attr in ['data-srcset', 'srcset']:
        val = img.get(attr)
        if val and val.strip():
            first = val.split(',')[0].strip().split(' ')[0]
            if first:
                return first

    src = img.get('src')
    return src.strip() if src else ''


def is_relevant_seo_image(img, src):
    if not src:
        return False
    src_lower = src.lower()

    # رفض base64 وصور النظام الثابتة (placeholders غالباً)
    if src_lower.startswith('data:image'):
        return False
    if 'static.' in src_lower or '/static/' in src_lower:
        return False

    # الشعار والعلامات
    if any(k in src_lower for k in ['logo', 'brand', 'favicon', 'watermark']):
        return False

    img_classes = ' '.join(img.get('class', [])).lower()
    img_id = (img.get('id') or '').lower()
    if any(k in img_classes or k in img_id for k in ['logo', 'brand']):
        return False

    # امتدادات غير مخصصة لصور المحتوى
    path_part = src_lower.split('?')[0]
    if path_part.endswith(('.gif', '.svg', '.ico')):
        return False

    # عناصر الواجهة وبوابات الدفع
    if any(junk in src_lower for junk in JUNK_KEYWORDS):
        return False

    return True


def strip_boilerplate(soup):
    """إعدام الترويسة والفوتر والقوائم مرة واحدة فقط بدون تكرار."""
    targets = soup.select(
        'header, nav, footer, aside, '
        '[class*="header"], [class*="footer"], [class*="navbar"], [class*="nav-menu"]'
    )
    for tag in targets:
        try:
            tag.decompose()
        except Exception:
            pass
    return soup


# ==============================================================
#  فحص صفحة واحدة
# ==============================================================
def failed_row(url, reason):
    return {
        'page_data': {
            'نوع الصفحة': 'صفحة غير متاحة',
            'الرابط': url,
            'الرابط الكانوني': url,
            'متاحة': False,
            'كود الاستجابة': str(reason),
            'درجة السيو': None,
            'عنوان الميتا': '',
            'حالة العنوان': 'تعذر الفحص',
            'وصف الميتا': '',
            'حالة الوصف': 'تعذر الفحص',
            'إجمالي الصور': 0,
            'صور بدون Alt': 0,
            'عدد الكلمات': 0,
            'حالة المحتوى': 'غير متاح'
        },
        'images_data': []
    }


def audit_single_page(url_item):
    url, base_url = url_item
    try:
        return _audit_single_page(url, base_url)
    except Exception as e:
        # عزل الاستثناء حتى لا تسقط نتائج الفحص بالكامل
        return failed_row(clean_url(url), f'خطأ فني: {type(e).__name__}')


def _audit_single_page(url, base_url):
    res = None
    for attempt in range(3):
        try:
            res = requests.get(url, headers=HEADERS, timeout=12, allow_redirects=True)
            if res.status_code == 429:
                time.sleep(2 * (attempt + 1))
                continue
            break
        except Exception:
            time.sleep(1)

    if res is None:
        return failed_row(clean_url(url), 'فشل اتصال')

    final_url = clean_url(res.url)

    if res.status_code != 200:
        return failed_row(final_url, f'خطأ {res.status_code}')

    soup = make_soup(res.text)
    page_type = detect_page_type_advanced(final_url, base_url, soup)

    # الرابط الكانوني (لاستبعاد النسخ المكررة بشكل صحيح)
    canonical = final_url
    can_tag = soup.find('link', attrs={'rel': lambda v: v and 'canonical' in [x.lower() for x in (v if isinstance(v, list) else [v])]})
    if can_tag and can_tag.get('href'):
        cand = clean_url(urljoin(final_url, can_tag['href']))
        if cand and urlparse(cand).netloc == urlparse(final_url).netloc:
            canonical = cand

    # العنوان
    title_tag = soup.find('title')
    title = title_tag.get_text(strip=True) if title_tag else ''
    if not title:
        title_status = 'مفقود'
    elif len(title) < 30:
        title_status = 'قصير جداً'
    elif len(title) > 65:
        title_status = 'طويل جداً'
    else:
        title_status = 'سليم'

    # الوصف
    meta_desc_tag = (soup.find('meta', attrs={'name': 'description'})
                     or soup.find('meta', attrs={'property': 'og:description'}))
    meta_desc = meta_desc_tag['content'].strip() if meta_desc_tag and meta_desc_tag.get('content') else ''
    if not meta_desc:
        desc_status = 'مفقود'
    elif len(meta_desc) < 70:
        desc_status = 'قصير جداً'
    elif len(meta_desc) > 165:
        desc_status = 'طويل جداً'
    else:
        desc_status = 'سليم'

    # جسم الصفحة بعد إزالة الترويسة والفوتر
    content_soup = strip_boilerplate(make_soup(res.text))

    total_img = 0
    missing_alt = 0
    page_images = []

    for img in content_soup.find_all('img'):
        src = get_image_src(img)
        if src and is_relevant_seo_image(img, src):
            total_img += 1
            full_img_url = urljoin(final_url, src)
            alt_text = (img.get('alt') or '').strip()
            is_missing = (alt_text == '')
            if is_missing:
                missing_alt += 1
            page_images.append({
                'رابط الصفحة': final_url,
                'نوع الصفحة': page_type,
                'رابط الصورة': full_img_url,
                'النص البديل الحالي (Alt)': alt_text if alt_text else 'لا يوجد (فارغ)',
                'حالة النص البديل': 'مفقود' if is_missing else 'سليم ومكتمل'
            })

    for s in content_soup(['script', 'style', 'noscript']):
        s.decompose()
    words = len(content_soup.get_text(separator=' ', strip=True).split())
    content_status = 'جيد' if words >= 50 else 'ضعيف جداً'

    score = 100
    if title_status != 'سليم':
        score -= 25
    if desc_status != 'سليم':
        score -= 25
    if total_img > 0 and missing_alt > 0:
        score -= int((missing_alt / total_img) * 25)
    if content_status != 'جيد':
        score -= 25
    score = max(0, score)

    return {
        'page_data': {
            'نوع الصفحة': page_type,
            'الرابط': final_url,
            'الرابط الكانوني': canonical,
            'متاحة': True,
            'كود الاستجابة': '200',
            'درجة السيو': score,
            'عنوان الميتا': title,
            'حالة العنوان': title_status,
            'وصف الميتا': meta_desc,
            'حالة الوصف': desc_status,
            'إجمالي الصور': total_img,
            'صور بدون Alt': missing_alt,
            'عدد الكلمات': words,
            'حالة المحتوى': content_status
        },
        'images_data': page_images
    }


# ==============================================================
#  مولد تقرير العميل (PDF)
# ==============================================================
def ar(text):
    return get_display(arabic_reshaper.reshape(str(text)))


def build_diagnosis(score, stats):
    """نص تشخيص مبني على نتائج الفحص الفعلية لا نص ثابت."""
    total_imgs = stats.get('total_images', 0)
    missing = stats.get('missing_alts', 0)
    bad_titles = stats.get('bad_titles', 0)
    bad_descs = stats.get('bad_descs', 0)
    broken = stats.get('broken_pages', 0)

    issues = []
    if missing > 0 and total_imgs > 0:
        ratio = round(missing / total_imgs * 100, 1)
        issues.append(f"وجود {missing} صورة من أصل {total_imgs} بلا نص بديل (بنسبة {ratio}%)، "
                      "وهو ما يحد من ظهور المتجر في نتائج بحث الصور")
    if bad_titles > 0:
        issues.append(f"{bad_titles} عنوان ميتا مفقود أو خارج الطول الموصى به")
    if bad_descs > 0:
        issues.append(f"{bad_descs} وصف ميتا مفقود أو غير مهيأ")
    if broken > 0:
        issues.append(f"{broken} رابط لم تنجح الاستجابة له أثناء الفحص")

    if not issues:
        return ("لم يرصد الفحص فجوات جوهرية في العناصر المدققة: العناوين والأوصاف ووسوم الصور "
                "ضمن المعايير الموصى بها. يوصى بمتابعة دورية للحفاظ على هذا المستوى "
                "ومراجعة المحتوى عند إضافة منتجات أو أقسام جديدة.")

    body = "أظهر الفحص الفني: " + "، و".join(issues) + ". "
    if score < 60:
        body += ("تشير النتيجة الإجمالية إلى فجوة واسعة في تهيئة المتجر لمحركات البحث. "
                 "يوصى بإعادة كتابة البيانات الوصفية وإسناد نصوص بديلة لجميع صور المحتوى "
                 "ضمن خطة عمل مرحلية.")
    elif score < 80:
        body += ("المتجر مهيأ جزئياً، ومعالجة العناصر أعلاه من شأنها رفع درجة التوافق "
                 "وتحسين فرص الظهور في نتائج البحث.")
    else:
        body += ("المستوى العام جيد، وتبقى المعالجات المذكورة تحسينات تكميلية "
                 "يمكن تنفيذها ضمن جولة مراجعة واحدة.")
    return body


def generate_client_pdf(domain, score, summary_stats):
    if not FONT_PATH.exists():
        raise FileNotFoundError(
            f"ملف الخط غير موجود في المسار: {FONT_PATH}\n"
            "تأكد من رفع Amiri-Regular.ttf إلى جذر المستودع."
        )

    clean_domain = urlparse(domain).netloc or domain
    logo_exists = LOGO_PATH.exists()

    class PDFReport(FPDF):
        def header(self):
            # الشعار بنسبة 2:1 (عرض 34mm / ارتفاع 17mm) ليبقى داخل الترويسة
            if logo_exists:
                try:
                    self.image(str(LOGO_PATH), x=15, y=9, h=13)
                except Exception:
                    pass
            self.set_font("Amiri", "", 14)
            self.set_text_color(15, 23, 42)
            self.cell(0, 7, ar("أنس راشد"), ln=True, align="R")
            self.set_font("Amiri", "", 10)
            self.set_text_color(100, 116, 139)
            self.cell(0, 5, ar("خبير تحسين محركات البحث"), ln=True, align="R")
            self.set_draw_color(226, 232, 240)
            self.line(15, 27, 195, 27)
            self.ln(6)

        def footer(self):
            self.set_y(-15)
            self.set_draw_color(226, 232, 240)
            self.line(15, 282, 195, 282)
            self.set_font("Amiri", "", 9)
            self.set_text_color(148, 163, 184)
            self.cell(0, 10, "anasrashed.com   |   anas@anasrashed.com", align="C")

    pdf = PDFReport()
    pdf.add_font("Amiri", "", str(FONT_PATH))
    pdf.add_page()

    pdf.set_font("Amiri", "", 16)
    pdf.set_text_color(15, 23, 42)
    pdf.cell(0, 8, ar("تقرير الفحص الفني الشامل لمحركات البحث"), ln=True, align="C")

    pdf.set_font("Amiri", "", 11)
    pdf.set_text_color(71, 85, 105)
    pdf.cell(0, 6, ar(f"المتجر المستهدف: {clean_domain}   |   تاريخ الفحص: "
                      f"{datetime.now().strftime('%Y-%m-%d')}"), ln=True, align="C")
    pdf.ln(4)

    # صندوق الدرجة (إحداثيات نسبية لا ثابتة)
    box_y = pdf.get_y()
    pdf.set_fill_color(248, 250, 252)
    pdf.set_draw_color(203, 213, 225)
    pdf.rect(15, box_y, 180, 16, 'DF')
    pdf.set_xy(15, box_y + 3)
    pdf.set_font("Amiri", "", 15)
    if score < 60:
        pdf.set_text_color(225, 29, 72)
    elif score < 80:
        pdf.set_text_color(217, 119, 6)
    else:
        pdf.set_text_color(16, 185, 129)
    pdf.cell(180, 10, ar(f"درجة التوافق العامة مع محركات البحث: {score}%"), align="C")
    pdf.set_y(box_y + 22)

    def draw_table(title, rows, col_widths=(120, 60)):
        table_width = sum(col_widths)
        start_x = (210 - table_width) / 2

        pdf.set_x(start_x)
        pdf.set_font("Amiri", "", 12)
        pdf.set_text_color(15, 23, 42)
        pdf.cell(table_width, 7, ar(title), ln=True, align="R")
        pdf.ln(1)

        pdf.set_x(start_x)
        pdf.set_fill_color(241, 245, 249)
        pdf.set_draw_color(203, 213, 225)
        pdf.set_font("Amiri", "", 10)
        pdf.set_text_color(30, 41, 59)
        pdf.cell(col_widths[1], 7, ar("الحالة / العدد"), 1, 0, 'C', fill=True)
        pdf.cell(col_widths[0], 7, ar("عنصر الفحص والتدقيق"), 1, 1, 'C', fill=True)

        pdf.set_font("Amiri", "", 9)
        for label, val in rows:
            pdf.set_x(start_x)
            pdf.set_text_color(71, 85, 105)
            pdf.cell(col_widths[1], 6, ar(val), 1, 0, 'C')
            pdf.cell(col_widths[0], 6, ar(label), 1, 1, 'R')
        pdf.ln(5)

    pages_rows = [
        ("إجمالي عدد الصفحات المفحوصة في المتجر", f"{summary_stats['total_pages']} صفحة"),
        ("صفحات المنتجات المكتشفة", f"{summary_stats['products']} منتج"),
        ("صفحات الأقسام والكولكشنات", f"{summary_stats['categories']} تصنيف"),
        ("مقالات وصفحات المدونة", f"{summary_stats.get('blog_pages', 0)} مقال"),
        ("الصفحات التعريفية والسياسات", f"{summary_stats['info_pages']} صفحة"),
        ("روابط تعذر الوصول إليها أثناء الفحص", f"{summary_stats.get('broken_pages', 0)} رابط"),
        ("عناوين الميتا الرئيسية المفقودة أو غير المتوافقة", f"{summary_stats['bad_titles']} عنوان"),
        ("أوصاف الميتا التسويقية المفقودة أو غير المهيأة", f"{summary_stats['bad_descs']} وصف"),
    ]
    draw_table("1. جدول تدقيق بنية الصفحات والعناوين:", pages_rows)

    total_imgs = summary_stats.get('total_images', 0)
    missing_alts = summary_stats.get('missing_alts', 0)
    alt_ratio = round((missing_alts / total_imgs * 100), 1) if total_imgs > 0 else 0

    if total_imgs == 0:
        img_state = "لم يرصد الفحص صور محتوى"
    elif missing_alts == 0:
        img_state = "مكتمل"
    elif alt_ratio > 50:
        img_state = "فجوة واسعة"
    else:
        img_state = "فجوة جزئية"

    image_rows = [
        ("إجمالي صور المحتوى والمنتجات المفحوصة", f"{total_imgs} صورة"),
        ("صور تفتقر لوسم النص البديل لمحركات البحث", f"{missing_alts} صورة"),
        ("نسبة الصور غير المهيأة لمحركات البحث", f"{alt_ratio}%"),
        ("حالة تهيئة الصور للظهور في بحث صور جوجل", img_state),
    ]
    draw_table("2. جدول تدقيق وسوم وصور المتجر:", image_rows)

    # صندوق التشخيص بارتفاع محسوب من عدد الأسطر الفعلي
    box_width = 180
    box_x = (210 - box_width) / 2
    pdf.set_x(box_x)
    pdf.set_font("Amiri", "", 12)
    pdf.set_text_color(15, 23, 42)
    pdf.cell(box_width, 6, ar("3. التشخيص الاستشاري وخطة العمل:"), ln=True, align="R")
    pdf.ln(1)

    diag_text = build_diagnosis(score, summary_stats)

    pdf.set_font("Amiri", "", 9)
    max_text_width = box_width - 10
    lines = []
    current = ""
    for word in diag_text.split():
        trial = (current + " " + word).strip()
        if pdf.get_string_width(ar(trial)) <= max_text_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)

    line_h = 4.8
    box_h = len(lines) * line_h + 6
    box_y = pdf.get_y()

    pdf.set_fill_color(248, 250, 252)
    pdf.set_draw_color(226, 232, 240)
    pdf.rect(box_x, box_y, box_width, box_h, 'DF')

    pdf.set_xy(box_x + 5, box_y + 3)
    pdf.set_text_color(71, 85, 105)
    for line in lines:
        pdf.set_x(box_x + 5)
        pdf.cell(max_text_width, line_h, ar(line), ln=True, align="R")

    return bytes(pdf.output())


# ==============================================================
#  حزمة الملفات (ZIP)
# ==============================================================
def build_zip(df, images_df):
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        groups = [
            ('صفحة منتج', "1_المنتجات_products.csv"),
            ('صفحة تصنيف', "2_التصنيفات_categories.csv"),
            ('صفحة مدونة', "3_المدونة_blog.csv"),
            ('صفحة تعريفية', "4_الصفحات_التعريفية_pages.csv"),
            ('صفحة رئيسية', "5_الصفحة_الرئيسية_homepage.csv"),
            ('غير مصنفة', "6_غير_مصنفة_unclassified.csv"),
            ('صفحة غير متاحة', "7_روابط_معطلة_errors.csv"),
        ]
        for ptype, fname in groups:
            sub = df[df['نوع الصفحة'] == ptype]
            if not sub.empty:
                zip_file.writestr(fname, sub.to_csv(index=False, encoding='utf-8-sig'))

        if images_df is not None and not images_df.empty:
            zip_file.writestr("8_تفاصيل_صور_المتجر_images_audit.csv",
                              images_df.to_csv(index=False, encoding='utf-8-sig'))

        excel_buf = io.BytesIO()
        with pd.ExcelWriter(excel_buf, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='SEO Pages Audit')
            if images_df is not None and not images_df.empty:
                images_df.to_excel(writer, index=False, sheet_name='Images Alt Audit')
        zip_file.writestr("التقرير_الشامل_all_pages_and_images.xlsx", excel_buf.getvalue())

    return zip_buffer.getvalue()


# ==============================================================
#  الواجهة
# ==============================================================
st.sidebar.title("🧭 القائمة الرئيسية")
nav = st.sidebar.radio("اختر الوجهة:", ["🔍 فحص متجر جديد", "📁 سجل المتاجر السابقة"])

if nav == "🔍 فحص متجر جديد":
    st.title("🚀 مركز عمليات السيو الشامل للمتاجر")
    st.write("أداة الفحص والتدقيق الكامل لجميع أقسام ومنتجات ومدونات وسياسات وصور المتجر الإلكتروني.")

    c_url, c_btn = st.columns([4, 1])
    with c_url:
        input_url = st.text_input("أدخل رابط المتجر الإلكتروني:",
                                  value=st.session_state.current_url,
                                  placeholder="https://midhal-oud.store")
    with c_btn:
        st.write("")
        st.write("")
        start_btn = st.button("🔍 بدء الفحص")

    with st.sidebar.expander("⚙️ إعدادات الفحص"):
        max_pages = st.number_input("الحد الأقصى للصفحات:", min_value=50, max_value=5000,
                                    value=MAX_PAGES_DEFAULT, step=50)
        workers = st.slider("عدد المسارات المتوازية:", min_value=1, max_value=8, value=4)

    if st.session_state.audit_df is not None:
        if st.sidebar.button("🔄 فحص متجر جديد (تفريغ الشاشة)"):
            for k in ['audit_df', 'images_df', 'summary', 'pdf_bytes', 'zip_bytes']:
                st.session_state[k] = None
            st.session_state.current_url = ""
            st.rerun()

    if start_btn and input_url:
        target_url = normalize_url(input_url)
        st.session_state.current_url = target_url

        with st.spinner("جاري استخراج كافة الصفحات من خرائط الموقع وروابط الفوتر..."):
            urls, truncated, total_found = get_all_store_urls(target_url, max_pages)

        if truncated:
            st.warning(f"تم العثور على {total_found} رابط، وسيقتصر الفحص على أول {max_pages} رابط "
                       "حسب الحد المحدد في الإعدادات الجانبية.")
        st.info(f"جاري فحص {len(urls)} صفحة وتدقيق الصفحات والصور...")

        progress_bar = st.progress(0)
        page_results = []
        all_images_results = []
        url_tuples = [(u, target_url) for u in urls]
        total_urls = max(len(urls), 1)
        completed = 0

        with ThreadPoolExecutor(max_workers=workers) as executor:
            for res in executor.map(audit_single_page, url_tuples):
                page_results.append(res['page_data'])
                all_images_results.extend(res['images_data'])
                completed += 1
                progress_bar.progress(min(completed / total_urls, 1.0))

        df = pd.DataFrame(page_results)
        images_df = pd.DataFrame(all_images_results)

        # إزالة التكرار على الرابط ثم على الرابط الكانوني (بدل تجريد الأرقام)
        df = df.drop_duplicates(subset=['الرابط']).copy()
        available = df[df['متاحة'] == True]  # noqa: E712
        dup_mask = available.duplicated(subset=['الرابط الكانوني'], keep='first')
        dup_urls = set(available[dup_mask]['الرابط'])
        df = df[~df['الرابط'].isin(dup_urls)].copy().reset_index(drop=True)

        # مزامنة جدول الصور مع الصفحات الباقية
        if not images_df.empty:
            images_df = images_df[images_df['رابط الصفحة'].isin(df['الرابط'])].copy().reset_index(drop=True)

        ok_df = df[df['متاحة'] == True]  # noqa: E712
        avg_score = round(ok_df['درجة السيو'].mean(), 1) if not ok_df.empty else 0.0

        summary = {
            'total_pages': len(df),
            'score': avg_score,
            'products': int((df['نوع الصفحة'] == 'صفحة منتج').sum()),
            'categories': int((df['نوع الصفحة'] == 'صفحة تصنيف').sum()),
            'info_pages': int((df['نوع الصفحة'] == 'صفحة تعريفية').sum()),
            'blog_pages': int((df['نوع الصفحة'] == 'صفحة مدونة').sum()),
            'unclassified': int((df['نوع الصفحة'] == 'غير مصنفة').sum()),
            'broken_pages': int((df['متاحة'] == False).sum()),  # noqa: E712
            'bad_titles': int((ok_df['حالة العنوان'] != 'سليم').sum()),
            'bad_descs': int((ok_df['حالة الوصف'] != 'سليم').sum()),
            'missing_alts': int(ok_df['صور بدون Alt'].sum()),
            'total_images': int(ok_df['إجمالي الصور'].sum()),
        }

        st.session_state.audit_df = df
        st.session_state.images_df = images_df
        st.session_state.summary = summary

        # توليد المخرجات مرة واحدة فقط بعد الفحص
        st.session_state.zip_bytes = build_zip(df, images_df)
        try:
            st.session_state.pdf_bytes = generate_client_pdf(target_url, avg_score, summary)
        except Exception as e:
            st.session_state.pdf_bytes = None
            st.error(f"تعذر توليد ملف الـ PDF: {e}")

        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute('''INSERT INTO audits (domain, scan_date, score, total_pages, products_count,
                     categories_count, info_pages_count, blog_pages_count, data_json, images_json)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                  (target_url, datetime.now().strftime("%Y-%m-%d %H:%M"), avg_score,
                   summary['total_pages'], summary['products'], summary['categories'],
                   summary['info_pages'], summary['blog_pages'],
                   df.to_json(orient='records'),
                   images_df.to_json(orient='records') if not images_df.empty else ''))
        conn.commit()
        conn.close()

    if st.session_state.audit_df is not None:
        df = st.session_state.audit_df
        images_df = st.session_state.images_df
        summary = st.session_state.summary

        st.success(f"اكتمل فحص وتصنيف المتجر: {st.session_state.current_url}")

        cols = st.columns(7)
        metrics = [
            (summary["total_pages"], "إجمالي الصفحات"),
            (f'{summary["score"]}%', "نسبة التوافق"),
            (summary["products"], "المنتجات"),
            (summary["categories"], "الأقسام"),
            (summary["blog_pages"], "المدونة"),
            (summary["info_pages"], "التعريفية"),
            (summary.get("broken_pages", 0), "روابط معطلة"),
        ]
        for col, (value, label) in zip(cols, metrics):
            with col:
                st.markdown(
                    f'<div class="metric-card"><div class="metric-value">{value}</div>'
                    f'<div class="metric-label">{label}</div></div>',
                    unsafe_allow_html=True
                )

        if summary.get('unclassified', 0) > 0:
            st.caption(f"ملاحظة: {summary['unclassified']} صفحة لم يمكن تصنيفها آلياً "
                       "وهي معروضة تحت تصنيف (غير مصنفة) للمراجعة اليدوية.")

        tab1, tab2 = st.tabs(["📄 جدول فحص الصفحات", "🖼️ جدول تدقيق صور المتجر (Alt Tags)"])

        with tab1:
            st.subheader("📋 تصفية وعرض الصفحات")
            available_types = ["جميع الصفحات"] + [t for t in PAGE_TYPES if (df['نوع الصفحة'] == t).any()]
            selected_type = st.selectbox("اختر نوع الصفحة للعرض:", available_types)

            if selected_type == "جميع الصفحات":
                display_df = df.copy().reset_index(drop=True)
            else:
                display_df = df[df['نوع الصفحة'] == selected_type].copy().reset_index(drop=True)

            display_df.index = display_df.index + 1
            st.dataframe(display_df, use_container_width=True)

        with tab2:
            st.subheader("🖼️ التقرير المفصل لصور المحتوى والمنتجات")
            if images_df is not None and not images_df.empty:
                filter_img = st.selectbox("تصفية الصور:",
                                          ["جميع الصور", "صور تفتقر لوسم Alt فقط", "صور سليمة"])
                if filter_img == "صور تفتقر لوسم Alt فقط":
                    view_images_df = images_df[images_df['حالة النص البديل'] == 'مفقود']
                elif filter_img == "صور سليمة":
                    view_images_df = images_df[images_df['حالة النص البديل'] == 'سليم ومكتمل']
                else:
                    view_images_df = images_df

                view_images_df = view_images_df.copy().reset_index(drop=True)
                view_images_df.index = view_images_df.index + 1
                st.dataframe(view_images_df, use_container_width=True)
            else:
                st.info("لا توجد صور محتوى بحاجة لتدقيق في هذه الصفحات.")

        st.subheader("📥 منطقة التحميل والتصدير")
        netloc = urlparse(st.session_state.current_url).netloc or "store"
        d_col1, d_col2 = st.columns(2)
        with d_col1:
            if st.session_state.pdf_bytes:
                st.download_button(
                    label="📄 تحميل تقرير العميل الرسمي (PDF)",
                    data=st.session_state.pdf_bytes,
                    file_name=f"SEO_Audit_Report_{netloc}.pdf",
                    mime="application/pdf"
                )
            else:
                st.info("تقرير الـ PDF غير متاح لهذا الفحص.")
        with d_col2:
            if st.session_state.zip_bytes:
                st.download_button(
                    label="📦 تحميل حزمة البيانات والملفات المصنفة (ZIP)",
                    data=st.session_state.zip_bytes,
                    file_name=f"Data_Package_{netloc}.zip",
                    mime="application/zip"
                )

elif nav == "📁 سجل المتاجر السابقة":
    st.title("📁 سجل المتاجر المفحوصة مسبقاً")
    st.write("يمكنك استعراض أي متجر فحصته مسبقاً وإعادة تحميل تقاريره فوراً دون إعادة الفحص.")
    st.caption("تنبيه: قاعدة البيانات محلية داخل الخادم، وقد تُفقد عند إعادة نشر التطبيق "
               "على Streamlit Cloud. للاعتماد الدائم يُنصح بتخزين خارجي.")

    conn = sqlite3.connect(DB_FILE)
    history_df = pd.read_sql_query(
        "SELECT id, domain as 'المتجر', scan_date as 'تاريخ الفحص', score as 'النسبة', "
        "total_pages as 'الصفحات', products_count as 'المنتجات', categories_count as 'الأقسام', "
        "blog_pages_count as 'المدونة', info_pages_count as 'التعريفية' "
        "FROM audits ORDER BY id DESC", conn)
    conn.close()

    if history_df.empty:
        st.info("لا توجد متاجر مفحوصة بعد في السجل.")
    else:
        st.dataframe(history_df.drop(columns=['id']), use_container_width=True)

        selected_id = st.selectbox(
            "اختر المتجر لاسترجاع بياناته:",
            history_df['id'].tolist(),
            format_func=lambda x: (f"متجر: {history_df[history_df['id'] == x]['المتجر'].values[0]} "
                                   f"({history_df[history_df['id'] == x]['تاريخ الفحص'].values[0]})")
        )

        if st.button("📥 استرجاع بيانات هذا المتجر"):
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute("SELECT domain, data_json, images_json, score FROM audits WHERE id = ?",
                      (selected_id,))
            row = c.fetchone()
            conn.close()

            if row:
                restored_df = pd.read_json(io.StringIO(row[1]))
                restored_images = (pd.read_json(io.StringIO(row[2]))
                                   if row[2] else pd.DataFrame())

                if 'متاحة' not in restored_df.columns:
                    restored_df['متاحة'] = True
                ok_df = restored_df[restored_df['متاحة'] == True]  # noqa: E712

                st.session_state.current_url = row[0]
                st.session_state.audit_df = restored_df
                st.session_state.images_df = restored_images
                st.session_state.summary = {
                    'total_pages': len(restored_df),
                    'score': row[3],
                    'products': int((restored_df['نوع الصفحة'] == 'صفحة منتج').sum()),
                    'categories': int((restored_df['نوع الصفحة'] == 'صفحة تصنيف').sum()),
                    'info_pages': int((restored_df['نوع الصفحة'] == 'صفحة تعريفية').sum()),
                    'blog_pages': int((restored_df['نوع الصفحة'] == 'صفحة مدونة').sum()),
                    'unclassified': int((restored_df['نوع الصفحة'] == 'غير مصنفة').sum()),
                    'broken_pages': int((restored_df['متاحة'] == False).sum()),  # noqa: E712
                    'bad_titles': int((ok_df['حالة العنوان'] != 'سليم').sum()),
                    'bad_descs': int((ok_df['حالة الوصف'] != 'سليم').sum()),
                    'missing_alts': int(ok_df['صور بدون Alt'].sum()),
                    'total_images': int(ok_df['إجمالي الصور'].sum()),
                }

                st.session_state.zip_bytes = build_zip(restored_df, restored_images)
                try:
                    st.session_state.pdf_bytes = generate_client_pdf(
                        row[0], row[3], st.session_state.summary)
                except Exception as e:
                    st.session_state.pdf_bytes = None
                    st.error(f"تعذر توليد ملف الـ PDF: {e}")

                st.success("تم استرجاع البيانات بنجاح! انتقل إلى صفحة (فحص متجر جديد) "
                           "من القائمة الجانبية لعرض الجداول وتحميل الملفات.")
