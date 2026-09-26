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
from functools import lru_cache
import sqlite3
import threading
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse, urljoin, unquote
from concurrent.futures import ThreadPoolExecutor

# المتصفح الخفي (اختياري): يُستخدم فقط للأقسام التي تعتمد على التمرير اللانهائي
try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except Exception:
    HAS_PLAYWRIGHT = False

# ==============================================================
#  مركز عمليات السيو الشامل للمتاجر الإلكترونية
#  أنس راشد — anasrashed.com
# ==============================================================

BASE_DIR = Path(__file__).resolve().parent

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
        if rp.exists() and rp.stat().st_size > 20000:
            bp = BASE_DIR / bold
            return name, rp, (bp if bp.exists() and bp.stat().st_size > 20000 else None)
    return "Amiri", BASE_DIR / "Amiri-Regular.ttf", None


AR_FONT_NAME, FONT_PATH, FONT_BOLD_PATH = pick_font()

try:
    import uharfbuzz  # noqa: F401
    HAS_SHAPING = True
except Exception:
    HAS_SHAPING = False

LOGO_PATH = BASE_DIR / "brand_logo.png"
RIYAL_PATH = BASE_DIR / "Saudi_Riyal_Symbol-1.png"
DB_FILE = str(BASE_DIR / "store_history.db")

try:
    import lxml  # noqa: F401
    PARSER = "lxml"
except Exception:
    PARSER = "html.parser"

MAX_PAGES_DEFAULT = 1500
MAX_PAGINATION_DEPTH = 50
MAX_CRAWL_LEVELS = 8
MAX_REDIRECT_CHECKS = 300
MAX_BROWSER_ROOTS = 6          # أقصى عدد أقسام تُفتح بالمتصفح الخفي في الفحص الواحد

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'ar,en-US;q=0.9,en;q=0.8',
    'Sec-Ch-Ua': '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    'Sec-Ch-Ua-Mobile': '?0',
    'Sec-Ch-Ua-Platform': '"Windows"',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'same-origin',
    'Sec-Fetch-User': '?1',
    'Upgrade-Insecure-Requests': '1',
}
XHR_HEADERS = {'X-Requested-With': 'XMLHttpRequest',
               'Accept': 'application/json, text/html, */*'}

T_HOME, T_PRODUCT, T_CATEGORY = 'home', 'product', 'category'
T_BLOG, T_INFO, T_UNKNOWN, T_BROKEN = 'blog', 'info', 'unknown', 'broken'
T_ARCHIVE = 'archive'
PAGE_TYPE_ORDER = [T_HOME, T_PRODUCT, T_CATEGORY, T_BLOG, T_INFO, T_ARCHIVE,
                   T_UNKNOWN, T_BROKEN]
CONTENT_TYPES = (T_PRODUCT, T_CATEGORY, T_BLOG, T_INFO)
LISTING_TYPES = (T_HOME, T_CATEGORY, T_BLOG, T_ARCHIVE, T_UNKNOWN)

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
        'match_ok': 'مطابق', 'match_diff': 'مختلف عن عنوان الصفحة', 'match_na': '—',
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
        'match_ok': 'Matches', 'match_diff': 'Differs from page heading',
        'match_na': '—',
    },
}

TITLE_MAX, TITLE_MIN_OPTIMAL, TITLE_MIN_OK = 60, 50, 30
DESC_MAX, DESC_MIN_OPTIMAL, DESC_MIN_OK = 150, 120, 70
ALT_MAX = 125
ALT_DUP_THRESHOLD = 3

COL_EN = {
    'نوع الصفحة': 'Page Type', 'الرابط': 'URL', 'الرابط الكانوني': 'Canonical URL',
    'مصدر الاكتشاف': 'Discovered Via', 'متاحة': 'Reachable', 'كود الاستجابة': 'Status Code',
    'درجة السيو': 'SEO Score', 'عنوان الميتا': 'Meta Title', 'طول العنوان': 'Title Length',
    'حالة العنوان': 'Title Status', 'وصف الميتا': 'Meta Description',
    'طول الوصف': 'Description Length', 'حالة الوصف': 'Description Status',
    'إجمالي الصور': 'Total Images', 'صور بدون Alt': 'Images Missing Alt',
    'صور Alt ضعيف': 'Images With Weak Alt', 'عدد الكلمات': 'Word Count',
    'حالة المحتوى': 'Content Status', 'لغة الصفحة': 'Page Language',
    'حالة الكانونيكال': 'Canonical Status', 'قابلة للأرشفة': 'Indexable',
    'مطابقة العنوان مع H1': 'Title vs H1', 'عنوان الصفحة (H1)': 'Page H1', 'رابط الصفحة': 'Page URL',
    'رابط الصورة': 'Image URL', 'النص البديل الحالي (Alt)': 'Current Alt Text',
    'طول النص البديل': 'Alt Length', 'حالة النص البديل': 'Alt Status',
    'عدد الصفحات': 'Appears On Pages',
    'الوجهة النهائية': 'Final Destination', 'سلسلة التحويل': 'Redirect Chain',
    'الرابط الأصلي': 'Original URL', 'الحالة': 'Status', 'نوع الرابط': 'URL Type',
    'الإجراء المقترح': 'Suggested Action',
    'يظهر في': 'Found On', 'الوجهة المقترحة': 'Suggested Destination',
    'ثقة الاقتراح': 'Suggestion Confidence',
    'اسم إعادة التوجيه': 'Redirect Name', 'التوجيه من': 'Redirect From',
    'التوجيه إلى': 'Redirect To',
    'جودة العنوان': 'Title Quality', 'جودة الوصف': 'Description Quality',
    'جودة الرابط': 'URL Quality', 'المسار': 'Slug', 'محتوى مكرر': 'Duplicate Content',
    'اسم المنتج المعروض': 'Displayed Product Name', 'صيغة الصورة': 'Image Format',
    'اسم منظم': 'Declared Name', 'صور معلنة': 'Declared Images',
    'رقم المنتج': 'SKU', 'عدد معلن': 'Declared Count',
    'الاسم المعلن': 'Declared Name', 'الاسم المعروض': 'Displayed Name',
    'صور مرصودة': 'Images Detected', 'القسم': 'Category',
    'في الخريطة': 'In Sitemap', 'مرتبط برابط': 'Internally Linked',
    'الأولوية': 'Priority', 'ما يحتاج إصلاحاً': 'What Needs Fixing',
    'عنوان الميتا الحالي': 'Current Meta Title',
    'وصف الميتا الحالي': 'Current Meta Description', 'م': '#',
    'مرصود': 'Detected', 'ناقص': 'Missing',
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


# ==============================================================
#  جلسة اتصال مجمّعة
# ==============================================================
_TL = threading.local()


def _session():
    sess = getattr(_TL, 'sess', None)
    if sess is None:
        sess = requests.Session()
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=16, pool_maxsize=32, max_retries=1)
        sess.mount('https://', adapter)
        sess.mount('http://', adapter)
        sess.headers.update(HEADERS)
        _TL.sess = sess
    return sess


_THROTTLE = {'fails': 0, 'delay': 0.0, 'streak': 0}
_THROTTLE_LOCK = threading.Lock()
MAX_DELAY = 2.0          # أقصى تمهّل بين الطلبات (ثانية)
DELAY_STEP_UP = 0.3      # كم نتمهّل عند كل رفض
DELAY_STEP_DOWN = 0.2    # كم نسرع بعد سلسلة نجاح
SUCCESS_STREAK = 12      # عدد النجاحات المتتالية قبل أن نسرع خطوة


def note_failure():
    """المتجر رفض أو تعثّر: نتمهّل خطوة."""
    with _THROTTLE_LOCK:
        _THROTTLE['fails'] += 1
        _THROTTLE['streak'] = 0
        _THROTTLE['delay'] = min(_THROTTLE['delay'] + DELAY_STEP_UP, MAX_DELAY)


def note_success():
    """سلسلة نجاح: نرجع نسرع تدريجياً بدل البقاء بطيئين لنهاية الفحص."""
    if _THROTTLE['delay'] <= 0:
        return
    with _THROTTLE_LOCK:
        _THROTTLE['streak'] += 1
        if _THROTTLE['streak'] >= SUCCESS_STREAK:
            _THROTTLE['delay'] = max(0.0, _THROTTLE['delay'] - DELAY_STEP_DOWN)
            _THROTTLE['streak'] = 0


def reset_throttle():
    _THROTTLE['fails'] = 0
    _THROTTLE['delay'] = 0.0
    _THROTTLE['streak'] = 0


def is_challenge(res):
    """صفحة تحقق من الحماية (Cloudflare) بدل المحتوى المطلوب."""
    if res is None:
        return False
    if str(res.headers.get('cf-mitigated', '')).lower() == 'challenge':
        return True
    if res.status_code in (403, 503):
        head = (res.text or '')[:3000].lower()
        return ('just a moment' in head or 'cf-chl' in head
                or 'challenge-platform' in head or 'attention required' in head)
    return False


def safe_get(url, timeout=14, retries=2, headers=None):
    """يعيد الاستجابة كما هي (حتى 404 و429 و5xx) حتى يُسجَّل سبب الفشل الحقيقي،
    و None فقط عند انقطاع الاتصال فعلاً."""
    if _THROTTLE['delay'] > 0:
        time.sleep(_THROTTLE['delay'])
    h = dict(HEADERS)
    if headers:
        h.update(headers)
    last = None
    for attempt in range(retries + 1):
        try:
            res = _session().get(url, timeout=timeout, allow_redirects=True, headers=h)
        except Exception:
            note_failure()
            if attempt < retries:
                time.sleep(1 + attempt)
            continue
        if res.status_code == 429 or res.status_code >= 500 or is_challenge(res):
            note_failure()
            last = res
            if attempt < retries:
                ra = str(res.headers.get('Retry-After', '')).strip()
                wait = float(ra) if ra.isdigit() else 2.0 * (attempt + 1)
                time.sleep(min(wait, 10))
            continue
        note_success()
        return res
    return last


def is_ok(res):
    return res is not None and res.status_code == 200


# ==============================================================
#  أدوات النصوص والروابط والفلترة وحظر التاقات
# ==============================================================
AR_PREFIXES = ('وال', 'بال', 'فال', 'كال', 'لل', 'ال', 'و')


def normalize_ar_token(tok):
    t = tok.strip('.,،؛:!?()[]')
    t = re.sub(r'[\u064B-\u0652\u0670]', '', t)
    t = t.replace('أ', 'ا').replace('إ', 'ا').replace('آ', 'ا')
    t = t.replace('ى', 'ي').replace('ة', 'ه')
    for pre in AR_PREFIXES:
        if t.startswith(pre) and len(t) > len(pre) + 1:
            t = t[len(pre):]
            break
    return t


def slug_tokens(text):
    raw = re.split(r'[\s\-_/|،,.:؛…]+', str(text or '').lower())
    out = []
    for t in raw:
        t = re.sub(r'[^0-9a-z\u0600-\u06FF]', '', t)
        if len(t) < 2:
            continue
        out.append(normalize_ar_token(t) if re.search(r'[\u0600-\u06FF]', t) else t)
    return out


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


def norm_host(netloc):
    h = (netloc or '').lower().split(':')[0]
    return h[4:] if h.startswith('www.') else h


# بادئات اللغة: /ar و /en وغيرها — الصفحة نفسها بلغة أخرى لا تُحسب صفحة جديدة
LANG_CODES = {'ar', 'en', 'fr', 'ur', 'tr', 'es', 'de', 'it', 'id', 'fa', 'hi', 'bn', 'ru', 'zh'}

PLATFORM_ID_RE = re.compile(r'^(p|c|a|page|tag|category|product)-?(\d{4,})$', re.I)


def url_segments(url):
    """مقاطع المسار بعد فك الترميز وحذف بادئة اللغة."""
    path = unquote(urlparse(clean_url(url)).path).strip('/')
    segs = [s for s in path.split('/') if s]
    if segs and segs[0].lower() in LANG_CODES:
        segs = segs[1:]
    return segs


def has_lang_prefix(url):
    path = unquote(urlparse(clean_url(url)).path).strip('/')
    first = path.split('/')[0].lower() if path else ''
    return first in LANG_CODES


@lru_cache(maxsize=200000)
def url_key(url):
    """مفتاح موحّد للصفحة: يتجاهل www وبادئة اللغة، ويعتمد رقم المنتج/التصنيف
    الثابت في سلة، فلا يتكرر المنتج إذا تغيّر اسمه أو ظهر بلغتين."""
    if not url:
        return ""
    p = urlparse(clean_url(url))
    host = norm_host(p.netloc)
    segs = url_segments(url)
    if segs:
        mo = PLATFORM_ID_RE.match(segs[-1])
        if mo:
            return f"{host}/#{mo.group(1).lower()}{mo.group(2)}"
    return f"{host}/{'/'.join(segs)}".rstrip('/').lower()


def prefer_url(a, b):
    """بين رابطين لنفس الصفحة: نفضّل النسخة بلا بادئة لغة ثم الأقصر."""
    ka = (1 if has_lang_prefix(a) else 0, len(a))
    kb = (1 if has_lang_prefix(b) else 0, len(b))
    return a if ka <= kb else b


def make_soup(markup):
    return BeautifulSoup(markup, PARSER)


TAG_IDENTIFIERS = {'tag', 'tags', 'وسم', 'وسوم', 'wsm', 'tag-products', 'product-tag', 'product-tags'}

EXCLUDE_EXACT_SEGMENTS = {
    'cart', 'checkout', 'login', 'signin', 'register', 'signup', 'account',
    'my-account', 'wishlist', 'favorites', 'compare', 'search', 'orders',
    'customer', 'password', 'thank-you', 'logout',
    'سلة', 'حسابي', 'تسجيل', 'الدفع', 'المفضلة', 'طلب-جديد',
    'wp-admin', 'wp-json', '__'
} | TAG_IDENTIFIERS

BAD_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.gif', '.svg', '.webp', '.avif', '.pdf',
                  '.zip', '.rar', '.xml', '.css', '.js', '.ico', '.mp4', '.webm',
                  '.mp3', '.doc', '.docx', '.xls', '.xlsx', '.json')


def is_tag_url(url):
    if not url:
        return False
    u = unquote(url.lower())
    p = urlparse(u)
    path = p.path.strip('/')
    segs = [s for s in path.split('/') if s]

    for s in segs:
        if s in TAG_IDENTIFIERS:
            return True
        if any(s.startswith(f"{k}-") or s.startswith(f"{k}_") for k in ('tag', 'tags', 'وسم', 'وسوم')):
            return True

    if p.query:
        q_lower = p.query.lower()
        if any(k in q_lower for k in ('tag=', 'tags=', 'tag_id=', 'tags_id=', 'وسم=', 'وسوم=')):
            return True
    return False


def is_crawlable(url, base_netloc):
    if not url:
        return False
    p = urlparse(url)
    if p.scheme not in ('http', 'https'):
        return False
    if norm_host(p.netloc) != norm_host(base_netloc):
        return False
    if is_tag_url(url):
        return False
    path = unquote(p.path.lower())
    if path.endswith(BAD_EXTENSIONS):
        return False
    segments = set(path.strip('/').split('/'))
    if segments & EXCLUDE_EXACT_SEGMENTS:
        return False
    if '/cdn-cgi/' in path or '/email-protection' in path:
        return False
    return True


def image_format(url):
    path = urlparse(str(url or '')).path.lower()
    mo = re.search(r'\.(jpe?g|png|webp|avif|gif|svg|bmp|tiff?)(?:$|\?)', path)
    if mo:
        ext = mo.group(1)
        return 'jpg' if ext in ('jpg', 'jpeg') else ext
    mo2 = re.search(r'(?:format|fm)=(\w+)', str(url or '').lower())
    return mo2.group(1) if mo2 else '—'


