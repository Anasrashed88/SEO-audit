import requests
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
import pandas as pd
import time
import gzip
import json
import re
from functools import lru_cache
import threading
from urllib.parse import urlparse, urljoin, unquote
from concurrent.futures import ThreadPoolExecutor

try:
    import advertools as adv
    HAS_ADVERTOOLS = True
except Exception:
    HAS_ADVERTOOLS = False

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

# ==============================================================
#  أنواع الصفحات والتصنيفات
# ==============================================================
T_HOME, T_PRODUCT, T_CATEGORY = 'home', 'product', 'category'
T_BLOG, T_INFO, T_UNKNOWN, T_BROKEN = 'blog', 'info', 'unknown', 'broken'
T_ARCHIVE = 'archive'
PAGE_TYPE_ORDER = [T_HOME, T_PRODUCT, T_CATEGORY, T_BLOG, T_INFO, T_ARCHIVE, T_UNKNOWN, T_BROKEN]

PAGE_TYPE_LABEL = {
    'ar': {T_HOME: 'صفحة رئيسية', T_PRODUCT: 'صفحة منتج', T_CATEGORY: 'صفحة تصنيف',
           T_BLOG: 'صفحة مدونة', T_INFO: 'صفحة تعريفية', T_ARCHIVE: 'صفحة أرشيف',
           T_UNKNOWN: 'غير مصنفة', T_BROKEN: 'صفحة معطلة'},
    'en': {T_HOME: 'Homepage', T_PRODUCT: 'Product', T_CATEGORY: 'Category',
           T_BLOG: 'Blog', T_INFO: 'Info / Policy', T_ARCHIVE: 'Archive',
           T_UNKNOWN: 'Unclassified', T_BROKEN: 'Broken'},
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
        'match_ok': 'متطابق مع H1', 'match_diff': 'مختلف عن H1', 'match_empty': 'غير متوفر',
    }
}

TITLE_MAX, TITLE_MIN_OPTIMAL, TITLE_MIN_OK = 60, 50, 30
DESC_MAX, DESC_MIN_OPTIMAL, DESC_MIN_OK = 150, 120, 70
ALT_MAX = 125
ALT_DUP_THRESHOLD = 3

COLOR = {'ok': '#059669', 'warn': '#d97706', 'bad': '#dc2626', 'neutral': '#475569',
         'accent': '#0f172a', 'muted': '#94a3b8'}

# أكواد تعني أن الصفحة محذوفة فعلاً (تُستبعد من التقرير)
GONE_CODES = {'404', '410'}
# أكواد تعني أن المتجر أبطأنا أو تعطل مؤقتاً (تستحق إعادة محاولة هادئة)
RETRYABLE_CODES = {'فشل اتصال', '403', '429', '500', '502', '503', '504',
                   '520', '521', '522', '523', '524'}

# ==============================================================
#  محرك الاتصال (Connection Pooling & Keep-Alive)
# ==============================================================
_SHARED_SESSION = None
_SESSION_LOCK = threading.Lock()

def get_shared_session(pool_size=32):
    global _SHARED_SESSION
    if _SHARED_SESSION is None:
        with _SESSION_LOCK:
            if _SHARED_SESSION is None:
                sess = requests.Session()
                sess.headers.update(HEADERS)
                adapter = requests.adapters.HTTPAdapter(
                    pool_connections=pool_size, pool_maxsize=pool_size, max_retries=0
                )
                sess.mount('https://', adapter)
                sess.mount('http://', adapter)
                _SHARED_SESSION = sess
    return _SHARED_SESSION

def safe_get(url, timeout=10, retries=2):
    """يعيد الاستجابة دائماً إن وصلت (حتى لو كانت 404 أو 429)، و None فقط عند انقطاع الاتصال."""
    sess = get_shared_session()
    last = None
    for attempt in range(retries + 1):
        try:
            res = sess.get(url, timeout=timeout, allow_redirects=True)
        except Exception:
            if attempt < retries:
                time.sleep(1.0 * (attempt + 1))
            continue
        if res.status_code in (429, 503) and attempt < retries:
            last = res
            wait = (res.headers.get('Retry-After') or '').strip()
            delay = float(wait) if wait.isdigit() else 2.0 * (attempt + 1)
            time.sleep(min(delay, 10))
            continue
        return res
    return last

def normalize_domain(netloc):
    netloc = netloc.lower().split(':')[0]
    if netloc.startswith('www.'):
        return netloc[4:]
    return netloc

def normalize_url(url):
    if not url: return ""
    url = url.strip()
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    return url.rstrip('/')

def clean_url(url):
    if not url: return ""
    return url.split('#')[0].split('?')[0].rstrip('/')

PLATFORM_ID_RE = re.compile(r'^(p|c|a|page|tag|category|product)-?(\d{4,})$', re.I)

