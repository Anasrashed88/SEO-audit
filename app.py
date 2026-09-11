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
#
#  مبدأ الفحص: يبدأ من الصفحة الرئيسية ويتصفح المتجر كما يتصفحه
#  الزائر. لا تدخل التقرير أي صفحة لا يمكن للزائر الوصول إليها.
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
MAX_PAGINATION_DEPTH = 40
MAX_CRAWL_LEVELS = 8

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept-Language': 'ar,en;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
}

# مفاتيح ثابتة لأنواع الصفحات (مستقلة عن لغة العرض)
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
    'ar': {'ok': 'سليم', 'missing': 'مفقود', 'short': 'قصير جداً', 'long': 'طويل جداً',
           'failed': 'تعذر الفحص', 'good': 'جيد', 'thin': 'ضعيف جداً', 'na': 'غير متاح',
           'alt_ok': 'سليم ومكتمل', 'alt_missing': 'مفقود', 'alt_empty': 'لا يوجد (فارغ)'},
    'en': {'ok': 'OK', 'missing': 'Missing', 'short': 'Too short', 'long': 'Too long',
           'failed': 'Scan failed', 'good': 'Good', 'thin': 'Thin content', 'na': 'N/A',
           'alt_ok': 'Present', 'alt_missing': 'Missing', 'alt_empty': '(empty)'},
}

COL_EN = {
    'نوع الصفحة': 'Page Type', 'الرابط': 'URL', 'الرابط الكانوني': 'Canonical URL',
    'مصدر الاكتشاف': 'Discovered Via', 'متاحة': 'Reachable', 'كود الاستجابة': 'Status Code',
    'درجة السيو': 'SEO Score', 'عنوان الميتا': 'Meta Title', 'حالة العنوان': 'Title Status',
    'وصف الميتا': 'Meta Description', 'حالة الوصف': 'Description Status',
    'إجمالي الصور': 'Total Images', 'صور بدون Alt': 'Images Missing Alt',
    'عدد الكلمات': 'Word Count', 'حالة المحتوى': 'Content Status', 'لغة الصفحة': 'Page Language',
    'رابط الصفحة': 'Page URL', 'رابط الصورة': 'Image URL',
    'النص البديل الحالي (Alt)': 'Current Alt Text', 'حالة النص البديل': 'Alt Status',
}


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
        blog_pages_count INTEGER, data_json TEXT, images_json TEXT, coverage_json TEXT
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

for key, default in [('audit_df', None), ('images_df', None), ('summary', None),
                     ('current_url', ""), ('coverage', None), ('report_lang', 'ar')]:
    if key not in st.session_state:
        st.session_state[key] = default

st.markdown("""
    <style>
    .main { direction: rtl; text-align: right; }
    h1, h2, h3, h4, p, span, div { text-align: right; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
    .metric-card { background-color:#1e293b; border:1px solid #334155; border-radius:10px;
                   padding:12px; text-align:center; margin-bottom:10px; }
    .metric-value { font-size:24px; font-weight:bold; color:#38bdf8; }
    .metric-label { font-size:13px; color:#94a3b8; }
    </style>
""", unsafe_allow_html=True)


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


