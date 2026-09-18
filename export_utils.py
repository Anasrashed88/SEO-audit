
import io
import zipfile
import pandas as pd
from audit_engine import (
    PAGE_TYPE_ORDER, ALT_WEAK_STATES,
    unique_images
)

PAGE_TYPE_LABEL = {
    'ar': {'home': 'صفحة رئيسية', 'product': 'صفحة منتج', 'category': 'صفحة تصنيف',
           'blog': 'صفحة مدونة', 'info': 'صفحة تعريفية', 'archive': 'صفحة أرشيف',
           'unknown': 'غير مصنفة', 'broken': 'صفحة غير متاحة'},
    'en': {'home': 'Homepage', 'product': 'Product', 'category': 'Category',
           'blog': 'Blog', 'info': 'Info / Policy', 'archive': 'Archive',
           'unknown': 'Unclassified', 'broken': 'Unreachable'},
}

STATUS_LABEL = {
    'ar': {
        'missing': 'مفقود', 'very_short': 'قصير جداً', 'acceptable': 'مقبول',
        'optimal': 'مثالي', 'long': 'طويل', 'failed': 'تعذر الفحص',
        'good': 'جيد', 'thin': 'ضعيف جداً', 'na': 'غير متاح',
        'alt_missing': 'مفقود', 'alt_generic': 'غير وصفي', 'alt_stuffed': 'حشو كلمات',
        'alt_long': 'يتجاوز 125 حرفاً', 'alt_duplicate': 'مكرر على عدة صور',
        'alt_ok': 'سليم', 'alt_empty': 'لا يوجد (فارغ)',
        'canon_same': 'مطابق', 'canon_diff': 'مختلف عن رابط الصفحة', 'canon_missing': 'مفقود',
        'match_ok': 'مطابق', 'match_diff': 'مختلف عن عنوان الصفحة', 'match_na': '—',
    },
    'en': {
        'missing': 'Missing', 'very_short': 'Too short', 'acceptable': 'Acceptable',
        'optimal': 'Optimal', 'long': 'Too long', 'failed': 'Scan failed',
        'good': 'Good', 'thin': 'Thin content', 'na': 'N/A',
        'alt_missing': 'Missing', 'alt_generic': 'Not descriptive',
        'alt_stuffed': 'Keyword stuffed', 'alt_long': 'Over 125 characters',
        'alt_duplicate': 'Duplicated across images', 'alt_ok': 'Good',
        'alt_empty': '(empty)',
        'canon_same': 'Self-referencing', 'canon_diff': 'Differs from page URL',
        'canon_missing': 'Missing',
        'match_ok': 'Matches', 'match_diff': 'Differs from page heading',
        'match_na': '—',
    },
}

QUALITY_LABEL = {
    'ar': {'q_ok': 'سليم', 'q_symbols': 'رموز بلا نص', 'q_placeholder': 'قيمة قالب افتراضية',
           'q_brand_only': 'اسم المتجر فقط', 'q_duplicate': 'مكرر على عدة صفحات',
           'q_one_word': 'كلمة واحدة بلا وصف', 'q_same_as_title': 'نسخة من العنوان',
           'q_na': '—'},
    'en': {'q_ok': 'Sound', 'q_symbols': 'Symbols only', 'q_placeholder': 'Template placeholder',
           'q_brand_only': 'Store name only', 'q_duplicate': 'Duplicated across pages',
           'q_one_word': 'Single word, no description', 'q_same_as_title': 'Copy of the title',
           'q_na': '—'},
}

URL_LABEL = {
    'ar': {'u_ok': 'سليم', 'u_clone': 'منتج مستنسخ', 'u_generic': 'رقم أو رمز بلا كلمات',
           'u_wrongname': 'يشير لمنتج آخر',
           'u_underscore': 'شرطة سفلية بدل الواصلة', 'u_uppercase': 'حروف كبيرة',
           'u_long': 'طويل جداً', 'u_repeat': 'كلمة مكررة داخل الرابط',
           'u_wordy': 'كلمات كثيرة', 'u_malformed': 'رابط معطوب فيه عنوان موقع',
           'u_na': '—'},
    'en': {'u_ok': 'Sound', 'u_clone': 'Cloned product', 'u_generic': 'ID or code, no words',
           'u_wrongname': 'Points to a different product',
           'u_underscore': 'Underscores instead of hyphens', 'u_uppercase': 'Uppercase letters',
           'u_long': 'Too long', 'u_repeat': 'Repeated word in slug',
           'u_wordy': 'Too many words', 'u_malformed': 'Malformed: contains a URL',
           'u_na': '—'},
}