@lru_cache(maxsize=60000)
def url_key(url):
    if not url: return ""
    p = urlparse(clean_url(url))
    path = unquote(p.path).rstrip('/')
    host = normalize_domain(p.netloc)
    segs = [x for x in path.split('/') if x]
    if segs:
        mo = PLATFORM_ID_RE.match(segs[-1])
        if mo:
            return f"{host}/#{mo.group(1).lower()}{mo.group(2)}"
    if segs and segs[0].lower() in LANG_SEGMENTS:
        segs = segs[1:]
    return f"{host}/{'/'.join(segs)}".rstrip('/')

def make_soup(markup):
    return BeautifulSoup(markup, PARSER)

# مقارنة بجزء الرابط كاملاً (وليس بجزء من النص)
# حتى لا يُستبعد تصنيف مثل «سلة-هدايا» بسبب كلمة «سلة»
EXCLUDE_SEGMENTS = {
    'cart', 'checkout', 'login', 'signin', 'register', 'signup', 'account',
    'my-account', 'wishlist', 'favorites', 'compare', 'search', 'orders',
    'customer', 'password', 'thank-you', 'logout', 'email-protection', 'cdn-cgi',
    'سلة', 'حسابي', 'تسجيل', 'الدفع', 'بحث', 'المفضلة'
}
BAD_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.gif', '.svg', '.webp', '.avif', '.pdf',
                  '.zip', '.rar', '.xml', '.css', '.js', '.ico', '.mp4', '.mp3')

def is_crawlable(url, base_netloc):
    if not url: return False
    p = urlparse(url)
    if p.scheme not in ('http', 'https'): return False
    if normalize_domain(p.netloc) != normalize_domain(base_netloc): return False
    path = unquote(p.path.lower())
    if path.endswith(BAD_EXTENSIONS): return False
    segs = [s for s in path.split('/') if s]
    if any(s in EXCLUDE_SEGMENTS for s in segs): return False
    return True

PLATFORM_LABEL = {'salla': 'سلة (Salla)', 'zid': 'زد (Zid)',
                  'shopify': 'شوبيفاي (Shopify)', 'woocommerce': 'ووكومرس', 'unknown': 'غير محددة'}

def detect_platform(html, headers=None, url=""):
    blob = (html or "")[:100000].lower() + " " + (url or "").lower()
    if any(s in blob for s in ['salla.sa', 'cdn.salla.network', 'window.salla', 'salla-']): return 'salla'
    if any(s in blob for s in ['zid.store', 'media.zid.sa', 'zidapi', 'x-zid', 'cdn.zid']): return 'zid'
    if any(s in blob for s in ['cdn.shopify.com', 'myshopify.com', 'shopify.theme']): return 'shopify'
    if 'woocommerce' in blob or 'wp-content' in blob: return 'woocommerce'
    return 'unknown'

# ==============================================================
#  تحديد نوع الصفحة
#  الترتيب: أنماط الرابط القاطعة ← إشارات الصفحة ← الكلمات المفتاحية
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

POLICY_KEYWORDS = [
    'سياسة', 'شروط', 'خصوصية', 'استبدال', 'استرجاع', 'شحن', 'توصيل', 'شكاوى',
    'اسئلة', 'أسئلة', 'من-نحن', 'اتصل', 'ضمان', 'دفع', 'مقترحات', 'أحكام',
    'الاستخدام', 'ارجاع', 'إرجاع', 'مرتجعات', 'تبديل', 'ضمانات',
    'pages', 'page', 'policies', 'policy', 'privacy', 'terms', 'conditions',
    'about', 'about-us', 'contact', 'contact-us', 'faq', 'faqs', 'help',
    'shipping', 'delivery', 'complaint', 'complaints', 'returns', 'return',
    'refund', 'refunds', 'payment', 'warranty', 'support', 'legal',
]
CATALOG_ROOTS = {'products', 'product', 'all-products', 'latest-products', 'catalog',
                 'catalogue', 'collections/all', 'shop', 'store', 'categories'}
BLOG_SEGMENTS = ('blog', 'blogs', 'articles', 'article', 'post', 'posts', 'news',
                 'مدونة', 'مقالات', 'اخبار', 'أخبار')
CATEGORY_SEGMENTS = ('category', 'categories', 'collection', 'collections',
                     'department', 'departments', 'قسم', 'اقسام', 'أقسام', 'تصنيف')
ARCHIVE_PARENT_SEGMENTS = ('tag', 'tags', 'author', 'authors', 'archive',
                           'وسم', 'وسوم', 'ماركة', 'ماركات')
LANG_SEGMENTS = {'ar', 'en'}

