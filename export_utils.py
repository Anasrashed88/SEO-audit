import io
import zipfile
import pandas as pd
from audit_engine import (
    PAGE_TYPE_ORDER, PAGE_TYPE_LABEL, STATUS_LABEL, EXCLUDED_COLUMNS,
    T_PRODUCT, T_CATEGORY, T_BLOG, T_INFO, T_HOME, T_ARCHIVE, T_UNKNOWN, T_BROKEN
)

ZIP_NAMES = {
    'ar': {
        T_PRODUCT: "1_المنتجات.csv",
        T_CATEGORY: "2_التصنيفات.csv",
        T_BLOG: "3_المدونة.csv",
        T_INFO: "4_الصفحات_التعريفية.csv",
        T_HOME: "5_الصفحة_الرئيسية.csv",
        T_ARCHIVE: "6_صفحات_أرشيف.csv",
        T_UNKNOWN: "7_غير_مصنفة.csv",
        T_BROKEN: "8_روابط_معطلة.csv",
        'images': "9_تدقيق_الصور_الفريدة.csv",
        'notidx': "10_صفحات_غير_مدرجة_في_الخريطة.csv",
        'orphan': "11_صفحات_يتيمة.csv",
        'dead': "12_روابط_معطلة_في_الخريطة.csv",
        'excluded': "13_روابط_مستبعدة_محذوفة_أو_محوّلة.csv",
        'unreachable': "14_روابط_تعذر_فحصها.csv",
        'fix': "00_صفحات_تحتاج_إصلاح.csv",
        'noalt': "00_صور_تحتاج_وصفاً.csv",
        'excel': "التقرير_الشامل.xlsx"
    },
    'en': {
        T_PRODUCT: "1_products.csv",
        T_CATEGORY: "2_categories.csv",
        T_BLOG: "3_blog.csv",
        T_INFO: "4_info_pages.csv",
        T_HOME: "5_homepage.csv",
        T_ARCHIVE: "6_archive_pages.csv",
        T_UNKNOWN: "7_unclassified.csv",
        T_BROKEN: "8_broken_links.csv",
        'images': "9_unique_images_audit.csv",
        'notidx': "10_pages_missing_from_sitemap.csv",
        'orphan': "11_orphan_pages.csv",
        'dead': "12_dead_urls_in_sitemap.csv",
        'excluded': "13_excluded_links_deleted_or_redirected.csv",
        'unreachable': "14_unreachable_urls.csv",
        'fix': "00_pages_to_fix.csv",
        'noalt': "00_images_needing_alt.csv",
        'excel': "full_audit_report.xlsx"
    }
}

# تسميات إنجليزية لحالات الاستبعاد (النصوص تأتي من محرك الفحص بالعربية)
EXCLUDED_STATUS_EN = {
    'محذوفة (404)': 'Deleted (404)',
    'محذوفة (410)': 'Deleted (410)',
    'محوّلة للرئيسية': 'Redirected to homepage',
    'مخفية عن جوجل (noindex)': 'Hidden from Google (noindex)',
}

EXCLUDED_HEADERS_EN = {
    'الرابط': 'URL',
    'نوع الصفحة': 'Page Type',
    'الحالة': 'Status',
    'كود الاستجابة': 'Response Code',
    'وجهة التحويل': 'Redirect Target',
    'في خريطة الموقع': 'In Sitemap',
    'مصدر الاكتشاف': 'Discovered Via',
}

# دالة تعريب الحالات التقنية لعرضها للعميل باحترافية
def localize_dataframe(df, lang='ar'):
    if df is None or df.empty:
        return df
    out = df.copy()
    labels = PAGE_TYPE_LABEL.get(lang, PAGE_TYPE_LABEL['ar'])
    statuses = STATUS_LABEL.get(lang, STATUS_LABEL['ar'])
    if 'نوع الصفحة' in out.columns:
        out['نوع الصفحة'] = out['نوع الصفحة'].map(lambda x: labels.get(x, x))
    for col in ['حالة العنوان', 'حالة الوصف', 'حالة المحتوى', 'حالة النص البديل', 'حالة الكانونيكال', 'مطابقة العنوان مع H1']:
        if col in out.columns:
            out[col] = out[col].map(lambda x: statuses.get(x, x))
    return out