# ==============================================================
#  القياس والتقييم
# ==============================================================
def text_length(text):
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
    if images_df is None or images_df.empty:
        return images_df
    counts = images_df.groupby('رابط الصورة')['رابط الصفحة'].nunique()
    out = images_df.drop_duplicates(subset=['رابط الصورة']).copy()
    out['عدد الصفحات'] = out['رابط الصورة'].map(counts)
    return out.reset_index(drop=True)


# ==============================================================
#  كشف المنصة
# ==============================================================
PLATFORM_LABEL = {'salla': 'سلة (Salla)', 'zid': 'زد (Zid)',
                  'shopify': 'شوبيفاي (Shopify)', 'rmz': 'رمز (rmz.gg)',
                  'woocommerce': 'ووكومرس', 'unknown': 'غير معروفة'}
PLATFORM_LABEL_EN = {'salla': 'Salla', 'zid': 'Zid', 'shopify': 'Shopify',
                     'rmz': 'rmz.gg', 'woocommerce': 'WooCommerce',
                     'unknown': 'Unidentified'}
SUPPORTED_PLATFORMS = ('salla', 'zid', 'shopify')


def detect_platform(html, headers=None, url=""):
    h = (html or "")[:250000].lower()
    hdr = " ".join(f"{k}:{v}" for k, v in (headers or {}).items()).lower()
    blob = h + " " + hdr + " " + (url or "").lower()
    if any(s in blob for s in ['salla.sa', 'cdn.salla.network', 'window.salla', 'salla-', 'assets.salla.cloud', 'twilight']):
        return 'salla'
    if any(s in blob for s in ['zid.store', 'media.zid.sa', 'zidapi', 'x-zid', 'cdn.zid', 'zid-theme']):
        return 'zid'
    if any(s in blob for s in ['cdn.shopify.com', 'myshopify.com', 'shopify.theme',
                               'x-shopify', 'shopify-features', 'window.shopify']):
        return 'shopify'
    if any(s in blob for s in ['cdn.rmz.gg', 'rmz.gg/store', 'matjrah']):
        return 'rmz'
    if any(s in blob for s in ['woocommerce', 'wp-content/plugins/woo']):
        return 'woocommerce'
    return 'unknown'


# ==============================================================
#  تصنيف الصفحات
#  الترتيب: أنماط الرابط القاطعة ← إشارات الصفحة ← الكلمات المفتاحية
# ==============================================================
POLICY_KEYWORDS = [
    'سياسة', 'شروط', 'خصوصية', 'استبدال', 'استرجاع', 'شحن', 'توصيل', 'شكاوى',
    'اسئلة', 'أسئلة', 'من-نحن', 'اتصل', 'ضمان', 'دفع', 'مقترحات', 'أحكام',
    'الاستخدام', 'ارجاع', 'إرجاع', 'مرتجعات', 'تبديل', 'ضمانات',
    'pages', 'page', 'policies', 'policy', 'privacy', 'terms', 'conditions',
    'about', 'about-us', 'contact', 'contact-us', 'faq', 'faqs', 'help',
    'shipping', 'delivery', 'complaint', 'complaints', 'returns', 'return',
    'refund', 'refunds', 'warranty', 'support', 'legal',
]
CATALOG_ROOTS = {'products', 'product', 'all-products', 'latest-products', 'catalog',
                 'catalogue', 'collections/all', 'collections', 'shop', 'store',
                 'categories', 'offers', 'brands', 'كل-المنتجات', 'جميع-المنتجات'}
BLOG_SEGMENTS = ('blog', 'blogs', 'articles', 'article', 'post', 'posts', 'news',
                 'مدونة', 'مقالات', 'اخبار', 'أخبار')
CATEGORY_SEGMENTS = ('category', 'categories', 'collection', 'collections',
                     'department', 'departments', 'قسم', 'اقسام', 'أقسام', 'تصنيف',
                     'brands', 'brand', 'ماركة', 'ماركات')
INFO_ROOT_SEGMENTS = ('pages', 'policies', 'page')
ARCHIVE_PARENT_SEGMENTS = ('tag', 'tags', 'author', 'authors', 'archive', 'وسم', 'وسوم')

# سلة: /اسم-المنتج/p123 ، /اسم-التصنيف/c123 ، /اسم-الصفحة/page-123
PRODUCT_ID_RE = re.compile(r'^p-?\d{3,}$', re.I)
CATEGORY_ID_RE = re.compile(r'^c-?\d{3,}$', re.I)
INFO_ID_RE = re.compile(r'^page-?\d+$', re.I)
ARCHIVE_LAST_RE = re.compile(r'^(tag|author|category|archive)-?\d*$', re.I)

_POLICY_NORM = None


def _policy_norm():
    global _POLICY_NORM
    if _POLICY_NORM is None:
        _POLICY_NORM = set()
        for k in POLICY_KEYWORDS:
            for part in k.split('-'):
                _POLICY_NORM.add(normalize_ar_token(part.lower()))
    return _POLICY_NORM


def _seg_tokens(seg):
    return [normalize_ar_token(p.lower()) for p in re.split(r'[-_]+', seg) if p]


def segment_is_policy(seg):
    """كلمة كاملة من كلمات السياسات (وليس جزءاً من كلمة): «شحنة» لا تطابق «شحن»."""
    norm = _policy_norm()
    return any(t in norm for t in _seg_tokens(seg) if len(t) > 2)


def segment_is_mostly_policy(seg):
    """نصف كلمات الرابط على الأقل من كلمات السياسات — يُستخدم داخل المدونة فقط
    حتى لا يتحول مقال مثل «افضل-شركات-الشحن» إلى صفحة سياسة."""
    norm = _policy_norm()
    toks = [t for t in _seg_tokens(seg) if len(t) > 2]
    if not toks:
        return False
    return sum(1 for t in toks if t in norm) / len(toks) > 0.5


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
            if '@graph' in b and isinstance(b['@graph'], list):
                for sub in b['@graph']:
                    if isinstance(sub, dict):
                        st = sub.get('@type')
                        stypes = st if isinstance(st, list) else [st]
                        if any(str(x) in wanted for x in stypes if x):
                            return True
    return False


def _html_signal(soup):
    """ما تعلنه الصفحة عن نفسها: product / article / collection / None"""
    if soup is None:
        return None
    og_type = ""
    tag = soup.find('meta', attrs={'property': 'og:type'})
    if tag and tag.get('content'):
        og_type = tag['content'].lower()
    if ('product' in og_type
            or soup.find(attrs={'itemtype': re.compile(r'schema\.org/Product', re.I)})
            or _has_jsonld_type(soup, ('Product', 'IndividualProduct'))):
        return 'product'
    if ('article' in og_type or 'blog' in og_type
            or soup.find(attrs={'itemtype': re.compile(r'schema\.org/(Article|BlogPosting|NewsArticle)', re.I)})
            or _has_jsonld_type(soup, ('Article', 'BlogPosting', 'NewsArticle'))):
        return 'article'
    if (soup.find(attrs={'itemtype': re.compile(r'schema\.org/CollectionPage', re.I)})
            or _has_jsonld_type(soup, ('CollectionPage',))):
        return 'collection'
    return None


@lru_cache(maxsize=100000)
def _detect_type_by_url(url, base_url):
    return detect_page_type(url, base_url, None)


def detect_page_type(url, base_url, soup=None):
    url_clean = clean_url(url)
    if is_tag_url(url_clean):
        return T_ARCHIVE

    segs = [s.lower() for s in url_segments(url_clean)]

    # 1) الرئيسية، بما فيها /ar و /en
    if not segs or url_key(url_clean) == url_key(normalize_url(base_url)):
        return T_HOME

    last = segs[-1]
    path_clean = '/'.join(segs)
    in_blog = any(s in BLOG_SEGMENTS for s in segs)

    # 2) أنماط قاطعة من الرابط (سلة، زد، شوبيفاي)
    if PRODUCT_ID_RE.match(last):
        return T_PRODUCT
    if not in_blog and ('products' in segs[:-1] or 'product' in segs[:-1]):
        return T_PRODUCT                       # زد وشوبيفاي: /products/اسم-المنتج
    if INFO_ID_RE.match(last):
        return T_INFO                          # سلة: /اسم-الصفحة/page-123
    if segs[0] in INFO_ROOT_SEGMENTS and len(segs) >= 2:
        return T_INFO                          # زد وشوبيفاي: /pages/... و /policies/...

    # 3) المدونة تُحسم قبل كلمات السياسات
    if in_blog:
        if last in BLOG_SEGMENTS or (segs[0] == 'blogs' and len(segs) == 2):
            return T_ARCHIVE                   # صفحة المدونة الرئيسية = قائمة مقالات
        if (CATEGORY_ID_RE.match(last) or ARCHIVE_LAST_RE.match(last)
                or any(s in ARCHIVE_PARENT_SEGMENTS for s in segs[:-1])):
            return T_ARCHIVE                   # تصنيفات ووسوم المدونة
        sig = _html_signal(soup)
        if sig == 'article':
            return T_BLOG
        if sig == 'product':
            return T_PRODUCT
        slug = segs[-2] if (re.fullmatch(r'[a-z]?-?\d+', last) and len(segs) >= 2) else last
        if segment_is_mostly_policy(slug):
            return T_INFO
        return T_BLOG

    # 4) التصنيفات والقوائم
    if (CATEGORY_ID_RE.match(last) or path_clean in CATALOG_ROOTS
            or any(s in CATEGORY_SEGMENTS for s in segs)):
        return T_CATEGORY

    # 5) إشارات الصفحة نفسها (للقوالب والمنصات الأخرى)
    sig = _html_signal(soup)
    if sig == 'product':
        return T_PRODUCT
    if sig == 'article':
        return T_BLOG
    if sig == 'collection':
        return T_CATEGORY

    # 6) أرشيف عام
    if (ARCHIVE_LAST_RE.match(last) or re.fullmatch(r'\d{4}', last)
            or (len(segs) >= 2 and any(s in ARCHIVE_PARENT_SEGMENTS for s in segs[:-1]))):
        return T_ARCHIVE

    # 7) السياسات والصفحات التعريفية (بالكلمة الكاملة)
    if any(segment_is_policy(s) for s in segs):
        return T_INFO

    # 8) أنماط ضعيفة أخيرة
    if '-p-' in path_clean or re.search(r'[-/]p-?\d{4,}$', path_clean):
        return T_PRODUCT
    if re.search(r'[-/]c-?\d{4,}$', path_clean):
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
#  استخراج صور المحتوى والبيانات المهيكلة JSON-LD
# ==============================================================
JUNK_KEYWORDS = [
    'spinner', 'loader', 'loading', 'ajax', 'icon', 'badge', 'payment', 'gateway',
    'tamara', 'tabby', 'mada', 'visa', 'mastercard', 'apple-pay', 'applepay',
    'stc-pay', 'stcpay', 'maroof', 'social', 'whatsapp', 'snapchat',
    'instagram', 'tiktok', 'twitter', 'pixel', 'spacer', 'avatar', 'arrow',
    'placeholder', 'blank', 'zidship', 'aramex', 'smsa', 'redbox', 'naqel',
    'servicelevel', 'courier', 'shipment', 'shipping-company', 'carrier', 'fastlo',
    'imile', 's-empty', 'empty.png', 'lazy.png', 'transparent', 'dummy', '1x1',
]
# كلمات تُطابق ككلمة كاملة فقط، حتى لا تُستبعد صورة منتج مثل «cravat» أو «brand-oud»
JUNK_WORDS = {'vat', 'tax', 'logo', 'logos', 'favicon', 'watermark'}


def clean_image_url(url):
    if not url:
        return ""
    u = str(url).strip()
    mo = re.search(r'/cdn-cgi/image/[^/]+/(https?://.+)$', u, re.I)
    if mo:
        u = mo.group(1)
    elif '/cdn-cgi/image/' in u.lower():
        u = re.sub(r'/cdn-cgi/image/[^/]+/', '/', u, flags=re.I)
    return u.split('#')[0]


def get_image_src(img):
    for attr in ['data-src', 'data-original', 'data-lazy', 'data-lazy-src',
                 'data-image', 'data-large_image', 'data-zoom-image',
                 'data-src-webp', 's-image']:
        val = img.get(attr)
        if val and val.strip() and not val.strip().startswith('data:'):
            return val.strip()
    parent = img.parent
    if parent and parent.name == 'picture':
        for source in parent.find_all('source'):
            srcset = source.get('srcset') or source.get('data-srcset')
            if srcset and not srcset.strip().startswith('data:'):
                first = srcset.split(',')[0].strip().split(' ')[0]
                if first:
                    return first
    for attr in ['data-srcset', 'srcset']:
        val = img.get(attr)
        if val and val.strip() and not val.strip().startswith('data:'):
            first = val.split(',')[0].strip().split(' ')[0]
            if first:
                return first
    src = img.get('src')
    return src.strip() if src and not src.strip().startswith('data:') else ''


def is_relevant_seo_image(img, src):
    if not src:
        return False
    s = src.lower()
    if s.startswith('data:image') or 'static.' in s or '/static/' in s:
        return False
    tokens = set(re.split(r'[^a-z0-9]+', urlparse(s).path))
    if tokens & JUNK_WORDS:
        return False
    classes = ' '.join(img.get('class', [])).lower()
    img_id = (img.get('id') or '').lower()
    if any(k in classes or k in img_id for k in ['logo', 'brand', 'favicon']):
        return False
    if s.split('?')[0].endswith(('.gif', '.svg', '.ico')):
        return False
    if any(j in s for j in JUNK_KEYWORDS):
        return False
    return True


def strip_boilerplate(soup, markup=None):
    body = soup.body or soup
    total = len(body.get_text(' ', strip=True))
    targets = soup.select(
        'header#site-header, header.site-header, header.main-header, '
        'footer#site-footer, footer.site-footer, footer.main-footer, '
        'nav#main-nav, nav.main-navigation, aside#sidebar'
    )
    for tag in targets:
        try:
            if tag.name in ('html', 'body', 'main'):
                continue
            if tag.find('main') is not None or tag.find(attrs={'class': re.compile(r'product', re.I)}):
                continue
            tag.decompose()
        except Exception:
            pass
    if markup and total > 200:
        left = len((soup.body or soup).get_text(' ', strip=True))
        if left < total * 0.15:
            return make_soup(markup)
    return soup


def is_noindex(soup, res=None):
    for tag in soup.find_all('meta', attrs={'name': re.compile(r'^(robots|googlebot)$', re.I)}):
        if 'noindex' in str(tag.get('content') or '').lower():
            return True
    if res is not None:
        if 'noindex' in str(res.headers.get('X-Robots-Tag', '')).lower():
            return True
    return False


def title_h1_match(meta_title, h1_text):
    if not meta_title or not h1_text:
        return 'match_na'
    t = set(slug_tokens(meta_title))
    h = set(slug_tokens(h1_text))
    if not h:
        return 'match_na'
    return 'match_ok' if len(t & h) / len(h) >= 0.5 else 'match_diff'


def find_page_h1(soup):
    h1s = soup.find_all('h1')
    if not h1s:
        return ''
    for h in h1s:
        if h.find_parent(['header', 'nav']):
            continue
        text = re.sub(r'\s+', ' ', h.get_text(strip=True)).strip()
        if text:
            return text
    for h in h1s:
        text = re.sub(r'\s+', ' ', h.get_text(strip=True)).strip()
        if text:
            return text
    return ''


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
                facts['images'].append(clean_image_url(it.strip()))
        if node.get('sku') and not facts['sku']:
            facts['sku'] = str(node['sku'])
        if node.get('offers'):
            facts['offers'] = True
        break
    facts['images'] = list(dict.fromkeys(facts['images']))
    return facts