# أنماط سلة: /اسم-المنتج/p123 ، /اسم-التصنيف/c123 ، /اسم-الصفحة/page-123
PRODUCT_ID_RE = re.compile(r'^p-?\d+$', re.I)
CATEGORY_ID_RE = re.compile(r'^c-?\d+$', re.I)
INFO_ID_RE = re.compile(r'^page-?\d+$', re.I)
ARCHIVE_LAST_RE = re.compile(r'^(tag|author|category|archive)-?\d*$', re.I)

POLICY_KEYWORDS_NORM = None

def _policy_keywords_norm():
    global POLICY_KEYWORDS_NORM
    if POLICY_KEYWORDS_NORM is None:
        POLICY_KEYWORDS_NORM = set()
        for k in POLICY_KEYWORDS:
            for part in k.split('-'):
                POLICY_KEYWORDS_NORM.add(normalize_ar_token(part.lower()))
    return POLICY_KEYWORDS_NORM

def _slug_tokens(seg):
    return [normalize_ar_token(p.lower()) for p in seg.split('-') if p]

def segment_is_policy(seg):
    """كلمة واحدة من كلمات السياسات تكفي (للصفحات العامة)."""
    norm = _policy_keywords_norm()
    return any(p in norm for p in _slug_tokens(seg) if len(p) > 2)

def segment_is_mostly_policy(seg):
    """نصف كلمات الرابط على الأقل من كلمات السياسات (داخل المدونة فقط)،
    حتى لا يتحول مقال مثل «افضل-شركات-الشحن» إلى صفحة سياسة."""
    norm = _policy_keywords_norm()
    toks = [p for p in _slug_tokens(seg) if len(p) > 2]
    if not toks: return False
    return sum(1 for p in toks if p in norm) / len(toks) >= 0.5

def _has_jsonld_type(soup, wanted):
    if not soup: return False
    for tag in soup.find_all('script', attrs={'type': 'application/ld+json'}):
        try:
            data = json.loads(tag.string or '{}')
        except Exception:
            continue
        blocks = data if isinstance(data, list) else [data]
        for b in blocks:
            if not isinstance(b, dict):
                continue
            if '@graph' in b and isinstance(b['@graph'], list):
                for item in b['@graph']:
                    if not isinstance(item, dict):
                        continue
                    t = item.get('@type')
                    types = t if isinstance(t, list) else [t]
                    if any(str(x) in wanted for x in types if x):
                        return True
            t = b.get('@type')
            types = t if isinstance(t, list) else [t]
            if any(str(x) in wanted for x in types if x):
                return True
    return False

def _html_signals(soup):
    """يقرأ ما تعلنه الصفحة عن نفسها: product / article / collection / None"""
    if not soup: return None
    og_type = ""
    tag = soup.find('meta', attrs={'property': 'og:type'})
    if tag and tag.get('content'):
        og_type = tag['content'].lower()

    if 'product' in og_type \
            or soup.find(attrs={'itemtype': re.compile(r'schema\.org/Product', re.I)}) \
            or _has_jsonld_type(soup, ('Product', 'IndividualProduct')):
        return 'product'
    if 'article' in og_type or 'blog' in og_type \
            or soup.find(attrs={'itemtype': re.compile(r'schema\.org/(Article|BlogPosting|NewsArticle)', re.I)}) \
            or _has_jsonld_type(soup, ('Article', 'BlogPosting', 'NewsArticle')):
        return 'article'
    if soup.find(attrs={'itemtype': re.compile(r'schema\.org/CollectionPage', re.I)}) \
            or _has_jsonld_type(soup, ('CollectionPage',)):
        return 'collection'
    return None

def _url_segments(url):
    path = unquote(urlparse(clean_url(url)).path.lower()).strip('/')
    segs = [s for s in path.split('/') if s]
    if segs and segs[0] in LANG_SEGMENTS:   # /ar/... و /en/...
        segs = segs[1:]
    return segs

@lru_cache(maxsize=60000)
def _detect_type_by_url(url, base_url):
    return detect_page_type(url, base_url, None)

