import streamlit as st
import requests
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
import pandas as pd
import time
import io
import gzip
import json
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

BASE_DIR = Path(__file__).parent
FONT_PATH = BASE_DIR / "Amiri-Regular.ttf"
LOGO_PATH = BASE_DIR / "brand_logo.png"
DB_FILE = str(BASE_DIR / "store_history.db")

try:
    import lxml  # noqa: F401
    PARSER = "lxml"
except Exception:
    PARSER = "html.parser"

MAX_PAGES_DEFAULT = 1500
MAX_CATEGORIES_TO_CRAWL = 80
MAX_PAGINATION_DEPTH = 40

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
        images_json TEXT,
        coverage_json TEXT
    )''')
    c.execute("PRAGMA table_info(audits)")
    existing = {row[1] for row in c.fetchall()}
    for col, coltype in [("blog_pages_count", "INTEGER DEFAULT 0"),
                         ("images_json", "TEXT"), ("coverage_json", "TEXT")]:
        if col not in existing:
            c.execute(f"ALTER TABLE audits ADD COLUMN {col} {coltype}")
    conn.commit()
    conn.close()


init_db()

for key, default in [
    ('audit_df', None), ('images_df', None), ('summary', None),
    ('current_url', ""), ('pdf_bytes', None), ('zip_bytes', None),
    ('coverage', None)
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
    if not url:
        return ""
    url = url.strip()
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    return url.rstrip('/')


def clean_url(url):
    if not url:
        return ""
    return url.split('#')[0].split('?')[0].rstrip('/')


def make_soup(markup):
    return BeautifulSoup(markup, PARSER)


def safe_get(url, timeout=12, retries=2):
    for attempt in range(retries + 1):
        try:
            res = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
            if res.status_code == 429:
                time.sleep(2 * (attempt + 1))
                continue
            return res
        except Exception:
            time.sleep(1)
    return None


# ==============================================================
#  اكتشاف الروابط
# ==============================================================
def discover_sitemaps_from_robots(base_url):
    found = []
    res = safe_get(f"{base_url}/robots.txt", timeout=10, retries=1)
    if res is not None and res.status_code == 200:
        for line in res.text.splitlines():
            if line.lower().strip().startswith('sitemap:'):
                sm = line.split(':', 1)[1].strip()
                if sm:
                    found.append(sm)
    return found


def fetch_xml_root(url):
    res = safe_get(url, timeout=12, retries=1)
    if res is None or res.status_code != 200:
        return None
    content = res.content
    if url.lower().endswith('.gz') or content[:2] == b'\x1f\x8b':
        try:
            content = gzip.decompress(content)
        except Exception:
            pass
    try:
        return ET.fromstring(content)
    except Exception:
        return None


def iter_locs(root):
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
        low = loc.lower()
        if low.endswith('.xml') or low.endswith('.xml.gz'):
            collect_from_sitemap(loc, base_netloc, all_urls, visited, depth + 1, max_depth)
        else:
            u = clean_url(loc)
            if u and urlparse(u).netloc == base_netloc:
                all_urls.add(u)


def extract_footer_and_menu_urls(base_url):
    found = set()
    res = safe_get(base_url)
    if res is None or res.status_code != 200:
        return found
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
    return found


def get_all_store_urls(base_url, max_pages=MAX_PAGES_DEFAULT):
    base_url = normalize_url(base_url)
    base_netloc = urlparse(base_url).netloc
    all_urls, visited = set(), set()

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
    return urls[:max_pages], len(urls) > max_pages, len(urls)


# ==============================================================
#  تصنيف الصفحات
# ==============================================================
POLICY_KEYWORDS = [
    'سياسة', 'شروط', 'خصوصية', 'استبدال', 'استرجاع', 'شحن', 'توصيل', 'شكاوى',
    'اسئلة', 'أسئلة', 'من-نحن', 'اتصل', 'pages', 'policies', 'policy', 'privacy',
    'terms', 'about', 'about-us', 'contact', 'contact-us', 'faq', 'faqs',
    'shipping', 'complaint', 'complaints', 'returns', 'refund', 'payment'
]

CATALOG_ROOTS = ['products', 'product', 'all-products', 'catalog', 'collections/all', 'shop']


def detect_page_type_advanced(url, base_url, soup=None):
    base_clean = normalize_url(base_url)
    url_clean = clean_url(url)

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

    # المنتجات أولاً
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

    # المدونة
    if 'article' in og_type or 'blog' in og_type:
        return 'صفحة مدونة'
    if soup and soup.find(attrs={'itemtype': re.compile(r'schema\.org/(Article|BlogPosting|NewsArticle)', re.I)}):
        return 'صفحة مدونة'
    if any(s in ('blog', 'blogs', 'articles', 'article', 'post', 'posts') for s in segments):
        return 'صفحة مدونة'

    if path_clean in CATALOG_ROOTS:
        return 'صفحة تصنيف'

    for seg in segments:
        if any(seg == k or seg.startswith(k + '-') or k in seg.split('-') for k in POLICY_KEYWORDS):
            return 'صفحة تعريفية'

    if soup and soup.find(attrs={'itemtype': re.compile(r'schema\.org/CollectionPage', re.I)}):
        return 'صفحة تصنيف'
    if any(s in ('category', 'categories', 'collection', 'collections') for s in segments):
        return 'صفحة تصنيف'
    if re.search(r'/c\d+', path) or any(re.match(r'^c\d+$', s) for s in segments):
        return 'صفحة تصنيف'

    return 'غير مصنفة'


# ==============================================================
#  طبقة التحقق من التغطية (الزحف على الأقسام)
# ==============================================================
def extract_product_links(html, base_url, page_url):
    """استخراج روابط المنتجات من صفحة قسم: من وسوم <a> ومن JSON-LD ItemList."""
    soup = make_soup(html)
    base_netloc = urlparse(base_url).netloc
    links = set()

    for a in soup.find_all('a', href=True):
        u = clean_url(urljoin(page_url, a['href']))
        if not u or urlparse(u).netloc != base_netloc:
            continue
        if detect_page_type_advanced(u, base_url, None) == 'صفحة منتج':
            links.add(u)

    for tag in soup.find_all('script', attrs={'type': 'application/ld+json'}):
        try:
            data = json.loads(tag.string or '{}')
        except Exception:
            continue
        blocks = data if isinstance(data, list) else [data]
        for block in blocks:
            if not isinstance(block, dict):
                continue
            for item in (block.get('itemListElement') or []):
                if not isinstance(item, dict):
                    continue
                target = None
                if isinstance(item.get('item'), dict):
                    target = item['item'].get('url')
                if not target:
                    target = item.get('url')
                if target:
                    u = clean_url(urljoin(page_url, str(target)))
                    if urlparse(u).netloc == base_netloc and \
                            detect_page_type_advanced(u, base_url, None) == 'صفحة منتج':
                        links.add(u)
    return links


def crawl_catalog_for_products(base_url, category_urls, progress_cb=None,
                               max_categories=MAX_CATEGORIES_TO_CRAWL,
                               max_depth=MAX_PAGINATION_DEPTH):
    """يزحف على صفحات الأقسام مع الترقيم ليجمع المنتجات المعروضة فعلياً في الواجهة."""
    base_url = normalize_url(base_url)
    roots = list(dict.fromkeys(
        [base_url] + [f"{base_url}/{r}" for r in ['products', 'collections/all', 'shop']]
        + list(category_urls)
    ))[:max_categories]

    found = set()
    pages_fetched = 0

    for idx, cat in enumerate(roots):
        seen_in_cat = set()
        for page in range(1, max_depth + 1):
            page_url = cat if page == 1 else f"{cat}?page={page}"
            res = safe_get(page_url, retries=1)
            pages_fetched += 1
            if res is None or res.status_code != 200:
                break

            new_links = extract_product_links(res.text, base_url, page_url)
            fresh = new_links - seen_in_cat
            if not fresh:
                break  # لا جديد: نهاية الترقيم أو ترقيم غير مدعوم
            seen_in_cat |= fresh
            found |= fresh

        if progress_cb:
            progress_cb((idx + 1) / max(len(roots), 1), len(found), pages_fetched)

    return found, pages_fetched


def build_coverage_report(sitemap_products, catalog_products):
    """مقارنة ثنائية الاتجاه بين ما تعلنه خريطة الموقع وما يُعرض فعلياً."""
    sm = set(sitemap_products)
    cat = set(catalog_products)
    missing_from_sitemap = sorted(cat - sm)
    not_in_catalog = sorted(sm - cat)
    total_real = len(sm | cat)
    coverage_pct = round(len(sm) / total_real * 100, 1) if total_real else 100.0
    return {
        'sitemap_count': len(sm),
        'catalog_count': len(cat),
        'matched_count': len(sm & cat),
        'missing_from_sitemap': missing_from_sitemap,
        'not_in_catalog': not_in_catalog,
        'total_real': total_real,
        'coverage_pct': coverage_pct,
    }


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
    s = src.lower()
    if s.startswith('data:image'):
        return False
    if 'static.' in s or '/static/' in s:
        return False
    if any(k in s for k in ['logo', 'brand', 'favicon', 'watermark']):
        return False
    classes = ' '.join(img.get('class', [])).lower()
    img_id = (img.get('id') or '').lower()
    if any(k in classes or k in img_id for k in ['logo', 'brand']):
        return False
    if s.split('?')[0].endswith(('.gif', '.svg', '.ico')):
        return False
    if any(j in s for j in JUNK_KEYWORDS):
        return False
    return True


def strip_boilerplate(soup):
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
            'مصدر الاكتشاف': '',
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
    url, base_url, source = url_item
    try:
        result = _audit_single_page(url, base_url)
    except Exception as e:
        result = failed_row(clean_url(url), f'خطأ فني: {type(e).__name__}')
    result['page_data']['مصدر الاكتشاف'] = source
    return result


def _audit_single_page(url, base_url):
    res = safe_get(url, timeout=12, retries=2)
    if res is None:
        return failed_row(clean_url(url), 'فشل اتصال')

    final_url = clean_url(res.url)
    if res.status_code != 200:
        return failed_row(final_url, f'خطأ {res.status_code}')

    soup = make_soup(res.text)
    page_type = detect_page_type_advanced(final_url, base_url, soup)

    canonical = final_url
    for link in soup.find_all('link', href=True):
        rel = link.get('rel') or []
        rel = [r.lower() for r in (rel if isinstance(rel, list) else [rel])]
        if 'canonical' in rel:
            cand = clean_url(urljoin(final_url, link['href']))
            if cand and urlparse(cand).netloc == urlparse(final_url).netloc:
                canonical = cand
            break

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

    content_soup = strip_boilerplate(make_soup(res.text))

    total_img = missing_alt = 0
    page_images = []
    for img in content_soup.find_all('img'):
        src = get_image_src(img)
        if src and is_relevant_seo_image(img, src):
            total_img += 1
            alt_text = (img.get('alt') or '').strip()
            if not alt_text:
                missing_alt += 1
            page_images.append({
                'رابط الصفحة': final_url,
                'نوع الصفحة': page_type,
                'رابط الصورة': urljoin(final_url, src),
                'النص البديل الحالي (Alt)': alt_text if alt_text else 'لا يوجد (فارغ)',
                'حالة النص البديل': 'مفقود' if not alt_text else 'سليم ومكتمل'
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
            'مصدر الاكتشاف': '',
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


def run_audit(urls_with_source, base_url, workers, progress_bar=None):
    page_results, image_results = [], []
    items = [(u, base_url, src) for u, src in urls_with_source]
    total = max(len(items), 1)
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for res in ex.map(audit_single_page, items):
            page_results.append(res['page_data'])
            image_results.extend(res['images_data'])
            done += 1
            if progress_bar:
                progress_bar.progress(min(done / total, 1.0))
    return page_results, image_results


# ==============================================================
#  تقرير العميل (PDF)
# ==============================================================
def ar(text):
    return get_display(arabic_reshaper.reshape(str(text)))


def build_diagnosis(score, stats):
    total_imgs = stats.get('total_images', 0)
    missing = stats.get('missing_alts', 0)
    bad_titles = stats.get('bad_titles', 0)
    bad_descs = stats.get('bad_descs', 0)
    broken = stats.get('broken_pages', 0)
    uncovered = stats.get('missing_from_sitemap_count', 0)

    issues = []
    if missing > 0 and total_imgs > 0:
        ratio = round(missing / total_imgs * 100, 1)
        issues.append(f"وجود {missing} صورة من أصل {total_imgs} بلا نص بديل (بنسبة {ratio}%)، "
                      "وهو ما يحد من ظهور المتجر في نتائج بحث الصور")
    if bad_titles > 0:
        issues.append(f"{bad_titles} عنوان ميتا مفقود أو خارج الطول الموصى به")
    if bad_descs > 0:
        issues.append(f"{bad_descs} وصف ميتا مفقود أو غير مهيأ")
    if uncovered > 0:
        issues.append(f"{uncovered} منتجاً معروضاً في المتجر لا يظهر في خريطة الموقع، "
                      "أي أن محركات البحث قد لا تعلم بوجوده")
    if broken > 0:
        issues.append(f"{broken} رابط لم تنجح الاستجابة له أثناء الفحص")

    if not issues:
        return ("لم يرصد الفحص فجوات جوهرية في العناصر المدققة: العناوين والأوصاف ووسوم الصور "
                "وتغطية خريطة الموقع ضمن المعايير الموصى بها. يوصى بمتابعة دورية للحفاظ على "
                "هذا المستوى ومراجعة المحتوى عند إضافة منتجات أو أقسام جديدة.")

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


def generate_client_pdf(domain, score, stats):
    if not FONT_PATH.exists():
        raise FileNotFoundError(f"ملف الخط غير موجود: {FONT_PATH}")

    clean_domain = urlparse(domain).netloc or domain
    logo_exists = LOGO_PATH.exists()

    class PDFReport(FPDF):
        def header(self):
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
        if pdf.get_y() + (len(rows) + 3) * 6.5 > 270:
            pdf.add_page()
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

    draw_table("1. جدول تدقيق بنية الصفحات والعناوين:", [
        ("إجمالي عدد الصفحات المفحوصة في المتجر", f"{stats['total_pages']} صفحة"),
        ("صفحات المنتجات المكتشفة", f"{stats['products']} منتج"),
        ("صفحات الأقسام والكولكشنات", f"{stats['categories']} تصنيف"),
        ("مقالات وصفحات المدونة", f"{stats.get('blog_pages', 0)} مقال"),
        ("الصفحات التعريفية والسياسات", f"{stats['info_pages']} صفحة"),
        ("روابط تعذر الوصول إليها أثناء الفحص", f"{stats.get('broken_pages', 0)} رابط"),
        ("عناوين الميتا المفقودة أو غير المتوافقة", f"{stats['bad_titles']} عنوان"),
        ("أوصاف الميتا المفقودة أو غير المهيأة", f"{stats['bad_descs']} وصف"),
    ])

    total_imgs = stats.get('total_images', 0)
    missing_alts = stats.get('missing_alts', 0)
    alt_ratio = round((missing_alts / total_imgs * 100), 1) if total_imgs > 0 else 0
    if total_imgs == 0:
        img_state = "لم يرصد الفحص صور محتوى"
    elif missing_alts == 0:
        img_state = "مكتمل"
    elif alt_ratio > 50:
        img_state = "فجوة واسعة"
    else:
        img_state = "فجوة جزئية"

    draw_table("2. جدول تدقيق وسوم وصور المتجر:", [
        ("إجمالي صور المحتوى والمنتجات المفحوصة", f"{total_imgs} صورة"),
        ("صور تفتقر لوسم النص البديل لمحركات البحث", f"{missing_alts} صورة"),
        ("نسبة الصور غير المهيأة لمحركات البحث", f"{alt_ratio}%"),
        ("حالة تهيئة الصور للظهور في بحث صور جوجل", img_state),
    ])

    if stats.get('coverage_enabled'):
        draw_table("3. جدول تدقيق تغطية خريطة الموقع:", [
            ("منتجات معروضة في واجهة المتجر", f"{stats.get('catalog_count', 0)} منتج"),
            ("منتجات معلنة في خريطة الموقع", f"{stats.get('sitemap_count', 0)} منتج"),
            ("منتجات معروضة ولا تظهر في الخريطة", f"{stats.get('missing_from_sitemap_count', 0)} منتج"),
            ("روابط في الخريطة غير معروضة في المتجر", f"{stats.get('not_in_catalog_count', 0)} رابط"),
            ("نسبة تغطية خريطة الموقع", f"{stats.get('coverage_pct', 0)}%"),
        ])
        diag_no = "4"
    else:
        diag_no = "3"

    box_width = 180
    box_x = (210 - box_width) / 2
    pdf.set_x(box_x)
    pdf.set_font("Amiri", "", 12)
    pdf.set_text_color(15, 23, 42)
    pdf.cell(box_width, 6, ar(f"{diag_no}. التشخيص الاستشاري وخطة العمل:"), ln=True, align="R")
    pdf.ln(1)

    diag_text = build_diagnosis(score, stats)
    pdf.set_font("Amiri", "", 9)
    max_w = box_width - 10
    lines, current = [], ""
    for word in diag_text.split():
        trial = (current + " " + word).strip()
        if pdf.get_string_width(ar(trial)) <= max_w:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)

    line_h = 4.8
    box_h = len(lines) * line_h + 6
    if pdf.get_y() + box_h > 265:
        pdf.add_page()
    box_y = pdf.get_y()
    pdf.set_fill_color(248, 250, 252)
    pdf.set_draw_color(226, 232, 240)
    pdf.rect(box_x, box_y, box_width, box_h, 'DF')
    pdf.set_xy(box_x + 5, box_y + 3)
    pdf.set_text_color(71, 85, 105)
    for line in lines:
        pdf.set_x(box_x + 5)
        pdf.cell(max_w, line_h, ar(line), ln=True, align="R")

    return bytes(pdf.output())


# ==============================================================
#  حزمة الملفات والملخص
# ==============================================================
def build_zip(df, images_df, coverage=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for ptype, fname in [
            ('صفحة منتج', "1_المنتجات_products.csv"),
            ('صفحة تصنيف', "2_التصنيفات_categories.csv"),
            ('صفحة مدونة', "3_المدونة_blog.csv"),
            ('صفحة تعريفية', "4_الصفحات_التعريفية_pages.csv"),
            ('صفحة رئيسية', "5_الصفحة_الرئيسية_homepage.csv"),
            ('غير مصنفة', "6_غير_مصنفة_unclassified.csv"),
            ('صفحة غير متاحة', "7_روابط_معطلة_errors.csv"),
        ]:
            sub = df[df['نوع الصفحة'] == ptype]
            if not sub.empty:
                z.writestr(fname, sub.to_csv(index=False, encoding='utf-8-sig'))

        if images_df is not None and not images_df.empty:
            z.writestr("8_تفاصيل_صور_المتجر_images_audit.csv",
                       images_df.to_csv(index=False, encoding='utf-8-sig'))

        if coverage:
            if coverage.get('missing_from_sitemap'):
                z.writestr("9_منتجات_غير_مدرجة_في_الخريطة.csv",
                           pd.DataFrame({'رابط المنتج': coverage['missing_from_sitemap']})
                           .to_csv(index=False, encoding='utf-8-sig'))
            if coverage.get('not_in_catalog'):
                z.writestr("10_روابط_في_الخريطة_غير_معروضة.csv",
                           pd.DataFrame({'الرابط': coverage['not_in_catalog']})
                           .to_csv(index=False, encoding='utf-8-sig'))

        xbuf = io.BytesIO()
        with pd.ExcelWriter(xbuf, engine='openpyxl') as w:
            df.to_excel(w, index=False, sheet_name='SEO Pages Audit')
            if images_df is not None and not images_df.empty:
                images_df.to_excel(w, index=False, sheet_name='Images Alt Audit')
        z.writestr("التقرير_الشامل_all_pages_and_images.xlsx", xbuf.getvalue())
    return buf.getvalue()


def compute_summary(df, coverage=None):
    ok = df[df['متاحة'] == True]  # noqa: E712
    s = {
        'total_pages': len(df),
        'score': round(ok['درجة السيو'].mean(), 1) if not ok.empty else 0.0,
        'products': int((df['نوع الصفحة'] == 'صفحة منتج').sum()),
        'categories': int((df['نوع الصفحة'] == 'صفحة تصنيف').sum()),
        'info_pages': int((df['نوع الصفحة'] == 'صفحة تعريفية').sum()),
        'blog_pages': int((df['نوع الصفحة'] == 'صفحة مدونة').sum()),
        'unclassified': int((df['نوع الصفحة'] == 'غير مصنفة').sum()),
        'broken_pages': int((df['متاحة'] == False).sum()),  # noqa: E712
        'bad_titles': int((ok['حالة العنوان'] != 'سليم').sum()),
        'bad_descs': int((ok['حالة الوصف'] != 'سليم').sum()),
        'missing_alts': int(ok['صور بدون Alt'].sum()),
        'total_images': int(ok['إجمالي الصور'].sum()),
        'coverage_enabled': bool(coverage),
    }
    if coverage:
        s.update({
            'sitemap_count': coverage['sitemap_count'],
            'catalog_count': coverage['catalog_count'],
            'missing_from_sitemap_count': len(coverage['missing_from_sitemap']),
            'not_in_catalog_count': len(coverage['not_in_catalog']),
            'coverage_pct': coverage['coverage_pct'],
        })
    return s


# ==============================================================
#  الواجهة
# ==============================================================
st.sidebar.title("🧭 القائمة الرئيسية")
nav = st.sidebar.radio("اختر الوجهة:", ["🔍 فحص متجر جديد", "📁 سجل المتاجر السابقة"])

if nav == "🔍 فحص متجر جديد":
    st.title("🚀 مركز عمليات السيو الشامل للمتاجر")
    st.write("فحص وتدقيق كامل لأقسام ومنتجات ومدونة وسياسات وصور المتجر، "
             "مع التحقق من تغطية خريطة الموقع.")

    c_url, c_btn = st.columns([4, 1])
    with c_url:
        input_url = st.text_input("أدخل رابط المتجر الإلكتروني:",
                                  value=st.session_state.current_url,
                                  placeholder="https://midhal-oud.store")
    with c_btn:
        st.write("")
        st.write("")
        start_btn = st.button("🔍 بدء الفحص")

    with st.sidebar.expander("⚙️ إعدادات الفحص", expanded=False):
        max_pages = st.number_input("الحد الأقصى للصفحات:", 50, 5000, MAX_PAGES_DEFAULT, 50)
        workers = st.slider("عدد المسارات المتوازية:", 1, 8, 4)
        do_coverage = st.checkbox("التحقق من تغطية خريطة الموقع", value=True,
                                  help="يزحف على صفحات الأقسام لاكتشاف المنتجات المعروضة "
                                       "فعلياً ومقارنتها بخريطة الموقع. يطيل مدة الفحص.")
        audit_missing = st.checkbox("فحص المنتجات المكتشفة خارج الخريطة", value=True)

    if st.session_state.audit_df is not None:
        if st.sidebar.button("🔄 فحص متجر جديد (تفريغ الشاشة)"):
            for k in ['audit_df', 'images_df', 'summary', 'pdf_bytes', 'zip_bytes', 'coverage']:
                st.session_state[k] = None
            st.session_state.current_url = ""
            st.rerun()

    if start_btn and input_url:
        target = normalize_url(input_url)
        st.session_state.current_url = target

        with st.spinner("استخراج الروابط من robots.txt وخرائط الموقع وروابط الفوتر..."):
            urls, truncated, total_found = get_all_store_urls(target, max_pages)
        if truncated:
            st.warning(f"عُثر على {total_found} رابط، وسيقتصر الفحص على {max_pages} رابط.")

        st.info(f"المرحلة 1: فحص {len(urls)} صفحة من خريطة الموقع...")
        bar1 = st.progress(0)
        pages, imgs = run_audit([(u, 'خريطة الموقع') for u in urls], target, workers, bar1)

        df = pd.DataFrame(pages)
        images_df = pd.DataFrame(imgs)

        df = df.drop_duplicates(subset=['الرابط']).copy()
        avail = df[df['متاحة'] == True]  # noqa: E712
        dups = set(avail[avail.duplicated(subset=['الرابط الكانوني'], keep='first')]['الرابط'])
        df = df[~df['الرابط'].isin(dups)].copy().reset_index(drop=True)

        coverage = None
        if do_coverage:
            st.info("المرحلة 2: الزحف على صفحات الأقسام للتحقق من التغطية...")
            cat_urls = df[df['نوع الصفحة'] == 'صفحة تصنيف']['الرابط'].tolist()
            bar2 = st.progress(0)
            status2 = st.empty()

            def cb(pct, found_n, fetched_n):
                bar2.progress(min(pct, 1.0))
                status2.caption(f"تم جلب {fetched_n} صفحة قسم واكتشاف {found_n} رابط منتج.")

            catalog_products, fetched = crawl_catalog_for_products(target, cat_urls, cb)
            sitemap_products = set(df[df['نوع الصفحة'] == 'صفحة منتج']['الرابط'])
            coverage = build_coverage_report(sitemap_products, catalog_products)

            known = set(df['الرابط'])
            new_products = [u for u in coverage['missing_from_sitemap'] if u not in known]
            if audit_missing and new_products:
                st.info(f"المرحلة 3: فحص {len(new_products)} منتج مكتشف خارج خريطة الموقع...")
                bar3 = st.progress(0)
                extra_pages, extra_imgs = run_audit(
                    [(u, 'الزحف على الأقسام') for u in new_products], target, workers, bar3)
                df = pd.concat([df, pd.DataFrame(extra_pages)], ignore_index=True)
                if extra_imgs:
                    images_df = pd.concat([images_df, pd.DataFrame(extra_imgs)], ignore_index=True)
                df = df.drop_duplicates(subset=['الرابط']).reset_index(drop=True)

        if not images_df.empty:
            images_df = images_df[images_df['رابط الصفحة'].isin(df['الرابط'])] \
                .copy().reset_index(drop=True)

        summary = compute_summary(df, coverage)

        st.session_state.audit_df = df
        st.session_state.images_df = images_df
        st.session_state.summary = summary
        st.session_state.coverage = coverage
        st.session_state.zip_bytes = build_zip(df, images_df, coverage)
        try:
            st.session_state.pdf_bytes = generate_client_pdf(target, summary['score'], summary)
        except Exception as e:
            st.session_state.pdf_bytes = None
            st.error(f"تعذر توليد الـ PDF: {e}")

        conn = sqlite3.connect(DB_FILE)
        conn.cursor().execute(
            '''INSERT INTO audits (domain, scan_date, score, total_pages, products_count,
               categories_count, info_pages_count, blog_pages_count, data_json,
               images_json, coverage_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
            (target, datetime.now().strftime("%Y-%m-%d %H:%M"), summary['score'],
             summary['total_pages'], summary['products'], summary['categories'],
             summary['info_pages'], summary['blog_pages'], df.to_json(orient='records'),
             images_df.to_json(orient='records') if not images_df.empty else '',
             json.dumps(coverage, ensure_ascii=False) if coverage else ''))
        conn.commit()
        conn.close()

    if st.session_state.audit_df is not None:
        df = st.session_state.audit_df
        images_df = st.session_state.images_df
        summary = st.session_state.summary
        coverage = st.session_state.coverage

        st.success(f"اكتمل الفحص: {st.session_state.current_url}")

        cols = st.columns(7)
        for col, (val, lbl) in zip(cols, [
            (summary["total_pages"], "إجمالي الصفحات"),
            (f'{summary["score"]}%', "نسبة التوافق"),
            (summary["products"], "المنتجات"),
            (summary["categories"], "الأقسام"),
            (summary["blog_pages"], "المدونة"),
            (summary["info_pages"], "التعريفية"),
            (summary.get("broken_pages", 0), "روابط معطلة"),
        ]):
            with col:
                st.markdown(f'<div class="metric-card"><div class="metric-value">{val}</div>'
                            f'<div class="metric-label">{lbl}</div></div>', unsafe_allow_html=True)

        tabs = st.tabs(["📄 الصفحات", "🖼️ الصور", "🎯 تغطية الخريطة", "🔬 التحقق اليدوي"])

        with tabs[0]:
            types_avail = ["جميع الصفحات"] + [t for t in PAGE_TYPES if (df['نوع الصفحة'] == t).any()]
            sel = st.selectbox("نوع الصفحة:", types_avail)
            d = df if sel == "جميع الصفحات" else df[df['نوع الصفحة'] == sel]
            d = d.copy().reset_index(drop=True)
            d.index = d.index + 1
            st.dataframe(d, use_container_width=True)
            if summary.get('unclassified', 0) > 0:
                st.caption(f"{summary['unclassified']} صفحة غير مصنفة آلياً تحتاج مراجعة يدوية.")

        with tabs[1]:
            if images_df is not None and not images_df.empty:
                f = st.selectbox("تصفية:", ["جميع الصور", "بدون Alt فقط", "سليمة فقط"])
                v = images_df
                if f == "بدون Alt فقط":
                    v = images_df[images_df['حالة النص البديل'] == 'مفقود']
                elif f == "سليمة فقط":
                    v = images_df[images_df['حالة النص البديل'] == 'سليم ومكتمل']
                v = v.copy().reset_index(drop=True)
                v.index = v.index + 1
                st.dataframe(v, use_container_width=True)
            else:
                st.info("لا توجد صور محتوى مرصودة.")

        with tabs[2]:
            if not coverage:
                st.info("لم يُفعَّل التحقق من التغطية في هذا الفحص. "
                        "فعّله من الإعدادات الجانبية وأعد الفحص.")
            else:
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("معروضة في المتجر", coverage['catalog_count'])
                c2.metric("معلنة في الخريطة", coverage['sitemap_count'])
                c3.metric("مفقودة من الخريطة", len(coverage['missing_from_sitemap']))
                c4.metric("نسبة التغطية", f"{coverage['coverage_pct']}%")

                if coverage['missing_from_sitemap']:
                    st.error(f"{len(coverage['missing_from_sitemap'])} منتج معروض في المتجر "
                             "ولا يظهر في خريطة الموقع — محركات البحث قد لا تعلم بوجوده.")
                    st.dataframe(pd.DataFrame({'رابط المنتج': coverage['missing_from_sitemap']}),
                                 use_container_width=True)
                else:
                    st.success("جميع المنتجات المعروضة مدرجة في خريطة الموقع.")

                if coverage['not_in_catalog']:
                    st.warning(f"{len(coverage['not_in_catalog'])} رابط موجود في خريطة الموقع "
                               "ولم يظهر في أي صفحة قسم — قد تكون منتجات مخفية أو محذوفة أو "
                               "غير مرتبطة بأي تصنيف.")
                    st.dataframe(pd.DataFrame({'الرابط': coverage['not_in_catalog']}),
                                 use_container_width=True)

                st.caption("ملاحظة: الزحف يعتمد على ترقيم الصفحات بصيغة ?page=N. "
                           "المتاجر التي تحمّل المنتجات بالتمرير اللانهائي قد لا تُغطى بالكامل.")

        with tabs[3]:
            st.subheader("🔬 عيّنة للتحقق اليدوي")
            st.write("افتح كل رابط في المتصفح وقارن العنوان والوصف بما هو مسجّل هنا. "
                     "إن تطابقت العيّنة كاملة، فمحرك القراءة يعمل بشكل صحيح.")
            ok_pages = df[(df['متاحة'] == True) & (df['نوع الصفحة'] == 'صفحة منتج')]  # noqa: E712
            if ok_pages.empty:
                ok_pages = df[df['متاحة'] == True]  # noqa: E712
            if ok_pages.empty:
                st.info("لا توجد صفحات متاحة للتحقق.")
            else:
                n = min(5, len(ok_pages))
                sample = ok_pages.sample(n=n, random_state=int(time.time()) % 1000)
                for _, row in sample.iterrows():
                    with st.container(border=True):
                        st.markdown(f"**الرابط:** [{row['الرابط']}]({row['الرابط']})")
                        st.write(f"العنوان المقروء ({len(str(row['عنوان الميتا']))} حرف): "
                                 f"{row['عنوان الميتا'] or '— مفقود —'}")
                        st.write(f"الوصف المقروء ({len(str(row['وصف الميتا']))} حرف): "
                                 f"{row['وصف الميتا'] or '— مفقود —'}")
                        st.write(f"صور مرصودة: {row['إجمالي الصور']} | "
                                 f"بدون Alt: {row['صور بدون Alt']} | "
                                 f"كلمات: {row['عدد الكلمات']}")
                st.caption("إن ظهرت الصور بصفر والصفحة تحتوي صورًا فعلية، "
                           "فالمتجر يبني المحتوى بـ JavaScript ويحتاج معالجة مختلفة.")

        st.subheader("📥 التحميل والتصدير")
        netloc = urlparse(st.session_state.current_url).netloc or "store"
        d1, d2 = st.columns(2)
        with d1:
            if st.session_state.pdf_bytes:
                st.download_button("📄 تقرير العميل (PDF)", st.session_state.pdf_bytes,
                                   f"SEO_Audit_{netloc}.pdf", "application/pdf")
            else:
                st.info("تقرير الـ PDF غير متاح.")
        with d2:
            if st.session_state.zip_bytes:
                st.download_button("📦 حزمة البيانات (ZIP)", st.session_state.zip_bytes,
                                   f"Data_Package_{netloc}.zip", "application/zip")

