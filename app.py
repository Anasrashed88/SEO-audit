import base64
import io
import json
from pathlib import Path
import sqlite3
import time
from datetime import datetime
from urllib.parse import urlparse

import pandas as pd
import streamlit as st

# استيراد الوحدات الثلاث كحزم نظيفة ومباشرة
import audit_engine as ae
import export_utils as exp
import pdf_generator as pdf_gen

from audit_engine import (
    MAX_PAGES_DEFAULT, PAGE_TYPE_ORDER,
    PLATFORM_LABEL, SUPPORTED_PLATFORMS,
    TITLE_MIN_OK, TITLE_MAX, TITLE_MIN_OPTIMAL,
    DESC_MIN_OK, DESC_MAX, DESC_MIN_OPTIMAL,
    ALT_MAX, ALT_DUP_THRESHOLD, ALT_WEAK_STATES,
    T_PRODUCT,
    CHECK_FAIL, CHECK_WARN, CHECK_PASS,
    normalize_url, unique_images, compute_summary, run_full_scan
)
from export_utils import (
    PAGE_TYPE_LABEL, STATUS_LABEL, QUALITY_LABEL, URL_LABEL,
    localize_df, build_zip
)
from pdf_generator import (
    DEFAULT_PRICES, LOGO_PATH,
    build_quote, generate_client_pdf, generate_invoice_pdf
)

DB_FILE = str(Path(__file__).parent / "store_history.db")

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
    conn.commit()
    conn.close()

init_db()

