import streamlit as st
import requests
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
import pandas as pd
import time
import io
import os
import re
import zipfile
import sqlite3
import textwrap
from datetime import datetime
from urllib.parse import urlparse, urljoin, unquote
from concurrent.futures import ThreadPoolExecutor
from fpdf import FPDF
import arabic_reshaper
from bidi.algorithm import get_display

st.set_page_config(page_title="مركز عمليات السيو | أنس راشد", layout="wide", page_icon="🚀")

DB_FILE = "store_history.db"

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
        data_json TEXT
    )''')
    try:
        c.execute("ALTER TABLE audits ADD COLUMN blog_pages_count INTEGER DEFAULT 0")
    except:
        pass
    conn.commit()
    conn.close()

init_db()

if 'audit_df' not in st.session_state:
    st.session_state.audit_df = None
if 'images_df' not in st.session_state:
    st.session_state.images_df = None
if 'summary' not in st.session_state:
    st.session_state.summary = None
if 'current_url' not in st.session_state:
    st.session_state.current_url = ""

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

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept-Language': 'ar,en;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
}

def extract_footer_and_menu_urls(base_url):
    found = set()
    try:
        res = requests.get(base_url, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            target_keywords = ['سياسة', 'الشروط', 'الخصوصية', 'الاستبدال', 'الاسترجاع', 'الشحن', 'الشكاوى', 'الأسئلة', 'من نحن', 'اتصل', 'توصيل', 'ضمان', 'مدونة', 'faq', 'terms', 'privacy', 'return', 'shipping', 'about', 'contact', 'blog']
            for a in soup.find_all('a', href=True):
                href = a['href'].strip()
                text = a.get_text(strip=True).lower()
                if any(k in text for k in target_keywords) or any(k in href.lower() for k in target_keywords):
                    full_url = urljoin(base_url, href).split('#')[0].split('?')[0].rstrip('/')
                    if urlparse(full_url).netloc == urlparse(base_url).netloc:
                        found.add(full_url)
    except:
        pass
    return found

def detect_page_type_advanced(url, base_url, soup):
    base_clean = base_url.rstrip('/')
    url_clean = url.rstrip('/')
    if url_clean == base_clean:
        return 'صفحة رئيسية'
    
    path = unquote(urlparse(url).path.lower())
    path_clean = path.strip('/')
    segments = [s for s in path.split('/') if s]

    # 1. فحص صفحات الكتالوج العامة (ليست منتجاً بل تصنيفاً)
    if path_clean in ['products', 'product', 'all-products', 'catalog', 'collections/all']:
        return 'صفحة تصنيف'

    # 2. فحص الصفحات التعريفية والسياسات
    policy_keywords = ['سياسة', 'شروط', 'خصوصية', 'استبدال', 'استرجاع', 'شحن', 'توصيل', 'شكاوى', 'أسئلة', 'من-نحن', 'اتصل', 'pages', 'policies', 'privacy', 'terms', 'about', 'contact', 'faq', 'shipping', 'complaint', 'return', 'payment']
    if any(k in path for k in policy_keywords):
        return 'صفحة تعريفية'

    og_type = ""
    if soup:
        og_tag = soup.find('meta', attrs={'property': 'og:type'})
        if og_tag and og_tag.get('content'):
            og_type = og_tag['content'].lower()

    # 3. فحص المنتجات (يجب أن يحتوي على اسم منتج حقيقي وليس مجرد مسار عام)
    if 'product' in og_type:
        return 'صفحة منتج'
    if soup and soup.find(attrs={'itemtype': re.compile(r'schema\.org/Product', re.I)}):
        return 'صفحة منتج'

    if ('/products/' in path or '/product/' in path) and len(segments) >= 2:
        return 'صفحة منتج'
    if re.search(r'/p\d+', path) or path.endswith('/p') or '-p-' in path:
        return 'صفحة منتج'
    if any(re.match(r'^p\d+', s) for s in segments):
        return 'صفحة منتج'

    # 4. فحص المدونة والمقالات
    if any(k in path for k in ['/blog', '/blogs', '/articles', '/article', '/post', '/posts']):
        return 'صفحة مدونة'
    if 'article' in og_type:
        return 'صفحة مدونة'
    if soup and soup.find(attrs={'itemtype': re.compile(r'schema\.org/(Article|BlogPosting)', re.I)}):
        return 'صفحة مدونة'

    # 5. فحص التصنيفات والكولكشنات
    if soup and soup.find(attrs={'itemtype': re.compile(r'schema\.org/CollectionPage', re.I)}):
        return 'صفحة تصنيف'
            
    if any(k in path for k in ['/category/', '/categories/', '/collection/', '/collections/']) or re.search(r'/c\d+', path):
        return 'صفحة تصنيف'
    if any(re.match(r'^c\d+', s) for s in segments):
        return 'صفحة تصنيف'

    return 'صفحة تعريفية' if len(segments) == 1 and not re.search(r'\d', segments[0]) else 'صفحة تصنيف'

def get_all_store_urls(base_url):
    base_url = base_url.rstrip('/')
    all_urls = set()
    sitemap_candidates = [
        f"{base_url}/sitemap.xml",
        f"{base_url}/sitemap_products_1.xml",
        f"{base_url}/sitemap_categories.xml",
        f"{base_url}/sitemap_pages_1.xml"
    ]
    for s_url in sitemap_candidates:
        try:
            res = requests.get(s_url, headers=HEADERS, timeout=10)
            if res.status_code == 200:
                root = ET.fromstring(res.content)
                namespaces = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
                for loc in root.findall('.//ns:loc', namespaces):
                    u = loc.text.strip()
                    if u.endswith('.xml'):
                        sub_res = requests.get(u, headers=HEADERS, timeout=10)
                        if sub_res.status_code == 200:
                            sub_root = ET.fromstring(sub_res.content)
                            for sub_loc in sub_root.findall('.//ns:loc', namespaces):
                                clean_u = sub_loc.text.strip().split('?')[0].rstrip('/')
                                all_urls.add(clean_u)
                    else:
                        clean_u = u.split('?')[0].rstrip('/')
                        all_urls.add(clean_u)
        except:
            continue
            
    footer_urls = extract_footer_and_menu_urls(base_url)
    all_urls.update(footer_urls)
    
    if not all_urls:
        all_urls.add(base_url)
    return list(all_urls)

# فلتر استبعاد صور عناصر الواجهة وأيقونات الدفع والتحميل
def is_relevant_seo_image(img, src):
    if not src:
        return False
    src_lower = src.lower()

    if src_lower.startswith('data:image'):
        return False

    # استبعاد ملفات التحميل والأيقونات التفاعلية
    if any(src_lower.endswith(ext) or f"{ext}?" in src_lower for ext in ['.gif', '.svg', '.ico']):
        return False

    # استبعاد وسوم عناصر الواجهة، بوابات الدفع، وسائل التواصل، والتتبع
    junk_keywords = [
        'spinner', 'loader', 'loading', 'ajax', 'icon', 'logo', 'badge',
        'payment', 'gateway', 'tamara', 'tabby', 'mada', 'visa', 'mastercard',
        'apple-pay', 'applepay', 'stc-pay', 'stcpay', 'vat', 'tax',
        'maroof', 'social', 'whatsapp', 'snapchat', 'instagram', 'tiktok',
        'twitter', 'pixel', 'spacer', 'avatar', 'arrow', 'placeholder'
    ]
    if any(junk in src_lower for junk in junk_keywords):
        return False

    # استبعاد الصور المصغرة جداً (أقل من 60 بكسل)
    w = img.get('width')
    h = img.get('height')
    try:
        if w and int(str(w).replace('px', '')) < 60:
            return False
        if h and int(str(h).replace('px', '')) < 60:
            return False
    except:
        pass

    return True

def audit_single_page(url_item):
    url, base_url = url_item
    
    res = None
    for attempt in range(3):
        try:
            res = requests.get(url, headers=HEADERS, timeout=12, allow_redirects=True)
            if res.status_code == 429:
                time.sleep(2 * (attempt + 1))
                continue
            break
        except:
            time.sleep(1)

    final_url = res.url.split('?')[0].rstrip('/') if res else url

    if res is None or res.status_code != 200:
        status_code = res.status_code if res else 'فشل اتصال'
        return {
            'page_data': {
                'نوع الصفحة': 'صفحة عامة',
                'الرابط': final_url,
                'درجة السيو': 0,
                'عنوان الميتا': 'تعذر الفحص',
                'حالة العنوان': f'خطأ {status_code}',
                'وصف الميتا': 'تعذر الفحص',
                'حالة الوصف': f'خطأ {status_code}',
                'إجمالي الصور': 0,
                'صور بدون Alt': 0,
                'عدد الكلمات': 0,
                'حالة المحتوى': 'غير متاح'
            },
            'images_data': []
        }

    soup = BeautifulSoup(res.text, 'html.parser')
    page_type = detect_page_type_advanced(final_url, base_url, soup)

    # Title
    title_tag = soup.find('title')
    title = title_tag.text.strip() if title_tag else ''
    title_status = 'سليم'
    if not title: title_status = 'مفقود'
    elif len(title) < 30: title_status = 'قصير جداً'
    elif len(title) > 65: title_status = 'طويل جداً'

    # Description
    meta_desc_tag = soup.find('meta', attrs={'name': 'description'}) or soup.find('meta', attrs={'property': 'og:description'})
    meta_desc = meta_desc_tag['content'].strip() if meta_desc_tag and 'content' in meta_desc_tag.attrs else ''
    desc_status = 'سليم'
    if not meta_desc: desc_status = 'مفقود'
    elif len(meta_desc) < 70: desc_status = 'قصير جداً'
    elif len(meta_desc) > 165: desc_status = 'طويل جداً'

    # فحص مفلتر ودقيق لصور المحتوى الحقيقية فقط
    raw_images = soup.find_all('img')
    total_img = 0
    missing_alt = 0
    page_images = []

    for img in raw_images:
        src = img.get('src') or img.get('data-src') or ''
        if src and is_relevant_seo_image(img, src):
            total_img += 1
            full_img_url = urljoin(final_url, src)
            alt_text = img.get('alt', '').strip()
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

    # Words
    for s in soup(['script', 'style', 'nav', 'footer']): s.decompose()
    words = len(soup.get_text(separator=' ', strip=True).split())
    content_status = 'جيد' if words >= 50 else 'ضعيف جداً'

    score = 100
    if title_status != 'سليم': score -= 25
    if desc_status != 'سليم': score -= 25
    if total_img > 0 and missing_alt > 0: score -= int((missing_alt / total_img) * 25)
    if content_status != 'جيد': score -= 25
    score = max(0, score)

    return {
        'page_data': {
            'نوع الصفحة': page_type,
            'الرابط': final_url,
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

def generate_client_pdf(domain, score, summary_stats):
    font_path = "Amiri-Regular.ttf"
    if not os.path.exists(font_path) or os.path.getsize(font_path) < 30000:
        font_url = "https://raw.githubusercontent.com/google/fonts/main/ofl/amiri/Amiri-Regular.ttf"
        try:
            r = requests.get(font_url, timeout=15)
            if r.status_code == 200:
                with open(font_path, "wb") as f:
                    f.write(r.content)
        except:
            pass

    logo_path = "brand_logo.png"
    if not os.path.exists(logo_path) or os.path.getsize(logo_path) < 1000:
        try:
            logo_url = "https://i.imgur.com/zGoNASG.png"
            r = requests.get(logo_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
            if r.status_code == 200:
                with open(logo_path, "wb") as f:
                    f.write(r.content)
        except:
            pass

    def ar(text):
        reshaped = arabic_reshaper.reshape(str(text))
        return get_display(reshaped)

    clean_domain = urlparse(domain).netloc if urlparse(domain).netloc else domain

    class PDFReport(FPDF):
        def header(self):
            if os.path.exists(logo_path):
                try:
                    self.image(logo_path, x=15, y=10, w=22)
                except:
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
    pdf.add_font("Amiri", "", font_path)
    pdf.add_page()
    
    pdf.set_font("Amiri", "", 16)
    pdf.set_text_color(15, 23, 42)
    pdf.cell(0, 8, ar("تقرير الفحص الفني الشامل لمحركات البحث"), ln=True, align="C")
    
    pdf.set_font("Amiri", "", 11)
    pdf.set_text_color(71, 85, 105)
    pdf.cell(0, 6, ar(f"المتجر المستهدف: {clean_domain}   |   تاريخ الفحص: {datetime.now().strftime('%Y-%m-%d')}"), ln=True, align="C")
    pdf.ln(4)

    pdf.set_fill_color(248, 250, 252)
    pdf.set_draw_color(203, 213, 225)
    pdf.rect(15, 46, 180, 16, 'DF')
    pdf.set_xy(15, 49)
    pdf.set_font("Amiri", "", 15)
    if score < 60:
        pdf.set_text_color(225, 29, 72)
    elif score < 80:
        pdf.set_text_color(217, 119, 6)
    else:
        pdf.set_text_color(16, 185, 129)
    pdf.cell(180, 10, ar(f"درجة التوافق العامة مع محركات البحث: {score}%"), align="C")
    pdf.ln(18)

    def draw_table(title, rows, col_widths=[120, 60]):
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
        ("عناوين الميتا الرئيسية المفقودة أو غير المتوافقة", f"{summary_stats['bad_titles']} عنوان"),
        ("أوصاف الميتا التسويقية المفقودة أو غير المهيأة", f"{summary_stats['bad_descs']} وصف")
    ]
    draw_table("1. جدول تدقيق بنية الصفحات والعناوين:", pages_rows)

    total_imgs = summary_stats.get('total_images', 0)
    missing_alts = summary_stats.get('missing_alts', 0)
    alt_ratio = round((missing_alts / total_imgs * 100), 1) if total_imgs > 0 else 0

    image_rows = [
        ("إجمالي صور المحتوى والمنتجات المفحوصة", f"{total_imgs} صورة"),
        ("صور تفتقر لوسم النص البديل لمحركات البحث", f"{missing_alts} صورة"),
        ("نسبة الصور غير المهيأة لمحركات البحث", f"{alt_ratio}%"),
        ("حالة ظهور الصور في بحث صور جوجل المجاني", "ضعيف جداً ومفقود" if missing_alts > 0 else "ممتاز ومكتمل")
    ]
    draw_table("2. جدول تدقيق وسوم وصور المتجر:", image_rows)

    box_width = 180
    box_x = (210 - box_width) / 2
    pdf.set_x(box_x)
    pdf.set_font("Amiri", "", 12)
    pdf.set_text_color(15, 23, 42)
    pdf.cell(box_width, 6, ar("3. التشخيص الاستشاري وخطة العمل:"), ln=True, align="R")
    pdf.ln(1)

    box_y = pdf.get_y()
    pdf.set_fill_color(248, 250, 252)
    pdf.set_draw_color(226, 232, 240)
    pdf.rect(box_x, box_y, box_width, 24, 'DF')
    
    pdf.set_xy(box_x + 5, box_y + 3)
    pdf.set_font("Amiri", "", 9)
    pdf.set_text_color(71, 85, 105)
    
    diag_text = (
        "يعاني المتجر من ضعف كبير في تهيئة وسوم الصور مما يحرمه من آلاف الزيارات عبر بحث الصور المجاني، "
        "بالإضافة لوجود فجوة في صياغة أوصاف الميتا التسويقية. يوصى فوراً بإعادة كتابة البيانات الوصفية وفق معايير محركات البحث، "
        "وإسناد نصوص بديلة لجميع الصور لرفع التوافق فوق 95% ومضاعفة المبيعات المجانية."
    )
    
    wrapped_lines = textwrap.wrap(diag_text, width=85)
    for line in wrapped_lines:
        pdf.set_x(box_x + 5)
        pdf.cell(box_width - 10, 4.8, ar(line), ln=True, align="R")

    return bytes(pdf.output())

st.sidebar.title("🧭 القائمة الرئيسية")
nav = st.sidebar.radio("اختر الوجهة:", ["🔍 فحص متجر جديد", "📁 سجل المتاجر السابقة"])

if nav == "🔍 فحص متجر جديد":
    st.title("🚀 مركز عمليات السيو الشامل للمتاجر")
    st.write("أداة الفحص والتدقيق الكامل لجميع أقسام ومنتجات ومدونات وسياسات وصور المتجر الإلكتروني.")

    c_url, c_btn = st.columns([4, 1])
    with c_url:
        input_url = st.text_input("أدخل رابط المتجر الإلكتروني:", value=st.session_state.current_url, placeholder="https://midhal-oud.store")
    with c_btn:
        st.write("")
        st.write("")
        start_btn = st.button("🔍 بدء الفحص")

    if st.session_state.audit_df is not None:
        if st.sidebar.button("🔄 فحص متجر جديد (تفريغ الشاشة)"):
            st.session_state.audit_df = None
            st.session_state.images_df = None
            st.session_state.summary = None
            st.session_state.current_url = ""
            st.rerun()

    if start_btn and input_url:
        st.session_state.current_url = input_url
        with st.spinner("جاري استخراج كافة الصفحات وتجريد المتغيرات الزائدة..."):
            urls = get_all_store_urls(input_url)

        st.info(f"تم العثور على {len(urls)} صفحة شاملة. جاري الفحص وتدقيق الصفحات والصور بدقة...")

        progress_bar = st.progress(0)
        page_results = []
        all_images_results = []
        url_tuples = [(u, input_url) for u in urls]
        total_urls = len(urls)
        completed = 0

        with ThreadPoolExecutor(max_workers=5) as executor:
            for res in executor.map(audit_single_page, url_tuples):
                page_results.append(res['page_data'])
                all_images_results.extend(res['images_data'])
                completed += 1
                progress_bar.progress(completed / total_urls)
                time.sleep(0.04)

        df = pd.DataFrame(page_results)
        images_df = pd.DataFrame(all_images_results)
        
        st.session_state.audit_df = df
        st.session_state.images_df = images_df
        
        avg_score = round(df['درجة السيو'].mean(), 1)
        summary = {
            'total_pages': len(df),
            'score': avg_score,
            'products': len(df[df['نوع الصفحة'] == 'صفحة منتج']),
            'categories': len(df[df['نوع الصفحة'] == 'صفحة تصنيف']),
            'info_pages': len(df[df['نوع الصفحة'] == 'صفحة تعريفية']),
            'blog_pages': len(df[df['نوع الصفحة'] == 'صفحة مدونة']),
            'bad_titles': len(df[df['حالة العنوان'] != 'سليم']),
            'bad_descs': len(df[df['حالة الوصف'] != 'سليم']),
            'missing_alts': int(df['صور بدون Alt'].sum()),
            'total_images': int(df['إجمالي الصور'].sum())
        }
        st.session_state.summary = summary

        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute('''INSERT INTO audits (domain, scan_date, score, total_pages, products_count, categories_count, info_pages_count, blog_pages_count, data_json)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                  (input_url, datetime.now().strftime("%Y-%m-%d %H:%M"), avg_score, summary['total_pages'],
                   summary['products'], summary['categories'], summary['info_pages'], summary['blog_pages'], df.to_json(orient='records')))
        conn.commit()
        conn.close()

    if st.session_state.audit_df is not None:
        df = st.session_state.audit_df
        images_df = st.session_state.images_df
        summary = st.session_state.summary

        st.success(f" اكتمل فحص وتصنيف المتجر بنجاح: {st.session_state.current_url}")

        k1, k2, k3, k4, k5, k6 = st.columns(6)
        with k1:
            st.markdown(f'<div class="metric-card"><div class="metric-value">{summary["total_pages"]}</div><div class="metric-label">إجمالي الصفحات</div></div>', unsafe_allow_html=True)
        with k2:
            st.markdown(f'<div class="metric-card"><div class="metric-value">{summary["score"]}%</div><div class="metric-label">نسبة التوافق</div></div>', unsafe_allow_html=True)
        with k3:
            st.markdown(f'<div class="metric-card"><div class="metric-value">{summary["products"]}</div><div class="metric-label">المنتجات</div></div>', unsafe_allow_html=True)
        with k4:
            st.markdown(f'<div class="metric-card"><div class="metric-value">{summary["categories"]}</div><div class="metric-label">الأقسام</div></div>', unsafe_allow_html=True)
        with k5:
            st.markdown(f'<div class="metric-card"><div class="metric-value">{summary["blog_pages"]}</div><div class="metric-label">المدونة</div></div>', unsafe_allow_html=True)
        with k6:
            st.markdown(f'<div class="metric-card"><div class="metric-value">{summary["info_pages"]}</div><div class="metric-label">التعريفية</div></div>', unsafe_allow_html=True)

        tab1, tab2 = st.tabs(["📄 جدول فحص الصفحات", "🖼️ جدول تدقيق صور المتجر (Alt Tags)"])

        with tab1:
            st.subheader("📋 تصفية وعرض الصفحات")
            selected_type = st.selectbox("اختر نوع الصفحة للعرض:", ["جميع الصفحات", "صفحة منتج", "صفحة تصنيف", "صفحة مدونة", "صفحة تعريفية", "صفحة رئيسية"])
            
            if selected_type == "جميع الصفحات":
                display_df = df.copy().reset_index(drop=True)
            else:
                display_df = df[df['نوع الصفحة'] == selected_type].copy().reset_index(drop=True)

            display_df.index = display_df.index + 1
            st.dataframe(display_df, use_container_width=True)

        with tab2:
            st.subheader("🖼️ التقرير المفصل لصور المحتوى والمنتجات (مستبعد منها الأيقونات)")
            if images_df is not None and not images_df.empty:
                col_img1, col_img2 = st.columns(2)
                with col_img1:
                    filter_img = st.selectbox("تصفية الصور:", ["جميع الصور", "صور تفتقر لوسم Alt فقط", "صور سليمة"])
                
                if filter_img == "صور تفتقر لوسم Alt فقط":
                    view_images_df = images_df[images_df['حالة النص البديل'] == 'مفقود'].copy().reset_index(drop=True)
                elif filter_img == "صور سليمة":
                    view_images_df = images_df[images_df['حالة النص البديل'] == 'سليم ومكتمل'].copy().reset_index(drop=True)
                else:
                    view_images_df = images_df.copy().reset_index(drop=True)

                view_images_df.index = view_images_df.index + 1
                st.dataframe(view_images_df, use_container_width=True)
            else:
                st.info("لا توجد بيانات صور متاحة للعرض.")

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            df_p = df[df['نوع الصفحة'] == 'صفحة منتج']
            if not df_p.empty: zip_file.writestr("1_المنتجات_products.csv", df_p.to_csv(index=False, encoding='utf-8-sig'))
            df_c = df[df['نوع الصفحة'] == 'صفحة تصنيف']
            if not df_c.empty: zip_file.writestr("2_التصنيفات_categories.csv", df_c.to_csv(index=False, encoding='utf-8-sig'))
            df_b = df[df['نوع الصفحة'] == 'صفحة مدونة']
            if not df_b.empty: zip_file.writestr("3_المدونة_blog.csv", df_b.to_csv(index=False, encoding='utf-8-sig'))
            df_i = df[df['نوع الصفحة'] == 'صفحة تعريفية']
            if not df_i.empty: zip_file.writestr("4_الصفحات_التعريفية_pages.csv", df_i.to_csv(index=False, encoding='utf-8-sig'))
            df_h = df[df['نوع الصفحة'] == 'صفحة رئيسية']
            if not df_h.empty: zip_file.writestr("5_الصفحة_الرئيسية_homepage.csv", df_h.to_csv(index=False, encoding='utf-8-sig'))
            
            if images_df is not None and not images_df.empty:
                zip_file.writestr("6_تفاصيل_صور_المتجر_images_audit.csv", images_df.to_csv(index=False, encoding='utf-8-sig'))

            excel_buf = io.BytesIO()
            with pd.ExcelWriter(excel_buf, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='SEO Pages Audit')
                if images_df is not None and not images_df.empty:
                    images_df.to_excel(writer, index=False, sheet_name='Images Alt Audit')
            zip_file.writestr("التقرير_الشامل_all_pages_and_images.xlsx", excel_buf.getvalue())

        pdf_bytes = generate_client_pdf(st.session_state.current_url, summary['score'], summary)

        st.subheader("📥 منطقة التحميل والتصدير")
        d_col1, d_col2 = st.columns(2)
        with d_col1:
            st.download_button(
                label="📄 تحميل تقرير العميل الرسمي (PDF)",
                data=pdf_bytes,
                file_name=f"SEO_Audit_Report_{urlparse(st.session_state.current_url).netloc}.pdf",
                mime="application/pdf"
            )
        with d_col2:
            st.download_button(
                label="📦 تحميل حزمة البيانات والملفات المصنفة مع الصور (ملف ZIP)",
                data=zip_buffer.getvalue(),
                file_name=f"Data_Package_{urlparse(st.session_state.current_url).netloc}.zip",
                mime="application/zip"
            )