def detect_page_type(url, base_url, soup=None):
    url_clean = clean_url(url)
    segments = _url_segments(url_clean)

    # 1) الرئيسية (بما فيها /ar و /en)
    if not segments or url_key(url_clean) == url_key(normalize_url(base_url)):
        return T_HOME

    last = segments[-1]
    path_clean = '/'.join(segments)
    in_blog = any(s in BLOG_SEGMENTS for s in segments)

    # 2) أنماط الرابط القاطعة
    if PRODUCT_ID_RE.match(last):
        return T_PRODUCT
    if not in_blog and ('products' in segments[:-1] or 'product' in segments[:-1]):
        return T_PRODUCT
    if INFO_ID_RE.match(last):
        return T_INFO

    # 3) المدونة: تُحسم قبل كلمات السياسات
    if in_blog:
        if last in BLOG_SEGMENTS:                       # صفحة المدونة الرئيسية (قائمة مقالات)
            return T_ARCHIVE
        if CATEGORY_ID_RE.match(last) or ARCHIVE_LAST_RE.match(last) \
                or any(s in ARCHIVE_PARENT_SEGMENTS for s in segments[:-1]):
            return T_ARCHIVE
        sig = _html_signals(soup)
        if sig == 'article':
            return T_BLOG
        if sig == 'product':
            return T_PRODUCT
        slug = segments[-2] if re.fullmatch(r'[a-z]?-?\d+', last) and len(segments) >= 2 else last
        if segment_is_mostly_policy(slug):
            return T_INFO
        return T_BLOG

    # 4) التصنيفات بالرابط
    if CATEGORY_ID_RE.match(last) or path_clean in CATALOG_ROOTS \
            or any(s in CATEGORY_SEGMENTS for s in segments):
        return T_CATEGORY

    # 5) إشارات الصفحة نفسها (للمتاجر غير سلة وزد)
    sig = _html_signals(soup)
    if sig == 'product':
        return T_PRODUCT
    if sig == 'article':
        return T_BLOG
    if sig == 'collection':
        return T_CATEGORY

    # 6) الأرشيف (وسم/كاتب/سنة/ماركة)
    if ARCHIVE_LAST_RE.match(last) or re.match(r'^\d{4}$', last) \
            or (len(segments) >= 2 and any(s in ARCHIVE_PARENT_SEGMENTS for s in segments[:-1])):
        return T_ARCHIVE

    # 7) السياسات والصفحات التعريفية
    if any(segment_is_policy(seg) for seg in segments):
        return T_INFO

    # 8) أنماط ضعيفة أخيرة
    if '-p-' in path_clean or re.search(r'[-/]p-?\d{4,}', url_clean):
        return T_PRODUCT
    if re.search(r'[-/]c-?\d{3,}', url_clean):
        return T_CATEGORY

    return T_UNKNOWN

# ==============================================================
#  فحص معايير السيو والرموز والميتا
# ==============================================================
PLACEHOLDER_PATTERNS = [
    r'^\s*\[\s*[\.\-_]*\s*\]\s*$',
    r'\{\{.*?\}\}', r'\{%.*?%\}',
    r'^\s*[-_–—|•·\.\s]+\s*$',
    r'\b(undefined|null|nan|none|untitled|default)\b'
]

def is_title_symbol_or_placeholder(title):
    if not title: return True
    t = title.strip()
    if not re.search(r'[0-9a-zA-Z\u0600-\u06FF]', t): return True
    return any(re.search(pat, t, re.I) for pat in PLACEHOLDER_PATTERNS)

def grade_length(length, min_ok, min_optimal, max_len):
    if length == 0: return 'missing'
    if length < min_ok: return 'very_short'
    if length < min_optimal: return 'acceptable'
    if length <= max_len: return 'optimal'
    return 'long'

GENERIC_ALTS = {
    'image', 'images', 'img', 'photo', 'photos', 'picture', 'pic', 'icon', 'logo', 'product',
    'mobile image', 'desktop image', 'banner', 'slider', 'slide', 'hero', 'thumbnail',
    'thumb', 'mobile', 'desktop', 'cover', 'default', 'untitled',
    'صورة', 'صوره', 'صور', 'منتج', 'شعار', 'غلاف', 'رئيسية', 'جديد', 'خلفية'
}

def grade_alt(alt_text):
    txt = re.sub(r'\s+', ' ', str(alt_text or '')).strip()
    if not txt: return 'alt_missing', 0
    length = len(txt)
    low = txt.lower()

    if re.search(r'\.(jpg|jpeg|png|webp|gif|svg)$', low) or re.fullmatch(r'[\d\W_]+', txt):
        return 'alt_generic', length

    if low in GENERIC_ALTS:
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
    if not meta_title or not h1_text: return 'match_empty'
    t_clean = re.sub(r'[^\w\s\u0600-\u06FF]', '', meta_title.lower())
    h_clean = re.sub(r'[^\w\s\u0600-\u06FF]', '', h1_text.lower())
    h_words = set(h_clean.split())
    if not h_words: return 'match_empty'
    match_count = sum(1 for w in h_words if w in t_clean)
    return 'match_ok' if (match_count / len(h_words)) >= 0.5 else 'match_diff'

def extract_image_src(img):
    for attr in ['data-src', 'data-original', 'data-lazy', 'data-lazy-src', 'data-image']:
        val = img.get(attr)
        if val and val.strip(): return val.strip()
    return img.get('src', '').strip()

def clean_image_url(url):
    if not url: return ""
    u = url.strip()
    mo = re.search(r'/cdn-cgi/image/[^/]+/(https?://.+)$', u, re.I)
    if mo:
        u = mo.group(1)
    elif '/cdn-cgi/image/' in u.lower():
        u = re.sub(r'/cdn-cgi/image/[^/]+/', '/', u, flags=re.I)
    return u.split('?')[0].split('#')[0]