COUNT_PATTERNS = [
    r'عدد\s*المنتجات\s*[:：]?\s*([\d,]+)',
    r'([\d,]+)\s*منتج(?:اً|ا)?\b',
    r'من\s*أصل\s*([\d,]+)',
    r'\b([\d,]+)\s*products?\b',
    r'showing\s*\d+\s*(?:-|to)\s*\d+\s*of\s*([\d,]+)',
]


def extract_declared_count(soup, text=None):
    for node in iter_jsonld(soup):
        if node_types(node) & {'ItemList', 'CollectionPage'}:
            n = node.get('numberOfItems')
            if isinstance(n, (int, float)) and n > 0:
                return int(n)
    body = text if text is not None else soup.get_text(' ', strip=True)
    body = body[:4000]
    best = None
    for pat in COUNT_PATTERNS:
        for mo in re.finditer(pat, body, re.I):
            try:
                v = int(mo.group(1).replace(',', ''))
            except Exception:
                continue
            if 0 < v < 100000:
                best = v if best is None else max(best, v)
    return best


# ==============================================================
#  استخراج الروابط الشامل ودعم مكونات سلة وزد
# ==============================================================
# روابط منتجات وتصنيفات مدفونة داخل السكربتات وردود JSON
EMBEDDED_LINK_RE = re.compile(
    r'https?://[^\s"\'<>\\]+?/(?:[^\s"\'<>\\/]+/)?(?:[pc]-?\d{4,}|products/[^\s"\'<>\\/?#]+)'
    r'|(?<=["\'])/(?:[a-z]{2}/)?[^\s"\'<>\\]+?/[pc]-?\d{4,}(?=["\'])',
    re.I)
SCROLL_MARKERS = ('salla-infinite-scroll', 'infinite-scroll', 'infinite_scroll',
                  'load-more', 'loadmore', 'data-next-page', 'next-page=',
                  'ajaxinate', 'infinitescroll', 'pagination__load')


def unescape_json_text(text):
    """الروابط داخل JSON تُكتب https:\\/\\/... فلا يلتقطها البحث العادي."""
    return (text or '').replace('\\/', '/').replace('\\u002F', '/').replace('\\u002f', '/')


def extract_all_links(soup, raw_html, current_url, base_netloc):
    links = set()

    # 1. روابط <a> وخصائص البيانات
    for a in soup.find_all(['a', 'salla-button', 'div', 'button'], href=True):
        href = a['href'].strip()
        if href and not href.startswith(('mailto:', 'tel:', 'javascript:', '#')):
            full = clean_url(urljoin(current_url, href))
            if is_crawlable(full, base_netloc):
                links.add(full)

    for tag in soup.find_all(attrs={'data-href': True}):
        h = tag['data-href'].strip()
        if h:
            full = clean_url(urljoin(current_url, h))
            if is_crawlable(full, base_netloc):
                links.add(full)

    # 2. مكونات سلة وزد المخصصة
    for card in soup.find_all(['salla-product-card', 'custom-salla-product-card', 'salla-products-list']):
        for attr in ['url', 'data-url', 'link']:
            val = card.get(attr)
            if val and val.strip():
                full = clean_url(urljoin(current_url, val.strip()))
                if is_crawlable(full, base_netloc):
                    links.add(full)
        prod_json = card.get('product')
        if prod_json:
            try:
                p_data = json.loads(prod_json)
                u = p_data.get('url') or p_data.get('slug')
                if u:
                    full = clean_url(urljoin(current_url, u.strip()))
                    if is_crawlable(full, base_netloc):
                        links.add(full)
            except Exception:
                pass

    # 3. روابط المنتجات والتصنيفات المضمنة في السكربتات وردود JSON
    if raw_html:
        for m in EMBEDDED_LINK_RE.findall(unescape_json_text(raw_html)):
            full = clean_url(urljoin(current_url, m.strip()))
            if is_crawlable(full, base_netloc):
                links.add(full)

    return links


def extract_next_pages(soup, raw_html, current_url, base_netloc):
    """روابط «الصفحة التالية» كما يعلنها القالب — مع الإبقاء على ?page=
    (دالة clean_url تحذفه، ولهذا كانت صفحات التمرير اللانهائي تضيع)."""
    cands = []
    for tag in soup.find_all(['link', 'a']):
        rel = tag.get('rel')
        rels = [r.lower() for r in (rel if isinstance(rel, list) else ([rel] if rel else []))]
        if 'next' in rels and tag.get('href'):
            cands.append(tag['href'])
    for attr in ('next-page', 'data-next-page', 'data-next', 'data-next-url', 'data-next-page-url'):
        for tag in soup.find_all(attrs={attr: True}):
            cands.append(tag.get(attr))
    if raw_html:
        text = unescape_json_text(raw_html)
        for mo in re.finditer(r'["\'](?:next_page_url|next_page|nextPageUrl|next)["\']\s*:\s*["\']([^"\']+)["\']', text):
            cands.append(mo.group(1))
    out = set()
    for c in cands:
        c = str(c or '').strip()
        if not c or c.startswith(('#', 'javascript:')):
            continue
        full = urljoin(current_url, c)
        if is_crawlable(clean_url(full), base_netloc) and full.rstrip('/') != current_url.rstrip('/'):
            out.add(full)
    return out


def listing_text(res):
    """نص صفحة القائمة: HTML كما هو، أو حقل html داخل رد JSON، أو JSON نفسه بعد فك ترميز الروابط."""
    ctype = (res.headers.get('Content-Type') or '').lower()
    text = res.text or ''
    if 'json' in ctype or text.lstrip()[:1] in ('{', '['):
        try:
            data = res.json()
            if isinstance(data, dict):
                for k in ('html', 'content', 'data', 'products'):
                    v = data.get(k)
                    if isinstance(v, str) and '<' in v:
                        return unescape_json_text(v)
            return unescape_json_text(json.dumps(data, ensure_ascii=False))
        except Exception:
            pass
    return unescape_json_text(text)


# ==============================================================
#  محركات الحصد المخصصة للمنصات (شوبيفاي - سلة - زد)
# ==============================================================
def harvest_shopify_all(base_url):
    """سحب شامل لشوبيفاي عبر ملفات المنتجات والمجموعات العامة"""
    base_url = normalize_url(base_url)
    urls = set()
    for kind, key, max_pages in (('products', 'products', 40), ('collections', 'collections', 20)):
        page = 1
        while page <= max_pages:
            res = safe_get(f"{base_url}/{kind}.json?limit=250&page={page}", timeout=12, retries=1)
            if not is_ok(res):
                break
            try:
                items = res.json().get(key, [])
            except Exception:
                break
            if not items:
                break
            for it in items:
                handle = it.get('handle')
                if handle:
                    urls.add(f"{base_url}/{kind}/{handle}")
            if len(items) < 250:
                break
            page += 1
    return urls


def harvest_zid_catalog(base_url):
    """سحب مسارات وروابط متجر زد الأساسية والتصنيفات"""
    base_url = normalize_url(base_url)
    found = set()
    netloc = urlparse(base_url).netloc
    for path in ['/categories', '/products', '/collections']:
        res = safe_get(f"{base_url}{path}", retries=1)
        if is_ok(res):
            soup = make_soup(res.text)
            found.update(extract_all_links(soup, res.text, base_url, netloc))
    return found


def harvest_infinite_scroll_many(urls, base_url, max_scrolls=30):
    """التمرير اللانهائي بمتصفح خفي واحد لكل الأقسام (بدل متصفح جديد لكل قسم).
    يعيد {رابط القسم: مجموعة روابط المنتجات}."""
    results = {}
    if not HAS_PLAYWRIGHT or not urls:
        return results
    base_netloc = urlparse(normalize_url(base_url)).netloc

    deep_extract_script = """
    () => {
        const urls = new Set();
        function traverse(node) {
            if (!node) return;
            if (node.nodeType === Node.ELEMENT_NODE) {
                if (node.tagName === 'A' && node.href) urls.add(node.href);
                for (const attr of ['href', 'data-href', 'url', 'data-url', 'data-product-url']) {
                    const val = node.getAttribute(attr);
                    if (val) urls.add(val);
                }
            }
            if (node.shadowRoot) traverse(node.shadowRoot);
            for (const child of node.childNodes) traverse(child);
        }
        traverse(document.body);
        return Array.from(urls);
    }
    """

    def keep(u, found):
        full = clean_url(urljoin(base_url, str(u).strip()))
        if is_crawlable(full, base_netloc) and _detect_type_by_url(full, base_url) == T_PRODUCT:
            found.add(full)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=['--disable-gpu', '--no-sandbox',
                                                             '--disable-dev-shm-usage'])
            context = browser.new_context(user_agent=HEADERS['User-Agent'],
                                          viewport={'width': 1366, 'height': 900})
            for url in list(urls):
                found = set()
                page = context.new_page()

                def on_response(response, found=found):
                    try:
                        if 'json' in (response.headers.get('content-type') or ''):
                            text = unescape_json_text(response.text())
                            for m in EMBEDDED_LINK_RE.findall(text):
                                keep(m, found)
                    except Exception:
                        pass

                page.on("response", on_response)
                try:
                    page.goto(url, timeout=25000, wait_until='domcontentloaded')
                    page.wait_for_timeout(1500)
                    stagnant, last_total = 0, 0
                    for _ in range(max_scrolls):
                        for h in page.evaluate(deep_extract_script):
                            keep(h, found)
                        try:
                            btn = page.query_selector('button[class*="load-more"], .load-more, '
                                                      'salla-infinite-scroll button')
                            if btn and btn.is_visible():
                                btn.click()
                                page.wait_for_timeout(800)
                        except Exception:
                            pass
                        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        page.wait_for_timeout(1000)
                        if len(found) == last_total:
                            stagnant += 1
                            if stagnant >= 4:
                                break
                        else:
                            stagnant = 0
                        last_total = len(found)
                except Exception:
                    pass
                finally:
                    try:
                        page.close()
                    except Exception:
                        pass
                results[url] = found
            browser.close()
    except Exception:
        pass
    return results


def harvest_infinite_scroll_playwright(url, base_url, max_scrolls=30):
    """واجهة متوافقة مع الإصدار السابق."""
    return harvest_infinite_scroll_many([url], base_url, max_scrolls).get(url, set())


# ==============================================================
#  فحص الصفحة الواحدة
# ==============================================================
def fetch_page_with_playwright_fallback(url):
    """جلب المحتوى بالمتصفح الخفي إذا كانت الصفحة فارغة بدون JavaScript"""
    if not HAS_PLAYWRIGHT:
        return None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=['--disable-gpu', '--no-sandbox', '--disable-dev-shm-usage'])
            page = browser.new_page(user_agent=HEADERS['User-Agent'], viewport={'width': 1366, 'height': 768})
            page.goto(url, timeout=25000, wait_until='domcontentloaded')
            page.wait_for_timeout(1500)
            content = page.content()
            browser.close()
            return content
    except Exception:
        return None


def same_page_url(a, b):
    """هل الرابطان لنفس المسار؟ نتجاهل www وبادئة اللغة والحروف الكبيرة فقط،
    فيبقى تغيير اسم المنتج (شراريب ← جوارب) تحويلاً حقيقياً يستحق الذكر."""
    def norm(u):
        return norm_host(urlparse(clean_url(u)).netloc) + '/' + '/'.join(url_segments(u)).lower()
    return norm(a) == norm(b)


def redirect_chain(res):
    """سلسلة أكواد التحويل مثل «301 → 200»، أو نص فارغ إن لم يحدث تحويل."""
    if res is None or not res.history:
        return ''
    return ' → '.join([str(r.status_code) for r in res.history] + [str(res.status_code)])


def broken_page_row(url, reason, source, base_url='', final='', chain=''):
    return {
        'page_data': {
            'نوع الصفحة': T_BROKEN, 'الرابط': unquote(url), 'مصدر الاكتشاف': source,
            'متاحة': False, 'كود الاستجابة': str(reason), 'لغة الصفحة': '—',
            'نوع الرابط': _detect_type_by_url(clean_url(url), base_url) if base_url else T_UNKNOWN,
            'الوجهة النهائية': unquote(final) if final else '',
            'سلسلة التحويل': chain,
            'اسم المنتج المعروض': '', 'اسم منظم': '', 'صور معلنة': 0,
            'قابلة للأرشفة': True, 'مطابقة العنوان مع H1': 'match_na',
            'رقم المنتج': '', 'عدد معلن': None,
            'درجة السيو': None, 'عنوان الميتا': '', 'طول العنوان': 0,
            'حالة العنوان': 'failed', 'وصف الميتا': '', 'طول الوصف': 0,
            'حالة الوصف': 'failed', 'إجمالي الصور': 0, 'صور بدون Alt': 0,
            'صور Alt ضعيف': 0, 'عدد الكلمات': 0, 'حالة المحتوى': 'na',
            'حالة الكانونيكال': 'canon_missing', 'الرابط الكانوني': '',
            '_raw_url': url, '_req_url': url,
        },
        'images_data': [], 'links': set(), 'product_links': set(),
        'next_pages': set(), 'scroll_marker': False,
    }


def fetch_and_audit(task):
    url, base_url, source = task
    try:
        return _fetch_and_audit(url, base_url, source)
    except Exception as e:
        return broken_page_row(clean_url(url), f'خطأ فني: {type(e).__name__}', source, base_url)


DELETED_HOME = 'محذوف — تحويل للرئيسية'