elif nav == "📁 سجل المتاجر السابقة":
    st.title("📁 سجل المتاجر المفحوصة مسبقاً")
    st.write("يمكنك استعراض أي متجر قمت بفتحه مسبقاً وإعادة تحميل تقاريره فوراً دون إعادة الفحص.")

    conn = sqlite3.connect(DB_FILE)
    history_df = pd.read_sql_query("SELECT id, domain as 'المتجر', scan_date as 'تاريخ الفحص', score as 'النسبة', total_pages as 'الصفحات', products_count as 'المنتجات', categories_count as 'الأقسام', blog_pages_count as 'المدونة', info_pages_count as 'التعريفية' FROM audits ORDER BY id DESC", conn)
    conn.close()

    if history_df.empty:
        st.info("لا توجد متاجر مفحوصة بعد في السجل.")
    else:
        st.dataframe(history_df.drop(columns=['id']), use_container_width=True)

        selected_id = st.selectbox("اختر المتجر لاسترجاع بياناته وتحميل ملفاته:", history_df['id'].tolist(), format_func=lambda x: f"متجر: {history_df[history_df['id']==x]['المتجر'].values[0]} ({history_df[history_df['id']==x]['تاريخ الفحص'].values[0]})")

        if st.button("📥 استرجاع بيانات هذا المتجر للشاشة"):
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute("SELECT domain, data_json, score, total_pages, products_count, categories_count, info_pages_count, blog_pages_count FROM audits WHERE id = ?", (selected_id,))
            row = c.fetchone()
            conn.close()

            if row:
                st.session_state.current_url = row[0]
                st.session_state.audit_df = pd.read_json(row[1])
                st.session_state.images_df = None
                st.session_state.summary = {
                    'total_pages': row[3],
                    'score': row[2],
                    'products': row[4],
                    'categories': row[5],
                    'info_pages': row[6],
                    'blog_pages': row[7] if row[7] is not None else 0,
                    'bad_titles': len(st.session_state.audit_df[st.session_state.audit_df['حالة العنوان'] != 'سليم']),
                    'bad_descs': len(st.session_state.audit_df[st.session_state.audit_df['حالة الوصف'] != 'سليم']),
                    'missing_alts': int(st.session_state.audit_df['صور بدون Alt'].sum()),
                    'total_images': int(st.session_state.audit_df['إجمالي الصور'].sum())
                }
                st.success("تم استرجاع البيانات بنجاح! انتقل إلى صفحة (فحص متجر جديد) في القائمة الجانبية لتحميل ملفات الـ PDF و الـ ZIP.")
