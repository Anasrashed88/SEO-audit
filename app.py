import streamlit as st
import requests
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
import pandas as pd
import time
import io

st.set_page_config(page_title="مركز عمليات السيو الشامل", layout="wide", page_icon="🚀")

st.markdown("""
    <style>
    .main { direction: rtl; text-align: right; }
    h1, h2, h3, p, div { text-align: right; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
    </style>
""", unsafe_allow_html=True)

st.title("🚀 مركز عمليات السيو الشامل للمتاجر")
st.write("أداة الفحص الشامل والمحصنة ضد الحظر لكل صفحات وتصنيفات المتجر الإلكتروني.")

target_url = st.text_input("أدخل رابط المتجر الإلكتروني (مثال: https://pinkit.sa):")

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept-Language': 'ar,en;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
}

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

def audit_single_page(url):
    # محاولة الفحص مع إعادة المحاولة في حال وجود 429
    res = None
    for attempt in range(3):
        try:
            res = requests.get(url, headers=HEADERS, timeout=12)
            if res.status_code == 429:
                time.sleep(2 * (attempt + 1))  # انتظر ثانيتين ثم أربع ثوانٍ وتجاوز الحظر
                continue
            break
        except:
            time.sleep(1)

    # إذا تعذر الفتح تماماً
    if res is None or res.status_code != 200:
        status_code = res.status_code if res else 'فشل اتصال'
        return {
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

    # 1. فحص Title
    title_tag = soup.find('title')
    title = title_tag.text.strip() if title_tag else ''
    title_status = 'سليم'
    if not title: title_status = 'مفقود'
    elif len(title) < 30: title_status = 'قصير جداً'
    elif len(title) > 65: title_status = 'طويل يتجاوز 65 حرف'

    # 2. فحص Meta Description
    meta_desc_tag = soup.find('meta', attrs={'name': 'description'}) or soup.find('meta', attrs={'property': 'og:description'})
    meta_desc = meta_desc_tag['content'].strip() if meta_desc_tag and 'content' in meta_desc_tag.attrs else ''
    desc_status = 'سليم'
    if not meta_desc: desc_status = 'مفقود'
    elif len(meta_desc) < 70: desc_status = 'قصير جداً'
    elif len(meta_desc) > 165: desc_status = 'طويل يتجاوز 165 حرف'

    # 3. فحص الصور و Alt
    images = soup.find_all('img')
    total_img = len(images)
    missing_alt = sum(1 for img in images if not img.get('alt', '').strip())

    # 4. فحص المحتوى
    for s in soup(['script', 'style', 'nav', 'footer']): s.decompose()
    words = len(soup.get_text(separator=' ', strip=True).split())
    content_status = 'جيد' if words >= 50 else 'ضعيف جداً'

    # حساب السكور
    score = 100
    if title_status != 'سليم': score -= 25
    if desc_status != 'سليم': score -= 25
    if total_img > 0 and missing_alt > 0: score -= int((missing_alt / total_img) * 25)
    if content_status != 'جيد': score -= 25
    score = max(0, score)

    return {
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

if st.button("🔍 ابدأ الفحص الشامل لكل الصفحات"):
    if not target_url:
        st.warning("الرجاء إدخال رابط المتجر أولاً.")
    else:
        with st.spinner("جاري استخراج خرائط الموقع وفهرس الروابط..."):
            urls = get_sitemap_urls(target_url)

        st.info(f"تم العثور على {len(urls)} صفحة. جاري الفحص المتأني لتفادي حظر الخوادم...")

        progress_bar = st.progress(0)
        results = []

        for i, u in enumerate(urls):
            results.append(audit_single_page(u))
            progress_bar.progress((i + 1) / len(urls))
            time.sleep(0.3)  # وتيرة متزنة لتجنب 429

        df = pd.DataFrame(results)

        st.success(" اكتمل الفحص الشامل بنجاح!")
        avg_score = round(df['درجة السيو'].mean(), 1)

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("إجمالي الصفحات المفحوصة", len(df))
        col2.metric("نسبة توافق المتجر الحقيقية", f"{avg_score}%")
        col3.metric("عناوين مفقودة/غير سليمة", len(df[df['حالة العنوان'] != 'سليم']))
        col4.metric("أوصاف ميتا مفقودة/غير سليمة", len(df[df['حالة الوصف'] != 'سليم']))

        st.subheader("📋 تقرير الفحص التفصيلي المنظم")
        st.dataframe(df, use_container_width=True)

        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='SEO Audit')

        st.download_button(
            label="📥 تحميل التقرير الشامل بصيغة Excel (منظم 100%)",
            data=buffer.getvalue(),
            file_name="full_store_seo_audit.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
