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
from functools import lru_cache
import sqlite3
import threading
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse, urljoin, unquote
from concurrent.futures import ThreadPoolExecutor
from fpdf import FPDF
import arabic_reshaper
from bidi.algorithm import get_display

# ==============================================================
#  مركز فحص وعمليات السيو الشامل للمتاجر الإلكترونية
#  أنس راشد — anasrashed.com
# ==============================================================

st.set_page_config(
    page_title="مركز عمليات السيو | أنس راشد",
    layout="wide",
    page_icon="🚀",
    initial_sidebar_state="expanded"
)

BASE_DIR = Path(__file__).parent
FONT_CANDIDATES = [
    ("Tajawal", "Tajawal-Regular.ttf", "Tajawal-Bold.ttf"),
    ("Almarai", "Almarai-Regular.ttf", "Almarai-Bold.ttf"),
    ("Cairo", "Cairo-Regular.ttf", "Cairo-Bold.ttf"),
    ("IBMPlexArabic", "IBMPlexSansArabic-Regular.ttf", "IBMPlexSansArabic-Bold.ttf"),
    ("NotoKufi", "NotoKufiArabic-Regular.ttf", "NotoKufiArabic-Bold.ttf"),
    ("Amiri", "Amiri-Regular.ttf", "Amiri-Bold.ttf"),
]

def pick_font():
    for name, reg, bold in FONT_CANDIDATES:
        rp = BASE_DIR / reg
        if rp.exists() and rp.stat().st_size > 10000:
            bp = BASE_DIR / bold
            has_b = bp.exists() and bp.stat().st_size > 10000
            return name, rp, (bp if has_b else rp)
    amiri = BASE_DIR / "Amiri-Regular.ttf"
    if amiri.exists():
        return "Amiri", amiri, amiri
    return "Helvetica", None, None

AR_FONT_NAME, FONT_PATH, FONT_BOLD_PATH = pick_font()

LOGO_PATH = BASE_DIR / "brand_logo.png"
RIYAL_PATH = BASE_DIR / "Saudi_Riyal_Symbol-1.png"
DB_FILE = str(BASE_DIR / "store_history.db")

try:
    import lxml  # noqa: F401
    PARSER = "lxml"
except Exception:
    PARSER = "html.parser"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept-Language': 'ar,en;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
}

T_HOME, T_PRODUCT, T_CATEGORY = 'home', 'product', 'category'
T_BLOG, T_INFO, T_UNKNOWN, T_BROKEN = 'blog', 'info', 'unknown', 'broken'
PAGE_TYPE_ORDER = [T_HOME, T_PRODUCT, T_CATEGORY, T_BLOG, T_INFO, T_UNKNOWN, T_BROKEN]

PAGE_TYPE_LABEL = {
    'ar': {T_HOME: 'صفحة رئيسية', T_PRODUCT: 'صفحة منتج', T_CATEGORY: 'صفحة تصنيف',
           T_BLOG: 'صفحة مدونة', T_INFO: 'صفحة تعريفية', T_UNKNOWN: 'غير مصنفة', T_BROKEN: 'صفحة معطلة'},
    'en': {T_HOME: 'Homepage', T_PRODUCT: 'Product', T_CATEGORY: 'Category',
           T_BLOG: 'Blog', T_INFO: 'Info / Policy', T_UNKNOWN: 'Unclassified', T_BROKEN: 'Broken'},
}

STATUS_LABEL = {
    'ar': {
        'missing': 'مفقود', 'very_short': 'قصير جداً', 'acceptable': 'مقبول',
        'optimal': 'مثالي', 'long': 'طويل', 'failed': 'تعذر الفحص',
        'good': 'جيد', 'thin': 'ضعيف جداً', 'na': 'غير متاح',
        'alt_missing': 'مفقود', 'alt_generic': 'غير وصفي', 'alt_stuffed': 'حشو كلمات',
        'alt_long': 'يتجاوز 125 حرفاً', 'alt_duplicate': 'مكرر على عدة صور',
        'alt_ok': 'سليم', 'alt_empty': 'لا يوجد (فارغ)',
        'canon_same': 'مطابق', 'canon_diff': 'مختلف عن رابط الصفحة', 'canon_missing': 'مفقود',
        'match_ok': 'متطابق', 'match_diff': 'مختلف عن اسم المنتج', 'match_empty': 'غير متوفر',
    }
}

TITLE_MAX, TITLE_MIN_OPTIMAL, TITLE_MIN_OK = 60, 50, 30
DESC_MAX, DESC_MIN_OPTIMAL, DESC_MIN_OK = 150, 120, 70
ALT_MAX = 125
ALT_DUP_THRESHOLD = 3

COLOR = {'ok': '#059669', 'warn': '#d97706', 'bad': '#dc2626', 'neutral': '#475569',
         'accent': '#0f172a', 'muted': '#94a3b8'}

