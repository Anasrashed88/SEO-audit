"""واجهة مركز عمليات السيو — Streamlit."""
import io
import json
import time
import sqlite3
from datetime import datetime
from urllib.parse import urlparse, unquote

import pandas as pd
import streamlit as st

import audit_engine as eng
from audit_engine import (
    DB_FILE, LOGO_PATH, MAX_PAGES_DEFAULT, PAGE_TYPE_ORDER, PAGE_TYPE_LABEL,
    STATUS_LABEL, QUALITY_LABEL, URL_LABEL, COLOR, COL_EN, ALT_WEAK_STATES,
    ALT_DUP_THRESHOLD, ALT_MAX, TITLE_MAX, TITLE_MIN_OPTIMAL, TITLE_MIN_OK,
    DESC_MAX, DESC_MIN_OPTIMAL, DESC_MIN_OK, PLATFORM_LABEL, PLATFORM_LABEL_EN,
    SUPPORTED_PLATFORMS, T_HOME, T_PRODUCT, T_CATEGORY, T_BLOG, T_INFO,
    T_ARCHIVE, T_UNKNOWN, T_BROKEN, CHECK_FAIL, CHECK_WARN, CHECK_PASS,
    init_db, run_full_scan, compute_summary, localize_df, unique_images,
    normalize_url, clean_url, dedupe_pages, run_self_checks,
    url_key, build_broken_links, build_zid_redirects, verify_redirects,
)
from pdf_generator import generate_client_pdf, generate_invoice_pdf, build_quote, DEFAULT_PRICES
from export_utils import (build_zip, build_filtered_exports, to_csv_bytes, build_filtered_zip,
                          table_bytes)

st.set_page_config(page_title="مركز عمليات السيو | أنس راشد",
                   layout="wide", page_icon="🚀",
                   initial_sidebar_state="expanded")
init_db()
for _key, _default in [('audit_df', None), ('images_df', None), ('summary', None),
                       ('current_url', ""), ('coverage', None),
                       ('platform', 'unknown'), ('selfcheck', None),
                       ('brand', ''), ('dup_groups', None), ('structured', None)]:
    if _key not in st.session_state:
        st.session_state[_key] = _default