def _fetch_and_audit(url, base_url, source):
    req = clean_url(url)
    res = safe_get(url)
    if res is None:
        return broken_page_row(req, 'فشل اتصال', source, base_url)
    chain = redirect_chain(res)
    final_url = clean_url(res.url)
    moved = not same_page_url(final_url, req)
    ctype = (res.headers.get('Content-Type') or '').lower()
    if res.status_code != 200:
        return broken_page_row(req, f'خطأ {res.status_code}', source, base_url,
                               final_url if moved else '', chain)
    if ctype and 'html' not in ctype:
        return broken_page_row(req, 'ليست صفحة HTML', source, base_url)

    html_text = res.text
    soup = make_soup(html_text)

    # صفحة فارغة تعتمد كلياً على JavaScript: نستعين بالمتصفح الخفي
    content_words = len((soup.body or soup).get_text(' ', strip=True).split())
    if content_words < 15 and HAS_PLAYWRIGHT:
        rendered_html = fetch_page_with_playwright_fallback(final_url)
        if rendered_html:
            html_text = rendered_html
            soup = make_soup(html_text)

    # سلة تحوّل المنتج المحذوف أو المخفي إلى الرئيسية بدل 404
    home_key = url_key(normalize_url(base_url))
    if url_key(req) != home_key:
        canon_now = ''
        for lk in soup.find_all('link', href=True):
            rel = lk.get('rel') or []
            rel = [r.lower() for r in (rel if isinstance(rel, list) else [rel])]
            if 'canonical' in rel:
                canon_now = clean_url(urljoin(final_url, lk['href']))
                break
        if url_key(final_url) == home_key or (canon_now and url_key(canon_now) == home_key):
            return broken_page_row(req, DELETED_HOME, source, base_url, final_url,
                                   chain or 'canonical → الرئيسية')

    page_type = detect_page_type(final_url, base_url, soup)
    base_netloc = urlparse(normalize_url(base_url)).netloc

    links = extract_all_links(soup, html_text, final_url, base_netloc)
    is_listing = page_type in LISTING_TYPES
    next_pages = extract_next_pages(soup, html_text, final_url, base_netloc) if is_listing else set()
    low_html = html_text.lower() if is_listing else ''
    scroll_marker = is_listing and any(m in low_html for m in SCROLL_MARKERS)

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

    display_name = find_page_h1(soup)
    noindex = is_noindex(soup, res)
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

    content_soup = strip_boilerplate(soup, html_text)
    total_img = 0
    page_images = []

    for img in content_soup.find_all(['img', 'salla-image']):
        src = get_image_src(img)
        if src and is_relevant_seo_image(img, src):
            total_img += 1
            alt_text = (img.get('alt') or '').strip()
            alt_status, alt_len = grade_alt(alt_text)
            page_images.append({
                'رابط الصفحة': unquote(final_url), 'نوع الصفحة': page_type,
                'رابط الصورة': clean_image_url(urljoin(final_url, src)),
                'النص البديل الحالي (Alt)': alt_text,
                'طول النص البديل': alt_len, 'حالة النص البديل': alt_status,
                'صيغة الصورة': image_format(urljoin(final_url, src)),
            })

    jd = extract_product_facts(soup) if page_type == T_PRODUCT else \
        {'name': '', 'images': [], 'sku': '', 'offers': False}

    prod_links = set()
    if page_type in (T_CATEGORY, T_HOME):
        for lk in links:
            if _detect_type_by_url(lk, base_url) == T_PRODUCT:
                prod_links.add(url_key(lk))

    declared_n = (extract_declared_count(soup)
                  if page_type in (T_CATEGORY, T_HOME) else None)

    for s in content_soup(['script', 'style', 'noscript']):
        s.decompose()
    body_text = content_soup.get_text(separator=' ', strip=True)
    words = len(body_text.split())
    content_status = 'good' if words >= 40 else 'thin'
    page_lang = detect_page_language(soup, (title + ' ' + body_text[:500]))

    return {
        'page_data': {
            'نوع الصفحة': page_type, 'الرابط': unquote(final_url), 'مصدر الاكتشاف': source,
            'متاحة': True, 'كود الاستجابة': '200', 'لغة الصفحة': page_lang,
            'نوع الرابط': page_type,
            'الوجهة النهائية': unquote(final_url) if moved else '',
            'سلسلة التحويل': chain if moved else '',
            'اسم المنتج المعروض': display_name, 'اسم منظم': jd['name'],
            'قابلة للأرشفة': not noindex,
            'مطابقة العنوان مع H1': title_h1_match(title, display_name),
            'صور معلنة': len(jd['images']), 'رقم المنتج': jd['sku'],
            'عدد معلن': declared_n,
            'درجة السيو': None,
            'عنوان الميتا': title, 'طول العنوان': title_len, 'حالة العنوان': title_status,
            'وصف الميتا': meta_desc, 'طول الوصف': desc_len, 'حالة الوصف': desc_status,
            'إجمالي الصور': total_img, 'صور بدون Alt': 0, 'صور Alt ضعيف': 0,
            'عدد الكلمات': words, 'حالة المحتوى': content_status,
            'حالة الكانونيكال': canon_status,
            'الرابط الكانوني': unquote(canonical) if canon_status == 'canon_diff' else '',
            '_raw_url': final_url, '_req_url': req,
        },
        'images_data': page_images,
        'links': links,
        'product_links': prod_links,
        'next_pages': next_pages,
        'scroll_marker': scroll_marker,
        'platform_html': html_text[:70000] if page_type == T_HOME else '',
        'platform_headers': dict(res.headers) if page_type == T_HOME else {},
    }


# ==============================================================
#  الجودة البنيوية وتدقيق الروابط
# ==============================================================
PLACEHOLDER_PATTERNS = [
    r'^\s*\[\s*[\.\-_]*\s*\]\s*$',
    r'\{\{.*?\}\}', r'\{%.*?%\}',
    r'%[sd]\b', r'<%.*?%>',
    r'\b(undefined|null|nan|none|lorem ipsum|test|xxx|todo|tbd)\b',
    r'^\s*(page|product|item|title|default)\s*\d*\s*$',
]


def meaningful_text(t):
    return re.sub(r'[^0-9A-Za-z\u0600-\u06FF]+', '', str(t or ''))


def is_placeholder(t):
    low = str(t or '').strip().lower()
    if not low:
        return False
    return any(re.search(pat, low) for pat in PLACEHOLDER_PATTERNS)


def detect_brand(titles):
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
QUALITY_FATAL = ('q_symbols', 'q_placeholder')
QUALITY_CREDIT = {'q_ok': 1.0, 'q_duplicate': 0.3, 'q_brand_only': 0.2,
                  'q_one_word': 0.3, 'q_same_as_title': 0.4,
                  'q_symbols': 0.0, 'q_placeholder': 0.0, 'q_na': 1.0}
TEXT_DUP_THRESHOLD = 3


def analyze_text_quality(df):
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

    for col_q, col_s, col_len in [('جودة العنوان', 'حالة العنوان', 'طول العنوان'),
                                  ('جودة الوصف', 'حالة الوصف', 'طول الوصف')]:
        fatal = out[col_q].isin(QUALITY_FATAL)
        out.loc[fatal, col_s] = 'missing'
        out.loc[fatal, col_len] = 0
    return out, brand


CLONE_PATTERNS = [r'copy-of', r'copy_of', r'-copy\b', r'نسخة', r'نسخه',
                  r'duplicate', r'\bتجربة\b', r'\btest\b']
URL_MAX_PATH = 90

URL_LABEL = {
    'ar': {'u_ok': 'سليم', 'u_clone': 'منتج مستنسخ', 'u_generic': 'رقم أو رمز بلا كلمات',
           'u_wrongname': 'يشير لمنتج آخر',
           'u_underscore': 'شرطة سفلية بدل الواصلة', 'u_uppercase': 'حروف كبيرة',
           'u_long': 'طويل جداً', 'u_repeat': 'كلمة مكررة داخل الرابط',
           'u_wordy': 'كلمات كثيرة', 'u_malformed': 'رابط معطوب فيه عنوان موقع',
           'u_na': '—'},
    'en': {'u_ok': 'Sound', 'u_clone': 'Cloned product', 'u_generic': 'ID or code, no words',
           'u_wrongname': 'Points to a different product',
           'u_underscore': 'Underscores instead of hyphens', 'u_uppercase': 'Uppercase letters',
           'u_long': 'Too long', 'u_repeat': 'Repeated word in slug',
           'u_wordy': 'Too many words', 'u_malformed': 'Malformed: contains a URL',
           'u_na': '—'},
}
URL_CREDIT = {'u_malformed': 0.5, 'u_ok': 1.0, 'u_underscore': 0.95, 'u_uppercase': 0.95, 'u_repeat': 0.95,
              'u_wordy': 0.93, 'u_long': 0.90, 'u_generic': 0.80, 'u_wrongname': 0.65,
              'u_clone': 0.70, 'u_na': 1.0}
URL_MAX_WORDS = 9


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
    """الجزء الوصفي من الرابط. نتجاوز مقاطع المعرّفات (p123 و c123 و page-123 والأرقام)
    حتى لا يُعتبر رابط التصنيف في سلة «رقماً بلا كلمات»."""
    segs = url_segments(url)
    if not segs:
        return ''
    last = segs[-1]
    if (PRODUCT_ID_RE.match(last) or CATEGORY_ID_RE.match(last) or INFO_ID_RE.match(last)
            or re.fullmatch(r'\d+', last)) and len(segs) >= 2:
        return segs[-2]
    return last


def analyze_url_quality(df, brand=''):
    if df.empty:
        return df
    out = df.copy()
    out['المسار'] = out['الرابط'].map(slug_of)
    known = {url_key(u) for u in out['الرابط']}

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

        if any(re.search(pat, low) for pat in CLONE_PATTERNS):
            return 'u_clone'
        mo = re.match(r'^(.*)-(\d{1,2})$', slug)
        if mo:
            parent = str(row['الرابط']).replace(slug, mo.group(1))
            own = url_key(row['الرابط'])
            # في سلة المفتاح هو رقم المنتج، فالرابط «الأب» يعطي المفتاح نفسه: ليس نسخة
            if url_key(parent) in known and url_key(parent) != own:
                return 'u_clone'

        if re.search(r'https?[:;]|://|www\.|\.com\b|\.net\b|\.store\b', low):
            return 'u_malformed'

        if re.fullmatch(r'[\d\W_]+', slug) or \
                re.fullmatch(r'(product|item|page|post)[-_]?\d*', low):
            return 'u_generic'

        words = [w for w in re.split(r'[-_]+', slug) if w]

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

        name = (str(row.get('اسم منظم') or '').strip()
                or str(row.get('اسم المنتج المعروض') or '').strip())
        meta_t = str(row.get('عنوان الميتا') or '').strip()
        if (name or meta_t) and row.get('نوع الصفحة') == T_PRODUCT:
            s_tok = [t for t in slug_tokens(slug) if not t.isdigit()]
            n_tok = (set(slug_tokens(name)) | set(slug_tokens(meta_t))) - brand_tokens
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
    if df.empty:
        return df, []
    out = df.copy()
    ok = out[out['متاحة'] == True]  # noqa: E712
    groups = []
    sub = ok[(ok['عنوان الميتا'].astype(str).str.strip() != '') & (ok['وصف الميتا'].astype(str).str.strip() != '')]
    for (t, d), grp in sub.groupby(['عنوان الميتا', 'وصف الميتا']):
        if len(grp) > 1:
            groups.append({'العنوان': t, 'عدد الصفحات': len(grp),
                           'الروابط': list(grp['الرابط'])})
    dup_urls = {u for g in groups for u in g['الروابط']}
    out['محتوى مكرر'] = out['الرابط'].isin(dup_urls)
    return out, groups


MODERN_FORMATS = ('webp', 'avif')
LEN_WEIGHT = {'optimal': 1.0, 'acceptable': 0.7, 'very_short': 0.3,
              'long': 0.4, 'missing': 0.0}


def score_pages(df, images_df):
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
#  الترقيم والتمرير اللانهائي
# ==============================================================
PAGING_PATTERNS = ['?page={n}', '?p={n}', '/page/{n}', '?page={n}&limit=24', '?offset={o}']
LISTING_ROOTS = ['products', 'latest-products', 'collections/all', 'collections', 'shop', 'store',
                 'all-products', 'كل-المنتجات', 'جميع-المنتجات', 'offers']
PLATFORM_LISTINGS = [
    'products', 'latest-products', 'offers', 'categories', 'brands',
    'collections/all', 'shop', 'blog', 'all-products'
]
MIN_ITEMS_FOR_PAGING = 12   # قسم يعرض 12 منتجاً أو أكثر في صفحته الأولى غالباً له صفحات تالية
MIN_PROBE_ITEMS = 8         # قبل اكتشاف نمط الترقيم لا نجرّب الأنماط على الأقسام الصغيرة


def listing_product_links(text, base_url, page_url):
    soup = make_soup(text)
    netloc = urlparse(normalize_url(base_url)).netloc
    out = set()
    for full in extract_all_links(soup, text, page_url, netloc):
        if _detect_type_by_url(full, base_url) in (T_PRODUCT, T_BLOG):
            out.add(full)
    return out


def _paged_url(root, pat, n):
    part = pat.format(n=n, o=(n - 1) * 20)
    if part.startswith('?') and '?' in root:
        part = '&' + part[1:]
    return root + part


def harvest_paginated_products(base_url, category_urls, seen_keys, progress_cb=None,
                               max_depth=MAX_PAGINATION_DEPTH, cat_products=None,
                               listing_urls=None, next_hints=None, scroll_roots=None):
    """يجمع المنتجات المخفية خلف الترقيم والتمرير اللانهائي بثلاث طرق مرتبة:
    1) رابط «الصفحة التالية» الذي يعلنه القالب نفسه.
    2) نمط ترقيم واحد يُكتشف مرة للمتجر كله ثم يُعاد استخدامه (بدل تجربة 5 أنماط لكل قسم).
    3) المتصفح الخفي لعدد محدود من الأقسام التي تعتمد على التمرير فعلاً."""
    base_url = normalize_url(base_url)
    netloc = urlparse(base_url).netloc
    cat_products = cat_products if cat_products is not None else {}
    next_hints = next_hints or {}
    scroll_roots = set(scroll_roots or [])
    roots = list(dict.fromkeys(
        list(category_urls) + list(listing_urls or []) +
        [f"{base_url}/{r}" for r in LISTING_ROOTS]))

    new_urls, fetched = [], 0
    learned = None            # نمط الترقيم الذي يعمل في هذا المتجر
    failed_probes = 0
    need_browser = []

    def register(root, urls, seen_here):
        added = 0
        for u in urls:
            k = url_key(u)
            if k in seen_here:
                continue
            seen_here.add(k)
            cat_products.setdefault(root, set()).add(k)
            added += 1
            if k not in seen_keys:
                seen_keys.add(k)
                new_urls.append(u)
        return added

    for idx, root in enumerate(roots):
        seen_here = set(cat_products.get(root, set()))
        first_page_items = len(seen_here)
        got_more = False

        # 1) سلسلة «الصفحة التالية»
        queue, visited = list(next_hints.get(root, [])), set()
        while queue and len(visited) < max_depth:
            nxt = queue.pop(0)
            if nxt in visited:
                continue
            visited.add(nxt)
            res = safe_get(nxt, retries=1, headers=XHR_HEADERS)
            fetched += 1
            if not is_ok(res):
                break
            text = listing_text(res)
            if register(root, listing_product_links(text, base_url, root), seen_here) == 0:
                break
            got_more = True
            queue.extend(u for u in extract_next_pages(make_soup(text), text, nxt, netloc)
                         if u not in visited)

        # 2) نمط الترقيم
        if not got_more and learned != 'none' and (learned or first_page_items >= MIN_PROBE_ITEMS):
            patterns = [learned] if learned else PAGING_PATTERNS
            for n in range(2, max_depth + 1):
                added = 0
                for pat in patterns:
                    res = safe_get(_paged_url(root, pat, n), retries=0, headers=XHR_HEADERS)
                    fetched += 1
                    if not is_ok(res):
                        continue
                    added = register(root, listing_product_links(listing_text(res), base_url, root),
                                     seen_here)
                    if added:
                        learned, patterns = pat, [pat]
                        break
                if not added:
                    if n == 2 and not learned and first_page_items >= MIN_ITEMS_FOR_PAGING:
                        failed_probes += 1
                        if failed_probes >= 3:
                            learned = 'none'    # المتجر لا يستخدم ترقيماً بالروابط
                    break
                got_more = True

        # 3) مرشح للمتصفح الخفي
        if not got_more and root in scroll_roots:
            need_browser.append(root)

        if progress_cb:
            progress_cb(idx + 1, len(roots), len(new_urls), fetched)

    if need_browser and HAS_PLAYWRIGHT:
        for root, found in harvest_infinite_scroll_many(need_browser[:MAX_BROWSER_ROOTS],
                                                        base_url).items():
            register(root, found, set(cat_products.get(root, set())))

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
#  قراءة خرائط الموقع (المتعددة والمتداخلة)
# ==============================================================
try:
    from usp.tree import sitemap_tree_for_homepage as _usp_tree
    HAS_USP = True
except Exception:
    HAS_USP = False


def sitemap_urls_via_usp(base_url, netloc):
    if not HAS_USP:
        return None
    try:
        tree = _usp_tree(base_url)
        out = set()
        for page in tree.all_pages():
            u = clean_url(page.url)
            if u and norm_host(urlparse(u).netloc) == norm_host(netloc) and not is_tag_url(u):
                out.add(u)
        return out if out else None
    except Exception:
        return None


def discover_sitemaps_from_robots(base_url):
    found = []
    res = safe_get(f"{base_url}/robots.txt", timeout=10, retries=1)
    if is_ok(res):
        for line in res.text.splitlines():
            if line.lower().strip().startswith('sitemap:'):
                sm = line.split(':', 1)[1].strip()
                if sm and sm not in found:
                    found.append(sm)
    return found


