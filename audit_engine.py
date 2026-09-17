import requests
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
import pandas as pd
import time
import gzip
import re
from functools import lru_cache
import threading
from urllib.parse import urlparse, urljoin, unquote
from concurrent.futures import ThreadPoolExecutor

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
        'match_ok': 'متطابق مع H1', 'match_diff': 'مختلف عن H1', 'match_empty': 'غير متوفر',
    }
}

TITLE_MAX, TITLE_MIN_OPTIMAL, TITLE_MIN_OK = 60, 50, 30
DESC_MAX, DESC_MIN_OPTIMAL, DESC_MIN_OK = 150, 120, 70
ALT_MAX = 125
ALT_DUP_THRESHOLD = 3

COLOR = {'ok': '#059669', 'warn': '#d97706', 'bad': '#dc2626', 'neutral': '#475569',
         'accent': '#0f172a', 'muted': '#94a3b8'}

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
    if not url: return ""
    url = url.strip()
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    return url.rstrip('/')

def clean_url(url):
    if not url: return ""
    return url.split('#')[0].split('?')[0].rstrip('/')

PLATFORM_ID_RE = re.compile(r'^(p|c|a|page|tag|category|product)-?(\d{4,})$', re.I)

@lru_cache(maxsize=50000)
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
    if not url: return False
    p = urlparse(url)
    if p.scheme not in ('http', 'https'): return False
    if normalize_domain(p.netloc) != normalize_domain(base_netloc): return False
    path = unquote(p.path.lower())
    if path.endswith(BAD_EXTENSIONS): return False
    if any(part in path for part in EXCLUDE_PATH_PARTS): return False
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
    'image', 'img', 'photo', 'picture', 'pic', 'icon', 'logo', 'product',
    'صورة', 'صوره', 'صور', 'منتج', 'شعار', 'غلاف', 'رئيسية', 'جديد'
}

def grade_alt(alt_text):
    txt = re.sub(r'\s+', ' ', str(alt_text or '')).strip()
    if not txt: return 'alt_missing', 0
    length = len(txt)
    low = txt.lower()

    if re.search(r'\.(jpg|jpeg|png|webp|gif|svg)$', low) or re.fullmatch(r'[\d\W_]+', txt):
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

# فلتر استبعاد صور القوالب وأصول المنصة (مثل static.zid.store والشعارات)
def is_relevant_seo_image(src, img):
    if not src or src.startswith('data:image'):
        return False
    s = src.lower()

    # 1. استبعاد ملفات وأصول منصات زد وسلة وشوبيفاي الثابتة
    if any(k in s for k in [
        'static.zid.store', 'cdn.zid.store/assets', 'assets.salla.sa',
        'cdn.salla.network/assets', 'shopifycloud', '/static/', 'static.'
    ]):
        return False

    # 2. استبعاد صور النظام والشعارات الشائعة وأيقونات الدفع والشحن
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
        src = extract_image_src(img)
        if src and is_relevant_seo_image(src, img):
            total_img += 1
            full_img_url = urljoin(final_url, src)
            alt_text = (img.get('alt') or '').strip()
            alt_st, alt_l = grade_alt(alt_text)
            if alt_st == 'alt_missing': missing_alt += 1
            elif alt_st in ('alt_generic', 'alt_stuffed', 'alt_long'): weak_alt += 1

            page_images.append({
                'رابط الصفحة': final_url, 'نوع الصفحة': page_type,
                'رابط الصورة': full_img_url,
                'النص البديل الحالي (Alt)': alt_text,
                'حالة النص البديل': alt_st,
                'طول النص البديل': alt_l
            })

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

LOC_RE = re.compile(r'<loc>\s*(.*?)\s*</loc>', re.I | re.S)

def fetch_sitemap_urls(base_url):
    base_clean = normalize_url(base_url)
    target_netloc = normalize_domain(urlparse(base_clean).netloc)
    found_urls, visited_maps = set(), set()

    candidates = [
        f"{base_clean}/sitemap.xml", f"{base_clean}/sitemap_index.xml",
        f"{base_clean}/sitemap_products_1.xml", f"{base_clean}/sitemap_categories_1.xml",
        f"{base_clean}/sitemap_pages_1.xml",
    ]

    res_r = safe_get(f"{base_clean}/robots.txt", timeout=8, retries=1)
    if res_r and res_r.status_code == 200:
        for line in res_r.text.splitlines():
            if line.lower().strip().startswith('sitemap:'):
                sm = line.split(':', 1)[1].strip()
                if sm and sm not in candidates: candidates.append(sm)

    def parse_map(sm_url):
        if sm_url in visited_maps or len(visited_maps) > 25: return
        visited_maps.add(sm_url)
        res = safe_get(sm_url, timeout=15, retries=1)
        if not res or res.status_code != 200: return
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

    for c in candidates: parse_map(c)
    return found_urls

# دالة فلترة وتوحيد الصور الفريدة مع حساب مرات الظهور
def get_unique_images(images_df):
    if images_df is None or images_df.empty:
        return images_df
    counts = images_df.groupby('رابط الصورة')['رابط الصفحة'].nunique()
    u_df = images_df.drop_duplicates(subset=['رابط الصورة']).copy()
    u_df['عدد الصفحات'] = u_df['رابط الصورة'].map(counts)
    return u_df.reset_index(drop=True)

def run_full_audit(target_url, max_pages=1500, workers=4, progress_cb=None):
    target = normalize_url(target_url)
    if progress_cb: progress_cb(0.05, "جلب وفحص خريطة الموقع (Sitemap)... (5%)")

    sitemap_urls = fetch_sitemap_urls(target)
    queue = list(sitemap_urls) if sitemap_urls else []
    if target not in queue: queue.insert(0, target)

    seen = {url_key(u) for u in queue}
    pages_result, images_result, visited_keys = [], [], set()
    platform, done_count = 'unknown', 0

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
                progress_cb(pct, f"جارٍ الفحص: {done_count} من أصل {est_total} صفحة ({int(pct * 100)}%)")

    df = pd.DataFrame(pages_result).drop_duplicates(subset=['الرابط']).reset_index(drop=True)
    raw_imgs_df = pd.DataFrame(images_result)

    # احتساب وتحليل الصور بناءً على الصور الفريدة فقط لمنع التكرار
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
        'total_images': len(imgs_df) if imgs_df is not None and not imgs_df.empty else 0,
        'missing_alts': int((imgs_df['حالة النص البديل'] == 'alt_missing').sum()) if imgs_df is not None and not imgs_df.empty else 0,
        'weak_alts': int(imgs_df['حالة النص البديل'].isin(['alt_generic', 'alt_stuffed', 'alt_duplicate', 'alt_long']).sum()) if imgs_df is not None and not imgs_df.empty else 0,
        'platform': platform
    }

    return df, imgs_df, summary, coverage, dup_titles, dup_descs
