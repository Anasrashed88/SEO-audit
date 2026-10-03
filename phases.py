"""المراحل والفواتير: تقسيم المشروع إلى مراحل، لكل مرحلة ملف مهام وفاتورة ورسالة واتساب.

مستقل عن محرك الفحص: يأخذ ملفات العمل الجاهزة (المرتبة بالأولوية) ويقسمها.
"""
import io
import sqlite3
from datetime import datetime

import pandas as pd

# الخدمات: مفتاحها، ومفتاحها في عرض السعر، والجداول (ملفات التصدير) التي تكوّنها
SERVICES = [
    ('titles', 'meta_title', 'عناوين الميتا والروابط', 'Meta titles & URLs'),
    ('descs', 'meta_desc', 'أوصاف الميتا', 'Meta descriptions'),
    ('images', 'image_alt', 'النصوص البديلة للصور', 'Image alt texts'),
    ('broken', 'broken_link_fix', 'الروابط المعطلة', 'Broken links'),
]
SERVICE_TABLES = {'titles': ['titles'], 'descs': ['descs'], 'images': ['alt_missing', 'alt_weak'],
                  'broken': ['broken']}
# أسماء أوراق ملف المهام = أسماء ملفات التصدير نفسها
SHEET_NAMES = {'titles': 'عناوين وروابط تحتاج إصلاح', 'descs': 'أوصاف ميتا تحتاج إصلاح',
               'alt_missing': 'صور بلا وصف', 'alt_weak': 'صور وصفها غير وصفي أو مكرر',
               'broken': 'روابط لا تعمل', 'zid_redirects': 'تحويلات زد للاستيراد'}
ORDINAL_AR = ['الأولى', 'الثانية', 'الثالثة', 'الرابعة', 'الخامسة']


def work_tables(exports):
    """ملفات العمل كما هي في تبويب التصدير، بكل أعمدتها.
    الروابط المعطلة: ما يحتاج عملاً فقط (هي التي في عرض السعر)."""
    def get(k):
        v = exports.get(k)
        return v[1].copy().reset_index(drop=True) if v else pd.DataFrame()
    broken = get('broken')
    if not broken.empty:
        act = next((c for c in broken.columns if 'الإجراء' in str(c) or 'Action' in str(c)), None)
        if act:
            broken = broken[~broken[act].astype(str).str.contains('لا إجراء|No action', na=False)]
    return {'titles': get('titles'), 'descs': get('descs'), 'alt_missing': get('alt_missing'),
            'alt_weak': get('alt_weak'), 'broken': broken.reset_index(drop=True),
            'zid_redirects': get('zid_redirects')}


def _chunks(df, n):
    """تقسيم بالتساوي مع الحفاظ على الترتيب (الأهم أولاً): 81 على مرحلتين = 41 ثم 40."""
    size, extra = divmod(len(df), n)
    out, start = [], 0
    for i in range(n):
        end = start + size + (1 if i < extra else 0)
        out.append(df.iloc[start:end].reset_index(drop=True))
        start = end
    return out


def _service_empty(tables, svc):
    return all(tables.get(t) is None or tables.get(t).empty for t in SERVICE_TABLES[svc])


def split_phases(tables, n, mode='priority'):
    """يعيد قائمة مراحل، كل مرحلة {اسم الجدول: جدول} بنفس أعمدة ملفات التصدير.
    priority: كل جدول يُقسم على المراحل والأهم في المرحلة الأولى.
    type: كل خدمة كاملة في مرحلة واحدة (العناوين والأوصاف، ثم الصور)."""
    n = max(1, int(n))
    phases = [dict() for _ in range(n)]
    if mode == 'type':
        active = [k for k, *_ in SERVICES if not _service_empty(tables, k)]
        main = [k for k in active if k != 'broken']
        n_eff = min(n, max(1, len(main)))
        size, extra = divmod(len(main), n_eff)
        groups, start = [], 0
        for i in range(n_eff):
            end = start + size + (1 if i < n_eff - extra else 0) if extra else start + size
            groups.append(main[start:end])
            start = end
        if start < len(main):
            groups[-1].extend(main[start:])
        for i, g in enumerate(groups):
            for svc in g:
                for t in SERVICE_TABLES[svc]:
                    if tables.get(t) is not None and not tables[t].empty:
                        phases[i][t] = tables[t]
        if 'broken' in active:
            phases[0]['broken'] = tables['broken']
    else:
        for svc, *_ in SERVICES:
            for t in SERVICE_TABLES[svc]:
                tb = tables.get(t)
                if tb is None or tb.empty:
                    continue
                for i, part in enumerate(_chunks(tb, n)):
                    if not part.empty:
                        phases[i][t] = part
    # تحويلات زد: الصفوف الخاصة بالروابط المعطلة في كل مرحلة
    red = tables.get('zid_redirects')
    if red is not None and not red.empty:
        from_col = next((c for c in red.columns if 'من' in str(c) or 'From' in str(c)), None)
        for p in phases:
            b = p.get('broken')
            if from_col and b is not None and not b.empty:
                url_col = next((c for c in b.columns if str(c) in ('الرابط', 'URL')), b.columns[0])
                paths = {_path(u) for u in b[url_col]}
                sub = red[red[from_col].map(_path).isin(paths)]
                if not sub.empty:
                    p['zid_redirects'] = sub.reset_index(drop=True)
    return [p for p in phases if p] or [dict()]


def _path(u):
    from urllib.parse import urlparse, unquote
    u = unquote(str(u or ''))
    return (urlparse(u).path if u.startswith('http') else u).rstrip('/').lower()


