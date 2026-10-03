"""المراحل والفواتير: تقسيم المشروع إلى مراحل، لكل مرحلة ملف مهام وفاتورة ورسالة واتساب.

مستقل عن محرك الفحص: يأخذ ملفات العمل الجاهزة (المرتبة بالأولوية) ويقسمها.
"""
import io
import sqlite3
from datetime import datetime

import pandas as pd

# ترتيب الخدمات في المراحل عند التقسيم حسب النوع، ومفتاح كل خدمة في عرض السعر
SERVICES = [
    ('titles', 'meta_title', 'عناوين الميتا والروابط', 'Meta titles & URLs'),
    ('descs', 'meta_desc', 'أوصاف الميتا', 'Meta descriptions'),
    ('images', 'image_alt', 'النصوص البديلة للصور', 'Image alt texts'),
    ('broken', 'broken_link_fix', 'الروابط المعطلة', 'Broken links'),
]
ORDINAL_AR = ['الأولى', 'الثانية', 'الثالثة', 'الرابعة', 'الخامسة']


def work_tables(exports):
    """من ملفات العمل الجاهزة: العناوين، والأوصاف، والصور (بلا وصف + ضعيفة)، والروابط التي تحتاج عملاً."""
    def get(k):
        v = exports.get(k)
        return v[1].copy() if v else pd.DataFrame()
    images = pd.concat([get('alt_missing'), get('alt_weak')], ignore_index=True)
    broken = get('broken')
    if not broken.empty:
        act = next((c for c in broken.columns if 'الإجراء' in str(c) or 'Action' in str(c)), None)
        if act:
            broken = broken[~broken[act].astype(str).str.contains('لا إجراء|No action', na=False)]
    return {'titles': get('titles'), 'descs': get('descs'), 'images': images,
            'broken': broken.reset_index(drop=True)}


def _chunks(df, n):
    """تقسيم بالتساوي مع الحفاظ على الترتيب (الأهم أولاً): 81 على مرحلتين = 41 ثم 40."""
    size, extra = divmod(len(df), n)
    out, start = [], 0
    for i in range(n):
        end = start + size + (1 if i < extra else 0)
        out.append(df.iloc[start:end].reset_index(drop=True))
        start = end
    return out


def split_phases(tables, n, mode='priority'):
    """يعيد قائمة مراحل، كل مرحلة {الخدمة: جدول}.
    priority: كل خدمة تُقسم على المراحل والأهم في المرحلة الأولى.
    type: كل خدمة كاملة في مرحلة واحدة (العناوين أولاً، ثم الأوصاف، ثم الصور)."""
    n = max(1, int(n))
    phases = [dict() for _ in range(n)]
    if mode == 'type':
        active = [k for k, *_ in SERVICES if not tables.get(k, pd.DataFrame()).empty]
        # الروابط المعطلة تُرافق أول مرحلة (عمل صغير وعاجل)
        main = [k for k in active if k != 'broken']
        n_eff = min(n, max(1, len(main)))
        # مجموعات متتالية: مرحلتان = (العناوين + الأوصاف) ثم (الصور)
        size, extra = divmod(len(main), n_eff)
        groups, start = [], 0
        for i in range(n_eff):
            end = start + size + (1 if i < n_eff - extra else 0) if extra else start + size
            groups.append(main[start:end])
            start = end
        if start < len(main):
            groups[-1].extend(main[start:])
        for i, g in enumerate(groups):
            for k in g:
                phases[i][k] = tables[k]
        if 'broken' in active:
            phases[0]['broken'] = tables['broken']
        return [p for p in phases if p] or [dict()]
    for k, *_ in SERVICES:
        t = tables.get(k, pd.DataFrame())
        if t is None or t.empty:
            continue
        for i, part in enumerate(_chunks(t, n)):
            if not part.empty:
                phases[i][k] = part
    return [p for p in phases if p] or [dict()]


def phase_counts(phase):
    return {k: len(phase.get(k, pd.DataFrame())) for k, *_ in SERVICES}


def phase_summary(phase, platform):
    """ملخص بصيغة عرض السعر، لتُبنى فاتورة المرحلة بنفس قواعد الأسعار."""
    c = phase_counts(phase)
    return {'fix_titles_urls': c['titles'], 'fix_descs': c['descs'], 'missing_alts': c['images'],
            'weak_alts': 0, 'broken_actionable': c['broken'], 'platform': platform,
            'bad_titles': c['titles'], 'bad_descs': c['descs']}


def task_file(phase, phase_no, total):
    """ملف مهام المرحلة: ورقة لكل خدمة."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as w:
        info = pd.DataFrame([{'المرحلة': f"{phase_no} من {total}",
                              **{name: len(phase.get(k, pd.DataFrame())) for k, _, name, _ in SERVICES}}])
        info.to_excel(w, index=False, sheet_name='ملخص المرحلة')
        for k, _, name, _ in SERVICES:
            t = phase.get(k)
            if t is not None and not t.empty:
                t.to_excel(w, index=False, sheet_name=name[:31])
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
{bank}
الآيبان: {iban}

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
