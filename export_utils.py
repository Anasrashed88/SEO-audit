import io
import zipfile
import pandas as pd
from audit_engine import PAGE_TYPE_ORDER, PAGE_TYPE_LABEL, STATUS_LABEL, T_PRODUCT, T_CATEGORY, T_BLOG, T_INFO, T_HOME, T_UNKNOWN, T_BROKEN

ZIP_NAMES = {
    'ar': {
        T_PRODUCT: "1_المنتجات.csv",
        T_CATEGORY: "2_التصنيفات.csv",
        T_BLOG: "3_المدونة.csv",
        T_INFO: "4_الصفحات_التعريفية.csv",
        T_HOME: "5_الصفحة_الرئيسية.csv",
        T_UNKNOWN: "6_غير_مصنفة.csv",
        T_BROKEN: "7_روابط_معطلة.csv",
        'images': "8_تدقيق_الصور_الفريدة.csv",
        'notidx': "9_صفحات_غير_مدرجة_في_الخريطة.csv",
        'orphan': "10_صفحات_يتيمة.csv",
        'dead': "11_روابط_معطلة_في_الخريطة.csv",
        'fix': "00_صفحات_تحتاج_إصلاح.csv",
        'noalt': "00_صور_تحتاج_وصفاً.csv",
        'excel': "التقرير_الشامل.xlsx"
    }
}

def build_fix_lists(df, images_df, lang='ar'):
    ok = df[df['متاحة'] == True].copy()
    rows = []
    for _, r in ok.iterrows():
        need = []
        if r['حالة العنوان'] in ('missing', 'very_short', 'long'):
            need.append('إصلاح العنوان' if lang == 'ar' else 'Fix Title')
        if r['مطابقة العنوان مع H1'] == 'match_diff':
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
                'النوع': PAGE_TYPE_LABEL[lang].get(r['نوع الصفحة'], r['نوع الصفحة']),
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
            bad_imgs['نوع الصفحة'] = bad_imgs['نوع الصفحة'].map(lambda x: PAGE_TYPE_LABEL[lang].get(x, x))
            bad_imgs['حالة النص البديل'] = bad_imgs['حالة النص البديل'].map(lambda x: STATUS_LABEL[lang].get(x, x))
            cols = ['رابط الصفحة', 'نوع الصفحة', 'رابط الصورة', 'النص البديل الحالي (Alt)', 'حالة النص البديل']
            if 'عدد الصفحات' in bad_imgs.columns:
                cols.append('عدد الصفحات')
            noalt_df = bad_imgs[cols].reset_index(drop=True)
            noalt_df.insert(0, 'م', range(1, len(noalt_df) + 1))

    return fix_df, noalt_df

def build_zip_package(df, images_df, coverage=None, lang='ar'):
    names = ZIP_NAMES[lang]
    buf = io.BytesIO()

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for tkey in PAGE_TYPE_ORDER:
            sub = df[df['نوع الصفحة'] == tkey].copy()
            if not sub.empty:
                sub['نوع الصفحة'] = sub['نوع الصفحة'].map(lambda x: PAGE_TYPE_LABEL[lang].get(x, x))
                fname = names.get(tkey, f"{tkey}.csv")
                z.writestr(fname, sub.to_csv(index=False, encoding='utf-8-sig'))

        if images_df is not None and not images_df.empty:
            v_imgs = images_df.copy()
            v_imgs['نوع الصفحة'] = v_imgs['نوع الصفحة'].map(lambda x: PAGE_TYPE_LABEL[lang].get(x, x))
            v_imgs['حالة النص البديل'] = v_imgs['حالة النص البديل'].map(lambda x: STATUS_LABEL[lang].get(x, x))
            z.writestr(names['images'], v_imgs.to_csv(index=False, encoding='utf-8-sig'))

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

        fix_df, noalt_df = build_fix_lists(df, images_df, lang)
        if not fix_df.empty:
            z.writestr(names['fix'], fix_df.to_csv(index=False, encoding='utf-8-sig'))
        if not noalt_df.empty:
            z.writestr(names['noalt'], noalt_df.to_csv(index=False, encoding='utf-8-sig'))

        xbuf = io.BytesIO()
        with pd.ExcelWriter(xbuf, engine='openpyxl') as w:
            df.to_excel(w, index=False, sheet_name='فحص الصفحات')
            if images_df is not None and not images_df.empty:
                images_df.to_excel(w, index=False, sheet_name='فحص الصور الفريدة')
            if not fix_df.empty:
                fix_df.to_excel(w, index=False, sheet_name='يحتاج إصلاح')
            if not noalt_df.empty:
                noalt_df.to_excel(w, index=False, sheet_name='صور بلا وصف')
        z.writestr(names['excel'], xbuf.getvalue())

    return buf.getvalue()