def phase_counts(phase):
    def ln(t):
        v = phase.get(t)
        return 0 if v is None else len(v)
    return {'titles': ln('titles'), 'descs': ln('descs'), 'images': ln('alt_missing') + ln('alt_weak'),
            'broken': ln('broken')}


def phase_summary(phase, platform):
    """ملخص بصيغة عرض السعر، لتُبنى فاتورة المرحلة بنفس قواعد الأسعار."""
    c = phase_counts(phase)
    return {'fix_titles_urls': c['titles'], 'fix_descs': c['descs'], 'missing_alts': c['images'],
            'weak_alts': 0, 'broken_actionable': c['broken'], 'platform': platform,
            'bad_titles': c['titles'], 'bad_descs': c['descs']}


def task_file(phase, phase_no, total):
    """ملف مهام المرحلة: نفس ملفات التصدير بكل أعمدتها، كل ملف في ورقة، مرقّمة من 1 داخل المرحلة."""
    from export_utils import write_chunked
    buf = io.BytesIO()
    c = phase_counts(phase)
    with pd.ExcelWriter(buf, engine='openpyxl') as w:
        pd.DataFrame([{'المرحلة': f"{phase_no} من {total}", 'عناوين': c['titles'], 'أوصاف': c['descs'],
                       'صور': c['images'], 'روابط معطلة': c['broken']}]).to_excel(
            w, index=False, sheet_name='ملخص المرحلة')
        for key in ('titles', 'descs', 'alt_missing', 'alt_weak', 'broken', 'zid_redirects'):
            t = phase.get(key)
            if t is None or t.empty:
                continue
            t = t.copy()
            num_col = next((col for col in t.columns if str(col) in ('م', '#')), None)
            if num_col is not None:
                t[num_col] = range(1, len(t) + 1)
            write_chunked(w, t, SHEET_NAMES[key])       # كل 500 صف في ورقة
    return buf.getvalue()


# ---------- ترقيم ثابت للطلبات ----------
def order_number(db_file, store_url):
    """رقم طلب ثابت لكل متجر: يُنشأ مرة واحدة ويبقى نفسه في كل الفواتير (1001، 1002، ...)."""
    key = (store_url or '').strip().lower().rstrip('/')
    conn = sqlite3.connect(db_file)
    try:
        conn.execute('CREATE TABLE IF NOT EXISTS orders (store TEXT PRIMARY KEY, number INTEGER, created TEXT)')
        row = conn.execute('SELECT number FROM orders WHERE store = ?', (key,)).fetchone()
        if row:
            return int(row[0])
        last = conn.execute('SELECT MAX(number) FROM orders').fetchone()[0]
        num = int(last or 1000) + 1
        conn.execute('INSERT INTO orders VALUES (?, ?, ?)', (key, num, datetime.now().isoformat()))
        conn.commit()
        return num
    finally:
        conn.close()


def phase_title(i, n, lang='ar'):
    if lang == 'ar':
        if n == 1:
            return 'فاتورة'
        return f"فاتورة - المرحلة {ORDINAL_AR[i] if i < len(ORDINAL_AR) else i + 1} ({i + 1} من {n})"
    return 'Invoice' if n == 1 else f"Invoice - Phase {i + 1} of {n}"


def phase_name(i, n, lang='ar'):
    if n == 1:
        return 'المشروع كاملاً' if lang == 'ar' else 'the full project'
    return (f"المرحلة {ORDINAL_AR[i] if i < len(ORDINAL_AR) else i + 1}" if lang == 'ar' else f"Phase {i + 1}")


# ---------- رسالة واتساب جاهزة ----------
def whatsapp_message(client_name, store, phase, i, n, number, total, iban, bank, signer='أنس راشد'):
    c = phase_counts(phase)
    lines_ = []
    if c['titles']:
        lines_.append(f"• كتابة عناوين الميتا وتحديث الروابط: {c['titles']:,}")
    if c['descs']:
        lines_.append(f"• كتابة أوصاف الميتا: {c['descs']:,}")
    if c['images']:
        lines_.append(f"• كتابة النصوص البديلة للصور: {c['images']:,}")
    if c['broken']:
        lines_.append(f"• معالجة الروابط التي لا تعمل: {c['broken']:,}")
    hello = f"السلام عليكم {client_name}،" if client_name else "السلام عليكم،"
    what = (f"مرفق لكم فاتورة {phase_name(i, n)} ({i + 1} من {n}) لتحسين ظهور متجركم {store} في محركات البحث."
            if n > 1 else f"مرفق لكم فاتورة تحسين ظهور متجركم {store} في محركات البحث.")
    total_txt = f"{total:,.0f}"
    msg = f"""{hello}

{what}

تشمل هذه {'المرحلة' if n > 1 else 'الفاتورة'}:
{chr(10).join(lines_)}

المبلغ المستحق: {total_txt} ريال
رقم الفاتورة: {number}

بيانات التحويل:
الآيبان (البنك الأهلي السعودي): {iban}
STC Bank: 0553541890

يبدأ العمل فور التحويل، وبعد التسليم لديكم 3 أيام عمل لإبداء أي ملاحظات.

شاكر لكم ثقتكم،
{signer}"""
    return msg


def fix_counts(text):
    """مطابقة العدد والمعدود: 3 عناوين، 15 عنواناً..."""
    try:
        from pdf_generator import ar_counts
        return ar_counts(text)
    except Exception:
        return text
