"""بناء ملفات التصدير: الحزمة والجداول العملية."""
import io
import re
import zipfile

import pandas as pd

from audit_engine import (
    PAGE_TYPE_ORDER, PAGE_TYPE_LABEL, STATUS_LABEL, QUALITY_LABEL, URL_LABEL,
    COL_EN, ALT_WEAK_STATES, localize_df, unique_images, build_broken_links,
    title_url_fix_mask, desc_fix_mask, build_zid_redirects,
    T_HOME, T_PRODUCT, T_CATEGORY, T_BLOG, T_INFO, T_ARCHIVE, T_UNKNOWN,
    T_BROKEN,
)

#  حزمة الملفات
# ==============================================================
ZIP_NAMES = {
    'ar': {T_PRODUCT: "1_المنتجات.csv", T_CATEGORY: "2_التصنيفات.csv",
           T_BLOG: "3_المدونة.csv", T_INFO: "4_الصفحات_التعريفية.csv",
           T_HOME: "5_الصفحة_الرئيسية.csv", T_ARCHIVE: "6_صفحات_أرشيف.csv",
           T_UNKNOWN: "7_غير_مصنفة.csv", T_BROKEN: "8_روابط_معطلة.csv",
           'images': "9_تدقيق_الصور.csv",
           'notidx': "9_منتجات_غير_مدرجة_في_الخريطة.csv",
           'orphan': "10_صفحات_يتيمة.csv",
           'scroll': "15_منتجات_بالتمرير_فقط.csv",
           'fix': "00_صفحات_تحتاج_إصلاح.csv",
           'noalt': "00_صور_تحتاج_وصفاً.csv",
           'alt_missing': "00_صور_بلا_وصف.csv",
           'alt_weak': "00_صور_وصفها_غير_وصفي_أو_مكرر.csv",
           'broken': "8_روابط_لا_تعمل_بلا_تحويل.csv",
           'zid_redirects': "8_ملف_تحويلات_زد_للاستيراد.xlsx",
           'titles': "00_عناوين_وروابط_تحتاج_إصلاح.csv",
           'descs': "00_أوصاف_ميتا_تحتاج_إصلاح.csv",
           'bundle': "ملفات_العمل.zip",
           'redirect': "11_روابط_محذوفة_في_الخريطة.csv",
           'imggap': "12_صفحات_صورها_ناقصة.csv",
           'namegap': "13_اسم_معلن_مختلف.csv",
           'catgap': "14_مقارنة_عدادات_الأقسام.csv",
           'excel': "فحص_الصفحات_الكامل.csv"},
    'en': {T_PRODUCT: "1_products.csv", T_CATEGORY: "2_categories.csv",
           T_BLOG: "3_blog.csv", T_INFO: "4_info_pages.csv",
           T_HOME: "5_homepage.csv", T_ARCHIVE: "6_archive_pages.csv",
           T_UNKNOWN: "7_unclassified.csv", T_BROKEN: "8_broken_links.csv",
           'images': "9_image_alt_audit.csv",
           'notidx': "9_products_missing_from_sitemap.csv",
           'orphan': "10_orphan_pages.csv",
           'scroll': "15_scroll_only_products.csv",
           'fix': "00_pages_to_fix.csv",
           'noalt': "00_images_needing_alt.csv",
           'alt_missing': "00_images_missing_alt.csv",
           'alt_weak': "00_images_weak_or_duplicate_alt.csv",
           'broken': "8_broken_links_no_redirect.csv",
           'zid_redirects': "8_zid_redirects_import.xlsx",
           'titles': "00_titles_and_urls_to_fix.csv",
           'descs': "00_meta_descriptions_to_fix.csv",
           'bundle': "work_files.zip",
           'redirect': "11_dead_urls_in_sitemap.csv",
           'imggap': "12_pages_with_missing_images.csv",
           'namegap': "13_declared_name_mismatch.csv",
           'catgap': "14_category_counter_comparison.csv",
           'excel': "full_pages_audit.csv"},
}