COL_EN = {
    'نوع الصفحة': 'Page Type', 'الرابط': 'URL', 'الرابط الكانوني': 'Canonical URL',
    'مصدر الاكتشاف': 'Discovered Via', 'متاحة': 'Reachable', 'كود الاستجابة': 'Status Code',
    'درجة السيو': 'SEO Score', 'عنوان الميتا': 'Meta Title', 'طول العنوان': 'Title Length',
    'حالة العنوان': 'Title Status', 'وصف الميتا': 'Meta Description',
    'طول الوصف': 'Description Length', 'حالة الوصف': 'Description Status',
    'إجمالي الصور': 'Total Images', 'صور بدون Alt': 'Images Missing Alt',
    'صور Alt ضعيف': 'Images With Weak Alt', 'عدد الكلمات': 'Word Count',
    'حالة المحتوى': 'Content Status', 'لغة الصفحة': 'Page Language',
    'حالة الكانونيكال': 'Canonical Status', 'قابلة للأرشفة': 'Indexable',
    'مطابقة العنوان مع H1': 'Title vs H1', 'عنوان الصفحة (H1)': 'Page H1', 'رابط الصفحة': 'Page URL',
    'رابط الصورة': 'Image URL', 'النص البديل الحالي (Alt)': 'Current Alt Text',
    'طول النص البديل': 'Alt Length', 'حالة النص البديل': 'Alt Status',
    'عدد الصفحات': 'Appears On Pages',
    'الوجهة النهائية': 'Final Destination',
    'جودة العنوان': 'Title Quality', 'جودة الوصف': 'Description Quality',
    'جودة الرابط': 'URL Quality', 'المسار': 'Slug', 'محتوى مكرر': 'Duplicate Content',
    'اسم المنتج المعروض': 'Displayed Product Name', 'صيغة الصورة': 'Image Format',
    'اسم منظم': 'Declared Name', 'صور معلنة': 'Declared Images',
    'رقم المنتج': 'SKU', 'عدد معلن': 'Declared Count',
    'الاسم المعلن': 'Declared Name', 'الاسم المعروض': 'Displayed Name',
    'صور مرصودة': 'Images Detected', 'القسم': 'Category',
    'في الخريطة': 'In Sitemap', 'مرتبط برابط': 'Internally Linked',
    'الأولوية': 'Priority', 'ما يحتاج إصلاحاً': 'What Needs Fixing',
    'عنوان الميتا الحالي': 'Current Meta Title',
    'وصف الميتا الحالي': 'Current Meta Description', 'م': '#',
    'مرصود': 'Detected', 'ناقص': 'Missing', 'عدد معلن': 'Declared Count',
}

ZIP_NAMES = {
    'ar': {'product': "1_المنتجات.csv", 'category': "2_التصنيفات.csv",
           'blog': "3_المدونة.csv", 'info': "4_الصفحات_التعريفية.csv",
           'home': "5_الصفحة_الرئيسية.csv", 'archive': "6_صفحات_أرشيف.csv",
           'unknown': "7_غير_مصنفة.csv", 'broken': "8_روابط_معطلة.csv",
           'images': "9_تدقيق_الصور.csv",
           'notidx': "9_منتجات_غير_مدرجة_في_الخريطة.csv",
           'orphan': "10_صفحات_يتيمة.csv",
           'scroll': "15_منتجات_بالتمرير_فقط.csv",
           'fix': "00_صفحات_تحتاج_إصلاح.csv",
           'noalt': "00_صور_تحتاج_وصفاً.csv",
           'redirect': "11_روابط_محذوفة_في_الخريطة.csv",
           'imggap': "12_صفحات_صورها_ناقصة.csv",
           'namegap': "13_اسم_معلن_مختلف.csv",
           'catgap': "14_مقارنة_عدادات_الأقسام.csv",
           'excel': "التقرير_الشامل.xlsx"},
    'en': {'product': "1_products.csv", 'category': "2_categories.csv",
           'blog': "3_blog.csv", 'info': "4_info_pages.csv",
           'home': "5_homepage.csv", 'archive': "6_archive_pages.csv",
           'unknown': "7_unclassified.csv", 'broken': "8_broken_links.csv",
           'images': "9_image_alt_audit.csv",
           'notidx': "9_products_missing_from_sitemap.csv",
           'orphan': "10_orphan_pages.csv",
           'scroll': "15_scroll_only_products.csv",
           'fix': "00_pages_to_fix.csv",
           'noalt': "00_images_needing_alt.csv",
           'redirect': "11_dead_urls_in_sitemap.csv",
           'imggap': "12_pages_with_missing_images.csv",
           'namegap': "13_declared_name_mismatch.csv",
           'catgap': "14_category_counter_comparison.csv",
           'excel': "full_audit_report.xlsx"},
}