LOC_RE = re.compile(r'<loc>\s*(.*?)\s*</loc>', re.I | re.S)


def parse_sitemap_text(content, name=''):
    """يستخرج الروابط من محتوى ملف خريطة (نص أو gz). يعيد قائمة أو None إن لم يكن خريطة."""
    if isinstance(content, str):
        content = content.encode('utf-8', 'ignore')
    if str(name).lower().endswith('.gz') or content[:2] == b'\x1f\x8b':
        try:
            content = gzip.decompress(content)
        except Exception:
            pass
    text = content.decode('utf-8', 'ignore').lstrip('\ufeff \t\r\n')
    low = text.lower()
    if '<loc' not in low and '<sitemapindex' not in low and '<urlset' not in low:
        return None
    locs = []
    for m in LOC_RE.findall(text):
        v = m.strip()
        # بعض المنصات تغلّف الرابط: <loc><![CDATA[https://...]]></loc>
        v = re.sub(r'^<!\[CDATA\[(.*)\]\]>$', r'\1', v, flags=re.S).strip()
        v = v.replace('&amp;', '&')
        if v:
            locs.append(v)
    if locs:
        return locs
    try:
        root = ET.fromstring(text.encode('utf-8'))
        return [el.text.strip() for el in root.iter()
                if (el.tag.split('}')[-1] if '}' in el.tag else el.tag) == 'loc'
                and el.text]
    except Exception:
        return None


def sitemap_fail_reason(res):
    if res is None:
        return 'انقطع الاتصال أو انتهت المهلة'
    if is_challenge(res):
        return 'الحماية منعت الطلب'
    code = res.status_code
    if code == 429:
        return 'المتجر طلب التمهّل (429)'
    if code == 403:
        return 'الحماية منعت الطلب (403)'
    if code in (404, 410):
        return f'الملف غير موجود ({code})'
    if code >= 500:
        return f'خطأ في خادم المتجر ({code})'
    if code != 200:
        return f'رد غير متوقع ({code})'
    return 'الملف ليس بصيغة خريطة موقع'


def fetch_sitemap_locs(url, quick=False, with_reason=False):
    res = safe_get(url, timeout=(8 if quick else 30), retries=(0 if quick else 2),
                   headers={'Accept': 'application/xml,text/xml;q=0.9,*/*;q=0.8',
                            'Sec-Fetch-Dest': 'empty', 'Sec-Fetch-Mode': 'no-cors'})
    locs = parse_sitemap_text(res.content, url) if is_ok(res) else None
    if with_reason:
        return locs, (None if locs is not None else sitemap_fail_reason(res))
    return locs


def _is_sitemap_loc(loc):
    p = loc.lower().split('?')[0]
    return p.endswith(('.xml', '.xml.gz')) or bool(re.search(r'/sitemap[^/]*$', p))


SITEMAP_PAUSE = 0.3   # مهلة قصيرة بين ملفات الخريطة فقط (لا بين الصفحات)


class SitemapCollector:
    """يجمع روابط كل خرائط المتجر من ثلاثة مصادر:
    ملفات يرفعها المستخدم (تتجاوز الحماية تماماً)، وروابط خرائط يلصقها،
    وما يعلنه المتجر في robots.txt. ويحفظ سبب فشل كل ملف لم يُقرأ."""

    def __init__(self, base_url, max_depth=4):
        self.base_url = normalize_url(base_url)
        self.base_netloc = urlparse(self.base_url).netloc
        self.max_depth = max_depth
        self.found = {}
        self.visited = set()
        self.uploaded_names = set()
        self.failed = {}          # رابط الملف ← السبب
        self.report = {'files_ok': 0, 'files': [], 'source': '', 'uploaded': 0}

    # ---------- أدوات ----------
    def add(self, u):
        u = clean_url(u)
        if not u or norm_host(urlparse(u).netloc) != norm_host(self.base_netloc) or is_tag_url(u):
            return
        k = url_key(u)
        self.found[k] = prefer_url(self.found[k], u) if k in self.found else u

    @staticmethod
    def _basename(u):
        return unquote(urlparse(str(u)).path).rstrip('/').rsplit('/', 1)[-1].lower()

    def _consume(self, locs, depth):
        for loc in locs:
            if _is_sitemap_loc(loc):
                # ملف فرعي رفعه المستخدم؟ لا داعي لتحميله
                if self._basename(loc) in self.uploaded_names:
                    self.visited.add(loc)
                    continue
                self.walk(loc, depth + 1, declared=True)
            else:
                self.add(loc)

    def walk(self, sm_url, depth, declared=True):
        if depth > self.max_depth:
            return False
        if sm_url in self.visited:
            return True
        self.visited.add(sm_url)
        tries = 3 if declared else 1
        locs, reason = None, None
        for attempt in range(tries):
            if attempt == 0 and self.report['files_ok']:
                time.sleep(SITEMAP_PAUSE)
            locs, reason = fetch_sitemap_locs(sm_url, quick=not declared, with_reason=True)
            if locs is not None:
                break
            if attempt + 1 < tries:
                time.sleep(1.5 * (attempt + 1))
        if locs is None:
            if declared:
                self.failed[sm_url] = reason
            return False
        self.failed.pop(sm_url, None)
        self.report['files_ok'] += 1
        self.report['files'].append(sm_url)
        self._consume(locs, depth)
        return True

    # ---------- المصادر ----------
    def add_uploaded(self, files):
        """files: قائمة (اسم الملف، المحتوى bytes)."""
        for name, content in files or []:
            locs = parse_sitemap_text(content, name)
            if locs is None:
                self.failed[f'ملف مرفوع: {name}'] = 'الملف ليس بصيغة خريطة موقع'
                continue
            self.uploaded_names.add(str(name).lower())
            self.report['uploaded'] += 1
            self.report['files_ok'] += 1
            self.report['files'].append(f'ملف مرفوع: {name}')
            self._consume(locs, 0)

    def run(self, uploaded=None, urls=None):
        self.add_uploaded(uploaded)
        for u in urls or []:
            u = str(u).strip()
            if u:
                self.walk(u if u.startswith('http') else urljoin(self.base_url + '/', u), 0, True)

        # ما يعلنه المتجر في robots.txt — والملفات التي رفعها المستخدم لا تُحمَّل مرة أخرى
        user_given = bool(self.found)
        for c in discover_sitemaps_from_robots(self.base_url):
            if self._basename(c) in self.uploaded_names:
                continue
            self.walk(c, 0, declared=True)
        if self.found:
            self.report['source'] = 'user + robots.txt' if user_given else 'robots.txt'

        if not self.found:
            via = sitemap_urls_via_usp(self.base_url, self.base_netloc)
            if via:
                for u in via:
                    self.add(u)
                self.report['source'] = 'usp'

        if not self.found:
            for c in [f"{self.base_url}/sitemap.xml", f"{self.base_url}/sitemap_index.xml",
                      f"{self.base_url}/sitemap-index.xml", f"{self.base_url}/sitemap.xml.gz",
                      f"{self.base_url}/sitemap/sitemap.xml", f"{self.base_url}/sitemaps.xml",
                      f"{self.base_url}/wp-sitemap.xml"]:
                self.walk(c, 0, declared=False)
            if self.found:
                self.report['source'] = 'standard'

        if not self.found:
            for prefix in ['sitemap-', 'sitemap_', 'sitemap_products_', 'sitemap_categories_',
                           'sitemap_pages_', 'sitemap_blogs_']:
                for i in range(1, 30):
                    if not self.walk(f"{self.base_url}/{prefix}{i}.xml", 0, declared=False):
                        break
            if self.found:
                self.report['source'] = 'guessed'
        return self

    def retry_failed(self):
        """جولة ثانية هادئة للملفات التي فشلت، بعد انتهاء الزحف."""
        before = set(self.found)
        for sm_url in list(self.failed):
            if sm_url.startswith('ملف مرفوع'):
                continue
            self.visited.discard(sm_url)
            time.sleep(2)
            self.walk(sm_url, 0, declared=True)
        return [self.found[k] for k in set(self.found) - before]

    # ---------- النتيجة ----------
    def urls(self):
        return set(self.found.values())

    def final_report(self):
        rep = dict(self.report)
        rep['failed'] = [{'الملف': u, 'السبب': r} for u, r in self.failed.items()]
        rep['failed_urls'] = list(self.failed)
        rep['files_failed'] = len(self.failed)
        rep['partial'] = bool(self.failed)
        rep['total_urls'] = len(self.found)
        return rep


def collect_sitemap_urls(base_url, max_depth=4, uploaded=None, urls=None):
    """واجهة متوافقة مع الإصدار السابق."""
    col = SitemapCollector(base_url, max_depth).run(uploaded, urls)
    return col.urls(), col.final_report()


# ==============================================================
#  إزالة التكرار والملخص
# ==============================================================
def dedupe_pages(df):
    if df.empty:
        return df
    df = df.copy()
    src_col = '_raw_url' if '_raw_url' in df.columns else 'الرابط'
    df['_key'] = df[src_col].map(url_key)
    df['_lang'] = df[src_col].map(lambda u: 1 if has_lang_prefix(str(u)) else 0)
    df['_avail'] = df['متاحة'].map(lambda v: 0 if v else 1)
    df['_canon'] = df.apply(
        lambda r: url_key(r['الرابط الكانوني'])
        if str(r.get('الرابط الكانوني') or '').strip() else r['_key'], axis=1)
    # نبقي النسخة المتاحة ثم النسخة الأساسية بلا بادئة لغة
    df = df.sort_values(['_avail', '_lang'], kind='stable').drop_duplicates(subset=['_key'])
    avail = df[df['متاحة'] == True]  # noqa: E712
    dup_keys = set(avail[avail.duplicated(subset=['_canon'], keep='first')]['_key'])

    canon_broken = len(avail) >= 10 and len(dup_keys) > len(avail) * 0.5
    if not canon_broken:
        df = df[~df['_key'].isin(dup_keys)]
    out = df.drop(columns=['_key', '_canon', '_lang', '_avail']).reset_index(drop=True)
    if canon_broken:
        out.attrs['canon_broken'] = int(len(dup_keys))
    return out


def _avail_series(df):
    return df['متاحة'].fillna(False).astype(bool) if 'متاحة' in df.columns \
        else pd.Series(True, index=df.index)


def title_url_fix_mask(df):
    """صفحات يحتاج عنوانها أو رابطها إصلاحاً: طول غير مثالي، أو عنوان مكرر/رموز/اسم المتجر فقط،
    أو رابط بصياغة سيئة. نفس التعريف يُحسب به بند «العناوين والروابط» في عرض السعر."""
    if df is None or df.empty:
        return pd.Series(False, index=getattr(df, 'index', None))
    m = df['حالة العنوان'] != 'optimal'
    if 'جودة العنوان' in df.columns:
        m |= ~df['جودة العنوان'].fillna('q_na').isin(['q_ok', 'q_na'])
    if 'جودة الرابط' in df.columns:
        m |= ~df['جودة الرابط'].fillna('u_na').isin(['u_ok', 'u_na'])
    return _avail_series(df) & m


def desc_fix_mask(df):
    """صفحات يحتاج وصف الميتا فيها إصلاحاً: طول غير مثالي، أو وصف مكرر أو نسخة من العنوان."""
    if df is None or df.empty:
        return pd.Series(False, index=getattr(df, 'index', None))
    m = df['حالة الوصف'] != 'optimal'
    if 'جودة الوصف' in df.columns:
        m |= ~df['جودة الوصف'].fillna('q_na').isin(['q_ok', 'q_na'])
    return _avail_series(df) & m


def _code_series(df):
    return df['كود الاستجابة'].astype(str)


def compute_summary(df, coverage=None, images_df=None, redirects=None, platform=None):
    ok = df[df['متاحة'] == True]  # noqa: E712
    codes = _code_series(df)
    not_found = codes.str.contains(r'خطأ 4(?:04|10)\b', na=False)
    deleted = codes.str.contains('محذوف', na=False)
    alt_counts = {}
    uimg = unique_images(images_df)
    if uimg is not None and not uimg.empty:
        alt_counts = uimg['حالة النص البديل'].value_counts().to_dict()
    s = {
        'total_pages': len(df),
        'score': round(ok['درجة السيو'].mean(), 1) if not ok.empty else 0.0,
        'products': int((ok['نوع الصفحة'] == T_PRODUCT).sum()),
        'categories': int((ok['نوع الصفحة'] == T_CATEGORY).sum()),
        'info_pages': int((ok['نوع الصفحة'] == T_INFO).sum()),
        'blog_pages': int((ok['نوع الصفحة'] == T_BLOG).sum()),
        'archive_pages': int((ok['نوع الصفحة'] == T_ARCHIVE).sum()),
        'unclassified': int((ok['نوع الصفحة'] == T_UNKNOWN).sum()),
        # روابط غير موجودة فعلاً (404/410)
        'broken_pages': int(((df['متاحة'] == False) & not_found).sum()),  # noqa: E712
        # روابط لا تعمل وليس لها إعادة توجيه (404/410 مباشرة)
        'broken_no_redirect': int(broken_no_redirect_mask(df).sum()),
        # تعذّر الوصول مؤقتاً (رفض، مهلة، خطأ خادم) — ليست محذوفة
        'unreachable_pages': int(((df['متاحة'] == False) & ~not_found & ~deleted).sum()),  # noqa: E712
        'bad_titles': int((~ok['حالة العنوان'].isin(['optimal'])).sum()),
        # ما يحتاج عملاً فعلاً (يطابق ملفات التحميل وكميات عرض السعر)
        'fix_titles_urls': int(title_url_fix_mask(df).sum()),
        'fix_descs': int(desc_fix_mask(df).sum()),
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
        'url_malformed': int((ok['جودة الرابط'] == 'u_malformed').sum())
        if 'جودة الرابط' in ok.columns else 0,
        'url_generic': int((ok['جودة الرابط'] == 'u_generic').sum())
        if 'جودة الرابط' in ok.columns else 0,
        'url_bad': int((~ok['جودة الرابط'].isin(['u_ok', 'u_na'])).sum())
        if 'جودة الرابط' in ok.columns else 0,
        'dup_content': int(ok['محتوى مكرر'].sum()) if 'محتوى مكرر' in ok.columns else 0,
        'canon_broken': int(df.attrs.get('canon_broken', 0)),
        'canon_missing': int((ok['حالة الكانونيكال'] == 'canon_missing').sum()),
        'canon_diff': int((ok['حالة الكانونيكال'] == 'canon_diff').sum()),
        'thin_pages': int((ok['حالة المحتوى'] == 'thin').sum()),
        'noindex_pages': int((~ok['قابلة للأرشفة'].fillna(True).astype(bool)).sum())
        if 'قابلة للأرشفة' in ok.columns else 0,
        'h1_mismatch': int((ok['مطابقة العنوان مع H1'] == 'match_diff').sum())
        if 'مطابقة العنوان مع H1' in ok.columns else 0,
        'deleted_pages': int(deleted.sum()),
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
            'visible_products': coverage.get('products_live', 0),
            'sitemap_products': coverage.get('sitemap_total', 0),
            'sitemap_live': coverage.get('sitemap_live', 0),
            'not_indexed_count': coverage.get('products_unlisted', 0),
            'dead_count': coverage.get('sitemap_dead', 0),
            'sitemap_unreachable': coverage.get('sitemap_unreachable', 0),
            'hidden_count': len(coverage.get('orphan_pages', [])),
            'scroll_only_count': len(coverage.get('scroll_only_products', [])),
            'unlisted_count': len(coverage.get('unlisted_pages', [])),
            'orphan_by_type': coverage.get('orphan_by_type', {}),
            'indexed_pct': coverage.get('indexed_pct', 100.0),
        })
    s.update(redirect_stats(redirects))
    s.update(broken_work_counts(df, platform or 'unknown'))
    return s