# ==============================================================
#  قاعدة البيانات
# ==============================================================
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS audits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        domain TEXT, scan_date TEXT, score REAL, total_pages INTEGER,
        products_count INTEGER, categories_count INTEGER, info_pages_count INTEGER,
        blog_pages_count INTEGER, data_json TEXT, images_json TEXT,
        coverage_json TEXT, platform TEXT
    )''')
    conn.commit()
    conn.close()

init_db()

for key, default in [('audit_df', None), ('images_df', None), ('summary', None),
                     ('current_url', ""), ('coverage', None), ('platform', 'unknown'),
                     ('dup_titles', None), ('dup_descs', None)]:
    if key not in st.session_state:
        st.session_state[key] = default

# ==============================================================
#  التنسيق العام للواجهة
# ==============================================================
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Tajawal:wght@400;500;700&display=swap');
html, body, [class*="css"] { font-family:'Tajawal','Segoe UI',Tahoma,sans-serif; }
.main .block-container { direction:rtl; text-align:right; padding-top:1.2rem; max-width:1500px; }
h1,h2,h3,h4,h5,p,span,div,label { text-align:right; }
section[data-testid="stSidebar"] { direction:rtl; text-align:right; background:#0f172a; }
section[data-testid="stSidebar"] * { color:#e2e8f0 !important; }
.brandbar { display:flex; align-items:center; justify-content:space-between; border-bottom:2px solid #0f172a; padding:0 0 14px 0; margin-bottom:22px; }
.brandbar .name { font-size:24px; font-weight:700; color:#0f172a; line-height:1.2; }
.brandbar .role { font-size:13px; color:#64748b; }
.brandbar .tool { font-size:13px; color:#64748b; text-align:left; }
.hero { border:1px solid #e2e8f0; border-radius:14px; padding:22px 26px; background:#f8fafc; display:flex; align-items:center; justify-content:space-between; margin-bottom:18px; }
.hero .score { font-size:46px; font-weight:700; line-height:1; }
.hero .scorelbl { font-size:13px; color:#64748b; margin-top:6px; }
.hero .store { font-size:17px; font-weight:500; color:#0f172a; text-align:left; }
.hero .plat { font-size:12px; color:#64748b; text-align:left; margin-top:4px; }
.mcard { border:1px solid #e2e8f0; border-radius:12px; padding:14px 10px; text-align:center; background:#fff; height:100%; }
.mcard .v { font-size:26px; font-weight:700; line-height:1.1; }
.mcard .l { font-size:12px; color:#64748b; margin-top:4px; }
.chart-card { border:1px solid #e2e8f0; border-radius:12px; padding:16px 18px; background:#fff; margin-bottom:14px; }
.chart-title { font-size:14px; font-weight:700; color:#0f172a; margin-bottom:12px; }
.bar-row { display:flex; align-items:center; gap:10px; margin-bottom:7px; }
.bar-label { flex:0 0 160px; font-size:12.5px; color:#334155; }
.bar-track { flex:1; height:9px; background:#f1f5f9; border-radius:5px; overflow:hidden; }
.bar-fill { height:100%; border-radius:5px; }
.bar-value { flex:0 0 46px; font-size:12px; color:#475569; text-align:left; }
.finding { border-right:4px solid; border-radius:8px; padding:11px 14px; margin-bottom:9px; background:#fff; border-top:1px solid #e2e8f0; border-bottom:1px solid #e2e8f0; border-left:1px solid #e2e8f0; font-size:13.5px; color:#334155; }
.finding b { color:#0f172a; }
.stTabs [data-baseweb="tab-list"] { gap:4px; direction:rtl; }
.stTabs [data-baseweb="tab"] { font-size:14px; font-weight:500; padding:8px 16px; }
div[data-testid="stDataFrame"] { direction:ltr; }
</style>
""", unsafe_allow_html=True)

def render_brandbar():
    st.markdown(
        f'<div class="brandbar">'
        f'<div><div class="name">أنس راشد</div>'
        f'<div class="role">خبير تحسين محركات البحث للمتاجر الإلكترونية</div></div>'
        f'<div style="display:flex;align-items:center;gap:18px">'
        f'<div class="tool">مركز عمليات السيو<br>anasrashed.com</div></div></div>',
        unsafe_allow_html=True)

def metric_card(value, label, color=COLOR['accent']):
    return (f'<div class="mcard"><div class="v" style="color:{color}">{value}</div>'
            f'<div class="l">{label}</div></div>')

def bar_chart(title, items, colors=None):
    total = sum(v for _, v in items) or 1
    rows = ""
    for label, val in items:
        pct = val / total * 100
        c = (colors or {}).get(label, COLOR['neutral'])
        rows += (f'<div class="bar-row"><div class="bar-label">{label}</div>'
                 f'<div class="bar-track"><div class="bar-fill" '
                 f'style="width:{pct:.1f}%;background:{c}"></div></div>'
                 f'<div class="bar-value">{val}</div></div>')
    return f'<div class="chart-card"><div class="chart-title">{title}</div>{rows}</div>'

def finding(text, level='warn'):
    return f'<div class="finding" style="border-right-color:{COLOR[level]}">{text}</div>'

# ==============================================================
#  أدوات الاتصال ومعالجة الروابط
# ==============================================================
_TL = threading.local()

def _session():
    sess = getattr(_TL, 'sess', None)
    if sess is None:
        sess = requests.Session()
        adapter = requests.adapters.HTTPAdapter(pool_connections=10, pool_maxsize=20, max_retries=1)
        sess.mount('https://', adapter)
        sess.mount('http://', adapter)
        sess.headers.update(HEADERS)
        _TL.sess = sess
    return sess

def safe_get(url, timeout=12, retries=2):
    for attempt in range(retries + 1):
        try:
            res = _session().get(url, timeout=timeout, allow_redirects=True)
            if res.status_code == 429:
                time.sleep(2.5 * (attempt + 1))
                continue
            return res
        except Exception:
            time.sleep(1)
    return None

def normalize_domain(netloc):
    netloc = netloc.lower().split(':')[0]
    if netloc.startswith('www.'):
        return netloc[4:]
    return netloc

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

PLATFORM_ID_RE = re.compile(r'^(p|c|a|page|tag|category|product)-?(\d{4,})$', re.I)

@lru_cache(maxsize=50000)
def url_key(url):
    if not url:
        return ""
    p = urlparse(clean_url(url))
    path = unquote(p.path).rstrip('/')
    host = normalize_domain(p.netloc)
    segs = [x for x in path.split('/') if x]
    if segs:
        mo = PLATFORM_ID_RE.match(segs[-1])
        if mo:
            return f"{host}/#{mo.group(1).lower()}{mo.group(2)}"
    return f"{host}{path}"

def make_soup(markup):
    return BeautifulSoup(markup, PARSER)

EXCLUDE_PATH_PARTS = [
    '/cart', '/checkout', '/login', '/signin', '/register', '/signup', '/account',
    '/my-account', '/wishlist', '/favorites', '/compare', '/search', '/orders',
    '/customer', '/password', '/thank-you', '/logout', '/cdn-cgi/', '/email-protection',
    '/سلة', '/حسابي', '/تسجيل', '/الدفع', '/بحث', '/المفضلة'
]
BAD_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.gif', '.svg', '.webp', '.avif', '.pdf',
                  '.zip', '.rar', '.xml', '.css', '.js', '.ico', '.mp4', '.mp3')

def is_crawlable(url, base_netloc):
    if not url:
        return False
    p = urlparse(url)
    if p.scheme not in ('http', 'https'):
        return False
    if normalize_domain(p.netloc) != normalize_domain(base_netloc):
        return False
    path = unquote(p.path.lower())
    if path.endswith(BAD_EXTENSIONS):
        return False
    if any(part in path for part in EXCLUDE_PATH_PARTS):
        return False
    return True

# ==============================================================
#  كشف المنصات والأنواع
# ==============================================================
PLATFORM_LABEL = {'salla': 'سلة (Salla)', 'zid': 'زد (Zid)',
                  'shopify': 'شوبيفاي (Shopify)', 'woocommerce': 'ووكومرس', 'unknown': 'غير محددة'}

def detect_platform(html, headers=None, url=""):
    blob = (html or "")[:100000].lower() + " " + (url or "").lower()
    if any(s in blob for s in ['salla.sa', 'cdn.salla.network', 'window.salla', 'salla-']):
        return 'salla'
    if any(s in blob for s in ['zid.store', 'media.zid.sa', 'zidapi', 'x-zid', 'cdn.zid']):
        return 'zid'
    if any(s in blob for s in ['cdn.shopify.com', 'myshopify.com', 'shopify.theme']):
        return 'shopify'
    if 'woocommerce' in blob or 'wp-content' in blob:
        return 'woocommerce'
    return 'unknown'

POLICY_KEYWORDS = [
    'سياسة', 'شروط', 'خصوصية', 'استبدال', 'استرجاع', 'شحن', 'توصيل', 'شكاوى',
    'من-نحن', 'اتصل', 'ضمان', 'أحكام', 'الاستخدام', 'about', 'contact', 'terms', 'privacy'
]

def detect_page_type(url, base_url, soup=None):
    base_clean = normalize_url(base_url)
    url_clean = clean_url(url)
    if url_key(url_clean) == url_key(base_clean) or urlparse(url_clean).path in ('', '/'):
        return T_HOME

    path = unquote(urlparse(url_clean).path.lower()).strip('/')
    segs = [s for s in path.split('/') if s]

    og_type = ""
    if soup:
        tag = soup.find('meta', attrs={'property': 'og:type'})
        if tag and tag.get('content'):
            og_type = tag['content'].lower()

    if 'product' in og_type or re.search(r'/p\d+', url_clean) or any(re.match(r'^p\d+$', s) for s in segs):
        return T_PRODUCT
    if ('products' in segs or 'product' in segs) and len(segs) >= 2:
        return T_PRODUCT

    if any(k in path for k in POLICY_KEYWORDS):
        return T_INFO

    if 'article' in og_type or 'blog' in og_type or any(s in ('blog', 'blogs', 'articles', 'مدونة', 'مقالات') for s in segs):
        return T_BLOG

    if any(s in ('category', 'categories', 'collection', 'collections', 'قسم', 'أقسام', 'تصنيف') for s in segs):
        return T_CATEGORY
    if re.search(r'/c\d+', url_clean) or any(re.match(r'^c\d+$', s) for s in segs):
        return T_CATEGORY

    return T_UNKNOWN

# ==============================================================
#  فحص معايير السيو (العناوين، الرموز، الصور، H1)
# ==============================================================
PLACEHOLDER_PATTERNS = [
    r'^\s*\[\s*[\.\-_]*\s*\]\s*$',
    r'\{\{.*?\}\}', r'\{%.*?%\}',
    r'^\s*[-_–—|•·\.\s]+\s*$',
    r'\b(undefined|null|nan|none|untitled|default)\b'
]

def is_title_symbol_or_placeholder(title):
    if not title:
        return True
    t = title.strip()
    if not re.search(r'[0-9a-zA-Z\u0600-\u06FF]', t):
        return True
    return any(re.search(pat, t, re.I) for pat in PLACEHOLDER_PATTERNS)

def grade_length(length, min_ok, min_optimal, max_len):
    if length == 0:
        return 'missing'
    if length < min_ok:
        return 'very_short'
    if length < min_optimal:
        return 'acceptable'
    if length <= max_len:
        return 'optimal'
    return 'long'

GENERIC_ALTS = {
    'image', 'img', 'photo', 'picture', 'pic', 'icon', 'logo', 'product',
    'صورة', 'صوره', 'صور', 'منتج', 'شعار', 'غلاف', 'رئيسية', 'جديد'
}

def grade_alt(alt_text):
    txt = re.sub(r'\s+', ' ', str(alt_text or '')).strip()
    if not txt:
        return 'alt_missing', 0
    length = len(txt)
    low = txt.lower()

    if re.search(r'\.(jpg|jpeg|png|webp|gif|svg)$', low):
        return 'alt_generic', length
    if re.fullmatch(r'[\d\W_]+', txt):
        return 'alt_generic', length

    words = [w.strip('.,،؛:!?|-()[]') for w in low.split()]
    if not words or all(w in GENERIC_ALTS for w in words):
        return 'alt_generic', length
    if length > ALT_MAX:
        return 'alt_long', length

    commas = txt.count(',') + txt.count('،')
    if commas >= 4 and len(words) / max(commas, 1) < 3:
        return 'alt_stuffed', length

    return 'alt_ok', length

def check_title_h1_match(meta_title, h1_text):
    if not meta_title or not h1_text:
        return 'match_empty'
    t_clean = re.sub(r'[^\w\s\u0600-\u06FF]', '', meta_title.lower())
    h_clean = re.sub(r'[^\w\s\u0600-\u06FF]', '', h1_text.lower())
    h_words = set(h_clean.split())
    if not h_words:
        return 'match_empty'
    match_count = sum(1 for w in h_words if w in t_clean)
    ratio = match_count / len(h_words)
    return 'match_ok' if ratio >= 0.5 else 'match_diff'

def extract_image_src(img):
    for attr in ['data-src', 'data-original', 'data-lazy', 'data-lazy-src', 'data-image']:
        val = img.get(attr)
        if val and val.strip():
            return val.strip()
    return img.get('src', '').strip()

def is_product_content_image(src, img):
    if not src or src.startswith('data:image'):
        return False
    s = src.lower()
    if any(k in s for k in ['favicon', 'avatar', 'payment', 'tamara', 'tabby', 'mada', 'visa', 'mastercard', 'pixel', 'spinner', 'loader']):
        return False
    classes = ' '.join(img.get('class', [])).lower()
    if any(k in classes for k in ['logo', 'icon', 'badge', 'payment']):
        return False
    return True

# ==============================================================
#  استخراج الروابط لتجاوز التمرير ومكونات سلة
# ==============================================================
def extract_page_links(soup, page_url, base_netloc):
    links = set()
    for a in soup.find_all('a', href=True):
        href = a['href'].strip()
        if href.startswith(('mailto:', 'tel:', 'javascript:', '#')):
            continue
        full = clean_url(urljoin(page_url, href))
        if is_crawlable(full, base_netloc):
            links.add(full)

    # وسوم سلة
    for card in soup.find_all(['salla-product-card', 'div', 'article'], attrs={'data-url': True}):
        full = clean_url(urljoin(page_url, card['data-url']))
        if is_crawlable(full, base_netloc):
            links.add(full)

    # التمرير اللانهائي
    for el in soup.find_all(['salla-infinite-scroll', 'div'], attrs={'next-page': True}):
        next_p = el.get('next-page')
        if next_p:
            full = clean_url(urljoin(page_url, next_p))
            if is_crawlable(full, base_netloc):
                links.add(full)

    return links

# ==============================================================
#  فحص صفحة واحدة
# ==============================================================
def audit_single_page(task):
    url, base_url, source = task
    base_netloc = urlparse(normalize_url(base_url)).netloc
    res = safe_get(url)

    if res is None or res.status_code != 200:
        code = str(res.status_code) if res else 'فشل اتصال'
        return {
            'page_data': {
                'نوع الصفحة': T_BROKEN, 'الرابط': url, 'مصدر الاكتشاف': source,
                'متاحة': False, 'كود الاستجابة': code,
                'عنوان الميتا': '', 'طول العنوان': 0, 'حالة العنوان': 'failed',
                'عنوان الصفحة (H1)': '', 'مطابقة العنوان مع H1': 'match_empty',
                'وصف الميتا': '', 'طول الوصف': 0, 'حالة الوصف': 'failed',
                'إجمالي الصور': 0, 'صور بدون Alt': 0, 'صور Alt ضعيف': 0,
                'عدد الكلمات': 0, 'حالة المحتوى': 'na',
                'حالة الكانونيكال': 'canon_missing', 'الرابط الكانوني': '',
                'درجة السيو': 0
            },
            'images_data': [], 'links': set()
        }

    final_url = clean_url(res.url)
    soup = make_soup(res.text)
    page_type = detect_page_type(final_url, base_url, soup)

    links = extract_page_links(soup, final_url, base_netloc)

    canonical = ''
    for link in soup.find_all('link', href=True):
        rel = link.get('rel') or []
        if isinstance(rel, str):
            rel = [rel]
        if 'canonical' in [r.lower() for r in rel]:
            canonical = clean_url(urljoin(final_url, link['href']))
            break
    if not canonical:
        canon_status, canonical = 'canon_missing', final_url
    elif url_key(canonical) == url_key(final_url):
        canon_status = 'canon_same'
    else:
        canon_status = 'canon_diff'

    h1 = soup.find('h1')
    h1_text = re.sub(r'\s+', ' ', h1.get_text(strip=True)).strip() if h1 else ''

    title_tag = soup.find('title')
    meta_title = re.sub(r'\s+', ' ', title_tag.get_text(strip=True)).strip() if title_tag else ''
    title_len = len(meta_title)
    if is_title_symbol_or_placeholder(meta_title):
        title_status = 'missing'
    else:
        title_status = grade_length(title_len, TITLE_MIN_OK, TITLE_MIN_OPTIMAL, TITLE_MAX)

    match_status = check_title_h1_match(meta_title, h1_text)

    desc_tag = soup.find('meta', attrs={'name': re.compile(r'^description$', re.I)}) or \
               soup.find('meta', attrs={'property': 'og:description'})
    meta_desc = re.sub(r'\s+', ' ', desc_tag['content']).strip() if desc_tag and desc_tag.get('content') else ''
    desc_len = len(meta_desc)
    desc_status = grade_length(desc_len, DESC_MIN_OK, DESC_MIN_OPTIMAL, DESC_MAX)

    page_images = []
    total_img, missing_alt, weak_alt = 0, 0, 0
    for img in soup.find_all('img'):
        src = extract_image_src(img)
        if src and is_product_content_image(src, img):
            total_img += 1
            full_img_url = urljoin(final_url, src)
            alt_text = (img.get('alt') or '').strip()
            alt_st, alt_l = grade_alt(alt_text)
            if alt_st == 'alt_missing':
                missing_alt += 1
            elif alt_st in ('alt_generic', 'alt_stuffed', 'alt_long'):
                weak_alt += 1

            page_images.append({
                'رابط الصفحة': final_url, 'نوع الصفحة': page_type,
                'رابط الصورة': full_img_url,
                'النص البديل الحالي (Alt)': alt_text,
                'حالة النص البديل': alt_st,
                'طول النص البديل': alt_l
            })

    for s in soup(['script', 'style', 'nav', 'footer']):
        s.decompose()
    words = len(soup.get_text(separator=' ', strip=True).split())
    content_status = 'good' if words >= 40 else 'thin'

    score = 100
    if title_status == 'missing': score -= 30
    elif title_status in ('very_short', 'long'): score -= 15
    if desc_status == 'missing': score -= 25
    elif desc_status in ('very_short', 'long'): score -= 10
    if match_status == 'match_diff': score -= 15
    if missing_alt > 0: score -= min(20, missing_alt * 5)
    if content_status == 'thin': score -= 10

    return {
        'page_data': {
            'نوع الصفحة': page_type, 'الرابط': final_url, 'مصدر الاكتشاف': source,
            'متاحة': True, 'كود الاستجابة': '200',
            'عنوان الميتا': meta_title, 'طول العنوان': title_len, 'حالة العنوان': title_status,
            'عنوان الصفحة (H1)': h1_text, 'مطابقة العنوان مع H1': match_status,
            'وصف الميتا': meta_desc, 'طول الوصف': desc_len, 'حالة الوصف': desc_status,
            'إجمالي الصور': total_img, 'صور بدون Alt': missing_alt, 'صور Alt ضعيف': weak_alt,
            'عدد الكلمات': words, 'حالة المحتوى': content_status,
            'حالة الكانونيكال': canon_status, 'الرابط الكانوني': canonical,
            'درجة السيو': max(10, score)
        },
        'images_data': page_images,
        'links': links,
        'html': res.text[:20000] if page_type == T_HOME else ''
    }

# ==============================================================
#  قارئ خريطة الموقع (Sitemap)
# ==============================================================
LOC_RE = re.compile(r'<loc>\s*(.*?)\s*</loc>', re.I | re.S)

def fetch_sitemap_urls(base_url):
    base_clean = normalize_url(base_url)
    target_netloc = normalize_domain(urlparse(base_clean).netloc)
    found_urls = set()
    visited_maps = set()

    candidates = [
        f"{base_clean}/sitemap.xml",
        f"{base_clean}/sitemap_index.xml",
        f"{base_clean}/sitemap_products_1.xml",
        f"{base_clean}/sitemap_categories_1.xml",
        f"{base_clean}/sitemap_pages_1.xml",
    ]

    res_r = safe_get(f"{base_clean}/robots.txt", timeout=8, retries=1)
    if res_r and res_r.status_code == 200:
        for line in res_r.text.splitlines():
            if line.lower().strip().startswith('sitemap:'):
                sm = line.split(':', 1)[1].strip()
                if sm and sm not in candidates:
                    candidates.append(sm)

    def parse_map(sm_url):
        if sm_url in visited_maps or len(visited_maps) > 25:
            return
        visited_maps.add(sm_url)
        res = safe_get(sm_url, timeout=15, retries=1)
        if not res or res.status_code != 200:
            return
        content = res.content
        if sm_url.lower().endswith('.gz') or content[:2] == b'\x1f\x8b':
            try:
                content = gzip.decompress(content)
            except Exception:
                pass
        text = content.decode('utf-8', 'ignore')
        locs = LOC_RE.findall(text)
        for loc in locs:
            loc = loc.strip()
            clean_loc = loc.split('?')[0].lower()
            if clean_loc.endswith(('.xml', '.xml.gz')) or 'sitemap' in clean_loc:
                parse_map(loc)
            else:
                u_netloc = normalize_domain(urlparse(loc).netloc)
                if u_netloc == target_netloc:
                    found_urls.add(clean_url(loc))

    for c in candidates:
        parse_map(c)

    return found_urls

# ==============================================================
#  محرك الزحف الشامل بالنسبة المئوية
# ==============================================================
def run_full_audit(target_url, max_pages=1500, workers=4, progress_cb=None):
    target = normalize_url(target_url)

    if progress_cb:
        progress_cb(0.05, "جلب وفحص خريطة الموقع (Sitemap)... (5%)")

    sitemap_urls = fetch_sitemap_urls(target)

    queue = list(sitemap_urls) if sitemap_urls else []
    if target not in queue:
        queue.insert(0, target)

    seen = {url_key(u) for u in queue}
    pages_result = []
    images_result = []
    visited_keys = set()
    platform = 'unknown'

    done_count = 0

    while queue and len(pages_result) < max_pages:
        batch = queue[:workers * 2]
        queue = queue[workers * 2:]
        tasks = [(u, target, 'خريطة الموقع' if u in sitemap_urls else 'رابط داخلي') for u in batch]

        with ThreadPoolExecutor(max_workers=workers) as ex:
            results = list(ex.map(audit_single_page, tasks))

        for res in results:
            p_data = res['page_data']
            pages_result.append(p_data)
            images_result.extend(res['images_data'])
            visited_keys.add(url_key(p_data['الرابط']))

            if res.get('html') and platform == 'unknown':
                platform = detect_platform(res['html'], url=target)

            for link in res['links']:
                k = url_key(link)
                if k not in seen and len(seen) < max_pages * 2:
                    seen.add(k)
                    queue.append(link)

            done_count += 1
            if progress_cb:
                est_total = min(max_pages, max(done_count + len(queue), 1))
                pct = min(1.0, 0.05 + 0.95 * (done_count / est_total))
                pct_int = int(pct * 100)
                progress_cb(pct, f"جارٍ الفحص: {done_count} من أصل {est_total} صفحة ({pct_int}%)")

    df = pd.DataFrame(pages_result).drop_duplicates(subset=['الرابط']).reset_index(drop=True)
    imgs_df = pd.DataFrame(images_result)

    if not imgs_df.empty:
        counts = imgs_df[imgs_df['حالة النص البديل'] == 'alt_ok']['النص البديل الحالي (Alt)'].value_counts()
        dupes = set(counts[counts >= ALT_DUP_THRESHOLD].index)
        if dupes:
            imgs_df.loc[imgs_df['النص البديل الحالي (Alt)'].isin(dupes), 'حالة النص البديل'] = 'alt_duplicate'

    valid_titles = df[df['عنوان الميتا'].str.strip() != '']['عنوان الميتا']
    dup_titles = set(valid_titles[valid_titles.duplicated()].unique())
    valid_descs = df[df['وصف الميتا'].str.strip() != '']['وصف الميتا']
    dup_descs = set(valid_descs[valid_descs.duplicated()].unique())

    sitemap_keys = {url_key(u) for u in sitemap_urls}
    live_keys = {url_key(r['الرابط']) for _, r in df[df['متاحة'] == True].iterrows()}

    unlisted_pages = df[(df['متاحة'] == True) & (~df['الرابط'].map(url_key).isin(sitemap_keys))]['الرابط'].tolist()
    orphan_pages = [u for u in sitemap_urls if url_key(u) in live_keys and df[df['الرابط'].map(url_key) == url_key(u)]['مصدر الاكتشاف'].iloc[0] == 'خريطة الموقع']
    dead_pages = df[(df['متاحة'] == False) & (df['مصدر الاكتشاف'] == 'خريطة الموقع')]['الرابط'].tolist()

    coverage = {
        'sitemap_count': len(sitemap_urls),
        'unlisted_pages': unlisted_pages,
        'orphan_pages': orphan_pages,
        'dead_pages': dead_pages
    }

    summary = {
        'total_pages': len(df),
        'score': round(df[df['متاحة'] == True]['درجة السيو'].mean(), 1) if not df.empty else 0,
        'products': int((df['نوع الصفحة'] == T_PRODUCT).sum()),
        'categories': int((df['نوع الصفحة'] == T_CATEGORY).sum()),
        'info_pages': int((df['نوع الصفحة'] == T_INFO).sum()),
        'blog_pages': int((df['نوع الصفحة'] == T_BLOG).sum()),
        'broken_pages': int((df['متاحة'] == False).sum()),
        'missing_titles': int((df['حالة العنوان'] == 'missing').sum()),
        'duplicate_titles': len(dup_titles),
        'title_mismatch': int((df['مطابقة العنوان مع H1'] == 'match_diff').sum()),
        'missing_descs': int((df['حالة الوصف'] == 'missing').sum()),
        'short_descs': int((df['حالة الوصف'] == 'very_short').sum()),
        'duplicate_descs': len(dup_descs),
        'total_images': len(imgs_df),
        'missing_alts': int((imgs_df['حالة النص البديل'] == 'alt_missing').sum()) if not imgs_df.empty else 0,
        'weak_alts': int(imgs_df['حالة النص البديل'].isin(['alt_generic', 'alt_stuffed', 'alt_duplicate', 'alt_long']).sum()) if not imgs_df.empty else 0,
        'platform': platform
    }

    return df, imgs_df, summary, coverage, dup_titles, dup_descs

# ==============================================================
#  توليد الفاتورة مع رمز الريال على اليسار وألوان RGB الصحيحة
# ==============================================================
def shape_ar(text):
    if not text:
        return ""
    try:
        return get_display(arabic_reshaper.reshape(str(text)))
    except Exception:
        return str(text)

def generate_invoice_pdf(domain, quote, lang='ar'):
    rtl = (lang == 'ar')
    fmt = shape_ar if rtl else str

    pdf = FPDF()
    has_font = rtl and (FONT_PATH is not None) and FONT_PATH.exists()
    font_family = AR_FONT_NAME if has_font else "Helvetica"

    if has_font:
        pdf.add_font(font_family, "", str(FONT_PATH))
        bold_file = str(FONT_BOLD_PATH) if (FONT_BOLD_PATH and FONT_BOLD_PATH.exists()) else str(FONT_PATH)
        pdf.add_font(font_family, "B", bold_file)

    pdf.add_page()
    M, W = 18, 174

    def print_price(val, x, y, size=10, bold=False):
        num_str = f"{val:,.0f}"
        pdf.set_font(font_family, "B" if (has_font and bold) else "", size)
        pdf.set_text_color(15, 23, 42)
        nw = pdf.get_string_width(num_str)
        sym_h = size * 0.32
        sym_w = sym_h * 0.95
        gap = 1.5

        # رمز الريال يوضع أولاً من اليسار ثم الرقم على يمينه
        if RIYAL_PATH.exists():
            try:
                pdf.image(str(RIYAL_PATH), x=x, y=y + 0.8, h=sym_h)
            except Exception:
                pass
            pdf.set_xy(x + sym_w + gap, y)
            pdf.cell(nw, 6, num_str, 0, 0, 'L')
        else:
            pdf.set_xy(x, y)
            pdf.cell(nw, 6, num_str, 0, 0, 'L')
            pdf.set_xy(x + nw + gap, y)
            pdf.cell(10, 6, fmt("ر.س"), 0, 0, 'L')

    pdf.set_font(font_family, "B" if has_font else "", 18)
    pdf.set_text_color(15, 23, 42)
    pdf.set_xy(M, 18)
    pdf.cell(W, 8, fmt("عرض سعر وتهيئة السيو"), 0, 1, 'R')
    pdf.set_font(font_family, "", 9.5)
    pdf.set_text_color(100, 116, 139)
    pdf.cell(W, 5, fmt(f"المتجر: {domain}  ·  التاريخ: {datetime.now().strftime('%Y-%m-%d')}"), 0, 1, 'R')
    pdf.ln(8)

    pdf.set_fill_color(15, 23, 42)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font(font_family, "B" if has_font else "", 9.5)
    pdf.cell(35, 8, fmt("المبلغ"), 0, 0, 'C', fill=True)
    pdf.cell(30, 8, fmt("سعر الوحدة"), 0, 0, 'C', fill=True)
    pdf.cell(25, 8, fmt("الكمية"), 0, 0, 'C', fill=True)
    pdf.cell(W - 90, 8, fmt("الخدمة"), 0, 1, 'R', fill=True)

    pdf.set_font(font_family, "", 9)
    pdf.set_text_color(15, 23, 42)
    for idx, item in enumerate(quote['items']):
        y = pdf.get_y()
        if idx % 2 == 0:
            pdf.set_fill_color(248, 250, 252)
            pdf.rect(M, y, W, 8, 'F')
        print_price(item['total'], M + 5, y + 1, 9, True)
        print_price(item['unit'], M + 38, y + 1, 9, False)
        pdf.set_xy(M + 65, y + 1)
        pdf.cell(25, 6, str(item['qty']), 0, 0, 'C')
        pdf.set_xy(M + 90, y + 1)
        pdf.cell(W - 90, 6, fmt(item['name']), 0, 1, 'R')
        pdf.set_y(y + 8)

    pdf.ln(5)
    y_tot = pdf.get_y()
    pdf.set_font(font_family, "B" if has_font else "", 12)
    pdf.set_text_color(15, 23, 42)
    pdf.set_xy(M + 80, y_tot)
    pdf.cell(50, 8, fmt("الإجمالي المستحق:"), 0, 0, 'R')
    print_price(quote['total'], M + 135, y_tot + 1, 12, True)

    return bytes(pdf.output())

# ==============================================================
#  الواجهة الرسومية (Streamlit)
# ==============================================================
render_brandbar()

with st.sidebar:
    st.markdown("### 🧭 التحكم")
    nav = st.radio("", ["🔍 فحص المتجر", "📁 السجل السابق"], label_visibility="collapsed")
    st.markdown("---")
    st.markdown("#### ⚙️ إعدادات الفحص")
    max_pages = st.slider("الحد الأقصى للصفحات", 50, 3000, 1000, 50)
    workers = st.slider("عدد مسارات الزحف (Workers)", 1, 6, 3, help="القيم بين 2 و 4 هي الأنسب لتجنب حظر Cloudflare")

if nav == "🔍 فحص المتجر":
    c1, c2 = st.columns([5, 1])
    with c1:
        target_input = st.text_input("رابط المتجر", placeholder="https://example.com", value=st.session_state.current_url)
    with c2:
        st.write("")
        st.write("")
        start_btn = st.button("بدء الفحص", type="primary", use_container_width=True)

    if start_btn and target_input:
        target_clean = normalize_url(target_input)
        st.session_state.current_url = target_clean

        with st.status("جارٍ فحص المتجر بدقة...", expanded=True) as status:
            prog_bar = st.progress(0.0, text="بدء تجهيز الفحص (0%)...")
            df, imgs_df, summary, coverage, dup_t, dup_d = run_full_audit(
                target_clean, max_pages=max_pages, workers=workers,
                progress_cb=lambda pct, msg: prog_bar.progress(pct, text=msg)
            )
            prog_bar.progress(1.0, text="اكتمل الفحص بالكامل (100%)")
            status.update(label="اكتمل الفحص بنجاح!", state="complete", expanded=False)

        st.session_state.audit_df = df
        st.session_state.images_df = imgs_df
        st.session_state.summary = summary
        st.session_state.coverage = coverage
        st.session_state.dup_titles = dup_t
        st.session_state.dup_descs = dup_d
        st.session_state.platform = summary['platform']

        conn = sqlite3.connect(DB_FILE)
        conn.cursor().execute(
            '''INSERT INTO audits (domain, scan_date, score, total_pages, products_count,
               categories_count, info_pages_count, blog_pages_count, data_json, images_json, coverage_json, platform)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
            (target_clean, datetime.now().strftime("%Y-%m-%d %H:%M"), summary['score'],
             summary['total_pages'], summary['products'], summary['categories'],
             summary['info_pages'], summary['blog_pages'], df.to_json(orient='records'),
             imgs_df.to_json(orient='records') if not imgs_df.empty else '',
             json.dumps(coverage, ensure_ascii=False), summary['platform'])
        )
        conn.commit()
        conn.close()

    if st.session_state.audit_df is not None:
        df = st.session_state.audit_df
        imgs_df = st.session_state.images_df
        summary = st.session_state.summary
        coverage = st.session_state.coverage

        sc = summary['score']
        sc_col = COLOR['ok'] if sc >= 80 else (COLOR['warn'] if sc >= 60 else COLOR['bad'])

        st.markdown(
            f'<div class="hero">'
            f'<div><div class="score" style="color:{sc_col}">{sc}%</div>'
            f'<div class="scorelbl">درجة توافق السيو الفعلية</div></div>'
            f'<div><div class="store">{urlparse(st.session_state.current_url).netloc}</div>'
            f'<div class="plat">المنصة: {PLATFORM_LABEL.get(summary["platform"], "غير محددة")}</div></div></div>',
            unsafe_allow_html=True
        )

        cards = [
            (summary["total_pages"], "الصفحات المفحوصة", COLOR['accent']),
            (summary["products"], "المنتجات", COLOR['accent']),
            (summary["missing_titles"] + summary["duplicate_titles"], "مشاكل العناوين", COLOR['bad'] if summary["missing_titles"] else COLOR['ok']),
            (summary["title_mismatch"], "عناوين تخالف H1", COLOR['warn'] if summary["title_mismatch"] else COLOR['ok']),
            (summary["missing_descs"] + summary["duplicate_descs"], "مشاكل الأوصاف", COLOR['bad'] if summary["missing_descs"] else COLOR['ok']),
            (summary["missing_alts"], "صور بدون Alt", COLOR['bad'] if summary["missing_alts"] else COLOR['ok']),
        ]
        cols = st.columns(len(cards))
        for col, (v, l, c) in zip(cols, cards):
            with col:
                st.markdown(metric_card(v, l, c), unsafe_allow_html=True)

        st.write("")
        tabs = st.tabs(["📊 الملخص والنتائج", "🏷️ العناوين و H1", "📝 أوصاف الميتا", "🖼️ تدقيق الصور", "🗺️ الخريطة والظهور", "💰 عرض السعر الفوري"])

        # تبويب 1: الملخص
        with tabs[0]:
            c1, c2 = st.columns(2)
            with c1:
                t_items = [
                    (PAGE_TYPE_LABEL['ar'].get(k, k), int((df['نوع الصفحة'] == k).sum()))
                    for k in PAGE_TYPE_ORDER if (df['نوع الصفحة'] == k).any()
                ]
                st.markdown(bar_chart("توزيع صفحات المتجر", t_items), unsafe_allow_html=True)
            with c2:
                alt_items = [
                    ("سليم", int((imgs_df['حالة النص البديل'] == 'alt_ok').sum())),
                    ("مفقود", int((imgs_df['حالة النص البديل'] == 'alt_missing').sum())),
                    ("مكرر", int((imgs_df['حالة النص البديل'] == 'alt_duplicate').sum())),
                    ("غير وصفي", int((imgs_df['حالة النص البديل'] == 'alt_generic').sum())),
                ] if not imgs_df.empty else []
                st.markdown(bar_chart("جودة نصوص الصور البديلة (Alt)", alt_items, {
                    "سليم": COLOR['ok'], "مفقود": COLOR['bad'], "مكرر": COLOR['warn'], "غير وصفي": COLOR['bad']
                }), unsafe_allow_html=True)

            st.markdown("#### أهم الملاحظات المكتشفة:")
            if summary['missing_titles']:
                st.markdown(finding(f"يوجد <b>{summary['missing_titles']}</b> صفحة بدون عنوان ميتا أو عنوانها عبارة عن رموز فقط.", 'bad'), unsafe_allow_html=True)
            if summary['duplicate_titles']:
                st.markdown(finding(f"تم رصد <b>{summary['duplicate_titles']}</b> عنوان ميتا مكرر بين أكثر من صفحة.", 'warn'), unsafe_allow_html=True)
            if summary['title_mismatch']:
                st.markdown(finding(f"يوجد <b>{summary['title_mismatch']}</b> صفحة عنوان الميتا فيها لا يطابق اسم المنتج/القسم الظاهر (H1).", 'warn'), unsafe_allow_html=True)
            if summary['missing_alts']:
                st.markdown(finding(f"يوجد <b>{summary['missing_alts']}</b> صورة منتج لا تحمل أي نص بديل وتغيب عن بحث صور جوجل.", 'bad'), unsafe_allow_html=True)
            if coverage['unlisted_pages']:
                st.markdown(finding(f"تم اكتشاف <b>{len(coverage['unlisted_pages'])}</b> صفحة معروضة في المتجر ولكنها غائبة تماماً عن خريطة الموقع (Sitemap).", 'warn'), unsafe_allow_html=True)

        # تبويب 2: العناوين
        with tabs[1]:
            st.markdown("#### فحص العناوين ومطابقتها لـ H1")
            view_titles = df[['الرابط', 'نوع الصفحة', 'عنوان الميتا', 'طول العنوان', 'حالة العنوان', 'عنوان الصفحة (H1)', 'مطابقة العنوان مع H1']].copy()
            view_titles['نوع الصفحة'] = view_titles['نوع الصفحة'].map(lambda x: PAGE_TYPE_LABEL['ar'].get(x, x))
            view_titles['حالة العنوان'] = view_titles['حالة العنوان'].map(lambda x: STATUS_LABEL['ar'].get(x, x))
            view_titles['مطابقة العنوان مع H1'] = view_titles['مطابقة العنوان مع H1'].map(lambda x: STATUS_LABEL['ar'].get(x, x))
            st.dataframe(view_titles, use_container_width=True)

        # تبويب 3: الأوصاف
        with tabs[2]:
            st.markdown("#### فحص أوصاف الميتا (Meta Description)")
            view_descs = df[['الرابط', 'نوع الصفحة', 'وصف الميتا', 'طول الوصف', 'حالة الوصف']].copy()
            view_descs['نوع الصفحة'] = view_descs['نوع الصفحة'].map(lambda x: PAGE_TYPE_LABEL['ar'].get(x, x))
            view_descs['حالة الوصف'] = view_descs['حالة الوصف'].map(lambda x: STATUS_LABEL['ar'].get(x, x))
            st.dataframe(view_descs, use_container_width=True)

        # تبويب 4: الصور
        with tabs[3]:
            st.markdown("#### تدقيق نصوص الصور (Alt Text)")
            if not imgs_df.empty:
                v_imgs = imgs_df.copy()
                v_imgs['نوع الصفحة'] = v_imgs['نوع الصفحة'].map(lambda x: PAGE_TYPE_LABEL['ar'].get(x, x))
                v_imgs['حالة النص البديل'] = v_imgs['حالة النص البديل'].map(lambda x: STATUS_LABEL['ar'].get(x, x))
                st.dataframe(v_imgs, use_container_width=True)
            else:
                st.info("لم يتم العثور على صور محتوى مفحوصة.")

        # تبويب 5: الخريطة
        with tabs[4]:
            st.markdown("#### مطابقة صفحات المتجر مع خريطة الموقع")
            m1, m2, m3 = st.columns(3)
            m1.metric("روابط الخريطة", coverage['sitemap_count'])
            m2.metric("صفحات معروضة خارج الخريطة", len(coverage['unlisted_pages']))
            m3.metric("صفحات يتيمة بالخريطة", len(coverage['orphan_pages']))
            st.write("")
            if coverage['unlisted_pages']:
                with st.expander("📄 صفحات معروضة لكنها مفقودة من السايت ماب:"):
                    st.write(coverage['unlisted_pages'])
            if coverage['orphan_pages']:
                with st.expander("👻 صفحات يتيمة (في السايت ماب ولا توجد روابط لها بالمتجر):"):
                    st.write(coverage['orphan_pages'])

        # تبويب 6: عرض السعر
        with tabs[5]:
            st.markdown("#### توليد عرض سعر مخصص للإصلاح")
            p_title = st.number_input("سعر كتابة وتعديل العنوان الواحد (ريال)", 5.0, 100.0, 15.0, 1.0)
            p_desc = st.number_input("سعر كتابة الوصف الواحد (ريال)", 5.0, 100.0, 10.0, 1.0)
            p_alt = st.number_input("سعر كتابة النص البديل للصورة (ريال)", 1.0, 50.0, 3.0, 0.5)

            qty_titles = summary['missing_titles'] + summary['duplicate_titles'] + summary['title_mismatch']
            qty_descs = summary['missing_descs'] + summary['duplicate_descs'] + summary['short_descs']
            qty_alts = summary['missing_alts'] + summary['weak_alts']

            quote = {
                'items': [
                    {'name': 'إصلاح وصياغة عناوين الميتا و H1', 'qty': qty_titles, 'unit': p_title, 'total': qty_titles * p_title},
                    {'name': 'كتابة أوصاف ميتا فريدة وجذابة', 'qty': qty_descs, 'unit': p_desc, 'total': qty_descs * p_desc},
                    {'name': 'صياغة نصوص بديلة للصور (Alt Text)', 'qty': qty_alts, 'unit': p_alt, 'total': qty_alts * p_alt},
                ],
                'total': (qty_titles * p_title) + (qty_descs * p_desc) + (qty_alts * p_alt)
            }

            st.write(f"**الإجمالي التقديري للتكلفة:** {quote['total']:,.0f} ريال")
            inv_pdf = generate_invoice_pdf(urlparse(st.session_state.current_url).netloc, quote, lang='ar')

            st.download_button(
                "🧾 تحميل عرض السعر PDF (رمز الريال على اليسار)",
                data=inv_pdf,
                file_name=f"Quote_{urlparse(st.session_state.current_url).netloc}.pdf",
                mime="application/pdf"
            )

else:
    st.markdown("### 📁 سجل المتاجر السابقة")
    conn = sqlite3.connect(DB_FILE)
    hist = pd.read_sql_query("SELECT id, domain, scan_date, score, total_pages, products_count FROM audits ORDER BY id DESC", conn)
    conn.close()
    if not hist.empty:
        st.dataframe(hist, use_container_width=True)
    else:
        st.info("لا توجد فحوصات محفوظة بعد.")
