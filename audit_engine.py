
import gzip
import json
import re
import threading
import time
from functools import lru_cache
from urllib.parse import clean_url as _clean, unquote, urljoin, urlparse
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

from bs4 import BeautifulSoup
import pandas as pd
import requests

try:
    import lxml  # noqa: F401
    PARSER = "lxml"
except Exception:
    PARSER = "html.parser"

try:
    from usp.tree import sitemap_tree_for_homepage as _usp_tree
    HAS_USP = True
except Exception:
    HAS_USP = False

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
PAGE_TYPE_ORDER = [T_HOME, T_PRODUCT, T_CATEGORY, T_BLOG, T_INFO, T_ARCHIVE, T_UNKNOWN, T_BROKEN]

TITLE_MAX, TITLE_MIN_OPTIMAL, TITLE_MIN_OK = 60, 50, 30
DESC_MAX, DESC_MIN_OPTIMAL, DESC_MIN_OK = 150, 120, 70
ALT_MAX = 125
ALT_DUP_THRESHOLD = 3

PLATFORM_LABEL = {
    'salla': 'سلة (Salla)', 'zid': 'زد (Zid)',
    'shopify': 'شوبيفاي (Shopify)', 'rmz': 'رمز (rmz.gg)',
    'woocommerce': 'ووكومرس', 'unknown': 'غير معروفة'
}
PLATFORM_LABEL_EN = {
    'salla': 'Salla', 'zid': 'Zid', 'shopify': 'Shopify',
    'rmz': 'rmz.gg', 'woocommerce': 'WooCommerce',
    'unknown': 'Unidentified'
}
SUPPORTED_PLATFORMS = ('salla', 'zid', 'shopify')

MODERN_FORMATS = ('webp', 'avif')

_THROTTLE = {'fails': 0, 'delay': 0.0}
_TL = threading.local()


def note_failure():
    _THROTTLE['fails'] += 1
    if _THROTTLE['fails'] in (5, 15, 40):
        _THROTTLE['delay'] = min(_THROTTLE['delay'] + 0.25, 1.0)


def reset_throttle():
    _THROTTLE['fails'] = 0
    _THROTTLE['delay'] = 0.0


def _session():
    sess = getattr(_TL, 'sess', None)
    if sess is None:
        sess = requests.Session()
        adapter = requests.adapters.HTTPAdapter(pool_connections=8, pool_maxsize=16, max_retries=0)
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
                time.sleep(2 * (attempt + 1))
                continue
            return res
        except Exception:
            time.sleep(1)
    return None


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


@lru_cache(maxsize=100000)
def url_key(url):
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
        GENERIC_ALT_NORM = {normalize_ar_token(w) if re.search(r'[\u0600-\u06FF]', w) else w for w in GENERIC_ALT}
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
    words = [normalize_ar_token(w) if re.search(r'[\u0600-\u06FF]', w) else w for w in words if w]
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
        mask = (df['حالة النص البديل'] == 'alt_ok') & df['النص البديل الحالي (Alt)'].isin(dupes)
        df.loc[mask, 'حالة النص البديل'] = 'alt_duplicate'
    return df


def unique_images(images_df):
    if images_df is None or images_df.empty:
        return images_df
    counts = images_df.groupby('رابط الصورة')['رابط الصفحة'].nunique()
    out = images_df.drop_duplicates(subset=['رابط الصورة']).copy()
    out['عدد الصفحات'] = out['رابط الصورة'].map(counts)
    return out.reset_index(drop=True)


def detect_platform(html, headers=None, url=""):
    h = (html or "")[:200000].lower()
    hdr = " ".join(f"{k}:{v}" for k, v in (headers or {}).items()).lower()
    blob = h + " " + hdr + " " + (url or "").lower()
    if any(s in blob for s in ['salla.sa', 'cdn.salla.network', 'window.salla', 'salla-']):
        return 'salla'
    if any(s in blob for s in ['zid.store', 'media.zid.sa', 'zidapi', 'x-zid', 'cdn.zid']):
        return 'zid'
    if any(s in blob for s in ['cdn.shopify.com', 'myshopify.com', 'shopify.theme', 'x-shopify', 'shopify-features']):
        return 'shopify'
    if any(s in blob for s in ['cdn.rmz.gg', 'rmz.gg/store', 'matjrah']):
        return 'rmz'
    if any(s in blob for s in ['woocommerce', 'wp-content/plugins/woo']):
        return 'woocommerce'
    return 'unknown'


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


@lru_cache(maxsize=60000)
def _detect_type_by_url(url, base_url):
    return detect_page_type(url, base_url, None)


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

    if any(segment_is_policy(seg) for seg in segments if seg not in BLOG_SEGMENTS):
        return T_INFO

    if segments:
        last = segments[-1]
        if re.match(r'^(tag|author|category|archive)-?\d*$', last) or re.match(r'^\d{4}$', last):
            return T_ARCHIVE
        if re.match(r'^c-?\d{4,}$', last) and any(x in BLOG_SEGMENTS for x in segments[:-1]):
            return T_ARCHIVE
        if len(segments) >= 2 and any(x in ('tag', 'tags', 'author', 'authors', 'archive', 'وسم', 'وسوم') for x in segments[:-1]):
            return T_ARCHIVE

    if 'article' in og_type or 'blog' in og_type:
        return T_BLOG
    if soup and soup.find(attrs={'itemtype': re.compile(r'schema\.org/(Article|BlogPosting|NewsArticle)', re.I)}):
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


JUNK_KEYWORDS = [
    'spinner', 'loader', 'loading', 'ajax', 'icon', 'badge', 'payment', 'gateway',
    'tamara', 'tabby', 'mada', 'visa', 'mastercard', 'apple-pay', 'applepay',
    'stc-pay', 'stcpay', 'vat', 'tax', 'maroof', 'social', 'whatsapp', 'snapchat',
    'instagram', 'tiktok', 'twitter', 'pixel', 'spacer', 'avatar', 'arrow',
    'placeholder', 'blank',
    'zidship', 'aramex', 'smsa', 'redbox', 'naqel', 'servicelevel', 'courier',
    'shipment', 'shipping-company', 'carrier', 'fastlo', 'imile',
    's-empty', 'empty.png', 'lazy.png', 'transparent', 'dummy', '1x1',
]