def localize_df(df, lang):
    if df is None or df.empty:
        return df
    out = df.copy()
    internal = [c for c in out.columns if str(c).startswith('_')]
    if internal:
        out = out.drop(columns=internal)
    labels = PAGE_TYPE_LABEL.get(lang, PAGE_TYPE_LABEL['ar'])
    for col in ('نوع الصفحة', 'نوع الرابط'):
        if col in out.columns:
            out[col] = out[col].map(lambda v: labels.get(v, v))
    statuses = STATUS_LABEL.get(lang, STATUS_LABEL['ar'])
    for col in ['حالة العنوان', 'حالة الوصف', 'حالة المحتوى', 'حالة النص البديل',
                'حالة الكانونيكال', 'مطابقة العنوان مع H1']:
        if col in out.columns:
            out[col] = out[col].map(lambda v: statuses.get(v, v))
    for col in ['جودة العنوان', 'جودة الوصف']:
        if col in out.columns:
            out[col] = out[col].map(lambda v: QUALITY_LABEL[lang].get(v, v))
    if 'جودة الرابط' in out.columns:
        out['جودة الرابط'] = out['جودة الرابط'].map(lambda v: URL_LABEL[lang].get(v, v))
    if 'النص البديل الحالي (Alt)' in out.columns:
        empty = statuses['alt_empty']
        out['النص البديل الحالي (Alt)'] = out['النص البديل الحالي (Alt)'].map(
            lambda v: v if str(v).strip() else empty)
    if lang == 'en':
        if 'الحالة' in out.columns:
            out['الحالة'] = out['الحالة'].map(lambda v: REDIRECT_STATUS_EN.get(v, v))
        if 'الإجراء المقترح' in out.columns:
            out['الإجراء المقترح'] = out['الإجراء المقترح'].map(
                lambda v: REDIRECT_ACTION_EN.get(v, BROKEN_ACTION_EN.get(v, v)))
        if 'ثقة الاقتراح' in out.columns:
            out['ثقة الاقتراح'] = out['ثقة الاقتراح'].map(
                lambda v: {CONF_HIGH: 'High', CONF_MED: 'Medium'}.get(v, v))
        if 'مصدر الاكتشاف' in out.columns:
            out['مصدر الاكتشاف'] = out['مصدر الاكتشاف'].map(lambda v: SOURCE_EN.get(v, v))
        for col in ('في الخريطة', 'مرتبط برابط'):
            if col in out.columns:
                out[col] = out[col].map(lambda v: {'نعم': 'Yes', 'لا': 'No'}.get(v, v))
        out = out.rename(columns={k: v for k, v in COL_EN.items() if k in out.columns})
    return out


def build_structured_report(df, declared_counts, cat_products=None):
    ok = df[df['متاحة'] == True]  # noqa: E712
    prod = ok[ok['نوع الصفحة'] == T_PRODUCT]
    n_found = len(prod)
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
#  تقرير الروابط المحوّلة وصفحات 404
# ==============================================================
R_PERM = 'تحويل دائم (301)'
R_TEMP = 'تحويل مؤقت (302)'
R_HOME = 'تحويل للرئيسية (منتج أو صفحة محذوفة/مخفية)'
R_404 = 'صفحة غير موجودة (404)'
R_410 = 'محذوفة نهائياً (410)'

REDIRECT_STATUS_EN = {
    R_PERM: 'Permanent redirect (301)', R_TEMP: 'Temporary redirect (302)',
    R_HOME: 'Redirects to homepage (deleted/hidden)',
    R_404: 'Not found (404)', R_410: 'Gone (410)',
}

A_UPDATE = 'حدّث الرابط في خريطة الموقع والروابط الداخلية ليشير إلى الوجهة مباشرة'
A_TEMP = 'إذا كان النقل دائماً فاجعل التحويل 301 بدل 302'
A_HOME = 'أعد تفعيل المنتج أو حوّله لأقرب منتج بديل، واحذف رابطه من الخريطة'
A_404 = 'أنشئ تحويل 301 لأقرب صفحة بديلة، واحذف الرابط من الخريطة والروابط الداخلية'
A_OK = 'لا إجراء عاجل — الرابط القديم غير معلن في الخريطة ولا مرتبط داخلياً'

REDIRECT_ACTION_EN = {
    A_UPDATE: 'Update sitemap and internal links to point straight to the destination',
    A_TEMP: 'If the move is permanent, use a 301 instead of a 302',
    A_HOME: 'Re-enable the product or redirect it to the closest alternative; remove it from the sitemap',
    A_404: 'Add a 301 to the closest alternative page; remove it from the sitemap and internal links',
    A_OK: 'No urgent action — old URL is neither in the sitemap nor linked internally',
}

SOURCE_EN = {'خريطة الموقع': 'Sitemap', 'زحف داخلي': 'Internal link',
             'التمرير اللانهائي والترقيم': 'Pagination / infinite scroll',
             'إعادة محاولة': 'Retry'}

REDIRECT_COLUMNS = ['الرابط الأصلي', 'الحالة', 'الوجهة النهائية', 'سلسلة التحويل',
                    'نوع الرابط', 'في الخريطة', 'مرتبط برابط', 'مصدر الاكتشاف',
                    'الإجراء المقترح']


def build_redirect_report(pages):
    """كل رابط حوّله المتجر أو أرجع 404/410، مع وجهته وسبب أهميته والإجراء المقترح.
    يُبنى من سجل الفحص قبل إزالة التكرار حتى لا تضيع الروابط القديمة."""
    rows, seen = [], set()
    for r in pages:
        code = str(r.get('كود الاستجابة') or '')
        req = r.get('_req_url') or r.get('_raw_url') or r.get('الرابط')
        final = r.get('الوجهة النهائية') or ''
        chain = r.get('سلسلة التحويل') or ''
        in_map = bool(r.get('_req_in_map', r.get('في الخريطة', False)))
        linked = bool(r.get('_req_linked', r.get('مرتبط برابط', False)))

        if DELETED_HOME in code:
            status, action = R_HOME, A_HOME
        elif re.search(r'خطأ 404\b', code):
            status, action = R_404, A_404
        elif re.search(r'خطأ 410\b', code):
            status, action = R_410, A_404
        elif r.get('متاحة') and final:
            first = chain.split(' → ')[0] if chain else '301'
            if first in ('302', '303', '307'):
                status, action = R_TEMP, A_TEMP
            else:
                status, action = R_PERM, A_UPDATE
        else:
            continue

        if status in (R_PERM, R_TEMP) and not in_map and not linked:
            action = A_OK

        k = url_key(req)
        if k in seen:
            continue
        seen.add(k)
        rows.append({
            'الرابط الأصلي': unquote(str(req)),
            'الحالة': status,
            'الوجهة النهائية': final,
            'سلسلة التحويل': chain,
            'نوع الرابط': r.get('نوع الرابط') or _detect_type_by_url(clean_url(str(req)), ''),
            'في الخريطة': 'نعم' if in_map else 'لا',
            'مرتبط برابط': 'نعم' if linked else 'لا',
            'مصدر الاكتشاف': r.get('مصدر الاكتشاف', ''),
            'الإجراء المقترح': action,
        })

    order = {R_404: 0, R_410: 0, R_HOME: 1, R_TEMP: 2, R_PERM: 3}
    rep = pd.DataFrame(rows, columns=REDIRECT_COLUMNS)
    if not rep.empty:
        rep = rep.assign(_o=rep['الحالة'].map(order),
                         _m=rep['في الخريطة'].map({'نعم': 0, 'لا': 1})) \
                 .sort_values(['_o', '_m', 'الرابط الأصلي']) \
                 .drop(columns=['_o', '_m']).reset_index(drop=True)
    return rep


BROKEN_COLUMNS = ['الرابط', 'نوع الرابط', 'كود الاستجابة', 'في الخريطة',
                  'مرتبط برابط', 'يظهر في', 'الوجهة المقترحة', 'ثقة الاقتراح',
                  'الإجراء المقترح', 'مصدر الاكتشاف']

CONF_HIGH, CONF_MED = 'عالية', 'متوسطة'
ACT_REDIRECT = 'تحويل 301 إلى الوجهة المقترحة'
ACT_REDIRECT_FIX = 'تحويل 301 إلى الوجهة المقترحة، وتصحيح الرابط الداخلي ليشير إليها مباشرة'
ACT_FIX_TO = 'تصحيح الرابط الداخلي ليشير إلى الوجهة المقترحة'
ACT_FIX_REMOVE = 'حذف الرابط الداخلي أو تغييره لصفحة مناسبة'
ACT_NONE = 'لا إجراء — الرد 404/410 صحيح لصفحة محذوفة بلا بديل'
REDIRECT_PLATFORMS = ('zid',)
BROKEN_ACTION_EN = {
    ACT_REDIRECT: '301 redirect to the suggested destination',
    ACT_REDIRECT_FIX: '301 redirect to the suggestion, and point the internal link straight to it',
    ACT_FIX_TO: 'Point the internal link to the suggested destination',
    ACT_FIX_REMOVE: 'Remove the internal link or point it to a relevant page',
    ACT_NONE: 'No action — 404/410 is correct for a deleted page with no alternative',
}   # المنصات التي نملك فيها طريقة مؤكدة لإنشاء التحويلات


def broken_no_redirect_mask(df):
    """روابط ترد مباشرة بأن الصفحة غير موجودة (404 أو 410) دون أي تحويل.
    لا تشمل: الروابط المحوّلة، ولا المحوّلة للرئيسية، ولا الرفض المؤقت (429/5xx)."""
    if df is None or df.empty or 'كود الاستجابة' not in df.columns:
        return pd.Series(False, index=getattr(df, 'index', None))
    codes = df['كود الاستجابة'].astype(str)
    chain = df['سلسلة التحويل'].fillna('').astype(str) if 'سلسلة التحويل' in df.columns \
        else pd.Series('', index=df.index)
    avail = df['متاحة'].fillna(False).astype(bool) if 'متاحة' in df.columns \
        else pd.Series(False, index=df.index)
    return (~avail) & codes.str.contains(r'خطأ 4(?:04|10)\b', na=False) & (chain.str.strip() == '')


def _truthy(v):
    return bool(v) and str(v) not in ('False', 'لا', 'nan', 'None', '0')


def where_label(key, referrers, ref_counts, total_pages):
    n = int(ref_counts.get(key, 0))
    if not n:
        return ''
    if n >= max(10, total_pages * 0.5):
        return f'القائمة أو التذييل (يظهر في {n} صفحة)'
    paths = [unquote(urlparse(u).path) or '/' for u in referrers.get(key, [])]
    more = f' (+{n - len(paths)})' if n > len(paths) else ''
    return ' | '.join(paths) + more


def _page_tokens(url, name='', title=''):
    toks = set(t for t in slug_tokens(slug_of(url)) if not t.isdigit())
    toks |= set(t for t in slug_tokens(name) if not t.isdigit())
    return toks


def suggest_alternatives(df):
    """لكل رابط معطل: أقرب صفحة حية بنفس الموضوع، أو لا شيء.
    لا نقترح الرئيسية ولا وجهة عامة: إن لم نجد تطابقاً حقيقياً نترك الخانة فارغة."""
    out = {}
    if df is None or df.empty:
        return out
    avail = df['متاحة'].fillna(False).astype(bool)
    live = df[avail & df['نوع الصفحة'].isin([T_PRODUCT, T_CATEGORY, T_BLOG, T_INFO])]
    if 'الوجهة النهائية' in live.columns:
        live = live[live['الوجهة النهائية'].fillna('').astype(str).str.strip() == '']
    if 'قابلة للأرشفة' in live.columns:
        live = live[live['قابلة للأرشفة'].fillna(True).astype(bool)]
    if live.empty:
        return out

    cands = []
    for _, r in live.iterrows():
        cands.append((r['الرابط'], r['نوع الصفحة'],
                      _page_tokens(r['الرابط'], r.get('اسم المنتج المعروض', ''))))
    # كلمات تتكرر في أكثر من ثلث الصفحات (اسم المتجر، «عباية» في متجر عبايات) لا تميّز شيئاً
    from collections import Counter
    df_count = Counter(t for _, _, toks in cands for t in toks)
    common = {t for t, c in df_count.items() if c > max(3, len(cands) * 0.33)}

    type_pref = {T_PRODUCT: (T_PRODUCT, T_CATEGORY), T_CATEGORY: (T_CATEGORY, T_PRODUCT),
                 T_BLOG: (T_BLOG,), T_INFO: (T_INFO,)}

    for idx, r in df[broken_no_redirect_mask(df)].iterrows():
        btype = r.get('نوع الرابط') or _detect_type_by_url(clean_url(str(r['الرابط'])), '')
        want = (_page_tokens(r['الرابط']) - common)
        if not want:
            continue
        allowed = type_pref.get(btype, (T_PRODUCT, T_CATEGORY, T_BLOG, T_INFO))
        best = None
        for url, ctype, toks in cands:
            if ctype not in allowed:
                continue
            hit = len(want & (toks - common))
            if not hit:
                continue
            score = hit / len(want)
            rank = (score, hit, -allowed.index(ctype))
            if best is None or rank > best[0]:
                best = (rank, url, hit, score, ctype)
        if not best:
            continue
        _, url, hit, score, ctype = best
        if hit >= 2 and score >= 0.75:
            conf = CONF_HIGH
        elif (hit >= 2 and score >= 0.5) or (len(want) == 1 and hit == 1 and ctype == T_CATEGORY):
            conf = CONF_MED
        else:
            continue
        out[idx] = (url, conf)
    return out


def annotate_broken_links(df, meta):
    """يضيف لصفوف الروابط المعطلة: أين تظهر، والوجهة المقترحة، ودرجة الثقة."""
    if df is None or df.empty:
        return df
    df = df.copy()
    for col in ('يظهر في', 'الوجهة المقترحة', 'ثقة الاقتراح'):
        if col not in df.columns:
            df[col] = ''
    mask = broken_no_redirect_mask(df)
    if not mask.any():
        return df
    refs = (meta or {}).get('referrers', {})
    counts = (meta or {}).get('ref_counts', {})
    total = int((meta or {}).get('pages_scanned', len(df)))
    for idx in df[mask].index:
        k = url_key(str(df.at[idx, '_req_url'] if '_req_url' in df.columns and
                        str(df.at[idx, '_req_url']) not in ('', 'nan', 'None')
                        else df.at[idx, 'الرابط']))
        df.at[idx, 'يظهر في'] = where_label(k, refs, counts, total)
    for idx, (url, conf) in suggest_alternatives(df).items():
        df.at[idx, 'الوجهة المقترحة'] = url
        df.at[idx, 'ثقة الاقتراح'] = conf
    return df


def broken_action(row, platform):
    has_alt = bool(str(row.get('الوجهة المقترحة') or '').strip())
    linked = _truthy(row.get('مرتبط برابط'))
    can_redirect = platform in REDIRECT_PLATFORMS
    if can_redirect and has_alt:
        return ACT_REDIRECT_FIX if linked else ACT_REDIRECT
    if linked:
        return ACT_FIX_TO if has_alt else ACT_FIX_REMOVE
    return ACT_NONE


