from pathlib import Path
from datetime import datetime
from fpdf import FPDF
import arabic_reshaper
from bidi.algorithm import get_display

BASE_DIR = Path(__file__).parent
FONT_CANDIDATES = [
    ("Tajawal", "Tajawal-Regular.ttf", "Tajawal-Bold.ttf"),
    ("Almarai", "Almarai-Regular.ttf", "Almarai-Bold.ttf"),
    ("Cairo", "Cairo-Regular.ttf", "Cairo-Bold.ttf"),
    ("Amiri", "Amiri-Regular.ttf", "Amiri-Bold.ttf"),
]

def pick_font():
    for name, reg, bold in FONT_CANDIDATES:
        rp = BASE_DIR / reg
        if rp.exists() and rp.stat().st_size > 10000:
            bp = BASE_DIR / bold
            has_b = bp.exists() and bp.stat().st_size > 10000
            return name, rp, (bp if has_b else rp)
    amiri = BASE_DIR / "Amiri-Regular.ttf"
    if amiri.exists(): return "Amiri", amiri, amiri
    return "Helvetica", None, None

AR_FONT_NAME, FONT_PATH, FONT_BOLD_PATH = pick_font()
LOGO_PATH = BASE_DIR / "brand_logo.png"
RIYAL_PATH = BASE_DIR / "Saudi_Riyal_Symbol-1.png"

C_INK = (15, 23, 42)
C_MUTED = (100, 116, 139)
C_LINE = (226, 232, 240)
C_BG = (248, 250, 252)
C_OK = (5, 150, 105)
C_WARN = (217, 119, 6)
C_BAD = (220, 38, 38)
STATUS_RGB = {'ok': C_OK, 'warn': C_WARN, 'bad': C_BAD, 'neutral': C_MUTED}

def shape_ar(text):
    if not text: return ""
    try: return get_display(arabic_reshaper.reshape(str(text)))
    except Exception: return str(text)

def setup_pdf_fonts(pdf, rtl):
    has_font = rtl and (FONT_PATH is not None) and FONT_PATH.exists()
    font_family = AR_FONT_NAME if has_font else "Helvetica"
    has_bold = False
    if has_font:
        pdf.add_font(font_family, "", str(FONT_PATH))
        bold_path = str(FONT_BOLD_PATH) if (FONT_BOLD_PATH and FONT_BOLD_PATH.exists()) else str(FONT_PATH)
        pdf.add_font(font_family, "B", bold_path)
        has_bold = True
    return font_family, has_font, has_bold