def get_image_src(img):
    for attr in ['data-src', 'data-original', 'data-lazy', 'data-lazy-src', 'data-image', 'data-large_image']:
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
    body = soup.body or soup
    total = len(body.get_text(' ', strip=True))

    targets = soup.select(
        'header, nav, footer, aside, [class*="header"], [class*="footer"], '
        '[class*="navbar"], [class*="nav-menu"]')
    for tag in targets:
        try:
            if tag.name in ('html', 'body', 'main') or tag.find('main') is not None:
                continue
            if total and len(tag.get_text(' ', strip=True)) > total * 0.6:
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
    for tag in soup.find_all('meta', attrs={'name': re.compile(r'robots', re.I)}):
        if 'noindex' in str(tag.get('content') or '').lower():
            return True
    if res is not None and 'noindex' in str(res.headers.get('X-Robots-Tag', '')).lower():
        return True
    return False


def slug_tokens(text):
    raw = re.split(r'[\s\-_/|،,.:؛…]+', str(text or '').lower())
    out = []
    for t in raw:
        t = re.sub(r'[^0-9a-z\u0600-\u06FF]', '', t)
        if len(t) < 2:
            continue
        out.append(normalize_ar_token(t) if re.search(r'[\u0600-\u06FF]', t) else t)
    return out


def title_h1_match(meta_title, h1_text):
    if not meta_title or not h1_text:
        return 'match_na'
    t = set(slug_tokens(meta_title))
    h = set(slug_tokens(h1_text))
    if not h:
        return 'match_na'
    return 'match_ok' if len(t & h) / len(h) >= 0.5 else 'match_diff'


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


def image_format(url):
    path = urlparse(str(url or '')).path.lower()
    mo = re.search(r'\.(jpe?g|png|webp|avif|gif|svg|bmp|tiff?)(?:$|\?)', path)
    if mo:
        ext = mo.group(1)
        return 'jpg' if ext in ('jpg', 'jpeg') else ext
    mo2 = re.search(r'(?:format|fm)=(\w+)', str(url or '').lower())
    return mo2.group(1) if mo2 else '—'


def broken_page_row(url, reason, source):
    return {
        'page_data': {
            'نوع الصفحة': T_BROKEN, 'الرابط': unquote(url), 'مصدر الاكتشاف': source,
            'متاحة': False, 'كود الاستجابة': str(reason), 'لغة الصفحة': '—',
            'اسم المنتج المعروض': '', 'اسم منظم': '', 'صور معلنة': 0,
            'قابلة للأرشفة': True, 'مطابقة العنوان مع H1': 'match_na',
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

    home_key = url_key(normalize_url(base_url))
    if url_key(clean_url(url)) != home_key:
        canon_now = ''
        for lk in soup.find_all('link', href=True):
            rel = lk.get('rel') or []
            rel = [r.lower() for r in (rel if isinstance(rel, list) else [rel])]
            if 'canonical' in rel:
                canon_now = clean_url(urljoin(final_url, lk['href']))
                break
        if url_key(final_url) == home_key or (canon_now and url_key(canon_now) == home_key):
            return broken_page_row(clean_url(url), 'محذوف — تحويل للرئيسية', source)

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
    noindex = is_noindex(soup, res)
    if not display_name:
        ogt = soup.find('meta', attrs={'property': 'og:title'})
        if ogt and ogt.get('content'):
            display_name = re.sub(r'\s+', ' ', ogt['content']).strip()

    title_tag = soup.find('title')
    title = re.sub(r'\s+', ' ', title_tag.get_text(strip=True)).strip() if title_tag else ''
    title_len = text_length(title)
    title_status = grade_length(title_len, TITLE_MIN_OK, TITLE_MIN_OPTIMAL, TITLE_MAX)

    desc_tag = (soup.find('meta', attrs={'name': 'description'}) or soup.find('meta', attrs={'property': 'og:description'}))
    meta_desc = desc_tag['content'].strip() if desc_tag and desc_tag.get('content') else ''
    meta_desc = re.sub(r'\s+', ' ', meta_desc).strip()
    desc_len = text_length(meta_desc)
    desc_status = grade_length(desc_len, DESC_MIN_OK, DESC_MIN_OPTIMAL, DESC_MAX)

    content_soup = strip_boilerplate(soup, res.text)
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
                'رابط الصورة': clean_image_url(urljoin(final_url, src)),
                'النص البديل الحالي (Alt)': alt_text,
                'طول النص البديل': alt_len, 'حالة النص البديل': alt_status,
                'صيغة الصورة': image_format(urljoin(final_url, src)),
            })

    jd = extract_product_facts(soup) if page_type == T_PRODUCT else {'name': '', 'images': [], 'sku': '', 'offers': False}
    prod_links = set()
    if page_type in (T_CATEGORY, T_HOME):
        for lk in links:
            if _detect_type_by_url(lk, base_url) == T_PRODUCT:
                prod_links.add(url_key(lk))
    declared_n = (extract_declared_count(soup) if page_type in (T_CATEGORY, T_HOME) else None)

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
            '_raw_url': final_url,
        },
        'images_data': page_images,
        'links': links,
        'product_links': prod_links,
        'platform_html': res.text[:60000] if page_type == T_HOME else '',
        'platform_headers': dict(res.headers) if page_type == T_HOME else {},
    }


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
    return any(re.search(pat, low) for pat in PLACEHOLDER_PATTERNS) if low else False


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
    dup_titles = {v for v, n in tvals[tvals != ''].value_counts().items() if n >= TEXT_DUP_THRESHOLD}
    dvals = out.loc[ok_mask, 'وصف الميتا'].map(lambda x: str(x or '').strip())
    dup_descs = {v for v, n in dvals[dvals != ''].value_counts().items() if n >= TEXT_DUP_THRESHOLD}

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
        if len(meaningful_text(strip_brand(t)).strip()) and len(strip_brand(t).split()) < 2:
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


CLONE_PATTERNS = [r'copy-of', r'copy_of', r'-copy\b', r'نسخة', r'نسخه', r'duplicate', r'\bتجربة\b', r'\btest\b']
URL_MAX_PATH = 90
URL_MAX_WORDS = 9
URL_CREDIT = {'u_malformed': 0.5, 'u_ok': 1.0, 'u_underscore': 0.95, 'u_uppercase': 0.95, 'u_repeat': 0.95,
              'u_wordy': 0.93, 'u_long': 0.90, 'u_generic': 0.80, 'u_wrongname': 0.65,
              'u_clone': 0.70, 'u_na': 1.0}


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
    path = unquote(urlparse(clean_url(url)).path)
    segs = [x for x in path.split('/') if x]
    if not segs:
        return ''
    if re.fullmatch(r'p\d+', segs[-1]) and len(segs) >= 2:
        return segs[-2]
    return segs[-1]


