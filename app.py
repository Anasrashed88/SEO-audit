import streamlit as st
import requests
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
import pandas as pd
import time
import io
import zipfile
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor

st.set_page_config(page_title="مركز عمليات السيو الشامل", layout="wide", page_icon="🚀")

st.markdown("""
    <style>
    .main { direction: rtl; text-align: right; }
    h1, h2, h3, p, div { text-align: right; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
    </style>
""", unsafe_allow_html=True)

st.title("🚀 مركز عمليات السيو الشامل للمتاجر")
st.write("أداة الفحص والتصنيف التلقائي لجميع أقسام ومنتجات المتجر مع التصدير المنفصل.")

target_url = st.text_input("أدخل رابط المتجر الإلكتروني (مثال: https://pinkit.sa):")

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept-Language': 'ar,en;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
}

def detect_page_type(url, base_url):
    """تصنيف الصفحة تلقائياً بدون ذكاء اصطناعي"""
    base_clean = base_url.rstrip('/')
    url_clean = url.rstrip('/')
    
    if url_clean == base_clean:
        return 'صفحة رئيسية'
    
    path = urlparse(url).path.lower()
    
    # 1. فحص المنتجات (سلة، زد، شوبيفاي)
    if '/products/' in path or '/product/' in path or '/p/' in path:
        return 'صفحة منتج'
    # نمط سلة الشهير للمنتجات: يبدأ بـ /p متبوعاً بأرقام
    segments = [s for s in path.split('/') if s]
    if segments and segments[0].startswith('p') and any(char.isdigit() for char in segments[0][:5]):
        return 'صفحة منتج'

    # 2. فحص التصنيفات والكولكشنات
    if any(k in path for k in ['/category/', '/categories/', '/collection/', '/collections/', '/c/']):
        return 'صفحة تصنيف'
    if segments and (segments[0] in ['c', 'categories', 'collections', 'category']):
        return 'صفحة تصنيف'

    # 3. فحص الصفحات التعريفية والسياسات
    if any(k in path for k in ['/pages/', '/policies/', 'privacy', 'terms', 'about', 'contact', 'faq', 'shipping']):
        return 'صفحة تعريفية'

    return 'صفحة عامة'

def get_sitemap_urls(base_url):
    base_url = base_url.rstrip('/')
    sitemap_candidates = [
        f"{base_url}/sitemap.xml",
        f"{base_url}/sitemap_products_1.xml",
        f"{base_url}/sitemap_categories.xml"
    ]
    found_urls = set()
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
                                found_urls.add(sub_loc.text.strip())
                    else:
                        found_urls.add(u)
        except:
            continue
    if not found_urls:
        found_urls.add(base_url)
    return list(found_urls)

def audit_single_page(url_item):
    url, base_url = url_item
    page_type = detect_page_type(url, base_url)
    
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
            'نوع الصفحة': page_type,
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

    # 1. Title
    title_tag = soup.find('title')
    title = title_tag.text.strip() if title_tag else ''
    title_status = 'سليم'
    if not title: title_status = 'مفقود'
    elif len(title) < 30: title_status = 'قصير جداً'
    elif len(title) > 65: title_status = 'طويل جداً'

    # 2. Meta Description
    meta_desc_tag = soup.find('meta', attrs={'name': 'description'}) or soup.find('meta', attrs={'property': 'og:description'})
    meta_desc = meta_desc_tag['content'].strip() if meta_desc_tag and 'content' in meta_desc_tag.attrs else ''
    desc_status = 'سليم'
    if not meta_desc: desc_status = 'مفقود'
    elif len(meta_desc) < 70: desc_status = 'قصير جداً'
    elif len(meta_desc) > 165: desc_status = 'طويل جداً'

    # 3. Images & Alt
    images = soup.find_all('img')
    total_img = len(images)
    missing_alt = sum(1 for img in images if not img.get('alt', '').strip())

    # 4. Words
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