for key, default in [('audit_df', None), ('images_df', None), ('summary', None),
                     ('current_url', ""), ('coverage', None), ('platform', 'unknown'),
                     ('dup_titles', None), ('dup_descs', None)]:
    if key not in st.session_state:
        st.session_state[key] = default

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
.bar-label { flex:0 0 160px; font-size:12.5px; color:#334155; }
.bar-track { flex:1; height:9px; background:#f1f5f9; border-radius:5px; overflow:hidden; }
.bar-fill { height:100%; border-radius:5px; }
.bar-value { flex:0 0 46px; font-size:12px; color:#475569; text-align:left; }
.finding { border-right:4px solid; border-radius:8px; padding:11px 14px; margin-bottom:9px; background:#fff; border-top:1px solid #e2e8f0; border-bottom:1px solid #e2e8f0; border-left:1px solid #e2e8f0; font-size:13.5px; color:#334155; }
.finding b { color:#0f172a; }
.stTabs [data-baseweb="tab-list"] { gap:4px; direction:rtl; }
.stTabs [data-baseweb="tab"] { font-size:14px; font-weight:500; padding:8px 16px; }
div[data-testid="stDataFrame"] { direction:ltr; }
</style>
""", unsafe_allow_html=True)

def render_brandbar():
    st.markdown(
        f'<div class="brandbar">'
        f'<div><div class="name">أنس راشد</div>'
        f'<div class="role">خبير تحسين محركات البحث للمتاجر الإلكترونية</div></div>'
        f'<div style="display:flex;align-items:center;gap:18px">'
        f'<div class="tool">مركز عمليات السيو<br>anasrashed.com</div></div></div>',
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

render_brandbar()

with st.sidebar:
    st.markdown("### 🧭 التحكم")
    nav = st.radio("", ["🔍 فحص المتجر", "📁 السجل السابق"], label_visibility="collapsed")
    st.markdown("---")
    st.markdown("#### ⚙️ إعدادات الفحص")
    max_pages = st.slider("الحد الأقصى للصفحات", 50, 3000, 1000, 50)
    workers = st.slider("عدد مسارات الزحف (Workers)", 1, 6, 3, help="القيم بين 2 و 4 هي الأنسب لتجنب حظر Cloudflare")

if nav == "🔍 فحص المتجر":
    c1, c2 = st.columns([5, 1])
    with c1:
        target_input = st.text_input("رابط المتجر", placeholder="https://example.com", value=st.session_state.current_url)
    with c2:
        st.write("")
        st.write("")
        start_btn = st.button("بدء الفحص", type="primary", use_container_width=True)

    if start_btn and target_input:
        for k in ['audit_df', 'images_df', 'summary', 'coverage', 'dup_titles', 'dup_descs']:
            st.session_state[k] = None

        target_clean = normalize_url(target_input)
        st.session_state.current_url = target_clean

        with st.status("جارٍ فحص المتجر بدقة...", expanded=True) as status:
            prog_bar = st.progress(0.0, text="بدء تجهيز الفحص (0%)...")
            df, imgs_df, summary, coverage, dup_t, dup_d = run_full_audit(
                target_clean, max_pages=max_pages, workers=workers,
                progress_cb=lambda pct, msg: prog_bar.progress(pct, text=msg)
            )
            prog_bar.progress(1.0, text="اكتمل الفحص بالكامل (100%)")
            status.update(label="اكتمل الفحص بنجاح!", state="complete", expanded=False)

        st.session_state.audit_df = df
        st.session_state.images_df = imgs_df
        st.session_state.summary = summary
        st.session_state.coverage = coverage
        st.session_state.dup_titles = dup_t
        st.session_state.dup_descs = dup_d
        st.session_state.platform = summary['platform']

        conn = sqlite3.connect(DB_FILE)
        conn.cursor().execute(
            '''INSERT INTO audits (domain, scan_date, score, total_pages, products_count,
               categories_count, info_pages_count, blog_pages_count, data_json, images_json, coverage_json, platform)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
            (target_clean, datetime.now().strftime("%Y-%m-%d %H:%M"), summary['score'],
             summary['total_pages'], summary['products'], summary['categories'],
             summary['info_pages'], summary['blog_pages'], df.to_json(orient='records'),
             imgs_df.to_json(orient='records') if imgs_df is not None and not imgs_df.empty else '',
             json.dumps(coverage, ensure_ascii=False), summary['platform'])
        )
        conn.commit()
        conn.close()

    if st.session_state.audit_df is not None:
        df = st.session_state.audit_df
        imgs_df = st.session_state.images_df
        summary = st.session_state.summary
        coverage = st.session_state.coverage

        sc = summary['score']
        sc_col = COLOR['ok'] if sc >= 80 else (COLOR['warn'] if sc >= 60 else COLOR['bad'])

        st.markdown(
            f'<div class="hero">'
            f'<div><div class="score" style="color:{sc_col}">{sc}%</div>'
            f'<div class="scorelbl">درجة توافق السيو الفعلية</div></div>'
            f'<div><div class="store">{urlparse(st.session_state.current_url).netloc}</div>'
            f'<div class="plat">المنصة: {PLATFORM_LABEL.get(summary["platform"], "غير محددة")}</div></div></div>',
            unsafe_allow_html=True
        )

        cards = [
            (summary["total_pages"], "الصفحات المفحوصة", COLOR['accent']),
            (summary["products"], "المنتجات", COLOR['accent']),
            (summary["missing_titles"] + summary["duplicate_titles"], "مشاكل العناوين", COLOR['bad'] if summary["missing_titles"] else COLOR['ok']),
            (summary["title_mismatch"], "عناوين تخالف H1", COLOR['warn'] if summary["title_mismatch"] else COLOR['ok']),
            (summary["missing_descs"] + summary["duplicate_descs"], "مشاكل الأوصاف", COLOR['bad'] if summary["missing_descs"] else COLOR['ok']),
            (summary["missing_alts"], "صور فريدة بدون Alt", COLOR['bad'] if summary["missing_alts"] else COLOR['ok']),
        ]
        cols = st.columns(len(cards))
        for col, (v, l, c) in zip(cols, cards):
            with col:
                st.markdown(metric_card(v, l, c), unsafe_allow_html=True)

        st.write("")
        tabs = st.tabs(["📊 الملخص والنتائج", "🏷️ العناوين و H1", "📝 أوصاف الميتا", "🖼️ تدقيق الصور الفريدة", "🗺️ الخريطة والظهور", "📥 التصدير والتقارير"])

        with tabs[0]:
            c1, c2 = st.columns(2)
            with c1:
                t_items = [
                    (PAGE_TYPE_LABEL['ar'].get(k, k), int((df['نوع الصفحة'] == k).sum()))
                    for k in PAGE_TYPE_ORDER if (df['نوع الصفحة'] == k).any()
                ]
                st.markdown(bar_chart("توزيع صفحات المتجر", t_items), unsafe_allow_html=True)
            with c2:
                alt_items = [
                    ("سليم", int((imgs_df['حالة النص البديل'] == 'alt_ok').sum())),
                    ("مفقود", int((imgs_df['حالة النص البديل'] == 'alt_missing').sum())),
                    ("مكرر", int((imgs_df['حالة النص البديل'] == 'alt_duplicate').sum())),
                    ("غير وصفي", int((imgs_df['حالة النص البديل'] == 'alt_generic').sum())),
                ] if imgs_df is not None and not imgs_df.empty else []
                st.markdown(bar_chart("جودة نصوص الصور الفريدة (Alt)", alt_items, {
                    "سليم": COLOR['ok'], "مفقود": COLOR['bad'], "مكرر": COLOR['warn'], "غير وصفي": COLOR['bad']
                }), unsafe_allow_html=True)

            st.markdown("#### أهم الملاحظات المكتشفة:")
            if summary['missing_titles']:
                st.markdown(finding(f"يوجد <b>{summary['missing_titles']}</b> صفحة بدون عنوان ميتا أو عنوانها عبارة عن رموز فقط.", 'bad'), unsafe_allow_html=True)
            if summary['duplicate_titles']:
                st.markdown(finding(f"تم رصد <b>{summary['duplicate_titles']}</b> عنوان ميتا مكرر بين أكثر من صفحة.", 'warn'), unsafe_allow_html=True)
            if summary['title_mismatch']:
                st.markdown(finding(f"يوجد <b>{summary['title_mismatch']}</b> صفحة عنوان الميتا فيها لا يطابق اسم المنتج/القسم الظاهر (H1).", 'warn'), unsafe_allow_html=True)
            if summary['missing_alts']:
                st.markdown(finding(f"يوجد <b>{summary['missing_alts']}</b> صورة فريدة لا تحمل أي نص بديل وتغيب عن بحث صور جوجل.", 'bad'), unsafe_allow_html=True)
            if coverage['unlisted_pages']:
                st.markdown(finding(f"تم اكتشاف <b>{len(coverage['unlisted_pages'])}</b> صفحة معروضة في المتجر ولكنها غائبة تماماً عن خريطة الموقع (Sitemap).", 'warn'), unsafe_allow_html=True)

        with tabs[1]:
            st.markdown("#### فحص العناوين ومطابقتها لـ H1")
            view_titles = df[['الرابط', 'نوع الصفحة', 'عنوان الميتا', 'طول العنوان', 'حالة العنوان', 'عنوان الصفحة (H1)', 'مطابقة العنوان مع H1']].copy()
            view_titles['نوع الصفحة'] = view_titles['نوع الصفحة'].map(lambda x: PAGE_TYPE_LABEL['ar'].get(x, x))
            view_titles['حالة العنوان'] = view_titles['حالة العنوان'].map(lambda x: STATUS_LABEL['ar'].get(x, x))
            view_titles['مطابقة العنوان مع H1'] = view_titles['مطابقة العنوان مع H1'].map(lambda x: STATUS_LABEL['ar'].get(x, x))
            st.dataframe(view_titles, use_container_width=True)

        with tabs[2]:
            st.markdown("#### فحص أوصاف الميتا (Meta Description)")
            view_descs = df[['الرابط', 'نوع الصفحة', 'وصف الميتا', 'طول الوصف', 'حالة الوصف']].copy()
            view_descs['نوع الصفحة'] = view_descs['نوع الصفحة'].map(lambda x: PAGE_TYPE_LABEL['ar'].get(x, x))
            view_descs['حالة الوصف'] = view_descs['حالة الوصف'].map(lambda x: STATUS_LABEL['ar'].get(x, x))
            st.dataframe(view_descs, use_container_width=True)

        with tabs[3]:
            st.markdown("#### تدقيق نصوص الصور الفريدة (Alt Text)")
            if imgs_df is not None and not imgs_df.empty:
                v_imgs = imgs_df.copy()
                v_imgs['نوع الصفحة'] = v_imgs['نوع الصفحة'].map(lambda x: PAGE_TYPE_LABEL['ar'].get(x, x))
                v_imgs['حالة النص البديل'] = v_imgs['حالة النص البديل'].map(lambda x: STATUS_LABEL['ar'].get(x, x))
                st.dataframe(v_imgs, use_container_width=True)
                st.caption(f"تم حصر {len(v_imgs)} صورة محتوى فريدة (تم استبعاد الصور المكررة وأصول القوالب والشعارات).")
            else:
                st.info("لم يتم العثور على صور محتوى مفحوصة.")

        with tabs[4]:
            st.markdown("#### مطابقة صفحات المتجر مع خريطة الموقع")
            m1, m2, m3 = st.columns(3)
            m1.metric("روابط الخريطة", coverage['sitemap_count'])
            m2.metric("صفحات معروضة خارج الخريطة", len(coverage['unlisted_pages']))
            m3.metric("صفحات يتيمة بالخريطة", len(coverage['orphan_pages']))
            st.write("")
            if coverage['unlisted_pages']:
                with st.expander("📄 صفحات معروضة لكنها مفقودة من السايت ماب:"):
                    st.write(coverage['unlisted_pages'])
            if coverage['orphan_pages']:
                with st.expander("👻 صفحات يتيمة (في السايت ماب ولا توجد روابط لها بالمتجر):"):
                    st.write(coverage['orphan_pages'])

        with tabs[5]:
            st.markdown("#### 📥 تصدير البيانات والتقارير")
            clean_dom = urlparse(st.session_state.current_url).netloc or "store"

            zip_bytes = build_zip_package(df, imgs_df, coverage, lang='ar')
            client_pdf = generate_client_pdf(clean_dom, summary['score'], summary, coverage, lang='ar')

            p_title = 15.0
            p_desc = 10.0
            p_alt = 3.0

            qty_titles = summary['missing_titles'] + summary['duplicate_titles'] + summary['title_mismatch']
            qty_descs = summary['missing_descs'] + summary['duplicate_descs'] + summary['short_descs']
            qty_alts = summary['missing_alts'] + summary['weak_alts']

            quote = {
                'items': [
                    {'name': 'إصلاح وصياغة عناوين الميتا و H1', 'qty': qty_titles, 'unit': p_title, 'total': qty_titles * p_title},
                    {'name': 'كتابة أوصاف ميتا فريدة وجذابة', 'qty': qty_descs, 'unit': p_desc, 'total': qty_descs * p_desc},
                    {'name': 'صياغة نصوص بديلة للصور الفريدة (Alt Text)', 'qty': qty_alts, 'unit': p_alt, 'total': qty_alts * p_alt},
                ],
                'total': (qty_titles * p_title) + (qty_descs * p_desc) + (qty_alts * p_alt)
            }
            inv_pdf = generate_invoice_pdf(clean_dom, quote, lang='ar')

            d1, d2, d3 = st.columns(3)
            with d1:
                st.download_button(
                    "📦 تحميل حزمة البيانات (ZIP)",
                    data=zip_bytes,
                    file_name=f"SEO_Data_{clean_dom}.zip",
                    mime="application/zip",
                    use_container_width=True,
                    help="تشمل جميع ملفات CSV مقسمة + ملف الإكسل الشامل + قوائم الإصلاح الفوري"
                )
            with d2:
                st.download_button(
                    "📄 تحميل تقرير العميل (PDF)",
                    data=client_pdf,
                    file_name=f"SEO_Audit_Report_{clean_dom}.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                    help="تقرير فني شامل ومصمم لتقديمه للعميل مباشرة"
                )
            with d3:
                st.download_button(
                    "🧾 تحميل عرض السعر (PDF)",
                    data=inv_pdf,
                    file_name=f"Quotation_{clean_dom}.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                    help="عرض سعر احترافي مع رمز الريال السعودي على يسار السعر"
                )

            st.markdown("---")
            st.markdown("##### 📄 تحميل ملفات CSV منفصلة:")
            fix_df, noalt_df = build_fix_lists(df, imgs_df, lang='ar')
            c_csv1, c_csv2 = st.columns(2)
            with c_csv1:
                if not fix_df.empty:
                    st.download_button(
                        "📥 تحميل قائمة الصفحات التي تحتاج إصلاح (CSV)",
                        data=fix_df.to_csv(index=False, encoding='utf-8-sig'),
                        file_name=f"Pages_To_Fix_{clean_dom}.csv",
                        mime="text/csv",
                        use_container_width=True
                    )
            with c_csv2:
                if not noalt_df.empty:
                    st.download_button(
                        "📥 تحميل قائمة الصور التي تحتاج وصف (CSV)",
                        data=noalt_df.to_csv(index=False, encoding='utf-8-sig'),
                        file_name=f"Images_To_Fix_{clean_dom}.csv",
                        mime="text/csv",
                        use_container_width=True
                    )

else:
    st.markdown("### 📁 سجل المتاجر السابقة")
    conn = sqlite3.connect(DB_FILE)
    hist = pd.read_sql_query("SELECT id, domain, scan_date, score, total_pages, products_count FROM audits ORDER BY id DESC", conn)
    conn.close()
    if not hist.empty:
        st.dataframe(hist, use_container_width=True)
    else:
        st.info("لا توجد فحوصات محفوظة بعد.")