def is_relevant_seo_image(src, img):
    if not src or src.startswith('data:image'):
        return False
    s = src.lower()

    if any(k in s for k in [
        'static.zid.store', 'cdn.zid.store', 'assets.salla.sa',
        'cdn.salla.network/assets', 'shopifycloud', '/static/', 'static.'
    ]):
        return False

    junk = [
        'favicon', 'avatar', 'payment', 'tamara', 'tabby', 'mada', 'visa', 'mastercard',
        'apple-pay', 'applepay', 'stc-pay', 'stcpay', 'pixel', 'spinner', 'loader',
        'business_center', 'maroof', 'vat', 'tax', 'badge', 'icon', 'logo', 'brand',
        'whatsapp', 'snapchat', 'instagram', 'tiktok', 'twitter', 'smsa', 'aramex',
        'redbox', 'zidship', 'placeholder', 'empty.png', 'transparent', 'dummy'
    ]
    if any(k in s for k in junk):
        return False

    classes = ' '.join(img.get('class', [])).lower()
    img_id = (img.get('id') or '').lower()
    if any(k in classes or k in img_id for k in ['logo', 'brand', 'badge', 'icon', 'footer', 'header']):
        return False

    if s.split('?')[0].endswith(('.svg', '.ico', '.gif')):
        return False

    return True

def extract_page_links(soup, page_url, base_netloc):
    links = set()
    for a in soup.find_all('a', href=True):
        href = a['href'].strip()
        if href.startswith(('mailto:', 'tel:', 'javascript:', '#')): continue
        full = clean_url(urljoin(page_url, href))
        if is_crawlable(full, base_netloc): links.add(full)

    for card in soup.find_all(['salla-product-card', 'div', 'article'], attrs={'data-url': True}):
        full = clean_url(urljoin(page_url, card['data-url']))
        if is_crawlable(full, base_netloc): links.add(full)

    for el in soup.find_all(['salla-infinite-scroll', 'div'], attrs={'next-page': True}):
        next_p = el.get('next-page')
        if next_p:
            full = clean_url(urljoin(page_url, next_p))
            if is_crawlable(full, base_netloc): links.add(full)

    return links

def is_noindex(soup, res):
    header = (res.headers.get('X-Robots-Tag') or '').lower()
    if 'noindex' in header:
        return True
    for m in soup.find_all('meta', attrs={'name': re.compile(r'^(robots|googlebot)$', re.I)}):
        if 'noindex' in (m.get('content') or '').lower():
            return True
    return False