def localize_df(df, lang):
    if df is None or df.empty:
        return df
    out = df.copy()
    if '_raw_url' in out.columns:
        out = out.drop(columns=['_raw_url'])
    if 'نوع الصفحة' in out.columns:
        out['نوع الصفحة'] = out['نوع الصفحة'].map(lambda v: PAGE_TYPE_LABEL[lang].get(v, v))
    for col in ['حالة العنوان', 'حالة الوصف', 'حالة المحتوى', 'حالة النص البديل',
                'حالة الكانونيكال', 'مطابقة العنوان مع H1']:
        if col in out.columns:
            out[col] = out[col].map(lambda v: STATUS_LABEL[lang].get(v, v))
    for col in ['جودة العنوان', 'جودة الوصف']:
        if col in out.columns:
            out[col] = out[col].map(lambda v: QUALITY_LABEL[lang].get(v, v))
    if 'جودة الرابط' in out.columns:
        out['جودة الرابط'] = out['جودة الرابط'].map(lambda v: URL_LABEL[lang].get(v, v))
    if 'النص البديل الحالي (Alt)' in out.columns:
        empty = STATUS_LABEL[lang]['alt_empty']
        out['النص البديل الحالي (Alt)'] = out['النص البديل الحالي (Alt)'].map(
            lambda v: v if str(v).strip() else empty)
    if lang == 'en':
        out = out.rename(columns={k: v for k, v in COL_EN.items() if k in out.columns})
    return out


def build_fix_lists(df, images_df, lang='ar'):
    L = STATUS_LABEL[lang]
    QL = QUALITY_LABEL[lang]
    UL = URL_LABEL[lang]
    ok = df[df['متاحة'] == True].copy()  # noqa: E712
    rows = []
    for _, r in ok.iterrows():
        need = []
        if r['حالة العنوان'] in ('missing', 'very_short', 'long'):
            need.append(('العنوان' if lang == 'ar' else 'Title') + f" ({L[r['حالة العنوان']]})")
        elif r['حالة العنوان'] == 'acceptable':
            need.append('تحسين العنوان' if lang == 'ar' else 'Improve title')
        if r.get('جودة العنوان') not in ('q_ok', 'q_na', None):
            need.append(QL.get(r.get('جودة العنوان'), ''))
        if r['حالة الوصف'] in ('missing', 'very_short', 'long'):
            need.append(('الوصف' if lang == 'ar' else 'Description') + f" ({L[r['حالة الوصف']]})")
        elif r['حالة الوصف'] == 'acceptable':
            need.append('تحسين الوصف' if lang == 'ar' else 'Improve description')
        if r.get('جودة الرابط') not in ('u_ok', 'u_na', None):
            need.append(UL.get(r.get('جودة الرابط'), ''))
        if int(r.get('صور بدون Alt') or 0):
            need.append((f"{int(r['صور بدون Alt'])} صورة بلا وصف" if lang == 'ar' else f"{int(r['صور بدون Alt'])} images without alt"))
        if int(r.get('صور Alt ضعيف') or 0):
            need.append((f"{int(r['صور Alt ضعيف'])} صورة بوصف ضعيف" if lang == 'ar' else f"{int(r['صور Alt ضعيف'])} images with weak alt"))
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


def build_zip(df, images_df, coverage=None, lang='ar', structured=None):
    names = ZIP_NAMES[lang]
    ldf = localize_df(df, lang)
    limg = localize_df(unique_images(images_df), lang)
    type_col = COL_EN['نوع الصفحة'] if lang == 'en' else 'نوع الصفحة'

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for tkey in PAGE_TYPE_ORDER:
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
                    z.writestr(names[key], localize_df(pd.DataFrame(data), lang).to_csv(index=False, encoding='utf-8-sig'))

        if structured:
            for key, data in [('imggap', structured.get('image_gap')),
                              ('namegap', structured.get('name_mismatch')),
                              ('catgap', structured.get('category_rows'))]:
                if data:
                    z.writestr(names[key], localize_df(pd.DataFrame(data), lang).to_csv(index=False, encoding='utf-8-sig'))

        fix, noalt = build_fix_lists(df, images_df, lang)
        if fix is not None and not fix.empty:
            z.writestr(names['fix'], fix.to_csv(index=False, encoding='utf-8-sig'))
        if noalt is not None and not noalt.empty:
            z.writestr(names['noalt'], noalt.to_csv(index=False, encoding='utf-8-sig'))

        xbuf = io.BytesIO()
        with pd.ExcelWriter(xbuf, engine='openpyxl') as w:
            ldf.to_excel(w, index=False, sheet_name='Pages Audit' if lang == 'en' else 'فحص الصفحات')
            if limg is not None and not limg.empty:
                limg.to_excel(w, index=False, sheet_name='Images Audit' if lang == 'en' else 'فحص الصور')
            if fix is not None and not fix.empty:
                fix.to_excel(w, index=False, sheet_name='To Fix' if lang == 'en' else 'يحتاج إصلاح')
            if noalt is not None and not noalt.empty:
                noalt.to_excel(w, index=False, sheet_name='No Alt' if lang == 'en' else 'صور بلا وصف')
        z.writestr(names['excel'], xbuf.getvalue())
    return buf.getvalue()