# ==============================================================
#  التنسيق
# ==============================================================
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
.bar-label { flex:0 0 150px; font-size:12.5px; color:#334155; }
.bar-track { flex:1; height:9px; background:#f1f5f9; border-radius:5px; overflow:hidden; }
.bar-fill { height:100%; border-radius:5px; }
.bar-value { flex:0 0 46px; font-size:12px; color:#475569; text-align:left; }
.finding { border-right:4px solid; border-radius:8px; padding:11px 14px; margin-bottom:9px; background:#fff; border-top:1px solid #e2e8f0; border-bottom:1px solid #e2e8f0; border-left:1px solid #e2e8f0; font-size:13.5px; color:#334155; }
.finding b { color:#0f172a; }
.chk { display:flex; gap:12px; align-items:flex-start; border:1px solid #e2e8f0; border-radius:10px; padding:12px 14px; margin-bottom:8px; background:#fff; }
.chk .dot { flex:0 0 10px; height:10px; border-radius:50%; margin-top:6px; }
.chk .t { font-size:13.5px; font-weight:700; color:#0f172a; }
.chk .m { font-size:13px; color:#475569; margin-top:2px; }
.chk .a { font-size:12.5px; color:#b45309; margin-top:5px; }
.verdict { border-radius:12px; padding:16px 20px; margin-bottom:16px; font-size:15px; font-weight:500; }
.v-ready { background:#ecfdf5; border:1px solid #a7f3d0; color:#065f46; }
.v-review { background:#fffbeb; border:1px solid #fde68a; color:#92400e; }
.v-blocked { background:#fef2f2; border:1px solid #fecaca; color:#991b1b; }
.stTabs [data-baseweb="tab-list"] { gap:4px; direction:rtl; }
.stTabs [data-baseweb="tab"] { font-size:14px; font-weight:500; padding:8px 16px; }
div[data-testid="stDataFrame"] { direction:ltr; }
</style>
""", unsafe_allow_html=True)


def infer_store_url(sm_text, sm_files):
    """رابط المتجر من الخرائط نفسها: من رابط خريطة ملصوق، أو من أول رابط داخل ملف مرفوع."""
    for ln in (sm_text or '').splitlines():
        ln = ln.strip()
        if ln.startswith('http'):
            p = urlparse(ln)
            return f"{p.scheme}://{p.netloc}"
    for f in sm_files or []:
        for loc in (eng.parse_sitemap_text(f.getvalue(), f.name) or []):
            if str(loc).startswith('http'):
                p = urlparse(loc)
                return f"{p.scheme}://{p.netloc}"
    return ''


def logo_data_uri():
    try:
        import base64
        return "data:image/png;base64," + base64.b64encode(LOGO_PATH.read_bytes()).decode()
    except Exception:
        return ""


def render_brandbar():
    logo = logo_data_uri()
    img = f'<img src="{logo}" style="height:40px">' if logo else ''
    st.markdown(
        f'<div class="brandbar">'
        f'<div><div class="name">أنس راشد</div>'
        f'<div class="role">خبير تحسين محركات البحث</div></div>'
        f'<div style="display:flex;align-items:center;gap:18px">'
        f'<div class="tool">مركز عمليات السيو<br>anasrashed.com</div>{img}</div></div>',
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



#  الواجهة
# ==============================================================
render_brandbar()

with st.sidebar:
    st.markdown("### 🧭 القائمة")
    nav = st.radio("", ["🔍 فحص متجر جديد", "📁 سجل المتاجر"], label_visibility="collapsed")
    st.markdown("---")
    st.markdown("#### ⚙️ إعدادات الفحص")
    max_pages = st.number_input("الحد الأقصى للصفحات", 50, 5000, MAX_PAGES_DEFAULT, 50)
    workers = st.slider("المسارات المتوازية", 1, 8, 4)
    do_pagination = st.checkbox("متابعة ترقيم الأقسام عند الحاجة", value=True,
                                help="تعمل تلقائياً فقط إذا كانت خريطة الموقع ناقصة، "
                                     "لتوفير وقت الفحص.")
    do_sitemap_check = st.checkbox("مقارنة مع خريطة الموقع", value=True,
                                   help="تشخيصية فقط — لا تؤثر على أرقام الفحص.")
    conn_modes = [eng.CONN_BROWSER, eng.CONN_PLAIN] + ([eng.CONN_REAL] if eng.HAS_PLAYWRIGHT else [])
    conn_names = {eng.CONN_BROWSER: "بصمة متصفح كروم (موصى به)",
                  eng.CONN_PLAIN: "الاتصال العادي",
                  eng.CONN_REAL: "متصفح حقيقي (للمتاجر المحمية — أبطأ)"}
    conn_choice = st.radio(
        "طريقة الاتصال بالمتجر", conn_modes, format_func=lambda m: conn_names[m],
        index=0 if eng.HAS_CFFI else 1,
        help="إذا رفض المتجر الأداة، اختر «متصفح حقيقي»: يفتح الصفحات بكروم مخفي "
             "كما تفتحها أنت. يعمل على جهازك فقط.")
    if conn_choice == eng.CONN_REAL:
        if st.session_state.get('real_ok') is None:
            with st.spinner("تشغيل المتصفح الحقيقي..."):
                ok, msg = eng.real_browser_available()
            st.session_state.real_ok, st.session_state.real_msg = ok, msg
        if not st.session_state.real_ok:
            st.error(st.session_state.real_msg)
            conn_choice = eng.CONN_BROWSER if eng.HAS_CFFI else eng.CONN_PLAIN
        else:
            st.caption("🐢 صفحة واحدة في كل مرة — فحص 350 صفحة يأخذ تقريباً 10 إلى 15 دقيقة.")
    eng.set_connection_mode(conn_choice)
    use_cache = st.checkbox(
        "استكمال من الفحص السابق (آخر 24 ساعة)", value=True,
        help="كل صفحة تُفحص تُحفظ فوراً. عند إعادة فحص نفس المتجر تؤخذ الصفحات الناجحة "
             "من الحفظ دون طلبها من المتجر، ولا يُفحص إلا ما فشل أو لم يُفحص بعد.")
    gentle = st.checkbox("الوضع الهادئ", value=False,
                         disabled=(conn_choice == eng.CONN_REAL),
                         help="صفحة واحدة في كل مرة مع مهلة ثابتة، واحترام كامل لطلب المتجر "
                              "التمهّل. أبطأ، لكنه يقلل رفض المتاجر التي تقيّد كثرة الطلبات.")
    eng.set_gentle(gentle or conn_choice == eng.CONN_REAL)
    if not eng.HAS_CFFI:
        st.caption("⚠️ بصمة المتصفح غير متاحة: مكتبة curl_cffi غير مثبتة.")
    st.markdown("---")
    st.caption("الأداة معايرة على منصات سلة وزد وشوبيفاي.")

if nav == "🔍 فحص متجر جديد":
    c1, c2 = st.columns([5, 1])
    with c1:
        input_url = st.text_input("رابط المتجر الإلكتروني (أو اتركه فارغاً وارفع خرائط الموقع)",
                                  value=st.session_state.current_url,
                                  placeholder="https://example.store")
    with c2:
        st.write("")
        st.write("")
        start_btn = st.button("بدء الفحص", type="primary", use_container_width=True)

    with st.expander("🗺️ خيارات خريطة الموقع (اختياري) — استخدمها إذا فشلت قراءة الخرائط"):
        st.caption("إذا منعت حماية المتجر الأداة من تحميل ملف خريطة: افتح الملف في متصفحك، "
                   "واحفظه (في Safari: ملف ← حفظ باسم ← التنسيق: مصدر الصفحة)، ثم ارفعه هنا. "
                   "الملفات المرفوعة لا تُحمَّل من المتجر مرة أخرى.")
        sm_text = st.text_area("روابط خرائط الموقع (رابط في كل سطر)", height=80,
                               placeholder="https://example.store/sitemap.xml")
        sm_files = st.file_uploader("رفع ملفات الخريطة", type=['xml', 'gz', 'txt'],
                                    accept_multiple_files=True)

    with st.expander("🔌 اختبار الاتصال بالمتجر — هل يسمح المتجر للأداة بالفحص؟"):
        st.caption("يجرّب صفحة واحدة من المتجر بالطريقتين، ويخبرك أيهما يقبلها المتجر. "
                   "اختر بعدها الطريقة الناجحة من القائمة الجانبية.")
        if st.button("اختبر الاتصال الآن", key="conn_test"):
            test_url = normalize_url(input_url) if (input_url or '').strip() else \
                infer_store_url(sm_text, sm_files)
            if not test_url:
                st.error("اكتب رابط المتجر أولاً.")
            else:
                with st.spinner("جارٍ الاختبار..."):
                    rows = eng.test_connection(test_url)
                st.dataframe(pd.DataFrame(rows).drop(columns=['ok']),
                             use_container_width=True, hide_index=True)
                ok = [r['الطريقة'] for r in rows if r['ok']]
                if not ok:
                    st.warning("المتجر رفض الطريقتين من هذا الجهاز. الفحص سيكون ناقصاً.")
                elif len(ok) == 1:
                    st.success(f"المتجر يقبل: {ok[0]} فقط — اخترها من القائمة الجانبية.")
                else:
                    st.success("المتجر يقبل الطريقتين.")

    if st.session_state.audit_df is not None:
        if st.sidebar.button("🔄 تفريغ الشاشة", use_container_width=True):
            for k in ['audit_df', 'images_df', 'summary', 'coverage', 'selfcheck',
                      'dup_groups', 'structured', 'sitemap_report']:
                st.session_state[k] = None
            st.session_state.current_url = ""
            st.rerun()

    resume_now = st.session_state.pop('resume_now', False)
    if resume_now:
        start_btn = True
        input_url = input_url or st.session_state.current_url

    if start_btn and not (input_url or '').strip():
        input_url = infer_store_url(sm_text, sm_files)
        if input_url:
            st.info(f"رابط المتجر من خريطة الموقع: {input_url}")
        else:
            st.error("اكتب رابط المتجر، أو ارفع ملف خريطة موقع صالحاً.")

    if start_btn and input_url:
        target = normalize_url(input_url)
        st.session_state.current_url = target

        with st.status("جارٍ الفحص...", expanded=True) as status:
            head = st.empty()
            bar = st.progress(0)
            note = st.empty()

            def progress(stage, **kw):
                if stage == 'discover_start':
                    head.write("**المرحلة 1** — قراءة خريطة الموقع وفحص الصفحات")
                elif stage == 'sitemap_read':
                    note.caption("جارٍ قراءة خريطة الموقع...")
                elif stage == 'cache_loaded':
                    n = kw.get('count', 0)
                    if not kw.get('enabled'):
                        st.caption("الاستكمال موقوف من الإعدادات — فحص كامل من البداية.")
                    elif n:
                        st.info(f"♻️ وُجدت {n} صفحة محفوظة من فحص سابق لهذا المتجر. "
                                "لن تُطلب من المتجر مرة أخرى — يُفحص الباقي فقط.")
                    else:
                        st.caption("لا توجد نتائج محفوظة لهذا المتجر — فحص كامل من البداية.")
                elif stage == 'audit':
                    done, pend = kw.get('done', 0), kw.get('pending', 0)
                    cached = kw.get('cached', 0)
                    bar.progress(min(done / max(done + pend, 1), 1.0))
                    fresh = done - cached
                    note.caption(f"فُحصت {fresh} صفحة من المتجر · {cached} من الحفظ دون طلب · "
                                 f"{pend} في الانتظار")
                elif stage == 'pagination_start':
                    head.write("**المرحلة 2** — متابعة ترقيم القوائم")
                    bar.progress(0)
                elif stage == 'pagination':
                    bar.progress(min(kw.get('i', 0) / max(kw.get('total', 1), 1), 1.0))
                    note.caption(f"{kw.get('i')}/{kw.get('total')} قسم · "
                                 f"{kw.get('found')} منتج إضافي · "
                                 f"{kw.get('fetched')} صفحة مجلوبة")
                elif stage == 'extra_start':
                    head.write(f"**المرحلة 3** — فحص {kw.get('count')} منتج "
                               "من الصفحات التالية")
                    bar.progress(0)
                elif stage == 'sitemap_retry':
                    note.caption(f"إعادة قراءة هادئة لـ {kw.get('count')} ملف خريطة تعذّر تحميله...")
                elif stage == 'pagination_skipped':
                    note.caption(f"تخطّي متابعة الترقيم: {kw.get('reason')}")
                elif stage == 'retry_aborted':
                    note.caption("المتجر رفض أغلب عيّنة إعادة المحاولة — توقفت الأداة حتى لا تنتظر بلا فائدة. "
                                 "استخدم «أكمل الفحص» لاحقاً.")
                elif stage == 'retry_start':
                    head.write(f"**إعادة محاولة** — {kw.get('count')} صفحة "
                               "تعذّر الاتصال بها")
                    bar.progress(0)
                elif stage == 'done':
                    bar.progress(1.0)

            uploads = [(f.name, f.getvalue()) for f in (sm_files or [])]
            inputs = [ln.strip() for ln in (sm_text or '').splitlines() if ln.strip()]
            result = run_full_scan(target, max_pages, workers, do_pagination,
                                   do_sitemap_check, progress,
                                   sitemap_uploads=uploads or None,
                                   sitemap_inputs=inputs or None,
                                   use_cache=use_cache)
            status.update(label="اكتمل الفحص", state="complete", expanded=False)

        df = result['df']
        images_df = result['images_df']
        summary = result['summary']
        coverage = result['coverage']
        structured = result['structured']
        selfcheck = result['selfcheck']
        platform = result['platform']
        st.session_state.platform = platform
        st.session_state.brand = result['brand']
        st.session_state.dup_groups = result['dup_groups']

        st.session_state.audit_df = df
        st.session_state.images_df = images_df
        st.session_state.summary = summary
        st.session_state.coverage = coverage
        st.session_state.selfcheck = selfcheck
        st.session_state.structured = structured
        st.session_state.sitemap_report = (result.get('crawl_meta') or {}).get('sitemap_report')

        conn = sqlite3.connect(DB_FILE)
        conn.cursor().execute(
            '''INSERT INTO audits (domain, scan_date, score, total_pages, products_count,
               categories_count, info_pages_count, blog_pages_count, data_json,
               images_json, coverage_json, platform) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
            (target, datetime.now().strftime("%Y-%m-%d %H:%M"), summary['score'],
             summary['total_pages'], summary['products'], summary['categories'],
             summary['info_pages'], summary['blog_pages'], df.to_json(orient='records'),
             images_df.to_json(orient='records') if not images_df.empty else '',
             json.dumps(coverage, ensure_ascii=False) if coverage else '', platform))
        conn.commit()
        conn.close()

    if st.session_state.audit_df is not None:
        df = st.session_state.audit_df
        images_df = st.session_state.images_df
        summary = st.session_state.summary
        coverage = st.session_state.coverage
        platform = st.session_state.platform

        n_fail = int(summary.get('unreachable_pages', 0) or 0)
        if n_fail:
            cc1, cc2 = st.columns([3, 1])
            with cc1:
                st.warning(f"تعذّر فحص {n_fail} صفحة، فالنتائج ناقصة. «أكمل الفحص» يعيد فحص "
                           "هذه الصفحات فقط، ويأخذ الباقي من الفحص الحالي دون إزعاج المتجر.")
            with cc2:
                st.write("")
                if st.button(f"🔁 أكمل الفحص ({n_fail} صفحة)", use_container_width=True,
                             key="resume_btn"):
                    st.session_state.resume_now = True
                    st.rerun()
            cached_n = eng.cache_count(st.session_state.current_url)
            if cached_n:
                if st.button("🗑️ مسح النتائج المحفوظة لهذا المتجر وبدء فحص جديد كلياً",
                             key="clear_cache_btn"):
                    eng.cache_clear(st.session_state.current_url)
                    st.success("مُسحت النتائج المحفوظة. الفحص القادم سيبدأ من الصفر.")

        sc = summary['score']
        sc_color = COLOR['bad'] if sc < 60 else COLOR['warn'] if sc < 80 else COLOR['ok']
        plat_txt = PLATFORM_LABEL.get(platform, '—')
        st.markdown(
            f'<div class="hero">'
            f'<div><div class="score" style="color:{sc_color}">{sc}%</div>'
            f'<div class="scorelbl">درجة التوافق مع محركات البحث</div></div>'
            f'<div><div class="store">{urlparse(st.session_state.current_url).netloc}</div>'
            f'<div class="plat">المنصة: {plat_txt} · '
            f'{datetime.now().strftime("%Y-%m-%d")}</div></div></div>',
            unsafe_allow_html=True)

        if platform not in SUPPORTED_PLATFORMS:
            st.warning("لم يتم التعرف على المنصة كسلة أو زد أو شوبيفاي. الأداة معايرة "
                       "على هذه المنصات الثلاث — راجع تبويب التحقق اليدوي قبل إرسال "
                       "التقرير لأي عميل.")

        cards = [
            (summary["total_pages"], "الصفحات المعروضة", COLOR['accent']),
            (summary["products"], "المنتجات", COLOR['accent']),
            (summary["categories"], "الأقسام", COLOR['accent']),
            (summary["blog_pages"], "المدونة",
             COLOR['warn'] if summary["blog_pages"] == 0 else COLOR['accent']),
            (summary["info_pages"], "التعريفية", COLOR['accent']),
            (summary["missing_alts"], "صور بلا Alt",
             COLOR['bad'] if summary["missing_alts"] else COLOR['ok']),
            (summary.get("broken_pages", 0), "روابط معطلة",
             COLOR['bad'] if summary.get("broken_pages") else COLOR['ok']),
        ]
        for col, (v, l, c) in zip(st.columns(7), cards):
            with col:
                st.markdown(metric_card(v, l, c), unsafe_allow_html=True)

        st.write("")
        view_df = localize_df(df, 'ar')
        uimgs = unique_images(images_df)
        view_imgs = localize_df(uimgs, 'ar')
        selfcheck = st.session_state.get('selfcheck')
        vmap = {'ready': ('v-ready', '✅ جاهز للإرسال',
                          'اجتازت النتائج كل فحوص الموثوقية. يمكنك إرسال التقرير.'),
                'review': ('v-review', '⚠️ يحتاج مراجعة قبل الإرسال',
                           'بعض المؤشرات تحتاج نظرة سريعة منك قبل إرسال التقرير لعميل.'),
                'blocked': ('v-blocked', '⛔ لا ترسل هذا التقرير',
                            'رصدت الأداة خللاً يجعل أرقامها غير موثوقة لهذا المتجر.')}
        if selfcheck:
            cls, head, sub = vmap[selfcheck['verdict']]
            extra = (f" · {selfcheck['fails']} فحص فاشل"
                     if selfcheck['fails'] else "")
            extra += (f" · {selfcheck['warns']} تنبيه" if selfcheck['warns'] else "")
            st.markdown(f'<div class="verdict {cls}"><b>{head}</b>{extra}<br>'
                        f'<span style="font-size:13.5px;font-weight:400">{sub} '
                        f'التفاصيل في تبويب «فحص الثقة».</span></div>',
                        unsafe_allow_html=True)

        tabs = st.tabs(["📊 نظرة عامة", "🛡️ فحص الثقة", "🧾 البيانات المعلنة",
                        "📄 الصفحات", "🖼️ الصور", "🗺️ خريطة الموقع",
                        "🔬 التحقق اليدوي", "📥 التصدير"])

        # ---------------- نظرة عامة ----------------
        with tabs[0]:
            L = STATUS_LABEL['ar']
            ok = df[df['متاحة'] == True]  # noqa: E712
            g1, g2 = st.columns(2)

            with g1:
                items = [(PAGE_TYPE_LABEL['ar'][t], int((df['نوع الصفحة'] == t).sum()))
                         for t in PAGE_TYPE_ORDER if (df['نوع الصفحة'] == t).any()]
                st.markdown(bar_chart("توزيع أنواع الصفحات", items),
                            unsafe_allow_html=True)

                tcounts = ok['حالة العنوان'].value_counts()
                items = [(L[k], int(tcounts.get(k, 0)))
                         for k in ['optimal', 'acceptable', 'very_short', 'long', 'missing']
                         if tcounts.get(k, 0)]
                st.markdown(bar_chart("حالة عناوين الميتا", items, {
                    L['optimal']: COLOR['ok'], L['acceptable']: COLOR['warn'],
                    L['very_short']: COLOR['bad'], L['long']: COLOR['bad'],
                    L['missing']: COLOR['bad']}), unsafe_allow_html=True)

            with g2:
                if images_df is not None and not images_df.empty:
                    acounts = uimgs['حالة النص البديل'].value_counts()
                    items = [(L[k], int(acounts.get(k, 0)))
                             for k in ['alt_ok', 'alt_duplicate', 'alt_long',
                                       'alt_stuffed', 'alt_generic', 'alt_missing']
                             if acounts.get(k, 0)]
                    st.markdown(bar_chart("جودة النصوص البديلة للصور", items, {
                        L['alt_ok']: COLOR['ok'], L['alt_duplicate']: COLOR['warn'],
                        L['alt_long']: COLOR['warn'], L['alt_stuffed']: COLOR['bad'],
                        L['alt_generic']: COLOR['bad'], L['alt_missing']: COLOR['bad']}),
                        unsafe_allow_html=True)

                dcounts = ok['حالة الوصف'].value_counts()
                items = [(L[k], int(dcounts.get(k, 0)))
                         for k in ['optimal', 'acceptable', 'very_short', 'long', 'missing']
                         if dcounts.get(k, 0)]
                st.markdown(bar_chart("حالة أوصاف الميتا", items, {
                    L['optimal']: COLOR['ok'], L['acceptable']: COLOR['warn'],
                    L['very_short']: COLOR['bad'], L['long']: COLOR['bad'],
                    L['missing']: COLOR['bad']}), unsafe_allow_html=True)

            QL = QUALITY_LABEL['ar']
            qc = ok['جودة العنوان'].value_counts()
            items = [(QL[k], int(qc.get(k, 0))) for k in
                     ['q_ok', 'q_duplicate', 'q_brand_only', 'q_one_word',
                      'q_placeholder', 'q_symbols'] if qc.get(k, 0)]
            if items and len(items) > 1:
                st.markdown(bar_chart("الجودة البنيوية لعناوين الميتا", items, {
                    QL['q_ok']: COLOR['ok'], QL['q_duplicate']: COLOR['warn'],
                    QL['q_brand_only']: COLOR['bad'], QL['q_one_word']: COLOR['warn'],
                    QL['q_placeholder']: COLOR['bad'], QL['q_symbols']: COLOR['bad']}),
                    unsafe_allow_html=True)

            UL = URL_LABEL['ar']
            if 'جودة الرابط' in ok.columns:
                uc = ok['جودة الرابط'].value_counts()
                items = [(UL[k], int(uc.get(k, 0))) for k in
                         ['u_ok', 'u_underscore', 'u_uppercase', 'u_repeat', 'u_wordy',
                          'u_long', 'u_generic', 'u_malformed', 'u_wrongname',
                          'u_clone']
                         if uc.get(k, 0)]
                if len(items) > 1:
                    st.markdown(bar_chart("جودة روابط الصفحات", items, {
                        UL['u_ok']: COLOR['ok'], UL['u_underscore']: COLOR['warn'],
                        UL['u_uppercase']: COLOR['warn'], UL['u_repeat']: COLOR['warn'],
                        UL['u_wordy']: COLOR['warn'], UL['u_long']: COLOR['warn'],
                        UL['u_generic']: COLOR['bad'], UL['u_malformed']: COLOR['bad'],
                        UL['u_wrongname']: COLOR['bad'],
                        UL['u_clone']: COLOR['bad']}),
                        unsafe_allow_html=True)
            if summary.get('img_formats'):
                items = [(k.upper(), v) for k, v in
                         sorted(summary['img_formats'].items(), key=lambda x: -x[1])[:5]]
                st.markdown(bar_chart("صيغ صور المتجر", items, {
                    'WEBP': COLOR['ok'], 'AVIF': COLOR['ok'],
                    'JPG': COLOR['warn'], 'PNG': COLOR['warn']}),
                    unsafe_allow_html=True)

            st.markdown("#### أبرز النتائج")
            out = []
            if summary['missing_alts']:
                out.append((f"<b>{summary['missing_alts']}</b> صورة بلا نص بديل إطلاقاً "
                            f"من أصل {summary['total_images']} — أكبر فجوة قابلة "
                            "للإصلاح في المتجر.", 'bad'))
            if summary['weak_alts']:
                out.append((f"<b>{summary['weak_alts']}</b> صورة نصها البديل موجود لكنه "
                            "غير وصفي أو مكرر — يمر كسليم في الأدوات السطحية.", 'warn'))
            if summary.get('url_clone'):
                out.append((f"<b>{summary['url_clone']}</b> منتج مستنسخ — نسخ مكررة "
                            "من منتج واحد تتنافس مع أصلها.", 'bad'))
            if summary.get('dup_content'):
                out.append((f"<b>{summary['dup_content']}</b> صفحة بنفس العنوان والوصف "
                            "حرفياً — محتوى مكرر يختار جوجل منه واحدة فقط.", 'bad'))
            if summary.get('url_wrongname'):
                out.append((f"<b>{summary['url_wrongname']}</b> رابط يحمل اسم منتج مختلف "
                            "عن المعروض في الصفحة — الزبون ينقر على منتج ويصل لآخر.",
                            'bad'))
            if summary.get('url_style'):
                out.append((f"<b>{summary['url_style']}</b> رابط بصياغة غير مثالية — "
                            "شرطة سفلية أو حروف كبيرة أو طول مفرط.", 'warn'))
            if summary.get('img_legacy') and summary.get('img_modern_pct', 100) < 50:
                out.append((f"<b>{summary['img_legacy']}</b> صورة بصيغة قديمة ثقيلة — "
                            f"{summary.get('img_modern_pct', 0)}% فقط بصيغ حديثة. "
                            "التحويل يخفض حجم الصفحة بنحو الثلث.", 'warn'))
            if summary.get('title_symbols'):
                out.append((f"<b>{summary['title_symbols']}</b> عنوان ميتا مجرد رموز أو "
                            "قيمة قالب افتراضية — الصفحة بلا عنوان فعلي في نتائج البحث.",
                            'bad'))
            if summary.get('title_brand_only'):
                out.append((f"<b>{summary['title_brand_only']}</b> عنوان لا يحمل سوى اسم "
                            "المتجر بلا وصف للمنتج.", 'bad'))
            if summary.get('title_dup'):
                out.append((f"<b>{summary['title_dup']}</b> صفحة تتشارك نفس عنوان "
                            "الميتا.", 'warn'))
            if summary.get('desc_same'):
                out.append((f"<b>{summary['desc_same']}</b> وصف ميتا نسخة حرفية من "
                            "العنوان.", 'warn'))
            if summary['critical_titles']:
                out.append((f"<b>{summary['critical_titles']}</b> عنوان مفقود أو قصير جداً "
                            "أو يُقتطع في نتائج البحث.", 'bad'))
            if summary['critical_descs']:
                out.append((f"<b>{summary['critical_descs']}</b> وصف ميتا خارج الحدود "
                            "المفيدة.", 'warn'))
            if summary['canon_missing']:
                out.append((f"<b>{summary['canon_missing']}</b> صفحة بلا وسم كانونيكال — "
                            "خطر تكرار المحتوى.", 'warn'))
            if summary.get('hidden_count'):
                bt = summary.get('orphan_by_type', {})
                brk = "، ".join(f"{PAGE_TYPE_LABEL['ar'].get(k, k)}: {v}"
                                for k, v in bt.items())
                out.append((f"<b>{summary['hidden_count']}</b> صفحة يتيمة في خريطة الموقع "
                            f"({brk}) — منشورة ولا يصل إليها أحد.", 'warn'))
            if summary.get('redirect_count'):
                out.append((f"<b>{summary['redirect_count']}</b> رابط في الخريطة يعيد "
                            "التوجيه لصفحة أخرى — هدر لميزانية الزحف.", 'warn'))
            if summary['broken_pages']:
                out.append((f"<b>{summary['broken_pages']}</b> رابط معطل يصل إليه الزائر.",
                            'bad'))
            if summary['thin_pages']:
                out.append((f"<b>{summary['thin_pages']}</b> صفحة بمحتوى نصي ضعيف "
                            "(أقل من 50 كلمة).", 'warn'))
            if not out:
                out.append(("لم يرصد الفحص فجوات جوهرية في الصفحات المعروضة.", 'ok'))
            for text, lvl in out:
                st.markdown(finding(text, lvl), unsafe_allow_html=True)

        # ---------------- فحص الثقة ----------------
        with tabs[1]:
            st.markdown("#### فحوص موثوقية النتائج")
            st.caption("هذه الفحوص لا تقيس جودة سيو المتجر، بل تقيس مدى ثقة الأداة "
                       "في أرقامها هي. أي فحص فاشل يعني أن الزاحف لم يرَ المتجر كما "
                       "يراه الزائر.")
            if not selfcheck:
                st.info("لا توجد نتائج فحص ذاتي لهذه الجلسة.")
            else:
                dots = {CHECK_PASS: COLOR['ok'], CHECK_WARN: COLOR['warn'],
                        CHECK_FAIL: COLOR['bad']}
                order = {CHECK_FAIL: 0, CHECK_WARN: 1, CHECK_PASS: 2}
                failed_sm = (st.session_state.get('sitemap_report') or {}).get('failed') or []
                if failed_sm:
                    st.markdown("##### ملفات خريطة تعذّرت قراءتها")
                    st.dataframe(pd.DataFrame(failed_sm), use_container_width=True,
                                 hide_index=True)
                    st.caption("افتح هذه الملفات في متصفحك واحفظها، ثم ارفعها من "
                               "«خيارات خريطة الموقع» وأعد الفحص.")
                for c in sorted(selfcheck['checks'], key=lambda x: order[x['level']]):
                    act = (f'<div class="a">الإجراء المقترح: {c["action"]}</div>'
                           if c['action'] else '')
                    st.markdown(
                        f'<div class="chk"><div class="dot" '
                        f'style="background:{dots[c["level"]]}"></div>'
                        f'<div><div class="t">{c["title"]}</div>'
                        f'<div class="m">{c["msg"]}</div>{act}</div></div>',
                        unsafe_allow_html=True)

        # ---------------- البيانات المعلنة ----------------
        with tabs[2]:
            stx = st.session_state.get('structured')
            st.markdown("#### ما يعلنه المتجر مقابل ما رصده الفحص")
            st.caption("تُقارَن كل صفحة قسم بعدّاد المنتجات الظاهر فيها. العدّاد يعدّ "
                       "المعروض للزائر فقط — لا المخفي ولا المحذوف — فأي نقص يعني "
                       "منتجات معروضة لم يصل إليها الفحص.")
            if not stx:
                st.info("لا توجد بيانات معلنة في هذا الفحص.")
            else:
                checked = stx.get('categories_checked', 0)
                short = stx.get('categories_short') or []
                miss = stx.get('missing_products', 0)
                c1, c2, c3 = st.columns(3)
                c1.metric("أقسام قورنت بعدّادها", checked if checked else "—")
                c2.metric("أقسام ينقصها منتجات", len(short))
                c3.metric("منتجات معروضة لم تُرصد", miss)
                st.write("")

                if not checked:
                    st.markdown(finding(
                        "لم يعرض المتجر عدّاد منتجات في أقسامه، فتعذّرت مقارنة "
                        "التغطية. تبقى مقارنة الصور والأسماء أدناه صالحة.", 'warn'),
                        unsafe_allow_html=True)
                elif short:
                    st.markdown(finding(
                        f"<b>{len(short)}</b> قسماً يعلن منتجات أكثر مما رصده الفحص "
                        f"(ناقص <b>{miss}</b> منتجاً). الأرجح أن القسم يحمّل بقية "
                        "منتجاته بالتمرير أو بزر «عرض المزيد». لا تعتمد أرقام "
                        "المنتجات في هذا التقرير.", 'bad'), unsafe_allow_html=True)
                else:
                    st.markdown(finding(
                        f"جميع الأقسام الـ{checked} مطابقة تماماً لعدّاداتها — "
                        "لم يفت الفحص أي منتج معروض.", 'ok'), unsafe_allow_html=True)

                rows = stx.get('category_rows') or []
                if rows:
                    view = pd.DataFrame(rows)
                    st.dataframe(view, use_container_width=True,
                                 column_config={"القسم": st.column_config.LinkColumn(
                                     "القسم", width="large")})

                gaps = stx.get('image_gap') or []
                if gaps:
                    st.markdown(finding(
                        f"<b>{len(gaps)}</b> صفحة منتج تعلن صوراً أكثر مما رصده الفحص — "
                        "معرض الصور يُحمَّل بـ JavaScript جزئياً.", 'bad'),
                        unsafe_allow_html=True)
                    st.dataframe(pd.DataFrame(gaps), use_container_width=True)

                nm = stx.get('name_mismatch') or []
                if nm:
                    st.markdown(finding(
                        f"<b>{len(nm)}</b> منتجاً اسمه المعلن لمحركات البحث يختلف عن "
                        "الاسم المعروض في الصفحة.", 'warn'), unsafe_allow_html=True)
                    st.dataframe(pd.DataFrame(nm), use_container_width=True)

                st.caption(f"صفحات منتجات تحمل بيانات مهيكلة: "
                           f"{stx.get('jsonld_pages', 0)} · بدونها: "
                           f"{stx.get('no_jsonld', 0)} · إجمالي منتجات الفحص: "
                           f"{stx.get('found_products', 0)}")

        # ---------------- الصفحات ----------------
        with tabs[3]:
            present = [PAGE_TYPE_LABEL['ar'][t] for t in PAGE_TYPE_ORDER
                       if (df['نوع الصفحة'] == t).any()]
            f1, f2 = st.columns([2, 3])
            with f1:
                sel = st.selectbox("نوع الصفحة", ["الكل"] + present)
            with f2:
                only_issues = st.checkbox("عرض الصفحات التي بها مشاكل فقط", value=False)

            d = view_df if sel == "الكل" else view_df[view_df['نوع الصفحة'] == sel]
            if only_issues:
                QL = QUALITY_LABEL['ar']
                d = d[(d['حالة العنوان'] != STATUS_LABEL['ar']['optimal']) |
                      (d['حالة الوصف'] != STATUS_LABEL['ar']['optimal']) |
                      (~d['جودة العنوان'].isin([QL['q_ok'], QL['q_na']])) |
                      (~d['جودة الوصف'].isin([QL['q_ok'], QL['q_na']])) |
                      (~d['جودة الرابط'].isin([URL_LABEL['ar']['u_ok'],
                                               URL_LABEL['ar']['u_na']])) |
                      (d['صور بدون Alt'] > 0) | (d['متاحة'] == False)]  # noqa: E712
            d = d.copy().reset_index(drop=True)
            d.index = d.index + 1
            st.dataframe(d, use_container_width=True, height=460,
                         column_config={"الرابط": st.column_config.LinkColumn(
                             "الرابط", width="large"),
                             "درجة السيو": st.column_config.ProgressColumn(
                                 "درجة السيو", min_value=0, max_value=100, format="%d")})
            dgroups = st.session_state.get('dup_groups') or []
            if dgroups:
                with st.expander(f"⚠️ {len(dgroups)} مجموعة محتوى مكرر "
                                 f"({sum(g['عدد الصفحات'] for g in dgroups)} صفحة)"):
                    for g in dgroups:
                        st.markdown(f"**{g['عدد الصفحات']} صفحات** بنفس العنوان: "
                                    f"{str(g['العنوان'])[:70]}")
                        for u in g['الروابط']:
                            st.caption(f"• {u}")
            langs = df[df['متاحة'] == True]['لغة الصفحة'].value_counts()  # noqa: E712
            st.caption(
                f"معايير الطول — العنوان مثالي {TITLE_MIN_OPTIMAL}-{TITLE_MAX} حرفاً "
                f"(مقبول من {TITLE_MIN_OK})، الوصف مثالي {DESC_MIN_OPTIMAL}-{DESC_MAX} "
                f"حرفاً (مقبول من {DESC_MIN_OK}). يُحسب الطول بالحروف شاملاً المسافات "
                "وعلامات الترقيم. · لغات الصفحات: " +
                "، ".join(f"{k}: {v}" for k, v in langs.items()))

        # ---------------- الصور ----------------
        with tabs[4]:
            if view_imgs is not None and not view_imgs.empty:
                L = STATUS_LABEL['ar']
                fc1, fc2 = st.columns(2)
                with fc1:
                    f = st.selectbox("تصفية", ["الكل", "بلا نص بديل", "نص بديل ضعيف",
                                               "نص بديل سليم"])
                with fc2:
                    fmts = ["الكل"] + sorted(view_imgs['صيغة الصورة'].dropna().unique().tolist()) \
                        if 'صيغة الصورة' in view_imgs.columns else ["الكل"]
                    fsel = st.selectbox("صيغة الصورة", fmts)
                v = view_imgs
                if f == "بلا نص بديل":
                    v = view_imgs[view_imgs['حالة النص البديل'] == L['alt_missing']]
                elif f == "نص بديل ضعيف":
                    v = view_imgs[view_imgs['حالة النص البديل'].isin(
                        [L[k] for k in ALT_WEAK_STATES])]
                elif f == "نص بديل سليم":
                    v = view_imgs[view_imgs['حالة النص البديل'] == L['alt_ok']]
                if fsel != "الكل" and 'صيغة الصورة' in v.columns:
                    v = v[v['صيغة الصورة'] == fsel]
                v = v.copy().reset_index(drop=True)
                v.index = v.index + 1
                st.dataframe(v, use_container_width=True, height=460,
                             column_config={
                                 "رابط الصورة": st.column_config.ImageColumn(
                                     "معاينة", width="small"),
                                 "رابط الصفحة": st.column_config.LinkColumn(
                                     "رابط الصفحة", width="medium")})
                st.caption(f"الجدول يعرض {len(view_imgs)} صورة فريدة. عمود «عدد الصفحات» "
                           "يبيّن كم صفحة تظهر فيها الصورة — ظهور الصورة نفسها في "
                           "الرئيسية والقسم وصفحة المنتج أمر طبيعي وليس تكراراً. · "
                           "معايير التقييم — النص البديل يُقيَّم بجودته لا بطوله: "
                           "الغياب، أو النص غير الوصفي (اسم ملف أو كلمة عامة)، أو حشو "
                           f"الكلمات، أو تكراره على {ALT_DUP_THRESHOLD} صور فأكثر، أو "
                           f"تجاوزه {ALT_MAX} حرفاً (حد قارئات الشاشة).")
            else:
                st.info("لا توجد صور محتوى مرصودة.")

        # ---------------- خريطة الموقع ----------------
        with tabs[5]:
            if not coverage:
                st.info("لم تُفعّل مقارنة خريطة الموقع في هذا الفحص.")
            else:
                st.caption("كل رابط في الخريطة فُتح فعلياً: المحذوف يردّ بخطأ، "
                           "والمعروض يُفحص. وروابط الصفحات جُمعت أثناء الفحص "
                           "لمعرفة ما يصل إليه الزائر بنقرة.")
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("روابط في الخريطة", coverage['sitemap_total'])
                m2.metric("تعمل ويصل إليها الزائر", coverage['sitemap_live'])
                m3.metric("محذوفة ما زالت مدرجة", coverage['sitemap_dead'])
                m4.metric("نسبة إدراج المنتجات", f"{coverage['indexed_pct']}%")
                st.write("")

                if coverage['dead_pages']:
                    st.markdown(finding(
                        f"<b>{len(coverage['dead_pages'])}</b> رابط محذوف ما زال معلناً "
                        "في خريطة الموقع. محركات البحث ترسل زحفها إلى صفحات غير "
                        "موجودة، فتهدر ميزانية الزحف.", 'bad'), unsafe_allow_html=True)
                    st.dataframe(localize_df(pd.DataFrame(coverage['dead_pages']), 'ar'),
                                 use_container_width=True)

                if coverage['unlisted_pages']:
                    st.markdown(finding(
                        f"<b>{len(coverage['unlisted_pages'])}</b> صفحة معروضة في المتجر "
                        "وغير مدرجة في خريطة الموقع — قد لا تعلم بها محركات البحث.",
                        'bad'), unsafe_allow_html=True)
                    st.dataframe(localize_df(
                        pd.DataFrame(coverage['unlisted_pages']), 'ar'),
                        use_container_width=True)

                if coverage.get('scroll_only_products'):
                    st.markdown(finding(
                        f"<b>{len(coverage['scroll_only_products'])}</b> منتجاً لا "
                        "تظهر روابطه في صفحات الأقسام، ويصل إليه الزائر بالتمرير أو "
                        "بزر «عرض المزيد». المنتجات نفسها مفحوصة بالكامل، لكن ضعف "
                        "الترابط الداخلي يقلل قوتها في نتائج البحث.", 'warn'),
                        unsafe_allow_html=True)
                    with st.expander(
                            f"عرض الـ{len(coverage['scroll_only_products'])} منتجاً"):
                        st.dataframe(localize_df(
                            pd.DataFrame(coverage['scroll_only_products']), 'ar'),
                            use_container_width=True)

                if coverage['orphan_pages']:
                    bt = coverage.get('orphan_by_type', {})
                    brk = "، ".join(f"{PAGE_TYPE_LABEL['ar'].get(k, k)}: {v}"
                                    for k, v in bt.items())
                    st.markdown(finding(
                        f"<b>{len(coverage['orphan_pages'])}</b> صفحة يتيمة ({brk}): "
                        "تعمل ومدرجة في الخريطة لكن لا يصل إليها الزائر بأي رابط "
                        "داخلي، فلا تستفيد من قوة المتجر.", 'warn'),
                        unsafe_allow_html=True)
                    st.dataframe(localize_df(
                        pd.DataFrame(coverage['orphan_pages']), 'ar'),
                        use_container_width=True)

                if not (coverage['dead_pages'] or coverage['unlisted_pages']
                        or coverage['orphan_pages']
                        or coverage.get('scroll_only_products')):
                    st.markdown(finding(
                        "خريطة الموقع مطابقة لما يراه الزائر: لا روابط محذوفة ولا "
                        "صفحات يتيمة ولا صفحات خارج الخريطة.", 'ok'),
                        unsafe_allow_html=True)

        # ---------------- التحقق اليدوي ----------------
        with tabs[6]:
            st.markdown("#### عيّنة للمطابقة اليدوية")
            st.caption("افتح كل رابط وقارن العنوان والوصف بما هو مسجّل هنا. "
                       "تطابق العيّنة كاملة يعني أن محرك القراءة يعمل بشكل صحيح.")
            pool = df[(df['متاحة'] == True) & (df['نوع الصفحة'] == T_PRODUCT)]  # noqa: E712
            if pool.empty:
                pool = df[df['متاحة'] == True]  # noqa: E712
            if pool.empty:
                st.info("لا توجد صفحات متاحة للتحقق.")
            else:
                if st.button("🎲 عيّنة جديدة"):
                    st.session_state['sample_seed'] = int(time.time())
                seed = st.session_state.get('sample_seed', 42)
                sample = pool.sample(n=min(5, len(pool)), random_state=seed)
                L = STATUS_LABEL['ar']
                for _, r in sample.iterrows():
                    with st.container(border=True):
                        st.markdown(f"**[{r['الرابط']}]({r['الرابط']})**")
                        a, b, c = st.columns(3)
                        a.metric("طول العنوان", r['طول العنوان'], L[r['حالة العنوان']])
                        b.metric("طول الوصف", r['طول الوصف'], L[r['حالة الوصف']])
                        c.metric("درجة الصفحة", f"{r['درجة السيو']}%")
                        QL = QUALITY_LABEL['ar']
                        tq = QL.get(r.get('جودة العنوان', 'q_na'), '—')
                        dq = QL.get(r.get('جودة الوصف', 'q_na'), '—')
                        st.write(f"**العنوان** ({tq}): {r['عنوان الميتا'] or '— مفقود —'}")
                        st.write(f"**الوصف** ({dq}): {r['وصف الميتا'] or '— مفقود —'}")
                        st.caption(f"صور: {r['إجمالي الصور']} · بلا Alt: "
                                   f"{r['صور بدون Alt']} · Alt ضعيف: {r['صور Alt ضعيف']} · "
                                   f"كلمات: {r['عدد الكلمات']} · لغة: {r['لغة الصفحة']} · "
                                   f"كانونيكال: {L[r['حالة الكانونيكال']]}")

        # ---------------- التصدير ----------------
        with tabs[7]:
            st.markdown("#### تصدير التقرير والبيانات")
            lang_choice = st.radio("لغة الملفات", ["العربية", "English"], horizontal=True)
            lang = 'ar' if lang_choice == "العربية" else 'en'
            exp_summary = dict(summary)
            exp_summary['platform_label'] = (PLATFORM_LABEL if lang == 'ar'
                                             else PLATFORM_LABEL_EN).get(platform, '—')
            exp_summary['broken_links'] = build_broken_links(df, platform).to_dict('records')
            exp_summary['platform'] = platform
            netloc = urlparse(st.session_state.current_url).netloc or "store"
            try:
                pdf_bytes = generate_client_pdf(st.session_state.current_url,
                                                summary['score'], exp_summary, lang)
            except Exception as e:
                pdf_bytes = None
                st.error(f"تعذر توليد الـ PDF: {e}")
            zip_bytes = build_zip(df, images_df, coverage, lang,
                                  st.session_state.get('structured'), platform)

            gate_ok = True
            if selfcheck and selfcheck['verdict'] == 'blocked':
                st.markdown(
                    '<div class="verdict v-blocked"><b>⛔ تقرير العميل محجوب</b><br>'
                    '<span style="font-size:13.5px;font-weight:400">رصدت الأداة خللاً '
                    'يجعل أرقامها غير موثوقة لهذا المتجر. راجع تبويب «فحص الثقة» أولاً.'
                    '</span></div>', unsafe_allow_html=True)
                gate_ok = st.checkbox(
                    "راجعت الفحوص الفاشلة وأتحمل مسؤولية إرسال هذا التقرير",
                    value=False)
            elif selfcheck and selfcheck['verdict'] == 'review':
                st.warning("توجد تنبيهات على موثوقية النتائج. راجع تبويب «فحص الثقة» "
                           "قبل إرسال التقرير لعميل.")

            st.markdown("---")
            st.markdown("##### 💰 عرض السعر")
            pc1, pc2, pc3, pc4 = st.columns(4)
            with pc1:
                p_title = st.number_input("سعر عنوان الميتا + الرابط (ريال)",
                                          1.0, 200.0, DEFAULT_PRICES['meta_title'], 1.0)
            with pc2:
                p_desc = st.number_input("سعر وصف الميتا (ريال)",
                                         1.0, 200.0, DEFAULT_PRICES['meta_desc'], 1.0)
            with pc3:
                p_alt = st.number_input("سعر وصف الصورة (ريال)",
                                        0.5, 100.0, DEFAULT_PRICES['image_alt'], 0.5)
            with pc4:
                p_internal = st.number_input("سعر تصحيح رابط داخلي (ريال)",
                                             1.0, 200.0, DEFAULT_PRICES['internal_link_fix'], 1.0)
            p_redirect = DEFAULT_PRICES['redirect_fix']
            if platform == 'zid':
                p_redirect = st.number_input("سعر تحويل 301 لرابط معطل (ريال) — زد",
                                             1.0, 200.0, DEFAULT_PRICES['redirect_fix'], 1.0)
            dc1, dc2 = st.columns([1, 3])
            with dc1:
                use_disc = st.checkbox("إضافة خصم", value=False)
            with dc2:
                disc_pct = st.slider("نسبة الخصم %", 0, 50, 10,
                                     disabled=not use_disc)
            quote = build_quote(summary,
                                {'meta_title': p_title, 'meta_desc': p_desc,
                                 'image_alt': p_alt, 'redirect_fix': p_redirect,
                                 'internal_link_fix': p_internal},
                                discount_rate=(disc_pct / 100 if use_disc else 0.0))
            qc = st.columns(5)
            qc[0].metric("عناوين وروابط",
                         f"{summary.get('fix_titles_urls', summary.get('bad_titles', 0))}")
            qc[1].metric("أوصاف ميتا",
                         f"{summary.get('fix_descs', summary.get('bad_descs', 0))}")
            qc[2].metric("صور تحتاج وصفاً",
                         f"{summary.get('missing_alts', 0) + summary.get('weak_alts', 0)}")
            qc[3].metric("روابط تحتاج معالجة",
                         f"{summary.get('redirect_qty', 0)} تحويل · "
                         f"{summary.get('internal_fix_qty', 0)} تصحيح")
            qc[4].metric("الإجمالي المستحق", f"{quote['total']:,.0f}")
            if quote['discount']:
                st.caption(f"شمل خصماً {int(quote['discount_rate'] * 100)}% "
                           f"({quote['discount']:,.0f}) · الأسعار غير شاملة "
                           "ضريبة القيمة المضافة")
            else:
                st.caption("الأسعار غير شاملة ضريبة القيمة المضافة")
            try:
                inv_bytes = generate_invoice_pdf(st.session_state.current_url,
                                                 quote, lang)
            except Exception as e:
                inv_bytes = None
                st.error(f"تعذّر توليد الفاتورة: {e}")
            if inv_bytes:
                st.download_button(
                    "🧾 تحميل عرض السعر (PDF)" if lang == 'ar'
                    else "🧾 Download quotation (PDF)",
                    inv_bytes, f"Quote_{netloc}_{lang}.pdf", "application/pdf",
                    use_container_width=True)
            st.markdown("---")

            d1, d2 = st.columns(2)
            with d1:
                if pdf_bytes and gate_ok:
                    st.download_button(
                        "📄 تقرير العميل (PDF)" if lang == 'ar' else "📄 Client report (PDF)",
                        pdf_bytes, f"SEO_Audit_{netloc}_{lang}.pdf", "application/pdf",
                        use_container_width=True)
                elif pdf_bytes:
                    st.button("📄 تقرير العميل (PDF)", disabled=True,
                              use_container_width=True,
                              help="مُعطّل حتى تقرّ بمراجعة الفحوص الفاشلة.")
            with d2:
                st.download_button(
                    "📦 حزمة البيانات (ZIP)" if lang == 'ar' else "📦 Data package (ZIP)",
                    zip_bytes, f"Data_Package_{netloc}_{lang}.zip", "application/zip",
                    use_container_width=True)

            st.markdown("---")
            st.markdown("##### 🎯 تحميل ما يحتاج عملاً فقط" if lang == 'ar'
                        else "##### 🎯 Download only what needs work")
            filtered = build_filtered_exports(df, images_df, lang, platform)
            buttons = [
                ('titles', "🏷️ عناوين وروابط تحتاج إصلاح", "🏷️ Titles & URLs to fix"),
                ('descs', "📝 أوصاف ميتا تحتاج إصلاح", "📝 Meta descriptions to fix"),
                ('alt_missing', "🖼️ صور بلا وصف Alt", "🖼️ Images missing alt"),
                ('alt_weak', "🖼️ صور وصفها غير وصفي أو مكرر", "🖼️ Weak or duplicate alt"),
                ('broken', "🔗 روابط لا تعمل وبلا تحويل", "🔗 Broken links, no redirect"),
            ]
            if platform == 'zid':
                buttons.append(('zid_redirects', "↪️ ملف تحويلات زد (للاستيراد)",
                                "↪️ Zid redirects (import file)"))
            fcols = st.columns(len(buttons))
            for col, (key, lbl_ar, lbl_en) in zip(fcols, buttons):
                with col:
                    label = lbl_ar if lang == 'ar' else lbl_en
                    if key in filtered:
                        fname, table = filtered[key]
                        data, mime = table_bytes(fname, table)
                        st.download_button(f"{label} ({len(table)})", data,
                                           f"{netloc}_{fname}", mime,
                                           use_container_width=True, key=f"dl_{key}_{lang}")
                    else:
                        st.button(f"{label} (0)", disabled=True, use_container_width=True,
                                  key=f"dl_{key}_{lang}_empty",
                                  help="لا يوجد ما يحتاج عملاً في هذا البند." if lang == 'ar'
                                  else "Nothing to fix here.")
            if filtered:
                total_rows = sum(len(t) for _, t in filtered.values())
                st.download_button(
                    (f"🗂️ تحميل كل ملفات العمل دفعة واحدة (ZIP) — {len(filtered)} ملفات · {total_rows} صف"
                     if lang == 'ar' else
                     f"🗂️ Download all work files (ZIP) — {len(filtered)} files · {total_rows} rows"),
                    build_filtered_zip(filtered),
                    f"{netloc}_{'ملفات_العمل' if lang == 'ar' else 'work_files'}.zip",
                    "application/zip", use_container_width=True, type="primary",
                    key=f"dl_bundle_{lang}")

            if platform == 'zid' and 'zid_redirects' in filtered:
                st.markdown("---")
                st.markdown("##### ✅ التحقق من التحويلات بعد رفع الملف في زد")
                st.caption("ارفع ملف التحويلات من لوحة زد (الإعدادات ← إعادة توجيه الروابط ← "
                           "استيراد)، ثم اضغط الزر: تفتح الأداة كل رابط قديم وتتأكد أنه "
                           "يحوّل بـ 301 إلى الوجهة الصحيحة.")
                if st.button("تحقق من التحويلات الآن", key=f"verify_{lang}"):
                    _, zid_table = filtered['zid_redirects']
                    pairs = list(zip(zid_table['التوجيه من'], zid_table['التوجيه إلى']))
                    with st.spinner(f"جارٍ فحص {len(pairs)} تحويل..."):
                        vres = verify_redirects(st.session_state.current_url, pairs)
                    ok_n = int(vres['ناجح'].sum())
                    (st.success if ok_n == len(vres) else st.warning)(
                        f"{ok_n} من {len(vres)} تحويل يعمل بشكل صحيح.")
                    st.dataframe(vres.drop(columns=['ناجح']), use_container_width=True,
                                 hide_index=True)

else:
    st.markdown("### 📁 سجل المتاجر المفحوصة")
    st.caption("تنبيه: قاعدة البيانات محلية وقد تُفقد عند إعادة نشر التطبيق على "
               "Streamlit Cloud.")
    conn = sqlite3.connect(DB_FILE)
    hist = pd.read_sql_query(
        "SELECT id, domain as 'المتجر', scan_date as 'تاريخ الفحص', score as 'النسبة', "
        "platform as 'المنصة', total_pages as 'الصفحات', products_count as 'المنتجات', "
        "categories_count as 'الأقسام', blog_pages_count as 'المدونة', "
        "info_pages_count as 'التعريفية' FROM audits ORDER BY id DESC", conn)
    conn.close()

    if hist.empty:
        st.info("لا توجد متاجر مفحوصة بعد.")
    else:
        st.dataframe(hist.drop(columns=['id']), use_container_width=True)
        sel_id = st.selectbox(
            "اختر المتجر", hist['id'].tolist(),
            format_func=lambda x: f"{hist[hist['id']==x]['المتجر'].values[0]} "
                                  f"({hist[hist['id']==x]['تاريخ الفحص'].values[0]})")
        if st.button("📥 استرجاع البيانات", type="primary"):
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute("SELECT domain, data_json, images_json, coverage_json, platform "
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
                st.session_state.platform = row[4] or 'unknown'
                st.session_state.summary = compute_summary(rdf, rcov, rimg,
                                                           platform=row[4] or 'unknown')
                st.session_state.summary['platform'] = row[4] or 'unknown'
                st.session_state.summary['platform_label'] = PLATFORM_LABEL.get(
                    row[4] or 'unknown', '—')
                st.success("تم الاسترجاع. انتقل إلى (فحص متجر جديد) لعرض النتائج.")