if st.button("🔍 ابدأ الفحص السريع والمصنف"):
    if not target_url:
        st.warning("الرجاء إدخال رابط المتجر أولاً.")
    else:
        with st.spinner("جاري استخراج خرائط الموقع وفهرس الروابط..."):
            urls = get_sitemap_urls(target_url)

        st.info(f"تم العثور على {len(urls)} صفحة. جاري الفحص السريع والذكي عبر مسارات متعددة...")

        progress_bar = st.progress(0)
        results = []
        url_tuples = [(u, target_url) for u in urls]

        # فحص سريع ومتعدد الخيوط (5 مسارات آمنة في نفس الوقت)
        total_urls = len(urls)
        completed = 0
        
        with ThreadPoolExecutor(max_workers=5) as executor:
            for res in executor.map(audit_single_page, url_tuples):
                results.append(res)
                completed += 1
                progress_bar.progress(completed / total_urls)
                time.sleep(0.05)

        df = pd.DataFrame(results)

        st.success(" اكتمل الفحص الشامل وتصنيف الصفحات بنجاح!")
        avg_score = round(df['درجة السيو'].mean(), 1)

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("إجمالي الصفحات", len(df))
        col2.metric("نسبة توافق المتجر الكلية", f"{avg_score}%")
        col3.metric("عدد المنتجات المفحوصة", len(df[df['نوع الصفحة'] == 'صفحة منتج']))
        col4.metric("عدد الأقسام المفحوصة", len(df[df['نوع الصفحة'] == 'صفحة تصنيف']))

        # تصفية حسب نوع الصفحة
        st.subheader("📋 تقرير الفحص مصنفاً حسب الأقسام")
        selected_type = st.selectbox("عرض البيانات حسب نوع الصفحة:", ["جميع الصفحات", "صفحة منتج", "صفحة تصنيف", "صفحة تعريفية", "صفحة رئيسية"])
        
        if selected_type == "جميع الصفحات":
            st.dataframe(df, use_container_width=True)
        else:
            st.dataframe(df[df['نوع الصفحة'] == selected_type], use_container_width=True)

        # تجهيز ملف الـ ZIP مع ملفات منفصلة
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            # 1. المنتجات
            df_products = df[df['نوع الصفحة'] == 'صفحة منتج']
            if not df_products.empty:
                zip_file.writestr("1_المنتجات_products.csv", df_products.to_csv(index=False, encoding='utf-8-sig'))
            
            # 2. التصنيفات
            df_cats = df[df['نوع الصفحة'] == 'صفحة تصنيف']
            if not df_cats.empty:
                zip_file.writestr("2_التصنيفات_categories.csv", df_cats.to_csv(index=False, encoding='utf-8-sig'))
                
            # 3. الصفحات التعريفية
            df_pages = df[df['نوع الصفحة'] == 'صفحة تعريفية']
            if not df_pages.empty:
                zip_file.writestr("3_الصفحات_التعريفية_pages.csv", df_pages.to_csv(index=False, encoding='utf-8-sig'))
                
            # 4. الصفحة الرئيسية
            df_home = df[df['نوع الصفحة'] == 'صفحة رئيسية']
            if not df_home.empty:
                zip_file.writestr("4_الصفحة_الرئيسية_homepage.csv", df_home.to_csv(index=False, encoding='utf-8-sig'))
                
            # 5. التقرير الكامل كإكسل داخل الـ ZIP
            excel_buffer = io.BytesIO()
            with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='All Pages')
            zip_file.writestr("التقرير_الشامل_all_pages.xlsx", excel_buffer.getvalue())

        col_d1, col_d2 = st.columns(2)
        with col_d1:
            st.download_button(
                label="📦 تحميل حزمة التقارير المصنفة (ملف ZIP يحتوي على ملف لكل نوع)",
                data=zip_buffer.getvalue(),
                file_name="store_seo_audit_classified.zip",
                mime="application/zip"
            )