def build_fix_lists(df, images_df, lang='ar'):
    """ملفان عمليان للتنفيذ: ما يحتاج إصلاحاً فقط، مرتباً حسب الأولوية."""
    L = STATUS_LABEL[lang]
    QL = QUALITY_LABEL[lang]
    UL = URL_LABEL[lang]
    ok = df[df['متاحة'] == True].copy()  # noqa: E712
    rows = []
    for _, r in ok.iterrows():
        need = []
        if r['حالة العنوان'] in ('missing', 'very_short', 'long'):
            need.append(('العنوان' if lang == 'ar' else 'Title') +
                        f" ({L[r['حالة العنوان']]})")
        elif r['حالة العنوان'] == 'acceptable':
            need.append('تحسين العنوان' if lang == 'ar' else 'Improve title')
        if r.get('جودة العنوان') not in ('q_ok', 'q_na', None):
            need.append(QL.get(r.get('جودة العنوان'), ''))
        if r['حالة الوصف'] in ('missing', 'very_short', 'long'):
            need.append(('الوصف' if lang == 'ar' else 'Description') +
                        f" ({L[r['حالة الوصف']]})")
        elif r['حالة الوصف'] == 'acceptable':
            need.append('تحسين الوصف' if lang == 'ar' else 'Improve description')
        if r.get('جودة الرابط') not in ('u_ok', 'u_na', None):
            need.append(UL.get(r.get('جودة الرابط'), ''))
        if int(r.get('صور بدون Alt') or 0):
            need.append((f"{int(r['صور بدون Alt'])} صورة بلا وصف" if lang == 'ar'
                         else f"{int(r['صور بدون Alt'])} images without alt"))
        if int(r.get('صور Alt ضعيف') or 0):
            need.append((f"{int(r['صور Alt ضعيف'])} صورة بوصف ضعيف" if lang == 'ar'
                         else f"{int(r['صور Alt ضعيف'])} images with weak alt"))
        if r['حالة المحتوى'] == 'thin':
            need.append('محتوى نصي ضعيف' if lang == 'ar' else 'Thin content')
        if not need:
            continue
        rows.append({
            'الأولوية': 0, 'نوع الصفحة': r['نوع الصفحة'], 'الرابط': r['الرابط'],
            'درجة السيو': r['درجة السيو'],
            'ما يحتاج إصلاحاً': ' · '.join([x for x in need if x]),
            'عنوان الميتا الحالي': r['عنوان الميتا'], 'طول العنوان': r['طول العنوان'],
            'وصف الميتا الحالي': r['وصف الميتا'], 'طول الوصف': r['طول الوصف'],
        })
    fix = pd.DataFrame(rows)
    if not fix.empty:
        fix['الأولوية'] = fix['درجة السيو'].rank(method='first').astype(int)
        fix = fix.sort_values('درجة السيو').reset_index(drop=True)
        fix['الأولوية'] = range(1, len(fix) + 1)
        fix = localize_df(fix, lang)

    noalt = pd.DataFrame()
    uimg = unique_images(images_df)
    if uimg is not None and not uimg.empty:
        need = ['alt_missing'] + list(ALT_WEAK_STATES)
        sub = uimg[uimg['حالة النص البديل'].isin(need)].copy()
        if not sub.empty:
            order = {'alt_missing': 0, 'alt_generic': 1, 'alt_duplicate': 2,
                     'alt_stuffed': 3, 'alt_long': 4}
            sub['_o'] = sub['حالة النص البديل'].map(order).fillna(9)
            sub = sub.sort_values(['_o', 'رابط الصفحة']).drop(columns=['_o'])
            cols = ['رابط الصفحة', 'نوع الصفحة', 'رابط الصورة',
                    'النص البديل الحالي (Alt)', 'حالة النص البديل', 'عدد الصفحات']
            sub = sub[[c for c in cols if c in sub.columns]]
            sub.insert(0, 'م', range(1, len(sub) + 1))
            noalt = localize_df(sub, lang)
    return fix, noalt


ALT_MISSING_STATES = ('alt_missing',)
# «ضعيف» = غير وصفي أو مكرر، ومعهما الحشو والطول الزائد لأنها تحتاج إعادة كتابة أيضاً
# (ونفس التعريف تُحسب به كمية الصور في عرض السعر)
ALT_WEAK_EXPORT = tuple(ALT_WEAK_STATES)


