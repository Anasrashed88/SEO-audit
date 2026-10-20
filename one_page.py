"""تحليل مختصر من صفحة واحدة — للمواقع خارج زد وسلة وشوبيفاي (ووردبريس وغيرها)."""
import sys
sys.path.insert(0, '/home/claude/work')
from fpdf import FPDF
import pdf_generator as g

INK, ACC, MUTED, BG, LINE = g.C_INK, g.C_ACC, g.C_MUTED, g.C_BG, g.C_LINE
OK, WARN, BAD = (22, 163, 74), (217, 119, 6), (220, 38, 38)
M, W = 14, 182


def build(out_path, d):
    pdf = FPDF()
    pdf.add_font('T', '', str(g.FONT_PATH))
    pdf.set_text_shaping(True, direction='rtl')
    pdf.set_auto_page_break(False)
    pdf.add_page()
    F = 'T'

    def txt(x, y, w, h, s, size=9.5, color=INK, align='R'):
        pdf.set_font(F, '', size)
        pdf.set_text_color(*color)
        pdf.set_xy(x, y)
        pdf.cell(w, h, s, align=align)

    def wrap(x, y, w, s, size=9, color=INK, lh=4.6):
        pdf.set_font(F, '', size)
        pdf.set_text_color(*color)
        lines = pdf.multi_cell(w, lh, s, align='R', dry_run=True, output='LINES')
        for i, ln in enumerate(lines):
            pdf.set_xy(x, y + i * lh)
            pdf.cell(w, lh, ln, align='R')
        return y + len(lines) * lh

    # الترويسة
    pdf.set_fill_color(*INK)
    pdf.rect(0, 0, 210, 34, 'F')
    pdf.set_fill_color(*ACC)
    pdf.rect(0, 34, 210, 1.4, 'F')
    pdf.set_fill_color(255, 255, 255)
    pdf.rect(M, 8, 36, 17, 'F', round_corners=True, corner_radius=3)
    g.logo_centered(pdf, M, 8, 36, 17, 11)
    txt(M + 40, 8, W - 40, 9, 'تحليل مختصر لسيو الموقع', 17, (255, 255, 255))
    txt(M + 40, 18, W - 40, 6, f"{d['domain']}  ·  {d['platform']}  ·  {d['date']}", 9.5, (203, 213, 225))

    # بطاقات الأرقام
    y = 41
    cards = d['kpis']
    cw = (W - 3 * 3) / 4
    for i, (val, lbl, col) in enumerate(reversed(cards)):
        x = M + i * (cw + 3)
        pdf.set_fill_color(*BG)
        pdf.rect(x, y, cw, 17, 'F', round_corners=True, corner_radius=2.5)
        txt(x, y + 2.5, cw, 7, val, 14, col, 'C')
        txt(x, y + 10, cw, 5, lbl, 7.8, MUTED, 'C')
    y += 22

    # نقاط القوة
    txt(M, y, W, 6, 'نقاط القوة', 11.5, OK)
    y += 7
    for s in d['strengths']:
        pdf.set_fill_color(*OK)
        pdf.ellipse(210 - M - 2.2, y + 1.6, 1.6, 1.6, 'F')
        y = wrap(M, y, W - 5, s, 8.8) + 0.6
    y += 2.5

    # أهم المشاكل
    txt(M, y, W, 6, 'أهم ما يحتاج إصلاحاً (حسب الأثر)', 11.5, BAD)
    y += 7.5
    for k, (head, body, col) in enumerate(d['issues'], 1):
        pdf.set_font(F, '', 8.4)
        lines = pdf.multi_cell(W - 12, 4.4, body, align='R', dry_run=True, output='LINES') if body else []
        h = 6.5 + len(lines) * 4.4 + 2
        pdf.set_fill_color(*(BG if k % 2 else (255, 255, 255)))
        pdf.rect(M, y, W, h, 'F', round_corners=True, corner_radius=2)
        pdf.set_fill_color(*col)
        pdf.ellipse(210 - M - 8, y + 1.6, 5.5, 5.5, 'F')
        txt(210 - M - 8, y + 1.6, 5.5, 5.5, str(k), 8, (255, 255, 255), 'C')
        txt(M + 2, y + 1.3, W - 12, 6, head, 9.6, INK)
        wrap(M + 2, y + 7, W - 12, body, 8.4, MUTED, 4.4)
        y += h + 1.6
    y += 1.5

    # التوصية
    pdf.set_fill_color(*INK)
    pdf.set_font(F, '', 9)
    lines = pdf.multi_cell(W - 12, 4.8, d['summary'], align='R', dry_run=True, output='LINES')
    h = 9 + len(lines) * 4.8
    pdf.rect(M, y, W, h, 'F', round_corners=True, corner_radius=3)
    pdf.set_fill_color(*ACC)
    pdf.rect(210 - M - 3, y + 3, 3, h - 6, 'F', round_corners=True, corner_radius=1.5)
    txt(M + 4, y + 2.5, W - 12, 5, 'الخلاصة', 10, (94, 234, 212))
    wrap(M + 4, y + 8, W - 12, d['summary'], 9, (255, 255, 255), 4.8)

    # التذييل
    pdf.set_draw_color(*LINE)
    pdf.line(M, 285, 210 - M, 285)
    if g.SETTINGS.get('show_contact', True):
        txt(M, 287, W, 5, 'anasrashed.com   |   anas@anasrashed.com', 8, MUTED, 'C')
    pdf.output(out_path)
    return pdf.page_no()