elif nav == "📁 سجل المتاجر السابقة":
    st.title("📁 سجل المتاجر المفحوصة")
    st.caption("تنبيه: قاعدة البيانات محلية وقد تُفقد عند إعادة نشر التطبيق على Streamlit Cloud.")

    conn = sqlite3.connect(DB_FILE)
    hist = pd.read_sql_query(
        "SELECT id, domain as 'المتجر', scan_date as 'تاريخ الفحص', score as 'النسبة', "
        "total_pages as 'الصفحات', products_count as 'المنتجات', categories_count as 'الأقسام', "
        "blog_pages_count as 'المدونة', info_pages_count as 'التعريفية' "
        "FROM audits ORDER BY id DESC", conn)
    conn.close()

    if hist.empty:
        st.info("لا توجد متاجر مفحوصة بعد.")
    else:
        st.dataframe(hist.drop(columns=['id']), use_container_width=True)
        sel_id = st.selectbox("اختر المتجر:", hist['id'].tolist(),
                              format_func=lambda x: f"{hist[hist['id']==x]['المتجر'].values[0]} "
                                                    f"({hist[hist['id']==x]['تاريخ الفحص'].values[0]})")
        if st.button("📥 استرجاع البيانات"):
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute("SELECT domain, data_json, images_json, coverage_json, score "
                      "FROM audits WHERE id = ?", (sel_id,))
            row = c.fetchone()
            conn.close()
            if row:
                rdf = pd.read_json(io.StringIO(row[1]))
                rimg = pd.read_json(io.StringIO(row[2])) if row[2] else pd.DataFrame()
                rcov = json.loads(row[3]) if row[3] else None
                if 'متاحة' not in rdf.columns:
                    rdf['متاحة'] = True
                st.session_state.current_url = row[0]
                st.session_state.audit_df = rdf
                st.session_state.images_df = rimg
                st.session_state.coverage = rcov
                st.session_state.summary = compute_summary(rdf, rcov)
                st.session_state.zip_bytes = build_zip(rdf, rimg, rcov)
                try:
                    st.session_state.pdf_bytes = generate_client_pdf(
                        row[0], row[4], st.session_state.summary)
                except Exception as e:
                    st.session_state.pdf_bytes = None
                    st.error(f"تعذر توليد الـ PDF: {e}")
                st.success("تم الاسترجاع. انتقل إلى (فحص متجر جديد) لعرض النتائج والتحميل.")