def analyze_url_quality(df, brand=''):
    if df.empty:
        return df
    out = df.copy()
    out['المسار'] = out['الرابط'].map(slug_of)
    known = {url_key(u) for u in out['الرابط']}

    prod_names = out.loc[out['نوع الصفحة'] == T_PRODUCT, 'اسم المنتج المعروض'] if 'اسم المنتج المعروض' in out.columns else []
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
            if url_key(parent) in known:
                return 'u_clone'

        if re.search(r'https?[:;]|://|www\.|\.com|\.net|\.store\b', low):
            return 'u_malformed'

        if re.fullmatch(r'[\d\W_]+', slug) or re.fullmatch(r'(product|item|page|post)[-_]?\d*', low):
            return 'u_generic'

        words = [w for w in re.split(r'[-_]+', slug) if w]

        if '_' in slug:
            return 'u_underscore'
        if re.search(r'[A-Z]', slug):
            return 'u_uppercase'
        if len(unquote(urlparse(clean_url(row['الرابط'])).path)) > URL_MAX_PATH:
            return 'u_long'
        norm = [normalize_ar_token(w.lower()) if re.search(r'[\u0600-\u06FF]', w) else w.lower() for w in words]
        if len(norm) != len(set(norm)) and len(norm) > 2:
            return 'u_repeat'
        if len(words) > URL_MAX_WORDS:
            return 'u_wordy'

        name = (str(row.get('اسم منظم') or '').strip() or str(row.get('اسم المنتج المعروض') or '').strip())
        meta_t = str(row.get('عنوان الميتا') or '').strip()
        if (name or meta_t) and row.get('نوع الصفحة') == T_PRODUCT:
            s_tok = [t for t in slug_tokens(slug) if not t.isdigit()]
            n_tok = (set(slug_tokens(name)) | set(slug_tokens(meta_t))) - brand_tokens
            ref = name if name else meta_t
            if s_tok and n_tok and script_of(slug) == script_of(ref):
                distinctive = [t for t in s_tok if t not in generic_vocab and t not in brand_tokens]
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
    sub = ok[(ok['عنوان الميتا'].astype(str).str.strip() != '')]
    for (t, d), grp in sub.groupby(['عنوان الميتا', 'وصف الميتا']):
        if len(grp) > 1:
            groups.append({'العنوان': t, 'عدد الصفحات': len(grp), 'الروابط': list(grp['الرابط'])})
    dup_urls = {u for g in groups for u in g['الروابط']}
    out['محتوى مكرر'] = out['الرابط'].isin(dup_urls)
    return out, groups


LEN_WEIGHT = {'optimal': 1.0, 'acceptable': 0.7, 'very_short': 0.3, 'long': 0.4, 'missing': 0.0}


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
        s = 25 * LEN_WEIGHT.get(r['حالة العنوان'], 0) * QUALITY_CREDIT.get(r.get('جودة العنوان', 'q_na'), 1.0)
        s += 25 * LEN_WEIGHT.get(r['حالة الوصف'], 0) * QUALITY_CREDIT.get(r.get('جودة الوصف', 'q_na'), 1.0)
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


PAGING_PATTERNS = ['?page={n}', '?p={n}', '/page/{n}', '?offset={o}']
LISTING_ROOTS = ['products', 'latest-products', 'collections/all', 'shop', 'store',
                 'blog', 'new-arrivals', 'best-selling', 'offers']
PLATFORM_LISTINGS = [
    'products', 'latest-products', 'offers', 'categories', 'brands',
    'collections/all', 'shop', 'blog', 'testimonials',
]


def listing_product_links(html, base_url, page_url):
    soup = make_soup(html)
    netloc = urlparse(normalize_url(base_url)).netloc
    out = set()
    for a in soup.find_all('a', href=True):
        full = clean_url(urljoin(page_url, a['href'].strip()))
        if is_crawlable(full, netloc) and _detect_type_by_url(full, base_url) in (T_PRODUCT, T_BLOG):
            out.add(full)
    for node in iter_jsonld(soup):
        for item in (node.get('itemListElement') or []):
            if not isinstance(item, dict):
                continue
            tgt = None
            if isinstance(item.get('item'), dict):
                tgt = item['item'].get('url')
            tgt = tgt or item.get('url')
            if tgt:
                full = clean_url(urljoin(page_url, str(tgt)))
                if is_crawlable(full, netloc) and _detect_type_by_url(full, base_url) in (T_PRODUCT, T_BLOG):
                    out.add(full)
    return out


def harvest_paginated_products(base_url, category_urls, seen_keys, progress_cb=None,
                               max_depth=MAX_PAGINATION_DEPTH, cat_products=None,
                               listing_urls=None):
    base_url = normalize_url(base_url)
    roots = list(dict.fromkeys(
        list(category_urls) + list(listing_urls or []) +
        [f"{base_url}/{r}" for r in LISTING_ROOTS]))
    new_urls, fetched = [], 0

    for idx, cat in enumerate(roots):
        pattern = None
        seen_here = set()
        for page in range(2, max_depth + 1):
            candidates = ([pattern] if pattern else PAGING_PATTERNS)
            fresh = set()
            for pat in candidates:
                url = cat + pat.format(n=page, o=(page - 1) * 20)
                res = safe_get(url, retries=0)
                fetched += 1
                if res is None or res.status_code != 200:
                    continue
                found = listing_product_links(res.text, base_url, cat)
                f = found - seen_here
                if f:
                    fresh = f
                    pattern = pat
                    break
            if not fresh:
                break
            seen_here |= fresh
            if cat_products is not None:
                cat_products.setdefault(cat, set()).update({url_key(x) for x in fresh})
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


def sitemap_urls_via_usp(base_url, netloc):
    if not HAS_USP:
        return None
    try:
        tree = _usp_tree(base_url)
        out = set()
        for page in tree.all_pages():
            u = clean_url(page.url)
            if u and urlparse(u).netloc.lower().replace('www.', '') == netloc.lower().replace('www.', ''):
                out.add(u)
        return out if out else None
    except Exception:
        return None


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


LOC_RE = re.compile(r'<loc>\s*(.*?)\s*</loc>', re.I | re.S)


