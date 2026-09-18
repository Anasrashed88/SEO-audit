"""
ملف الروابط المستبعدة
=====================
يبني ملفاً منفصلاً بالروابط التي استبعدتها الأداة من التقرير، وسبب استبعاد كل رابط
كما اكتشفته فعلياً: محذوفة (404) أو محوّلة للرئيسية أو مخفية عن جوجل (noindex).

لا يحتاج تعديل export_utils.py — يضيف الملف داخل حزمة ZIP الجاهزة كما هي.
"""

import io
import zipfile
import pandas as pd

from audit_engine import EXCLUDED_COLUMNS

FILE_NAME = "Excluded_Links.csv"


def build_excluded_df(coverage):
    """يحوّل نتائج الفحص إلى جدول الروابط المستبعدة."""
    rows = (coverage or {}).get('excluded_rows') or []
    if not rows:
        return pd.DataFrame(columns=EXCLUDED_COLUMNS)
    df = pd.DataFrame(rows)
    for col in EXCLUDED_COLUMNS:
        if col not in df.columns:
            df[col] = ''
    df = df[EXCLUDED_COLUMNS]
    # المحذوفة أولاً، ثم المحوّلة، ثم المخفية
    order = {'محذوفة (404)': 0, 'محذوفة (410)': 0, 'محوّلة للرئيسية': 1}
    df = df.assign(_o=df['الحالة'].map(lambda x: order.get(x, 2))) \
           .sort_values(['_o', 'نوع الصفحة', 'الرابط']) \
           .drop(columns=['_o']) \
           .reset_index(drop=True)
    return df


def excluded_csv_bytes(coverage):
    """محتوى ملف CSV جاهز للتحميل (يفتح في إكسل بالعربي بدون رموز غريبة)."""
    df = build_excluded_df(coverage)
    return df.to_csv(index=False).encode('utf-8-sig')


def excluded_counts(coverage):
    """عدد الروابط لكل حالة، للعرض في الشاشة."""
    df = build_excluded_df(coverage)
    if df.empty:
        return {}
    return {str(k): int(v) for k, v in df['الحالة'].value_counts().items()}


def add_excluded_to_zip(zip_bytes, coverage, file_name=FILE_NAME):
    """يضيف ملف الروابط المستبعدة إلى حزمة ZIP موجودة ويعيدها."""
    df = build_excluded_df(coverage)
    if df.empty:
        return zip_bytes

    src = io.BytesIO(zip_bytes)
    out = io.BytesIO()
    with zipfile.ZipFile(src, 'r') as zin, \
            zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as zout:
        existing = set(zin.namelist())
        for item in zin.infolist():
            zout.writestr(item, zin.read(item.filename))
        name = file_name
        if name in existing:                     # لا نستبدل ملفاً موجوداً بنفس الاسم
            name = f"Excluded_Links_extra.csv"
        zout.writestr(name, df.to_csv(index=False).encode('utf-8-sig'))
    return out.getvalue()
