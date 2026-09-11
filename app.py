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
from urllib.parse import urlparse, urljoin
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
        data_json TEXT
    )''')
    conn.commit()
    conn.close()

init_db()

if 'audit_df' not in st.session_state:
    st.session_state.audit_df = None
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
        padding: 15px;
        text-align: center;
        margin-bottom: 10px;
    }
    .metric-value { font-size: 26px; font-weight: bold; color: #38bdf8; }
    .metric-label { font-size: 14px; color: #94a3b8; }
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
            target_keywords = ['سياسة', 'الشروط', 'الخصوصية', 'الاستبدال', 'الاسترجاع', 'الشحن', 'الشكاوى', 'الأسئلة', 'من نحن', 'اتصل', 'توصيل', 'ضمان', 'faq', 'terms', 'privacy', 'return', 'shipping', 'about', 'contact']
            for a in soup.find_all('a', href=True):
                href = a['href'].strip()
                text = a.get_text(strip=True).lower()
                if any(k in text for k in target_keywords) or any(k in href.lower() for k in target_keywords):
                    full_url = urljoin(base_url, href).split('#')[0].rstrip('/')
                    if urlparse(full_url).netloc == urlparse(base_url).netloc:
                        found.add(full_url)
    except:
        pass
    return found

# تصنيف الصفحات الذكي بنسبة 100% عبر فحص الـ HTML وهيكل الرابط معاً
def detect_page_type_advanced(url, base_url, soup):
    base_clean = base_url.rstrip('/')
    url_clean = url.rstrip('/')
    if url_clean == base_clean:
        return 'صفحة رئيسية'
    
    path = urlparse(url).path.lower()
    
    # 1. فحص الصفحات التعريفية أولاً
    if any(k in path for k in ['/pages/', '/policies/', 'privacy', 'terms', 'about', 'contact', 'faq', 'shipping', 'complaint', 'return', 'payment']):
        return 'صفحة تعريفية'

    # 2. فحص المنتجات عبر الـ HTML والـ Tags والروابط
    if soup:
        og_type = soup.find('meta', attrs={'property': 'og:type'})
        if og_type and 'product' in og_type.get('content', '').lower():
            return 'صفحة منتج'
        if soup.find(attrs={'itemtype': re.compile(r'schema\.org/Product', re.I)}):
            return 'صفحة منتج'

    # فحص الروابط للمنتجات (سلة، زد، شوبيفاي)
    if '/products/' in path or '/product/' in path or re.search(r'/p\d+', path) or path.endswith('/p') or '-p-' in path:
        return 'صفحة منتج'
    segments = [s for s in path.split('/') if s]
    if any(re.match(r'^p\d+', s) for s in segments):
        return 'صفحة منتج'

    # 3. فحص التصنيفات والكولكشنات
    if soup:
        if soup.find(attrs={'itemtype': re.compile(r'schema\.org/CollectionPage', re.I)}):
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
                                all_urls.add(sub_loc.text.strip())
                    else:
                        all_urls.add(u)
        except:
            continue
            
    footer_urls = extract_footer_and_menu_urls(base_url)
    all_urls.update(footer_urls)
    
    if not all_urls:
        all_urls.add(base_url)
    return list(all_urls)

def audit_single_page(url_item):
    url, base_url = url_item
    
    res = None
    for attempt in range(3):
        try:
            res = requests.get(url, headers=HEADERS, timeout=12)
            if res.status_code == 429:
                time.sleep(2 * (attempt + 1))
                continue
            break
        except:
            time.sleep(1)

    if res is None or res.status_code != 200:
        status_code = res.status_code if res else 'فشل اتصال'
        return {
            'نوع الصفحة': 'صفحة عامة',
            'الرابط': url,
            'درجة السيو': 0,
            'عنوان الميتا': 'تعذر الفحص',
            'حالة العنوان': f'خطأ {status_code}',
            'وصف الميتا': 'تعذر الفحص',
            'حالة الوصف': f'خطأ {status_code}',
            'إجمالي الصور': 0,
            'صور بدون Alt': 0,
            'عدد الكلمات': 0,
            'حالة المحتوى': 'غير متاح'
        }

    soup = BeautifulSoup(res.text, 'html.parser')
    page_type = detect_page_type_advanced(url, base_url, soup)

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

    # Images & Alt
    images = soup.find_all('img')
    total_img = len(images)
    missing_alt = sum(1 for img in images if not img.get('alt', '').strip())

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
        'نوع الصفحة': page_type,
        'الرابط': url,
        'درجة السيو': score,
        'عنوان الميتا': title,
        'حالة العنوان': title_status,
        'وصف الميتا': meta_desc,
        'حالة الوصف': desc_status,
        'إجمالي الصور': total_img,
        'صور بدون Alt': missing_alt,
        'عدد الكلمات': words,
        'حالة المحتوى': content_status
    }

# محرك الـ PDF الاحترافي الخالي من الأخطاء
def generate_client_pdf(domain, score, summary_stats):
    font_path = "Amiri-Regular.ttf"
    if not os.path.exists(font_path):
        font_url = "https://raw.githubusercontent.com/google/fonts/main/ofl/amiri/Amiri-Regular.ttf"
        r = requests.get(font_url)
        with open(font_path, "wb") as f:
            f.write(r.content)

    def ar(text):
        reshaped = arabic_reshaper.reshape(str(text))
        return get_display(reshaped)

    class PDFReport(FPDF):
        def header(self):
            self.add_font("Amiri", "", font_path)
            self.set_font("Amiri", "", 15)
            self.set_text_color(15, 23, 42)
            self.cell(0, 7, ar("أنس راشد"), ln=True, align="R")
            self.set_font("Amiri", "", 10)
            self.set_text_color(100, 116, 139)
            self.cell(0, 6, ar("خبير تحسين محركات البحث"), ln=True, align="R")
            self.set_draw_color(226, 232, 240)
            self.line(10, 24, 200, 24)
            self.ln(8)

        def footer(self):
            self.set_y(-15)
            self.set_draw_color(226, 232, 240)
            self.line(10, 282, 200, 282)
            self.set_font("Amiri", "", 9)
            self.set_text_color(148, 163, 184)
            self.cell(0, 10, "anasrashed.com   |   anas@anasrashed.com", align="C")

    pdf = PDFReport()
    pdf.add_page()
    pdf.add_font("Amiri", "", font_path)
    
    # عنوان التقرير
    pdf.set_font("Amiri", "", 18)
    pdf.set_text_color(15, 23, 42)
    pdf.cell(0, 10, ar("تقرير الفحص الفني والتدقيق الشامل لمحركات البحث"), ln=True, align="C")
    
    pdf.set_font("Amiri", "", 11)
    pdf.set_text_color(71, 85, 105)
    pdf.cell(0, 6, ar(f"المتجر المستهدف: {domain}"), ln=True, align="C")
    pdf.cell(0, 6, ar(f"تاريخ الفحص: {datetime.now().strftime('%Y-%m-%d')}"), ln=True, align="C")
    pdf.ln(6)

    # مربع السكور
    pdf.set_fill_color(248, 250, 252)
    pdf.set_draw_color(203, 213, 225)
    pdf.rect(15, 54, 180, 22, 'DF')
    pdf.set_xy(15, 59)
    pdf.set_font("Amiri", "", 16)
    if score < 60:
        pdf.set_text_color(225, 29, 72)
    elif score < 80:
        pdf.set_text_color(217, 119, 6)
    else:
        pdf.set_text_color(16, 185, 129)
    pdf.cell(180, 10, ar(f"درجة التوافق العامة مع محركات البحث: {score}%"), align="C")
    pdf.ln(22)

    # ملخص الفحص بالأرقام
    pdf.set_font("Amiri", "", 13)
    pdf.set_text_color(15, 23, 42)
    pdf.cell(0, 8, ar("ملخص نتائج الفحص الشامل لكافة صفحات المتجر:"), ln=True, align="R")
    pdf.ln(2)

    stats = [
        f"• إجمالي عدد الصفحات المفحوصة في المتجر: {summary_stats['total_pages']} صفحة.",
        f"• عدد صفحات المنتجات المكتشفة: {summary_stats['products']} منتجاً.",
        f"• عدد صفحات الأقسام والتصنيفات: {summary_stats['categories']} تصنيفاً.",
        f"• عدد الصفحات التعريفية والسياسات: {summary_stats['info_pages']} صفحة.",
        f"• عناوين ميتا مفقودة أو غير متوافقة: {summary_stats['bad_titles']} عنواناً.",
        f"• أوصاف ميتا مفقودة تحرم المتجر من النقرات: {summary_stats['bad_descs']} وصفاً.",
        f"• إجمالي الصور المفقود منها وسم النص البديل (Alt Tag): {summary_stats['missing_alts']} صورة.",
    ]
    
    pdf.set_font("Amiri", "", 11)
    pdf.set_text_color(51, 65, 85)
    for stat in stats:
        pdf.cell(0, 7, ar(stat), ln=True, align="R")
        
    pdf.ln(6)
    
    # التشخيص الاستشاري مع حل مشكلة انعكاس الأسطر بالكامل
    pdf.set_font("Amiri", "", 13)
    pdf.set_text_color(15, 23, 42)
    pdf.cell(0, 8, ar("التشخيص الاستشاري والتوصيات:"), ln=True, align="R")
    pdf.ln(2)

    diag_text = (
        "يعاني المتجر من فجوة واضحة في تهيئة البيانات الوصفية (Metadata) وخلو الصور من نصوص "
        "التعرف لمحركات البحث، مما يؤدي إلى فقدان تصدر نتائج البحث وظهور المنافسين في مراتب متقدمة. "
        "يوصى بإعادة هيكلة العناوين والأوصاف واستهداف نية الشراء بدقة لرفع نسبة التوافق إلى ما فوق "
        "95% ومضاعفة المبيعات المجانية عبر جوجل."
    )
    
    pdf.set_font("Amiri", "", 10)
    pdf.set_text_color(71, 85, 105)
    
    # تفكيك النص لأسطر منتظمة لتفادي قلب السطور في الـ PDF
    wrapped_lines = textwrap.wrap(diag_text, width=85)
    for line in wrapped_lines:
        pdf.cell(0, 6, ar(line), ln=True, align="R")

    return bytes(pdf.output())

# القائمة والتنقل
st.sidebar.title("🧭 القائمة الرئيسية")
nav = st.sidebar.radio("اختر الوجهة:", ["🔍 فحص متجر جديد", "📁 سجل المتاجر السابقة"])

if nav == "🔍 فحص متجر جديد":
    st.title("🚀 مركز عمليات السيو الشامل للمتاجر")
    st.write("أداة الفحص والتدقيق الكامل لجميع أقسام ومنتجات وسياسات المتجر الإلكتروني.")

    c_url, c_btn = st.columns([4, 1])
    with c_url:
        input_url = st.text_input("أدخل رابط المتجر الإلكتروني:", value=st.session_state.current_url, placeholder="https://pinkit.sa")
    with c_btn:
        st.write("")
        st.write("")
        start_btn = st.button("🔍 بدء الفحص")

    if st.session_state.audit_df is not None:
        if st.sidebar.button("🔄 فحص متجر جديد (تفريغ الشاشة)"):
            st.session_state.audit_df = None
            st.session_state.summary = None
            st.session_state.current_url = ""
            st.rerun()

    if start_btn and input_url:
        st.session_state.current_url = input_url
        with st.spinner("جاري استخراج كافة الصفحات عبر الـ Sitemap وقوائم المتجر..."):
            urls = get_all_store_urls(input_url)

        st.info(f"تم العثور على {len(urls)} صفحة شاملة. جاري الفحص والتصنيف الدقيق...")

        progress_bar = st.progress(0)
        results = []
        url_tuples = [(u, input_url) for u in urls]
        total_urls = len(urls)
        completed = 0

        with ThreadPoolExecutor(max_workers=5) as executor:
            for res in executor.map(audit_single_page, url_tuples):
                results.append(res)
                completed += 1
                progress_bar.progress(completed / total_urls)
                time.sleep(0.04)

        df = pd.DataFrame(results)
        st.session_state.audit_df = df
        
        avg_score = round(df['درجة السيو'].mean(), 1)
        summary = {
            'total_pages': len(df),
            'score': avg_score,
            'products': len(df[df['نوع الصفحة'] == 'صفحة منتج']),
            'categories': len(df[df['نوع الصفحة'] == 'صفحة تصنيف']),
            'info_pages': len(df[df['نوع الصفحة'] == 'صفحة تعريفية']),
            'bad_titles': len(df[df['حالة العنوان'] != 'سليم']),
            'bad_descs': len(df[df['حالة الوصف'] != 'سليم']),
            'missing_alts': int(df['صور بدون Alt'].sum())
        }
        st.session_state.summary = summary

        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute('''INSERT INTO audits (domain, scan_date, score, total_pages, products_count, categories_count, info_pages_count, data_json)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                  (input_url, datetime.now().strftime("%Y-%m-%d %H:%M"), avg_score, summary['total_pages'],
                   summary['products'], summary['categories'], summary['info_pages'], df.to_json(orient='records')))
        conn.commit()
        conn.close()

    if st.session_state.audit_df is not None:
        df = st.session_state.audit_df
        summary = st.session_state.summary

        st.success(f" اكتمل فحص وتصنيف المتجر بنجاح: {st.session_state.current_url}")

        k1, k2, k3, k4, k5 = st.columns(5)
        with k1:
            st.markdown(f'<div class="metric-card"><div class="metric-value">{summary["total_pages"]}</div><div class="metric-label">إجمالي الصفحات</div></div>', unsafe_allow_html=True)
        with k2:
            st.markdown(f'<div class="metric-card"><div class="metric-value">{summary["score"]}%</div><div class="metric-label">نسبة توافق السيو</div></div>', unsafe_allow_html=True)
        with k3:
            st.markdown(f'<div class="metric-card"><div class="metric-value">{summary["products"]}</div><div class="metric-label">المنتجات</div></div>', unsafe_allow_html=True)
        with k4:
            st.markdown(f'<div class="metric-card"><div class="metric-value">{summary["categories"]}</div><div class="metric-label">الأقسام</div></div>', unsafe_allow_html=True)
        with k5:
            st.markdown(f'<div class="metric-card"><div class="metric-value">{summary["info_pages"]}</div><div class="metric-label">الصفحات التعريفية</div></div>', unsafe_allow_html=True)

        st.subheader("📋 تصفية وعرض النتائج")
        selected_type = st.selectbox("اختر نوع الصفحة للعرض:", ["جميع الصفحات", "صفحة منتج", "صفحة تصنيف", "صفحة تعريفية", "صفحة رئيسية"])
        
        if selected_type == "جميع الصفحات":
            st.dataframe(df, use_container_width=True)
        else:
            st.dataframe(df[df['نوع الصفحة'] == selected_type], use_container_width=True)

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            df_p = df[df['نوع الصفحة'] == 'صفحة منتج']
            if not df_p.empty: zip_file.writestr("1_المنتجات_products.csv", df_p.to_csv(index=False, encoding='utf-8-sig'))
            df_c = df[df['نوع الصفحة'] == 'صفحة تصنيف']
            if not df_c.empty: zip_file.writestr("2_التصنيفات_categories.csv", df_c.to_csv(index=False, encoding='utf-8-sig'))
            df_i = df[df['نوع الصفحة'] == 'صفحة تعريفية']
            if not df_i.empty: zip_file.writestr("3_الصفحات_التعريفية_pages.csv", df_i.to_csv(index=False, encoding='utf-8-sig'))
            df_h = df[df['نوع الصفحة'] == 'صفحة رئيسية']
            if not df_h.empty: zip_file.writestr("4_الصفحة_الرئيسية_homepage.csv", df_h.to_csv(index=False, encoding='utf-8-sig'))
            
            excel_buf = io.BytesIO()
            with pd.ExcelWriter(excel_buf, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='SEO Audit')
            zip_file.writestr("التقرير_الشامل_all_pages.xlsx", excel_buf.getvalue())

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
                label="📦 تحميل حزمة البيانات المصنفة (ملف ZIP)",
                data=zip_buffer.getvalue(),
                file_name=f"Data_Package_{urlparse(st.session_state.current_url).netloc}.zip",
                mime="application/zip"
            )

