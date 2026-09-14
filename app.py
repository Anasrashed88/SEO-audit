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
# خطوط التقرير: تُختار أول عائلة يوجد ملفها في المستودع.
# لتغيير خط التقرير يكفي رفع ملفي الخط بالاسمين أدناه — لا تعديل في الكود.
FONT_CANDIDATES = [
    ("Tajawal", "Tajawal-Regular.ttf", "Tajawal-Bold.ttf"),
    ("Almarai", "Almarai-Regular.ttf", "Almarai-Bold.ttf"),
    ("Cairo", "Cairo-Regular.ttf", "Cairo-Bold.ttf"),
    ("IBMPlexArabic", "IBMPlexSansArabic-Regular.ttf", "IBMPlexSansArabic-Bold.ttf"),
    ("NotoKufi", "NotoKufiArabic-Regular.ttf", "NotoKufiArabic-Bold.ttf"),
    ("Amiri", "Amiri-Regular.ttf", "Amiri-Bold.ttf"),
]


def pick_font():
    """يعيد (الاسم، مسار العادي، مسار العريض أو None)."""
    for name, reg, bold in FONT_CANDIDATES:
        rp = BASE_DIR / reg
        if rp.exists() and rp.stat().st_size > 20000:
            bp = BASE_DIR / bold
            return name, rp, (bp if bp.exists() and bp.stat().st_size > 20000 else None)
    return "Amiri", BASE_DIR / "Amiri-Regular.ttf", None


AR_FONT_NAME, FONT_PATH, FONT_BOLD_PATH = pick_font()

# التشكيل الحديث (HarfBuzz) يتيح استخدام أي خط عربي عصري بلا الحاجة
# لأشكال الحروف القديمة. عند غيابه نعود لطريقة arabic-reshaper.
try:
    import uharfbuzz  # noqa: F401
    HAS_SHAPING = True
except Exception:
    HAS_SHAPING = False
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
T_ARCHIVE = 'archive'
PAGE_TYPE_ORDER = [T_HOME, T_PRODUCT, T_CATEGORY, T_BLOG, T_INFO, T_ARCHIVE,
                   T_UNKNOWN, T_BROKEN]