# الصفحات التي لا يفحصها الزائر بحثاً عن محتوى (سلة، حساب، بحث...)
EXCLUDE_PATH_PARTS = [
    '/cart', '/checkout', '/login', '/signin', '/register', '/signup', '/account',
    '/my-account', '/wishlist', '/favorites', '/compare', '/search', '/orders',
    '/customer', '/password', '/thank-you', '/logout', '/tag/', '/tags/',
    '/سلة', '/حسابي', '/تسجيل', '/الدفع', '/بحث', '/المفضلة',
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
#  تصنيف الصفحات (يعمل على المتاجر العربية والإنجليزية)
# ==============================================================
POLICY_KEYWORDS = [
    'سياسة', 'شروط', 'خصوصية', 'استبدال', 'استرجاع', 'شحن', 'توصيل', 'شكاوى',
    'اسئلة', 'أسئلة', 'من-نحن', 'اتصل', 'ضمان', 'الدفع',
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

    # المنتجات أولاً — إشارات قاطعة قبل أي مطابقة بالكلمات
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

    # المدونة
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

    for seg in segments:
        if any(seg == k or seg.startswith(k + '-') or k in seg.split('-')
               for k in POLICY_KEYWORDS):
            return T_INFO

    if soup and soup.find(attrs={'itemtype': re.compile(r'schema\.org/CollectionPage', re.I)}):
        return T_CATEGORY
    if any(s in CATEGORY_SEGMENTS for s in segments):
        return T_CATEGORY
    if re.search(r'/c\d+', path) or any(re.match(r'^c\d+$', s) for s in segments):
        return T_CATEGORY

    return T_UNKNOWN


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


def detect_page_language(soup, text_sample=""):
    """لغة الصفحة من وسم <html lang> وإلا من نسبة الحروف العربية."""
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
#  فحص صفحة واحدة + استخراج روابطها
# ==============================================================
def broken_page_row(url, reason, source):
    return {
        'page_data': {
            'نوع الصفحة': T_BROKEN, 'الرابط': url, 'الرابط الكانوني': url,
            'مصدر الاكتشاف': source, 'متاحة': False, 'كود الاستجابة': str(reason),
            'لغة الصفحة': '—', 'درجة السيو': None,
            'عنوان الميتا': '', 'حالة العنوان': 'failed',
            'وصف الميتا': '', 'حالة الوصف': 'failed',
            'إجمالي الصور': 0, 'صور بدون Alt': 0,
            'عدد الكلمات': 0, 'حالة المحتوى': 'na',
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
    if 'html' not in ctype and ctype:
        return broken_page_row(clean_url(res.url), 'ليست صفحة HTML', source)

    final_url = clean_url(res.url)
    soup = make_soup(res.text)
    page_type = detect_page_type(final_url, base_url, soup)

    # الروابط الخارجة (للزحف)
    base_netloc = urlparse(normalize_url(base_url)).netloc
    links = set()
    for a in soup.find_all('a', href=True):
        href = a['href'].strip()
        if href.startswith(('mailto:', 'tel:', 'javascript:', '#')):
            continue
        full = clean_url(urljoin(final_url, href))
        if is_crawlable(full, base_netloc):
            links.add(full)

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
        title_status = 'missing'
    elif len(title) < 30:
        title_status = 'short'
    elif len(title) > 65:
        title_status = 'long'
    else:
        title_status = 'ok'

    desc_tag = (soup.find('meta', attrs={'name': 'description'})
                or soup.find('meta', attrs={'property': 'og:description'}))
    meta_desc = desc_tag['content'].strip() if desc_tag and desc_tag.get('content') else ''
    if not meta_desc:
        desc_status = 'missing'
    elif len(meta_desc) < 70:
        desc_status = 'short'
    elif len(meta_desc) > 165:
        desc_status = 'long'
    else:
        desc_status = 'ok'

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
                'النص البديل الحالي (Alt)': alt_text,
                'حالة النص البديل': 'alt_ok' if alt_text else 'alt_missing',
            })

    for s in content_soup(['script', 'style', 'noscript']):
        s.decompose()
    body_text = content_soup.get_text(separator=' ', strip=True)
    words = len(body_text.split())
    content_status = 'good' if words >= 50 else 'thin'
    page_lang = detect_page_language(soup, (title + ' ' + body_text[:500]))

    score = 100
    if title_status != 'ok':
        score -= 25
    if desc_status != 'ok':
        score -= 25
    if total_img > 0 and missing_alt > 0:
        score -= int((missing_alt / total_img) * 25)
    if content_status != 'good':
        score -= 25
    score = max(0, score)

    return {
        'page_data': {
            'نوع الصفحة': page_type, 'الرابط': final_url, 'الرابط الكانوني': canonical,
            'مصدر الاكتشاف': source, 'متاحة': True, 'كود الاستجابة': '200',
            'لغة الصفحة': page_lang, 'درجة السيو': score,
            'عنوان الميتا': title, 'حالة العنوان': title_status,
            'وصف الميتا': meta_desc, 'حالة الوصف': desc_status,
            'إجمالي الصور': total_img, 'صور بدون Alt': missing_alt,
            'عدد الكلمات': words, 'حالة المحتوى': content_status,
        },
        'images_data': page_images,
        'links': links,
    }


# ==============================================================
#  الزحف من الواجهة (رؤية الزائر)
# ==============================================================
def crawl_store(base_url, max_pages, workers, progress_cb=None, max_levels=MAX_CRAWL_LEVELS):
    """يبدأ من الصفحة الرئيسية ويتبع الروابط الداخلية كما يفعل الزائر.
    كل صفحة تُجلب مرة واحدة، وتُفحص وتُستخرج روابطها في نفس الطلب."""
    base_url = normalize_url(base_url)
    base_netloc = urlparse(base_url).netloc

    pages, images = [], []
    seen = {url_key(base_url)}
    frontier = [base_url]
    category_urls = []
    level = 0

    while frontier and len(pages) < max_pages and level < max_levels:
        level += 1
        room = max_pages - len(pages)
        batch, frontier = frontier[:room], frontier[room:]
        next_frontier = []

        with ThreadPoolExecutor(max_workers=workers) as ex:
            for res in ex.map(fetch_and_audit,
                              [(u, base_url, 'الزحف من الواجهة') for u in batch]):
                pd_row = res['page_data']
                pages.append(pd_row)
                images.extend(res['images_data'])
                if pd_row['نوع الصفحة'] in (T_CATEGORY, T_HOME):
                    category_urls.append(pd_row['الرابط'])
                for link in res['links']:
                    k = url_key(link)
                    if k not in seen:
                        seen.add(k)
                        next_frontier.append(link)

        frontier = next_frontier + frontier
        if progress_cb:
            progress_cb(len(pages), len(frontier), level)

    return pages, images, category_urls, seen


def harvest_paginated_products(base_url, category_urls, seen_keys, progress_cb=None,
                               max_depth=MAX_PAGINATION_DEPTH):
    """يتابع ترقيم صفحات الأقسام (?page=2,3...) لالتقاط المنتجات التي
    لا تظهر في الصفحة الأولى — الزائر يصل إليها بالضغط على التالي."""
    base_url = normalize_url(base_url)
    base_netloc = urlparse(base_url).netloc
    roots = list(dict.fromkeys(
        list(category_urls) + [f"{base_url}/{r}" for r in ['products', 'collections/all', 'shop']]
    ))
    new_urls = []
    fetched = 0

    for idx, cat in enumerate(roots):
        seen_here = set()
        for page in range(2, max_depth + 1):
            res = safe_get(f"{cat}?page={page}", retries=1)
            fetched += 1
            if res is None or res.status_code != 200:
                break
            soup = make_soup(res.text)
            found_here = set()
            for a in soup.find_all('a', href=True):
                full = clean_url(urljoin(cat, a['href'].strip()))
                if not is_crawlable(full, base_netloc):
                    continue
                if detect_page_type(full, base_url, None) == T_PRODUCT:
                    found_here.add(full)
            fresh = found_here - seen_here
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
#  خريطة الموقع — للمقارنة فقط، لا تدخل أرقام الفحص
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

    candidates = discover_sitemaps_from_robots(base_url) + [
        f"{base_url}/sitemap.xml", f"{base_url}/sitemap_index.xml",
        f"{base_url}/sitemap_products_1.xml", f"{base_url}/sitemap_pages_1.xml",
    ]
    for c in candidates:
        walk(c, 0)
    return urls


def build_coverage_report(visible_products, sitemap_urls, base_url):
    """مقارنة بين ما يراه الزائر وما تعلنه خريطة الموقع.
    نتائجها تشخيصية فقط ولا تدخل في أرقام الفحص."""
    vis = {}
    for u in visible_products:
        vis.setdefault(url_key(u), u)

    sm_products = {}
    for u in sitemap_urls:
        if detect_page_type(u, base_url, None) == T_PRODUCT:
            sm_products.setdefault(url_key(u), u)

    vis_keys, sm_keys = set(vis), set(sm_products)
    return {
        'visible_count': len(vis_keys),
        'sitemap_count': len(sm_keys),
        'matched_count': len(vis_keys & sm_keys),
        'visible_not_in_sitemap': sorted(vis[k] for k in (vis_keys - sm_keys)),
        'sitemap_not_visible': sorted(sm_products[k] for k in (sm_keys - vis_keys)),
        'indexed_pct': round(len(vis_keys & sm_keys) / len(vis_keys) * 100, 1)
        if vis_keys else 100.0,
    }


# ==============================================================
#  تجميع النتائج
# ==============================================================
def dedupe_pages(df):
    if df.empty:
        return df
    df = df.copy()
    df['_key'] = df['الرابط'].map(url_key)
    df['_canon'] = df['الرابط الكانوني'].map(url_key)
    df = df.drop_duplicates(subset=['_key'])
    avail = df[df['متاحة'] == True]  # noqa: E712
    dup_keys = set(avail[avail.duplicated(subset=['_canon'], keep='first')]['_key'])
    df = df[~df['_key'].isin(dup_keys)]
    return df.drop(columns=['_key', '_canon']).reset_index(drop=True)


def compute_summary(df, coverage=None):
    ok = df[df['متاحة'] == True]  # noqa: E712
    s = {
        'total_pages': len(df),
        'score': round(ok['درجة السيو'].mean(), 1) if not ok.empty else 0.0,
        'products': int((df['نوع الصفحة'] == T_PRODUCT).sum()),
        'categories': int((df['نوع الصفحة'] == T_CATEGORY).sum()),
        'info_pages': int((df['نوع الصفحة'] == T_INFO).sum()),
        'blog_pages': int((df['نوع الصفحة'] == T_BLOG).sum()),
        'unclassified': int((df['نوع الصفحة'] == T_UNKNOWN).sum()),
        'broken_pages': int((df['متاحة'] == False).sum()),  # noqa: E712
        'bad_titles': int((ok['حالة العنوان'] != 'ok').sum()),
        'bad_descs': int((ok['حالة الوصف'] != 'ok').sum()),
        'missing_alts': int(ok['صور بدون Alt'].sum()),
        'total_images': int(ok['إجمالي الصور'].sum()),
        'coverage_enabled': bool(coverage),
    }
    if coverage:
        s.update({
            'visible_products': coverage['visible_count'],
            'sitemap_products': coverage['sitemap_count'],
            'not_indexed_count': len(coverage['visible_not_in_sitemap']),
            'hidden_count': len(coverage['sitemap_not_visible']),
            'indexed_pct': coverage['indexed_pct'],
        })
    return s


def localize_df(df, lang):
    """تحويل المفاتيح الداخلية إلى نصوص معروضة بلغة التقرير."""
    if df is None or df.empty:
        return df
    out = df.copy()
    if 'نوع الصفحة' in out.columns:
        out['نوع الصفحة'] = out['نوع الصفحة'].map(
            lambda v: PAGE_TYPE_LABEL[lang].get(v, v))
    for col in ['حالة العنوان', 'حالة الوصف', 'حالة المحتوى', 'حالة النص البديل']:
        if col in out.columns:
            out[col] = out[col].map(lambda v: STATUS_LABEL[lang].get(v, v))
    if 'النص البديل الحالي (Alt)' in out.columns:
        empty_label = STATUS_LABEL[lang]['alt_empty']
        out['النص البديل الحالي (Alt)'] = out['النص البديل الحالي (Alt)'].map(
            lambda v: v if str(v).strip() else empty_label)
    if lang == 'en':
        out = out.rename(columns={k: v for k, v in COL_EN.items() if k in out.columns})
    return out


# ==============================================================
#  تقرير العميل (PDF) — عربي أو إنجليزي
# ==============================================================
PDF_TXT = {
    'ar': {
        'owner': 'أنس راشد', 'role': 'خبير تحسين محركات البحث',
        'title': 'تقرير الفحص الفني الشامل لمحركات البحث',
        'meta': 'المتجر المستهدف: {d}   |   تاريخ الفحص: {t}',
        'score': 'درجة التوافق العامة مع محركات البحث: {s}%',
        'scope': 'نطاق الفحص: الصفحات والمنتجات المعروضة فعلياً لزوار المتجر',
        'tbl1': '1. جدول تدقيق بنية الصفحات والعناوين:',
        'tbl2': '2. جدول تدقيق وسوم وصور المتجر:',
        'tbl3': '3. جدول مقارنة المعروض بخريطة الموقع:',
        'diag': '{n}. التشخيص الاستشاري وخطة العمل:',
        'h_val': 'الحالة / العدد', 'h_item': 'عنصر الفحص والتدقيق',
        'r_total': 'إجمالي الصفحات المعروضة والمفحوصة', 'u_page': 'صفحة',
        'r_products': 'صفحات المنتجات المعروضة', 'u_product': 'منتج',
        'r_categories': 'صفحات الأقسام والكولكشنات', 'u_cat': 'تصنيف',
        'r_blog': 'مقالات وصفحات المدونة', 'u_article': 'مقال',
        'r_info': 'الصفحات التعريفية والسياسات',
        'r_broken': 'روابط معطلة داخل المتجر', 'u_link': 'رابط',
        'r_titles': 'عناوين الميتا المفقودة أو غير المتوافقة', 'u_title': 'عنوان',
        'r_descs': 'أوصاف الميتا المفقودة أو غير المهيأة', 'u_desc': 'وصف',
        'r_imgs': 'إجمالي صور المحتوى والمنتجات', 'u_img': 'صورة',
        'r_noalt': 'صور تفتقر لوسم النص البديل', 'r_ratio': 'نسبة الصور غير المهيأة',
        'r_imgstate': 'حالة تهيئة الصور لبحث صور جوجل',
        'img_none': 'لم يرصد الفحص صور محتوى', 'img_ok': 'مكتمل',
        'img_gap': 'فجوة واسعة', 'img_part': 'فجوة جزئية',
        'r_vis': 'منتجات معروضة لزوار المتجر',
        'r_sm': 'منتجات معلنة في خريطة الموقع',
        'r_notidx': 'منتجات معروضة ولا تظهر في الخريطة',
        'r_hidden': 'روابط في الخريطة لا يصل إليها الزائر',
        'r_idxpct': 'نسبة المنتجات المعروضة المدرجة في الخريطة',
        'footer': 'anasrashed.com   |   anas@anasrashed.com',
    },
    'en': {
        'owner': 'Anas Rashed', 'role': 'SEO Expert',
        'title': 'Comprehensive Technical SEO Audit Report',
        'meta': 'Store: {d}   |   Audit date: {t}',
        'score': 'Overall search engine compliance score: {s}%',
        'scope': 'Audit scope: pages and products actually visible to store visitors',
        'tbl1': '1. Page structure and metadata audit:',
        'tbl2': '2. Image tags and alt text audit:',
        'tbl3': '3. Visible catalogue vs sitemap comparison:',
        'diag': '{n}. Consultant diagnosis and action plan:',
        'h_val': 'Value / Count', 'h_item': 'Audited item',
        'r_total': 'Total visible pages audited', 'u_page': 'pages',
        'r_products': 'Visible product pages', 'u_product': 'products',
        'r_categories': 'Category and collection pages', 'u_cat': 'categories',
        'r_blog': 'Blog posts and articles', 'u_article': 'articles',
        'r_info': 'Info and policy pages',
        'r_broken': 'Broken links found inside the store', 'u_link': 'links',
        'r_titles': 'Missing or non-compliant meta titles', 'u_title': 'titles',
        'r_descs': 'Missing or non-optimised meta descriptions', 'u_desc': 'descriptions',
        'r_imgs': 'Total content and product images', 'u_img': 'images',
        'r_noalt': 'Images missing alt text', 'r_ratio': 'Share of images missing alt text',
        'r_imgstate': 'Readiness for Google Image search',
        'img_none': 'No content images detected', 'img_ok': 'Complete',
        'img_gap': 'Major gap', 'img_part': 'Partial gap',
        'r_vis': 'Products visible to visitors',
        'r_sm': 'Products declared in sitemap',
        'r_notidx': 'Visible products absent from sitemap',
        'r_hidden': 'Sitemap URLs unreachable by visitors',
        'r_idxpct': 'Visible products included in sitemap',
        'footer': 'anasrashed.com   |   anas@anasrashed.com',
    },
}


def shape_ar(text):
    return get_display(arabic_reshaper.reshape(str(text)))


def build_diagnosis(score, stats, lang):
    imgs = stats.get('total_images', 0)
    missing = stats.get('missing_alts', 0)
    bad_t = stats.get('bad_titles', 0)
    bad_d = stats.get('bad_descs', 0)
    broken = stats.get('broken_pages', 0)
    notidx = stats.get('not_indexed_count', 0)

    issues = []
    if lang == 'ar':
        if missing > 0 and imgs > 0:
            issues.append(f"وجود {missing} صورة من أصل {imgs} بلا نص بديل "
                          f"(بنسبة {round(missing / imgs * 100, 1)}%)، وهو ما يحد من "
                          "ظهور المتجر في نتائج بحث الصور")
        if bad_t > 0:
            issues.append(f"{bad_t} عنوان ميتا مفقود أو خارج الطول الموصى به")
        if bad_d > 0:
            issues.append(f"{bad_d} وصف ميتا مفقود أو غير مهيأ")
        if notidx > 0:
            issues.append(f"{notidx} منتجاً معروضاً في المتجر لا يظهر في خريطة الموقع")
        if broken > 0:
            issues.append(f"{broken} رابط معطل داخل المتجر يصل إليه الزائر")
        if not issues:
            return ("لم يرصد الفحص فجوات جوهرية في الصفحات المعروضة: العناوين والأوصاف "
                    "ووسوم الصور ضمن المعايير الموصى بها. يوصى بمتابعة دورية عند إضافة "
                    "منتجات أو أقسام جديدة.")
        body = "أظهر الفحص الفني: " + "، و".join(issues) + ". "
        if score < 60:
            body += ("تشير النتيجة الإجمالية إلى فجوة واسعة في تهيئة المتجر لمحركات البحث. "
                     "يوصى بإعادة كتابة البيانات الوصفية وإسناد نصوص بديلة لجميع صور "
                     "المحتوى ضمن خطة عمل مرحلية.")
        elif score < 80:
            body += ("المتجر مهيأ جزئياً، ومعالجة العناصر أعلاه من شأنها رفع درجة التوافق "
                     "وتحسين فرص الظهور في نتائج البحث.")
        else:
            body += ("المستوى العام جيد، وتبقى المعالجات المذكورة تحسينات تكميلية يمكن "
                     "تنفيذها ضمن جولة مراجعة واحدة.")
        return body

    if missing > 0 and imgs > 0:
        issues.append(f"{missing} of {imgs} images ({round(missing / imgs * 100, 1)}%) "
                      "have no alt text, limiting visibility in Google Image search")
    if bad_t > 0:
        issues.append(f"{bad_t} meta titles are missing or outside the recommended length")
    if bad_d > 0:
        issues.append(f"{bad_d} meta descriptions are missing or not optimised")
    if notidx > 0:
        issues.append(f"{notidx} products visible in the store are absent from the sitemap")
    if broken > 0:
        issues.append(f"{broken} broken links are reachable by visitors")
    if not issues:
        return ("The audit found no material gaps across the visible pages: titles, "
                "descriptions and image alt text all fall within recommended standards. "
                "Periodic review is advised whenever new products or categories are added.")
    body = "The technical audit found: " + "; ".join(issues) + ". "
    if score < 60:
        body += ("The overall score indicates a substantial gap in search engine readiness. "
                 "Rewriting the metadata and assigning alt text to all content images is "
                 "recommended as a phased programme of work.")
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
        (T['r_titles'], f"{stats['bad_titles']} {T['u_title']}"),
        (T['r_descs'], f"{stats['bad_descs']} {T['u_desc']}"),
    ])

    imgs = stats.get('total_images', 0)
    noalt = stats.get('missing_alts', 0)
    ratio = round((noalt / imgs * 100), 1) if imgs else 0
    state = (T['img_none'] if imgs == 0 else T['img_ok'] if noalt == 0
             else T['img_gap'] if ratio > 50 else T['img_part'])
    draw_table(T['tbl2'], [
        (T['r_imgs'], f"{imgs} {T['u_img']}"),
        (T['r_noalt'], f"{noalt} {T['u_img']}"),
        (T['r_ratio'], f"{ratio}%"),
        (T['r_imgstate'], state),
    ])

    if stats.get('coverage_enabled'):
        draw_table(T['tbl3'], [
            (T['r_vis'], f"{stats.get('visible_products', 0)} {T['u_product']}"),
            (T['r_sm'], f"{stats.get('sitemap_products', 0)} {T['u_product']}"),
            (T['r_notidx'], f"{stats.get('not_indexed_count', 0)} {T['u_product']}"),
            (T['r_hidden'], f"{stats.get('hidden_count', 0)} {T['u_link']}"),
            (T['r_idxpct'], f"{stats.get('indexed_pct', 0)}%"),
        ])
        diag_n = "4"
    else:
        diag_n = "3"

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
           'hidden': "10_روابط_الخريطة_غير_المعروضة.csv",
           'excel': "التقرير_الشامل.xlsx"},
    'en': {T_PRODUCT: "1_products.csv", T_CATEGORY: "2_categories.csv",
           T_BLOG: "3_blog.csv", T_INFO: "4_info_pages.csv",
           T_HOME: "5_homepage.csv", T_UNKNOWN: "6_unclassified.csv",
           T_BROKEN: "7_broken_links.csv", 'images': "8_image_alt_audit.csv",
           'notidx': "9_products_missing_from_sitemap.csv",
           'hidden': "10_sitemap_urls_not_visible.csv",
           'excel': "full_audit_report.xlsx"},
}