def audit_single_page(task, timeout=10):
    url, base_url, source = task
    base_netloc = urlparse(normalize_url(base_url)).netloc
    res = safe_get(url, timeout=timeout)

    if res is None or res.status_code != 200:
        # ملاحظة: لا نستخدم «if res» لأن الاستجابة 404/429 تُعتبر False في مكتبة requests
        code = str(res.status_code) if res is not None else 'فشل اتصال'
        return {
            'page_data': {
                # النوع يُستنتج من الرابط حتى لو لم تُفتح الصفحة
                'نوع الصفحة': _detect_type_by_url(clean_url(url), base_url),
                'الرابط': url, 'مصدر الاكتشاف': source,
                'متاحة': False, 'كود الاستجابة': code, 'قابلة للأرشفة': False,
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
    indexable = not is_noindex(soup, res)

    canonical = ''
    for link in soup.find_all('link', href=True):
        rel = link.get('rel') or []
        if isinstance(rel, str): rel = [rel]
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
        raw_src = extract_image_src(img)
        if raw_src and is_relevant_seo_image(raw_src, img):
            clean_src = clean_image_url(urljoin(final_url, raw_src))
            if not clean_src: continue

            total_img += 1
            alt_text = (img.get('alt') or '').strip()
            alt_st, alt_l = grade_alt(alt_text)
            if alt_st == 'alt_missing': missing_alt += 1
            elif alt_st in ('alt_generic', 'alt_stuffed', 'alt_long'): weak_alt += 1

            page_images.append({
                'رابط الصفحة': final_url, 'نوع الصفحة': page_type,
                'رابط الصورة': clean_src,
                'النص البديل الحالي (Alt)': alt_text,
                'حالة النص البديل': alt_st,
                'طول النص البديل': alt_l
            })

    html_snippet = res.text[:20000] if page_type == T_HOME else ''

    for s in soup(['script', 'style', 'nav', 'footer']): s.decompose()
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
            'متاحة': True, 'كود الاستجابة': '200', 'قابلة للأرشفة': indexable,
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
        'html': html_snippet
    }

# ==============================================================
#  قارئ الخرائط وحلقة الاستكشاف للملفات المقسمة
# ==============================================================
def fetch_sitemap_urls(base_url):
    base_clean = normalize_url(base_url)
    target_netloc = normalize_domain(urlparse(base_clean).netloc)
    found_urls = set()

    if HAS_ADVERTOOLS:
        try:
            sm_df = adv.sitemap_to_df(f"{base_clean}/sitemap.xml")
            if sm_df is not None and 'loc' in sm_df.columns:
                for loc in sm_df['loc'].dropna().tolist():
                    if normalize_domain(urlparse(loc).netloc) == target_netloc:
                        found_urls.add(clean_url(loc))
                if len(found_urls) > 5:
                    return found_urls
        except Exception:
            pass

    visited_maps = set()
    candidates = [
        f"{base_clean}/sitemap.xml", f"{base_clean}/sitemap_index.xml",
        f"{base_clean}/sitemap-1.xml", f"{base_clean}/sitemap_1.xml",
        f"{base_clean}/sitemap_products_1.xml", f"{base_clean}/sitemap-products-1.xml",
        f"{base_clean}/sitemap_categories_1.xml", f"{base_clean}/sitemap_pages_1.xml",
        f"{base_clean}/sitemap_brands_1.xml"
    ]

    res_r = safe_get(f"{base_clean}/robots.txt", timeout=8, retries=1)
    if res_r is not None and res_r.status_code == 200:
        for line in res_r.text.splitlines():
            if line.lower().strip().startswith('sitemap:'):
                sm = line.split(':', 1)[1].strip()
                if sm and sm not in candidates: candidates.append(sm)

    LOC_RE = re.compile(r'<loc>\s*(.*?)\s*</loc>', re.I | re.S)

    def parse_map(sm_url):
        if sm_url in visited_maps or len(visited_maps) > 60: return
        visited_maps.add(sm_url)
        res = safe_get(sm_url, timeout=8, retries=1)
        if res is None or res.status_code != 200: return
        content = res.content
        if sm_url.lower().endswith('.gz') or content[:2] == b'\x1f\x8b':
            try: content = gzip.decompress(content)
            except Exception: pass
        text = content.decode('utf-8', 'ignore')
        for loc in LOC_RE.findall(text):
            loc = loc.strip()
            clean_loc = loc.split('?')[0].lower()
            if clean_loc.endswith(('.xml', '.xml.gz')) or 'sitemap' in clean_loc:
                parse_map(loc)
            else:
                if normalize_domain(urlparse(loc).netloc) == target_netloc:
                    found_urls.add(clean_url(loc))

    for c in candidates:
        parse_map(c)

    # حلقة استكشاف خرائط سلة وزد المقسمة (sitemap-2.xml, sitemap_products_2.xml...)
    patterns = [
        ('sitemap-', ''),
        ('sitemap_', ''),
        ('sitemap_products_', ''),
        ('sitemap-products-', ''),
        ('sitemap_categories_', ''),
        ('sitemap_pages_', ''),
    ]
    for prefix, suffix in patterns:
        idx = 2
        fails = 0
        while idx <= 40:
            sm_url = f"{base_clean}/{prefix}{idx}{suffix}.xml"
            res = safe_get(sm_url, timeout=5, retries=0)
            if res is None or res.status_code != 200 or '<loc' not in res.text.lower():
                fails += 1
                if fails >= 2:
                    break
                idx += 1
                continue
            fails = 0
            parse_map(sm_url)
            idx += 1

    return found_urls

def get_unique_images(images_df):
    if images_df is None or images_df.empty:
        return images_df
    counts = images_df.groupby('رابط الصورة')['رابط الصفحة'].nunique()
    u_df = images_df.drop_duplicates(subset=['رابط الصورة']).copy()
    u_df['عدد الصفحات'] = u_df['رابط الصورة'].map(counts)
    return u_df.reset_index(drop=True)

# حصد ترقيم الأقسام
def harvest_category_pagination(base_url, listing_urls, seen_keys, max_pages, workers=6, progress_cb=None):
    base_netloc = urlparse(normalize_url(base_url)).netloc
    new_links = []

    def probe_page(task):
        cat_url, page_num = task
        sep = '&' if '?' in cat_url else '?'
        paged_url = f"{cat_url}{sep}page={page_num}"
        res = safe_get(paged_url, timeout=6, retries=0)
        if res is None or res.status_code != 200:
            return []
        soup = make_soup(res.text)
        return list(extract_page_links(soup, paged_url, base_netloc))

    for cat_url in list(listing_urls)[:25]:
        page_idx = 2
        while page_idx <= 25:
            if len(seen_keys) + len(new_links) >= max_pages:
                break

            tasks = [(cat_url, p) for p in range(page_idx, min(page_idx + workers, 26))]
            with ThreadPoolExecutor(max_workers=workers) as ex:
                batch_results = list(ex.map(probe_page, tasks))

            fresh_count = 0
            for link_list in batch_results:
                for link in link_list:
                    k = url_key(link)
                    if k not in seen_keys:
                        seen_keys.add(k)
                        new_links.append(link)
                        fresh_count += 1

            if fresh_count == 0:
                break
            page_idx += workers

    return new_links

# جولة إعادة هادئة للصفحات التي رفضها المتجر مؤقتاً (صفحة واحدة كل مرة)
def retry_failed_pages(pages_result, images_result, target, linked_keys,
                       progress_cb=None, delay=1.0, limit=300):
    idxs = [i for i, p in enumerate(pages_result)
            if not p['متاحة'] and p['كود الاستجابة'] in RETRYABLE_CODES][:limit]
    if not idxs:
        return
    time.sleep(3)  # نعطي المتجر فرصة يهدأ
    for n, i in enumerate(idxs, 1):
        old = pages_result[i]
        res = audit_single_page((old['الرابط'], target, old['مصدر الاكتشاف']), timeout=15)
        pages_result[i] = res['page_data']
        images_result.extend(res['images_data'])
        for link in res['links']:
            linked_keys.add(url_key(link))
        if progress_cb:
            pct = 0.94 + 0.04 * (n / len(idxs))
            progress_cb(pct, f"إعادة فحص هادئة للصفحات المتعثرة: {n}/{len(idxs)} ({int(pct * 100)}%)")
        time.sleep(delay)

# ==============================================================
#  محرك الفحص الشامل (Run Full Audit)
# ==============================================================
CONTENT_TYPES = {T_PRODUCT, T_CATEGORY, T_BLOG, T_INFO}

def run_full_audit(target_url, max_pages=1500, workers=8, progress_cb=None):
    target = normalize_url(target_url)
    if progress_cb: progress_cb(0.05, "جلب وقراءة خرائط الموقع... (5%)")

    sitemap_urls = fetch_sitemap_urls(target)

    discovered_seeds = set()
    for seed in [f"{target}/products", f"{target}/latest-products", f"{target}/categories"]:
        res_seed = safe_get(seed, timeout=5, retries=0)
        if res_seed is not None and res_seed.status_code == 200:
            discovered_seeds.add(seed)

    queue = list(dict.fromkeys([target] + list(sitemap_urls) + list(discovered_seeds)))
    seen = {url_key(u) for u in queue}

    pages_result, images_result = [], []
    internally_linked_keys = set()
    category_urls = set()
    platform, done_count = 'unknown', 0

    # الجولة الأولى
    while queue and len(pages_result) < max_pages:
        batch = queue[:workers * 4]
        queue = queue[workers * 4:]
        tasks = [(u, target, 'خريطة الموقع' if u in sitemap_urls else 'رابط داخلي') for u in batch]

        with ThreadPoolExecutor(max_workers=workers) as ex:
            results = list(ex.map(audit_single_page, tasks))

        for res in results:
            p_data = res['page_data']
            pages_result.append(p_data)
            images_result.extend(res['images_data'])

            if res.get('html') and platform == 'unknown':
                platform = detect_platform(res['html'], url=target)

            if p_data['نوع الصفحة'] == T_CATEGORY and p_data['متاحة']:
                category_urls.add(p_data['الرابط'])

            for link in res['links']:
                k = url_key(link)
                internally_linked_keys.add(k)
                if k not in seen and len(seen) < max_pages:
                    seen.add(k)
                    queue.append(link)

            done_count += 1
            if progress_cb:
                est_total = min(max_pages, max(done_count + len(queue), 1))
                pct = min(0.92, 0.05 + 0.87 * (done_count / est_total))
                progress_cb(pct, f"جارٍ الفحص: {done_count} صفحة ({int(pct * 100)}%)")

    # الجولة الثانية: ترقيم الأقسام
    if len(pages_result) < max_pages:
        if progress_cb: progress_cb(0.93, "متابعة ترقيم الأقسام... (93%)")
        harvest_seeds = list(category_urls) + [f"{target}/products", f"{target}/latest-products"]
        extra_products = harvest_category_pagination(target, harvest_seeds, seen, max_pages, workers=workers)

        if extra_products:
            extra_tasks = [(u, target, 'ترقيم وتمرير') for u in extra_products[:max_pages - len(pages_result)]]
            with ThreadPoolExecutor(max_workers=workers) as ex:
                extra_results = list(ex.map(audit_single_page, extra_tasks))
            for res in extra_results:
                pages_result.append(res['page_data'])
                images_result.extend(res['images_data'])

    # الجولة الثالثة: إعادة هادئة للصفحات المتعثرة
    retry_failed_pages(pages_result, images_result, target, internally_linked_keys, progress_cb)

    full_df = pd.DataFrame(pages_result).drop_duplicates(subset=['الرابط']).reset_index(drop=True)
    full_df['_key'] = full_df['الرابط'].map(url_key)
    full_df = full_df.drop_duplicates(subset=['_key']).reset_index(drop=True)

    sitemap_keys = {url_key(u) for u in sitemap_urls}

    # الصفحات المستبعدة: محذوفة (404/410) أو مخفية عن جوجل (noindex)
    gone_mask = full_df['كود الاستجابة'].isin(GONE_CODES)
    noindex_mask = (full_df['متاحة'] == True) & (full_df['قابلة للأرشفة'] == False)
    dead_pages = full_df[gone_mask & full_df['_key'].isin(sitemap_keys)]['الرابط'].tolist()
    noindex_pages = full_df[noindex_mask]['الرابط'].tolist()

    # التقرير يشمل فقط الصفحات الموجودة والمسموح لجوجل بعرضها
    df = full_df[~gone_mask & ~noindex_mask].reset_index(drop=True)
    kept_keys = set(df['_key'])
    df = df.drop(columns=['_key'])

    raw_imgs_df = pd.DataFrame(images_result)
    if not raw_imgs_df.empty:
        raw_imgs_df = raw_imgs_df[raw_imgs_df['رابط الصفحة'].map(url_key).isin(kept_keys)]
    imgs_df = get_unique_images(raw_imgs_df)

    if imgs_df is not None and not imgs_df.empty:
        counts = imgs_df[imgs_df['حالة النص البديل'] == 'alt_ok']['النص البديل الحالي (Alt)'].value_counts()
        dupes = set(counts[counts >= ALT_DUP_THRESHOLD].index)
        if dupes:
            imgs_df.loc[imgs_df['النص البديل الحالي (Alt)'].isin(dupes), 'حالة النص البديل'] = 'alt_duplicate'

    valid_titles = df[df['عنوان الميتا'].str.strip() != '']['عنوان الميتا']
    dup_titles = set(valid_titles[valid_titles.duplicated()].unique())
    valid_descs = df[df['وصف الميتا'].str.strip() != '']['وصف الميتا']
    dup_descs = set(valid_descs[valid_descs.duplicated()].unique())

    live_df = df[df['متاحة'] == True]
    live_keys = set(live_df['الرابط'].map(url_key))
    target_k = url_key(target)

    # 1. صفحات محتوى حقيقية (منتج/تصنيف/مقال/صفحة تعريفية) غائبة عن الخريطة
    unlisted_pages = live_df[
        live_df['نوع الصفحة'].isin(CONTENT_TYPES) &
        (~live_df['الرابط'].map(url_key).isin(sitemap_keys))
    ]['الرابط'].tolist()

    # 2. الصفحات اليتيمة: بالخريطة وليست الرئيسية وبلا أي رابط داخلي
    orphan_pages = []
    for u in sitemap_urls:
        k = url_key(u)
        if k in live_keys and k != target_k and k not in internally_linked_keys:
            orphan_pages.append(u)

    unreachable = df[df['متاحة'] == False]

    coverage = {
        'sitemap_count': len(sitemap_urls),
        'unlisted_pages': unlisted_pages,
        'orphan_pages': orphan_pages,
        'dead_pages': dead_pages,
        'noindex_pages': noindex_pages,
        'unreachable_pages': unreachable['الرابط'].tolist(),
        'unreachable_codes': unreachable['كود الاستجابة'].value_counts().to_dict(),
    }

    def type_count(t):
        return int((df['نوع الصفحة'] == t).sum())

    summary = {
        'total_pages': len(df),
        'score': round(live_df['درجة السيو'].mean(), 1) if not live_df.empty else 0,
        'products': type_count(T_PRODUCT),
        'categories': type_count(T_CATEGORY),
        'info_pages': type_count(T_INFO),
        'blog_pages': type_count(T_BLOG),
        'archive_pages': type_count(T_ARCHIVE),
        'unknown_pages': type_count(T_UNKNOWN),
        'broken_pages': len(unreachable),
        'excluded_pages': len(dead_pages) + len(noindex_pages),
        'missing_titles': int((df['حالة العنوان'] == 'missing').sum()),
        'duplicate_titles': len(dup_titles),
        'title_mismatch': int((df['مطابقة العنوان مع H1'] == 'match_diff').sum()),
        'missing_descs': int((df['حالة الوصف'] == 'missing').sum()),
        'short_descs': int((df['حالة الوصف'] == 'very_short').sum()),
        'duplicate_descs': len(dup_descs),
        'total_images': len(imgs_df) if imgs_df is not None and not imgs_df.empty else 0,
        'missing_alts': int((imgs_df['حالة النص البديل'] == 'alt_missing').sum()) if imgs_df is not None and not imgs_df.empty else 0,
        'weak_alts': int(imgs_df['حالة النص البديل'].isin(['alt_generic', 'alt_stuffed', 'alt_duplicate', 'alt_long']).sum()) if imgs_df is not None and not imgs_df.empty else 0,
        'platform': platform
    }

    return df, imgs_df, summary, coverage, dup_titles, dup_descs