PAGE_TYPE_LABEL = {
    'ar': {T_HOME: 'صفحة رئيسية', T_PRODUCT: 'صفحة منتج', T_CATEGORY: 'صفحة تصنيف',
           T_BLOG: 'صفحة مدونة', T_INFO: 'صفحة تعريفية', T_ARCHIVE: 'صفحة أرشيف',
           T_UNKNOWN: 'غير مصنفة', T_BROKEN: 'صفحة غير متاحة'},
    'en': {T_HOME: 'Homepage', T_PRODUCT: 'Product', T_CATEGORY: 'Category',
           T_BLOG: 'Blog', T_INFO: 'Info / Policy', T_ARCHIVE: 'Archive',
           T_UNKNOWN: 'Unclassified', T_BROKEN: 'Unreachable'},
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
    'جودة العنوان': 'Title Quality', 'جودة الوصف': 'Description Quality',
    'جودة الرابط': 'URL Quality', 'المسار': 'Slug', 'محتوى مكرر': 'Duplicate Content',
    'اسم المنتج المعروض': 'Displayed Product Name', 'صيغة الصورة': 'Image Format',
    'اسم منظم': 'Declared Name', 'صور معلنة': 'Declared Images',
    'رقم المنتج': 'SKU', 'عدد معلن': 'Declared Count',
    'الاسم المعلن': 'Declared Name', 'الاسم المعروض': 'Displayed Name',
    'صور مرصودة': 'Images Detected', 'القسم': 'Category',
    'مرصود': 'Detected', 'ناقص': 'Missing', 'عدد معلن': 'Declared Count',
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
                     ('current_url', ""), ('coverage', None), ('platform', 'unknown'),
                     ('selfcheck', None), ('brand', ''), ('dup_groups', None),
]:
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
.chk { display:flex; gap:12px; align-items:flex-start; border:1px solid #e2e8f0; border-radius:10px; padding:12px 14px; margin-bottom:8px; background:#fff; }
.chk .dot { flex:0 0 10px; height:10px; border-radius:50%; margin-top:6px; }
.chk .t { font-size:13.5px; font-weight:700; color:#0f172a; }
.chk .m { font-size:13px; color:#475569; margin-top:2px; }
.chk .a { font-size:12.5px; color:#b45309; margin-top:5px; }
.verdict { border-radius:12px; padding:16px 20px; margin-bottom:16px; font-size:15px; font-weight:500; }
.v-ready { background:#ecfdf5; border:1px solid #a7f3d0; color:#065f46; }
.v-review { background:#fffbeb; border:1px solid #fde68a; color:#92400e; }
.v-blocked { background:#fef2f2; border:1px solid #fecaca; color:#991b1b; }
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


# معرّفات المنصات الثابتة: سلة تضع رقم المنتج في آخر مقطع، والاسم قد
# يختلف بين خريطة الموقع والصفحة نفسها، فالمعرّف هو المرجع لا الاسم.
PLATFORM_ID_RE = re.compile(r'^(p|c|a|page|tag|category|product)-?(\d{4,})$', re.I)


def url_key(url):
    """مفتاح موحّد للمقارنة.

    يفك ترميز المسارات العربية، ويعتمد المعرّف الرقمي حين يوجد: رابطا
    /عبايات-مفتوحه/p163285128 و/عباية-مفتوحة/p163285128 صفحة واحدة.
    """
    if not url:
        return ""
    p = urlparse(clean_url(url))
    path = unquote(p.path).rstrip('/')
    host = p.netloc.lower()
    segs = [x for x in path.split('/') if x]
    if segs:
        mo = PLATFORM_ID_RE.match(segs[-1])
        if mo:
            return f"{host}/#{mo.group(1).lower()}{mo.group(2)}"
    return f"{host}{path}"


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
                  'shopify': 'شوبيفاي (Shopify)', 'rmz': 'رمز (rmz.gg)',
                  'woocommerce': 'ووكومرس', 'unknown': 'غير معروفة'}
PLATFORM_LABEL_EN = {'salla': 'Salla', 'zid': 'Zid', 'shopify': 'Shopify',
                     'rmz': 'rmz.gg', 'woocommerce': 'WooCommerce',
                     'unknown': 'Unidentified'}
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
    if any(s in blob for s in ['cdn.rmz.gg', 'rmz.gg/store', 'matjrah']):
        return 'rmz'
    if any(s in blob for s in ['woocommerce', 'wp-content/plugins/woo']):
        return 'woocommerce'
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

    # صفحات الأرشيف (وسم/كاتب/تاريخ): تعرض قوائم لا محتوى أصلياً
    if segments:
        last = segments[-1]
        if re.match(r'^(tag|author|category|archive)-?\d*$', last) or \
                re.match(r'^\d{4}$', last):
            return T_ARCHIVE
        # تصنيف داخل المدونة: /blog/عام/c-368175017
        if re.match(r'^c-?\d{4,}$', last) and \
                any(x in BLOG_SEGMENTS for x in segments[:-1]):
            return T_ARCHIVE
        if len(segments) >= 2 and any(
                x in ('tag', 'tags', 'author', 'authors', 'archive', 'وسم', 'وسوم')
                for x in segments[:-1]):
            return T_ARCHIVE

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
    # صور وهمية تضعها القوالب قبل التحميل الكسول
    's-empty', 'empty.png', 'lazy.png', 'transparent', 'dummy', '1x1',
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


def strip_boilerplate(soup, markup=None):
    """يحذف الترويسة والفوتر والقوائم فقط، لا الصفحة كلها.

    بعض القوالب (سلة مثلاً) تضع صنفاً فيه كلمة header على وسم body نفسه،
    فالمطابقة بالصنف وحدها تمسح المحتوى بالكامل. لذلك نستثني الأوسمة
    الجذرية وأي عنصر يحوي المحتوى الرئيسي أو معظم نص الصفحة، ونعود
    للصفحة كاملة إذا لم يتبقَّ منها شيء يُذكر.
    """
    body = soup.body or soup
    total = len(body.get_text(' ', strip=True))

    targets = soup.select(
        'header, nav, footer, aside, [class*="header"], [class*="footer"], '
        '[class*="navbar"], [class*="nav-menu"]')
    for tag in targets:
        try:
            if tag.name in ('html', 'body', 'main'):
                continue
            if tag.find('main') is not None:
                continue
            if total and len(tag.get_text(' ', strip=True)) > total * 0.6:
                continue
            tag.decompose()
        except Exception:
            pass

    # شبكة أمان: لو ابتلع التنظيف الصفحة، نعيد الأصل كما هو
    if markup and total > 200:
        left = len((soup.body or soup).get_text(' ', strip=True))
        if left < total * 0.15:
            return make_soup(markup)
    return soup


# ==============================================================
#  فحص صفحة واحدة
# ==============================================================
def broken_page_row(url, reason, source):
    return {
        'page_data': {
            'نوع الصفحة': T_BROKEN, 'الرابط': unquote(url), 'مصدر الاكتشاف': source,
            'متاحة': False, 'كود الاستجابة': str(reason), 'لغة الصفحة': '—',
            'اسم المنتج المعروض': '', 'اسم منظم': '', 'صور معلنة': 0,
            'رقم المنتج': '', 'عدد معلن': None,
            'درجة السيو': None, 'عنوان الميتا': '', 'طول العنوان': 0,
            'حالة العنوان': 'failed', 'وصف الميتا': '', 'طول الوصف': 0,
            'حالة الوصف': 'failed', 'إجمالي الصور': 0, 'صور بدون Alt': 0,
            'صور Alt ضعيف': 0, 'عدد الكلمات': 0, 'حالة المحتوى': 'na',
            'حالة الكانونيكال': 'canon_missing', 'الرابط الكانوني': '', '_raw_url': url,
        },
        'images_data': [], 'links': set(), 'product_links': set(),
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

    h1 = soup.find('h1')
    display_name = re.sub(r'\s+', ' ', h1.get_text(strip=True)).strip() if h1 else ''
    if not display_name:
        ogt = soup.find('meta', attrs={'property': 'og:title'})
        if ogt and ogt.get('content'):
            display_name = re.sub(r'\s+', ' ', ogt['content']).strip()

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

    content_soup = strip_boilerplate(make_soup(res.text), res.text)
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
                'صيغة الصورة': image_format(urljoin(final_url, src)),
            })

    jd = extract_product_facts(soup) if page_type == T_PRODUCT else \
        {'name': '', 'images': [], 'sku': '', 'offers': False}
    prod_links = set()
    if page_type in (T_CATEGORY, T_HOME):
        for lk in links:
            if detect_page_type(lk, base_url, None) == T_PRODUCT:
                prod_links.add(url_key(lk))
    declared_n = (extract_declared_count(soup)
                  if page_type in (T_CATEGORY, T_HOME) else None)

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
            'اسم المنتج المعروض': display_name, 'اسم منظم': jd['name'],
            'صور معلنة': len(jd['images']), 'رقم المنتج': jd['sku'],
            'عدد معلن': declared_n,
            'درجة السيو': None,  # تُحسب بعد تقييم الصور والروابط
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
        'product_links': prod_links,
        'platform_html': res.text[:60000] if page_type == T_HOME else '',
        'platform_headers': dict(res.headers) if page_type == T_HOME else {},
    }



# ==============================================================
#  الجودة البنيوية للعناوين والأوصاف
#  الطول وحده لا يكفي: «[]» ليس عنواناً قصيراً بل عنوان مفقود.
# ==============================================================
PLACEHOLDER_PATTERNS = [
    r'^\s*\[\s*[\.\-_]*\s*\]\s*$',      # [] [.] [-] [_]
    r'\{\{.*?\}\}', r'\{%.*?%\}',          # قوالب Liquid/Jinja
    r'%[sd]\b', r'<%.*?%>',
    r'\b(undefined|null|nan|none|lorem ipsum|test|xxx|todo|tbd)\b',
    r'^\s*(page|product|item|title|default)\s*\d*\s*$',
]


def meaningful_text(t):
    """النص بعد تجريد كل ما ليس حرفاً أو رقماً — لكشف العناوين الرمزية."""
    return re.sub(r'[^0-9A-Za-z\u0600-\u06FF]+', '', str(t or ''))


def is_placeholder(t):
    low = str(t or '').strip().lower()
    if not low:
        return False
    return any(re.search(pat, low) for pat in PLACEHOLDER_PATTERNS)


def detect_brand(titles):
    """اسم المتجر من اللاحقة المتكررة بعد الفاصل في العناوين."""
    from collections import Counter
    c = Counter()
    valid = [t for t in titles if isinstance(t, str) and t.strip()]
    for t in valid:
        for sep in ['|', '–', '—', '-', '•', '·']:
            if sep in t:
                tail = t.rsplit(sep, 1)[-1].strip()
                if 2 <= len(tail) <= 40:
                    c[tail] += 1
                break
    if c and valid:
        top, n = c.most_common(1)[0]
        if n >= max(3, 0.25 * len(valid)):
            return top
    return ''


QUALITY_LABEL = {
    'ar': {'q_ok': 'سليم', 'q_symbols': 'رموز بلا نص', 'q_placeholder': 'قيمة قالب افتراضية',
           'q_brand_only': 'اسم المتجر فقط', 'q_duplicate': 'مكرر على عدة صفحات',
           'q_one_word': 'كلمة واحدة بلا وصف', 'q_same_as_title': 'نسخة من العنوان',
           'q_na': '—'},
    'en': {'q_ok': 'Sound', 'q_symbols': 'Symbols only', 'q_placeholder': 'Template placeholder',
           'q_brand_only': 'Store name only', 'q_duplicate': 'Duplicated across pages',
           'q_one_word': 'Single word, no description', 'q_same_as_title': 'Copy of the title',
           'q_na': '—'},
}
# البنود التي تُعدّ العنصر مفقوداً فعلياً
QUALITY_FATAL = ('q_symbols', 'q_placeholder')
QUALITY_CREDIT = {'q_ok': 1.0, 'q_duplicate': 0.3, 'q_brand_only': 0.2,
                  'q_one_word': 0.3, 'q_same_as_title': 0.4,
                  'q_symbols': 0.0, 'q_placeholder': 0.0, 'q_na': 1.0}
TEXT_DUP_THRESHOLD = 3


def analyze_text_quality(df):
    """يضيف تقييم الجودة البنيوية ويصحّح حالة الطول عند العناوين الرمزية."""
    if df.empty:
        return df, ''
    out = df.copy()
    ok_mask = out['متاحة'] == True  # noqa: E712
    brand = detect_brand(out.loc[ok_mask, 'عنوان الميتا'].tolist())

    def strip_brand(t):
        v = str(t or '')
        if brand:
            for sep in ['|', '–', '—', '-', '•', '·']:
                v = v.replace(f"{sep} {brand}", '').replace(f"{sep}{brand}", '')
            v = v.replace(brand, '')
        return v.strip(' |-–—•·')

    tvals = out.loc[ok_mask, 'عنوان الميتا'].map(lambda x: str(x or '').strip())
    dup_titles = {v for v, n in tvals[tvals != ''].value_counts().items()
                  if n >= TEXT_DUP_THRESHOLD}
    dvals = out.loc[ok_mask, 'وصف الميتا'].map(lambda x: str(x or '').strip())
    dup_descs = {v for v, n in dvals[dvals != ''].value_counts().items()
                 if n >= TEXT_DUP_THRESHOLD}

    def qt(row):
        if not row['متاحة']:
            return 'q_na'
        t = str(row['عنوان الميتا'] or '').strip()
        if not t:
            return 'q_na'
        if is_placeholder(t):
            return 'q_placeholder'
        if not meaningful_text(t):
            return 'q_symbols'
        if brand and not meaningful_text(strip_brand(t)):
            return 'q_brand_only'
        if t in dup_titles:
            return 'q_duplicate'
        if len(meaningful_text(strip_brand(t)).strip()) and \
                len(strip_brand(t).split()) < 2:
            return 'q_one_word'
        return 'q_ok'

    def qd(row):
        if not row['متاحة']:
            return 'q_na'
        d = str(row['وصف الميتا'] or '').strip()
        if not d:
            return 'q_na'
        if is_placeholder(d):
            return 'q_placeholder'
        if not meaningful_text(d):
            return 'q_symbols'
        if d == str(row['عنوان الميتا'] or '').strip():
            return 'q_same_as_title'
        if d in dup_descs:
            return 'q_duplicate'
        return 'q_ok'

    out['جودة العنوان'] = out.apply(qt, axis=1)
    out['جودة الوصف'] = out.apply(qd, axis=1)

    # عنوان رمزي أو قيمة قالب = مفقود فعلياً، لا «قصير جداً»
    for col_q, col_s, col_len in [('جودة العنوان', 'حالة العنوان', 'طول العنوان'),
                                  ('جودة الوصف', 'حالة الوصف', 'طول الوصف')]:
        fatal = out[col_q].isin(QUALITY_FATAL)
        out.loc[fatal, col_s] = 'missing'
        out.loc[fatal, col_len] = 0
    return out, brand



# ==============================================================
#  تدقيق الروابط (Slug) — الرابط عنصر سيو مستقل
# ==============================================================
CLONE_PATTERNS = [r'copy-of', r'copy_of', r'-copy\b', r'نسخة', r'نسخه',
                  r'duplicate', r'\bتجربة\b', r'\btest\b']
URL_MAX_PATH = 90

URL_LABEL = {
    'ar': {'u_ok': 'سليم', 'u_clone': 'منتج مستنسخ', 'u_generic': 'رقم أو رمز بلا كلمات',
           'u_wrongname': 'يشير لمنتج آخر',
           'u_underscore': 'شرطة سفلية بدل الواصلة', 'u_uppercase': 'حروف كبيرة',
           'u_long': 'طويل جداً', 'u_repeat': 'كلمة مكررة داخل الرابط',
           'u_wordy': 'كلمات كثيرة', 'u_na': '—'},
    'en': {'u_ok': 'Sound', 'u_clone': 'Cloned product', 'u_generic': 'ID or code, no words',
           'u_wrongname': 'Points to a different product',
           'u_underscore': 'Underscores instead of hyphens', 'u_uppercase': 'Uppercase letters',
           'u_long': 'Too long', 'u_repeat': 'Repeated word in slug',
           'u_wordy': 'Too many words', 'u_na': '—'},
}
URL_CREDIT = {'u_ok': 1.0, 'u_underscore': 0.95, 'u_uppercase': 0.95, 'u_repeat': 0.95,
              'u_wordy': 0.93, 'u_long': 0.90, 'u_generic': 0.80, 'u_wrongname': 0.65,
              'u_clone': 0.70, 'u_na': 1.0}
URL_MAX_WORDS = 9


def slug_tokens(text):
    """كلمات الرابط أو الاسم بعد التطبيع، مع تجاهل الحروف المفردة."""
    raw = re.split(r'[\s\-_/|،,.:؛…]+', str(text or '').lower())
    out = []
    for t in raw:
        t = re.sub(r'[^0-9a-z\u0600-\u06FF]', '', t)
        if len(t) < 2:
            continue
        out.append(normalize_ar_token(t) if re.search(r'[\u0600-\u06FF]', t) else t)
    return out


def script_of(text):
    ar = len(re.findall(r'[\u0600-\u06FF]', str(text or '')))
    la = len(re.findall(r'[A-Za-z]', str(text or '')))
    if ar and not la:
        return 'ar'
    if la and not ar:
        return 'la'
    if ar or la:
        return 'ar' if ar >= la else 'la'
    return ''


def build_generic_vocab(names, threshold=0.22):
    """الكلمات الشائعة في أسماء المتجر (بوكس، علبة، عود...) ليست مميِّزة."""
    from collections import Counter
    c = Counter()
    n = 0
    for nm in names:
        toks = set(slug_tokens(nm))
        if toks:
            n += 1
            c.update(toks)
    if n < 5:
        return set()
    return {t for t, k in c.items() if k / n >= threshold}


def slug_of(url):
    path = unquote(urlparse(clean_url(url)).path)
    segs = [x for x in path.split('/') if x]
    if not segs:
        return ''
    # سلة تضع معرّف المنتج في المقطع الأخير (p123456) والاسم قبله
    if re.fullmatch(r'p\d+', segs[-1]) and len(segs) >= 2:
        return segs[-2]
    return segs[-1]


def analyze_url_quality(df, brand=''):
    """يقيّم صياغة الرابط نفسه.

    لا تُقارن كلمات الرابط باسم المنتج: الرابط قد يكون نقلاً صوتياً صحيحاً
    (moroki-oud-luxury لمنتج «عود مروكي فاخر»)، والاسم العربي الكامل يجعل
    الرابط طويلاً بلا فائدة. المعايير هنا تخص الرابط ذاته فقط.
    """
    if df.empty:
        return df
    out = df.copy()
    out['المسار'] = out['الرابط'].map(slug_of)
    known = {url_key(u) for u in out['الرابط']}

    # الكلمات الشائعة في أسماء منتجات هذا المتجر تحديداً
    prod_names = out.loc[out['نوع الصفحة'] == T_PRODUCT, 'اسم المنتج المعروض'] \
        if 'اسم المنتج المعروض' in out.columns else []
    generic_vocab = build_generic_vocab(list(prod_names)) if len(prod_names) else set()
    brand_tokens = set(slug_tokens(brand))

    def grade(row):
        if not row['متاحة']:
            return 'u_na'
        slug = str(row['المسار'] or '')
        if not slug:
            return 'u_na'
        low = slug.lower()

        # 1) نسخة مكررة من منتج آخر
        if any(re.search(pat, low) for pat in CLONE_PATTERNS):
            return 'u_clone'
        mo = re.match(r'^(.*)-(\d{1,2})$', slug)
        if mo:
            parent = str(row['الرابط']).replace(slug, mo.group(1))
            if url_key(parent) in known:
                return 'u_clone'

        # 2) رابط بلا كلمات وصفية
        if re.fullmatch(r'[\d\W_]+', slug) or \
                re.fullmatch(r'(product|item|page|post)[-_]?\d*', low):
            return 'u_generic'

        words = [w for w in re.split(r'[-_]+', slug) if w]

        # 3) صياغة
        if '_' in slug:
            return 'u_underscore'
        if re.search(r'[A-Z]', slug):
            return 'u_uppercase'
        if len(unquote(urlparse(clean_url(row['الرابط'])).path)) > URL_MAX_PATH:
            return 'u_long'
        norm = [normalize_ar_token(w.lower()) if re.search(r'[\u0600-\u06FF]', w)
                else w.lower() for w in words]
        if len(norm) != len(set(norm)) and len(norm) > 2:
            return 'u_repeat'
        if len(words) > URL_MAX_WORDS:
            return 'u_wordy'

        # 4) هل يشير الرابط لمنتج مختلف عن المعروض في الصفحة؟
        # يُقارن الرابط بالاسم المعروض وبعنوان الميتا معاً: بعض المتاجر
        # تختار رابطاً بكلمات البحث واسماً تجارياً مختلفاً، وهذا سليم.
        name = (str(row.get('اسم منظم') or '').strip()
                or str(row.get('اسم المنتج المعروض') or '').strip())
        meta_t = str(row.get('عنوان الميتا') or '').strip()
        if (name or meta_t) and row.get('نوع الصفحة') == T_PRODUCT:
            s_tok = [t for t in slug_tokens(slug) if not t.isdigit()]
            n_tok = (set(slug_tokens(name)) | set(slug_tokens(meta_t))) - brand_tokens
            # تُقارن الكلمات فقط عند اتفاق الأبجدية: الرابط قد يكون نقلاً صوتياً
            ref = name if name else meta_t
            if s_tok and n_tok and script_of(slug) == script_of(ref):
                distinctive = [t for t in s_tok
                               if t not in generic_vocab and t not in brand_tokens]
                if distinctive and not (set(distinctive) & n_tok):
                    return 'u_wrongname'
        return 'u_ok'

    out['جودة الرابط'] = out.apply(grade, axis=1)
    return out


def detect_duplicate_content(df):
    """مجموعات صفحات تتشارك نفس العنوان والوصف — محتوى مكرر فعلي."""
    if df.empty:
        return df, []
    out = df.copy()
    ok = out[out['متاحة'] == True]  # noqa: E712
    groups = []
    sub = ok[(ok['عنوان الميتا'].astype(str).str.strip() != '')]
    for (t, d), grp in sub.groupby(['عنوان الميتا', 'وصف الميتا']):
        if len(grp) > 1:
            groups.append({'العنوان': t, 'عدد الصفحات': len(grp),
                           'الروابط': list(grp['الرابط'])})
    dup_urls = {u for g in groups for u in g['الروابط']}
    out['محتوى مكرر'] = out['الرابط'].isin(dup_urls)
    return out, groups


# ==============================================================
#  صيغ الصور
# ==============================================================
MODERN_FORMATS = ('webp', 'avif')


def image_format(url):
    path = urlparse(str(url or '')).path.lower()
    mo = re.search(r'\.(jpe?g|png|webp|avif|gif|svg|bmp|tiff?)(?:$|\?)', path)
    if mo:
        ext = mo.group(1)
        return 'jpg' if ext in ('jpg', 'jpeg') else ext
    mo2 = re.search(r'(?:format|fm)=(\w+)', str(url or '').lower())
    return mo2.group(1) if mo2 else '—'


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
        s = 25 * LEN_WEIGHT.get(r['حالة العنوان'], 0) * \
            QUALITY_CREDIT.get(r.get('جودة العنوان', 'q_na'), 1.0)
        s += 25 * LEN_WEIGHT.get(r['حالة الوصف'], 0) * \
            QUALITY_CREDIT.get(r.get('جودة الوصف', 'q_na'), 1.0)
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
        s *= URL_CREDIT.get(r.get('جودة الرابط', 'u_na'), 1.0)
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
    listing_urls = []          # قوائم المدونة والأرشيف
    cat_products = {}
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
                if row['نوع الصفحة'] in (T_BLOG, T_ARCHIVE):
                    listing_urls.append(row.get('_raw_url', row['الرابط']))
                if row['نوع الصفحة'] in (T_CATEGORY, T_HOME):
                    cu = row.get('_raw_url', row['الرابط'])
                    category_urls.append(cu)
                    cat_products[cu] = set(res.get('product_links') or ())
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
    truncated = bool(frontier)   # بقيت روابط لم تُفحص
    meta = {'truncated': truncated, 'pending': len(frontier), 'levels': level,
            'cat_products': cat_products, 'listing_urls': listing_urls}
    return pages, images, category_urls, seen, platform, meta


def harvest_paginated_products(base_url, category_urls, seen_keys, progress_cb=None,
                               max_depth=MAX_PAGINATION_DEPTH, cat_products=None,
                               listing_urls=None):
    """يتابع ترقيم صفحات القوائم (أقسام ومدونة) لالتقاط ما لا يظهر في
    الصفحة الأولى. القوائم التي تحمّل بالتمرير لا تستجيب للترقيم، وهذا
    يظهر في فحص الثقة."""
    base_url = normalize_url(base_url)
    base_netloc = urlparse(base_url).netloc
    roots = list(dict.fromkeys(
        list(category_urls) + list(listing_urls or []) +
        [f"{base_url}/{r}" for r in ['products', 'collections/all', 'shop', 'blog']]))
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
                        detect_page_type(full, base_url, None) in (T_PRODUCT, T_BLOG):
                    found.add(full)
            fresh = found - seen_here
            if not fresh:
                break
            seen_here |= fresh
            if cat_products is not None:
                cat_products.setdefault(cat, set()).update(
                    {url_key(x) for x in fresh})
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
        'archive_pages': int((df['نوع الصفحة'] == T_ARCHIVE).sum()),
        'unclassified': int((df['نوع الصفحة'] == T_UNKNOWN).sum()),
        'broken_pages': int(((df['متاحة'] == False) &  # noqa: E712
                             (~df['كود الاستجابة'].astype(str)
                              .str.contains('فشل اتصال|خطأ فني', na=False))).sum()),
        'unreachable_pages': int(((df['متاحة'] == False) &  # noqa: E712
                                  (df['كود الاستجابة'].astype(str)
                                   .str.contains('فشل اتصال|خطأ فني', na=False))).sum()),
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
        'title_symbols': int(ok['جودة العنوان'].isin(QUALITY_FATAL).sum())
        if 'جودة العنوان' in ok.columns else 0,
        'title_brand_only': int((ok['جودة العنوان'] == 'q_brand_only').sum())
        if 'جودة العنوان' in ok.columns else 0,
        'title_dup': int((ok['جودة العنوان'] == 'q_duplicate').sum())
        if 'جودة العنوان' in ok.columns else 0,
        'desc_dup': int((ok['جودة الوصف'] == 'q_duplicate').sum())
        if 'جودة الوصف' in ok.columns else 0,
        'desc_same': int((ok['جودة الوصف'] == 'q_same_as_title').sum())
        if 'جودة الوصف' in ok.columns else 0,
        'url_clone': int((ok['جودة الرابط'] == 'u_clone').sum())
        if 'جودة الرابط' in ok.columns else 0,
        'url_wrongname': int((ok['جودة الرابط'] == 'u_wrongname').sum())
        if 'جودة الرابط' in ok.columns else 0,
        'url_style': int(ok['جودة الرابط'].isin(
            ['u_underscore', 'u_uppercase', 'u_long', 'u_repeat', 'u_wordy']).sum())
        if 'جودة الرابط' in ok.columns else 0,
        'url_generic': int((ok['جودة الرابط'] == 'u_generic').sum())
        if 'جودة الرابط' in ok.columns else 0,
        'url_bad': int((~ok['جودة الرابط'].isin(['u_ok', 'u_na'])).sum())
        if 'جودة الرابط' in ok.columns else 0,
        'dup_content': int(ok['محتوى مكرر'].sum()) if 'محتوى مكرر' in ok.columns else 0,
        'canon_missing': int((ok['حالة الكانونيكال'] == 'canon_missing').sum()),
        'canon_diff': int((ok['حالة الكانونيكال'] == 'canon_diff').sum()),
        'thin_pages': int((ok['حالة المحتوى'] == 'thin').sum()),
        'coverage_enabled': bool(coverage),
    }
    if uimg is not None and not uimg.empty and 'صيغة الصورة' in uimg.columns:
        fmts = uimg['صيغة الصورة'].value_counts().to_dict()
        modern = sum(v for k, v in fmts.items() if k in MODERN_FORMATS)
        s['img_formats'] = fmts
        s['img_modern'] = int(modern)
        s['img_legacy'] = int(len(uimg) - modern)
        s['img_modern_pct'] = round(modern / len(uimg) * 100, 1)
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
    for col in ['جودة العنوان', 'جودة الوصف']:
        if col in out.columns:
            out[col] = out[col].map(lambda v: QUALITY_LABEL[lang].get(v, v))
    if 'جودة الرابط' in out.columns:
        out['جودة الرابط'] = out['جودة الرابط'].map(lambda v: URL_LABEL[lang].get(v, v))
    if 'النص البديل الحالي (Alt)' in out.columns:
        empty = STATUS_LABEL[lang]['alt_empty']
        out['النص البديل الحالي (Alt)'] = out['النص البديل الحالي (Alt)'].map(
            lambda v: v if str(v).strip() else empty)
    if lang == 'en':
        out = out.rename(columns={k: v for k, v in COL_EN.items() if k in out.columns})
    return out





# ==============================================================
#  التحقق بالبيانات المهيكلة (JSON-LD) وعدّادات المتجر
#
#  مصدر يقين لا تخمين: هذه البيانات يكتبها المتجر من قاعدة بياناته
#  لمحركات البحث. مقارنتها بما استنتجه الزاحف من الشكل تكشف النقص.
# ==============================================================
def iter_jsonld(soup):
    for tag in soup.find_all('script', attrs={'type': 'application/ld+json'}):
        try:
            data = json.loads(tag.string or '{}')
        except Exception:
            continue
        stack = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
            elif isinstance(node, dict):
                yield node
                for v in node.values():
                    if isinstance(v, (dict, list)):
                        stack.append(v)


def node_types(node):
    t = node.get('@type')
    return {str(x) for x in (t if isinstance(t, list) else [t]) if x}


def extract_product_facts(soup):
    """اسم المنتج وصوره كما يعلنها المتجر لمحركات البحث."""
    facts = {'name': '', 'images': [], 'sku': '', 'offers': False}
    for node in iter_jsonld(soup):
        if 'Product' not in node_types(node):
            continue
        nm = node.get('name')
        if isinstance(nm, str) and nm.strip() and not facts['name']:
            facts['name'] = re.sub(r'\s+', ' ', nm).strip()
        img = node.get('image')
        imgs = img if isinstance(img, list) else ([img] if img else [])
        for it in imgs:
            if isinstance(it, dict):
                it = it.get('url') or it.get('contentUrl')
            if isinstance(it, str) and it.strip():
                facts['images'].append(it.strip())
        if node.get('sku') and not facts['sku']:
            facts['sku'] = str(node['sku'])
        if node.get('offers'):
            facts['offers'] = True
        break
    facts['images'] = list(dict.fromkeys(facts['images']))
    return facts


# صيغ إعلان عدد المنتجات في صفحات الأقسام
COUNT_PATTERNS = [
    r'عدد\s*المنتجات\s*[:：]?\s*([\d,]+)',
    r'([\d,]+)\s*منتج(?:اً|ا)?\b',
    r'من\s*أصل\s*([\d,]+)',
    r'\b([\d,]+)\s*products?\b',
    r'showing\s*\d+\s*(?:-|to)\s*\d+\s*of\s*([\d,]+)',
]


def extract_declared_count(soup, text=None):
    """الرقم الذي يعلنه المتجر نفسه لعدد منتجات القسم."""
    best = None
    for node in iter_jsonld(soup):
        if node_types(node) & {'ItemList', 'CollectionPage'}:
            n = node.get('numberOfItems')
            if isinstance(n, (int, float)) and n > 0:
                return int(n)
    body = text if text is not None else soup.get_text(' ', strip=True)
    body = body[:4000]
    for pat in COUNT_PATTERNS:
        for mo in re.finditer(pat, body, re.I):
            try:
                v = int(mo.group(1).replace(',', ''))
            except Exception:
                continue
            if 0 < v < 100000:
                best = v if best is None else max(best, v)
    return best


def build_structured_report(df, declared_counts, cat_products=None):
    """يقارن ما يعلنه المتجر بما رصده الزاحف — قسماً بقسم.

    لا تُجمع أعداد الأقسام ولا يؤخذ أكبرها: المنتج قد ينتمي لأكثر من قسم،
    فالمقارنة الصحيحة هي بين عدّاد كل قسم وعدد منتجاته المرصودة فيه.
    """
    ok = df[df['متاحة'] == True]  # noqa: E712
    prod = ok[ok['نوع الصفحة'] == T_PRODUCT]
    n_found = len(prod)
    # توحيد المفاتيح: قد يأتي رابط القسم مشفّراً من الزحف ومفكوكاً من الجدول
    cat_products = {url_key(k): v for k, v in (cat_products or {}).items()}

    def as_int(v):
        try:
            if v is not None and pd.notna(v) and int(v) > 0:
                return int(v)
        except (TypeError, ValueError):
            pass
        return None

    cats, short = [], []
    for url, raw in (declared_counts or {}).items():
        dec = as_int(raw)
        if dec is None:
            continue
        found = len(cat_products.get(url_key(url), set()))
        row = {'القسم': unquote(url), 'عدد معلن': dec, 'مرصود': found,
               'ناقص': max(dec - found, 0)}
        cats.append(row)
        if found < dec:
            short.append(row)

    total_missing = sum(r['ناقص'] for r in short)
    checked = len(cats)
    matched = checked - len(short)

    name_gap, img_gap, no_jsonld = [], [], 0
    for _, r in prod.iterrows():
        j_name = str(r.get('اسم منظم') or '').strip()
        if not j_name:
            no_jsonld += 1
            continue
        shown = str(r.get('اسم المنتج المعروض') or '').strip()
        if shown and slug_tokens(j_name) and \
                not (set(slug_tokens(j_name)) & set(slug_tokens(shown))):
            name_gap.append({'الرابط': r['الرابط'], 'الاسم المعلن': j_name,
                             'الاسم المعروض': shown})
        dec_i = as_int(r.get('صور معلنة')) or 0
        seen_i = as_int(r.get('إجمالي الصور')) or 0
        if dec_i and seen_i < dec_i:
            img_gap.append({'الرابط': r['الرابط'], 'صور معلنة': dec_i,
                            'صور مرصودة': seen_i})

    return {
        'found_products': n_found,
        'categories_checked': checked,
        'categories_matched': matched,
        'categories_short': short,
        'category_rows': cats,
        'missing_products': total_missing,
        'coverage_pct': round(matched / checked * 100, 1) if checked else None,
        'name_mismatch': name_gap,
        'image_gap': img_gap,
        'no_jsonld': no_jsonld,
        'jsonld_pages': len(prod) - no_jsonld,
    }


# ==============================================================
#  الفحص الذاتي — الأداة تحكم على موثوقية نتائجها قبل العميل
# ==============================================================
CHECK_FAIL, CHECK_WARN, CHECK_PASS = 'fail', 'warn', 'pass'


def run_self_checks(df, images_df, coverage, platform, summary, crawl_meta=None,
                    structured=None):
    """يفحص نتائج الفحص نفسها بحثاً عن علامات عدم الموثوقية.

    الهدف ليس إثبات صحة الأرقام — بل رصد الحالات التي تشير إلى أن الزاحف
    لم يرَ المتجر كما يراه الزائر، قبل أن يصل التقرير إلى عميل.
    """
    checks = []

    def add(level, title, msg, action=""):
        checks.append({'level': level, 'title': title, 'msg': msg, 'action': action})

    ok = df[df['متاحة'] == True] if not df.empty else df  # noqa: E712
    n_ok = len(ok)
    uimg = unique_images(images_df)
    n_img = 0 if uimg is None or uimg.empty else len(uimg)

    # 1) المنصة
    if platform in SUPPORTED_PLATFORMS:
        add(CHECK_PASS, "منصة المتجر",
            f"تم التعرف على المنصة: {PLATFORM_LABEL[platform]}.")
    else:
        known = PLATFORM_LABEL.get(platform, 'غير معروفة')
        add(CHECK_WARN, "منصة المتجر",
            f"المنصة ({known}) خارج المنصات التي عُوِّرت عليها الأداة "
            "(سلة وزد وشوبيفاي). الفحوص التالية هي ما يحدد موثوقية النتائج.",
            "راجع باقي الفحوص وعيّنة التحقق اليدوي قبل الإرسال.")

    # 2) حجم الزحف
    if n_ok == 0:
        add(CHECK_FAIL, "حجم الزحف", "لم تُفحص أي صفحة بنجاح.",
            "تحقق من أن الرابط صحيح وأن المتجر لا يحجب الزحف.")
    elif n_ok < 5:
        add(CHECK_FAIL, "حجم الزحف",
            f"{n_ok} صفحة فقط — رقم صغير جداً لمتجر إلكتروني.",
            "على الأرجح القائمة مبنية بـ JavaScript فلم يجد الزاحف روابط. "
            "هذا المتجر خارج نطاق الأداة.")
    else:
        add(CHECK_PASS, "حجم الزحف", f"{n_ok} صفحة مفحوصة بنجاح.")

    # 3) وجود منتجات
    n_prod = summary.get('products', 0)
    if n_ok >= 5 and n_prod == 0:
        add(CHECK_FAIL, "اكتشاف المنتجات",
            "لم يُعثر على أي صفحة منتج رغم نجاح الزحف.",
            "بنية روابط هذا المتجر غير معتادة — راجع تبويب الصفحات يدوياً.")
    elif n_prod:
        add(CHECK_PASS, "اكتشاف المنتجات", f"{n_prod} صفحة منتج.")

    # 4) نسبة غير المصنفة
    if n_ok:
        ratio = summary.get('unclassified', 0) / n_ok * 100
        if ratio > 25:
            add(CHECK_FAIL, "دقة التصنيف",
                f"{round(ratio, 1)}% من الصفحات لم تُصنّف آلياً.",
                "قواعد التصنيف لا تناسب بنية هذا المتجر. راجع تبويب الصفحات.")
        elif ratio > 10:
            add(CHECK_WARN, "دقة التصنيف",
                f"{round(ratio, 1)}% من الصفحات غير مصنّفة.",
                "راجعها في تبويب الصفحات قبل الإرسال.")
        else:
            add(CHECK_PASS, "دقة التصنيف",
                f"{round(ratio, 1)}% فقط غير مصنّفة.")

    # 5) رصد الصور على صفحات المنتجات (كاشف JavaScript الأهم)
    prod_pages = ok[ok['نوع الصفحة'] == T_PRODUCT] if n_ok else ok
    if len(prod_pages) >= 3:
        with_imgs = int((prod_pages['إجمالي الصور'] > 0).sum())
        pct = with_imgs / len(prod_pages) * 100
        if pct == 0:
            add(CHECK_FAIL, "رصد صور المنتجات",
                "لم تُرصد أي صورة على صفحات المنتجات.",
                "معرض الصور مبني بـ JavaScript. أرقام الصور في التقرير غير صحيحة.")
        elif pct < 60:
            add(CHECK_WARN, "رصد صور المنتجات",
                f"{round(pct, 1)}% فقط من صفحات المنتجات تحتوي صوراً مرصودة.",
                "افتح صفحة منتج وقارن عدد الصور الفعلي بالمسجّل.")
        else:
            add(CHECK_PASS, "رصد صور المنتجات",
                f"{round(pct, 1)}% من صفحات المنتجات بها صور مرصودة "
                f"({n_img} صورة فريدة).")

    # 6) قراءة البيانات الوصفية
    if n_ok:
        no_title = int((ok['طول العنوان'] == 0).sum())
        if no_title == n_ok:
            add(CHECK_FAIL, "قراءة العناوين",
                "كل الصفحات بلا عنوان — مؤشر على فشل في قراءة الصفحات.",
                "لا ترسل التقرير. افتح أي صفحة وتحقق من وجود وسم title.")
        elif no_title / n_ok > 0.5:
            add(CHECK_WARN, "قراءة العناوين",
                f"{no_title} صفحة بلا عنوان من أصل {n_ok}.",
                "تحقق من عيّنة في تبويب التحقق اليدوي.")
        else:
            add(CHECK_PASS, "قراءة العناوين",
                f"العناوين مقروءة في {n_ok - no_title} صفحة من {n_ok}.")

    # 6ب) العناوين الرمزية وقيم القوالب
    if n_ok and 'جودة العنوان' in ok.columns:
        sym = int(ok['جودة العنوان'].isin(QUALITY_FATAL).sum())
        if sym / n_ok > 0.6:
            add(CHECK_WARN, "سلامة العناوين",
                f"{sym} عنوان من أصل {n_ok} مجرد رموز أو قيمة قالب افتراضية — "
                "نسبة مرتفعة تعني أن قالب المتجر لا يولّد عناوين ميتا.",
                "تحقق من عيّنة يدوياً. هذه نتيجة حقيقية عن المتجر لا خلل في القراءة.")
        elif sym:
            add(CHECK_WARN, "سلامة العناوين",
                f"{sym} عنوان مجرد رموز أو قيمة قالب (مثل [] أو {{{{ }}}}).",
                "عُوملت كعناوين مفقودة في الأرقام.")
        else:
            add(CHECK_PASS, "سلامة العناوين", "لا توجد عناوين رمزية أو قيم قوالب.")

    # 6ج) مطابقة الرابط لاسم المنتج
    prod = ok[ok['نوع الصفحة'] == T_PRODUCT] if n_ok else ok
    if len(prod) >= 5 and 'جودة الرابط' in prod.columns:
        wrong = int((prod['جودة الرابط'] == 'u_wrongname').sum())
        noname = int((prod['اسم المنتج المعروض'].astype(str).str.strip() == '').sum()) \
            if 'اسم المنتج المعروض' in prod.columns else 0
        if noname == len(prod):
            add(CHECK_WARN, "قراءة اسم المنتج",
                "تعذّرت قراءة اسم المنتج من أي صفحة، فلم تُفحص مطابقة الروابط.",
                "قالب المتجر لا يستخدم وسم H1 للاسم.")
        elif wrong / len(prod) > 0.5:
            add(CHECK_WARN, "مطابقة الروابط",
                f"{wrong} رابط من {len(prod)} يحمل اسماً مختلفاً — نسبة مرتفعة.",
                "افتح عيّنة وتأكد أن الأمر واقع فعلي لا خطأ في قراءة الاسم.")
        else:
            add(CHECK_PASS, "مطابقة الروابط",
                f"{len(prod) - wrong} رابط من {len(prod)} يطابق اسم منتجه.")

    # 6د) مقارنة بما يعلنه المتجر نفسه — أقوى فحص تغطية
    if structured:
        checked = structured.get('categories_checked', 0)
        matched = structured.get('categories_matched', 0)
        short = structured.get('categories_short') or []
        miss = structured.get('missing_products', 0)
        if checked and short:
            pct = structured.get('coverage_pct') or 0
            lvl = CHECK_FAIL if pct < 70 else CHECK_WARN
            add(lvl, "تغطية أقسام المتجر",
                f"{len(short)} قسماً من {checked} يعلن منتجات أكثر مما رصده الزاحف "
                f"(ناقص {miss} منتجاً في المجموع).",
                "غالباً يحمّل القسم بقية منتجاته بالتمرير أو بزر «المزيد». "
                "راجع تبويب «البيانات المعلنة».")
        elif checked:
            add(CHECK_PASS, "تغطية أقسام المتجر",
                f"{matched} قسماً من {checked} مطابق تماماً لما يعلنه المتجر.")
        else:
            add(CHECK_WARN, "تغطية أقسام المتجر",
                "لم يعرض المتجر عدّاد منتجات في أقسامه، فتعذّرت مقارنة التغطية.",
                "اعتمد على عيّنة التحقق اليدوي بدلاً منها.")

        n_prod = structured.get('found_products', 0)
        gaps = structured.get('image_gap') or []
        if gaps:
            lvl = CHECK_FAIL if len(gaps) / max(n_prod, 1) > 0.5 else CHECK_WARN
            add(lvl, "مطابقة عدد الصور",
                f"{len(gaps)} صفحة منتج تعلن صوراً أكثر مما رصده الزاحف.",
                "معرض الصور يُحمَّل بـ JavaScript جزئياً. أرقام الصور أقل من الواقع.")
        elif n_prod:
            add(CHECK_PASS, "مطابقة عدد الصور",
                "عدد الصور المرصود يطابق ما يعلنه المتجر.")

        nm = structured.get('name_mismatch') or []
        if nm:
            add(CHECK_WARN, "مطابقة أسماء المنتجات",
                f"{len(nm)} منتجاً اسمه المعلن لمحركات البحث يختلف عن المعروض "
                "في الصفحة.",
                "راجعها في تبويب «البيانات المعلنة».")

        nj = structured.get('no_jsonld', 0)
        if n_prod and nj == n_prod:
            add(CHECK_WARN, "البيانات المهيكلة",
                "لا توجد بيانات منتجات مهيكلة في أي صفحة.",
                "هذا بحد ذاته نقص سيو في المتجر، ويحرم الأداة من مصدر تحقق.")
        elif n_prod:
            add(CHECK_PASS, "البيانات المهيكلة",
                f"{structured.get('jsonld_pages', 0)} صفحة منتج تحمل بيانات مهيكلة.")

    # 6هـ) تعذّر الاتصال — مؤشر على ضغط الفحص لا على عطل في المتجر
    unreach = summary.get('unreachable_pages', 0)
    if unreach:
        total_pages = max(len(df), 1)
        lvl = CHECK_WARN if unreach / total_pages < 0.15 else CHECK_FAIL
        add(lvl, "استقرار الاتصال",
            f"{unreach} صفحة تعذّر الاتصال بها رغم إعادة المحاولة.",
            "قد يحدّ المتجر من سرعة الزحف. خفّض «المسارات المتوازية» إلى 2 "
            "وأعد الفحص للحصول على تغطية كاملة.")

    # 7) المحتوى النصي الضعيف (مؤشر آخر على JavaScript)
    if n_ok:
        thin = summary.get('thin_pages', 0) / n_ok * 100
        if thin > 50:
            add(CHECK_FAIL, "قراءة المحتوى",
                f"{round(thin, 1)}% من الصفحات بمحتوى نصي شبه فارغ.",
                "المتجر يبني محتواه بـ JavaScript — النتائج غير معتمدة.")
        elif thin > 20:
            add(CHECK_WARN, "قراءة المحتوى",
                f"{round(thin, 1)}% من الصفحات بمحتوى نصي ضعيف.",
                "تأكد أن هذا واقع المتجر لا خلل في القراءة.")
        else:
            add(CHECK_PASS, "قراءة المحتوى", "المحتوى النصي مقروء بشكل طبيعي.")

    # 8) اكتمال الزحف
    if crawl_meta and crawl_meta.get('truncated'):
        add(CHECK_WARN, "اكتمال الزحف",
            f"توقف الزحف مع بقاء {crawl_meta.get('pending', 0)} رابط غير مفحوص.",
            "ارفع الحد الأقصى للصفحات من الإعدادات وأعد الفحص.")
    else:
        add(CHECK_PASS, "اكتمال الزحف", "غُطّيت كل الروابط المكتشفة.")

    # 9) اتساق المعروض مع خريطة الموقع
    if coverage and coverage.get('sitemap_count'):
        vis, sm = coverage['visible_count'], coverage['sitemap_count']
        if sm and vis / sm < 0.6:
            add(CHECK_WARN, "تغطية المنتجات",
                f"{vis} منتج معروض مقابل {sm} في خريطة الموقع.",
                "قد يستخدم المتجر تمريراً لانهائياً بدل ترقيم الصفحات، "
                "فلم يصل الزاحف لكل المنتجات.")
        else:
            add(CHECK_PASS, "تغطية المنتجات",
                f"{vis} منتج معروض مقابل {sm} في الخريطة — متسق.")

    # 10) الروابط المعطلة
    if n_ok:
        br = summary.get('broken_pages', 0)
        if br / max(len(df), 1) > 0.15:
            add(CHECK_WARN, "الروابط المعطلة",
                f"{br} رابط معطل — نسبة مرتفعة قد تعني حجباً جزئياً للزاحف.",
                "افتح عيّنة منها في المتصفح للتأكد أنها معطلة فعلاً.")
        else:
            add(CHECK_PASS, "الروابط المعطلة", f"{br} رابط معطل — ضمن المعقول.")

    fails = sum(1 for c in checks if c['level'] == CHECK_FAIL)
    warns = sum(1 for c in checks if c['level'] == CHECK_WARN)
    verdict = ('blocked' if fails else 'review' if warns else 'ready')
    return {'checks': checks, 'fails': fails, 'warns': warns, 'verdict': verdict}



# ==============================================================
#  مسار الفحص الكامل — نقطة دخول واحدة
#
#  تستدعيه الواجهة ويستدعيه الاختبار الآلي بنفس الطريقة، فلا يمكن
#  أن يختلف ما يُختبر عمّا يعمل فعلاً.
# ==============================================================
def run_full_scan(target, max_pages=MAX_PAGES_DEFAULT, workers=4,
                  do_pagination=True, do_sitemap_check=True, progress=None):
    """يشغّل الفحص من أوله لآخره ويعيد كل النتائج في قاموس واحد."""
    def say(stage, **kw):
        if progress:
            try:
                progress(stage, **kw)
            except Exception:
                pass

    target = normalize_url(target)

    say('crawl_start')
    pages, imgs, cat_urls, seen, platform, crawl_meta = crawl_store(
        target, max_pages, workers,
        (lambda d, pend, lvl: say('crawl', done=d, pending=pend, level=lvl)))
    cat_products = crawl_meta.setdefault('cat_products', {})

    if do_pagination and cat_urls:
        say('pagination_start')
        extra = harvest_paginated_products(
            target, cat_urls, seen,
            (lambda i, tot, f, fe: say('pagination', i=i, total=tot,
                                       found=f, fetched=fe)),
            cat_products=cat_products,
            listing_urls=crawl_meta.get('listing_urls'))
        if extra:
            say('extra_start', count=len(extra))
            p2, i2 = audit_urls(extra, target, 'ترقيم الأقسام', workers,
                                None)
            pages += p2
            imgs += i2

    # فشل الاتصال قد يكون ضغطاً مؤقتاً لا رابطاً معطلاً: نعيد المحاولة بتمهّل
    retry = [r['_raw_url'] for r in pages
             if not r['متاحة'] and 'فشل اتصال' in str(r['كود الاستجابة'])]
    if retry:
        say('retry_start', count=len(retry))
        time.sleep(2)
        fixed, fixed_imgs = audit_urls(retry[:120], target, 'إعادة محاولة', 2, None)
        good = {r['_raw_url']: r for r in fixed if r['متاحة']}
        if good:
            pages = [good.get(r['_raw_url'], r) for r in pages]
            imgs += [im for im in fixed_imgs
                     if im['رابط الصفحة'] in {g['الرابط'] for g in good.values()}]

    df = dedupe_pages(pd.DataFrame(pages))
    images_df = pd.DataFrame(imgs)
    if not images_df.empty:
        images_df = images_df[images_df['رابط الصفحة'].isin(df['الرابط'])] \
            .copy().reset_index(drop=True)
        images_df = apply_duplicate_alt(images_df)
    df, brand = analyze_text_quality(df)
    df = analyze_url_quality(df, brand)
    df, dup_groups = detect_duplicate_content(df)
    df = score_pages(df, images_df)

    coverage = None
    if do_sitemap_check:
        say('sitemap_start')
        sm_urls = collect_sitemap_urls(target)
        say('sitemap', count=len(sm_urls))
        coverage = build_coverage_report(df, sm_urls, target, workers)

    declared = {}
    for _, r in df.iterrows():
        v = r.get('عدد معلن')
        try:
            if v is not None and pd.notna(v) and int(v) > 0:
                declared[r['الرابط']] = int(v)
        except (TypeError, ValueError):
            continue
    structured = build_structured_report(df, declared, cat_products)

    summary = compute_summary(df, coverage, images_df)
    summary['structured'] = structured
    summary['platform'] = platform
    summary['platform_label'] = PLATFORM_LABEL.get(platform, '—')
    selfcheck = run_self_checks(df, images_df, coverage, platform, summary,
                                crawl_meta, structured)
    say('done')

    return {'df': df, 'images_df': images_df, 'summary': summary,
            'coverage': coverage, 'structured': structured,
            'selfcheck': selfcheck, 'brand': brand, 'dup_groups': dup_groups,
            'platform': platform, 'crawl_meta': crawl_meta,
            'declared': declared}


# ==============================================================
#  تقرير العميل (PDF)
# ==============================================================
PDF_TXT = {
    'ar': {
        'owner': 'أنس راشد', 'role': 'خبير تحسين محركات البحث',
        'title': 'تقرير الفحص الفني الشامل',
        'subtitle': 'تحسين محركات البحث للمتاجر الإلكترونية',
        'prepared': 'أُعدّ التقرير بواسطة أنس راشد — خبير تحسين محركات البحث',
        'store': 'المتجر', 'date': 'تاريخ الفحص', 'platform': 'المنصة',
        'scope': 'نطاق الفحص: الصفحات والمنتجات المعروضة فعلياً لزوار المتجر',
        'score_lbl': 'درجة التوافق العامة مع محركات البحث',
        'sc_bad': 'يحتاج معالجة عاجلة', 'sc_warn': 'مهيأ جزئياً', 'sc_ok': 'مستوى جيد',
        'page_of': 'صفحة {a}',
        'impact': 'الأثر على متجرك',
        'h_item': 'عنصر الفحص', 'h_val': 'النتيجة',
        'm_pages': 'صفحة معروضة', 'm_products': 'منتج', 'm_images': 'صورة',
        'm_issues': 'بند يحتاج معالجة', 'm_cats': 'قسم',
        'u_page': 'صفحة', 'u_product': 'منتج', 'u_cat': 'تصنيف', 'u_article': 'مقال',
        'u_link': 'رابط', 'u_title': 'عنوان', 'u_desc': 'وصف', 'u_img': 'صورة',
        'na': 'غير متاح',
    },
    'en': {
        'owner': 'Anas Rashed', 'role': 'SEO Expert',
        'title': 'Comprehensive Technical SEO Audit',
        'subtitle': 'Search engine optimisation for e-commerce stores',
        'prepared': 'Prepared by Anas Rashed - SEO Expert',
        'store': 'Store', 'date': 'Audit date', 'platform': 'Platform',
        'scope': 'Audit scope: pages and products actually visible to store visitors',
        'score_lbl': 'Overall search engine compliance score',
        'sc_bad': 'Needs urgent work', 'sc_warn': 'Partially optimised',
        'sc_ok': 'Good standard',
        'page_of': 'Page {a}',
        'impact': 'What this means for your store',
        'h_item': 'Audited item', 'h_val': 'Result',
        'm_pages': 'visible pages', 'm_products': 'products', 'm_images': 'images',
        'm_issues': 'items to fix', 'm_cats': 'categories',
        'u_page': 'pages', 'u_product': 'products', 'u_cat': 'categories',
        'u_article': 'articles', 'u_link': 'links', 'u_title': 'titles',
        'u_desc': 'descriptions', 'u_img': 'images', 'na': 'not available',
    },
}

SECTION_TXT = {
    'ar': {
        'structure': {
            'title': 'بنية المتجر ونطاق الفحص',
            'intro': 'يبدأ الفحص من الصفحة الرئيسية ويتصفح المتجر كما يتصفحه الزائر، '
                     'متتبعاً الروابط الداخلية وصفحات الأقسام. لا تدخل التقرير أي صفحة '
                     'لا يمكن للزائر الوصول إليها بالنقر.',
            'impact': 'هذه الأرقام هي ما تراه محركات البحث فعلياً عند زحفها للمتجر. أي '
                      'رابط معطل يصل إليه الزائر يهدر جزءاً من ميزانية الزحف المخصصة '
                      'للمتجر، ويقلل فرص أرشفة الصفحات المهمة.',
        },
        'meta': {
            'title': 'عناوين وأوصاف الميتا',
            'intro': 'عنوان الميتا هو السطر الأزرق القابل للنقر في نتائج البحث، والوصف '
                     'هو السطران تحته. المعيار المعتمد: العنوان بين 50 و60 حرفاً، والوصف '
                     'بين 120 و150 حرفاً، ويُحسب الطول بالحروف شاملاً المسافات وعلامات '
                     'الترقيم كما تحسبها محركات البحث.',
            'impact': 'العنوان القصير جداً يضيّع مساحة مجانية في نتيجة البحث، والطويل '
                      'يُقتطع بثلاث نقاط فتضيع نهايته. أما العنوان المفقود أو المكوّن من '
                      'رموز فيجعل جوجل يختار نصاً عشوائياً من الصفحة بدلاً عنه، وغالباً '
                      'ما يكون نصاً لا يشجع على النقر.',
        },
        'urls': {
            'title': 'روابط صفحات المتجر',
            'intro': 'الرابط عنصر سيو مستقل: تقرأه محركات البحث، ويظهر للزبون في نتيجة '
                     'البحث وعند مشاركة المنتج. يفحص هذا القسم صياغة الرابط ومطابقته '
                     'للمنتج المعروض، ووجود نسخ مكررة من منتج واحد.',
            'impact': 'المنتجات المستنسخة تُنشئ صفحات متطابقة تتنافس فيما بينها، فيوزّع '
                      'جوجل قوة الصفحة بين النسخ ثم يختار واحدة ويتجاهل الباقي. والرابط '
                      'الذي يحمل اسم منتج مختلف يربك الزبون: ينقر على شيء ويصل إلى آخر، '
                      'فترتفع نسبة المغادرة الفورية.',
        },
        'images': {
            'title': 'صور المتجر ونصوصها البديلة',
            'intro': 'النص البديل هو الوصف المرفق بالصورة في كود الصفحة. محركات البحث '
                     'لا ترى الصورة، بل تقرأ هذا النص. ويفحص هذا القسم أيضاً صيغة الصور، '
                     'إذ تؤثر مباشرة في حجم الصفحة وسرعتها.',
            'impact': 'بحث صور جوجل مصدر زيارات مهم في المتاجر البصرية كالأزياء والعطور '
                      'والهدايا، حيث يبحث الزبون بالصورة قبل الكلمة. الصورة بلا نص بديل '
                      'غير موجودة بالنسبة لجوجل. كما أن الصيغ الحديثة تخفض حجم الصورة '
                      'بنحو الثلث بنفس الجودة، فتتحسن سرعة الجوال تلقائياً.',
        },
        'sitemap': {
            'title': 'مقارنة المعروض بخريطة الموقع',
            'intro': 'خريطة الموقع هي القائمة التي يعلنها المتجر لمحركات البحث. يقارن '
                     'هذا القسم ما يراه الزائر فعلاً بما تعلنه الخريطة، في الاتجاهين.',
            'impact': 'المنتج المعروض وغير المدرج في الخريطة قد لا تعلم به محركات البحث '
                      'أصلاً. والصفحة المدرجة في الخريطة ولا يصل إليها الزائر بأي رابط '
                      'داخلي تبقى بلا قيمة: لا تستفيد من قوة المتجر ولا تجلب زيارات. '
                      'والروابط المحوّلة داخل الخريطة تستهلك ميزانية الزحف بلا مقابل.',
        },
        'diagnosis': {
            'title': 'التشخيص وخطة العمل',
            'intro': 'ملخص ما رصده الفحص، مرتباً حسب أثره على الظهور في نتائج البحث.',
            'impact': '',
        },
    },
    'en': {
        'structure': {
            'title': 'Store structure and audit scope',
            'intro': 'The audit starts at the homepage and browses the store the way a '
                     'visitor does, following internal links and category pages. No page '
                     'a visitor cannot reach by clicking enters this report.',
            'impact': 'These figures reflect what search engines actually encounter when '
                      'crawling the store. Every broken link a visitor can reach wastes '
                      'part of the crawl budget allocated to the store and reduces the '
                      'chance that important pages get indexed.',
        },
        'meta': {
            'title': 'Meta titles and descriptions',
            'intro': 'The meta title is the clickable blue line in search results; the '
                     'description is the two lines beneath it. Standard applied: titles '
                     'between 50 and 60 characters, descriptions between 120 and 150, '
                     'counted in characters including spaces and punctuation.',
            'impact': 'A very short title wastes free space in the result, while an '
                      'overly long one is truncated and loses its ending. A missing title '
                      'or one made of symbols leaves Google to pick arbitrary text from '
                      'the page instead, rarely text that invites a click.',
        },
        'urls': {
            'title': 'Page URLs',
            'intro': 'The URL is an SEO element in its own right: search engines read it, '
                     'and customers see it in results and when a product is shared. This '
                     'section checks URL formatting, its match to the displayed product, '
                     'and cloned copies of a single product.',
            'impact': 'Cloned products create near-identical pages competing with each '
                      'other, splitting page authority before Google picks one and '
                      'ignores the rest. A URL naming a different product confuses the '
                      'customer, who clicks one thing and lands on another, raising '
                      'bounce rate.',
        },
        'images': {
            'title': 'Store images and alt text',
            'intro': 'Alt text is the description attached to an image in the page code. '
                     'Search engines do not see the image; they read this text. This '
                     'section also checks image formats, which affect page weight and '
                     'loading and page weight directly.',
            'impact': 'Google Image search is a meaningful traffic source for visual '
                      'stores such as fashion, fragrance and gifts, where customers search '
                      'by image before words. An image without alt text does not exist to '
                      'Google. Modern formats also cut image weight by about a third at '
                      'the same quality, making pages lighter on mobile.',
        },
        'sitemap': {
            'title': 'Visible catalogue vs sitemap',
            'intro': 'The sitemap is the list the store declares to search engines. This '
                     'section compares what visitors actually see against what the sitemap '
                     'declares, in both directions.',
            'impact': 'A visible product missing from the sitemap may be unknown to search '
                      'engines. A sitemap page with no internal link path stays worthless: '
                      'it gains no authority and brings no traffic. Redirecting URLs inside '
                      'the sitemap consume crawl budget for nothing.',
        },
        'diagnosis': {
            'title': 'Diagnosis and action plan',
            'intro': 'A summary of the audit findings, ordered by impact on search '
                     'visibility.',
            'impact': '',
        },
    },
}

C_INK = (15, 23, 42)
C_MUTED = (100, 116, 139)
C_LINE = (226, 232, 240)
C_BG = (248, 250, 252)
C_OK = (5, 150, 105)
C_WARN = (217, 119, 6)
C_BAD = (220, 38, 38)
STATUS_RGB = {'ok': C_OK, 'warn': C_WARN, 'bad': C_BAD, 'neutral': C_MUTED}


def shape_ar(text):
    return get_display(arabic_reshaper.reshape(str(text)))


def build_diagnosis(score, stats, lang):
    """يُرجع (مقدمة، قائمة نقاط، خلاصة).

    القاعدة: العدد الرئيسي لكل بند هو ما يحتاج إصلاحاً فعلياً، لا كل ما
    يخرج عن المثالي. «مقبول» فرصة تحسين وليس عيباً، فيُذكر منفصلاً.
    """
    imgs = stats.get('total_images', 0)
    missing = stats.get('missing_alts', 0)
    weak = stats.get('weak_alts', 0)
    crit_t = stats.get('critical_titles', 0)
    crit_d = stats.get('critical_descs', 0)
    imp_t = max(stats.get('bad_titles', 0) - crit_t, 0)   # مقبول: قابل للتحسين
    imp_d = max(stats.get('bad_descs', 0) - crit_d, 0)
    points = []

    if lang == 'ar':
        if missing and imgs:
            points.append(f"{missing} صورة من أصل {imgs} بلا نص بديل إطلاقاً "
                          f"({round(missing / imgs * 100, 1)}%)، فلا تظهر في بحث صور جوجل.")
        if weak:
            points.append(f"{weak} صورة نصها البديل موجود لكنه غير وصفي أو مكرر، "
                          "فلا يضيف قيمة لمحركات البحث.")
        if stats.get('title_symbols'):
            points.append(f"{stats['title_symbols']} عنوان ميتا مجرد رموز أو قيمة قالب "
                          "افتراضية بدل النص، أي أن الصفحة بلا عنوان فعلي "
                          "في نتائج البحث.")
        if stats.get('title_brand_only'):
            points.append(f"{stats['title_brand_only']} عنوان لا يحمل سوى اسم المتجر "
                          "بلا أي وصف للمنتج، فلا يطابق أي بحث للزبون.")
        if stats.get('title_dup'):
            points.append(f"{stats['title_dup']} صفحة تتشارك نفس عنوان الميتا، "
                          "فلا تميّز محركات البحث بينها.")
        if stats.get('desc_same'):
            points.append(f"{stats['desc_same']} وصف ميتا نسخة حرفية من العنوان، "
                          "فيضيع سطر إضافي مجاني في نتيجة البحث.")
        if crit_t:
            points.append(f"{crit_t} عنوان ميتا يحتاج إصلاحاً عاجلاً: مفقود أو أقصر من "
                          f"{TITLE_MIN_OK} حرفاً أو يتجاوز {TITLE_MAX} حرفاً فيُقتطع "
                          "في نتائج البحث.")
        if imp_t:
            points.append(f"{imp_t} عنوان ضمن الحد المقبول ويمكن رفعه إلى الطول المثالي "
                          f"({TITLE_MIN_OPTIMAL}-{TITLE_MAX} حرفاً) لاستغلال كامل "
                          "المساحة المعروضة.")
        if crit_d:
            points.append(f"{crit_d} وصف ميتا يحتاج إصلاحاً عاجلاً: مفقود أو أقصر من "
                          f"{DESC_MIN_OK} حرفاً أو يتجاوز {DESC_MAX} حرفاً.")
        if imp_d:
            points.append(f"{imp_d} وصف ضمن الحد المقبول ويمكن رفعه إلى الطول المثالي "
                          f"({DESC_MIN_OPTIMAL}-{DESC_MAX} حرفاً).")
        if stats.get('url_clone'):
            points.append(f"{stats['url_clone']} منتجاً مستنسخاً: رابطه يحمل بادئة "
                          "النسخ أو لاحقة رقمية، وهي نسخ مكررة من منتج واحد تتنافس "
                          "مع أصلها في نتائج البحث.")
        if stats.get('dup_content'):
            points.append(f"{stats['dup_content']} صفحة تتشارك نفس العنوان والوصف "
                          "حرفياً، فتُعدّ محتوى مكرراً ويختار جوجل واحدة ويتجاهل الباقي.")
        if stats.get('url_wrongname'):
            points.append(f"{stats['url_wrongname']} رابط يحمل اسم منتج مختلف عن المنتج "
                          "المعروض في الصفحة، غالباً لأن المنتج نُسخ ثم غُيّر اسمه دون "
                          "تحديث الرابط. الزبون يصل لصفحة لا تطابق ما نقر عليه.")
        if stats.get('url_style'):
            points.append(f"{stats['url_style']} رابط بصياغة غير مثالية: شرطة سفلية "
                          "أو حروف كبيرة أو طول مفرط أو تكرار كلمة داخل الرابط.")
        if stats.get('url_generic'):
            points.append(f"{stats['url_generic']} رابط مكوّن من أرقام أو رموز بلا "
                          "كلمات وصفية.")
        if stats.get('img_legacy') and stats.get('img_modern_pct', 100) < 50:
            points.append(f"{stats['img_legacy']} صورة بصيغة قديمة ثقيلة بدل الصيغ "
                          "الحديثة الخفيفة، ما يزيد حجم الصفحة ويبطئ تحميلها "
                          "على الجوال.")
        if stats.get('canon_missing'):
            points.append(f"{stats['canon_missing']} صفحة بلا وسم كانونيكال، "
                          "ما يعرّض المتجر لتكرار المحتوى.")
        if stats.get('hidden_count'):
            points.append(f"{stats['hidden_count']} صفحة منشورة في خريطة الموقع لا يصل "
                          "إليها الزائر بأي رابط داخلي، فتفقد قيمتها.")
        if stats.get('redirect_count'):
            points.append(f"{stats['redirect_count']} رابط في خريطة الموقع يعيد التوجيه "
                          "لصفحة أخرى، ما يستهلك ميزانية زحف المتجر بلا فائدة.")
        if stats.get('not_indexed_count'):
            points.append(f"{stats['not_indexed_count']} منتجاً معروضاً في المتجر "
                          "لا يظهر في خريطة الموقع.")
        if stats.get('broken_pages'):
            points.append(f"{stats['broken_pages']} رابط معطل داخل المتجر يصل إليه الزائر.")
        if stats.get('archive_pages', 0) > 20:
            points.append(f"{stats['archive_pages']} صفحة أرشيف (وسوم وقوائم) تعرض "
                          "محتوى مكرراً بعنوان واحد، وتستهلك ميزانية الزحف دون أن "
                          "تجلب زيارات. يوصى بحصر الوسوم في المفيد منها.")
        if stats.get('thin_pages'):
            points.append(f"{stats['thin_pages']} صفحة بمحتوى نصي أقل من 50 كلمة.")

        if not points:
            return ("لم يرصد الفحص فجوات جوهرية في الصفحات المعروضة:", [
                "العناوين والأوصاف ضمن الأطوال الموصى بها.",
                "النصوص البديلة للصور مكتملة ووصفية.",
                "بنية الروابط وخريطة الموقع متسقة مع ما يراه الزائر."],
                "يوصى بمراجعة دورية عند إضافة منتجات أو أقسام جديدة.")

        intro = "رصد الفحص الفني النقاط التالية، مرتبة حسب أثرها على الظهور في البحث:"
        if score < 60:
            close = ("تشير النتيجة الإجمالية إلى فجوة واسعة في تهيئة المتجر لمحركات "
                     "البحث. يوصى بإعادة كتابة البيانات الوصفية وإسناد نصوص بديلة "
                     "وصفية لجميع صور المحتوى ضمن خطة عمل مرحلية.")
        elif score < 80:
            close = ("المتجر مهيأ جزئياً، ومعالجة البنود أعلاه من شأنها رفع درجة "
                     "التوافق وتحسين فرص الظهور في نتائج البحث.")
        else:
            close = ("المستوى العام جيد، والبنود أعلاه تحسينات تكميلية يمكن تنفيذها "
                     "ضمن جولة مراجعة واحدة.")
        return intro, points, close

    if missing and imgs:
        points.append(f"{missing} of {imgs} images ({round(missing / imgs * 100, 1)}%) "
                      "carry no alt text at all and cannot appear in Google Image search.")
    if weak:
        points.append(f"{weak} images have alt text that is present but non-descriptive "
                      "or duplicated, adding no value for search engines.")
    if stats.get('title_symbols'):
        points.append(f"{stats['title_symbols']} meta titles are only symbols or "
                      "template placeholders, leaving those pages with no real title.")
    if stats.get('title_brand_only'):
        points.append(f"{stats['title_brand_only']} titles contain nothing but the store "
                      "name, matching no customer search.")
    if stats.get('title_dup'):
        points.append(f"{stats['title_dup']} pages share an identical meta title.")
    if stats.get('desc_same'):
        points.append(f"{stats['desc_same']} descriptions are a verbatim copy of the "
                      "title, wasting a free line in the search result.")
    if crit_t:
        points.append(f"{crit_t} meta titles need urgent work: missing, under "
                      f"{TITLE_MIN_OK} characters, or over {TITLE_MAX} and truncated "
                      "in search results.")
    if imp_t:
        points.append(f"{imp_t} titles are acceptable and could be raised to the optimal "
                      f"{TITLE_MIN_OPTIMAL}-{TITLE_MAX} character range.")
    if crit_d:
        points.append(f"{crit_d} meta descriptions need urgent work: missing, under "
                      f"{DESC_MIN_OK} characters, or over {DESC_MAX}.")
    if imp_d:
        points.append(f"{imp_d} descriptions are acceptable and could be raised to the "
                      f"optimal {DESC_MIN_OPTIMAL}-{DESC_MAX} character range.")
    if stats.get('url_clone'):
        points.append(f"{stats['url_clone']} cloned products carry a copy-of prefix in "
                      "their URL and compete with the original in search results.")
    if stats.get('dup_content'):
        points.append(f"{stats['dup_content']} pages share an identical title and "
                      "description, counting as duplicate content.")
    if stats.get('url_wrongname'):
        points.append(f"{stats['url_wrongname']} URLs carry a different product name than "
                      "the page displays, usually because a product was cloned and "
                      "renamed without updating its URL.")
    if stats.get('url_style'):
        points.append(f"{stats['url_style']} URLs have imperfect formatting: underscores, "
                      "uppercase letters, excessive length, or a repeated word.")
    if stats.get('url_generic'):
        points.append(f"{stats['url_generic']} URLs consist of numbers or codes with no "
                      "descriptive words.")
    if stats.get('img_legacy') and stats.get('img_modern_pct', 100) < 50:
        points.append(f"{stats['img_legacy']} images use legacy formats (JPEG/PNG) "
                      "instead of WebP, increasing page weight on mobile.")
    if stats.get('canon_missing'):
        points.append(f"{stats['canon_missing']} pages have no canonical tag, exposing "
                      "the store to duplicate content.")
    if stats.get('hidden_count'):
        points.append(f"{stats['hidden_count']} pages published in the sitemap have no "
                      "internal link path for visitors and lose their value.")
    if stats.get('redirect_count'):
        points.append(f"{stats['redirect_count']} sitemap URLs redirect elsewhere, "
                      "consuming crawl budget without benefit.")
    if stats.get('not_indexed_count'):
        points.append(f"{stats['not_indexed_count']} visible products are absent "
                      "from the sitemap.")
    if stats.get('broken_pages'):
        points.append(f"{stats['broken_pages']} broken links are reachable by visitors.")
    if stats.get('archive_pages', 0) > 20:
        points.append(f"{stats['archive_pages']} archive pages (tags and lists) show "
                      "duplicated content under a single title and consume crawl "
                      "budget without bringing traffic.")
    if stats.get('thin_pages'):
        points.append(f"{stats['thin_pages']} pages carry fewer than 50 words of text.")

    if not points:
        return ("The audit found no material gaps across the visible pages:", [
            "Titles and descriptions fall within recommended lengths.",
            "Image alt text is complete and descriptive.",
            "Link structure and sitemap match what visitors can reach."],
            "Periodic review is advised as new products are added.")

    intro = "The technical audit identified the following, ordered by search impact:"
    if score < 60:
        close = ("The overall score indicates a substantial gap in search engine "
                 "readiness. Rewriting metadata and assigning descriptive alt text to "
                 "all content images is recommended as a phased programme of work.")
    elif score < 80:
        close = ("The store is partially optimised. Addressing the items above would "
                 "raise the compliance score and improve search visibility.")
    else:
        close = ("The overall standard is good; the items above are incremental "
                 "improvements that fit into a single review cycle.")
    return intro, points, close


def generate_client_pdf(domain, score, stats, lang='ar'):
    """تقرير عميل بتصميم حديث: غلاف، ثم قسم لكل محور في صفحة مستقلة
    يضم شرحاً للمقياس وجدول النتائج وصندوق الأثر، ثم التشخيص وخطة العمل."""
    rtl = (lang == 'ar')
    if rtl and not FONT_PATH.exists():
        raise FileNotFoundError(
            f"ملف الخط غير موجود: {FONT_PATH.name}. ارفع أحد الخطوط المدعومة "
            "إلى جذر المستودع.")

    T = PDF_TXT[lang]
    S = SECTION_TXT[lang]
    def _latin(t):
        t = str(t)
        for a, b in [('—', '-'), ('–', '-'), ('·', '|'), ('’', "'"), ('‘', "'"),
                     ('“', '"'), ('”', '"'), ('…', '...'), ('•', '-')]:
            t = t.replace(a, b)
        return t.encode('latin-1', 'replace').decode('latin-1')

    use_shaping = rtl and HAS_SHAPING
    fmt = (lambda t: str(t)) if use_shaping else (shape_ar if rtl else _latin)
    if not rtl:
        fmt = _latin
    ALIGN = "R" if rtl else "L"
    FONT = AR_FONT_NAME if rtl else "Helvetica"
    has_bold = bool(FONT_BOLD_PATH) if rtl else True

    def BOLD():
        return "B" if has_bold else ""
    clean_domain = urlparse(domain).netloc or domain
    logo_exists = LOGO_PATH.exists()
    M = 18                      # الهامش
    W = 210 - 2 * M             # عرض المحتوى
    verdict_rgb = C_BAD if score < 60 else (C_WARN if score < 80 else C_OK)

    class Report(FPDF):
        def header(self):
            if self.page_no() <= 1:
                return
            self.set_y(10)
            self.set_font(FONT, "", 8)
            self.set_text_color(*C_MUTED)
            self.cell(W, 4, fmt(f"{T['owner']}  ·  {clean_domain}"), align=ALIGN)
            self.set_draw_color(*C_LINE)
            self.line(M, 17, 210 - M, 17)
            self.set_y(26)

        def footer(self):
            if self.page_no() <= 1:
                return
            self.set_y(-16)
            self.set_draw_color(*C_LINE)
            self.line(M, 282, 210 - M, 282)
            self.set_font(FONT, "", 8)
            self.set_text_color(*C_MUTED)
            self.cell(W / 2, 8, "anasrashed.com", align="L" if rtl else "R")
            self.cell(W / 2, 8, fmt(T['page_of'].format(a=self.page_no())),
                      align="R" if rtl else "L")

        # ---------- أدوات الرسم ----------
        def wrap(self, txt, width, size=9):
            self.set_font(FONT, "", size)
            out, cur = [], ""
            for word in str(txt).split():
                trial = (cur + " " + word).strip()
                if self.get_string_width(fmt(trial)) <= width:
                    cur = trial
                else:
                    if cur:
                        out.append(cur)
                    cur = word
            if cur:
                out.append(cur)
            return out

        def safe(self, txt):
            """Helvetica لا يدعم يونيكود: تُستبدل الرموز الطويلة في النسخة اللاتينية."""
            t = str(txt)
            if rtl:
                return t
            for a, b in [('—', '-'), ('–', '-'), ('·', '|'), ('’', "'"),
                         ('‘', "'"), ('“', '"'), ('”', '"'), ('…', '...'),
                         ('•', '-')]:
                t = t.replace(a, b)
            return t.encode('latin-1', 'replace').decode('latin-1')

        def para(self, txt, width=W, size=9, color=C_MUTED, lh=5.0, x=M):
            self.set_font(FONT, "", size)
            self.set_text_color(*color)
            for line in self.wrap(txt, width, size):
                self.set_x(x)
                self.cell(width, lh, fmt(line), ln=True, align=ALIGN)

        def section(self, num, key):
            """ترويسة قسم: مربع رقم ملوّن + عنوان + شرح."""
            y = self.get_y()
            box = 9
            bx = (210 - M - box) if rtl else M
            self.set_fill_color(*C_INK)
            self.rect(bx, y, box, box, 'F')
            self.set_font(FONT, "", 10)
            self.set_text_color(255, 255, 255)
            self.set_xy(bx, y + 0.6)
            self.cell(box, box - 1, str(num), align="C")
            self.set_font(FONT, BOLD(), 15)
            self.set_text_color(*C_INK)
            tw = W - box - 4
            self.set_xy(M if rtl else M + box + 4, y + 0.4)
            self.cell(tw, box, fmt(S[key]['title']), align=ALIGN)
            self.set_y(y + box + 4)
            self.para(S[key]['intro'])
            self.ln(3)

        def table(self, rows):
            """جدول نتائج: عمود العنصر وعمود النتيجة بلون دلالي."""
            wv, wl = 52, W - 52
            self.set_font(FONT, BOLD(), 9.5)
            self.set_fill_color(*C_INK)
            self.set_text_color(255, 255, 255)
            self.set_x(M)
            if rtl:
                self.cell(wv, 8, fmt(T['h_val']), 0, 0, 'C', fill=True)
                self.cell(wl, 8, fmt(T['h_item']), 0, 1, 'R', fill=True)
            else:
                self.cell(wl, 8, fmt(T['h_item']), 0, 0, 'L', fill=True)
                self.cell(wv, 8, fmt(T['h_val']), 0, 1, 'C', fill=True)
            self.set_font(FONT, "", 9)
            for i, (label, value, stt) in enumerate(rows):
                if self.get_y() > 250:
                    self.add_page()
                self.set_x(M)
                if i % 2 == 0:
                    self.set_fill_color(*C_BG)
                    self.rect(M, self.get_y(), W, 7.5, 'F')
                self.set_text_color(*STATUS_RGB.get(stt, C_MUTED))
                self.set_font(FONT, "", 9)
                if rtl:
                    self.cell(wv, 7.5, fmt(value), 0, 0, 'C')
                    self.set_text_color(*C_INK)
                    self.cell(wl, 7.5, fmt(label), 0, 1, 'R')
                else:
                    self.set_text_color(*C_INK)
                    self.cell(wl, 7.5, fmt(label), 0, 0, 'L')
                    self.set_text_color(*STATUS_RGB.get(stt, C_MUTED))
                    self.cell(wv, 7.5, fmt(value), 0, 1, 'C')
                self.set_draw_color(*C_LINE)
                self.line(M, self.get_y(), 210 - M, self.get_y())
            self.ln(6)

        def impact(self, key):
            txt = S[key].get('impact')
            if not txt:
                return
            lines = self.wrap(txt, W - 14, 9)
            h = len(lines) * 5.0 + 13
            if self.get_y() + h > 265:
                self.add_page()
            y = self.get_y()
            self.set_fill_color(*C_BG)
            self.rect(M, y, W, h, 'F')
            self.set_fill_color(*C_INK)
            if rtl:
                self.rect(210 - M - 2.2, y, 2.2, h, 'F')
            else:
                self.rect(M, y, 2.2, h, 'F')
            self.set_font(FONT, BOLD(), 9.5)
            self.set_text_color(*C_INK)
            self.set_xy(M + 7, y + 3.5)
            self.cell(W - 14, 5, fmt(T['impact']), ln=True, align=ALIGN)
            self.set_font(FONT, "", 9)
            self.set_text_color(*C_MUTED)
            yy = y + 9.5
            for line in lines:
                self.set_xy(M + 7, yy)
                self.cell(W - 14, 5, fmt(line), align=ALIGN)
                yy += 5.0
            self.set_y(y + h + 6)

        def mini(self, x, y, w, value, label, color=C_INK):
            self.set_fill_color(*C_BG)
            self.rect(x, y, w, 20, 'F')
            self.set_font(FONT, BOLD(), 15)
            self.set_text_color(*color)
            self.set_xy(x, y + 3)
            self.cell(w, 8, fmt(value), align="C")
            self.set_font(FONT, "", 8)
            self.set_text_color(*C_MUTED)
            self.set_xy(x, y + 11.5)
            self.cell(w, 5, fmt(label), align="C")

    pdf = Report()
    if rtl:
        pdf.add_font(AR_FONT_NAME, "", str(FONT_PATH))
        if FONT_BOLD_PATH:
            pdf.add_font(AR_FONT_NAME, "B", str(FONT_BOLD_PATH))
        if use_shaping:
            pdf.set_text_shaping(True, direction="rtl")
    pdf.set_auto_page_break(True, margin=22)

    # ======================= الغلاف =======================
    pdf.add_page()
    if logo_exists:
        try:
            pdf.image(str(LOGO_PATH), x=(210 - 40) / 2, y=22, h=15)
        except Exception:
            pass
    pdf.set_y(48)
    pdf.set_draw_color(*C_LINE)
    pdf.line(M + 55, 46, 210 - M - 55, 46)

    pdf.set_font(FONT, BOLD(), 23)
    pdf.set_text_color(*C_INK)
    pdf.cell(0, 12, fmt(T['title']), ln=True, align="C")
    pdf.set_font(FONT, "", 11)
    pdf.set_text_color(*C_MUTED)
    pdf.cell(0, 7, fmt(T['subtitle']), ln=True, align="C")
    pdf.ln(6)

    # بطاقة الدرجة
    y = pdf.get_y()
    pdf.set_fill_color(*C_BG)
    pdf.rect(M, y, W, 44, 'F')
    pdf.set_fill_color(*verdict_rgb)
    pdf.rect(M, y, W, 1.6, 'F')
    pdf.set_font(FONT, BOLD(), 40)
    pdf.set_text_color(*verdict_rgb)
    pdf.set_xy(M, y + 7)
    pdf.cell(W, 18, f"{score}%", align="C")
    pdf.set_font(FONT, "", 10.5)
    pdf.set_text_color(*C_INK)
    pdf.set_xy(M, y + 25)
    pdf.cell(W, 6, fmt(T['score_lbl']), align="C")
    pdf.set_font(FONT, "", 9)
    pdf.set_text_color(*C_MUTED)
    pdf.set_xy(M, y + 32)
    verdict_lbl = (T['sc_bad'] if score < 60 else
                   T['sc_warn'] if score < 80 else T['sc_ok'])
    pdf.cell(W, 6, fmt(verdict_lbl), align="C")
    pdf.set_y(y + 52)

    # بطاقات موجزة
    cards = [
        (str(stats['total_pages']), T['m_pages'], C_INK),
        (str(stats['products']), T['m_products'], C_INK),
        (str(stats['categories']), T['m_cats'], C_INK),
        (str(stats.get('total_images', 0)), T['m_images'], C_INK),
        (str(stats.get('critical_titles', 0) + stats.get('missing_alts', 0)),
         T['m_issues'], C_BAD),
    ]
    gap, cw = 4, (W - 2 * 4) / 3
    y0 = pdf.get_y()
    for i, (v, l, c) in enumerate(cards):
        col, row = i % 3, i // 3
        pdf.mini(M + col * (cw + gap), y0 + row * 24, cw, v, l, c)
    pdf.set_y(y0 + 56)

    # بيانات المتجر
    pdf.set_draw_color(*C_LINE)
    pdf.line(M, pdf.get_y(), 210 - M, pdf.get_y())
    pdf.ln(5)
    pdf.set_font(FONT, "", 10)
    pdf.set_text_color(*C_INK)
    for lbl, val in [(T['store'], clean_domain),
                     (T['platform'], stats.get('platform_label', '—')),
                     (T['date'], datetime.now().strftime('%Y-%m-%d'))]:
        pdf.set_x(M)
        pdf.cell(W, 6.5, fmt(f"{lbl}: {val}"), ln=True, align=ALIGN)
    pdf.ln(3)
    pdf.set_font(FONT, "", 8.5)
    pdf.set_text_color(*C_MUTED)
    pdf.set_x(M)
    pdf.cell(W, 5, fmt(T['scope']), ln=True, align=ALIGN)

    pdf.set_y(265)
    pdf.set_font(FONT, "", 9)
    pdf.set_text_color(*C_MUTED)
    pdf.cell(0, 5, fmt(T['prepared']), ln=True, align="C")
    pdf.cell(0, 5, "anasrashed.com   |   anas@anasrashed.com", align="C")

    n = 0

    # ======================= البنية =======================
    n += 1
    pdf.add_page()
    pdf.section(n, 'structure')
    pdf.table([
        ('إجمالي الصفحات المعروضة والمفحوصة' if rtl else 'Total visible pages audited',
         f"{stats['total_pages']} {T['u_page']}", 'neutral'),
        ('صفحات المنتجات' if rtl else 'Product pages',
         f"{stats['products']} {T['u_product']}", 'neutral'),
        ('صفحات الأقسام والكولكشنات' if rtl else 'Category and collection pages',
         f"{stats['categories']} {T['u_cat']}", 'neutral'),
        ('مقالات وصفحات المدونة' if rtl else 'Blog posts and articles',
         f"{stats.get('blog_pages', 0)} {T['u_article']}",
         'warn' if not stats.get('blog_pages') else 'neutral'),
        ('صفحات أرشيف (وسوم وقوائم)' if rtl else 'Archive pages (tags and lists)',
         f"{stats.get('archive_pages', 0)} {T['u_page']}",
         'warn' if stats.get('archive_pages', 0) > 20 else 'neutral'),
        ('الصفحات التعريفية والسياسات' if rtl else 'Info and policy pages',
         f"{stats['info_pages']} {T['u_page']}", 'neutral'),
        ('روابط معطلة يصل إليها الزائر' if rtl else 'Broken links reachable by visitors',
         f"{stats.get('broken_pages', 0)} {T['u_link']}",
         'bad' if stats.get('broken_pages') else 'ok'),
        ('صفحات تعذّر الاتصال بها أثناء الفحص' if rtl else
         'Pages unreachable during the scan',
         f"{stats.get('unreachable_pages', 0)} {T['u_page']}",
         'warn' if stats.get('unreachable_pages') else 'ok'),
        ('صفحات بمحتوى نصي ضعيف' if rtl else 'Pages with thin text content',
         f"{stats.get('thin_pages', 0)} {T['u_page']}",
         'warn' if stats.get('thin_pages') else 'ok'),
    ])
    pdf.impact('structure')

    # ======================= الميتا =======================
    n += 1
    pdf.add_page()
    pdf.section(n, 'meta')
    tot = max(stats['total_pages'] - stats.get('broken_pages', 0), 1)
    ok_t = tot - stats['bad_titles']
    ok_d = tot - stats['bad_descs']
    pdf.table([
        ('عناوين ضمن الطول المثالي (50-60)' if rtl else
         'Titles within optimal length (50-60)',
         (f"{ok_t} من {tot}" if rtl else f"{ok_t} of {tot}"),
         'ok' if ok_t / tot > 0.7 else 'warn'),
        ('عناوين تحتاج إصلاحاً عاجلاً' if rtl else 'Titles needing urgent work',
         f"{stats.get('critical_titles', 0)} {T['u_title']}",
         'bad' if stats.get('critical_titles') else 'ok'),
        ('عناوين مجرد رموز أو قيمة قالب' if rtl else
         'Titles that are symbols or placeholders',
         f"{stats.get('title_symbols', 0)} {T['u_title']}",
         'bad' if stats.get('title_symbols') else 'ok'),
        ('عناوين لا تحمل سوى اسم المتجر' if rtl else 'Titles with only the store name',
         f"{stats.get('title_brand_only', 0)} {T['u_title']}",
         'bad' if stats.get('title_brand_only') else 'ok'),
        ('صفحات تتشارك نفس العنوان' if rtl else 'Pages sharing the same title',
         f"{stats.get('title_dup', 0)} {T['u_page']}",
         'warn' if stats.get('title_dup') else 'ok'),
        ('أوصاف ضمن الطول المثالي (120-150)' if rtl else
         'Descriptions within optimal length (120-150)',
         (f"{ok_d} من {tot}" if rtl else f"{ok_d} of {tot}"),
         'ok' if ok_d / tot > 0.7 else 'warn'),
        ('أوصاف تحتاج إصلاحاً عاجلاً' if rtl else 'Descriptions needing urgent work',
         f"{stats.get('critical_descs', 0)} {T['u_desc']}",
         'bad' if stats.get('critical_descs') else 'ok'),
        ('صفحات بلا وسم كانونيكال' if rtl else 'Pages without a canonical tag',
         f"{stats.get('canon_missing', 0)} {T['u_page']}",
         'warn' if stats.get('canon_missing') else 'ok'),
    ])
    pdf.impact('meta')

    # ======================= الروابط =======================
    n += 1
    pdf.add_page()
    pdf.section(n, 'urls')
    good_u = max(tot - stats.get('url_bad', 0), 0)
    pdf.table([
        ('روابط سليمة الصياغة' if rtl else 'Well-formed URLs',
         (f"{good_u} من {tot}" if rtl else f"{good_u} of {tot}"),
         'ok' if good_u / tot > 0.8 else 'warn'),
        ('منتجات مستنسخة من منتج واحد' if rtl else 'Cloned products',
         f"{stats.get('url_clone', 0)} {T['u_product']}",
         'bad' if stats.get('url_clone') else 'ok'),
        ('صفحات بنفس العنوان والوصف حرفياً' if rtl else
         'Pages with identical title and description',
         f"{stats.get('dup_content', 0)} {T['u_page']}",
         'bad' if stats.get('dup_content') else 'ok'),
        ('روابط تحمل اسم منتج مختلف' if rtl else 'URLs naming a different product',
         f"{stats.get('url_wrongname', 0)} {T['u_link']}",
         'bad' if stats.get('url_wrongname') else 'ok'),
        ('روابط بأرقام أو رموز بلا كلمات' if rtl else 'URLs with no descriptive words',
         f"{stats.get('url_generic', 0)} {T['u_link']}",
         'warn' if stats.get('url_generic') else 'ok'),
        ('روابط بصياغة غير مثالية' if rtl else 'URLs with imperfect formatting',
         f"{stats.get('url_style', 0)} {T['u_link']}",
         'warn' if stats.get('url_style') else 'ok'),
    ])
    pdf.impact('urls')

    # ======================= الصور =======================
    n += 1
    pdf.add_page()
    pdf.section(n, 'images')
    imgs = stats.get('total_images', 0)
    noalt = stats.get('missing_alts', 0)
    weak = stats.get('weak_alts', 0)
    good = stats.get('good_alts', 0)
    ratio = round((noalt + weak) / imgs * 100, 1) if imgs else 0
    fmts = ' · '.join(f"{k.upper()} {v}" for k, v in
                      list((stats.get('img_formats') or {}).items())[:4]) or '—'
    pdf.table([
        ('إجمالي صور المحتوى والمنتجات' if rtl else 'Total content and product images',
         f"{imgs} {T['u_img']}", 'neutral'),
        ('صور بلا نص بديل إطلاقاً' if rtl else 'Images with no alt text at all',
         f"{noalt} {T['u_img']}", 'bad' if noalt else 'ok'),
        ('صور بنص بديل غير وصفي أو مكرر' if rtl else
         'Images with non-descriptive or duplicated alt text',
         f"{weak} {T['u_img']}", 'warn' if weak else 'ok'),
        ('صور بنص بديل سليم' if rtl else 'Images with sound alt text',
         f"{good} {T['u_img']}", 'ok' if good else 'neutral'),
        ('نسبة الصور غير المهيأة' if rtl else 'Share of images not optimised',
         f"{ratio}%", 'bad' if ratio > 50 else 'warn' if ratio else 'ok'),
        ('صيغ الصور المستخدمة' if rtl else 'Image formats in use', fmts, 'neutral'),
        ('نسبة الصور بالصيغ الحديثة الخفيفة' if rtl else
         'Share of modern lightweight formats',
         f"{stats.get('img_modern_pct', 0)}%",
         'ok' if stats.get('img_modern_pct', 0) > 50 else 'warn'),
    ])
    pdf.impact('images')

    # ======================= خريطة الموقع =======================
    if stats.get('coverage_enabled'):
        n += 1
        pdf.add_page()
        pdf.section(n, 'sitemap')
        pdf.table([
            ('منتجات معروضة لزوار المتجر' if rtl else 'Products visible to visitors',
             f"{stats.get('visible_products', 0)} {T['u_product']}", 'neutral'),
            ('منتجات معلنة في خريطة الموقع' if rtl else 'Products declared in sitemap',
             f"{stats.get('sitemap_products', 0)} {T['u_product']}", 'neutral'),
            ('منتجات معروضة ولا تظهر في الخريطة' if rtl else
             'Visible products absent from sitemap',
             f"{stats.get('not_indexed_count', 0)} {T['u_product']}",
             'bad' if stats.get('not_indexed_count') else 'ok'),
            ('روابط في الخريطة تعيد التوجيه' if rtl else 'Sitemap URLs redirecting',
             f"{stats.get('redirect_count', 0)} {T['u_link']}",
             'warn' if stats.get('redirect_count') else 'ok'),
            ('صفحات في الخريطة لا يصل إليها الزائر' if rtl else
             'Sitemap pages unreachable by visitors',
             f"{stats.get('hidden_count', 0)} {T['u_page']}",
             'warn' if stats.get('hidden_count') else 'ok'),
            ('نسبة المنتجات المعروضة المدرجة' if rtl else
             'Visible products included in sitemap',
             f"{stats.get('indexed_pct', 0)}%",
             'ok' if stats.get('indexed_pct', 0) >= 95 else 'warn'),
        ])
        pdf.impact('sitemap')

    # ======================= التشخيص =======================
    n += 1
    pdf.add_page()
    pdf.section(n, 'diagnosis')
    intro, points, close = build_diagnosis(score, stats, lang)
    pdf.para(intro, size=9.5, color=C_INK)
    pdf.ln(3)
    for pt in points:
        lines = pdf.wrap(pt, W - 10, 9)
        need = len(lines) * 5 + 3
        if pdf.get_y() + need > 262:
            pdf.add_page()
        y = pdf.get_y()
        pdf.set_fill_color(*C_INK)
        dot = (210 - M - 2.4) if rtl else M
        pdf.rect(dot, y + 1.6, 2.4, 2.4, 'F')
        pdf.set_font(FONT, "", 9)
        pdf.set_text_color(*C_MUTED)
        for i, line in enumerate(lines):
            pdf.set_xy(M if rtl else M + 6, y + i * 5)
            pdf.cell(W - 6, 5, fmt(line), align=ALIGN)
        pdf.set_y(y + len(lines) * 5 + 2.5)
    pdf.ln(3)

    lines = pdf.wrap(close, W - 14, 9.5)
    h = len(lines) * 5.2 + 8
    if pdf.get_y() + h > 265:
        pdf.add_page()
    y = pdf.get_y()
    pdf.set_fill_color(*C_BG)
    pdf.rect(M, y, W, h, 'F')
    pdf.set_fill_color(*verdict_rgb)
    if rtl:
        pdf.rect(210 - M - 2.2, y, 2.2, h, 'F')
    else:
        pdf.rect(M, y, 2.2, h, 'F')
    pdf.set_font(FONT, "", 9.5)
    pdf.set_text_color(*C_INK)
    yy = y + 4
    for line in lines:
        pdf.set_xy(M + 7, yy)
        pdf.cell(W - 14, 5.2, fmt(line), align=ALIGN)
        yy += 5.2

    return bytes(pdf.output())


# ==============================================================
#  حزمة الملفات
# ==============================================================
ZIP_NAMES = {
    'ar': {T_PRODUCT: "1_المنتجات.csv", T_CATEGORY: "2_التصنيفات.csv",
           T_BLOG: "3_المدونة.csv", T_INFO: "4_الصفحات_التعريفية.csv",
           T_HOME: "5_الصفحة_الرئيسية.csv", T_UNKNOWN: "6_غير_مصنفة.csv",
           T_BROKEN: "8_روابط_معطلة.csv", 'images': "8_تدقيق_الصور.csv",
           'notidx': "9_منتجات_غير_مدرجة_في_الخريطة.csv",
           'orphan': "10_صفحات_يتيمة_في_الخريطة.csv",
           'redirect': "11_روابط_الخريطة_المحوّلة.csv",
           'imggap': "12_صفحات_صورها_ناقصة.csv",
           'namegap': "13_اسم_معلن_مختلف.csv",
           'catgap': "14_مقارنة_عدادات_الأقسام.csv",
           'excel': "التقرير_الشامل.xlsx"},
    'en': {T_PRODUCT: "1_products.csv", T_CATEGORY: "2_categories.csv",
           T_BLOG: "3_blog.csv", T_INFO: "4_info_pages.csv",
           T_HOME: "5_homepage.csv", T_UNKNOWN: "6_unclassified.csv",
           T_BROKEN: "8_broken_links.csv", 'images': "8_image_alt_audit.csv",
           'notidx': "9_products_missing_from_sitemap.csv",
           'orphan': "10_orphan_sitemap_pages.csv",
           'redirect': "11_redirecting_sitemap_urls.csv",
           'imggap': "12_pages_with_missing_images.csv",
           'namegap': "13_declared_name_mismatch.csv",
           'catgap': "14_category_counter_comparison.csv",
           'excel': "full_audit_report.xlsx"},
}


def build_zip(df, images_df, coverage=None, lang='ar', structured=None):
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

        if structured:
            for key, data in [('imggap', structured.get('image_gap')),
                              ('namegap', structured.get('name_mismatch')),
                              ('catgap', structured.get('category_rows'))]:
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
            for k in ['audit_df', 'images_df', 'summary', 'coverage', 'selfcheck',
                      'dup_groups', 'structured']:
                st.session_state[k] = None
            st.session_state.current_url = ""
            st.rerun()

    if start_btn and input_url:
        target = normalize_url(input_url)
        st.session_state.current_url = target

        with st.status("جارٍ الفحص...", expanded=True) as status:
            head = st.empty()
            bar = st.progress(0)
            note = st.empty()

            def progress(stage, **kw):
                if stage == 'crawl_start':
                    head.write("**المرحلة 1** — تصفح المتجر من الصفحة الرئيسية")
                elif stage == 'crawl':
                    done, pend = kw.get('done', 0), kw.get('pending', 0)
                    bar.progress(min(done / max(done + pend, 1), 1.0))
                    note.caption(f"المستوى {kw.get('level')} · فُحصت {done} صفحة · "
                                 f"{pend} رابط في الانتظار")
                elif stage == 'pagination_start':
                    head.write("**المرحلة 2** — متابعة ترقيم صفحات الأقسام")
                    bar.progress(0)
                elif stage == 'pagination':
                    bar.progress(min(kw.get('i', 0) / max(kw.get('total', 1), 1), 1.0))
                    note.caption(f"{kw.get('i')}/{kw.get('total')} قسم · "
                                 f"{kw.get('found')} منتج إضافي · "
                                 f"{kw.get('fetched')} صفحة مجلوبة")
                elif stage == 'extra_start':
                    head.write(f"**المرحلة 3** — فحص {kw.get('count')} منتج "
                               "من الصفحات التالية")
                    bar.progress(0)
                elif stage == 'retry_start':
                    head.write(f"**إعادة محاولة** — {kw.get('count')} صفحة "
                               "تعذّر الاتصال بها")
                    bar.progress(0)
                elif stage == 'sitemap_start':
                    head.write("**المرحلة 4** — مقارنة تشخيصية مع خريطة الموقع")
                    bar.progress(0)
                elif stage == 'sitemap':
                    note.caption(f"{kw.get('count')} رابط في الخريطة · جارٍ التحقق "
                                 "من وجهة الروابط غير المطابقة")
                elif stage == 'done':
                    bar.progress(1.0)

            result = run_full_scan(target, max_pages, workers, do_pagination,
                                   do_sitemap_check, progress)
            status.update(label="اكتمل الفحص", state="complete", expanded=False)

        df = result['df']
        images_df = result['images_df']
        summary = result['summary']
        coverage = result['coverage']
        structured = result['structured']
        selfcheck = result['selfcheck']
        platform = result['platform']
        st.session_state.platform = platform
        st.session_state.brand = result['brand']
        st.session_state.dup_groups = result['dup_groups']

        st.session_state.audit_df = df
        st.session_state.images_df = images_df
        st.session_state.summary = summary
        st.session_state.coverage = coverage
        st.session_state.selfcheck = selfcheck
        st.session_state.structured = structured

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
        selfcheck = st.session_state.get('selfcheck')
        vmap = {'ready': ('v-ready', '✅ جاهز للإرسال',
                          'اجتازت النتائج كل فحوص الموثوقية. يمكنك إرسال التقرير.'),
                'review': ('v-review', '⚠️ يحتاج مراجعة قبل الإرسال',
                           'بعض المؤشرات تحتاج نظرة سريعة منك قبل إرسال التقرير لعميل.'),
                'blocked': ('v-blocked', '⛔ لا ترسل هذا التقرير',
                            'رصدت الأداة خللاً يجعل أرقامها غير موثوقة لهذا المتجر.')}
        if selfcheck:
            cls, head, sub = vmap[selfcheck['verdict']]
            extra = (f" · {selfcheck['fails']} فحص فاشل"
                     if selfcheck['fails'] else "")
            extra += (f" · {selfcheck['warns']} تنبيه" if selfcheck['warns'] else "")
            st.markdown(f'<div class="verdict {cls}"><b>{head}</b>{extra}<br>'
                        f'<span style="font-size:13.5px;font-weight:400">{sub} '
                        f'التفاصيل في تبويب «فحص الثقة».</span></div>',
                        unsafe_allow_html=True)

        tabs = st.tabs(["📊 نظرة عامة", "🛡️ فحص الثقة", "🧾 البيانات المعلنة",
                        "📄 الصفحات", "🖼️ الصور", "🗺️ خريطة الموقع",
                        "🔬 التحقق اليدوي", "📥 التصدير"])

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

            QL = QUALITY_LABEL['ar']
            qc = ok['جودة العنوان'].value_counts()
            items = [(QL[k], int(qc.get(k, 0))) for k in
                     ['q_ok', 'q_duplicate', 'q_brand_only', 'q_one_word',
                      'q_placeholder', 'q_symbols'] if qc.get(k, 0)]
            if items and len(items) > 1:
                st.markdown(bar_chart("الجودة البنيوية لعناوين الميتا", items, {
                    QL['q_ok']: COLOR['ok'], QL['q_duplicate']: COLOR['warn'],
                    QL['q_brand_only']: COLOR['bad'], QL['q_one_word']: COLOR['warn'],
                    QL['q_placeholder']: COLOR['bad'], QL['q_symbols']: COLOR['bad']}),
                    unsafe_allow_html=True)

            UL = URL_LABEL['ar']
            if 'جودة الرابط' in ok.columns:
                uc = ok['جودة الرابط'].value_counts()
                items = [(UL[k], int(uc.get(k, 0))) for k in
                         ['u_ok', 'u_underscore', 'u_uppercase', 'u_repeat', 'u_wordy',
                          'u_long', 'u_generic', 'u_wrongname', 'u_clone']
                         if uc.get(k, 0)]
                if len(items) > 1:
                    st.markdown(bar_chart("جودة روابط الصفحات", items, {
                        UL['u_ok']: COLOR['ok'], UL['u_underscore']: COLOR['warn'],
                        UL['u_uppercase']: COLOR['warn'], UL['u_repeat']: COLOR['warn'],
                        UL['u_wordy']: COLOR['warn'], UL['u_long']: COLOR['warn'],
                        UL['u_generic']: COLOR['bad'], UL['u_wrongname']: COLOR['bad'],
                        UL['u_clone']: COLOR['bad']}),
                        unsafe_allow_html=True)
            if summary.get('img_formats'):
                items = [(k.upper(), v) for k, v in
                         sorted(summary['img_formats'].items(), key=lambda x: -x[1])[:5]]
                st.markdown(bar_chart("صيغ صور المتجر", items, {
                    'WEBP': COLOR['ok'], 'AVIF': COLOR['ok'],
                    'JPG': COLOR['warn'], 'PNG': COLOR['warn']}),
                    unsafe_allow_html=True)

            st.markdown("#### أبرز النتائج")
            out = []
            if summary['missing_alts']:
                out.append((f"<b>{summary['missing_alts']}</b> صورة بلا نص بديل إطلاقاً "
                            f"من أصل {summary['total_images']} — أكبر فجوة قابلة "
                            "للإصلاح في المتجر.", 'bad'))
            if summary['weak_alts']:
                out.append((f"<b>{summary['weak_alts']}</b> صورة نصها البديل موجود لكنه "
                            "غير وصفي أو مكرر — يمر كسليم في الأدوات السطحية.", 'warn'))
            if summary.get('url_clone'):
                out.append((f"<b>{summary['url_clone']}</b> منتج مستنسخ — نسخ مكررة "
                            "من منتج واحد تتنافس مع أصلها.", 'bad'))
            if summary.get('dup_content'):
                out.append((f"<b>{summary['dup_content']}</b> صفحة بنفس العنوان والوصف "
                            "حرفياً — محتوى مكرر يختار جوجل منه واحدة فقط.", 'bad'))
            if summary.get('url_wrongname'):
                out.append((f"<b>{summary['url_wrongname']}</b> رابط يحمل اسم منتج مختلف "
                            "عن المعروض في الصفحة — الزبون ينقر على منتج ويصل لآخر.",
                            'bad'))
            if summary.get('url_style'):
                out.append((f"<b>{summary['url_style']}</b> رابط بصياغة غير مثالية — "
                            "شرطة سفلية أو حروف كبيرة أو طول مفرط.", 'warn'))
            if summary.get('img_legacy') and summary.get('img_modern_pct', 100) < 50:
                out.append((f"<b>{summary['img_legacy']}</b> صورة بصيغة قديمة ثقيلة — "
                            f"{summary.get('img_modern_pct', 0)}% فقط بصيغ حديثة. "
                            "التحويل يخفض حجم الصفحة بنحو الثلث.", 'warn'))
            if summary.get('title_symbols'):
                out.append((f"<b>{summary['title_symbols']}</b> عنوان ميتا مجرد رموز أو "
                            "قيمة قالب افتراضية — الصفحة بلا عنوان فعلي في نتائج البحث.",
                            'bad'))
            if summary.get('title_brand_only'):
                out.append((f"<b>{summary['title_brand_only']}</b> عنوان لا يحمل سوى اسم "
                            "المتجر بلا وصف للمنتج.", 'bad'))
            if summary.get('title_dup'):
                out.append((f"<b>{summary['title_dup']}</b> صفحة تتشارك نفس عنوان "
                            "الميتا.", 'warn'))
            if summary.get('desc_same'):
                out.append((f"<b>{summary['desc_same']}</b> وصف ميتا نسخة حرفية من "
                            "العنوان.", 'warn'))
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

        # ---------------- فحص الثقة ----------------
        with tabs[1]:
            st.markdown("#### فحوص موثوقية النتائج")
            st.caption("هذه الفحوص لا تقيس جودة سيو المتجر، بل تقيس مدى ثقة الأداة "
                       "في أرقامها هي. أي فحص فاشل يعني أن الزاحف لم يرَ المتجر كما "
                       "يراه الزائر.")
            if not selfcheck:
                st.info("لا توجد نتائج فحص ذاتي لهذه الجلسة.")
            else:
                dots = {CHECK_PASS: COLOR['ok'], CHECK_WARN: COLOR['warn'],
                        CHECK_FAIL: COLOR['bad']}
                order = {CHECK_FAIL: 0, CHECK_WARN: 1, CHECK_PASS: 2}
                for c in sorted(selfcheck['checks'], key=lambda x: order[x['level']]):
                    act = (f'<div class="a">الإجراء المقترح: {c["action"]}</div>'
                           if c['action'] else '')
                    st.markdown(
                        f'<div class="chk"><div class="dot" '
                        f'style="background:{dots[c["level"]]}"></div>'
                        f'<div><div class="t">{c["title"]}</div>'
                        f'<div class="m">{c["msg"]}</div>{act}</div></div>',
                        unsafe_allow_html=True)

        # ---------------- البيانات المعلنة ----------------
        with tabs[2]:
            stx = st.session_state.get('structured')
            st.markdown("#### ما يعلنه المتجر مقابل ما رصده الفحص")
            st.caption("تُقارَن كل صفحة قسم بعدّاد المنتجات الظاهر فيها. العدّاد يعدّ "
                       "المعروض للزائر فقط — لا المخفي ولا المحذوف — فأي نقص يعني "
                       "منتجات معروضة لم يصل إليها الفحص.")
            if not stx:
                st.info("لا توجد بيانات معلنة في هذا الفحص.")
            else:
                checked = stx.get('categories_checked', 0)
                short = stx.get('categories_short') or []
                miss = stx.get('missing_products', 0)
                c1, c2, c3 = st.columns(3)
                c1.metric("أقسام قورنت بعدّادها", checked if checked else "—")
                c2.metric("أقسام ينقصها منتجات", len(short))
                c3.metric("منتجات معروضة لم تُرصد", miss)
                st.write("")

                if not checked:
                    st.markdown(finding(
                        "لم يعرض المتجر عدّاد منتجات في أقسامه، فتعذّرت مقارنة "
                        "التغطية. تبقى مقارنة الصور والأسماء أدناه صالحة.", 'warn'),
                        unsafe_allow_html=True)
                elif short:
                    st.markdown(finding(
                        f"<b>{len(short)}</b> قسماً يعلن منتجات أكثر مما رصده الفحص "
                        f"(ناقص <b>{miss}</b> منتجاً). الأرجح أن القسم يحمّل بقية "
                        "منتجاته بالتمرير أو بزر «عرض المزيد». لا تعتمد أرقام "
                        "المنتجات في هذا التقرير.", 'bad'), unsafe_allow_html=True)
                else:
                    st.markdown(finding(
                        f"جميع الأقسام الـ{checked} مطابقة تماماً لعدّاداتها — "
                        "لم يفت الفحص أي منتج معروض.", 'ok'), unsafe_allow_html=True)

                rows = stx.get('category_rows') or []
                if rows:
                    view = pd.DataFrame(rows)
                    st.dataframe(view, use_container_width=True,
                                 column_config={"القسم": st.column_config.LinkColumn(
                                     "القسم", width="large")})

                gaps = stx.get('image_gap') or []
                if gaps:
                    st.markdown(finding(
                        f"<b>{len(gaps)}</b> صفحة منتج تعلن صوراً أكثر مما رصده الفحص — "
                        "معرض الصور يُحمَّل بـ JavaScript جزئياً.", 'bad'),
                        unsafe_allow_html=True)
                    st.dataframe(pd.DataFrame(gaps), use_container_width=True)

                nm = stx.get('name_mismatch') or []
                if nm:
                    st.markdown(finding(
                        f"<b>{len(nm)}</b> منتجاً اسمه المعلن لمحركات البحث يختلف عن "
                        "الاسم المعروض في الصفحة.", 'warn'), unsafe_allow_html=True)
                    st.dataframe(pd.DataFrame(nm), use_container_width=True)

                st.caption(f"صفحات منتجات تحمل بيانات مهيكلة: "
                           f"{stx.get('jsonld_pages', 0)} · بدونها: "
                           f"{stx.get('no_jsonld', 0)} · إجمالي منتجات الفحص: "
                           f"{stx.get('found_products', 0)}")

        # ---------------- الصفحات ----------------
        with tabs[3]:
            present = [PAGE_TYPE_LABEL['ar'][t] for t in PAGE_TYPE_ORDER
                       if (df['نوع الصفحة'] == t).any()]
            f1, f2 = st.columns([2, 3])
            with f1:
                sel = st.selectbox("نوع الصفحة", ["الكل"] + present)
            with f2:
                only_issues = st.checkbox("عرض الصفحات التي بها مشاكل فقط", value=False)

            d = view_df if sel == "الكل" else view_df[view_df['نوع الصفحة'] == sel]
            if only_issues:
                QL = QUALITY_LABEL['ar']
                d = d[(d['حالة العنوان'] != STATUS_LABEL['ar']['optimal']) |
                      (d['حالة الوصف'] != STATUS_LABEL['ar']['optimal']) |
                      (~d['جودة العنوان'].isin([QL['q_ok'], QL['q_na']])) |
                      (~d['جودة الوصف'].isin([QL['q_ok'], QL['q_na']])) |
                      (~d['جودة الرابط'].isin([URL_LABEL['ar']['u_ok'],
                                               URL_LABEL['ar']['u_na']])) |
                      (d['صور بدون Alt'] > 0) | (d['متاحة'] == False)]  # noqa: E712
            d = d.copy().reset_index(drop=True)
            d.index = d.index + 1
            st.dataframe(d, use_container_width=True, height=460,
                         column_config={"الرابط": st.column_config.LinkColumn(
                             "الرابط", width="large"),
                             "درجة السيو": st.column_config.ProgressColumn(
                                 "درجة السيو", min_value=0, max_value=100, format="%d")})
            dgroups = st.session_state.get('dup_groups') or []
            if dgroups:
                with st.expander(f"⚠️ {len(dgroups)} مجموعة محتوى مكرر "
                                 f"({sum(g['عدد الصفحات'] for g in dgroups)} صفحة)"):
                    for g in dgroups:
                        st.markdown(f"**{g['عدد الصفحات']} صفحات** بنفس العنوان: "
                                    f"{str(g['العنوان'])[:70]}")
                        for u in g['الروابط']:
                            st.caption(f"• {u}")
            langs = df[df['متاحة'] == True]['لغة الصفحة'].value_counts()  # noqa: E712
            st.caption(
                f"معايير الطول — العنوان مثالي {TITLE_MIN_OPTIMAL}-{TITLE_MAX} حرفاً "
                f"(مقبول من {TITLE_MIN_OK})، الوصف مثالي {DESC_MIN_OPTIMAL}-{DESC_MAX} "
                f"حرفاً (مقبول من {DESC_MIN_OK}). يُحسب الطول بالحروف شاملاً المسافات "
                "وعلامات الترقيم. · لغات الصفحات: " +
                "، ".join(f"{k}: {v}" for k, v in langs.items()))

        # ---------------- الصور ----------------
        with tabs[4]:
            if view_imgs is not None and not view_imgs.empty:
                L = STATUS_LABEL['ar']
                fc1, fc2 = st.columns(2)
                with fc1:
                    f = st.selectbox("تصفية", ["الكل", "بلا نص بديل", "نص بديل ضعيف",
                                               "نص بديل سليم"])
                with fc2:
                    fmts = ["الكل"] + sorted(view_imgs['صيغة الصورة'].dropna().unique().tolist()) \
                        if 'صيغة الصورة' in view_imgs.columns else ["الكل"]
                    fsel = st.selectbox("صيغة الصورة", fmts)
                v = view_imgs
                if f == "بلا نص بديل":
                    v = view_imgs[view_imgs['حالة النص البديل'] == L['alt_missing']]
                elif f == "نص بديل ضعيف":
                    v = view_imgs[view_imgs['حالة النص البديل'].isin(
                        [L[k] for k in ALT_WEAK_STATES])]
                elif f == "نص بديل سليم":
                    v = view_imgs[view_imgs['حالة النص البديل'] == L['alt_ok']]
                if fsel != "الكل" and 'صيغة الصورة' in v.columns:
                    v = v[v['صيغة الصورة'] == fsel]
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
        with tabs[5]:
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
        with tabs[6]:
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
                        QL = QUALITY_LABEL['ar']
                        tq = QL.get(r.get('جودة العنوان', 'q_na'), '—')
                        dq = QL.get(r.get('جودة الوصف', 'q_na'), '—')
                        st.write(f"**العنوان** ({tq}): {r['عنوان الميتا'] or '— مفقود —'}")
                        st.write(f"**الوصف** ({dq}): {r['وصف الميتا'] or '— مفقود —'}")
                        st.caption(f"صور: {r['إجمالي الصور']} · بلا Alt: "
                                   f"{r['صور بدون Alt']} · Alt ضعيف: {r['صور Alt ضعيف']} · "
                                   f"كلمات: {r['عدد الكلمات']} · لغة: {r['لغة الصفحة']} · "
                                   f"كانونيكال: {L[r['حالة الكانونيكال']]}")

        # ---------------- التصدير ----------------
        with tabs[7]:
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
            zip_bytes = build_zip(df, images_df, coverage, lang,
                                  st.session_state.get('structured'))

            gate_ok = True
            if selfcheck and selfcheck['verdict'] == 'blocked':
                st.markdown(
                    '<div class="verdict v-blocked"><b>⛔ تقرير العميل محجوب</b><br>'
                    '<span style="font-size:13.5px;font-weight:400">رصدت الأداة خللاً '
                    'يجعل أرقامها غير موثوقة لهذا المتجر. راجع تبويب «فحص الثقة» أولاً.'
                    '</span></div>', unsafe_allow_html=True)
                gate_ok = st.checkbox(
                    "راجعت الفحوص الفاشلة وأتحمل مسؤولية إرسال هذا التقرير",
                    value=False)
            elif selfcheck and selfcheck['verdict'] == 'review':
                st.warning("توجد تنبيهات على موثوقية النتائج. راجع تبويب «فحص الثقة» "
                           "قبل إرسال التقرير لعميل.")

            d1, d2 = st.columns(2)
            with d1:
                if pdf_bytes and gate_ok:
                    st.download_button(
                        "📄 تقرير العميل (PDF)" if lang == 'ar' else "📄 Client report (PDF)",
                        pdf_bytes, f"SEO_Audit_{netloc}_{lang}.pdf", "application/pdf",
                        use_container_width=True)
                elif pdf_bytes:
                    st.button("📄 تقرير العميل (PDF)", disabled=True,
                              use_container_width=True,
                              help="مُعطّل حتى تقرّ بمراجعة الفحوص الفاشلة.")
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