def broken_work_counts(df, platform):
    """الكميات التي تدخل عرض السعر: ما يحتاج عملاً فعلاً فقط."""
    if df is None or df.empty:
        return {'redirect_qty': 0, 'internal_fix_qty': 0, 'broken_actionable': 0}
    sub = df[broken_no_redirect_mask(df)]
    redirect_qty = internal_qty = actionable = 0
    for _, r in sub.iterrows():
        act = broken_action(r, platform)
        if act in (ACT_REDIRECT, ACT_REDIRECT_FIX):
            redirect_qty += 1
        if _truthy(r.get('مرتبط برابط')):
            internal_qty += 1
        if act != ACT_NONE:
            actionable += 1
    return {'redirect_qty': redirect_qty, 'internal_fix_qty': internal_qty,
            'broken_actionable': actionable}


def build_broken_links(df, platform='unknown', actionable_only=False):
    """جدول الروابط التي لا تعمل وليس لها إعادة توجيه، مع مكانها والوجهة المقترحة والإجراء."""
    if df is None or df.empty:
        return pd.DataFrame(columns=BROKEN_COLUMNS)
    sub = df[broken_no_redirect_mask(df)].copy()
    if sub.empty:
        return pd.DataFrame(columns=BROKEN_COLUMNS)

    def col(name, default=''):
        return sub[name] if name in sub.columns else pd.Series(default, index=sub.index)

    out = pd.DataFrame({
        'الرابط': sub['الرابط'].astype(str),
        'نوع الرابط': col('نوع الرابط').where(col('نوع الرابط').astype(str).str.strip() != '',
                                              sub['الرابط'].map(lambda u: _detect_type_by_url(clean_url(str(u)), ''))),
        'كود الاستجابة': sub['كود الاستجابة'].astype(str).str.replace('خطأ ', '', regex=False),
        'في الخريطة': col('في الخريطة', False).map(lambda v: 'نعم' if _truthy(v) else 'لا'),
        'مرتبط برابط': col('مرتبط برابط', False).map(lambda v: 'نعم' if _truthy(v) else 'لا'),
        'يظهر في': col('يظهر في').fillna('').astype(str),
        'الوجهة المقترحة': col('الوجهة المقترحة').fillna('').astype(str),
        'ثقة الاقتراح': col('ثقة الاقتراح').fillna('').astype(str),
        'الإجراء المقترح': [broken_action(r, platform) for _, r in sub.iterrows()],
        'مصدر الاكتشاف': col('مصدر الاكتشاف'),
    })
    for c in ('يظهر في', 'الوجهة المقترحة', 'ثقة الاقتراح'):
        out[c] = out[c].replace({'nan': '', 'None': ''})
    if actionable_only:
        out = out[out['الإجراء المقترح'] != ACT_NONE]
    order = {ACT_REDIRECT_FIX: 0, ACT_REDIRECT: 1, ACT_FIX_TO: 2, ACT_FIX_REMOVE: 3, ACT_NONE: 4}
    out = out.assign(_o=out['الإجراء المقترح'].map(order)) \
             .sort_values(['_o', 'الرابط']).drop(columns=['_o']).reset_index(drop=True)
    return out[BROKEN_COLUMNS]


# ---------------- ملف التحويلات لزد ----------------
ZID_REDIRECT_COLUMNS = ['اسم إعادة التوجيه', 'التوجيه من', 'التوجيه إلى']


def _path_only(u):
    """المسار فقط، بلا https ولا اسم المتجر، كما تطلب زد."""
    p = unquote(urlparse(str(u)).path) or '/'
    return p if p.startswith('/') else '/' + p


def build_zid_redirects(df):
    """ملف تحويلات جاهز للاستيراد في زد، بعد تطبيق القواعد الصارمة:
    1) الرابط القديم يرد 404/410 فعلاً  2) الوجهة صفحة حية تفتح مباشرة
    3) لا سلاسل ولا دوائر  4) لا تكرار  5) مسارات بلا نطاق.
    يعيد (الجدول، قائمة بالمستبعد وسببه)."""
    empty = pd.DataFrame(columns=ZID_REDIRECT_COLUMNS)
    if df is None or df.empty:
        return empty, []
    live_keys = set()
    avail = df['متاحة'].fillna(False).astype(bool)
    for _, r in df[avail].iterrows():
        if not str(r.get('الوجهة النهائية') or '').strip():
            live_keys.add(url_key(r['الرابط']))
    rows, skipped, seen_from = [], [], set()
    sub = df[broken_no_redirect_mask(df)]
    from_paths = {_path_only(u) for u in sub['الرابط']}
    for _, r in sub.iterrows():
        dest = str(r.get('الوجهة المقترحة') or '').strip()
        if not dest or dest in ('nan', 'None'):
            continue
        src_p, dst_p = _path_only(r['الرابط']), _path_only(dest)
        if url_key(dest) not in live_keys:
            skipped.append((r['الرابط'], 'الوجهة المقترحة لا تفتح مباشرة'))
            continue
        if src_p == dst_p or dst_p in from_paths:
            skipped.append((r['الرابط'], 'تحويل دائري أو سلسلة تحويلات'))
            continue
        if src_p in seen_from:
            skipped.append((r['الرابط'], 'مكرر'))
            continue
        seen_from.add(src_p)
        rows.append({'اسم إعادة التوجيه': f'seo-{len(rows) + 1}',
                     'التوجيه من': src_p, 'التوجيه إلى': dst_p})
    return (pd.DataFrame(rows, columns=ZID_REDIRECT_COLUMNS) if rows else empty), skipped


def verify_redirects(base_url, pairs, workers=3):
    """بعد رفع الملف في زد: يفتح كل رابط قديم ويتأكد أنه يحوّل بـ 301 للوجهة الصحيحة."""
    base_url = normalize_url(base_url)

    def one(pair):
        src, dst = pair
        res = safe_get(base_url + src, timeout=15, retries=1)
        if res is None:
            return src, dst, 'تعذّر الاتصال', False
        chain = [h.status_code for h in res.history]
        if not chain:
            return src, dst, (f'لا يحوّل — الرابط يرد {res.status_code}'
                              if res.status_code != 200 else 'لا يحوّل — الرابط ما زال يفتح صفحة'), False
        if url_key(clean_url(res.url)) != url_key(base_url + dst):
            return src, dst, 'يحوّل لوجهة مختلفة', False
        if res.status_code != 200:
            return src, dst, f'الوجهة لا تعمل ({res.status_code})', False
        if chain[0] != 301:
            return src, dst, f'التحويل من نوع {chain[0]} وليس 301', False
        if len(chain) > 1:
            return src, dst, 'يمر بأكثر من تحويل قبل الوصول', False
        return src, dst, 'يعمل (301)', True

    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        results = list(ex.map(one, list(pairs)))
    return pd.DataFrame(results, columns=['التوجيه من', 'التوجيه إلى', 'النتيجة', 'ناجح'])


def redirect_stats(rep):
    if rep is None or rep.empty:
        return {'redirects_permanent': 0, 'redirects_temporary': 0, 'redirects_home': 0,
                'not_found_pages': 0, 'redirects_in_sitemap': 0, 'redirects_total': 0}
    st = rep['الحالة']
    return {
        'redirects_permanent': int((st == R_PERM).sum()),
        'redirects_temporary': int((st == R_TEMP).sum()),
        'redirects_home': int((st == R_HOME).sum()),
        'not_found_pages': int(st.isin([R_404, R_410]).sum()),
        'redirects_in_sitemap': int((rep['في الخريطة'] == 'نعم').sum()),
        'redirects_total': int(len(rep)),
    }


def redirect_report_csv(rep, lang='ar'):
    """ملف CSV جاهز للتحميل أو لإضافته إلى حزمة التصدير."""
    if rep is None or rep.empty:
        return b''
    out = localize_df(rep, lang)
    out.insert(0, 'م' if lang == 'ar' else '#', range(1, len(out) + 1))
    return out.to_csv(index=False).encode('utf-8-sig')


# ==============================================================
#  الفحص الذاتي
# ==============================================================
CHECK_FAIL, CHECK_WARN, CHECK_PASS = 'fail', 'warn', 'pass'


def run_self_checks(df, images_df, coverage, platform, summary, crawl_meta=None,
                    structured=None):
    checks = []

    def add(level, title, msg, action=""):
        checks.append({'level': level, 'title': title, 'msg': msg, 'action': action})

    ok = df[df['متاحة'] == True] if not df.empty else df  # noqa: E712
    n_ok = len(ok)
    uimg = unique_images(images_df)
    n_img = 0 if uimg is None or uimg.empty else len(uimg)

    if platform in SUPPORTED_PLATFORMS:
        add(CHECK_PASS, "منصة المتجر", f"تم التعرف على المنصة: {PLATFORM_LABEL[platform]}.")
    else:
        known = PLATFORM_LABEL.get(platform, 'غير معروفة')
        add(CHECK_WARN, "منصة المتجر",
            f"المنصة ({known}) خارج المنصات المعتمدة مباشرة. الفحوص التالية تحدد مدى الموثوقية.",
            "راجع عينة التحقق اليدوي.")

    sm = (crawl_meta or {}).get('sitemap_report') or {}
    if sm:
        if sm.get('total_urls', 0) == 0:
            add(CHECK_WARN, "خريطة الموقع", "لم يُعثر على خريطة موقع صالحة.",
                "افتح خريطة الموقع في متصفحك واحفظها، ثم ارفعها في خيارات خريطة الموقع وأعد الفحص.")
        elif sm.get('partial'):
            reasons = {}
            for f in sm.get('failed', []):
                reasons[f['السبب']] = reasons.get(f['السبب'], 0) + 1
            why = '، '.join(f"{n} بسبب: {r}" for r, n in reasons.items())
            add(CHECK_WARN, "خريطة الموقع",
                f"قُرئ {sm.get('files_ok', 0)} ملف خريطة وتعذّر {sm.get('files_failed', 0)} ({why}).",
                "افتح الملفات المذكورة في متصفحك واحفظها، ثم ارفعها في خيارات خريطة الموقع وأعد الفحص.")
        else:
            up = f" منها {sm['uploaded']} مرفوعة يدوياً" if sm.get('uploaded') else ''
            add(CHECK_PASS, "خريطة الموقع",
                f"قُرئت كل ملفات الخريطة ({sm.get('files_ok', 0)} ملف{up}، {sm.get('total_urls', 0)} رابط).")

    if crawl_meta and 'pagination_reason' in crawl_meta:
        if crawl_meta.get('pagination_ran'):
            add(CHECK_PASS, "متابعة الترقيم والتمرير",
                f"شُغّلت لأن {crawl_meta['pagination_reason']}.")
        else:
            add(CHECK_PASS, "متابعة الترقيم والتمرير",
                f"لم تُشغَّل لأن {crawl_meta['pagination_reason']} — وهذا وفّر وقت الفحص.")

    if n_ok == 0:
        add(CHECK_FAIL, "حجم الزحف", "لم تُفحص أي صفحة بنجاح.",
            "تحقق من أن الرابط يعمل وأن المتجر لا يفرض حظراً كاملاً.")
    elif n_ok < 5:
        add(CHECK_FAIL, "حجم الزحف", f"{n_ok} صفحة فقط — رقم صغير لمتجر إلكتروني.")
    else:
        add(CHECK_PASS, "حجم الزحف", f"{n_ok} صفحة مفحوصة بنجاح.")

    unreach = summary.get('unreachable_pages', 0)
    total_try = n_ok + unreach
    if total_try:
        pct = round(n_ok / total_try * 100, 1)
        if pct < 85:
            add(CHECK_FAIL, "اكتمال الفحص", f"نجح فحص {pct}% فقط من الصفحات ({unreach} تعذّر الوصول لها).",
                "خفّض عدد المسارات المتوازية وأعد الفحص.")
        elif pct < 97:
            add(CHECK_WARN, "اكتمال الفحص", f"نجح فحص {pct}% من الصفحات ({unreach} تعذّر الوصول لها).")
        else:
            add(CHECK_PASS, "اكتمال الفحص", f"نجح فحص {pct}% من الصفحات.")

    n_prod = summary.get('products', 0)
    if n_ok >= 2 and n_prod == 0:
        add(CHECK_FAIL, "اكتشاف المنتجات", "لم يُعثر على صفحات منتجات.",
            "تأكد من تفعيل خريطة الموقع أو مراجعة بنية القالب والتمرير اللانهائي.")
    elif n_prod:
        add(CHECK_PASS, "اكتشاف المنتجات", f"{n_prod} صفحة منتج مكتشفة.")

    if n_ok:
        ratio = summary.get('unclassified', 0) / n_ok * 100
        if ratio > 25:
            add(CHECK_FAIL, "دقة التصنيف", f"{round(ratio, 1)}% من الصفحات لم تُصنّف آلياً.")
        elif ratio > 10:
            add(CHECK_WARN, "دقة التصنيف", f"{round(ratio, 1)}% من الصفحات غير مصنّفة.")
        else:
            add(CHECK_PASS, "دقة التصنيف", f"{round(ratio, 1)}% فقط غير مصنّفة.")

    prod_pages = ok[ok['نوع الصفحة'] == T_PRODUCT] if n_ok else ok
    if len(prod_pages) >= 3:
        with_imgs = int((prod_pages['إجمالي الصور'] > 0).sum())
        pct = with_imgs / len(prod_pages) * 100
        if pct == 0:
            add(CHECK_FAIL, "رصد صور المنتجات", "لم تُرصد صور على صفحات المنتجات.")
        elif pct < 60:
            add(CHECK_WARN, "رصد صور المنتجات", f"{round(pct, 1)}% فقط من المنتجات تحوي صوراً مرصودة.")
        else:
            add(CHECK_PASS, "رصد صور المنتجات", f"{round(pct, 1)}% من المنتجات تحوي صوراً مرصودة ({n_img} صورة فريدة).")

    fails = sum(1 for c in checks if c['level'] == CHECK_FAIL)
    warns = sum(1 for c in checks if c['level'] == CHECK_WARN)
    verdict = ('blocked' if fails else 'review' if warns else 'ready')
    return {'checks': checks, 'fails': fails, 'warns': warns, 'verdict': verdict}


# ==============================================================
#  محرك الاكتشاف والفحص الشامل
# ==============================================================
def probe_seeds(urls, base_url, workers=4):
    """المسارات المخمّنة (/offers و /brands ...) تُضاف فقط إذا كانت موجودة فعلاً،
    حتى لا تظهر للعميل كروابط معطلة وهي ليست في متجره أصلاً."""
    home_key = url_key(base_url)

    def one(u):
        r = safe_get(u, timeout=10, retries=0)
        if is_ok(r) and 'html' in (r.headers.get('Content-Type') or 'html').lower() \
                and url_key(clean_url(r.url)) != home_key:
            return u
        return None

    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        return {u for u in ex.map(one, list(urls)) if u}


def _retryable(code):
    code = str(code or '')
    return ('فشل اتصال' in code or 'خطأ 429' in code or 'خطأ 403' in code
            or bool(re.search(r'خطأ 5\d\d', code)))


