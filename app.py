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
#  أنس راشد — anasrashed.com
#
#  مبدأ الفحص: يبدأ من الصفحة الرئيسية ويتصفح المتجر كما يتصفحه
#  الزائر. لا تدخل التقرير أي صفحة لا يمكن للزائر الوصول إليها.
# ==============================================================

st.set_page_config(page_title="مركز عمليات السيو | أنس راشد",
                   layout="wide", page_icon="🚀", initial_sidebar_state="expanded")

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
MAX_PAGINATION_DEPTH = 40
MAX_CRAWL_LEVELS = 8
MAX_REDIRECT_CHECKS = 300

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept-Language': 'ar,en;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
}

T_HOME, T_PRODUCT, T_CATEGORY = 'home', 'product', 'category'
T_BLOG, T_INFO, T_UNKNOWN, T_BROKEN = 'blog', 'info', 'unknown', 'broken'
PAGE_TYPE_ORDER = [T_HOME, T_PRODUCT, T_CATEGORY, T_BLOG, T_INFO, T_UNKNOWN, T_BROKEN]

PAGE_TYPE_LABEL = {
    'ar': {T_HOME: 'صفحة رئيسية', T_PRODUCT: 'صفحة منتج', T_CATEGORY: 'صفحة تصنيف',
           T_BLOG: 'صفحة مدونة', T_INFO: 'صفحة تعريفية', T_UNKNOWN: 'غير مصنفة',
           T_BROKEN: 'صفحة غير متاحة'},
    'en': {T_HOME: 'Homepage', T_PRODUCT: 'Product', T_CATEGORY: 'Category',
           T_BLOG: 'Blog', T_INFO: 'Info / Policy', T_UNKNOWN: 'Unclassified',
           T_BROKEN: 'Unreachable'},
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
    },
    'en': {
        'missing': 'Missing', 'very_short': 'Too short', 'acceptable': 'Acceptable',
        'optimal': 'Optimal', 'long': 'Too long', 'failed': 'Scan failed',
        'good': 'Good', 'thin': 'Thin content', 'na': 'N/A',
        'alt_missing': 'Missing', 'alt_generic': 'Not descriptive',
        'alt_stuffed': 'Keyword stuffed', 'alt_long': 'Over 125 characters',
        'alt_duplicate': 'Duplicated across images', 'alt_ok': 'Good',
        'alt_empty': '(empty)',
        'canon_same': 'Self-referencing', 'canon_diff': 'Differs from page URL',
        'canon_missing': 'Missing',
    },
}

# حدود الطول وفق أفضل ممارسات محركات البحث
# (تُحسب بالحروف شاملة المسافات وعلامات الترقيم كافة)
TITLE_MAX, TITLE_MIN_OPTIMAL, TITLE_MIN_OK = 60, 50, 30
DESC_MAX, DESC_MIN_OPTIMAL, DESC_MIN_OK = 150, 120, 70
ALT_MAX = 125                 # حد قارئات الشاشة العملي
ALT_DUP_THRESHOLD = 3         # نفس النص على 3 صور أو أكثر يُعدّ تكراراً

COL_EN = {
    'نوع الصفحة': 'Page Type', 'الرابط': 'URL', 'الرابط الكانوني': 'Canonical URL',
    'مصدر الاكتشاف': 'Discovered Via', 'متاحة': 'Reachable', 'كود الاستجابة': 'Status Code',
    'درجة السيو': 'SEO Score', 'عنوان الميتا': 'Meta Title', 'طول العنوان': 'Title Length',
    'حالة العنوان': 'Title Status', 'وصف الميتا': 'Meta Description',
    'طول الوصف': 'Description Length', 'حالة الوصف': 'Description Status',
    'إجمالي الصور': 'Total Images', 'صور بدون Alt': 'Images Missing Alt',
    'صور Alt ضعيف': 'Images With Weak Alt', 'عدد الكلمات': 'Word Count',
    'حالة المحتوى': 'Content Status', 'لغة الصفحة': 'Page Language',
    'حالة الكانونيكال': 'Canonical Status', 'رابط الصفحة': 'Page URL',
    'رابط الصورة': 'Image URL', 'النص البديل الحالي (Alt)': 'Current Alt Text',
    'طول النص البديل': 'Alt Length', 'حالة النص البديل': 'Alt Status',
    'عدد الصفحات': 'Appears On Pages',
    'الوجهة النهائية': 'Final Destination',
}

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
    c.execute("PRAGMA table_info(audits)")
    existing = {row[1] for row in c.fetchall()}
    for col, coltype in [("blog_pages_count", "INTEGER DEFAULT 0"),
                         ("images_json", "TEXT"), ("coverage_json", "TEXT"),
                         ("platform", "TEXT")]:
        if col not in existing:
            c.execute(f"ALTER TABLE audits ADD COLUMN {col} {coltype}")
    conn.commit()
    conn.close()


init_db()

for key, default in [('audit_df', None), ('images_df', None), ('summary', None),
                     ('current_url', ""), ('coverage', None), ('platform', 'unknown')]:
    if key not in st.session_state:
        st.session_state[key] = default