def fetch_sitemap_locs(url, quick=False):
    res = safe_get(url, timeout=(8 if quick else 30), retries=(0 if quick else 2))
    if res is None or res.status_code != 200:
        return None
    content = res.content
    if url.lower().endswith('.gz') or content[:2] == b'\x1f\x8b':
        try:
            content = gzip.decompress(content)
        except Exception:
            pass
    text = content.decode('utf-8', 'ignore').lstrip('\ufeff \t\r\n')
    if '<loc' not in text.lower() and '<sitemapindex' not in text.lower() and '<urlset' not in text.lower():
        return None
    locs = [m.strip() for m in LOC_RE.findall(text) if m.strip()]
    if locs:
        return locs
    try:
        root = ET.fromstring(text.encode('utf-8'))
        return [el.text.strip() for el in root.iter()
                if (el.tag.split('}')[-1] if '}' in el.tag else el.tag) == 'loc' and el.text]
    except Exception:
        return None


def collect_sitemap_urls(base_url, max_depth=3):
    base_url = normalize_url(base_url)
    base_netloc = urlparse(base_url).netloc
    urls, visited = set(), set()
    report = {'files_ok': 0, 'files_failed': 0, 'failed_urls': []}

    def walk(sm_url, depth, declared=True):
        if depth > max_depth or sm_url in visited:
            return
        visited.add(sm_url)
        tries = 3 if declared else 1
        locs = None
        for attempt in range(tries):
            locs = fetch_sitemap_locs(sm_url, quick=not declared)
            if locs is not None:
                break
            if attempt + 1 < tries:
                time.sleep(1.5 * (attempt + 1))
        if locs is None:
            if declared:
                report['files_failed'] += 1
                report['failed_urls'].append(sm_url)
            return False
        report['files_ok'] += 1
        for loc in locs:
            low = loc.lower()
            if low.endswith('.xml') or low.endswith('.xml.gz'):
                walk(loc, depth + 1, declared=True)
            else:
                u = clean_url(loc)
                if u and urlparse(u).netloc == base_netloc:
                    urls.add(u)
        return True

    via_lib = sitemap_urls_via_usp(base_url, base_netloc)
    if via_lib:
        urls.update(via_lib)
        report['files_ok'] += 1

    for c in discover_sitemaps_from_robots(base_url):
        walk(c, 0, declared=True)
    for c in [f"{base_url}/sitemap.xml", f"{base_url}/sitemap_index.xml",
              f"{base_url}/sitemap-index.xml", f"{base_url}/sitemap.xml.gz",
              f"{base_url}/sitemap/sitemap.xml", f"{base_url}/sitemaps.xml",
              f"{base_url}/sitemap_products_1.xml", f"{base_url}/sitemap_pages_1.xml",
              f"{base_url}/wp-sitemap.xml"]:
        walk(c, 0, declared=False)
    report['partial'] = report['files_failed'] > 0
    return urls, report


def dedupe_pages(df):
    if df.empty:
        return df
    df = df.copy()
    src_col = '_raw_url' if '_raw_url' in df.columns else 'الرابط'
    df['_key'] = df[src_col].map(url_key)
    df['_canon'] = df.apply(
        lambda r: url_key(r['الرابط الكانوني']) if str(r.get('الرابط الكانوني') or '').strip() else r['_key'], axis=1)
    df = df.drop_duplicates(subset=['_key'])
    avail = df[df['متاحة'] == True]  # noqa: E712
    dup_keys = set(avail[avail.duplicated(subset=['_canon'], keep='first')]['_key'])
    canon_broken = len(avail) >= 10 and len(dup_keys) > len(avail) * 0.5
    if canon_broken:
        df.attrs['canon_broken'] = int(len(dup_keys))
    else:
        df = df[~df['_key'].isin(dup_keys)]
    out = df.drop(columns=['_key', '_canon']).reset_index(drop=True)
    if canon_broken:
        out.attrs['canon_broken'] = int(len(dup_keys))
    return out


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
        'broken_pages': int(((df['متاحة'] == False) & (~df['كود الاستجابة'].astype(str).str.contains('فشل اتصال|خطأ فني|محذوف', na=False))).sum()),  # noqa: E712
        'unreachable_pages': int(((df['متاحة'] == False) & (df['كود الاستجابة'].astype(str).str.contains('فشل اتصال|خطأ فني', na=False))).sum()),  # noqa: E712
        'bad_titles': int((~ok['حالة العنوان'].isin(['optimal'])).sum()),
        'critical_titles': int(ok['حالة العنوان'].isin(['missing', 'very_short', 'long']).sum()),
        'bad_descs': int((~ok['حالة الوصف'].isin(['optimal'])).sum()),
        'critical_descs': int(ok['حالة الوصف'].isin(['missing', 'very_short', 'long']).sum()),
        'total_images': int(len(uimg)) if uimg is not None and not uimg.empty else 0,
        'image_slots': int(ok['إجمالي الصور'].sum()),
        'missing_alts': int(alt_counts.get('alt_missing', 0)),
        'weak_alts': int(sum(alt_counts.get(k, 0) for k in ALT_WEAK_STATES)),
        'good_alts': int(alt_counts.get('alt_ok', 0)),
        'dup_alts': int(alt_counts.get('alt_duplicate', 0)),
        'title_symbols': int(ok['جودة العنوان'].isin(QUALITY_FATAL).sum()) if 'جودة العنوان' in ok.columns else 0,
        'title_brand_only': int((ok['جودة العنوان'] == 'q_brand_only').sum()) if 'جودة العنوان' in ok.columns else 0,
        'title_dup': int((ok['جودة العنوان'] == 'q_duplicate').sum()) if 'جودة العنوان' in ok.columns else 0,
        'desc_dup': int((ok['جودة الوصف'] == 'q_duplicate').sum()) if 'جودة الوصف' in ok.columns else 0,
        'desc_same': int((ok['جودة الوصف'] == 'q_same_as_title').sum()) if 'جودة الوصف' in ok.columns else 0,
        'url_clone': int((ok['جودة الرابط'] == 'u_clone').sum()) if 'جودة الرابط' in ok.columns else 0,
        'url_wrongname': int((ok['جودة الرابط'] == 'u_wrongname').sum()) if 'جودة الرابط' in ok.columns else 0,
        'url_style': int(ok['جودة الرابط'].isin(['u_underscore', 'u_uppercase', 'u_long', 'u_repeat', 'u_wordy']).sum()) if 'جودة الرابط' in ok.columns else 0,
        'url_malformed': int((ok['جودة الرابط'] == 'u_malformed').sum()) if 'جودة الرابط' in ok.columns else 0,
        'url_generic': int((ok['جودة الرابط'] == 'u_generic').sum()) if 'جودة الرابط' in ok.columns else 0,
        'url_bad': int((~ok['جودة الرابط'].isin(['u_ok', 'u_na'])).sum()) if 'جودة الرابط' in ok.columns else 0,
        'dup_content': int(ok['محتوى مكرر'].sum()) if 'محتوى مكرر' in ok.columns else 0,
        'canon_broken': int(df.attrs.get('canon_broken', 0)),
        'canon_missing': int((ok['حالة الكانونيكال'] == 'canon_missing').sum()),
        'canon_diff': int((ok['حالة الكانونيكال'] == 'canon_diff').sum()),
        'thin_pages': int((ok['حالة المحتوى'] == 'thin').sum()),
        'noindex_pages': int((~ok['قابلة للأرشفة'].fillna(True)).sum()) if 'قابلة للأرشفة' in ok.columns else 0,
        'h1_mismatch': int((ok['مطابقة العنوان مع H1'] == 'match_diff').sum()) if 'مطابقة العنوان مع H1' in ok.columns else 0,
        'deleted_pages': int((df['كود الاستجابة'].astype(str).str.contains('محذوف', na=False)).sum()),
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
            'hidden_count': len(coverage.get('orphan_pages', [])),
            'scroll_only_count': len(coverage.get('scroll_only_products', [])),
            'unlisted_count': len(coverage.get('unlisted_pages', [])),
            'orphan_by_type': coverage.get('orphan_by_type', {}),
            'indexed_pct': coverage.get('indexed_pct', 100.0),
        })
    return s


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
                facts['images'].append(it.strip())
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
        row = {'القسم': unquote(url), 'عدد معلن': dec, 'مرصود': found, 'ناقص': max(dec - found, 0)}
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
        if shown and slug_tokens(j_name) and not (set(slug_tokens(j_name)) & set(slug_tokens(shown))):
            name_gap.append({'الرابط': r['الرابط'], 'الاسم المعلن': j_name, 'الاسم المعروض': shown})
        dec_i = as_int(r.get('صور معلنة')) or 0
        seen_i = as_int(r.get('إجمالي الصور')) or 0
        if dec_i and seen_i < dec_i:
            img_gap.append({'الرابط': r['الرابط'], 'صور معلنة': dec_i, 'صور مرصودة': seen_i})

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