def discover_and_audit(base_url, max_pages=MAX_PAGES_DEFAULT, workers=4, progress=None,
                       sitemap_uploads=None, sitemap_inputs=None):
    base_url = normalize_url(base_url)
    if progress:
        progress('sitemap_read')

    # 1. كشف المنصة عبر الصفحة الرئيسية
    home_res = safe_get(base_url)
    platform = 'unknown'
    if is_ok(home_res):
        platform = detect_platform(home_res.text, dict(home_res.headers), base_url)

    # 2. قراءة كل خرائط الموقع (مع الملفات والروابط التي أعطاها المستخدم)
    collector = SitemapCollector(base_url).run(sitemap_uploads, sitemap_inputs)
    sitemap_urls, sm_report = collector.urls(), collector.final_report()
    sitemap_keys = {url_key(u) for u in sitemap_urls}

    # 3. الروابط المبدئية
    initial = {base_url: None}
    for u in sitemap_urls:
        initial.setdefault(u, None)
    if platform == 'shopify':
        for u in harvest_shopify_all(base_url):
            initial.setdefault(u, None)
    elif platform == 'zid':
        for u in harvest_zid_catalog(base_url):
            initial.setdefault(u, None)
    for u in probe_seeds([f"{base_url}/{p}" for p in PLATFORM_LISTINGS], base_url, workers):
        initial.setdefault(u, None)

    base_netloc = urlparse(base_url).netloc
    queue, seen = [], set()
    for u in initial:
        cu = clean_url(u)
        k = url_key(cu)
        if k not in seen and is_crawlable(cu, base_netloc):
            seen.add(k)
            queue.append(cu)

    linked = set()
    referrers = {}          # مفتاح الرابط ← الصفحات التي يظهر فيها (عيّنة)
    ref_counts = {}         # مفتاح الرابط ← عدد الصفحات التي يظهر فيها
    cat_links = {}
    next_hints = {}
    scroll_roots = set()
    pages, images = [], []
    step = 0

    # 4. دورة الزحف
    with ThreadPoolExecutor(max_workers=workers) as ex:
        while queue and len(pages) < max_pages:
            step += 1
            batch_size = min(workers * 4, max_pages - len(pages), len(queue))
            batch, queue = queue[:batch_size], queue[batch_size:]
            tasks = [(u, base_url, 'خريطة الموقع' if url_key(u) in sitemap_keys else 'زحف داخلي')
                     for u in batch]

            for res in ex.map(fetch_and_audit, tasks):
                row = res['page_data']
                pages.append(row)
                images.extend(res['images_data'])

                if res.get('platform_html') and platform == 'unknown':
                    platform = detect_platform(res['platform_html'], res.get('platform_headers'), base_url)
                    if platform == 'shopify':
                        for su in harvest_shopify_all(base_url):
                            k = url_key(su)
                            if k not in seen:
                                seen.add(k)
                                queue.append(su)

                raw = row.get('_raw_url', row['الرابط'])
                if row['نوع الصفحة'] in (T_CATEGORY, T_HOME):
                    cat_links.setdefault(raw, set()).update(res.get('product_links', set()))
                if res.get('next_pages'):
                    next_hints.setdefault(raw, set()).update(res['next_pages'])
                if res.get('scroll_marker'):
                    scroll_roots.add(raw)

                # الوجهة الجديدة لرابط محوّل تُعتبر مكتشفة
                seen.add(url_key(raw))

                src_page = row['الرابط']
                for link in res.get('links', ()):
                    k = url_key(link)
                    linked.add(k)
                    ref_counts[k] = ref_counts.get(k, 0) + 1
                    lst = referrers.setdefault(k, [])
                    if len(lst) < 3 and src_page not in lst:
                        lst.append(src_page)
                    if k not in seen:
                        seen.add(k)
                        queue.append(link)

            if progress:
                progress('audit', done=len(pages), pending=len(queue), round=step)

    truncated = len(pages) >= max_pages and bool(queue)

    for row in pages:
        k_req = url_key(row.get('_req_url') or row.get('_raw_url') or row['الرابط'])
        k_fin = url_key(row.get('_raw_url') or row['الرابط'])
        row['_req_in_map'] = k_req in sitemap_keys
        row['_req_linked'] = k_req in linked
        row['في الخريطة'] = k_req in sitemap_keys or k_fin in sitemap_keys
        row['مرتبط برابط'] = k_req in linked or k_fin in linked

    from collections import Counter
    meta = {
        'source_counts': dict(Counter(r.get('مصدر الاكتشاف', '—') for r in pages)),
        'truncated': truncated,
        'pending': len(queue),
        'rounds': step,
        'cat_products': cat_links,
        'next_hints': {k: sorted(v) for k, v in next_hints.items()},
        'scroll_roots': sorted(scroll_roots),
        'sitemap_count': len(sitemap_keys),
        'sitemap_keys': sitemap_keys,
        'sitemap_urls': sitemap_urls,
        'sitemap_report': sm_report,
        'linked_keys': linked,
        'referrers': referrers,
        'ref_counts': ref_counts,
        'pages_scanned': len(pages),
        'collector': collector,
        'listing_urls': [r.get('_raw_url', r['الرابط']) for r in pages
                         if r['نوع الصفحة'] in (T_CATEGORY, T_HOME, T_BLOG, T_ARCHIVE)],
    }
    return pages, images, meta, platform


def build_sitemap_report(df, base_url, sm_report=None):
    if df.empty or 'في الخريطة' not in df.columns:
        return None
    in_map = df['في الخريطة'] == True                      # noqa: E712
    alive = df['متاحة'] == True                            # noqa: E712
    linked = df['مرتبط برابط'] == True                     # noqa: E712
    codes = _code_series(df)
    gone = codes.str.contains(r'خطأ 4(?:04|10)\b|محذوف', na=False)

    def rows(mask, extra=None):
        out = []
        for _, r in df[mask].iterrows():
            item = {'الرابط': str(r['الرابط']), 'نوع الصفحة': str(r['نوع الصفحة'])}
            if extra:
                item[extra] = str(r['كود الاستجابة'])
            out.append(item)
        return out

    is_prod = df['نوع الصفحة'] == T_PRODUCT
    is_content = df['نوع الصفحة'].isin(CONTENT_TYPES)
    dead = rows(in_map & ~alive & gone, 'كود الاستجابة')
    unreachable_n = int((in_map & ~alive & ~gone).sum())
    orphan = rows(in_map & alive & ~linked & ~is_prod)
    scroll_only = rows(in_map & alive & ~linked & is_prod)
    unlisted = rows(~in_map & alive & is_content)
    live_in_map = int((in_map & alive).sum())
    prod_live = int((alive & is_prod).sum())
    prod_unlisted = int((~in_map & alive & is_prod).sum())
    partial = bool((sm_report or {}).get('partial'))

    orphan_counts = {
        str(k): int(v)
        for k, v in df[in_map & alive & ~linked & ~is_prod]['نوع الصفحة'].value_counts().items()
    }

    return {
        'partial_read': partial,
        'files_failed': int((sm_report or {}).get('files_failed', 0)),
        'files_ok': int((sm_report or {}).get('files_ok', 0)),
        'sitemap_total': int(in_map.sum()),
        'sitemap_live': live_in_map,
        'sitemap_dead': len(dead),
        'sitemap_unreachable': unreachable_n,
        'orphan_pages': orphan,
        'scroll_only_products': scroll_only,
        'dead_pages': dead,
        'unlisted_pages': [] if partial else unlisted,
        'unlisted_suppressed': len(unlisted) if partial else 0,
        'products_live': prod_live,
        'products_unlisted': prod_unlisted,
        'indexed_pct': float(round((prod_live - prod_unlisted) / prod_live * 100, 1))
        if prod_live else 100.0,
        'orphan_by_type': orphan_counts,
    }


# ==============================================================
#  نقطة الدخول الرئيسية للفحص الكامل
# ==============================================================
def pagination_needed(pages, sm_report):
    """الخطوة البطيئة (الترقيم والتمرير) لا تعمل إلا إذا كانت الخريطة ناقصة.
    يعيد (هل نحتاجها، السبب)."""
    rep = sm_report or {}
    if not rep.get('total_urls'):
        return True, 'لم تُقرأ أي خريطة موقع'
    if rep.get('partial'):
        return True, f"تعذّرت قراءة {rep.get('files_failed', 0)} ملف من الخريطة"
    known_products = {url_key(r.get('_raw_url') or r['الرابط']) for r in pages
                      if r.get('متاحة') and r.get('نوع الصفحة') == T_PRODUCT}
    declared = []
    for r in pages:
        if r.get('نوع الصفحة') in (T_CATEGORY, T_HOME):
            try:
                v = int(r.get('عدد معلن') or 0)
            except (TypeError, ValueError):
                v = 0
            if v:
                declared.append(v)
    if declared and max(declared) > len(known_products):
        return True, (f"قسم يعلن {max(declared)} منتجاً والأداة تعرف "
                      f"{len(known_products)} فقط")
    if not known_products:
        return True, 'الخريطة لا تحتوي صفحات منتجات'
    return False, 'الخريطة مكتملة وتحتوي كل المنتجات'


def run_full_scan(target, max_pages=MAX_PAGES_DEFAULT, workers=4,
                  do_pagination=True, do_sitemap_check=True, progress=None,
                  sitemap_uploads=None, sitemap_inputs=None):
    def say(stage, **kw):
        if progress:
            try:
                progress(stage, **kw)
            except Exception:
                pass

    target = normalize_url(target)
    reset_throttle()

    say('discover_start')
    pages, imgs, crawl_meta, platform = discover_and_audit(
        target, max_pages, workers, (lambda st, **k: say(st, **k)),
        sitemap_uploads=sitemap_uploads, sitemap_inputs=sitemap_inputs)
    cat_products = crawl_meta.setdefault('cat_products', {})
    sitemap_keys = crawl_meta.get('sitemap_keys', set())
    linked_keys = crawl_meta.get('linked_keys', set())
    collector = crawl_meta.get('collector')

    # جولة ثانية هادئة لملفات الخريطة التي فشلت، بعد أن هدأ المتجر
    if collector is not None and collector.failed:
        say('sitemap_retry', count=len(collector.failed))
        new_urls = collector.retry_failed()
        crawl_meta['sitemap_report'] = collector.final_report()
        if new_urls:
            sitemap_keys |= {url_key(u) for u in new_urls}
            crawl_meta['sitemap_count'] = len(sitemap_keys)
            known = set()
            for r in pages:
                known.add(url_key(r.get('_raw_url') or r['الرابط']))
                known.add(url_key(r.get('_req_url') or r['الرابط']))
            fresh = [u for u in new_urls if url_key(u) not in known][:max(0, max_pages - len(pages))]
            if fresh:
                p3, i3 = audit_urls(fresh, target, 'خريطة الموقع', workers, None)
                for r in p3:
                    r['مرتبط برابط'] = url_key(r.get('_raw_url') or r['الرابط']) in linked_keys
                    r['_req_linked'] = url_key(r.get('_req_url') or r['الرابط']) in linked_keys
                pages += p3
                imgs += i3
            for r in pages:
                k_req = url_key(r.get('_req_url') or r.get('_raw_url') or r['الرابط'])
                k_fin = url_key(r.get('_raw_url') or r['الرابط'])
                r['_req_in_map'] = k_req in sitemap_keys
                r['في الخريطة'] = k_req in sitemap_keys or k_fin in sitemap_keys

    # الخطوة البطيئة (الترقيم والتمرير) فقط عندما تكون الخريطة ناقصة
    need_paging, paging_reason = pagination_needed(pages, crawl_meta.get('sitemap_report'))
    crawl_meta['pagination_ran'] = bool(do_pagination and need_paging)
    crawl_meta['pagination_reason'] = paging_reason
    if need_paging and not do_pagination:
        crawl_meta['pagination_reason'] = 'الخيار موقوف من إعدادات الفحص'
    if not need_paging:
        say('pagination_skipped', reason=paging_reason)

    # الترقيم والتمرير اللانهائي
    if do_pagination and need_paging:
        say('pagination_start')
        seen_keys = set()
        for r in pages:
            seen_keys.add(url_key(r.get('_raw_url', r['الرابط'])))
            seen_keys.add(url_key(r.get('_req_url') or r['الرابط']))
        listing_roots = list(cat_products.keys()) + list(crawl_meta.get('listing_urls', []))

        extra = harvest_paginated_products(
            target, list(dict.fromkeys(listing_roots)), seen_keys,
            (lambda i, tot, f, fe: say('pagination', i=i, total=tot, found=f, fetched=fe)),
            cat_products=cat_products, listing_urls=None,
            next_hints=crawl_meta.get('next_hints'),
            scroll_roots=crawl_meta.get('scroll_roots'))
        extra = extra[:max(0, max_pages - len(pages))]
        if extra:
            say('extra_start', count=len(extra))
            p2, i2 = audit_urls(extra, target, 'التمرير اللانهائي والترقيم', workers, None)
            for r in p2:
                k_req = url_key(r.get('_req_url') or r['الرابط'])
                k_fin = url_key(r.get('_raw_url') or r['الرابط'])
                r['_req_in_map'] = k_req in sitemap_keys
                r['_req_linked'] = True
                r['في الخريطة'] = k_req in sitemap_keys or k_fin in sitemap_keys
                r['مرتبط برابط'] = True
            pages += p2
            imgs += i2

    # إعادة هادئة للصفحات التي رفضها المتجر مؤقتاً (429 / 5xx / انقطاع)
    retry = [r.get('_req_url') or r['_raw_url'] for r in pages
             if not r['متاحة'] and _retryable(r['كود الاستجابة'])]
    if retry:
        say('retry_start', count=len(retry))
        time.sleep(3)
        fixed, fixed_imgs = audit_urls(retry[:300], target, 'إعادة محاولة', 2, None)
        good = {r['_req_url']: r for r in fixed if r['متاحة'] or not _retryable(r['كود الاستجابة'])}
        if good:
            merged = []
            for r in pages:
                g = good.get(r.get('_req_url') or r['_raw_url'])
                if g and not r['متاحة']:
                    g = dict(g)
                    for f in ('في الخريطة', 'مرتبط برابط', 'مصدر الاكتشاف', '_req_in_map', '_req_linked'):
                        g[f] = r.get(f, g.get(f))
                    merged.append(g)
                else:
                    merged.append(r)
            pages = merged
            good_final = {g['الرابط'] for g in good.values() if g['متاحة']}
            imgs += [im for im in fixed_imgs if im['رابط الصفحة'] in good_final]

    # استبعاد روابط الوسوم نهائياً
    pages = [r for r in pages if not is_tag_url(r.get('_raw_url', r.get('الرابط', '')))]

    # تقرير التحويلات و404 يُبنى قبل إزالة التكرار حتى لا تضيع الروابط القديمة
    redirects = build_redirect_report(pages)

    df = dedupe_pages(pd.DataFrame(pages))
    images_df = pd.DataFrame(imgs)
    if not images_df.empty:
        images_df = images_df[images_df['رابط الصفحة'].isin(df['الرابط'])].copy().reset_index(drop=True)
        images_df = apply_duplicate_alt(images_df)
    df, brand = analyze_text_quality(df)
    df = analyze_url_quality(df, brand)
    df, dup_groups = detect_duplicate_content(df)
    df = score_pages(df, images_df)
    df = annotate_broken_links(df, crawl_meta)

    coverage = (build_sitemap_report(df, target, crawl_meta.get('sitemap_report'))
                if do_sitemap_check else None)
    if coverage is not None:
        coverage['redirects'] = redirect_stats(redirects)

    declared = {}
    for _, r in df.iterrows():
        v = r.get('عدد معلن')
        try:
            if v is not None and pd.notna(v) and int(v) > 0:
                declared[r['الرابط']] = int(v)
        except (TypeError, ValueError):
            continue
    structured = build_structured_report(df, declared, cat_products)

    summary = compute_summary(df, coverage, images_df, redirects, platform)
    summary['structured'] = structured
    summary['platform'] = platform
    summary['platform_label'] = PLATFORM_LABEL.get(platform, '—')
    selfcheck = run_self_checks(df, images_df, coverage, platform, summary, crawl_meta, structured)
    say('done')

    # حذف البيانات الثقيلة غير القابلة للحفظ من سجل الزحف
    for k in ('sitemap_keys', 'linked_keys', 'collector', 'referrers', 'ref_counts'):
        crawl_meta.pop(k, None)

    return {'df': df, 'images_df': images_df, 'summary': summary,
            'coverage': coverage, 'structured': structured,
            'selfcheck': selfcheck, 'brand': brand, 'dup_groups': dup_groups,
            'platform': platform, 'crawl_meta': crawl_meta,
            'declared': declared, 'redirect_report': redirects}