# ==============================================================
#  التنسيق
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
.bar-label { flex:0 0 150px; font-size:12.5px; color:#334155; }
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


def logo_data_uri():
    try:
        import base64
        return "data:image/png;base64," + base64.b64encode(LOGO_PATH.read_bytes()).decode()
    except Exception:
        return ""


def render_brandbar():
    logo = logo_data_uri()
    img = f'<img src="{logo}" style="height:40px">' if logo else ''
    st.markdown(
        f'<div class="brandbar">'
        f'<div><div class="name">أنس راشد</div>'
        f'<div class="role">خبير تحسين محركات البحث</div></div>'
        f'<div style="display:flex;align-items:center;gap:18px">'
        f'<div class="tool">مركز عمليات السيو<br>anasrashed.com</div>{img}</div></div>',
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
#  أدوات الروابط
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


def url_key(url):
    """مفتاح موحّد للمقارنة: يفك ترميز المسارات العربية حتى لا يُعدّ
    /products/%D8%A8... مختلفاً عن /products/بوكس..."""
    if not url:
        return ""
    p = urlparse(clean_url(url))
    return f"{p.netloc.lower()}{unquote(p.path).rstrip('/')}"


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


def resolve_final_url(url, timeout=10):
    """وجهة الرابط بعد اتباع كل عمليات التحويل، دون تحميل الصفحة كاملة."""
    try:
        res = requests.head(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        if res.status_code >= 400 or res.status_code == 405:
            raise ValueError
        return clean_url(res.url), res.status_code
    except Exception:
        try:
            res = requests.get(url, headers=HEADERS, timeout=timeout,
                               allow_redirects=True, stream=True)
            final = clean_url(res.url)
            code = res.status_code
            res.close()
            return final, code
        except Exception:
            return None, None


EXCLUDE_PATH_PARTS = [
    '/cart', '/checkout', '/login', '/signin', '/register', '/signup', '/account',
    '/my-account', '/wishlist', '/favorites', '/compare', '/search', '/orders',
    '/customer', '/password', '/thank-you', '/logout', '/tag/', '/tags/',
    '/سلة', '/حسابي', '/تسجيل', '/الدفع', '/بحث', '/المفضلة',
    '/cdn-cgi/', '/email-protection', '/__', '/wp-admin', '/wp-json',
]
BAD_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.gif', '.svg', '.webp', '.avif', '.pdf',
                  '.zip', '.rar', '.xml', '.css', '.js', '.ico', '.mp4', '.webm',
                  '.mp3', '.doc', '.docx', '.xls', '.xlsx')


def is_crawlable(url, base_netloc):
    if not url:
        return False
    p = urlparse(url)
    if p.scheme not in ('http', 'https') or p.netloc.lower() != base_netloc.lower():
        return False
    path = unquote(p.path.lower())
    if path.endswith(BAD_EXTENSIONS):
        return False
    if any(part in path for part in EXCLUDE_PATH_PARTS):
        return False
    return True


# ==============================================================
#  القياس والتقييم
# ==============================================================
def text_length(text):
    """عدد الحروف بعد توحيد المسافات — يشمل المسافات والفواصل والنقاط
    وكل علامات الترقيم، لأن محركات البحث تحسبها ضمن المساحة المعروضة."""
    if not text:
        return 0
    return len(re.sub(r'\s+', ' ', str(text)).strip())


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


AR_PREFIXES = ('وال', 'بال', 'فال', 'كال', 'لل', 'ال', 'و')


def normalize_ar_token(tok):
    """تجريد أداة التعريف وحروف العطف وتوحيد الهمزات، حتى تطابق
    «والأحكام» الكلمة المفتاحية «احكام»."""
    t = tok.strip('.,،؛:!?()[]')
    t = re.sub(r'[\u064B-\u0652\u0670]', '', t)      # التشكيل
    t = t.replace('أ', 'ا').replace('إ', 'ا').replace('آ', 'ا')
    t = t.replace('ى', 'ي').replace('ة', 'ه')
    for pre in AR_PREFIXES:
        if t.startswith(pre) and len(t) > len(pre) + 1:
            t = t[len(pre):]
            break
    return t


GENERIC_ALT = {
    'image', 'images', 'img', 'photo', 'photos', 'picture', 'pic', 'icon', 'logo',
    'product', 'item', 'untitled', 'default', 'thumbnail', 'thumb', 'banner',
    'slide', 'slider', 'cover', 'hero', 'main', 'mobile', 'desktop', 'tablet',
    'new', 'sale', 'view', 'gallery', 'preview',
    'صورة', 'صوره', 'صور', 'منتج', 'شعار', 'غلاف', 'رئيسية', 'جديد',
}


GENERIC_ALT_NORM = None


def _generic_alt_norm():
    global GENERIC_ALT_NORM
    if GENERIC_ALT_NORM is None:
        GENERIC_ALT_NORM = {normalize_ar_token(w) if re.search(r'[\u0600-\u06FF]', w)
                            else w for w in GENERIC_ALT}
    return GENERIC_ALT_NORM


def grade_alt(alt_text):
    """تقييم النص البديل بمعايير الجودة لا بالطول وحده.

    الطول القصير ليس عيباً في ذاته: «عود مروكي محسن» نص بديل ممتاز.
    ما يضر فعلاً هو الغياب، أو النص غير الوصفي (اسم ملف/كلمة عامة)،
    أو حشو الكلمات المفتاحية، أو تجاوز حد قارئات الشاشة (125 حرفاً).
    """
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
    words = [normalize_ar_token(w) if re.search(r'[\u0600-\u06FF]', w) else w
             for w in words if w]
    if not words or all(w in _generic_alt_norm() for w in words):
        return 'alt_generic', length
    if length > ALT_MAX:
        return 'alt_long', length

    commas = txt.count(',') + txt.count('،')
    if commas >= 4 and len(words) / max(commas, 1) < 3:
        return 'alt_stuffed', length
    if len(words) >= 6 and len(set(words)) / len(words) < 0.5:
        return 'alt_stuffed', length

    return 'alt_ok', length


ALT_CREDIT = {'alt_ok': 1.0, 'alt_duplicate': 0.4, 'alt_long': 0.6,
              'alt_stuffed': 0.3, 'alt_generic': 0.0, 'alt_missing': 0.0}
ALT_WEAK_STATES = ('alt_generic', 'alt_stuffed', 'alt_long', 'alt_duplicate')


def apply_duplicate_alt(images_df):
    """نفس النص البديل على صور مختلفة لا يميّز أياً منها لمحركات البحث.

    يُحسب التكرار على مستوى الصورة الفريدة لا على مستوى الصفوف: ظهور صورة
    المنتج نفسها في الرئيسية وصفحة القسم وصفحة المنتج ليس تكراراً، بل هو
    السلوك الطبيعي لأي متجر.
    """
    if images_df is None or images_df.empty:
        return images_df
    df = images_df.copy()
    uniq = df.drop_duplicates(subset=['رابط الصورة'])
    ok = uniq[uniq['حالة النص البديل'] == 'alt_ok']
    counts = ok['النص البديل الحالي (Alt)'].value_counts()
    dupes = set(counts[counts >= ALT_DUP_THRESHOLD].index)
    if dupes:
        mask = (df['حالة النص البديل'] == 'alt_ok') & \
               df['النص البديل الحالي (Alt)'].isin(dupes)
        df.loc[mask, 'حالة النص البديل'] = 'alt_duplicate'
    return df


def unique_images(images_df):
    """جدول الصور الفريدة مع عدد الصفحات التي تظهر فيها كل صورة."""
    if images_df is None or images_df.empty:
        return images_df
    counts = images_df.groupby('رابط الصورة')['رابط الصفحة'].nunique()
    out = images_df.drop_duplicates(subset=['رابط الصورة']).copy()
    out['عدد الصفحات'] = out['رابط الصورة'].map(counts)
    return out.reset_index(drop=True)


# ==============================================================
#  كشف منصة المتجر
# ==============================================================
PLATFORM_LABEL = {'salla': 'سلة (Salla)', 'zid': 'زد (Zid)',
                  'shopify': 'شوبيفاي (Shopify)', 'unknown': 'غير معروفة'}
PLATFORM_LABEL_EN = {'salla': 'Salla', 'zid': 'Zid',
                     'shopify': 'Shopify', 'unknown': 'Unidentified'}
SUPPORTED_PLATFORMS = ('salla', 'zid', 'shopify')


def detect_platform(html, headers=None, url=""):
    h = (html or "")[:200000].lower()
    hdr = " ".join(f"{k}:{v}" for k, v in (headers or {}).items()).lower()
    blob = h + " " + hdr + " " + (url or "").lower()
    if any(s in blob for s in ['salla.sa', 'cdn.salla.network', 'window.salla', 'salla-']):
        return 'salla'
    if any(s in blob for s in ['zid.store', 'media.zid.sa', 'zidapi', 'x-zid', 'cdn.zid']):
        return 'zid'
    if any(s in blob for s in ['cdn.shopify.com', 'myshopify.com', 'shopify.theme',
                               'x-shopify', 'shopify-features']):
        return 'shopify'
    return 'unknown'


# ==============================================================
#  تصنيف الصفحات
# ==============================================================
POLICY_KEYWORDS = [
    'سياسة', 'شروط', 'خصوصية', 'استبدال', 'استرجاع', 'شحن', 'توصيل', 'شكاوى',
    'اسئلة', 'أسئلة', 'من-نحن', 'اتصل', 'ضمان', 'دفع', 'مقترحات', 'أحكام',
    'الاستخدام', 'ارجاع', 'إرجاع', 'مرتجعات', 'تبديل', 'ضمانات',
    'pages', 'page', 'policies', 'policy', 'privacy', 'terms', 'conditions',
    'about', 'about-us', 'contact', 'contact-us', 'faq', 'faqs', 'help',
    'shipping', 'delivery', 'complaint', 'complaints', 'returns', 'return',
    'refund', 'refunds', 'payment', 'warranty', 'support', 'legal',
]
CATALOG_ROOTS = ['products', 'product', 'all-products', 'catalog', 'catalogue',
                 'collections/all', 'shop', 'store']
BLOG_SEGMENTS = ('blog', 'blogs', 'articles', 'article', 'post', 'posts', 'news',
                 'مدونة', 'مقالات', 'اخبار', 'أخبار')
CATEGORY_SEGMENTS = ('category', 'categories', 'collection', 'collections',
                     'department', 'departments', 'قسم', 'اقسام', 'أقسام', 'تصنيف')


POLICY_KEYWORDS_NORM = None


def _policy_keywords_norm():
    global POLICY_KEYWORDS_NORM
    if POLICY_KEYWORDS_NORM is None:
        POLICY_KEYWORDS_NORM = set()
        for k in POLICY_KEYWORDS:
            for part in k.split('-'):
                POLICY_KEYWORDS_NORM.add(normalize_ar_token(part.lower()))
    return POLICY_KEYWORDS_NORM


def segment_is_policy(seg):
    norm = _policy_keywords_norm()
    parts = [normalize_ar_token(p.lower()) for p in seg.split('-') if p]
    return any(p in norm for p in parts if len(p) > 2)


def _has_jsonld_type(soup, wanted):
    for tag in soup.find_all('script', attrs={'type': 'application/ld+json'}):
        try:
            data = json.loads(tag.string or '{}')
        except Exception:
            continue
        blocks = data if isinstance(data, list) else [data]
        for b in blocks:
            if not isinstance(b, dict):
                continue
            t = b.get('@type')
            types = t if isinstance(t, list) else [t]
            if any(str(x) in wanted for x in types if x):
                return True
    return False


def detect_page_type(url, base_url, soup=None):
    base_clean = normalize_url(base_url)
    url_clean = clean_url(url)

    if url_key(url_clean) == url_key(base_clean) or urlparse(url_clean).path in ('', '/'):
        return T_HOME

    path = unquote(urlparse(url_clean).path.lower())
    path_clean = path.strip('/')
    segments = [s for s in path_clean.split('/') if s]

    og_type = ""
    if soup:
        tag = soup.find('meta', attrs={'property': 'og:type'})
        if tag and tag.get('content'):
            og_type = tag['content'].lower()

    if 'product' in og_type:
        return T_PRODUCT
    if soup and soup.find(attrs={'itemtype': re.compile(r'schema\.org/Product', re.I)}):
        return T_PRODUCT
    if soup and _has_jsonld_type(soup, ('Product',)):
        return T_PRODUCT
    if ('products' in segments or 'product' in segments) and len(segments) >= 2:
        return T_PRODUCT
    if re.search(r'/p\d+', path) or '-p-' in path:
        return T_PRODUCT
    if any(re.match(r'^p\d+$', s) for s in segments):
        return T_PRODUCT

    # السياسات قبل المدونة: بعض المتاجر تنشر السياسات تحت مسار /blogs/
    if any(segment_is_policy(seg) for seg in segments if seg not in BLOG_SEGMENTS):
        return T_INFO

    if 'article' in og_type or 'blog' in og_type:
        return T_BLOG
    if soup and soup.find(attrs={'itemtype': re.compile(
            r'schema\.org/(Article|BlogPosting|NewsArticle)', re.I)}):
        return T_BLOG
    if soup and _has_jsonld_type(soup, ('Article', 'BlogPosting', 'NewsArticle')):
        return T_BLOG
    if any(s in BLOG_SEGMENTS for s in segments):
        return T_BLOG

    if path_clean in CATALOG_ROOTS:
        return T_CATEGORY
    if soup and soup.find(attrs={'itemtype': re.compile(r'schema\.org/CollectionPage', re.I)}):
        return T_CATEGORY
    if any(s in CATEGORY_SEGMENTS for s in segments):
        return T_CATEGORY
    if re.search(r'/c\d+', path) or any(re.match(r'^c\d+$', s) for s in segments):
        return T_CATEGORY

    return T_UNKNOWN


def detect_page_language(soup, text_sample=""):
    if soup:
        html_tag = soup.find('html')
        if html_tag and html_tag.get('lang'):
            code = str(html_tag['lang']).strip().lower()[:2]
            if code:
                return code
    arabic = len(re.findall(r'[\u0600-\u06FF]', text_sample))
    latin = len(re.findall(r'[A-Za-z]', text_sample))
    if arabic == 0 and latin == 0:
        return '—'
    return 'ar' if arabic >= latin else 'en'


# ==============================================================
#  فلترة صور المحتوى
# ==============================================================
JUNK_KEYWORDS = [
    'spinner', 'loader', 'loading', 'ajax', 'icon', 'badge', 'payment', 'gateway',
    'tamara', 'tabby', 'mada', 'visa', 'mastercard', 'apple-pay', 'applepay',
    'stc-pay', 'stcpay', 'vat', 'tax', 'maroof', 'social', 'whatsapp', 'snapchat',
    'instagram', 'tiktok', 'twitter', 'pixel', 'spacer', 'avatar', 'arrow',
    'placeholder', 'blank',
    # شعارات شركات الشحن ومزودي الخدمة
    'zidship', 'aramex', 'smsa', 'redbox', 'naqel', 'servicelevel', 'courier',
    'shipment', 'shipping-company', 'carrier', 'fastlo', 'imile',
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
    if s.startswith('data:image') or 'static.' in s or '/static/' in s:
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
    targets = soup.select('header, nav, footer, aside, [class*="header"], '
                          '[class*="footer"], [class*="navbar"], [class*="nav-menu"]')
    for tag in targets:
        try:
            tag.decompose()
        except Exception:
            pass
    return soup


# ==============================================================
#  فحص صفحة واحدة
# ==============================================================
def broken_page_row(url, reason, source):
    return {
        'page_data': {
            'نوع الصفحة': T_BROKEN, 'الرابط': unquote(url), 'مصدر الاكتشاف': source,
            'متاحة': False, 'كود الاستجابة': str(reason), 'لغة الصفحة': '—',
            'درجة السيو': None, 'عنوان الميتا': '', 'طول العنوان': 0,
            'حالة العنوان': 'failed', 'وصف الميتا': '', 'طول الوصف': 0,
            'حالة الوصف': 'failed', 'إجمالي الصور': 0, 'صور بدون Alt': 0,
            'صور Alt ضعيف': 0, 'عدد الكلمات': 0, 'حالة المحتوى': 'na',
            'حالة الكانونيكال': 'canon_missing', 'الرابط الكانوني': '', '_raw_url': url,
        },
        'images_data': [], 'links': set(),
    }


def fetch_and_audit(task):
    url, base_url, source = task
    try:
        return _fetch_and_audit(url, base_url, source)
    except Exception as e:
        return broken_page_row(clean_url(url), f'خطأ فني: {type(e).__name__}', source)


def _fetch_and_audit(url, base_url, source):
    res = safe_get(url)
    if res is None:
        return broken_page_row(clean_url(url), 'فشل اتصال', source)
    ctype = (res.headers.get('Content-Type') or '').lower()
    if res.status_code != 200:
        return broken_page_row(clean_url(res.url), f'خطأ {res.status_code}', source)
    if ctype and 'html' not in ctype:
        return broken_page_row(clean_url(res.url), 'ليست صفحة HTML', source)

    final_url = clean_url(res.url)
    soup = make_soup(res.text)
    page_type = detect_page_type(final_url, base_url, soup)

    base_netloc = urlparse(normalize_url(base_url)).netloc
    links = set()
    for a in soup.find_all('a', href=True):
        href = a['href'].strip()
        if href.startswith(('mailto:', 'tel:', 'javascript:', '#')):
            continue
        full = clean_url(urljoin(final_url, href))
        if is_crawlable(full, base_netloc):
            links.add(full)

    canonical = ''
    for link in soup.find_all('link', href=True):
        rel = link.get('rel') or []
        rel = [r.lower() for r in (rel if isinstance(rel, list) else [rel])]
        if 'canonical' in rel:
            canonical = clean_url(urljoin(final_url, link['href']))
            break
    if not canonical:
        canon_status, canonical = 'canon_missing', final_url
    elif url_key(canonical) == url_key(final_url):
        canon_status = 'canon_same'
    else:
        canon_status = 'canon_diff'

    title_tag = soup.find('title')
    title = re.sub(r'\s+', ' ', title_tag.get_text(strip=True)).strip() if title_tag else ''
    title_len = text_length(title)
    title_status = grade_length(title_len, TITLE_MIN_OK, TITLE_MIN_OPTIMAL, TITLE_MAX)

    desc_tag = (soup.find('meta', attrs={'name': 'description'})
                or soup.find('meta', attrs={'property': 'og:description'}))
    meta_desc = desc_tag['content'].strip() if desc_tag and desc_tag.get('content') else ''
    meta_desc = re.sub(r'\s+', ' ', meta_desc).strip()
    desc_len = text_length(meta_desc)
    desc_status = grade_length(desc_len, DESC_MIN_OK, DESC_MIN_OPTIMAL, DESC_MAX)

    content_soup = strip_boilerplate(make_soup(res.text))
    total_img = 0
    page_images = []
    for img in content_soup.find_all('img'):
        src = get_image_src(img)
        if src and is_relevant_seo_image(img, src):
            total_img += 1
            alt_text = (img.get('alt') or '').strip()
            alt_status, alt_len = grade_alt(alt_text)
            page_images.append({
                'رابط الصفحة': unquote(final_url), 'نوع الصفحة': page_type,
                'رابط الصورة': urljoin(final_url, src),
                'النص البديل الحالي (Alt)': alt_text,
                'طول النص البديل': alt_len, 'حالة النص البديل': alt_status,
            })

    for s in content_soup(['script', 'style', 'noscript']):
        s.decompose()
    body_text = content_soup.get_text(separator=' ', strip=True)
    words = len(body_text.split())
    content_status = 'good' if words >= 50 else 'thin'
    page_lang = detect_page_language(soup, (title + ' ' + body_text[:500]))

    return {
        'page_data': {
            'نوع الصفحة': page_type, 'الرابط': unquote(final_url), 'مصدر الاكتشاف': source,
            'متاحة': True, 'كود الاستجابة': '200', 'لغة الصفحة': page_lang,
            'درجة السيو': None,  # تُحسب بعد تقييم تكرار الـ Alt
            'عنوان الميتا': title, 'طول العنوان': title_len, 'حالة العنوان': title_status,
            'وصف الميتا': meta_desc, 'طول الوصف': desc_len, 'حالة الوصف': desc_status,
            'إجمالي الصور': total_img, 'صور بدون Alt': 0, 'صور Alt ضعيف': 0,
            'عدد الكلمات': words, 'حالة المحتوى': content_status,
            'حالة الكانونيكال': canon_status,
            'الرابط الكانوني': unquote(canonical) if canon_status == 'canon_diff' else '',
            '_raw_url': final_url,
        },
        'images_data': page_images,
        'links': links,
        'platform_html': res.text[:60000] if page_type == T_HOME else '',
        'platform_headers': dict(res.headers) if page_type == T_HOME else {},
    }


LEN_WEIGHT = {'optimal': 1.0, 'acceptable': 0.7, 'very_short': 0.3,
              'long': 0.4, 'missing': 0.0}


def score_pages(df, images_df):
    """تُحسب الدرجة بعد اكتمال تقييم الصور (لأن تكرار الـ Alt يحتاج نظرة شاملة)."""
    if df.empty:
        return df
    per_page = {}
    if images_df is not None and not images_df.empty:
        for page, grp in images_df.groupby('رابط الصفحة'):
            credit = grp['حالة النص البديل'].map(ALT_CREDIT).fillna(0).sum()
            per_page[page] = {
                'credit': credit, 'n': len(grp),
                'missing': int((grp['حالة النص البديل'] == 'alt_missing').sum()),
                'weak': int(grp['حالة النص البديل'].isin(ALT_WEAK_STATES).sum()),
            }
    out = df.copy()
    scores, miss, weak = [], [], []
    for _, r in out.iterrows():
        if not r['متاحة']:
            scores.append(None)
            miss.append(0)
            weak.append(0)
            continue
        s = 25 * LEN_WEIGHT.get(r['حالة العنوان'], 0)
        s += 25 * LEN_WEIGHT.get(r['حالة الوصف'], 0)
        info = per_page.get(r['الرابط'])
        if not info or info['n'] == 0:
            s += 25
            miss.append(0)
            weak.append(0)
        else:
            s += 25 * (info['credit'] / info['n'])
            miss.append(info['missing'])
            weak.append(info['weak'])
        s += 25 if r['حالة المحتوى'] == 'good' else 0
        scores.append(max(0, min(100, round(s))))
    out['درجة السيو'] = scores
    out['صور بدون Alt'] = miss
    out['صور Alt ضعيف'] = weak
    return out


# ==============================================================
#  الزحف من الواجهة
# ==============================================================
def crawl_store(base_url, max_pages, workers, progress_cb=None, max_levels=MAX_CRAWL_LEVELS):
    base_url = normalize_url(base_url)
    pages, images = [], []
    seen = {url_key(base_url)}
    frontier = [base_url]
    category_urls = []
    platform = 'unknown'
    level = 0

    while frontier and len(pages) < max_pages and level < max_levels:
        level += 1
        room = max_pages - len(pages)
        batch, frontier = frontier[:room], frontier[room:]
        next_frontier = []
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for res in ex.map(fetch_and_audit,
                              [(u, base_url, 'الزحف من الواجهة') for u in batch]):
                row = res['page_data']
                pages.append(row)
                images.extend(res['images_data'])
                if res.get('platform_html') and platform == 'unknown':
                    platform = detect_platform(res['platform_html'],
                                               res.get('platform_headers'), base_url)
                if row['نوع الصفحة'] in (T_CATEGORY, T_HOME):
                    category_urls.append(row.get('_raw_url', row['الرابط']))
                # الوجهة النهائية بعد التحويل تُعدّ مزارة أيضاً
                seen.add(url_key(row.get('_raw_url', row['الرابط'])))
                for link in res.get('links', ()):
                    k = url_key(link)
                    if k not in seen:
                        seen.add(k)
                        next_frontier.append(link)
        frontier = next_frontier + frontier
        if progress_cb:
            progress_cb(len(pages), len(frontier), level)
    return pages, images, category_urls, seen, platform


def harvest_paginated_products(base_url, category_urls, seen_keys, progress_cb=None,
                               max_depth=MAX_PAGINATION_DEPTH):
    base_url = normalize_url(base_url)
    base_netloc = urlparse(base_url).netloc
    roots = list(dict.fromkeys(
        list(category_urls) + [f"{base_url}/{r}" for r in
                               ['products', 'collections/all', 'shop']]))
    new_urls, fetched = [], 0
    for idx, cat in enumerate(roots):
        seen_here = set()
        for page in range(2, max_depth + 1):
            res = safe_get(f"{cat}?page={page}", retries=1)
            fetched += 1
            if res is None or res.status_code != 200:
                break
            soup = make_soup(res.text)
            found = set()
            for a in soup.find_all('a', href=True):
                full = clean_url(urljoin(cat, a['href'].strip()))
                if is_crawlable(full, base_netloc) and \
                        detect_page_type(full, base_url, None) == T_PRODUCT:
                    found.add(full)
            fresh = found - seen_here
            if not fresh:
                break
            seen_here |= fresh
            for u in fresh:
                k = url_key(u)
                if k not in seen_keys:
                    seen_keys.add(k)
                    new_urls.append(u)
        if progress_cb:
            progress_cb(idx + 1, len(roots), len(new_urls), fetched)
    return new_urls


def audit_urls(urls, base_url, source, workers, progress_bar=None):
    pages, images = [], []
    tasks = [(u, base_url, source) for u in urls]
    total = max(len(tasks), 1)
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for res in ex.map(fetch_and_audit, tasks):
            pages.append(res['page_data'])
            images.extend(res['images_data'])
            done += 1
            if progress_bar:
                progress_bar.progress(min(done / total, 1.0))
    return pages, images


# ==============================================================
#  خريطة الموقع — مقارنة تشخيصية
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


def collect_sitemap_urls(base_url, max_depth=3):
    base_url = normalize_url(base_url)
    base_netloc = urlparse(base_url).netloc
    urls, visited = set(), set()

    def walk(sm_url, depth):
        if depth > max_depth or sm_url in visited:
            return
        visited.add(sm_url)
        root = fetch_xml_root(sm_url)
        if root is None:
            return
        for loc in iter_locs(root):
            low = loc.lower()
            if low.endswith('.xml') or low.endswith('.xml.gz'):
                walk(loc, depth + 1)
            else:
                u = clean_url(loc)
                if u and urlparse(u).netloc == base_netloc:
                    urls.add(u)

    for c in (discover_sitemaps_from_robots(base_url) +
              [f"{base_url}/sitemap.xml", f"{base_url}/sitemap_index.xml",
               f"{base_url}/sitemap_products_1.xml", f"{base_url}/sitemap_pages_1.xml"]):
        walk(c, 0)
    return urls


def build_coverage_report(visible_df, sitemap_urls, base_url, workers=4, progress_cb=None):
    """مقارنة بين ما يراه الزائر وما تعلنه خريطة الموقع.

    أي رابط في الخريطة لا يطابق صفحة مزارة يُتحقق من وجهته أولاً: قد يكون
    مجرد تحويل إلى صفحة مفحوصة (وهذا هدر لميزانية الزحف، لا صفحة يتيمة).
    """
    src_col = '_raw_url' if '_raw_url' in visible_df.columns else 'الرابط'
    vis, vis_types = {}, {}
    for _, r in visible_df[visible_df['متاحة'] == True].iterrows():  # noqa: E712
        k = url_key(r[src_col])
        vis.setdefault(k, r[src_col])
        vis_types.setdefault(k, r['نوع الصفحة'])

    sm, sm_types = {}, {}
    for u in sitemap_urls:
        k = url_key(u)
        sm.setdefault(k, u)
        sm_types.setdefault(k, detect_page_type(u, base_url, None))

    vis_keys, sm_keys = set(vis), set(sm)
    unmatched = sorted(sm_keys - vis_keys)[:MAX_REDIRECT_CHECKS]

    redirects, orphans = [], []
    if unmatched:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            finals = list(ex.map(lambda k: resolve_final_url(sm[k]), unmatched))
        for k, (final, code) in zip(unmatched, finals):
            row = {'الرابط': unquote(sm[k]), 'نوع الصفحة': sm_types.get(k, T_UNKNOWN)}
            if final and url_key(final) in vis_keys:
                row['الوجهة النهائية'] = unquote(final)
                redirects.append(row)
            else:
                row['كود الاستجابة'] = str(code or '—')
                orphans.append(row)
        if progress_cb:
            progress_cb(len(unmatched))

    orphan_by_type = {}
    for o in orphans:
        orphan_by_type[o['نوع الصفحة']] = orphan_by_type.get(o['نوع الصفحة'], 0) + 1

    vis_products = {k for k in vis_keys if vis_types.get(k) == T_PRODUCT}
    sm_products = {k for k in sm_keys if sm_types.get(k) == T_PRODUCT}
    matched_products = vis_products & sm_products

    return {
        'visible_count': len(vis_products),
        'sitemap_count': len(sm_products),
        'matched_count': len(matched_products),
        'visible_not_in_sitemap': [
            {'الرابط': unquote(vis[k]), 'نوع الصفحة': T_PRODUCT}
            for k in sorted(vis_products - sm_products)],
        'sitemap_not_visible': orphans,
        'sitemap_redirects': redirects,
        'orphan_by_type': orphan_by_type,
        'indexed_pct': round(len(matched_products) / len(vis_products) * 100, 1)
        if vis_products else 100.0,
    }


# ==============================================================
#  تجميع النتائج
# ==============================================================
def dedupe_pages(df):
    if df.empty:
        return df
    df = df.copy()
    src_col = '_raw_url' if '_raw_url' in df.columns else 'الرابط'
    df['_key'] = df[src_col].map(url_key)
    df['_canon'] = df.apply(
        lambda r: url_key(r['الرابط الكانوني'])
        if str(r.get('الرابط الكانوني') or '').strip() else r['_key'], axis=1)
    df = df.drop_duplicates(subset=['_key'])
    avail = df[df['متاحة'] == True]  # noqa: E712
    dup_keys = set(avail[avail.duplicated(subset=['_canon'], keep='first')]['_key'])
    df = df[~df['_key'].isin(dup_keys)]
    return df.drop(columns=['_key', '_canon']).reset_index(drop=True)


def compute_summary(df, coverage=None, images_df=None):
    ok = df[df['متاحة'] == True]  # noqa: E712
    alt_counts = {}
    uimg = unique_images(images_df)
    if uimg is not None and not uimg.empty:
        alt_counts = uimg['حالة النص البديل'].value_counts().to_dict()
    s = {
        'total_pages': len(df),
        'score': round(ok['درجة السيو'].mean(), 1) if not ok.empty else 0.0,
        'products': int((df['نوع الصفحة'] == T_PRODUCT).sum()),
        'categories': int((df['نوع الصفحة'] == T_CATEGORY).sum()),
        'info_pages': int((df['نوع الصفحة'] == T_INFO).sum()),
        'blog_pages': int((df['نوع الصفحة'] == T_BLOG).sum()),
        'unclassified': int((df['نوع الصفحة'] == T_UNKNOWN).sum()),
        'broken_pages': int((df['متاحة'] == False).sum()),  # noqa: E712
        'bad_titles': int((~ok['حالة العنوان'].isin(['optimal'])).sum()),
        'critical_titles': int(ok['حالة العنوان'].isin(
            ['missing', 'very_short', 'long']).sum()),
        'bad_descs': int((~ok['حالة الوصف'].isin(['optimal'])).sum()),
        'critical_descs': int(ok['حالة الوصف'].isin(
            ['missing', 'very_short', 'long']).sum()),
        'total_images': int(len(uimg)) if uimg is not None and not uimg.empty else 0,
        'image_slots': int(ok['إجمالي الصور'].sum()),
        'missing_alts': int(alt_counts.get('alt_missing', 0)),
        'weak_alts': int(sum(alt_counts.get(k, 0) for k in ALT_WEAK_STATES)),
        'good_alts': int(alt_counts.get('alt_ok', 0)),
        'dup_alts': int(alt_counts.get('alt_duplicate', 0)),
        'canon_missing': int((ok['حالة الكانونيكال'] == 'canon_missing').sum()),
        'canon_diff': int((ok['حالة الكانونيكال'] == 'canon_diff').sum()),
        'thin_pages': int((ok['حالة المحتوى'] == 'thin').sum()),
        'coverage_enabled': bool(coverage),
    }
    if coverage:
        s.update({
            'visible_products': coverage['visible_count'],
            'sitemap_products': coverage['sitemap_count'],
            'not_indexed_count': len(coverage['visible_not_in_sitemap']),
            'hidden_count': len(coverage['sitemap_not_visible']),
            'redirect_count': len(coverage.get('sitemap_redirects', [])),
            'orphan_by_type': coverage.get('orphan_by_type', {}),
            'indexed_pct': coverage['indexed_pct'],
        })
    return s


def localize_df(df, lang):
    if df is None or df.empty:
        return df
    out = df.copy()
    if '_raw_url' in out.columns:
        out = out.drop(columns=['_raw_url'])
    if 'نوع الصفحة' in out.columns:
        out['نوع الصفحة'] = out['نوع الصفحة'].map(lambda v: PAGE_TYPE_LABEL[lang].get(v, v))
    for col in ['حالة العنوان', 'حالة الوصف', 'حالة المحتوى', 'حالة النص البديل',
                'حالة الكانونيكال']:
        if col in out.columns:
            out[col] = out[col].map(lambda v: STATUS_LABEL[lang].get(v, v))
    if 'النص البديل الحالي (Alt)' in out.columns:
        empty = STATUS_LABEL[lang]['alt_empty']
        out['النص البديل الحالي (Alt)'] = out['النص البديل الحالي (Alt)'].map(
            lambda v: v if str(v).strip() else empty)
    if lang == 'en':
        out = out.rename(columns={k: v for k, v in COL_EN.items() if k in out.columns})
    return out


# ==============================================================
#  تقرير العميل (PDF)
# ==============================================================
PDF_TXT = {
    'ar': {
        'owner': 'أنس راشد', 'role': 'خبير تحسين محركات البحث',
        'title': 'تقرير الفحص الفني الشامل لمحركات البحث',
        'meta': 'المتجر المستهدف: {d}   |   تاريخ الفحص: {t}',
        'score': 'درجة التوافق العامة مع محركات البحث: {s}%',
        'scope': 'نطاق الفحص: الصفحات والمنتجات المعروضة فعلياً لزوار المتجر',
        'tbl1': '1. جدول بنية المتجر:',
        'tbl2': '2. جدول تدقيق أطوال العناوين والأوصاف:',
        'tbl3': '3. جدول تدقيق النصوص البديلة للصور:',
        'tbl4': '4. جدول مقارنة المعروض بخريطة الموقع:',
        'diag': '{n}. التشخيص الاستشاري وخطة العمل:',
        'h_val': 'الحالة / العدد', 'h_item': 'عنصر الفحص والتدقيق',
        'r_total': 'إجمالي الصفحات المعروضة والمفحوصة', 'u_page': 'صفحة',
        'r_products': 'صفحات المنتجات المعروضة', 'u_product': 'منتج',
        'r_categories': 'صفحات الأقسام والكولكشنات', 'u_cat': 'تصنيف',
        'r_blog': 'مقالات وصفحات المدونة', 'u_article': 'مقال',
        'r_info': 'الصفحات التعريفية والسياسات',
        'r_broken': 'روابط معطلة داخل المتجر', 'u_link': 'رابط',
        'r_platform': 'منصة المتجر',
        'r_titles_ok': 'عناوين ضمن الطول المثالي (50-60 حرفاً)',
        'r_titles_crit': 'عناوين مفقودة أو قصيرة جداً أو تتجاوز 60 حرفاً',
        'u_title': 'عنوان',
        'r_descs_ok': 'أوصاف ضمن الطول المثالي (120-150 حرفاً)',
        'r_descs_crit': 'أوصاف مفقودة أو قصيرة جداً أو تتجاوز 150 حرفاً',
        'u_desc': 'وصف',
        'r_canon': 'صفحات بلا وسم كانونيكال',
        'r_thin': 'صفحات بمحتوى نصي ضعيف',
        'r_imgs': 'إجمالي صور المحتوى والمنتجات', 'u_img': 'صورة',
        'r_noalt': 'صور بلا نص بديل إطلاقاً',
        'r_generic': 'صور بنص بديل غير وصفي (اسم ملف أو كلمة عامة)',
        'r_dup': 'صور تتشارك نفس النص البديل',
        'r_altok': 'صور بنص بديل سليم',
        'r_imgstate': 'حالة تهيئة الصور لبحث صور جوجل',
        'img_none': 'لم يرصد الفحص صور محتوى', 'img_ok': 'مكتمل',
        'img_gap': 'فجوة واسعة', 'img_part': 'فجوة جزئية',
        'r_vis': 'منتجات معروضة لزوار المتجر',
        'r_sm': 'منتجات معلنة في خريطة الموقع',
        'r_notidx': 'منتجات معروضة ولا تظهر في الخريطة',
        'r_redirect': 'روابط في الخريطة تعيد التوجيه لصفحات أخرى',
        'r_orphan': 'صفحات في الخريطة لا يصل إليها الزائر بأي رابط',
        'r_idxpct': 'نسبة المنتجات المعروضة المدرجة في الخريطة',
        'footer': 'anasrashed.com   |   anas@anasrashed.com',
    },
    'en': {
        'owner': 'Anas Rashed', 'role': 'SEO Expert',
        'title': 'Comprehensive Technical SEO Audit Report',
        'meta': 'Store: {d}   |   Audit date: {t}',
        'score': 'Overall search engine compliance score: {s}%',
        'scope': 'Audit scope: pages and products actually visible to store visitors',
        'tbl1': '1. Store structure:',
        'tbl2': '2. Title and description length audit:',
        'tbl3': '3. Image alt text audit:',
        'tbl4': '4. Visible catalogue vs sitemap comparison:',
        'diag': '{n}. Consultant diagnosis and action plan:',
        'h_val': 'Value / Count', 'h_item': 'Audited item',
        'r_total': 'Total visible pages audited', 'u_page': 'pages',
        'r_products': 'Visible product pages', 'u_product': 'products',
        'r_categories': 'Category and collection pages', 'u_cat': 'categories',
        'r_blog': 'Blog posts and articles', 'u_article': 'articles',
        'r_info': 'Info and policy pages',
        'r_broken': 'Broken links inside the store', 'u_link': 'links',
        'r_platform': 'Store platform',
        'r_titles_ok': 'Titles within optimal length (50-60 chars)',
        'r_titles_crit': 'Titles missing, far too short, or over 60 characters',
        'u_title': 'titles',
        'r_descs_ok': 'Descriptions within optimal length (120-150 chars)',
        'r_descs_crit': 'Descriptions missing, far too short, or over 150 characters',
        'u_desc': 'descriptions',
        'r_canon': 'Pages without a canonical tag',
        'r_thin': 'Pages with thin text content',
        'r_imgs': 'Total content and product images', 'u_img': 'images',
        'r_noalt': 'Images with no alt text at all',
        'r_generic': 'Images with non-descriptive alt text (filename or generic word)',
        'r_dup': 'Images sharing identical alt text',
        'r_altok': 'Images with sound alt text',
        'r_imgstate': 'Readiness for Google Image search',
        'img_none': 'No content images detected', 'img_ok': 'Complete',
        'img_gap': 'Major gap', 'img_part': 'Partial gap',
        'r_vis': 'Products visible to visitors',
        'r_sm': 'Products declared in sitemap',
        'r_notidx': 'Visible products absent from sitemap',
        'r_redirect': 'Sitemap URLs redirecting elsewhere',
        'r_orphan': 'Sitemap pages with no link path for visitors',
        'r_idxpct': 'Visible products included in sitemap',
        'footer': 'anasrashed.com   |   anas@anasrashed.com',
    },
}


def shape_ar(text):
    return get_display(arabic_reshaper.reshape(str(text)))


def build_diagnosis(score, stats, lang):
    imgs = stats.get('total_images', 0)
    missing = stats.get('missing_alts', 0)
    generic = stats.get('weak_alts', 0)
    issues = []

    if lang == 'ar':
        if missing > 0 and imgs > 0:
            issues.append(f"{missing} صورة من أصل {imgs} بلا نص بديل إطلاقاً "
                          f"(بنسبة {round(missing / imgs * 100, 1)}%)، وهو ما يحرم المتجر "
                          "من الظهور في بحث صور جوجل")
        if generic > 0:
            issues.append(f"{generic} صورة نصها البديل موجود لكنه غير وصفي أو مكرر "
                          "أو محشو بالكلمات، فلا يضيف قيمة لمحركات البحث")
        if stats.get('bad_titles', 0) > 0:
            issues.append(f"{stats['bad_titles']} عنوان ميتا خارج الطول المثالي "
                          f"(50-60 حرفاً)، منها {stats.get('critical_titles', 0)} عنوان "
                          "مفقود أو قصير جداً أو يُقتطع في نتائج البحث")
        if stats.get('bad_descs', 0) > 0:
            issues.append(f"{stats['bad_descs']} وصف ميتا خارج الطول المثالي "
                          f"(120-150 حرفاً)، منها {stats.get('critical_descs', 0)} "
                          "وصف مفقود أو قصير جداً أو يتجاوز الحد")
        if stats.get('canon_missing', 0) > 0:
            issues.append(f"{stats['canon_missing']} صفحة بلا وسم كانونيكال، "
                          "ما يعرّض المتجر لتكرار المحتوى")
        if stats.get('hidden_count', 0) > 0:
            issues.append(f"{stats['hidden_count']} صفحة منشورة في خريطة الموقع "
                          "لا يصل إليها الزائر بأي رابط داخلي، فتفقد قيمتها")
        if stats.get('redirect_count', 0) > 0:
            issues.append(f"{stats['redirect_count']} رابط في خريطة الموقع يعيد التوجيه "
                          "لصفحة أخرى، ما يستهلك ميزانية زحف المتجر بلا فائدة")
        if stats.get('not_indexed_count', 0) > 0:
            issues.append(f"{stats['not_indexed_count']} منتجاً معروضاً لا يظهر "
                          "في خريطة الموقع")
        if stats.get('broken_pages', 0) > 0:
            issues.append(f"{stats['broken_pages']} رابط معطل يصل إليه الزائر")

        if not issues:
            return ("لم يرصد الفحص فجوات جوهرية في الصفحات المعروضة: العناوين والأوصاف "
                    "والنصوص البديلة وبنية الروابط ضمن المعايير الموصى بها. يوصى بمتابعة "
                    "دورية عند إضافة منتجات أو أقسام جديدة.")
        body = "أظهر الفحص الفني: " + "، و".join(issues) + ". "
        if score < 60:
            body += ("تشير النتيجة الإجمالية إلى فجوة واسعة في تهيئة المتجر لمحركات "
                     "البحث. يوصى بإعادة كتابة البيانات الوصفية وإسناد نصوص بديلة "
                     "وصفية لجميع صور المحتوى ضمن خطة عمل مرحلية.")
        elif score < 80:
            body += ("المتجر مهيأ جزئياً، ومعالجة العناصر أعلاه من شأنها رفع درجة "
                     "التوافق وتحسين فرص الظهور في نتائج البحث.")
        else:
            body += ("المستوى العام جيد، وتبقى المعالجات المذكورة تحسينات تكميلية "
                     "يمكن تنفيذها ضمن جولة مراجعة واحدة.")
        return body

    if missing > 0 and imgs > 0:
        issues.append(f"{missing} of {imgs} images ({round(missing / imgs * 100, 1)}%) "
                      "carry no alt text at all, excluding the store from Google Image search")
    if generic > 0:
        issues.append(f"{generic} images have alt text that is present but non-descriptive, "
                      "duplicated, or keyword-stuffed")
    if stats.get('bad_titles', 0) > 0:
        issues.append(f"{stats['bad_titles']} meta titles fall outside the optimal 50-60 "
                      f"character range, {stats.get('critical_titles', 0)} of them critically")
    if stats.get('bad_descs', 0) > 0:
        issues.append(f"{stats['bad_descs']} meta descriptions fall outside the optimal "
                      f"120-150 character range, {stats.get('critical_descs', 0)} critically")
    if stats.get('canon_missing', 0) > 0:
        issues.append(f"{stats['canon_missing']} pages have no canonical tag, exposing "
                      "the store to duplicate content")
    if stats.get('hidden_count', 0) > 0:
        issues.append(f"{stats['hidden_count']} sitemap pages have no internal link path "
                      "for visitors and therefore lose their value")
    if stats.get('redirect_count', 0) > 0:
        issues.append(f"{stats['redirect_count']} sitemap URLs redirect elsewhere, "
                      "consuming crawl budget without benefit")
    if stats.get('broken_pages', 0) > 0:
        issues.append(f"{stats['broken_pages']} broken links are reachable by visitors")

    if not issues:
        return ("The audit found no material gaps across the visible pages: titles, "
                "descriptions, alt text and link structure all fall within recommended "
                "standards. Periodic review is advised as new products are added.")
    body = "The technical audit found: " + "; ".join(issues) + ". "
    if score < 60:
        body += ("The overall score indicates a substantial gap in search engine readiness. "
                 "Rewriting metadata and assigning descriptive alt text to all content "
                 "images is recommended as a phased programme of work.")
    elif score < 80:
        body += ("The store is partially optimised. Addressing the items above would raise "
                 "the compliance score and improve search visibility.")
    else:
        body += ("The overall standard is good; the remaining items are incremental "
                 "improvements that can be handled in a single review cycle.")
    return body


def generate_client_pdf(domain, score, stats, lang='ar'):
    rtl = (lang == 'ar')
    if rtl and not FONT_PATH.exists():
        raise FileNotFoundError(f"ملف الخط غير موجود: {FONT_PATH}")

    T = PDF_TXT[lang]
    fmt = shape_ar if rtl else (lambda x: str(x))
    align_text = "R" if rtl else "L"
    font_name = "Amiri" if rtl else "Helvetica"
    clean_domain = urlparse(domain).netloc or domain
    logo_exists = LOGO_PATH.exists()

    class Report(FPDF):
        def header(self):
            if logo_exists:
                try:
                    self.image(str(LOGO_PATH), x=15 if rtl else 163, y=9, h=13)
                except Exception:
                    pass
            self.set_font(font_name, "", 14)
            self.set_text_color(15, 23, 42)
            self.cell(0, 7, fmt(T['owner']), ln=True, align=align_text)
            self.set_font(font_name, "", 10)
            self.set_text_color(100, 116, 139)
            self.cell(0, 5, fmt(T['role']), ln=True, align=align_text)
            self.set_draw_color(226, 232, 240)
            self.line(15, 27, 195, 27)
            self.ln(6)

        def footer(self):
            self.set_y(-15)
            self.set_draw_color(226, 232, 240)
            self.line(15, 282, 195, 282)
            self.set_font(font_name, "", 9)
            self.set_text_color(148, 163, 184)
            self.cell(0, 10, T['footer'], align="C")

    pdf = Report()
    if rtl:
        pdf.add_font("Amiri", "", str(FONT_PATH))
    pdf.add_page()

    pdf.set_font(font_name, "", 16)
    pdf.set_text_color(15, 23, 42)
    pdf.cell(0, 8, fmt(T['title']), ln=True, align="C")
    pdf.set_font(font_name, "", 11)
    pdf.set_text_color(71, 85, 105)
    pdf.cell(0, 6, fmt(T['meta'].format(d=clean_domain,
                                        t=datetime.now().strftime('%Y-%m-%d'))),
             ln=True, align="C")
    pdf.set_font(font_name, "", 9)
    pdf.set_text_color(100, 116, 139)
    pdf.cell(0, 5, fmt(T['scope']), ln=True, align="C")
    pdf.ln(3)

    y0 = pdf.get_y()
    pdf.set_fill_color(248, 250, 252)
    pdf.set_draw_color(203, 213, 225)
    pdf.rect(15, y0, 180, 16, 'DF')
    pdf.set_xy(15, y0 + 3)
    pdf.set_font(font_name, "", 15)
    pdf.set_text_color(*((225, 29, 72) if score < 60 else
                         (217, 119, 6) if score < 80 else (16, 185, 129)))
    pdf.cell(180, 10, fmt(T['score'].format(s=score)), align="C")
    pdf.set_y(y0 + 22)

    def draw_table(title, rows, col_widths=(120, 60)):
        tw = sum(col_widths)
        sx = (210 - tw) / 2
        if pdf.get_y() + (len(rows) + 3) * 6.5 > 268:
            pdf.add_page()
        pdf.set_x(sx)
        pdf.set_font(font_name, "", 12)
        pdf.set_text_color(15, 23, 42)
        pdf.cell(tw, 7, fmt(title), ln=True, align=align_text)
        pdf.ln(1)
        pdf.set_x(sx)
        pdf.set_fill_color(241, 245, 249)
        pdf.set_draw_color(203, 213, 225)
        pdf.set_font(font_name, "", 10)
        pdf.set_text_color(30, 41, 59)
        if rtl:
            pdf.cell(col_widths[1], 7, fmt(T['h_val']), 1, 0, 'C', fill=True)
            pdf.cell(col_widths[0], 7, fmt(T['h_item']), 1, 1, 'C', fill=True)
        else:
            pdf.cell(col_widths[0], 7, T['h_item'], 1, 0, 'C', fill=True)
            pdf.cell(col_widths[1], 7, T['h_val'], 1, 1, 'C', fill=True)
        pdf.set_font(font_name, "", 9)
        for label, val in rows:
            pdf.set_x(sx)
            pdf.set_text_color(71, 85, 105)
            if rtl:
                pdf.cell(col_widths[1], 6, fmt(val), 1, 0, 'C')
                pdf.cell(col_widths[0], 6, fmt(label), 1, 1, 'R')
            else:
                pdf.cell(col_widths[0], 6, str(label), 1, 0, 'L')
                pdf.cell(col_widths[1], 6, str(val), 1, 1, 'C')
        pdf.ln(5)

    draw_table(T['tbl1'], [
        (T['r_total'], f"{stats['total_pages']} {T['u_page']}"),
        (T['r_products'], f"{stats['products']} {T['u_product']}"),
        (T['r_categories'], f"{stats['categories']} {T['u_cat']}"),
        (T['r_blog'], f"{stats.get('blog_pages', 0)} {T['u_article']}"),
        (T['r_info'], f"{stats['info_pages']} {T['u_page']}"),
        (T['r_broken'], f"{stats.get('broken_pages', 0)} {T['u_link']}"),
        (T['r_platform'], stats.get('platform_label', '—')),
    ])

    tot = max(stats['total_pages'] - stats.get('broken_pages', 0), 1)
    draw_table(T['tbl2'], [
        (T['r_titles_ok'], f"{tot - stats['bad_titles']} / {tot}"),
        (T['r_titles_crit'], f"{stats.get('critical_titles', 0)} {T['u_title']}"),
        (T['r_descs_ok'], f"{tot - stats['bad_descs']} / {tot}"),
        (T['r_descs_crit'], f"{stats.get('critical_descs', 0)} {T['u_desc']}"),
        (T['r_canon'], f"{stats.get('canon_missing', 0)} {T['u_page']}"),
        (T['r_thin'], f"{stats.get('thin_pages', 0)} {T['u_page']}"),
    ])

    imgs = stats.get('total_images', 0)
    noalt = stats.get('missing_alts', 0)
    weak = stats.get('weak_alts', 0)
    healthy = stats.get('good_alts', 0)
    ratio = round(((noalt + weak) / imgs * 100), 1) if imgs else 0
    state = (T['img_none'] if imgs == 0 else T['img_ok'] if (noalt + weak) == 0
             else T['img_gap'] if ratio > 50 else T['img_part'])
    draw_table(T['tbl3'], [
        (T['r_imgs'], f"{imgs} {T['u_img']}"),
        (T['r_noalt'], f"{noalt} {T['u_img']}"),
        (T['r_generic'], f"{weak - stats.get('dup_alts', 0)} {T['u_img']}"),
        (T['r_dup'], f"{stats.get('dup_alts', 0)} {T['u_img']}"),
        (T['r_altok'], f"{healthy} {T['u_img']}"),
        (T['r_imgstate'], state),
    ])

    if stats.get('coverage_enabled'):
        draw_table(T['tbl4'], [
            (T['r_vis'], f"{stats.get('visible_products', 0)} {T['u_product']}"),
            (T['r_sm'], f"{stats.get('sitemap_products', 0)} {T['u_product']}"),
            (T['r_notidx'], f"{stats.get('not_indexed_count', 0)} {T['u_product']}"),
            (T['r_redirect'], f"{stats.get('redirect_count', 0)} {T['u_link']}"),
            (T['r_orphan'], f"{stats.get('hidden_count', 0)} {T['u_page']}"),
            (T['r_idxpct'], f"{stats.get('indexed_pct', 0)}%"),
        ])
        diag_n = "5"
    else:
        diag_n = "4"

    bw = 180
    bx = (210 - bw) / 2
    pdf.set_x(bx)
    pdf.set_font(font_name, "", 12)
    pdf.set_text_color(15, 23, 42)
    pdf.cell(bw, 6, fmt(T['diag'].format(n=diag_n)), ln=True, align=align_text)
    pdf.ln(1)

    text = build_diagnosis(score, stats, lang)
    pdf.set_font(font_name, "", 9)
    maxw = bw - 10
    lines, cur = [], ""
    for word in text.split():
        trial = (cur + " " + word).strip()
        if pdf.get_string_width(fmt(trial)) <= maxw:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)

    lh = 4.8
    bh = len(lines) * lh + 6
    if pdf.get_y() + bh > 265:
        pdf.add_page()
    by = pdf.get_y()
    pdf.set_fill_color(248, 250, 252)
    pdf.set_draw_color(226, 232, 240)
    pdf.rect(bx, by, bw, bh, 'DF')
    pdf.set_xy(bx + 5, by + 3)
    pdf.set_text_color(71, 85, 105)
    for line in lines:
        pdf.set_x(bx + 5)
        pdf.cell(maxw, lh, fmt(line), ln=True, align=align_text)

    return bytes(pdf.output())


# ==============================================================
#  حزمة الملفات
# ==============================================================
ZIP_NAMES = {
    'ar': {T_PRODUCT: "1_المنتجات.csv", T_CATEGORY: "2_التصنيفات.csv",
           T_BLOG: "3_المدونة.csv", T_INFO: "4_الصفحات_التعريفية.csv",
           T_HOME: "5_الصفحة_الرئيسية.csv", T_UNKNOWN: "6_غير_مصنفة.csv",
           T_BROKEN: "7_روابط_معطلة.csv", 'images': "8_تدقيق_الصور.csv",
           'notidx': "9_منتجات_غير_مدرجة_في_الخريطة.csv",
           'orphan': "10_صفحات_يتيمة_في_الخريطة.csv",
           'redirect': "11_روابط_الخريطة_المحوّلة.csv",
           'excel': "التقرير_الشامل.xlsx"},
    'en': {T_PRODUCT: "1_products.csv", T_CATEGORY: "2_categories.csv",
           T_BLOG: "3_blog.csv", T_INFO: "4_info_pages.csv",
           T_HOME: "5_homepage.csv", T_UNKNOWN: "6_unclassified.csv",
           T_BROKEN: "7_broken_links.csv", 'images': "8_image_alt_audit.csv",
           'notidx': "9_products_missing_from_sitemap.csv",
           'orphan': "10_orphan_sitemap_pages.csv",
           'redirect': "11_redirecting_sitemap_urls.csv",
           'excel': "full_audit_report.xlsx"},
}


def build_zip(df, images_df, coverage=None, lang='ar'):
    names = ZIP_NAMES[lang]
    ldf = localize_df(df, lang)
    limg = localize_df(unique_images(images_df), lang)
    type_col = COL_EN['نوع الصفحة'] if lang == 'en' else 'نوع الصفحة'

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for tkey in PAGE_TYPE_ORDER:
            label = PAGE_TYPE_LABEL[lang][tkey]
            sub = ldf[ldf[type_col] == label] if type_col in ldf.columns else pd.DataFrame()
            if not sub.empty:
                z.writestr(names[tkey], sub.to_csv(index=False, encoding='utf-8-sig'))
        if limg is not None and not limg.empty:
            z.writestr(names['images'], limg.to_csv(index=False, encoding='utf-8-sig'))

        if coverage:
            for key, data in [('notidx', coverage.get('visible_not_in_sitemap')),
                              ('orphan', coverage.get('sitemap_not_visible')),
                              ('redirect', coverage.get('sitemap_redirects'))]:
                if data:
                    z.writestr(names[key],
                               localize_df(pd.DataFrame(data), lang)
                               .to_csv(index=False, encoding='utf-8-sig'))

        xbuf = io.BytesIO()
        with pd.ExcelWriter(xbuf, engine='openpyxl') as w:
            ldf.to_excel(w, index=False,
                         sheet_name='Pages Audit' if lang == 'en' else 'فحص الصفحات')
            if limg is not None and not limg.empty:
                limg.to_excel(w, index=False,
                              sheet_name='Images Audit' if lang == 'en' else 'فحص الصور')
        z.writestr(names['excel'], xbuf.getvalue())
    return buf.getvalue()


# ==============================================================
#  الواجهة
# ==============================================================
render_brandbar()

with st.sidebar:
    st.markdown("### 🧭 القائمة")
    nav = st.radio("", ["🔍 فحص متجر جديد", "📁 سجل المتاجر"], label_visibility="collapsed")
    st.markdown("---")
    st.markdown("#### ⚙️ إعدادات الفحص")
    max_pages = st.number_input("الحد الأقصى للصفحات", 50, 5000, MAX_PAGES_DEFAULT, 50)
    workers = st.slider("المسارات المتوازية", 1, 8, 4)
    do_pagination = st.checkbox("متابعة ترقيم الأقسام", value=True,
                                help="يلتقط المنتجات في الصفحات التالية من كل قسم.")
    do_sitemap_check = st.checkbox("مقارنة مع خريطة الموقع", value=True,
                                   help="تشخيصية فقط — لا تؤثر على أرقام الفحص.")
    st.markdown("---")
    st.caption("الأداة معايرة على منصات سلة وزد وشوبيفاي.")

if nav == "🔍 فحص متجر جديد":
    c1, c2 = st.columns([5, 1])
    with c1:
        input_url = st.text_input("رابط المتجر الإلكتروني",
                                  value=st.session_state.current_url,
                                  placeholder="https://example.store")
    with c2:
        st.write("")
        st.write("")
        start_btn = st.button("بدء الفحص", type="primary", use_container_width=True)

    if st.session_state.audit_df is not None:
        if st.sidebar.button("🔄 تفريغ الشاشة", use_container_width=True):
            for k in ['audit_df', 'images_df', 'summary', 'coverage']:
                st.session_state[k] = None
            st.session_state.current_url = ""
            st.rerun()

    if start_btn and input_url:
        target = normalize_url(input_url)
        st.session_state.current_url = target

        with st.status("جارٍ الفحص...", expanded=True) as status:
            st.write("**المرحلة 1** — تصفح المتجر من الصفحة الرئيسية")
            bar1 = st.progress(0)
            note1 = st.empty()

            def crawl_cb(done, pending, level):
                bar1.progress(min(done / max(done + pending, 1), 1.0))
                note1.caption(f"المستوى {level} · فُحصت {done} صفحة · "
                              f"{pending} رابط في الانتظار")

            pages, imgs, cat_urls, seen, platform = crawl_store(
                target, max_pages, workers, crawl_cb)
            bar1.progress(1.0)
            st.session_state.platform = platform

            if do_pagination and cat_urls:
                st.write("**المرحلة 2** — متابعة ترقيم صفحات الأقسام")
                bar2 = st.progress(0)
                note2 = st.empty()

                def pag_cb(i, total, found, fetched):
                    bar2.progress(min(i / max(total, 1), 1.0))
                    note2.caption(f"{i}/{total} قسم · {found} منتج إضافي · "
                                  f"{fetched} صفحة مجلوبة")

                extra = harvest_paginated_products(target, cat_urls, seen, pag_cb)
                if extra:
                    st.write(f"**المرحلة 3** — فحص {len(extra)} منتج من الصفحات التالية")
                    bar3 = st.progress(0)
                    p2, i2 = audit_urls(extra, target, 'ترقيم الأقسام', workers, bar3)
                    pages += p2
                    imgs += i2

            df = dedupe_pages(pd.DataFrame(pages))
            images_df = pd.DataFrame(imgs)
            if not images_df.empty:
                images_df = images_df[images_df['رابط الصفحة'].isin(df['الرابط'])] \
                    .copy().reset_index(drop=True)
                images_df = apply_duplicate_alt(images_df)
            df = score_pages(df, images_df)

            coverage = None
            if do_sitemap_check:
                st.write("**المرحلة 4** — مقارنة تشخيصية مع خريطة الموقع")
                note4 = st.empty()
                sm_urls = collect_sitemap_urls(target)
                note4.caption(f"{len(sm_urls)} رابط في الخريطة · جارٍ التحقق من "
                              "وجهة الروابط غير المطابقة")
                coverage = build_coverage_report(df, sm_urls, target, workers)

            summary = compute_summary(df, coverage, images_df)
            summary['platform'] = platform
            summary['platform_label'] = PLATFORM_LABEL.get(platform, '—')
            status.update(label="اكتمل الفحص", state="complete", expanded=False)

        st.session_state.audit_df = df
        st.session_state.images_df = images_df
        st.session_state.summary = summary
        st.session_state.coverage = coverage

        conn = sqlite3.connect(DB_FILE)
        conn.cursor().execute(
            '''INSERT INTO audits (domain, scan_date, score, total_pages, products_count,
               categories_count, info_pages_count, blog_pages_count, data_json,
               images_json, coverage_json, platform) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
            (target, datetime.now().strftime("%Y-%m-%d %H:%M"), summary['score'],
             summary['total_pages'], summary['products'], summary['categories'],
             summary['info_pages'], summary['blog_pages'], df.to_json(orient='records'),
             images_df.to_json(orient='records') if not images_df.empty else '',
             json.dumps(coverage, ensure_ascii=False) if coverage else '', platform))
        conn.commit()
        conn.close()

    if st.session_state.audit_df is not None:
        df = st.session_state.audit_df
        images_df = st.session_state.images_df
        summary = st.session_state.summary
        coverage = st.session_state.coverage
        platform = st.session_state.platform

        sc = summary['score']
        sc_color = COLOR['bad'] if sc < 60 else COLOR['warn'] if sc < 80 else COLOR['ok']
        plat_txt = PLATFORM_LABEL.get(platform, '—')
        st.markdown(
            f'<div class="hero">'
            f'<div><div class="score" style="color:{sc_color}">{sc}%</div>'
            f'<div class="scorelbl">درجة التوافق مع محركات البحث</div></div>'
            f'<div><div class="store">{urlparse(st.session_state.current_url).netloc}</div>'
            f'<div class="plat">المنصة: {plat_txt} · '
            f'{datetime.now().strftime("%Y-%m-%d")}</div></div></div>',
            unsafe_allow_html=True)

        if platform not in SUPPORTED_PLATFORMS:
            st.warning("لم يتم التعرف على المنصة كسلة أو زد أو شوبيفاي. الأداة معايرة "
                       "على هذه المنصات الثلاث — راجع تبويب التحقق اليدوي قبل إرسال "
                       "التقرير لأي عميل.")

        cards = [
            (summary["total_pages"], "الصفحات المعروضة", COLOR['accent']),
            (summary["products"], "المنتجات", COLOR['accent']),
            (summary["categories"], "الأقسام", COLOR['accent']),
            (summary["blog_pages"], "المدونة",
             COLOR['warn'] if summary["blog_pages"] == 0 else COLOR['accent']),
            (summary["info_pages"], "التعريفية", COLOR['accent']),
            (summary["missing_alts"], "صور بلا Alt",
             COLOR['bad'] if summary["missing_alts"] else COLOR['ok']),
            (summary.get("broken_pages", 0), "روابط معطلة",
             COLOR['bad'] if summary.get("broken_pages") else COLOR['ok']),
        ]
        for col, (v, l, c) in zip(st.columns(7), cards):
            with col:
                st.markdown(metric_card(v, l, c), unsafe_allow_html=True)

        st.write("")
        view_df = localize_df(df, 'ar')
        uimgs = unique_images(images_df)
        view_imgs = localize_df(uimgs, 'ar')
        tabs = st.tabs(["📊 نظرة عامة", "📄 الصفحات", "🖼️ الصور",
                        "🗺️ خريطة الموقع", "🔬 التحقق اليدوي", "📥 التصدير"])

        # ---------------- نظرة عامة ----------------
        with tabs[0]:
            L = STATUS_LABEL['ar']
            ok = df[df['متاحة'] == True]  # noqa: E712
            g1, g2 = st.columns(2)

            with g1:
                items = [(PAGE_TYPE_LABEL['ar'][t], int((df['نوع الصفحة'] == t).sum()))
                         for t in PAGE_TYPE_ORDER if (df['نوع الصفحة'] == t).any()]
                st.markdown(bar_chart("توزيع أنواع الصفحات", items),
                            unsafe_allow_html=True)

                tcounts = ok['حالة العنوان'].value_counts()
                items = [(L[k], int(tcounts.get(k, 0)))
                         for k in ['optimal', 'acceptable', 'very_short', 'long', 'missing']
                         if tcounts.get(k, 0)]
                st.markdown(bar_chart("حالة عناوين الميتا", items, {
                    L['optimal']: COLOR['ok'], L['acceptable']: COLOR['warn'],
                    L['very_short']: COLOR['bad'], L['long']: COLOR['bad'],
                    L['missing']: COLOR['bad']}), unsafe_allow_html=True)

            with g2:
                if images_df is not None and not images_df.empty:
                    acounts = uimgs['حالة النص البديل'].value_counts()
                    items = [(L[k], int(acounts.get(k, 0)))
                             for k in ['alt_ok', 'alt_duplicate', 'alt_long',
                                       'alt_stuffed', 'alt_generic', 'alt_missing']
                             if acounts.get(k, 0)]
                    st.markdown(bar_chart("جودة النصوص البديلة للصور", items, {
                        L['alt_ok']: COLOR['ok'], L['alt_duplicate']: COLOR['warn'],
                        L['alt_long']: COLOR['warn'], L['alt_stuffed']: COLOR['bad'],
                        L['alt_generic']: COLOR['bad'], L['alt_missing']: COLOR['bad']}),
                        unsafe_allow_html=True)

                dcounts = ok['حالة الوصف'].value_counts()
                items = [(L[k], int(dcounts.get(k, 0)))
                         for k in ['optimal', 'acceptable', 'very_short', 'long', 'missing']
                         if dcounts.get(k, 0)]
                st.markdown(bar_chart("حالة أوصاف الميتا", items, {
                    L['optimal']: COLOR['ok'], L['acceptable']: COLOR['warn'],
                    L['very_short']: COLOR['bad'], L['long']: COLOR['bad'],
                    L['missing']: COLOR['bad']}), unsafe_allow_html=True)

            st.markdown("#### أبرز النتائج")
            out = []
            if summary['missing_alts']:
                out.append((f"<b>{summary['missing_alts']}</b> صورة بلا نص بديل إطلاقاً "
                            f"من أصل {summary['total_images']} — أكبر فجوة قابلة "
                            "للإصلاح في المتجر.", 'bad'))
            if summary['weak_alts']:
                out.append((f"<b>{summary['weak_alts']}</b> صورة نصها البديل موجود لكنه "
                            "غير وصفي أو مكرر — يمر كسليم في الأدوات السطحية.", 'warn'))
            if summary['critical_titles']:
                out.append((f"<b>{summary['critical_titles']}</b> عنوان مفقود أو قصير جداً "
                            "أو يُقتطع في نتائج البحث.", 'bad'))
            if summary['critical_descs']:
                out.append((f"<b>{summary['critical_descs']}</b> وصف ميتا خارج الحدود "
                            "المفيدة.", 'warn'))
            if summary['canon_missing']:
                out.append((f"<b>{summary['canon_missing']}</b> صفحة بلا وسم كانونيكال — "
                            "خطر تكرار المحتوى.", 'warn'))
            if summary.get('hidden_count'):
                bt = summary.get('orphan_by_type', {})
                brk = "، ".join(f"{PAGE_TYPE_LABEL['ar'].get(k, k)}: {v}"
                                for k, v in bt.items())
                out.append((f"<b>{summary['hidden_count']}</b> صفحة يتيمة في خريطة الموقع "
                            f"({brk}) — منشورة ولا يصل إليها أحد.", 'warn'))
            if summary.get('redirect_count'):
                out.append((f"<b>{summary['redirect_count']}</b> رابط في الخريطة يعيد "
                            "التوجيه لصفحة أخرى — هدر لميزانية الزحف.", 'warn'))
            if summary['broken_pages']:
                out.append((f"<b>{summary['broken_pages']}</b> رابط معطل يصل إليه الزائر.",
                            'bad'))
            if summary['thin_pages']:
                out.append((f"<b>{summary['thin_pages']}</b> صفحة بمحتوى نصي ضعيف "
                            "(أقل من 50 كلمة).", 'warn'))
            if not out:
                out.append(("لم يرصد الفحص فجوات جوهرية في الصفحات المعروضة.", 'ok'))
            for text, lvl in out:
                st.markdown(finding(text, lvl), unsafe_allow_html=True)

        # ---------------- الصفحات ----------------
        with tabs[1]:
            present = [PAGE_TYPE_LABEL['ar'][t] for t in PAGE_TYPE_ORDER
                       if (df['نوع الصفحة'] == t).any()]
            f1, f2 = st.columns([2, 3])
            with f1:
                sel = st.selectbox("نوع الصفحة", ["الكل"] + present)
            with f2:
                only_issues = st.checkbox("عرض الصفحات التي بها مشاكل فقط", value=False)

            d = view_df if sel == "الكل" else view_df[view_df['نوع الصفحة'] == sel]
            if only_issues:
                d = d[(d['حالة العنوان'] != STATUS_LABEL['ar']['optimal']) |
                      (d['حالة الوصف'] != STATUS_LABEL['ar']['optimal']) |
                      (d['صور بدون Alt'] > 0) | (d['متاحة'] == False)]  # noqa: E712
            d = d.copy().reset_index(drop=True)
            d.index = d.index + 1
            st.dataframe(d, use_container_width=True, height=460,
                         column_config={"الرابط": st.column_config.LinkColumn(
                             "الرابط", width="large"),
                             "درجة السيو": st.column_config.ProgressColumn(
                                 "درجة السيو", min_value=0, max_value=100, format="%d")})
            langs = df[df['متاحة'] == True]['لغة الصفحة'].value_counts()  # noqa: E712
            st.caption(
                f"معايير الطول — العنوان مثالي {TITLE_MIN_OPTIMAL}-{TITLE_MAX} حرفاً "
                f"(مقبول من {TITLE_MIN_OK})، الوصف مثالي {DESC_MIN_OPTIMAL}-{DESC_MAX} "
                f"حرفاً (مقبول من {DESC_MIN_OK}). يُحسب الطول بالحروف شاملاً المسافات "
                "وعلامات الترقيم. · لغات الصفحات: " +
                "، ".join(f"{k}: {v}" for k, v in langs.items()))

        # ---------------- الصور ----------------
        with tabs[2]:
            if view_imgs is not None and not view_imgs.empty:
                L = STATUS_LABEL['ar']
                f = st.selectbox("تصفية", ["الكل", "بلا نص بديل", "نص بديل ضعيف",
                                           "نص بديل سليم"])
                v = view_imgs
                if f == "بلا نص بديل":
                    v = view_imgs[view_imgs['حالة النص البديل'] == L['alt_missing']]
                elif f == "نص بديل ضعيف":
                    v = view_imgs[view_imgs['حالة النص البديل'].isin(
                        [L[k] for k in ALT_WEAK_STATES])]
                elif f == "نص بديل سليم":
                    v = view_imgs[view_imgs['حالة النص البديل'] == L['alt_ok']]
                v = v.copy().reset_index(drop=True)
                v.index = v.index + 1
                st.dataframe(v, use_container_width=True, height=460,
                             column_config={
                                 "رابط الصورة": st.column_config.ImageColumn(
                                     "معاينة", width="small"),
                                 "رابط الصفحة": st.column_config.LinkColumn(
                                     "رابط الصفحة", width="medium")})
                st.caption(f"الجدول يعرض {len(view_imgs)} صورة فريدة. عمود «عدد الصفحات» "
                           "يبيّن كم صفحة تظهر فيها الصورة — ظهور الصورة نفسها في "
                           "الرئيسية والقسم وصفحة المنتج أمر طبيعي وليس تكراراً. · "
                           "معايير التقييم — النص البديل يُقيَّم بجودته لا بطوله: "
                           "الغياب، أو النص غير الوصفي (اسم ملف أو كلمة عامة)، أو حشو "
                           f"الكلمات، أو تكراره على {ALT_DUP_THRESHOLD} صور فأكثر، أو "
                           f"تجاوزه {ALT_MAX} حرفاً (حد قارئات الشاشة).")
            else:
                st.info("لا توجد صور محتوى مرصودة.")

        # ---------------- خريطة الموقع ----------------
        with tabs[3]:
            if not coverage:
                st.info("لم تُفعّل المقارنة مع خريطة الموقع في هذا الفحص.")
            else:
                st.caption("هذه المقارنة تشخيصية ولا تؤثر على أرقام الفحص أعلاه.")
                m = st.columns(4)
                m[0].metric("منتجات معروضة للزائر", coverage['visible_count'])
                m[1].metric("منتجات في الخريطة", coverage['sitemap_count'])
                m[2].metric("معروضة وخارج الخريطة",
                            len(coverage['visible_not_in_sitemap']))
                m[3].metric("نسبة الإدراج", f"{coverage['indexed_pct']}%")
                st.write("")

                if coverage['visible_not_in_sitemap']:
                    st.markdown(finding(
                        f"<b>{len(coverage['visible_not_in_sitemap'])}</b> منتج يراه الزائر "
                        "ولا يظهر في خريطة الموقع — محركات البحث قد لا تعلم بوجوده.",
                        'bad'), unsafe_allow_html=True)
                    st.dataframe(localize_df(
                        pd.DataFrame(coverage['visible_not_in_sitemap']), 'ar'),
                        use_container_width=True)
                else:
                    st.markdown(finding(
                        "جميع المنتجات المعروضة مدرجة في خريطة الموقع.", 'ok'),
                        unsafe_allow_html=True)

                if coverage.get('sitemap_redirects'):
                    st.markdown(finding(
                        f"<b>{len(coverage['sitemap_redirects'])}</b> رابط في خريطة الموقع "
                        "يعيد التوجيه لصفحة أخرى مفحوصة أصلاً. الصفحات نفسها سليمة، "
                        "لكن إدراج الروابط القديمة في الخريطة يستهلك ميزانية الزحف "
                        "ويُفضّل استبدالها بوجهاتها النهائية.", 'warn'),
                        unsafe_allow_html=True)
                    st.dataframe(localize_df(
                        pd.DataFrame(coverage['sitemap_redirects']), 'ar'),
                        use_container_width=True)

                if coverage['sitemap_not_visible']:
                    bt = coverage.get('orphan_by_type', {})
                    brk = "، ".join(f"{PAGE_TYPE_LABEL['ar'].get(k, k)}: {v}"
                                    for k, v in bt.items())
                    st.markdown(finding(
                        f"<b>{len(coverage['sitemap_not_visible'])}</b> صفحة يتيمة "
                        f"({brk}): منشورة في خريطة الموقع ولا يصل إليها الزائر بأي رابط "
                        "داخلي. لا تستفيد من قوة الموقع وهي مستبعدة من أرقام الفحص.",
                        'warn'), unsafe_allow_html=True)
                    st.dataframe(localize_df(
                        pd.DataFrame(coverage['sitemap_not_visible']), 'ar'),
                        use_container_width=True)

        # ---------------- التحقق اليدوي ----------------
        with tabs[4]:
            st.markdown("#### عيّنة للمطابقة اليدوية")
            st.caption("افتح كل رابط وقارن العنوان والوصف بما هو مسجّل هنا. "
                       "تطابق العيّنة كاملة يعني أن محرك القراءة يعمل بشكل صحيح.")
            pool = df[(df['متاحة'] == True) & (df['نوع الصفحة'] == T_PRODUCT)]  # noqa: E712
            if pool.empty:
                pool = df[df['متاحة'] == True]  # noqa: E712
            if pool.empty:
                st.info("لا توجد صفحات متاحة للتحقق.")
            else:
                if st.button("🎲 عيّنة جديدة"):
                    st.session_state['sample_seed'] = int(time.time())
                seed = st.session_state.get('sample_seed', 42)
                sample = pool.sample(n=min(5, len(pool)), random_state=seed)
                L = STATUS_LABEL['ar']
                for _, r in sample.iterrows():
                    with st.container(border=True):
                        st.markdown(f"**[{r['الرابط']}]({r['الرابط']})**")
                        a, b, c = st.columns(3)
                        a.metric("طول العنوان", r['طول العنوان'], L[r['حالة العنوان']])
                        b.metric("طول الوصف", r['طول الوصف'], L[r['حالة الوصف']])
                        c.metric("درجة الصفحة", f"{r['درجة السيو']}%")
                        st.write(f"**العنوان:** {r['عنوان الميتا'] or '— مفقود —'}")
                        st.write(f"**الوصف:** {r['وصف الميتا'] or '— مفقود —'}")
                        st.caption(f"صور: {r['إجمالي الصور']} · بلا Alt: "
                                   f"{r['صور بدون Alt']} · Alt ضعيف: {r['صور Alt ضعيف']} · "
                                   f"كلمات: {r['عدد الكلمات']} · لغة: {r['لغة الصفحة']} · "
                                   f"كانونيكال: {L[r['حالة الكانونيكال']]}")

        # ---------------- التصدير ----------------
        with tabs[5]:
            st.markdown("#### تصدير التقرير والبيانات")
            lang_choice = st.radio("لغة الملفات", ["العربية", "English"], horizontal=True)
            lang = 'ar' if lang_choice == "العربية" else 'en'
            exp_summary = dict(summary)
            exp_summary['platform_label'] = (PLATFORM_LABEL if lang == 'ar'
                                             else PLATFORM_LABEL_EN).get(platform, '—')
            netloc = urlparse(st.session_state.current_url).netloc or "store"
            try:
                pdf_bytes = generate_client_pdf(st.session_state.current_url,
                                                summary['score'], exp_summary, lang)
            except Exception as e:
                pdf_bytes = None
                st.error(f"تعذر توليد الـ PDF: {e}")
            zip_bytes = build_zip(df, images_df, coverage, lang)

            d1, d2 = st.columns(2)
            with d1:
                if pdf_bytes:
                    st.download_button(
                        "📄 تقرير العميل (PDF)" if lang == 'ar' else "📄 Client report (PDF)",
                        pdf_bytes, f"SEO_Audit_{netloc}_{lang}.pdf", "application/pdf",
                        use_container_width=True)
            with d2:
                st.download_button(
                    "📦 حزمة البيانات (ZIP)" if lang == 'ar' else "📦 Data package (ZIP)",
                    zip_bytes, f"Data_Package_{netloc}_{lang}.zip", "application/zip",
                    use_container_width=True)

else:
    st.markdown("### 📁 سجل المتاجر المفحوصة")
    st.caption("تنبيه: قاعدة البيانات محلية وقد تُفقد عند إعادة نشر التطبيق على "
               "Streamlit Cloud.")
    conn = sqlite3.connect(DB_FILE)
    hist = pd.read_sql_query(
        "SELECT id, domain as 'المتجر', scan_date as 'تاريخ الفحص', score as 'النسبة', "
        "platform as 'المنصة', total_pages as 'الصفحات', products_count as 'المنتجات', "
        "categories_count as 'الأقسام', blog_pages_count as 'المدونة', "
        "info_pages_count as 'التعريفية' FROM audits ORDER BY id DESC", conn)
    conn.close()

    if hist.empty:
        st.info("لا توجد متاجر مفحوصة بعد.")
    else:
        st.dataframe(hist.drop(columns=['id']), use_container_width=True)
        sel_id = st.selectbox(
            "اختر المتجر", hist['id'].tolist(),
            format_func=lambda x: f"{hist[hist['id']==x]['المتجر'].values[0]} "
                                  f"({hist[hist['id']==x]['تاريخ الفحص'].values[0]})")
        if st.button("📥 استرجاع البيانات", type="primary"):
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute("SELECT domain, data_json, images_json, coverage_json, platform "
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
                st.session_state.platform = row[4] or 'unknown'
                st.session_state.summary = compute_summary(rdf, rcov, rimg)
                st.session_state.summary['platform_label'] = PLATFORM_LABEL.get(
                    row[4] or 'unknown', '—')
                st.success("تم الاسترجاع. انتقل إلى (فحص متجر جديد) لعرض النتائج.")
