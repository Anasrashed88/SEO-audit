"""بناء ملفات التصدير: الحزمة والجداول العملية."""
import io
import zipfile

import pandas as pd

from audit_engine import (
    PAGE_TYPE_ORDER, PAGE_TYPE_LABEL, STATUS_LABEL, QUALITY_LABEL, URL_LABEL,
    COL_EN, ALT_WEAK_STATES, localize_df, unique_images, build_broken_links,
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
           'redirect': "11_روابط_محذوفة_في_الخريطة.csv",
           'imggap': "12_صفحات_صورها_ناقصة.csv",
           'namegap': "13_اسم_معلن_مختلف.csv",
           'catgap': "14_مقارنة_عدادات_الأقسام.csv",
           'excel': "التقرير_الشامل.xlsx"},
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
           'redirect': "11_dead_urls_in_sitemap.csv",
           'imggap': "12_pages_with_missing_images.csv",
           'namegap': "13_declared_name_mismatch.csv",
           'catgap': "14_category_counter_comparison.csv",
           'excel': "full_audit_report.xlsx"},
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


def build_broken_list(df, lang='ar'):
    """الروابط التي لا تعمل وليس لها إعادة توجيه، جاهزة للتصدير."""
    out = build_broken_links(df)
    if out.empty:
        return pd.DataFrame()
    out.insert(0, 'م', range(1, len(out) + 1))
    return localize_df(out, lang)


def build_filtered_exports(df, images_df, lang='ar'):
    """الملفات التي يمكن تحميلها منفصلة من الواجهة:
    يعيد {المفتاح: (اسم الملف، جدول)} للجداول غير الفارغة فقط."""
    names = ZIP_NAMES[lang]
    fix, _ = build_fix_lists(df, images_df, lang)
    tables = {
        'fix': fix,
        'alt_missing': build_image_list(images_df, ALT_MISSING_STATES, lang),
        'alt_weak': build_image_list(images_df, ALT_WEAK_EXPORT, lang),
        'broken': build_broken_list(df, lang),
    }
    return {k: (names[k], t) for k, t in tables.items() if t is not None and not t.empty}


def to_csv_bytes(table):
    return table.to_csv(index=False).encode('utf-8-sig')


def build_zip(df, images_df, coverage=None, lang='ar', structured=None):
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
                z.writestr(fname, sub.to_csv(index=False, encoding='utf-8-sig'))
        if limg is not None and not limg.empty:
            z.writestr(names['images'], limg.to_csv(index=False, encoding='utf-8-sig'))

        if coverage:
            for key, data in [('notidx', coverage.get('unlisted_pages')),
                              ('orphan', coverage.get('orphan_pages')),
                              ('redirect', coverage.get('dead_pages')),
                              ('scroll', coverage.get('scroll_only_products'))]:
                if data:
                    z.writestr(names[key],
                               localize_df(pd.DataFrame(data), lang)
                               .to_csv(index=False, encoding='utf-8-sig'))

        if structured:
            for key, data in [('imggap', structured.get('image_gap')),
                              ('namegap', structured.get('name_mismatch')),
                              ('catgap', structured.get('category_rows'))]:
                if data:
                    z.writestr(names[key],
                               localize_df(pd.DataFrame(data), lang)
                               .to_csv(index=False, encoding='utf-8-sig'))

        fix, noalt = build_fix_lists(df, images_df, lang)
        if fix is not None and not fix.empty:
            z.writestr(names['fix'], fix.to_csv(index=False, encoding='utf-8-sig'))
        if noalt is not None and not noalt.empty:
            z.writestr(names['noalt'], noalt.to_csv(index=False, encoding='utf-8-sig'))

        alt_missing = build_image_list(images_df, ALT_MISSING_STATES, lang)
        alt_weak = build_image_list(images_df, ALT_WEAK_EXPORT, lang)
        broken = build_broken_list(df, lang)
        for key, table in (('alt_missing', alt_missing), ('alt_weak', alt_weak),
                           ('broken', broken)):
            if table is not None and not table.empty:
                z.writestr(names[key], table.to_csv(index=False, encoding='utf-8-sig'))

        xbuf = io.BytesIO()
        with pd.ExcelWriter(xbuf, engine='openpyxl') as w:
            ldf.to_excel(w, index=False,
                         sheet_name='Pages Audit' if lang == 'en' else 'فحص الصفحات')
            if limg is not None and not limg.empty:
                limg.to_excel(w, index=False,
                              sheet_name='Images Audit' if lang == 'en' else 'فحص الصور')
            if fix is not None and not fix.empty:
                fix.to_excel(w, index=False,
                             sheet_name='To Fix' if lang == 'en' else 'يحتاج إصلاح')
            if alt_missing is not None and not alt_missing.empty:
                alt_missing.to_excel(w, index=False,
                                     sheet_name='Missing Alt' if lang == 'en' else 'صور بلا وصف')
            if alt_weak is not None and not alt_weak.empty:
                alt_weak.to_excel(w, index=False,
                                  sheet_name='Weak Alt' if lang == 'en' else 'صور وصفها ضعيف')
            if broken is not None and not broken.empty:
                broken.to_excel(w, index=False,
                                sheet_name='Broken Links' if lang == 'en' else 'روابط لا تعمل')
        z.writestr(names['excel'], xbuf.getvalue())
    return buf.getvalue()


# ==============================================================