def build_excluded_list(coverage, lang='ar'):
    """جدول الروابط التي استبعدتها الأداة من التقرير، وسبب استبعاد كل رابط كما اكتشفته:
    محذوفة (404) أو محوّلة للرئيسية أو مخفية عن جوجل (noindex)."""
    rows = (coverage or {}).get('excluded_rows') or []
    if not rows:
        return pd.DataFrame(columns=EXCLUDED_COLUMNS)

    out = pd.DataFrame(rows)
    for col in EXCLUDED_COLUMNS:
        if col not in out.columns:
            out[col] = ''
    out = out[EXCLUDED_COLUMNS].copy()

    labels = PAGE_TYPE_LABEL.get(lang, PAGE_TYPE_LABEL['ar'])
    out['نوع الصفحة'] = out['نوع الصفحة'].map(lambda x: labels.get(x, x))

    # المحذوفة أولاً، ثم المحوّلة، ثم المخفية
    order = {'محذوفة (404)': 0, 'محذوفة (410)': 0, 'محوّلة للرئيسية': 1}
    out = out.assign(_o=out['الحالة'].map(lambda x: order.get(x, 2))) \
             .sort_values(['_o', 'نوع الصفحة', 'الرابط']) \
             .drop(columns=['_o']) \
             .reset_index(drop=True)

    if lang == 'en':
        out['الحالة'] = out['الحالة'].map(lambda x: EXCLUDED_STATUS_EN.get(x, x))
        out['في خريطة الموقع'] = out['في خريطة الموقع'].map({'نعم': 'Yes', 'لا': 'No'})
        out = out.rename(columns=EXCLUDED_HEADERS_EN)

    out.insert(0, 'م' if lang == 'ar' else '#', range(1, len(out) + 1))
    return out

def build_unreachable_list(df, lang='ar'):
    """روابط موجودة لكن تعذّر فحصها (رفض مؤقت من المتجر أو انتهاء المهلة)،
    وهي ليست مستبعدة بل تحتاج إعادة فحص."""
    if df is None or df.empty or 'متاحة' not in df.columns:
        return pd.DataFrame()
    sub = df[df['متاحة'] == False].copy()
    if sub.empty:
        return pd.DataFrame()
    labels = PAGE_TYPE_LABEL.get(lang, PAGE_TYPE_LABEL['ar'])
    sub['نوع الصفحة'] = sub['نوع الصفحة'].map(lambda x: labels.get(x, x))
    cols = [c for c in ['الرابط', 'نوع الصفحة', 'كود الاستجابة', 'مصدر الاكتشاف'] if c in sub.columns]
    return sub[cols].reset_index(drop=True)

def build_fix_lists(df, images_df, lang='ar'):
    ok = df[df['متاحة'] == True].copy()
    rows = []
    for _, r in ok.iterrows():
        need = []
        if r['حالة العنوان'] in ('missing', 'very_short', 'long'):
            need.append('إصلاح العنوان' if lang == 'ar' else 'Fix Title')
        if r.get('مطابقة العنوان مع H1') == 'match_diff':
            need.append('العنوان لا يطابق H1' if lang == 'ar' else 'Title differs from H1')
        if r['حالة الوصف'] in ('missing', 'very_short', 'long'):
            need.append('إصلاح الوصف' if lang == 'ar' else 'Fix Description')
        if int(r.get('صور بدون Alt') or 0) > 0:
            need.append(f"{int(r['صور بدون Alt'])} صورة بلا Alt" if lang == 'ar' else f"{int(r['صور بدون Alt'])} images missing Alt")
        if int(r.get('صور Alt ضعيف') or 0) > 0:
            need.append(f"{int(r['صور Alt ضعيف'])} صورة بوصف ضعيف" if lang == 'ar' else f"{int(r['صور Alt ضعيف'])} images with weak Alt")
        if r['حالة المحتوى'] == 'thin':
            need.append('محتوى نصي ضعيف' if lang == 'ar' else 'Thin content')

        if need:
            rows.append({
                'النوع': PAGE_TYPE_LABEL.get(lang, PAGE_TYPE_LABEL['ar']).get(r['نوع الصفحة'], r['نوع الصفحة']),
                'الرابط': r['الرابط'],
                'درجة السيو': r['درجة السيو'],
                'المشاكل المرصودة': ' · '.join(need),
                'عنوان الميتا الحالي': r['عنوان الميتا'],
                'عنوان الصفحة (H1)': r.get('عنوان الصفحة (H1)', ''),
                'وصف الميتا الحالي': r['وصف الميتا'],
            })

    fix_df = pd.DataFrame(rows)
    if not fix_df.empty:
        fix_df = fix_df.sort_values('درجة السيو').reset_index(drop=True)
        fix_df.insert(0, 'الأولوية', range(1, len(fix_df) + 1))

    noalt_df = pd.DataFrame()
    if images_df is not None and not images_df.empty:
        bad_imgs = images_df[images_df['حالة النص البديل'] != 'alt_ok'].copy()
        if not bad_imgs.empty:
            bad_imgs['نوع الصفحة'] = bad_imgs['نوع الصفحة'].map(lambda x: PAGE_TYPE_LABEL.get(lang, PAGE_TYPE_LABEL['ar']).get(x, x))
            bad_imgs['حالة النص البديل'] = bad_imgs['حالة النص البديل'].map(lambda x: STATUS_LABEL.get(lang, STATUS_LABEL['ar']).get(x, x))
            cols = ['رابط الصفحة', 'نوع الصفحة', 'رابط الصورة', 'النص البديل الحالي (Alt)', 'حالة النص البديل']
            if 'عدد الصفحات' in bad_imgs.columns:
                cols.append('عدد الصفحات')
            noalt_df = bad_imgs[cols].reset_index(drop=True)
            noalt_df.insert(0, 'م', range(1, len(noalt_df) + 1))

    return fix_df, noalt_df