def build_image_list(images_df, states, lang='ar'):
    """صور فريدة بحالات محددة فقط، مرتبة حسب الصفحة."""
    uimg = unique_images(images_df)
    if uimg is None or uimg.empty:
        return pd.DataFrame()
    sub = uimg[uimg['حالة النص البديل'].isin(states)].copy()
    if sub.empty:
        return pd.DataFrame()
    order = {'alt_missing': 0, 'alt_generic': 1, 'alt_duplicate': 2,
             'alt_stuffed': 3, 'alt_long': 4}
    sub['_o'] = sub['حالة النص البديل'].map(order).fillna(9)
    sub = sub.sort_values(['_o', 'رابط الصفحة']).drop(columns=['_o'])
    cols = ['رابط الصفحة', 'نوع الصفحة', 'رابط الصورة',
            'النص البديل الحالي (Alt)', 'حالة النص البديل', 'عدد الصفحات']
    sub = sub[[c for c in cols if c in sub.columns]]
    sub.insert(0, 'م', range(1, len(sub) + 1))
    return localize_df(sub, lang)


COL_EN.setdefault('اسم المنتج المعروض', 'Displayed Name')
COL_EN.setdefault('الرابط بعد تعديل العنوان', 'URL After Title Update')


def _n(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def _pages_ar(n):
    n = int(n)
    return 'صفحتين' if n == 2 else f'{n} صفحات' if 3 <= n % 100 <= 10 else f'{n} صفحة'


def _title_issues(r, lang, dup_counts=None):
    """سبب دقيق لكل عنوان: الطول بالأرقام، أو التكرار وعدد الصفحات، أو الصياغة الترويجية."""
    QL, UL = QUALITY_LABEL[lang], URL_LABEL[lang]
    ar = lang == 'ar'
    need = []
    st, ln = r.get('حالة العنوان'), _n(r.get('طول العنوان'))
    q0 = r.get('جودة العنوان')
    if q0 in ('q_symbols', 'q_placeholder'):
        return ('العنوان مكوّن من رموز أو قيمة قالب بلا نص' if ar
                else 'Title is only symbols or a template placeholder')
    if st == 'missing':
        need.append('العنوان مفقود' if ar else 'Title missing')
    elif st == 'very_short':
        need.append(f'العنوان قصير جداً ({ln} حرفاً — المثالي 50–60)' if ar
                    else f'Title too short ({ln} chars — ideal 50–60)')
    elif st == 'acceptable':
        need.append(f'العنوان أقصر من المثالي ({ln} حرفاً — المثالي 50–60)' if ar
                    else f'Title below ideal ({ln} chars — ideal 50–60)')
    elif st == 'long':
        need.append(f'العنوان طويل ({ln} حرفاً — الحد 60) فيُقتطع في نتائج البحث' if ar
                    else f'Title too long ({ln} chars — max 60), truncated in results')
    q = r.get('جودة العنوان')
    n_dup = (dup_counts or {}).get(str(r.get('عنوان الميتا') or '').strip(), 0)
    if q == 'q_brand_only':
        need.append('العنوان هو اسم المتجر فقط — يحتاج كلمات تصف تخصص المتجر أو ما يقدمه' if ar
                    else 'Title is only the store name — needs words describing what the store offers')
    if n_dup >= 2:
        # التكرار يُذكر دائماً، حتى لو كان للعنوان سبب ضعف آخر
        need.append(f'العنوان مكرر في {_pages_ar(n_dup)}' if ar else f'Title duplicated on {n_dup} pages')
    elif q == 'q_duplicate':
        need.append(QL['q_duplicate'])
    if q in ('q_duplicate', 'q_brand_only', 'q_promo'):
        pass
    elif q not in ('q_ok', 'q_na', None) and not isinstance(q, float):
        need.append(('العنوان: ' if ar else 'Title: ') + QL.get(q, str(q)))
    return ' · '.join(need)


URL_NOTE = {
    'salla': ('يُحدَّث الرابط ليطابق العنوان الجديد، وسلة تحوّل الرابط القديم تلقائياً',
              'URL updated to match the new title; Salla redirects the old URL automatically'),
    'other': ('يُحدَّث الرابط ليطابق العنوان الجديد، مع تحويل 301 من الرابط القديم حتى لا ينكسر',
              'URL updated to match the new title, with a 301 from the old URL so it does not break'),
}


def url_note(platform, lang='ar'):
    ar_t, en_t = URL_NOTE['salla' if platform == 'salla' else 'other']
    return ar_t if lang == 'ar' else en_t


def _desc_issues(r, lang, dup_counts=None):
    QL = QUALITY_LABEL[lang]
    ar = lang == 'ar'
    need = []
    st, ln = r.get('حالة الوصف'), _n(r.get('طول الوصف'))
    q0 = r.get('جودة الوصف')
    if q0 in ('q_symbols', 'q_placeholder'):
        return ('الوصف مكوّن من رموز أو قيمة قالب بلا نص' if ar
                else 'Description is only symbols or a template placeholder')
    if st == 'missing':
        need.append('الوصف مفقود' if ar else 'Description missing')
    elif st == 'very_short':
        need.append(f'الوصف قصير جداً ({ln} حرفاً — المثالي 120–160)' if ar
                    else f'Description too short ({ln} chars — ideal 120–160)')
    elif st == 'acceptable':
        need.append(f'الوصف أقصر من المثالي ({ln} حرفاً — المثالي 120–160)' if ar
                    else f'Description below ideal ({ln} chars — ideal 120–160)')
    elif st == 'long':
        need.append(f'الوصف طويل ({ln} حرفاً — الحد 160) فيُقتطع في نتائج البحث' if ar
                    else f'Description too long ({ln} chars — max 160), truncated')
    q = r.get('جودة الوصف')
    if q == 'q_duplicate':
        n = (dup_counts or {}).get(str(r.get('وصف الميتا') or '').strip(), 0)
        need.append((f'الوصف مكرر في {_pages_ar(n)}' if n else QL['q_duplicate']) if ar
                    else (f'Description duplicated on {n} pages' if n else QL['q_duplicate']))
    elif q not in ('q_ok', 'q_na', None) and not isinstance(q, float):
        need.append(('الوصف: ' if ar else 'Description: ') + QL.get(q, str(q)))
    return ' · '.join(need)


def _dup_counts(df, col):
    live = df[df['متاحة'] == True] if 'متاحة' in df.columns else df  # noqa: E712
    vals = live[col].map(lambda x: str(x or '').strip())
    return vals[vals != ''].value_counts().to_dict()


def _priority_sorted(rows):
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out = out.sort_values('درجة السيو', na_position='last').reset_index(drop=True)
    out.insert(0, 'الأولوية', range(1, len(out) + 1))
    return out


def build_titles_urls_list(df, lang='ar', platform='unknown'):
    """الصفحات التي يحتاج عنوانها أو رابطها إصلاحاً فقط — ومعها ما يلزم لكتابة العنوان الجديد."""
    if df is None or df.empty:
        return pd.DataFrame()
    rows = []
    counts = _dup_counts(df, 'عنوان الميتا')
    for _, r in df[title_url_fix_mask(df)].iterrows():
        rows.append({
            'نوع الصفحة': r['نوع الصفحة'], 'الرابط': r['الرابط'],
            'درجة السيو': r.get('درجة السيو'),
            'ما يحتاج إصلاحاً': _title_issues(r, lang, counts),
            'عنوان الميتا الحالي': r.get('عنوان الميتا', ''),
            'طول العنوان': r.get('طول العنوان', 0),
            'اسم المنتج المعروض': r.get('اسم المنتج المعروض', ''),
            'الرابط بعد تعديل العنوان': url_note(platform, lang),
        })
    return localize_df(_priority_sorted(rows), lang)


def build_descs_list(df, lang='ar'):
    """الصفحات التي يحتاج وصف الميتا فيها إصلاحاً فقط."""
    if df is None or df.empty:
        return pd.DataFrame()
    rows = []
    counts = _dup_counts(df, 'وصف الميتا')
    for _, r in df[desc_fix_mask(df)].iterrows():
        rows.append({
            'نوع الصفحة': r['نوع الصفحة'], 'الرابط': r['الرابط'],
            'درجة السيو': r.get('درجة السيو'),
            'ما يحتاج إصلاحاً': _desc_issues(r, lang, counts),
            'وصف الميتا الحالي': r.get('وصف الميتا', ''),
            'طول الوصف': r.get('طول الوصف', 0),
            'عنوان الميتا الحالي': r.get('عنوان الميتا', ''),
            'اسم المنتج المعروض': r.get('اسم المنتج المعروض', ''),
        })
    return localize_df(_priority_sorted(rows), lang)


def build_broken_list(df, lang='ar', platform='unknown'):
    """الروابط التي لا تعمل وليس لها إعادة توجيه: مكانها، والوجهة المقترحة، والإجراء."""
    out = build_broken_links(df, platform)
    if out.empty:
        return pd.DataFrame()
    out.insert(0, 'م', range(1, len(out) + 1))
    return localize_df(out, lang)


def build_zid_redirect_table(df, platform='unknown'):
    """ملف التحويلات لزد — يُبنى لمتاجر زد فقط (الأعمدة كما في صفحة مساعدة زد)."""
    if platform != 'zid':
        return pd.DataFrame()
    table, _ = build_zid_redirects(df)
    return table


def build_filtered_exports(df, images_df, lang='ar', platform='unknown'):
    """الملفات التي يمكن تحميلها منفصلة من الواجهة:
    يعيد {المفتاح: (اسم الملف، جدول)} للجداول غير الفارغة فقط."""
    names = ZIP_NAMES[lang]
    tables = {
        'titles': build_titles_urls_list(df, lang, platform),
        'descs': build_descs_list(df, lang),
        'alt_missing': build_image_list(images_df, ALT_MISSING_STATES, lang),
        'alt_weak': build_image_list(images_df, ALT_WEAK_EXPORT, lang),
        'broken': build_broken_list(df, lang, platform),
        'zid_redirects': build_zid_redirect_table(df, platform),
    }
    return {k: (names[k], t) for k, t in tables.items() if t is not None and not t.empty}


def clickable_urls(table):
    """الروابط في الملفات تُكتب بحيث تُفتح بالضغط عليها: المسافة داخل الرابط تصبح %20.
    (سلة تضع مسافات في روابط المقالات، والمسافة تقطع الرابط عند فتحه من الإكسل أو نسخه.)"""
    if table is None or table.empty:
        return table
    out = table.copy()
    for col in out.columns:
        name = str(col)
        if any(k in name for k in ('رابط', 'الوجهة', 'URL', 'Destination')):
            out[col] = out[col].map(lambda v: v.replace(' ', '%20')
                                    if isinstance(v, str) and v.startswith('http') else v)
    return out


def to_csv_bytes(table):
    return clickable_urls(table).to_csv(index=False).encode('utf-8-sig')


def to_xlsx_bytes(table, sheet='Sheet1'):
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as w:
        clickable_urls(table).to_excel(w, index=False, sheet_name=sheet)
    return buf.getvalue()


ROWS_PER_SHEET = 500
XLSX_MIME = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


def write_chunked(writer, table, base_name='Sheet', rows=ROWS_PER_SHEET):
    """يكتب الجدول في أوراق متتالية: كل 500 صف في ورقة («صور بلا وصف 1»، «صور بلا وصف 2» ...).
    الترقيم داخل الجدول مستمر، فلا يضيع صف ولا يتكرر."""
    t = clickable_urls(table) if table is not None else pd.DataFrame()
    base = re.sub(r'[\\/*?:\[\]]', '', str(base_name)).strip()[:27] or 'Sheet'
    if t is None or t.empty or len(t) <= rows:
        (t if t is not None else pd.DataFrame()).to_excel(writer, index=False, sheet_name=base)
        return
    for k, start in enumerate(range(0, len(t), rows), 1):
        t.iloc[start:start + rows].to_excel(writer, index=False, sheet_name=f"{base} {k}"[:31])


def to_xlsx_chunked(table, base_name='Sheet', rows=ROWS_PER_SHEET):
    """ملف Excel: كل 500 صف في ورقة مستقلة."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as w:
        write_chunked(w, table, base_name, rows)
    return buf.getvalue()


def _sheet_base(fname):
    stem = str(fname).rsplit('/', 1)[-1].rsplit('.', 1)[0]
    stem = re.sub(r'^\d+_', '', stem).replace('_', ' ')
    return stem


def csv_chunks(table, fname, rows=ROWS_PER_SHEET):
    """[(اسم الملف، المحتوى)]: ملف واحد حتى 500 صف، وإلا ملفات متتالية «_1-500»، «_501-1000» ...
    الترقيم داخل الجداول مستمر، فلا يضيع صف ولا يتكرر."""
    t = clickable_urls(table) if table is not None else pd.DataFrame()
    stem = str(fname).rsplit('.', 1)[0]
    if t is None or t.empty or len(t) <= rows:
        return [(f"{stem}.csv", (t if t is not None else pd.DataFrame()).to_csv(index=False).encode('utf-8-sig'))]
    return [(f"{stem}_{a + 1}-{min(a + rows, len(t))}.csv",
             t.iloc[a:a + rows].to_csv(index=False).encode('utf-8-sig')) for a in range(0, len(t), rows)]


def zip_write(z, fname, table):
    """يكتب الجدول داخل ملف ZIP: CSV واحد أو أجزاء من 500 صف. ملف تحويلات زد يبقى Excel."""
    if 'zid' in str(fname).lower() or 'زد' in str(fname):
        z.writestr(fname, to_xlsx_bytes(table))
        return
    for name, data in csv_chunks(table, fname):
        z.writestr(name, data)


def table_payload(fname, table):
    """(المحتوى، النوع، اسم الملف للتحميل): CSV إن كان 500 صف أو أقل، وإلا ZIP فيه أجزاء CSV."""
    if 'zid' in str(fname).lower() or 'زد' in str(fname):
        return to_xlsx_bytes(table), XLSX_MIME, fname
    parts = csv_chunks(table, fname)
    if len(parts) == 1:
        return parts[0][1], 'text/csv', parts[0][0]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, data in parts:
            z.writestr(name, data)
    return buf.getvalue(), 'application/zip', str(fname).rsplit('.', 1)[0] + '.zip'


def table_bytes(fname, table):
    """(المحتوى، نوع الملف). ملف تحويلات زد يبقى ورقة واحدة لأن زد تستورده كما هو."""
    if 'zid' in str(fname).lower() or 'زد' in str(fname):
        return to_xlsx_bytes(table), XLSX_MIME
    return to_xlsx_chunked(table, _sheet_base(fname)), XLSX_MIME


def build_filtered_zip(filtered):
    """كل ملفات العمل في ملف مضغوط واحد."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for fname, table in filtered.values():
            zip_write(z, fname, table)
    return buf.getvalue()


def build_zip(df, images_df, coverage=None, lang='ar', structured=None, platform='unknown'):
    names = ZIP_NAMES[lang]
    ldf = localize_df(df, lang)
    limg = localize_df(unique_images(images_df), lang)
    type_col = COL_EN['نوع الصفحة'] if lang == 'en' else 'نوع الصفحة'

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for tkey in PAGE_TYPE_ORDER:
            if tkey == T_BROKEN:
                continue   # تُكتب أدناه كقائمة نظيفة للروابط المعطلة بلا تحويل
            label = PAGE_TYPE_LABEL[lang][tkey]
            sub = ldf[ldf[type_col] == label] if type_col in ldf.columns else pd.DataFrame()
            if not sub.empty:
                fname = names.get(tkey, f"{tkey}.csv")
                zip_write(z, fname, sub)
        if limg is not None and not limg.empty:
            zip_write(z, names['images'], limg)

        if coverage:
            for key, data in [('notidx', coverage.get('unlisted_pages')),
                              ('orphan', coverage.get('orphan_pages')),
                              ('scroll', coverage.get('scroll_only_products'))]:
                if data:
                    zip_write(z, names[key], localize_df(pd.DataFrame(data), lang))

        if structured:
            for key, data in [('imggap', structured.get('image_gap')),
                              ('namegap', structured.get('name_mismatch')),
                              ('catgap', structured.get('category_rows'))]:
                if data:
                    zip_write(z, names[key], localize_df(pd.DataFrame(data), lang))

        titles = build_titles_urls_list(df, lang, platform)
        descs = build_descs_list(df, lang)
        alt_missing = build_image_list(images_df, ALT_MISSING_STATES, lang)
        alt_weak = build_image_list(images_df, ALT_WEAK_EXPORT, lang)
        broken = build_broken_list(df, lang, platform)
        zid_red = build_zid_redirect_table(df, platform)
        if zid_red is not None and not zid_red.empty:
            z.writestr(names['zid_redirects'], to_xlsx_bytes(zid_red))
        for key, table in (('titles', titles), ('descs', descs),
                           ('alt_missing', alt_missing), ('alt_weak', alt_weak),
                           ('broken', broken)):
            if table is not None and not table.empty:
                zip_write(z, names[key], table)

        zip_write(z, names['excel'], ldf)
    return buf.getvalue()


# ==============================================================