MADAREJ = {
    'domain': 'madarej.sa', 'platform': 'ووردبريس', 'date': '2026-10-19',
    'kpis': [('367', 'صفحة تعمل', INK), ('334', 'مقالة', INK), ('79.6%', 'متوسط درجة السيو', WARN),
             ('266', 'عنواناً طويلاً', BAD)],
    'strengths': [
        'المحتوى قوي: 334 مقالة، ونصف المقالات أطول من 1,000 كلمة، وهذا من أهم ما يبحث عنه جوجل.',
        'كل الصفحات قابلة للأرشفة، والرابط الأساسي (Canonical) سليم في كل الصفحات، والعنوان الرئيسي (H1) يطابق عنوان الصفحة في 361 صفحة من 367.',
        'كل الصور لها نص بديل، ولا صفحات بمحتوى ضعيف.',
    ],
    'issues': [
        ('عناوين طويلة تُقطع في نتائج جوجل: 266 صفحة (72%)',
         'متوسط طول العنوان 79 حرفاً، والمثالي 50–60. والسبب الرئيسي: عبارة « - مدارج لحلول الأعمال» (21 حرفاً) تُضاف لكل عنوان، '
         'فتُقطع العناوين الطويلة ولا يرى الباحث نهايتها. الحل: اختصار العبارة (مثل «| مدارج») وإعادة صياغة عناوين المقالات الطويلة.', BAD),
        ('أوصاف ميتا مفقودة: 40 صفحة',
         '22 مقالة و17 صفحة تصنيف بلا وصف، فيختار جوجل نصاً عشوائياً من الصفحة. وهناك 40 وصفاً أطول من الحد.', BAD),
        ('عناوين مكررة: 14 صفحة',
         'مثل «دراسة الجدوى - مدارج لحلول الأعمال» على 3 صفحات، فتتنافس الصفحات مع بعضها في نفس البحث.', WARN),
        ('روابط تحتاج تنظيفاً: 36 رابطاً',
         '6 روابط فيها رموز تعبيرية (مثل علم السعودية)، و18 رابطاً أرقام أو رموز بلا كلمات، و9 روابط لصفحات مستنسخة. والإصلاح بتحويل 301 لكل رابط يتغير.', WARN),
        ('صفحات لا ينبغي أن تظهر في جوجل',
         '5 صفحات إتمام الطلب (/إنهاء-الطلب/...) وتصنيف «غير مصنف» مفتوحة للأرشفة، وتستهلك اهتمام جوجل دون فائدة.', WARN),
        ('رابط معطل، وصفحات معزولة',
         'رابط البريد كُتب رابطاً عادياً (/Info@madarej.sa) فيعطي خطأ 404، والصحيح «mailto:». و10 صفحات لا يصلها أي رابط داخلي، و15 خارج خريطة الموقع.', WARN),
    ],
    'summary': 'أساس الموقع قوي: محتوى غني وإعدادات أرشفة سليمة. والفرصة الأكبر في العناوين: إصلاح 266 عنواناً طويلاً و40 وصفاً مفقوداً '
               'يحسّن مظهر الموقع في نتائج البحث ونسبة النقر عليه مباشرة، دون الحاجة لكتابة محتوى جديد.',
}

if __name__ == '__main__':
    print('pages:', build('/mnt/user-data/outputs/تحليل_مختصر_madarej_sa.pdf', MADAREJ))