CHECK_FAIL, CHECK_WARN, CHECK_PASS = 'fail', 'warn', 'pass'


def run_self_checks(df, images_df, coverage, platform, summary, crawl_meta=None, structured=None):
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
            f"المنصة ({known}) خارج المنصات التي عُوِّرت عليها الأداة (سلة وزد وشوبيفاي). الفحوص التالية هي ما يحدد موثوقية النتائج.",
            "راجع باقي الفحوص وعيّنة التحقق اليدوي قبل الإرسال.")

    if n_ok == 0:
        add(CHECK_FAIL, "حجم الزحف", "لم تُفحص أي صفحة بنجاح.", "تحقق من أن الرابط صحيح وأن المتجر لا يحجب الزحف.")
    elif n_ok < 5:
        add(CHECK_FAIL, "حجم الزحف", f"{n_ok} صفحة فقط — رقم صغير جداً لمتجر إلكتروني.",
            "على الأرجح القائمة مبنية بـ JavaScript فلم يجد الزاحف روابط. هذا المتجر خارج نطاق الأداة.")
    else:
        add(CHECK_PASS, "حجم الزحف", f"{n_ok} صفحة مفحوصة بنجاح.")

    n_prod = summary.get('products', 0)
    if n_ok >= 2 and n_prod == 0:
        no_map = summary.get('sitemap_products', 0) == 0
        why = ("المتجر يعرض منتجاته بـ JavaScript ولا توجد خريطة موقع، فلا مصدر لقائمة المنتجات." if no_map else "بنية روابط هذا المتجر غير معتادة.")
        add(CHECK_FAIL, "اكتشاف المنتجات", f"لم يُعثر على أي صفحة منتج. {why}",
            "افتح الصفحة الرئيسية واضغط بزر الفأرة الأيمن ثم «عرض المصدر»: إن لم تجد روابط المنتجات في الكود فالمتجر خارج نطاق الأداة حالياً. الحل: تفعيل خريطة الموقع في إعدادات المتجر.")
    elif n_prod:
        add(CHECK_PASS, "اكتشاف المنتجات", f"{n_prod} صفحة منتج.")

    if n_ok:
        ratio = summary.get('unclassified', 0) / n_ok * 100
        if ratio > 25:
            add(CHECK_FAIL, "دقة التصنيف", f"{round(ratio, 1)}% من الصفحات لم تُصنّف آلياً.", "قواعد التصنيف لا تناسب بنية هذا المتجر. راجع تبويب الصفحات.")
        elif ratio > 10:
            add(CHECK_WARN, "دقة التصنيف", f"{round(ratio, 1)}% من الصفحات غير مصنّفة.", "راجعها في تبويب الصفحات قبل الإرسال.")
        else:
            add(CHECK_PASS, "دقة التصنيف", f"{round(ratio, 1)}% فقط غير مصنّفة.")

    prod_pages = ok[ok['نوع الصفحة'] == T_PRODUCT] if n_ok else ok
    if len(prod_pages) >= 3:
        with_imgs = int((prod_pages['إجمالي الصور'] > 0).sum())
        pct = with_imgs / len(prod_pages) * 100
        if pct == 0:
            add(CHECK_FAIL, "رصد صور المنتجات", "لم تُرصد أي صورة على صفحات المنتجات.", "معرض الصور مبني بـ JavaScript. أرقام الصور في التقرير غير صحيحة.")
        elif pct < 60:
            add(CHECK_WARN, "رصد صور المنتجات", f"{round(pct, 1)}% فقط من صفحات المنتجات تحتوي صوراً مرصودة.", "افتح صفحة منتج وقارن عدد الصور الفعلي بالمسجّل.")
        else:
            add(CHECK_PASS, "رصد صور المنتجات", f"{round(pct, 1)}% من صفحات المنتجات بها صور مرصودة ({n_img} صورة فريدة).")

    if n_ok:
        no_title = int((ok['طول العنوان'] == 0).sum())
        if no_title == n_ok:
            add(CHECK_FAIL, "قراءة العناوين", "كل الصفحات بلا عنوان — مؤشر على فشل في قراءة الصفحات.", "لا ترسل التقرير. افتح أي صفحة وتحقق من وجود وسم title.")
        elif no_title / n_ok > 0.5:
            add(CHECK_WARN, "قراءة العناوين", f"{no_title} صفحة بلا عنوان من أصل {n_ok}.", "تحقق من عيّنة في تبويب التحقق اليدوي.")
        else:
            add(CHECK_PASS, "قراءة العناوين", f"العناوين مقروءة في {n_ok - no_title} صفحة من {n_ok}.")

    if n_ok and 'جودة العنوان' in ok.columns:
        sym = int(ok['جودة العنوان'].isin(QUALITY_FATAL).sum())
        if sym / n_ok > 0.6:
            add(CHECK_WARN, "سلامة العناوين", f"{sym} عنوان من أصل {n_ok} مجرد رموز أو قيمة قالب افتراضية — نسبة مرتفعة تعني أن قالب المتجر لا يولّد عناوين ميتا.", "تحقق من عيّنة يدوياً. هذه نتيجة حقيقية عن المتجر لا خلل في القراءة.")
        elif sym:
            add(CHECK_WARN, "سلامة العناوين", f"{sym} عنوان مجرد رموز أو قيمة قالب (مثل [] أو {{{{ }}}}).", "عُوملت كعناوين مفقودة في الأرقام.")
        else:
            add(CHECK_PASS, "سلامة العناوين", "لا توجد عناوين رمزية أو قيم قوالب.")

    prod = ok[ok['نوع الصفحة'] == T_PRODUCT] if n_ok else ok
    if len(prod) >= 5 and 'جودة الرابط' in prod.columns:
        wrong = int((prod['جودة الرابط'] == 'u_wrongname').sum())
        noname = int((prod['اسم المنتج المعروض'].astype(str).str.strip() == '').sum()) if 'اسم المنتج المعروض' in prod.columns else 0
        if noname == len(prod):
            add(CHECK_WARN, "قراءة اسم المنتج", "تعذّرت قراءة اسم المنتج من أي صفحة، فلم تُفحص مطابقة الروابط.", "قالب المتجر لا يستخدم وسم H1 للاسم.")
        elif wrong / len(prod) > 0.5:
            add(CHECK_WARN, "مطابقة الروابط", f"{wrong} رابط من {len(prod)} يحمل اسماً مختلفاً — نسبة مرتفعة.", "افتح عيّنة وتأكد أن الأمر واقع فعلي لا خطأ في قراءة الاسم.")
        else:
            add(CHECK_PASS, "مطابقة الروابط", f"{len(prod) - wrong} رابط من {len(prod)} يطابق اسم منتجه.")

    if structured:
        checked = structured.get('categories_checked', 0)
        matched = structured.get('categories_matched', 0)
        short = structured.get('categories_short') or []
        miss = structured.get('missing_products', 0)
        if checked and short:
            has_map = summary.get('sitemap_products', 0) > 0
            if has_map:
                add(CHECK_WARN, "ترابط الأقسام الداخلي", f"{len(short)} قسماً من {checked} لا يعرض روابط كل منتجاته في صفحته ({miss} منتجاً يظهر بالتمرير أو بزر «المزيد»).", "المنتجات نفسها مفحوصة بالكامل من خريطة الموقع — هذه ملاحظة عن الترابط الداخلي للمتجر لا نقص في الفحص.")
            else:
                add(CHECK_FAIL, "تغطية المنتجات", f"{len(short)} قسماً يعلن {miss} منتجاً أكثر مما وصل إليه الفحص، ولا توجد خريطة موقع للاعتماد عليها.", "المتجر يحمّل منتجاته بالتمرير وبلا خريطة موقع — أرقام المنتجات في هذا التقرير ناقصة. لا ترسله.")
        elif checked:
            add(CHECK_PASS, "ترابط الأقسام الداخلي", f"{matched} قسماً من {checked} يعرض روابط كل منتجاته.")
        else:
            add(CHECK_PASS, "ترابط الأقسام الداخلي", "لا توجد عدّادات في صفحات الأقسام للمقارنة بها.")

        n_prod = structured.get('found_products', 0)
        gaps = structured.get('image_gap') or []
        if gaps:
            lvl = CHECK_FAIL if len(gaps) / max(n_prod, 1) > 0.5 else CHECK_WARN
            add(lvl, "مطابقة عدد الصور", f"{len(gaps)} صفحة منتج تعلن صوراً أكثر مما رصده الزاحف.", "معرض الصور يُحمَّل بـ JavaScript جزئياً. أرقام الصور أقل من الواقع.")
        elif n_prod:
            add(CHECK_PASS, "مطابقة عدد الصور", "عدد الصور المرصود يطابق ما يعلنه المتجر.")

        nm = structured.get('name_mismatch') or []
        if nm:
            add(CHECK_WARN, "مطابقة أسماء المنتجات", f"{len(nm)} منتجاً اسمه المعلن لمحركات البحث يختلف عن المعروض في الصفحة.", "راجعها في تبويب «البيانات المعلنة».")

        nj = structured.get('no_jsonld', 0)
        if n_prod and nj == n_prod:
            add(CHECK_WARN, "البيانات المهيكلة", "لا توجد بيانات منتجات مهيكلة في أي صفحة.", "هذا بحد ذاته نقص سيو في المتجر، ويحرم الأداة من مصدر تحقق.")
        elif n_prod:
            add(CHECK_PASS, "البيانات المهيكلة", f"{structured.get('jsonld_pages', 0)} صفحة منتج تحمل بيانات مهيكلة.")

    unreach = summary.get('unreachable_pages', 0)
    if unreach:
        total_pages = max(len(df), 1)
        lvl = CHECK_WARN if unreach / total_pages < 0.15 else CHECK_FAIL
        add(lvl, "استقرار الاتصال", f"{unreach} صفحة تعذّر الاتصال بها رغم إعادة المحاولة.", "قد يحدّ المتجر من سرعة الزحف. خفّض «المسارات المتوازية» إلى 2 وأعد الفحص للحصول على تغطية كاملة.")

    if summary.get('noindex_pages'):
        n_all = max(len(df), 1)
        lvl = CHECK_FAIL if summary['noindex_pages'] / n_all > 0.3 else CHECK_WARN
        add(lvl, "منع الأرشفة", f"{summary['noindex_pages']} صفحة تطلب من محركات البحث تجاهلها (وسم noindex).", "تحقق من إعدادات المتجر: قد تكون صفحات مهمة ممنوعة من الظهور.")

    if summary.get('canon_broken'):
        add(CHECK_FAIL, "وسم الكانونيكال", f"{summary['canon_broken']} صفحة تشير بوسم الكانونيكال إلى صفحة أخرى واحدة، وهو خلل في قالب المتجر يجعل محركات البحث تتجاهل هذه الصفحات كلها.", "أبلغ التاجر فوراً: هذا أخطر خلل سيو ممكن، ويعالج بإصلاح وسم الكانونيكال في القالب.")

    if crawl_meta:
        srcs = crawl_meta.get('source_counts') or {}
        if srcs:
            add(CHECK_PASS, "مصادر الاكتشاف", "الصفحات جاءت من: " + "، ".join(f"{k} ({v})" for k, v in srcs.items()))

    sm_total = summary.get('sitemap_products', 0)
    coverage_obj = coverage if isinstance(coverage, dict) else {}
    if summary.get('coverage_enabled'):
        if sm_total == 0:
            add(CHECK_WARN, "خريطة الموقع", "لا توجد خريطة موقع، فاعتمد الفحص على تتبع الروابط كما يفعل الزائر — وهذا يغطي كل صفحة مرتبطة برابط.", "غياب الخريطة بحد ذاته نقص سيو في المتجر يستحق الذكر للعميل. وإن كان المتجر يحمّل منتجاته بالتمرير فسيظهر ذلك في فحص «تغطية المنتجات».")
        elif coverage_obj.get('partial_read'):
            add(CHECK_FAIL, "قراءة خريطة الموقع", f"تعذّرت قراءة {coverage_obj.get('files_failed', 0)} من ملفات خريطة الموقع، فالقائمة التي اعتمدها الفحص ناقصة.", "خفّض «المسارات المتوازية» إلى 2 وأعد الفحص. لا تعتمد أرقام الخريطة في هذا التقرير.")
        elif summary.get('unlisted_count', 0) > sm_total * 0.3:
            add(CHECK_WARN, "خريطة الموقع", f"{summary['unlisted_count']} صفحة معروضة غير مدرجة في الخريطة مقابل {sm_total} مدرجة — الخريطة ناقصة.", "هذه نتيجة حقيقية عن المتجر، لكن راجع عيّنة للتأكد.")
        else:
            add(CHECK_PASS, "خريطة الموقع", f"{sm_total} رابط في الخريطة، منها {summary.get('sitemap_live', 0)} يعمل ويصل إليه الزائر.")

    if n_ok:
        thin = summary.get('thin_pages', 0) / n_ok * 100
        if thin > 50:
            add(CHECK_FAIL, "قراءة المحتوى", f"{round(thin, 1)}% من الصفحات بمحتوى نصي شبه فارغ.", "المتجر يبني محتواه بـ JavaScript — النتائج غير معتمدة.")
        elif thin > 20:
            add(CHECK_WARN, "قراءة المحتوى", f"{round(thin, 1)}% من الصفحات بمحتوى نصي ضعيف.", "تأكد أن هذا واقع المتجر لا خلل في القراءة.")
        else:
            add(CHECK_PASS, "قراءة المحتوى", "المحتوى النصي مقروء بشكل طبيعي.")

    if crawl_meta and crawl_meta.get('truncated'):
        add(CHECK_WARN, "اكتمال الزحف", f"توقف الزحف مع بقاء {crawl_meta.get('pending', 0)} رابط غير مفحوص.", "ارفع الحد الأقصى للصفحات من الإعدادات وأعد الفحص.")
    else:
        add(CHECK_PASS, "اكتمال الزحف", "غُطّيت كل الروابط المكتشفة.")

    if coverage and coverage.get('sitemap_count'):
        vis, sm = coverage['visible_count'], coverage['sitemap_count']
        if sm and vis / sm < 0.6:
            add(CHECK_WARN, "تغطية المنتجات", f"{vis} منتج معروض مقابل {sm} في خريطة الموقع.", "قد يستخدم المتجر تمريراً لانهائياً بدل ترقيم الصفحات، فلم يصل الزاحف لكل المنتجات.")
        else:
            add(CHECK_PASS, "تغطية المنتجات", f"{vis} منتج معروض مقابل {sm} في الخريطة — متسق.")

    if n_ok:
        br = summary.get('broken_pages', 0)
        if br / max(len(df), 1) > 0.15:
            add(CHECK_WARN, "الروابط المعطلة", f"{br} رابط معطل — نسبة مرتفعة قد تعني حجباً جزئياً للزاحف.", "افتح عيّنة منها في المتصفح للتأكد أنها معطلة فعلاً.")
        else:
            add(CHECK_PASS, "الروابط المعطلة", f"{br} رابط معطل — ضمن المعقول.")

    fails = sum(1 for c in checks if c['level'] == CHECK_FAIL)
    warns = sum(1 for c in checks if c['level'] == CHECK_WARN)
    verdict = ('blocked' if fails else 'review' if warns else 'ready')
    return {'checks': checks, 'fails': fails, 'warns': warns, 'verdict': verdict}