def generate_client_pdf(domain, score, summary, coverage, lang='ar'):
    rtl = (lang == 'ar')
    fmt = shape_ar if rtl else str
    pdf = FPDF()
    font_family, has_font, has_bold = setup_pdf_fonts(pdf, rtl)
    M, W = 18, 174
    verdict_rgb = C_BAD if score < 60 else (C_WARN if score < 80 else C_OK)

    pdf.add_page()
    if LOGO_PATH.exists():
        try: pdf.image(str(LOGO_PATH), x=(210 - 40) / 2, y=20, h=14)
        except Exception: pass
    pdf.set_y(44)
    pdf.set_draw_color(*C_LINE)
    pdf.line(M + 40, 42, 210 - M - 40, 42)

    pdf.set_font(font_family, "B" if has_bold else "", 22)
    pdf.set_text_color(*C_INK)
    pdf.cell(0, 12, fmt("تقرير الفحص الفني الشامل للسيو"), ln=True, align="C")
    pdf.set_font(font_family, "", 11)
    pdf.set_text_color(*C_MUTED)
    pdf.cell(0, 6, fmt("تحسين محركات البحث للمتاجر الإلكترونية"), ln=True, align="C")
    pdf.ln(8)

    y = pdf.get_y()
    pdf.set_fill_color(*C_BG)
    pdf.rect(M, y, W, 42, 'F')
    pdf.set_fill_color(*verdict_rgb)
    pdf.rect(M, y, W, 2, 'F')
    pdf.set_font(font_family, "B" if has_bold else "", 38)
    pdf.set_text_color(*verdict_rgb)
    pdf.set_xy(M, y + 6)
    pdf.cell(W, 16, f"{score}%", align="C")
    pdf.set_font(font_family, "", 10.5)
    pdf.set_text_color(*C_INK)
    pdf.set_xy(M, y + 24)
    pdf.cell(W, 6, fmt("درجة التوافق الفعلية مع محركات البحث"), align="C")
    pdf.set_y(y + 50)

    pdf.set_font(font_family, "", 10)
    pdf.set_text_color(*C_INK)
    for lbl, val in [("المتجر المفحوص:", domain),
                     ("المنصة:", summary.get('platform', '—')),
                     ("تاريخ الفحص:", datetime.now().strftime('%Y-%m-%d'))]:
        pdf.set_x(M)
        pdf.cell(W, 6.5, fmt(f"{lbl} {val}"), ln=True, align="R")

    def add_section_table(title, rows):
        pdf.add_page()
        pdf.set_font(font_family, "B" if has_bold else "", 14)
        pdf.set_text_color(*C_INK)
        pdf.cell(W, 8, fmt(title), ln=True, align="R")
        pdf.ln(3)

        pdf.set_fill_color(*C_INK)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font(font_family, "B" if has_bold else "", 9.5)
        pdf.cell(50, 8, fmt("النتيجة"), 0, 0, 'C', fill=True)
        pdf.cell(W - 50, 8, fmt("عنصر الفحص"), 0, 1, 'R', fill=True)

        for idx, (label, val, stt) in enumerate(rows):
            y_row = pdf.get_y()
            if idx % 2 == 0:
                pdf.set_fill_color(*C_BG)
                pdf.rect(M, y_row, W, 7.5, 'F')
            pdf.set_text_color(*STATUS_RGB.get(stt, C_INK))
            pdf.set_font(font_family, "", 9)
            pdf.cell(50, 7.5, fmt(str(val)), 0, 0, 'C')
            pdf.set_text_color(*C_INK)
            pdf.cell(W - 50, 7.5, fmt(label), 0, 1, 'R')

    add_section_table("1. بنية المتجر والصفحات المفحوصة", [
        ("إجمالي الصفحات المعروضة", summary['total_pages'], 'neutral'),
        ("صفحات المنتجات", summary['products'], 'neutral'),
        ("صفحات التصنيفات والأقسام", summary['categories'], 'neutral'),
        ("صفحات المدونة والمقالات", summary['blog_pages'], 'neutral' if summary['blog_pages'] else 'warn'),
        ("الصفحات التعريفية والسياسات", summary['info_pages'], 'neutral'),
        ("روابط معطلة يصل إليها الزائر", summary['broken_pages'], 'bad' if summary['broken_pages'] else 'ok'),
    ])

    add_section_table("2. عناوين وأوصاف الميتا و H1", [
        ("عناوين ميتا مفقودة أو كرموز", summary['missing_titles'], 'bad' if summary['missing_titles'] else 'ok'),
        ("عناوين ميتا مكررة بين الصفحات", summary['duplicate_titles'], 'warn' if summary['duplicate_titles'] else 'ok'),
        ("عناوين ميتا لا تطابق اسم المنتج (H1)", summary['title_mismatch'], 'bad' if summary['title_mismatch'] else 'ok'),
        ("أوصاف ميتا مفقودة تماماً", summary['missing_descs'], 'bad' if summary['missing_descs'] else 'ok'),
        ("أوصاف ميتا قصيرة جداً وغير مقنعة", summary['short_descs'], 'warn' if summary['short_descs'] else 'ok'),
        ("أوصاف ميتا مكررة بين الصفحات", summary['duplicate_descs'], 'warn' if summary['duplicate_descs'] else 'ok'),
    ])

    add_section_table("3. صور المتجر والنصوص البديلة (Alt)", [
        ("إجمالي صور المحتوى والمنتجات", summary['total_images'], 'neutral'),
        ("صور بدون نص بديل إطلاقاً (Alt)", summary['missing_alts'], 'bad' if summary['missing_alts'] else 'ok'),
        ("صور بنصوص بديلة ضعيفة أو غير وصفية", summary['weak_alts'], 'warn' if summary['weak_alts'] else 'ok'),
    ])

    add_section_table("4. مطابقة المعروض مع خريطة الموقع (Sitemap)", [
        ("روابط معلنة في خريطة الموقع", coverage.get('sitemap_count', 0), 'neutral'),
        ("صفحات معروضة وغير مدرجة بالخريطة", len(coverage.get('unlisted_pages', [])), 'bad' if coverage.get('unlisted_pages') else 'ok'),
        ("صفحات يتيمة (بالخريطة ولا تظهر بالمتجر)", len(coverage.get('orphan_pages', [])), 'warn' if coverage.get('orphan_pages') else 'ok'),
        ("روابط معطلة ما زالت مدرجة بالخريطة", len(coverage.get('dead_pages', [])), 'bad' if coverage.get('dead_pages') else 'ok'),
    ])

    pdf.add_page()
    pdf.set_font(font_family, "B" if has_bold else "", 14)
    pdf.set_text_color(*C_INK)
    pdf.cell(W, 8, fmt("5. خطة العمل وأولويات الإصلاح"), ln=True, align="R")
    pdf.ln(3)

    bullets = []
    if summary['missing_titles'] or summary['title_mismatch']:
        bullets.append("إعادة كتابة وتخصيص عناوين الميتا بما يطابق أسماء المنتجات الفعلية (H1) واستبدال الرموز.")
    if summary['missing_descs'] or summary['short_descs']:
        bullets.append("كتابة أوصاف ميتا تسويقية فريدة وجذابة لكل منتج بطول مثالي (120-150 حرفاً).")
    if summary['missing_alts'] or summary['weak_alts']:
        bullets.append(f"إضافة نصوص بديلة (Alt Text) وصفية لـ {summary['missing_alts'] + summary['weak_alts']} صورة لضمان ظهورها في بحث صور جوجل.")
    if coverage.get('unlisted_pages'):
        bullets.append(f"تحديث خريطة الموقع (Sitemap) لتشمل {len(coverage['unlisted_pages'])} صفحة معروضة حالياً بدون فهرسة.")
    if not bullets:
        bullets.append("المتجر بحالة فنية ممتازة وتتوافق معاييره مع أفضل ممارسات محركات البحث.")

    pdf.set_font(font_family, "", 9.5)
    pdf.set_text_color(*C_MUTED)
    for b in bullets:
        pdf.set_x(M)
        pdf.cell(W, 6, fmt(f"• {b}"), ln=True, align="R")

    return bytes(pdf.output())