def build_zip_package(df, images_df, coverage=None, lang='ar'):
    names = ZIP_NAMES.get(lang, ZIP_NAMES['ar'])
    buf = io.BytesIO()

    # تجهيز نسخ معربة بالكامل من الجداول لضمان احترافية الملفات
    loc_df = localize_dataframe(df, lang)
    loc_imgs = localize_dataframe(images_df, lang) if images_df is not None and not images_df.empty else None

    excluded_df = build_excluded_list(coverage, lang)
    unreachable_df = build_unreachable_list(df, lang)

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        # 1. ملفات CSV لكل نوع صفحة معربة بالكامل
        for tkey in PAGE_TYPE_ORDER:
            tlabel = PAGE_TYPE_LABEL.get(lang, PAGE_TYPE_LABEL['ar']).get(tkey, tkey)
            sub = loc_df[loc_df['نوع الصفحة'] == tlabel].copy()
            if not sub.empty:
                fname = names.get(tkey, f"{tkey}.csv")
                z.writestr(fname, sub.to_csv(index=False, encoding='utf-8-sig'))

        # 2. ملف تدقيق الصور الفريدة
        if loc_imgs is not None and not loc_imgs.empty:
            z.writestr(names['images'], loc_imgs.to_csv(index=False, encoding='utf-8-sig'))

        # 3. ملفات الخريطة
        if coverage:
            if coverage.get('unlisted_pages'):
                unl_df = pd.DataFrame({'الرابط': coverage['unlisted_pages']})
                z.writestr(names['notidx'], unl_df.to_csv(index=False, encoding='utf-8-sig'))
            if coverage.get('orphan_pages'):
                orph_df = pd.DataFrame({'الرابط': coverage['orphan_pages']})
                z.writestr(names['orphan'], orph_df.to_csv(index=False, encoding='utf-8-sig'))
            if coverage.get('dead_pages'):
                dead_df = pd.DataFrame({'الرابط': coverage['dead_pages']})
                z.writestr(names['dead'], dead_df.to_csv(index=False, encoding='utf-8-sig'))

        # 4. ملف الروابط المستبعدة (محذوفة 404 / محوّلة للرئيسية / مخفية عن جوجل)
        if not excluded_df.empty:
            z.writestr(names['excluded'], excluded_df.to_csv(index=False, encoding='utf-8-sig'))

        # 5. روابط تعذّر فحصها (تحتاج إعادة محاولة، وليست مستبعدة)
        if not unreachable_df.empty:
            z.writestr(names['unreachable'], unreachable_df.to_csv(index=False, encoding='utf-8-sig'))

        # 6. ملفات قوائم الإصلاح الفوري
        fix_df, noalt_df = build_fix_lists(df, images_df, lang)
        if not fix_df.empty:
            z.writestr(names['fix'], fix_df.to_csv(index=False, encoding='utf-8-sig'))
        if not noalt_df.empty:
            z.writestr(names['noalt'], noalt_df.to_csv(index=False, encoding='utf-8-sig'))

        # 7. ملف الإكسل الشامل متعدد الصفحات ببيانات عربية نظيفة
        xbuf = io.BytesIO()
        with pd.ExcelWriter(xbuf, engine='openpyxl') as w:
            loc_df.to_excel(w, index=False, sheet_name='فحص الصفحات' if lang == 'ar' else 'Pages Audit')
            if loc_imgs is not None and not loc_imgs.empty:
                loc_imgs.to_excel(w, index=False, sheet_name='فحص الصور الفريدة' if lang == 'ar' else 'Images Audit')
            if not fix_df.empty:
                fix_df.to_excel(w, index=False, sheet_name='يحتاج إصلاح' if lang == 'ar' else 'To Fix')
            if not noalt_df.empty:
                noalt_df.to_excel(w, index=False, sheet_name='صور بلا وصف' if lang == 'ar' else 'Missing Alt')
            if not excluded_df.empty:
                excluded_df.to_excel(w, index=False, sheet_name='روابط مستبعدة' if lang == 'ar' else 'Excluded Links')
            if not unreachable_df.empty:
                unreachable_df.to_excel(w, index=False, sheet_name='تعذر فحصها' if lang == 'ar' else 'Unreachable')
        z.writestr(names['excel'], xbuf.getvalue())

    return buf.getvalue()