def discover_and_audit(base_url, max_pages=MAX_PAGES_DEFAULT, workers=4, progress=None, max_rounds=6):
    base_url = normalize_url(base_url)
    if progress:
        progress('sitemap_read')
    sitemap_urls, sm_report = collect_sitemap_urls(base_url)
    sitemap_keys = {url_key(u) for u in sitemap_urls}

    platform_seeds = {f"{base_url}/{p}" for p in PLATFORM_LISTINGS}
    speculative = {url_key(u) for u in platform_seeds}
    queue = sorted({clean_url(u) for u in sitemap_urls} | {base_url} | platform_seeds)
    seen = {url_key(u) for u in queue}
    linked = set()
    cat_links = {}
    pages, images = [], []
    platform = 'unknown'
    rounds = 0
    truncated = False

    while queue and rounds < max_rounds:
        rounds += 1
        room = max_pages - len(pages)
        if room <= 0:
            truncated = True
            break
        batch, queue = queue[:room], queue[room:]
        if queue:
            truncated = True
        nxt = []
        src = 'خريطة الموقع' if rounds == 1 else 'رابط داخلي'
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for res in ex.map(fetch_and_audit, [(u, base_url, src) for u in batch]):
                row = res['page_data']
                pages.append(row)
                images.extend(res['images_data'])
                if res.get('platform_html') and platform == 'unknown':
                    platform = detect_platform(res['platform_html'], res.get('platform_headers'), base_url)
                raw = row.get('_raw_url', row['الرابط'])
                seen.add(url_key(raw))
                if row['نوع الصفحة'] in (T_CATEGORY, T_HOME):
                    cat_links.setdefault(raw, set()).update({url_key(x) for x in res.get('product_links', set())})
                for link in res.get('links', ()):
                    k = url_key(link)
                    linked.add(k)
                    if k not in seen:
                        seen.add(k)
                        nxt.append(link)
        queue = nxt + queue
        if progress:
            progress('audit', done=len(pages), pending=len(queue), round=rounds)

    pages = [r for r in pages
             if r['متاحة'] or url_key(r.get('_raw_url', r['الرابط'])) not in speculative
             or url_key(r.get('_raw_url', r['الرابط'])) in sitemap_keys
             or url_key(r.get('_raw_url', r['الرابط'])) in linked]

    for row in pages:
        raw = row.get('_raw_url', row['الرابط'])
        k = url_key(raw)
        row['في الخريطة'] = k in sitemap_keys
        row['مرتبط برابط'] = k in linked

    from collections import Counter
    src_counts = dict(Counter(r.get('مصدر الاكتشاف', '—') for r in pages))
    meta = {'source_counts': src_counts,
            'truncated': truncated, 'pending': len(queue), 'rounds': rounds,
            'cat_products': cat_links, 'sitemap_count': len(sitemap_keys),
            'sitemap_urls': sitemap_urls, 'sitemap_report': sm_report,
            'listing_urls': [r.get('_raw_url', r['الرابط']) for r in pages
                             if r['نوع الصفحة'] in (T_BLOG, T_ARCHIVE)]}
    return pages, images, meta, platform