def generate_invoice_pdf(domain, quote, lang='ar'):
    rtl = (lang == 'ar')
    fmt = shape_ar if rtl else str
    pdf = FPDF()
    font_family, has_font, has_bold = setup_pdf_fonts(pdf, rtl)
    pdf.add_page()
    M, W = 18, 174

    def print_price(val, x, y, size=10, bold=False):
        num_str = f"{val:,.0f}"
        pdf.set_font(font_family, "B" if (has_font and bold) else "", size)
        pdf.set_text_color(15, 23, 42)
        nw = pdf.get_string_width(num_str)
        sym_h = size * 0.32
        sym_w = sym_h * 0.95
        gap = 1.5

        if RIYAL_PATH.exists():
            try: pdf.image(str(RIYAL_PATH), x=x, y=y + 0.8, h=sym_h)
            except Exception: pass
            pdf.set_xy(x + sym_w + gap, y)
            pdf.cell(nw, 6, num_str, 0, 0, 'L')
        else:
            pdf.set_xy(x, y)
            pdf.cell(nw, 6, num_str, 0, 0, 'L')
            pdf.set_xy(x + nw + gap, y)
            pdf.cell(10, 6, fmt("ر.س"), 0, 0, 'L')

    pdf.set_font(font_family, "B" if has_font else "", 18)
    pdf.set_text_color(15, 23, 42)
    pdf.set_xy(M, 18)
    pdf.cell(W, 8, fmt("عرض سعر وتهيئة السيو"), 0, 1, 'R')
    pdf.set_font(font_family, "", 9.5)
    pdf.set_text_color(100, 116, 139)
    pdf.cell(W, 5, fmt(f"المتجر: {domain}  ·  التاريخ: {datetime.now().strftime('%Y-%m-%d')}"), 0, 1, 'R')
    pdf.ln(8)

    pdf.set_fill_color(15, 23, 42)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font(font_family, "B" if has_font else "", 9.5)
    pdf.cell(35, 8, fmt("المبلغ"), 0, 0, 'C', fill=True)
    pdf.cell(30, 8, fmt("سعر الوحدة"), 0, 0, 'C', fill=True)
    pdf.cell(25, 8, fmt("الكمية"), 0, 0, 'C', fill=True)
    pdf.cell(W - 90, 8, fmt("الخدمة"), 0, 1, 'R', fill=True)

    pdf.set_font(font_family, "", 9)
    pdf.set_text_color(15, 23, 42)
    for idx, item in enumerate(quote['items']):
        y = pdf.get_y()
        if idx % 2 == 0:
            pdf.set_fill_color(248, 250, 252)
            pdf.rect(M, y, W, 8, 'F')
        print_price(item['total'], M + 5, y + 1, 9, True)
        print_price(item['unit'], M + 38, y + 1, 9, False)
        pdf.set_xy(M + 65, y + 1)
        pdf.cell(25, 6, str(item['qty']), 0, 0, 'C')
        pdf.set_xy(M + 90, y + 1)
        pdf.cell(W - 90, 6, fmt(item['name']), 0, 1, 'R')
        pdf.set_y(y + 8)

    pdf.ln(5)
    y_tot = pdf.get_y()
    pdf.set_font(font_family, "B" if has_font else "", 12)
    pdf.set_text_color(15, 23, 42)
    pdf.set_xy(M + 80, y_tot)
    pdf.cell(50, 8, fmt("الإجمالي المستحق:"), 0, 0, 'R')
    print_price(quote['total'], M + 135, y_tot + 1, 12, True)

    return bytes(pdf.output())