def build_zip(df, images_df, coverage=None, lang='ar'):
    names = ZIP_NAMES[lang]
    ldf = localize_df(df, lang)
    limg = localize_df(images_df, lang)
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
            col = 'رابط المنتج' if lang == 'ar' else 'Product URL'
            if coverage.get('visible_not_in_sitemap'):
                z.writestr(names['notidx'],
                           pd.DataFrame({col: coverage['visible_not_in_sitemap']})
                           .to_csv(index=False, encoding='utf-8-sig'))
            if coverage.get('sitemap_not_visible'):
                col2 = 'الرابط' if lang == 'ar' else 'URL'
                z.writestr(names['hidden'],
                           pd.DataFrame({col2: coverage['sitemap_not_visible']})
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
st.sidebar.title("🧭 القائمة الرئيسية")
nav = st.sidebar.radio("اختر الوجهة:", ["🔍 فحص متجر جديد", "📁 سجل المتاجر السابقة"])

if nav == "🔍 فحص متجر جديد":
    st.title("🚀 مركز عمليات السيو الشامل للمتاجر")
    st.write("الفحص يبدأ من الصفحة الرئيسية ويتصفح المتجر كما يتصفحه الزائر. "
             "لا تدخل التقرير أي صفحة لا يصل إليها الزائر فعلياً.")

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
        do_pagination = st.checkbox("متابعة ترقيم صفحات الأقسام", value=True,
                                    help="يلتقط المنتجات التي لا تظهر في الصفحة الأولى "
                                         "من القسم — الزائر يصل إليها بزر التالي.")
        do_sitemap_check = st.checkbox("مقارنة تشخيصية مع خريطة الموقع", value=True,
                                       help="لا تؤثر على أرقام الفحص. تكشف المنتجات "
                                            "المعروضة وغير المدرجة في الخريطة، والعكس.")

    if st.session_state.audit_df is not None:
        if st.sidebar.button("🔄 فحص متجر جديد (تفريغ الشاشة)"):
            for k in ['audit_df', 'images_df', 'summary', 'coverage']:
                st.session_state[k] = None
            st.session_state.current_url = ""
            st.rerun()

    if start_btn and input_url:
        target = normalize_url(input_url)
        st.session_state.current_url = target

        st.info("المرحلة 1: تصفح المتجر من الصفحة الرئيسية...")
        bar1 = st.progress(0)
        note1 = st.empty()

        def crawl_cb(done, pending, level):
            bar1.progress(min(done / max(done + pending, 1), 1.0))
            note1.caption(f"المستوى {level} — فُحصت {done} صفحة، "
                          f"وفي الانتظار {pending} رابط.")

        pages, imgs, cat_urls, seen = crawl_store(target, max_pages, workers, crawl_cb)
        bar1.progress(1.0)

        if do_pagination and cat_urls:
            st.info("المرحلة 2: متابعة ترقيم صفحات الأقسام...")
            bar2 = st.progress(0)
            note2 = st.empty()

            def pag_cb(i, total, found, fetched):
                bar2.progress(min(i / max(total, 1), 1.0))
                note2.caption(f"{i}/{total} قسم — {found} منتج إضافي من {fetched} صفحة.")

            extra_urls = harvest_paginated_products(target, cat_urls, seen, pag_cb)
            if extra_urls:
                st.info(f"المرحلة 3: فحص {len(extra_urls)} منتج من الصفحات التالية...")
                bar3 = st.progress(0)
                p2, i2 = audit_urls(extra_urls, target, 'ترقيم الأقسام', workers, bar3)
                pages += p2
                imgs += i2

        df = dedupe_pages(pd.DataFrame(pages))
        images_df = pd.DataFrame(imgs)
        if not images_df.empty:
            images_df = images_df[images_df['رابط الصفحة'].isin(df['الرابط'])] \
                .copy().reset_index(drop=True)

        coverage = None
        if do_sitemap_check:
            with st.spinner("مقارنة تشخيصية مع خريطة الموقع..."):
                sm_urls = collect_sitemap_urls(target)
                visible_products = df[(df['نوع الصفحة'] == T_PRODUCT) &
                                      (df['متاحة'] == True)]['الرابط'].tolist()  # noqa: E712
                coverage = build_coverage_report(visible_products, sm_urls, target)

        summary = compute_summary(df, coverage)
        st.session_state.audit_df = df
        st.session_state.images_df = images_df
        st.session_state.summary = summary
        st.session_state.coverage = coverage

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

        for col, (val, lbl) in zip(st.columns(7), [
            (summary["total_pages"], "الصفحات المعروضة"),
            (f'{summary["score"]}%', "نسبة التوافق"),
            (summary["products"], "المنتجات"),
            (summary["categories"], "الأقسام"),
            (summary["blog_pages"], "المدونة"),
            (summary["info_pages"], "التعريفية"),
            (summary.get("broken_pages", 0), "روابط معطلة"),
        ]):
            with col:
                st.markdown(f'<div class="metric-card"><div class="metric-value">{val}</div>'
                            f'<div class="metric-label">{lbl}</div></div>',
                            unsafe_allow_html=True)

        view_df = localize_df(df, 'ar')
        view_imgs = localize_df(images_df, 'ar')
        tabs = st.tabs(["📄 الصفحات", "🖼️ الصور", "🎯 مقارنة الخريطة", "🔬 التحقق اليدوي"])

        with tabs[0]:
            present = [PAGE_TYPE_LABEL['ar'][t] for t in PAGE_TYPE_ORDER
                       if (df['نوع الصفحة'] == t).any()]
            sel = st.selectbox("نوع الصفحة:", ["جميع الصفحات"] + present)
            d = view_df if sel == "جميع الصفحات" else view_df[view_df['نوع الصفحة'] == sel]
            d = d.copy().reset_index(drop=True)
            d.index = d.index + 1
            st.dataframe(d, use_container_width=True)
            langs = df[df['متاحة'] == True]['لغة الصفحة'].value_counts()  # noqa: E712
            if not langs.empty:
                st.caption("لغات الصفحات المرصودة: " +
                           "، ".join(f"{k}: {v}" for k, v in langs.items()))

        with tabs[1]:
            if view_imgs is not None and not view_imgs.empty:
                f = st.selectbox("تصفية:", ["جميع الصور", "بدون Alt فقط", "سليمة فقط"])
                v = view_imgs
                if f == "بدون Alt فقط":
                    v = view_imgs[view_imgs['حالة النص البديل'] == STATUS_LABEL['ar']['alt_missing']]
                elif f == "سليمة فقط":
                    v = view_imgs[view_imgs['حالة النص البديل'] == STATUS_LABEL['ar']['alt_ok']]
                v = v.copy().reset_index(drop=True)
                v.index = v.index + 1
                st.dataframe(v, use_container_width=True)
            else:
                st.info("لا توجد صور محتوى مرصودة.")

        with tabs[2]:
            if not coverage:
                st.info("لم تُفعّل المقارنة مع خريطة الموقع في هذا الفحص.")
            else:
                st.caption("هذه المقارنة تشخيصية ولا تؤثر على أرقام الفحص أعلاه.")
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("منتجات معروضة للزائر", coverage['visible_count'])
                c2.metric("منتجات في الخريطة", coverage['sitemap_count'])
                c3.metric("معروضة وخارج الخريطة", len(coverage['visible_not_in_sitemap']))
                c4.metric("نسبة الإدراج", f"{coverage['indexed_pct']}%")

                if coverage['visible_not_in_sitemap']:
                    st.error(f"{len(coverage['visible_not_in_sitemap'])} منتج يراه الزائر "
                             "ولا يظهر في خريطة الموقع — محركات البحث قد لا تعلم بوجوده.")
                    st.dataframe(pd.DataFrame(
                        {'رابط المنتج': coverage['visible_not_in_sitemap']}),
                        use_container_width=True)
                else:
                    st.success("جميع المنتجات المعروضة مدرجة في خريطة الموقع.")

                if coverage['sitemap_not_visible']:
                    st.warning(f"{len(coverage['sitemap_not_visible'])} رابط في خريطة الموقع "
                               "لا يصل إليه الزائر — منتجات مخفية أو محذوفة أو غير مرتبطة "
                               "بأي قسم. هذه الروابط مستبعدة من الفحص.")
                    st.dataframe(pd.DataFrame({'الرابط': coverage['sitemap_not_visible']}),
                                 use_container_width=True)

        with tabs[3]:
            st.subheader("🔬 عيّنة للتحقق اليدوي")
            st.write("افتح كل رابط وقارن العنوان والوصف بما هو مسجّل هنا.")
            pool = df[(df['متاحة'] == True) & (df['نوع الصفحة'] == T_PRODUCT)]  # noqa: E712
            if pool.empty:
                pool = df[df['متاحة'] == True]  # noqa: E712
            if pool.empty:
                st.info("لا توجد صفحات متاحة للتحقق.")
            else:
                sample = pool.sample(n=min(5, len(pool)),
                                     random_state=int(time.time()) % 1000)
                for _, row in sample.iterrows():
                    with st.container(border=True):
                        st.markdown(f"**الرابط:** [{unquote(row['الرابط'])}]({row['الرابط']})")
                        st.write(f"العنوان ({len(str(row['عنوان الميتا']))} حرف): "
                                 f"{row['عنوان الميتا'] or '— مفقود —'}")
                        st.write(f"الوصف ({len(str(row['وصف الميتا']))} حرف): "
                                 f"{row['وصف الميتا'] or '— مفقود —'}")
                        st.write(f"صور: {row['إجمالي الصور']} | "
                                 f"بدون Alt: {row['صور بدون Alt']} | "
                                 f"كلمات: {row['عدد الكلمات']} | "
                                 f"لغة: {row['لغة الصفحة']}")

        st.subheader("📥 التحميل والتصدير")
        lang_choice = st.radio("لغة الملفات المُصدَّرة:", ["العربية", "English"],
                               horizontal=True, key="export_lang")
        lang = 'ar' if lang_choice == "العربية" else 'en'

        netloc = urlparse(st.session_state.current_url).netloc or "store"
        try:
            pdf_bytes = generate_client_pdf(st.session_state.current_url,
                                            summary['score'], summary, lang)
        except Exception as e:
            pdf_bytes = None
            st.error(f"تعذر توليد الـ PDF: {e}")
        zip_bytes = build_zip(df, images_df, coverage, lang)

        d1, d2 = st.columns(2)
        with d1:
            if pdf_bytes:
                st.download_button(
                    "📄 تقرير العميل (PDF)" if lang == 'ar' else "📄 Client report (PDF)",
                    pdf_bytes, f"SEO_Audit_{netloc}_{lang}.pdf", "application/pdf")
        with d2:
            st.download_button(
                "📦 حزمة البيانات (ZIP)" if lang == 'ar' else "📦 Data package (ZIP)",
                zip_bytes, f"Data_Package_{netloc}_{lang}.zip", "application/zip")

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
        sel_id = st.selectbox(
            "اختر المتجر:", hist['id'].tolist(),
            format_func=lambda x: f"{hist[hist['id']==x]['المتجر'].values[0]} "
                                  f"({hist[hist['id']==x]['تاريخ الفحص'].values[0]})")
        if st.button("📥 استرجاع البيانات"):
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute("SELECT domain, data_json, images_json, coverage_json "
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
                st.success("تم الاسترجاع. انتقل إلى (فحص متجر جديد) لعرض النتائج والتحميل.")