def build_sitemap_report(df, base_url, sm_report=None):
    if df.empty or 'في الخريطة' not in df.columns:
        return None
    in_map = df['في الخريطة'] == True                      # noqa: E712
    alive = df['متاحة'] == True                            # noqa: E712
    linked = df['مرتبط برابط'] == True                     # noqa: E712

    def rows(mask, extra=None):
        out = []
        for _, r in df[mask].iterrows():
            item = {'الرابط': r['الرابط'], 'نوع الصفحة': r['نوع الصفحة']}
            if extra:
                item[extra] = r['كود الاستجابة']
            out.append(item)
        return out

    is_prod = df['نوع الصفحة'] == T_PRODUCT
    dead = rows(in_map & ~alive, 'كود الاستجابة')
    orphan = rows(in_map & alive & ~linked & ~is_prod)
    scroll_only = rows(in_map & alive & ~linked & is_prod)
    unlisted = rows(~in_map & alive)
    live_in_map = int((in_map & alive).sum())
    prod_live = int((alive & (df['نوع الصفحة'] == T_PRODUCT)).sum())
    prod_unlisted = int((~in_map & alive & (df['نوع الصفحة'] == T_PRODUCT)).sum())
    partial = bool((sm_report or {}).get('partial'))
    return {
        'partial_read': partial,
        'files_failed': (sm_report or {}).get('files_failed', 0),
        'sitemap_total': int(in_map.sum()),
        'sitemap_live': live_in_map,
        'sitemap_dead': len(dead),
        'orphan_pages': orphan,
        'scroll_only_products': scroll_only,
        'dead_pages': dead,
        'unlisted_pages': [] if partial else unlisted,
        'unlisted_suppressed': len(unlisted) if partial else 0,
        'products_live': prod_live,
        'products_unlisted': prod_unlisted,
        'indexed_pct': round((prod_live - prod_unlisted) / prod_live * 100, 1) if prod_live else 100.0,
        'orphan_by_type': dict(df[in_map & alive & ~linked & ~is_prod]['نوع الصفحة'].value_counts()),
    }