elif nav == "📁 سجل المتاجر السابقة":
    st.title("📁 سجل المتاجر المفحوصة مسبقاً")
    st.write("يمكنك استعراض أي متجر قمت بفتحه مسبقاً وإعادة تحميل تقاريره فوراً دون إعادة الفحص.")

    conn = sqlite3.connect(DB_FILE)
    history_df = pd.read_sql_query("SELECT id, domain as 'المتجر', scan_date as 'تاريخ الفحص', score as 'النسبة', total_pages as 'الصفحات', products_count as 'المنتجات', categories_count as 'الأقسام', info_pages_count as 'الصفحات التعريفية' FROM audits ORDER BY id DESC", conn)
    conn.close()

    if history_df.empty:
        st.info("لا توجد متاجر مفحوصة بعد في السجل.")
    else:
        st.dataframe(history_df.drop(columns=['id']), use_container_width=True)

        selected_id = st.selectbox("اختر المتجر لاسترجاع بياناته وتحميل ملفاته:", history_df['id'].tolist(), format_func=lambda x: f"متجر: {history_df[history_df['id']==x]['المتجر'].values[0]} ({history_df[history_df['id']==x]['تاريخ الفحص'].values[0]})")

        if st.button("📥 استرجاع بيانات هذا المتجر للشاشة"):
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute("SELECT domain, data_json, score, total_pages, products_count, categories_count, info_pages_count FROM audits WHERE id = ?", (selected_id,))
            row = c.fetchone()
            conn.close()

            if row:
                st.session_state.current_url = row[0]
                st.session_state.audit_df = pd.read_json(row[1])
                st.session_state.summary = {
                    'total_pages': row[3],
                    'score': row[2],
                    'products': row[4],
                    'categories': row[5],
                    'info_pages': row[6],
                    'bad_titles': len(st.session_state.audit_df[st.session_state.audit_df['حالة العنوان'] != 'سليم']),
                    'bad_descs': len(st.session_state.audit_df[st.session_state.audit_df['حالة الوصف'] != 'سليم']),
                    'missing_alts': int(st.session_state.audit_df['صور بدون Alt'].sum())
                }
                st.success("تم استرجاع البيانات بنجاح! انتقل إلى صفحة (فحص متجر جديد) في القائمة الجانبية لتحميل ملفات الـ PDF و الـ ZIP.")