def run_full_scan(target, max_pages=MAX_PAGES_DEFAULT, workers=4, do_pagination=True, do_sitemap_check=True, progress=None):
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
        target, max_pages, workers, (lambda st, **k: say(st, **k)))
    cat_products = crawl_meta.setdefault('cat_products', {})

    if do_pagination and cat_products:
        say('pagination_start')
        seen_keys = {url_key(r.get('_raw_url', r['الرابط'])) for r in pages}
        listing_roots = list(cat_products.keys()) + [
            r.get('_raw_url', r['الرابط']) for r in pages
            if r['نوع الصفحة'] in (T_CATEGORY, T_ARCHIVE, T_BLOG, T_HOME)]
        extra = harvest_paginated_products(
            target, list(dict.fromkeys(listing_roots)), seen_keys,
            (lambda i, tot, f, fe: say('pagination', i=i, total=tot, found=f, fetched=fe)),
            cat_products=cat_products, listing_urls=crawl_meta.get('listing_urls'))
        if extra:
            say('extra_start', count=len(extra))
            p2, i2 = audit_urls(extra, target, 'ترقيم القوائم', workers, None)
            for r in p2:
                r['في الخريطة'] = False
                r['مرتبط برابط'] = True
            pages += p2
            imgs += i2

    retry = [r['_raw_url'] for r in pages if not r['متاحة'] and 'فشل اتصال' in str(r['كود الاستجابة'])]
    if retry:
        say('retry_start', count=len(retry))
        time.sleep(2)
        fixed, fixed_imgs = audit_urls(retry[:120], target, 'إعادة محاولة', 2, None)
        good = {r['_raw_url']: r for r in fixed if r['متاحة']}
        if good:
            merged = []
            for r in pages:
                g = good.get(r['_raw_url'])
                if g:
                    g = dict(g)
                    g['في الخريطة'] = r.get('في الخريطة', False)
                    g['مرتبط برابط'] = r.get('مرتبط برابط', False)
                    merged.append(g)
                else:
                    merged.append(r)
            pages = merged
            imgs += [im for im in fixed_imgs if im['رابط الصفحة'] in {g['الرابط'] for g in good.values()}]

    df = dedupe_pages(pd.DataFrame(pages))
    images_df = pd.DataFrame(imgs)
    if not images_df.empty:
        images_df = images_df[images_df['رابط الصفحة'].isin(df['الرابط'])].copy().reset_index(drop=True)
        images_df = apply_duplicate_alt(images_df)
    df, brand = analyze_text_quality(df)
    df = analyze_url_quality(df, brand)
    df, dup_groups = detect_duplicate_content(df)
    df = score_pages(df, images_df)

    coverage = (build_sitemap_report(df, target, crawl_meta.get('sitemap_report')) if do_sitemap_check else None)

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
    selfcheck = run_self_checks(df, images_df, coverage, platform, summary, crawl_meta, structured)
    say('done')

    return {'df': df, 'images_df': images_df, 'summary': summary,
            'coverage': coverage, 'structured': structured,
            'selfcheck': selfcheck, 'brand': brand, 'dup_groups': dup_groups,
            'platform': platform, 'crawl_meta': crawl_meta,
            'declared': declared}
