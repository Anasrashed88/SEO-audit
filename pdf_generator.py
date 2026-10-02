"""مولّد تقرير العميل وعرض السعر بصيغة PDF."""
import re
from datetime import datetime
from urllib.parse import urlparse, unquote

from fpdf import FPDF
import arabic_reshaper
from bidi.algorithm import get_display

from audit_engine import (
    AR_FONT_NAME, FONT_PATH, FONT_BOLD_PATH, HAS_SHAPING, LOGO_PATH,
    RIYAL_PATH, PAGE_TYPE_LABEL, TITLE_MAX, TITLE_MIN_OPTIMAL, TITLE_MIN_OK,
    DESC_MAX, DESC_MIN_OPTIMAL, DESC_MIN_OK,
)

#  تقرير العميل (PDF)
# ==============================================================
PDF_TXT = {
    'ar': {
        'owner': 'أنس راشد', 'role': 'خبير تحسين محركات البحث',
        'title': 'تقرير الفحص الفني الشامل',
        'subtitle': 'تحسين محركات البحث للمتاجر الإلكترونية',
        'prepared': 'أُعدّ التقرير بواسطة أنس راشد — خبير تحسين محركات البحث',
        'store': 'المتجر', 'date': 'تاريخ الفحص', 'platform': 'المنصة',
        'scope': 'نطاق الفحص: الصفحات والمنتجات المعروضة فعلياً لزوار المتجر',
        'score_lbl': 'درجة التوافق العامة مع محركات البحث',
        'sc_bad': 'يحتاج معالجة عاجلة', 'sc_warn': 'مهيأ جزئياً', 'sc_ok': 'مستوى جيد',
        'page_of': 'صفحة {a}',
        'impact': 'الأثر على متجرك',
        'h_item': 'عنصر الفحص', 'h_val': 'النتيجة',
        'm_pages': 'صفحة معروضة', 'm_products': 'منتج', 'm_images': 'صورة',
        'm_issues': 'بند يحتاج معالجة', 'm_cats': 'قسم',
        'u_page': 'صفحة', 'u_product': 'منتج', 'u_cat': 'تصنيف', 'u_article': 'مقال',
        'h_url': 'الرابط', 'h_where': 'الإجراء', 'h_code': 'الكود',
        'w_redirect': 'تحويل 301', 'w_fix': 'تصحيح رابط داخلي', 'w_both': 'تحويل + تصحيح',
        'more_links': 'و{n} رابط آخر في ملف «روابط لا تعمل» ضمن حزمة البيانات.',
        'u_link': 'رابط', 'u_title': 'عنوان', 'u_desc': 'وصف', 'u_img': 'صورة',
        'na': 'غير متاح',
    },
    'en': {
        'owner': 'Anas Rashed', 'role': 'SEO Expert',
        'title': 'Comprehensive Technical SEO Audit',
        'subtitle': 'Search engine optimisation for e-commerce stores',
        'prepared': 'Prepared by Anas Rashed - SEO Expert',
        'store': 'Store', 'date': 'Audit date', 'platform': 'Platform',
        'scope': 'Audit scope: pages and products actually visible to store visitors',
        'score_lbl': 'Overall search engine compliance score',
        'sc_bad': 'Needs urgent work', 'sc_warn': 'Partially optimised',
        'sc_ok': 'Good standard',
        'page_of': 'Page {a}',
        'impact': 'What this means for your store',
        'h_item': 'Audited item', 'h_val': 'Result',
        'm_pages': 'visible pages', 'm_products': 'products', 'm_images': 'images',
        'm_issues': 'items to fix', 'm_cats': 'categories',
        'u_page': 'pages', 'u_product': 'products', 'u_cat': 'categories',
        'h_url': 'URL', 'h_where': 'Action', 'h_code': 'Code',
        'w_redirect': '301 redirect', 'w_fix': 'Fix internal link', 'w_both': 'Redirect + fix',
        'more_links': 'Plus {n} more in the "Broken Links" file of the data package.',
        'u_article': 'articles', 'u_link': 'links', 'u_title': 'titles',
        'u_desc': 'descriptions', 'u_img': 'images', 'na': 'not available',
    },
}

SECTION_TXT = {
    'ar': {
        'structure': {
            'title': 'بنية المتجر ونطاق الفحص',
            'intro': 'يجمع الفحص صفحات المتجر من خريطة الموقع ومن الروابط التي يتنقل بها '
                     'الزائر داخل المتجر، ثم يفحص كل صفحة كما تراها محركات البحث.',
            'impact': 'هذه الأرقام هي ما تراه محركات البحث فعلياً عند زحفها للمتجر. أي '
                      'رابط معطل يصل إليه الزائر يهدر جزءاً من ميزانية الزحف المخصصة '
                      'للمتجر، ويقلل فرص أرشفة الصفحات المهمة.',
        },
        'meta': {
            'title': 'عناوين وأوصاف الميتا',
            'intro': 'عنوان الميتا هو السطر الأزرق القابل للنقر في نتائج البحث، والوصف '
                     'هو السطران تحته. المعيار المعتمد: العنوان بين 50 و60 حرفاً، والوصف '
                     'بين 120 و160 حرفاً، ويُحسب الطول بالحروف شاملاً المسافات وعلامات '
                     'الترقيم كما تحسبها محركات البحث.',
            'impact': 'العنوان القصير جداً يضيّع مساحة مجانية في نتيجة البحث، والطويل '
                      'يُقتطع بثلاث نقاط فتضيع نهايته. أما العنوان المفقود أو المكوّن من '
                      'رموز فيجعل جوجل يختار نصاً عشوائياً من الصفحة بدلاً عنه، وغالباً '
                      'ما يكون نصاً لا يشجع على النقر.',
        },
        'urls': {
            'title': 'روابط صفحات المتجر',
            'intro': 'الرابط عنصر سيو مستقل: تقرأه محركات البحث، ويظهر للزبون في نتيجة '
                     'البحث وعند مشاركة المنتج. يفحص هذا القسم صياغة الرابط ومطابقته '
                     'للمنتج المعروض، ووجود نسخ مكررة من منتج واحد.',
            'impact': 'المنتجات المستنسخة تُنشئ صفحات متطابقة تتنافس فيما بينها، فيوزّع '
                      'جوجل قوة الصفحة بين النسخ ثم يختار واحدة ويتجاهل الباقي. والرابط '
                      'الذي يحمل اسم منتج مختلف يربك الزبون: ينقر على شيء ويصل إلى آخر، '
                      'فترتفع نسبة المغادرة الفورية.',
        },
        'images': {
            'title': 'صور المتجر ونصوصها البديلة',
            'intro': 'النص البديل هو الوصف المرفق بالصورة في كود الصفحة. محركات البحث '
                     'لا ترى الصورة، بل تقرأ هذا النص. ولا يدخل هذا القسم شعار المتجر وصور '
                     'القالب المتكررة في كل الصفحات.',
            'impact': 'بحث صور جوجل مصدر زيارات مهم في المتاجر البصرية كالأزياء والعطور '
                      'والهدايا، حيث يبحث الزبون بالصورة قبل الكلمة. الصورة بلا نص بديل '
                      'غير موجودة بالنسبة لجوجل.',
        },
        'sitemap': {
            'title': 'صفحات الخريطة والروابط الداخلية',
            'intro': 'خريطة الموقع هي القائمة التي يعلنها المتجر لمحركات البحث. يتحقق هذا '
                     'القسم من أن كل صفحة فيها يصل إليها الزائر برابط من داخل المتجر.',
            'impact': 'الصفحة المدرجة في الخريطة ولا يصل إليها الزائر بأي رابط داخلي تبقى بلا '
                      'قيمة: لا تستفيد من قوة المتجر ولا تجلب زيارات. ربطها من صفحات المتجر '
                      'يعيد لها قيمتها.',
        },
        'broken': {
            'title': 'روابط لا تعمل: تحويلها وتصحيحها',
            'intro': 'روابط ترد بأن الصفحة غير موجودة (خطأ 404). تعرض القائمة فقط الروابط '
                     'التي سنعالجها: تحويل 301 لما له بديل قريب في المتجر، وتصحيح الروابط '
                     'الداخلية التي تقود الزائر إليها.',
            'impact': 'الزائر الذي يصل إلى صفحة غير موجودة يغادر غالباً دون شراء. تحويل 301 '
                      'إلى أقرب صفحة بديلة يعيده إلى مسار الشراء ويحفظ قيمة الرابط في نتائج '
                      'البحث، وتصحيح الرابط الداخلي يمنع وصوله إلى الخطأ من الأساس.',
        },
        'broken_internal': {
            'title': 'روابط داخلية لا تعمل',
            'intro': 'روابط داخل صفحات المتجر تقود الزائر إلى صفحة غير موجودة (خطأ 404). '
                     'سنصحح كل رابط منها ليشير إلى الصفحة المناسبة.',
            'impact': 'الزائر الذي يضغط رابطاً فيجد صفحة غير موجودة يفقد الثقة ويغادر '
                      'غالباً دون شراء. تصحيح الرابط يعيده إلى مسار الشراء مباشرة.',
        },
        'diagnosis': {
            'title': 'التشخيص وخطة العمل',
            'intro': 'ملخص ما رصده الفحص، مرتباً حسب أثره على الظهور في نتائج البحث.',
            'impact': '',
        },
    },
    'en': {
        'structure': {
            'title': 'Store structure and audit scope',
            'intro': 'The audit starts at the homepage and browses the store the way a '
                     'visitor does, following internal links and category pages. No page '
                     'a visitor cannot reach by clicking enters this report.',
            'impact': 'These figures reflect what search engines actually encounter when '
                      'crawling the store. Every broken link a visitor can reach wastes '
                      'part of the crawl budget allocated to the store and reduces the '
                      'chance that important pages get indexed.',
        },
        'meta': {
            'title': 'Meta titles and descriptions',
            'intro': 'The meta title is the clickable blue line in search results; the '
                     'description is the two lines beneath it. Standard applied: titles '
                     'between 50 and 60 characters, descriptions between 120 and 160, '
                     'counted in characters including spaces and punctuation.',
            'impact': 'A very short title wastes free space in the result, while an '
                      'overly long one is truncated and loses its ending. A missing title '
                      'or one made of symbols leaves Google to pick arbitrary text from '
                      'the page instead, rarely text that invites a click.',
        },
        'urls': {
            'title': 'Page URLs',
            'intro': 'The URL is an SEO element in its own right: search engines read it, '
                     'and customers see it in results and when a product is shared. This '
                     'section checks URL formatting, its match to the displayed product, '
                     'and cloned copies of a single product.',
            'impact': 'Cloned products create near-identical pages competing with each '
                      'other, splitting page authority before Google picks one and '
                      'ignores the rest. A URL naming a different product confuses the '
                      'customer, who clicks one thing and lands on another, raising '
                      'bounce rate.',
        },
        'images': {
            'title': 'Store images and alt text',
            'intro': 'Alt text is the description attached to an image in the page code. '
                     'Search engines do not see the image; they read this text. This '
                     'section also checks image formats, which affect page weight and '
                     'loading and page weight directly.',
            'impact': 'Google Image search is a meaningful traffic source for visual '
                      'stores such as fashion, fragrance and gifts, where customers search '
                      'by image before words. An image without alt text does not exist to '
                      'Google. Modern formats also cut image weight by about a third at '
                      'the same quality, making pages lighter on mobile.',
        },
        'sitemap': {
            'title': 'Sitemap pages and internal links',
            'intro': 'The sitemap is the list the store declares to search engines. This '
                     'section compares what visitors actually see against what the sitemap '
                     'declares, in both directions.',
            'impact': 'A visible product missing from the sitemap may be unknown to search '
                      'engines. A sitemap page with no internal link path stays worthless: '
                      'it gains no authority and brings no traffic.',
        },
        'broken': {
            'title': 'Broken links: redirects and fixes',
            'intro': 'URLs that return "not found" (404). Only the links we will handle are '
                     'listed: a 301 redirect where a close alternative exists, and a fix for '
                     'internal links that lead visitors to them.',
            'impact': 'A visitor who lands on a missing page usually leaves without buying. '
                      'A 301 to the closest alternative returns them to the purchase path and '
                      'keeps the URL\'s search value; fixing the internal link stops the error '
                      'at its source.',
        },
        'broken_internal': {
            'title': 'Broken internal links',
            'intro': 'Links inside store pages that lead visitors to a missing page (404). '
                     'We will point each one to the right page.',
            'impact': 'A visitor who clicks a link and finds a missing page loses trust and '
                      'usually leaves without buying. Fixing the link returns them straight '
                      'to the purchase path.',
        },
        'diagnosis': {
            'title': 'Diagnosis and action plan',
            'intro': 'A summary of the audit findings, ordered by impact on search '
                     'visibility.',
            'impact': '',
        },
    },
}

C_INK = (15, 23, 42)          # كحلي عميق: الهوية والعناوين
C_MUTED = (100, 116, 139)
C_LINE = (226, 232, 240)
C_BG = (246, 248, 251)
C_SOFT = (238, 242, 247)
C_ACC = (13, 148, 136)         # فيروزي: لمسة الهوية
C_OK = (16, 163, 127)
C_WARN = (234, 150, 32)
C_BAD = (225, 72, 72)
C_NAVY2 = (30, 41, 66)
STATUS_RGB = {'ok': C_OK, 'warn': C_WARN, 'bad': C_BAD, 'neutral': C_MUTED}


def draw_donut(pdf, cx, cy, r, th, parts, bg=None):
    """حلقة بيانية: parts = [(قيمة، لون)] تبدأ من الأعلى باتجاه عقارب الساعة."""
    tot = sum(max(v, 0) for v, _ in parts) or 1
    pdf.set_fill_color(*(bg or C_SOFT))
    pdf.ellipse(cx - r, cy - r, 2 * r, 2 * r, 'F')
    ang = 90.0
    for v, col in parts:
        if v <= 0:
            continue
        sweep = min(359.99, 360.0 * v / tot)
        pdf.set_fill_color(*col)
        pdf.solid_arc(cx - r, cy - r, 2 * r, ang - sweep, ang, style='F')
        ang -= sweep
    pdf.set_fill_color(255, 255, 255)
    pdf.ellipse(cx - r + th, cy - r + th, 2 * (r - th), 2 * (r - th), 'F')


def draw_stack(pdf, x, y, w, h, parts, rtl=False):
    """شريط مكدّس بزوايا دائرية: parts = [(قيمة، لون)]؛ يبدأ من اليمين في العربية."""
    tot = sum(max(v, 0) for v, _ in parts) or 1
    pdf.set_fill_color(*C_SOFT)
    pdf.rect(x, y, w, h, 'F', round_corners=True, corner_radius=h / 2)
    pos = x + w if rtl else x
    for v, col in parts:
        if v <= 0:
            continue
        seg = w * v / tot
        sx = pos - seg if rtl else pos
        pdf.set_fill_color(*col)
        pdf.rect(sx, y, seg, h, 'F', round_corners=seg >= h, corner_radius=min(h / 2, seg / 2))
        pos = sx if rtl else pos + seg


def shape_ar(text):
    return get_display(arabic_reshaper.reshape(str(text)))


def quote_units(stats):
    """مجموع البنود في عرض السعر، ليتطابق الغلاف مع الفاتورة."""
    return (int(stats.get('fix_titles_urls', stats.get('bad_titles', 0)) or 0)
            + int(stats.get('fix_descs', stats.get('bad_descs', 0)) or 0)
            + int(stats.get('missing_alts', 0) or 0) + int(stats.get('weak_alts', 0) or 0)
            + int(stats.get('broken_actionable', 0) or 0))


# ---------- مطابقة العدد والمعدود بالعربية: 3 عناوين، 15 عنواناً، 101 عنوان ----------
AR_COUNT_FORMS = {
    # المفرد: (جمع 3–10، منصوب 11–99)
    'صفحة': ('صفحات', 'صفحة'), 'منتج': ('منتجات', 'منتجاً'), 'عنوان': ('عناوين', 'عنواناً'),
    'وصف': ('أوصاف', 'وصفاً'), 'صورة': ('صور', 'صورة'), 'رابط': ('روابط', 'رابطاً'),
    'مقال': ('مقالات', 'مقالاً'), 'تصنيف': ('تصنيفات', 'تصنيفاً'), 'قسم': ('أقسام', 'قسماً'),
    'بند': ('بنود', 'بنداً'), 'حرف': ('أحرف', 'حرفاً'), 'كلمة': ('كلمات', 'كلمة'),
}
_AR_VARIANTS = {}
for base, (plural, acc) in AR_COUNT_FORMS.items():
    for v in (base, plural, acc):
        _AR_VARIANTS[v] = base
_AR_COUNT_RE = re.compile(r'(?<![\d.,])(\d+)(\s+)(' + '|'.join(
    sorted(map(re.escape, _AR_VARIANTS), key=len, reverse=True)) + r')(?![\u0600-\u06FF])')


def ar_counts(text):
    def fix(m):
        n = int(m.group(1))
        base = _AR_VARIANTS[m.group(3)]
        plural, acc = AR_COUNT_FORMS[base]
        r = n % 100
        word = plural if 3 <= r <= 10 else acc if 11 <= r <= 99 else base
        return f"{m.group(1)}{m.group(2)}{word}"
    return _AR_COUNT_RE.sub(fix, str(text))


def build_diagnosis(score, stats, lang):
    """يُرجع (مقدمة، قائمة نقاط، خلاصة).

    القاعدة: العدد الرئيسي لكل بند هو ما يحتاج إصلاحاً فعلياً، لا كل ما
    يخرج عن المثالي. «مقبول» فرصة تحسين وليس عيباً، فيُذكر منفصلاً.
    """
    imgs = stats.get('total_images', 0)
    missing = stats.get('missing_alts', 0)
    weak = stats.get('weak_alts', 0)
    crit_t = stats.get('critical_titles', 0)
    crit_d = stats.get('critical_descs', 0)
    imp_t = max(stats.get('bad_titles', 0) - crit_t, 0)   # مقبول: قابل للتحسين
    imp_d = max(stats.get('bad_descs', 0) - crit_d, 0)
    points = []

    if lang == 'ar':
        # صيغة «البند: العدد — الأثر» تتجنب أخطاء مطابقة العدد والمعدود والأفعال
        def add(label, n, why=''):
            points.append(f"{label}: {n}" + (f" — {why}" if why else "."))

        if missing and imgs:
            add('صور بلا نص بديل إطلاقاً', f"{missing} من أصل {imgs} ({round(missing / imgs * 100, 1)}%)",
                'لا تظهر في بحث صور جوجل.')
        if weak:
            add('صور نصها البديل غير وصفي أو مكرر', weak, 'لا يضيف قيمة لمحركات البحث.')
        if stats.get('title_symbols'):
            add('عناوين ميتا مكوّنة من رموز أو قيمة قالب افتراضية', stats['title_symbols'],
                'الصفحة بلا عنوان فعلي في نتائج البحث.')
        if stats.get('title_brand_only'):
            add('عناوين هي اسم المتجر فقط', stats['title_brand_only'],
                'تحتاج كلمات تصف تخصص المتجر أو ما يقدمه.')
        if stats.get('title_dup'):
            add('صفحات تتشارك نفس عنوان الميتا', stats['title_dup'],
                'لا تميّز محركات البحث بينها.')
        if stats.get('desc_same'):
            add('أوصاف ميتا منسوخة حرفياً من العنوان', stats['desc_same'],
                'يضيع سطر إضافي مجاني في نتيجة البحث.')
        if crit_t:
            add('عناوين ميتا تحتاج إصلاحاً عاجلاً', crit_t,
                f'مفقودة أو أقصر من {TITLE_MIN_OK} حرفاً، أو أطول من {TITLE_MAX} حرفاً فتُقتطع في نتائج البحث.')
        if imp_t:
            add('عناوين يمكن رفعها إلى الطول المثالي', imp_t,
                f'ضمن الحد المقبول، ورفعها إلى {TITLE_MIN_OPTIMAL}–{TITLE_MAX} حرفاً يستغل المساحة كاملة.')
        if crit_d:
            add('أوصاف ميتا تحتاج إصلاحاً عاجلاً', crit_d,
                f'مفقودة أو أقصر من {DESC_MIN_OK} حرفاً، أو أطول من {DESC_MAX} حرفاً.')
        if imp_d:
            add('أوصاف يمكن رفعها إلى الطول المثالي', imp_d,
                f'ضمن الحد المقبول، والمثالي {DESC_MIN_OPTIMAL}–{DESC_MAX} حرفاً.')
        if stats.get('url_clone'):
            add('منتجات مستنسخة من منتج واحد', stats['url_clone'],
                'نسخ مكررة تتنافس مع المنتج الأصلي في نتائج البحث.')
        if stats.get('dup_content'):
            add('صفحات تتشارك نفس العنوان والوصف حرفياً', stats['dup_content'],
                'تُعدّ محتوى مكرراً، فيختار جوجل واحدة ويتجاهل الباقي.')
        if stats.get('noindex_pages'):
            add('صفحات تطلب من محركات البحث تجاهلها (noindex)', stats['noindex_pages'],
                'لا تظهر في النتائج مهما كان محتواها جيداً.')
        if stats.get('h1_mismatch'):
            add('صفحات عنوانها في البحث يختلف عن العنوان المعروض فيها', stats['h1_mismatch'],
                'يصل الزبون لصفحة لا تطابق ما نقر عليه.')
        if stats.get('canon_broken'):
            add('صفحات تشير بوسم الكانونيكال إلى صفحة واحدة بدل نفسها', stats['canon_broken'],
                'تطلب من محركات البحث تجاهلها جميعاً، وهو أخطر خلل في التقرير.')
        if stats.get('canon_missing'):
            add('صفحات بلا وسم كانونيكال', stats['canon_missing'], 'تعرّض المتجر لتكرار المحتوى.')
        if stats.get('hidden_count'):
            add('صفحات في خريطة الموقع لا يصل إليها الزائر بأي رابط داخلي', stats['hidden_count'],
                'تفقد قيمتها في نتائج البحث.')
        if stats.get('scroll_only_count'):
            add('منتجات لا يصل إليها الزائر إلا بالتمرير', stats['scroll_only_count'],
                'يضعف ترابطها الداخلي وقوتها في نتائج البحث.')
        if stats.get('broken_actionable'):
            add('روابط لا تعمل تحتاج معالجة', stats['broken_actionable'],
                'تحويلها إلى أقرب صفحة بديلة وتصحيح الروابط الداخلية التي تقود إليها.'
                if stats.get('redirect_qty') else
                'تصحيح الروابط الداخلية التي تقود الزائر إلى صفحة غير موجودة.')
        if stats.get('archive_pages', 0) > 20:
            add('صفحات أرشيف (وسوم وقوائم)', stats['archive_pages'],
                'محتوى مكرر يستهلك زحف محركات البحث دون زيارات.')
        if stats.get('thin_pages'):
            add('صفحات بمحتوى نصي أقل من 50 كلمة', stats['thin_pages'])

        if not points:
            return ("لم يرصد الفحص فجوات جوهرية في الصفحات المعروضة:", [
                "العناوين والأوصاف ضمن الأطوال الموصى بها.",
                "النصوص البديلة للصور مكتملة ووصفية.",
                "بنية الروابط وخريطة الموقع متسقة مع ما يراه الزائر."],
                "يوصى بمراجعة دورية عند إضافة منتجات أو أقسام جديدة.")

        intro = "رصد الفحص الفني النقاط التالية، مرتبة حسب أثرها على الظهور في البحث:"
        if score < 60:
            close = ("تشير النتيجة الإجمالية إلى فجوة واسعة في تهيئة المتجر لمحركات "
                     "البحث. يوصى بإعادة كتابة البيانات الوصفية وإسناد نصوص بديلة "
                     "وصفية لجميع صور المحتوى ضمن خطة عمل مرحلية.")
        elif score < 80:
            close = ("المتجر مهيأ جزئياً، ومعالجة البنود أعلاه من شأنها رفع درجة "
                     "التوافق وتحسين فرص الظهور في نتائج البحث.")
        else:
            close = ("المستوى العام جيد، والبنود أعلاه تحسينات تكميلية يمكن تنفيذها "
                     "ضمن جولة مراجعة واحدة.")
        return intro, points, close

    if missing and imgs:
        points.append(f"{missing} of {imgs} images ({round(missing / imgs * 100, 1)}%) "
                      "carry no alt text at all and cannot appear in Google Image search.")
    if weak:
        points.append(f"{weak} images have alt text that is present but non-descriptive "
                      "or duplicated, adding no value for search engines.")
    if stats.get('title_symbols'):
        points.append(f"{stats['title_symbols']} meta titles are only symbols or "
                      "template placeholders, leaving those pages with no real title.")
    if stats.get('title_brand_only'):
        points.append(f"{stats['title_brand_only']} titles contain nothing but the store "
                      "name, matching no customer search.")
    if stats.get('title_dup'):
        points.append(f"{stats['title_dup']} pages share an identical meta title.")
    if stats.get('desc_same'):
        points.append(f"{stats['desc_same']} descriptions are a verbatim copy of the "
                      "title, wasting a free line in the search result.")
    if crit_t:
        points.append(f"{crit_t} meta titles need urgent work: missing, under "
                      f"{TITLE_MIN_OK} characters, or over {TITLE_MAX} and truncated "
                      "in search results.")
    if imp_t:
        points.append(f"{imp_t} titles are acceptable and could be raised to the optimal "
                      f"{TITLE_MIN_OPTIMAL}-{TITLE_MAX} character range.")
    if crit_d:
        points.append(f"{crit_d} meta descriptions need urgent work: missing, under "
                      f"{DESC_MIN_OK} characters, or over {DESC_MAX}.")
    if imp_d:
        points.append(f"{imp_d} descriptions are acceptable and could be raised to the "
                      f"optimal {DESC_MIN_OPTIMAL}-{DESC_MAX} character range.")
    if stats.get('url_clone'):
        points.append(f"{stats['url_clone']} cloned products carry a copy-of prefix in "
                      "their URL and compete with the original in search results.")
    if stats.get('dup_content'):
        points.append(f"{stats['dup_content']} pages share an identical title and "
                      "description, counting as duplicate content.")
    if stats.get('noindex_pages'):
        points.append(f"{stats['noindex_pages']} pages carry a noindex tag asking "
                      "search engines to ignore them.")
    if stats.get('h1_mismatch'):
        points.append(f"{stats['h1_mismatch']} pages show a search title that differs "
                      "from the heading on the page itself.")
    if stats.get('canon_broken'):
        points.append(f"{stats['canon_broken']} pages point their canonical tag at a "
                      "single other page, asking search engines to ignore them all. "
                      "This is the most severe issue in this report.")
    if stats.get('canon_missing'):
        points.append(f"{stats['canon_missing']} pages have no canonical tag, exposing "
                      "the store to duplicate content.")
    if stats.get('hidden_count'):
        points.append(f"{stats['hidden_count']} pages published in the sitemap have no "
                      "internal link path for visitors and lose their value.")
    if stats.get('redirect_qty'):
        points.append(f"{stats['redirect_qty']} broken URLs have a close alternative and need a 301.")
    if stats.get('internal_fix_qty'):
        points.append(f"{stats['internal_fix_qty']} internal links lead to missing pages and need fixing.")
    if stats.get('archive_pages', 0) > 20:
        points.append(f"{stats['archive_pages']} archive pages (tags and lists) show "
                      "duplicated content under a single title and consume crawl "
                      "budget without bringing traffic.")
    if stats.get('thin_pages'):
        points.append(f"{stats['thin_pages']} pages carry fewer than 50 words of text.")

    if not points:
        return ("The audit found no material gaps across the visible pages:", [
            "Titles and descriptions fall within recommended lengths.",
            "Image alt text is complete and descriptive.",
            "Link structure and sitemap match what visitors can reach."],
            "Periodic review is advised as new products are added.")

    intro = "The technical audit identified the following, ordered by search impact:"
    if score < 60:
        close = ("The overall score indicates a substantial gap in search engine "
                 "readiness. Rewriting metadata and assigning descriptive alt text to "
                 "all content images is recommended as a phased programme of work.")
    elif score < 80:
        close = ("The store is partially optimised. Addressing the items above would "
                 "raise the compliance score and improve search visibility.")
    else:
        close = ("The overall standard is good; the items above are incremental "
                 "improvements that fit into a single review cycle.")
    return intro, points, close


def generate_client_pdf(domain, score, stats, lang='ar'):
    """تقرير عميل بتصميم حديث: غلاف، ثم قسم لكل محور في صفحة مستقلة
    يضم شرحاً للمقياس وجدول النتائج وصندوق الأثر، ثم التشخيص وخطة العمل."""
    rtl = (lang == 'ar')
    if rtl and not FONT_PATH.exists():
        raise FileNotFoundError(
            f"ملف الخط غير موجود: {FONT_PATH.name}. ارفع أحد الخطوط المدعومة "
            "إلى جذر المستودع.")

    T = PDF_TXT[lang]
    S = SECTION_TXT[lang]
    def _latin(t):
        t = str(t)
        for a, b in [('—', '-'), ('–', '-'), ('·', '|'), ('’', "'"), ('‘', "'"),
                     ('“', '"'), ('”', '"'), ('…', '...'), ('•', '-')]:
            t = t.replace(a, b)
        return t.encode('latin-1', 'replace').decode('latin-1')

    use_shaping = rtl and HAS_SHAPING
    _base_fmt = (lambda t: str(t)) if use_shaping else (shape_ar if rtl else _latin)
    fmt = (lambda t: _base_fmt(ar_counts(t))) if rtl else _latin
    ALIGN = "R" if rtl else "L"
    FONT = AR_FONT_NAME if rtl else "Helvetica"
    has_bold = bool(FONT_BOLD_PATH) if rtl else True

    def BOLD():
        return "B" if has_bold else ""
    clean_domain = urlparse(domain).netloc or domain
    logo_exists = LOGO_PATH.exists()
    M = 18                      # الهامش
    W = 210 - 2 * M             # عرض المحتوى
    verdict_rgb = C_BAD if score < 60 else (C_WARN if score < 80 else C_OK)

    class Report(FPDF):
        def header(self):
            if self.page_no() <= 1:
                return
            self.set_fill_color(*C_INK)
            self.rect(0, 0, 210, 3, 'F')
            self.set_fill_color(*C_ACC)
            self.rect(0 if rtl else 150, 0, 60, 3, 'F')
            self.set_y(9)
            self.set_font(FONT, "", 8)
            self.set_text_color(*C_MUTED)
            self.set_x(M)
            if rtl:
                self.cell(W / 2, 5, clean_domain, align="L")
                self.cell(W / 2, 5, fmt(T['title']), align="R")
            else:
                self.cell(W / 2, 5, fmt(T['title']), align="L")
                self.cell(W / 2, 5, clean_domain, align="R")
            self.set_y(24)

        def footer(self):
            if self.page_no() <= 1:
                return
            self.set_y(-15)
            self.set_draw_color(*C_LINE)
            self.line(M, 283, 210 - M, 283)
            self.set_font(FONT, "", 8)
            self.set_text_color(*C_MUTED)
            self.set_x(M)
            self.cell(W / 2, 8, "anasrashed.com", align="L" if rtl else "R")
            self.cell(W / 2, 8, fmt(T['page_of'].format(a=self.page_no())),
                      align="R" if rtl else "L")

        # ---------- أدوات الرسم ----------
        def wrap(self, txt, width, size=9):
            self.set_font(FONT, "", size)
            out, cur = [], ""
            for word in str(txt).split():
                trial = (cur + " " + word).strip()
                if self.get_string_width(fmt(trial)) <= width:
                    cur = trial
                else:
                    if cur:
                        out.append(cur)
                    cur = word
            if cur:
                out.append(cur)
            return out

        def safe(self, txt):
            """Helvetica لا يدعم يونيكود: تُستبدل الرموز الطويلة في النسخة اللاتينية."""
            t = str(txt)
            if rtl:
                return t
            for a, b in [('—', '-'), ('–', '-'), ('·', '|'), ('’', "'"),
                         ('‘', "'"), ('“', '"'), ('”', '"'), ('…', '...'),
                         ('•', '-')]:
                t = t.replace(a, b)
            return t.encode('latin-1', 'replace').decode('latin-1')

        def para(self, txt, width=W, size=9, color=C_MUTED, lh=5.0, x=M):
            self.set_font(FONT, "", size)
            self.set_text_color(*color)
            for line in self.wrap(txt, width, size):
                self.set_x(x)
                self.cell(width, lh, fmt(line), ln=True, align=ALIGN)

        def section(self, num, key, title=None, intro=None):
            """ترويسة قسم عصرية: شارة رقم دائرية، عنوان كبير، خط فيروزي، ثم الشرح."""
            y = self.get_y()
            d = 10
            bx = (210 - M - d) if rtl else M
            self.set_fill_color(*(C_INK if str(num) else C_ACC))
            self.ellipse(bx, y, d, d, 'F')
            self.set_font(FONT, BOLD(), 10.5)
            self.set_text_color(255, 255, 255)
            self.set_xy(bx, y + 0.3)
            self.cell(d, d, str(num), align="C")
            self.set_font(FONT, BOLD(), 16)
            self.set_text_color(*C_INK)
            tw = W - d - 5
            self.set_xy(M if rtl else M + d + 5, y + 0.2)
            self.cell(tw, d, fmt(title or S[key]['title']), align=ALIGN)
            self.set_fill_color(*C_ACC)
            lx = (210 - M - d - 5 - 18) if rtl else (M + d + 5)
            self.rect(lx, y + d + 1.5, 18, 1.1, 'F', round_corners=True, corner_radius=0.5)
            self.set_y(y + d + 6)
            self.para(intro or S[key]['intro'], size=9.2)
            self.ln(4)

        def table(self, rows):
            """جدول نتائج داخل بطاقة: اسم العنصر، والنتيجة في شارة بلون دلالي."""
            rh, wv = 9.0, 50
            wl = W - wv
            soft = {'ok': (231, 246, 240), 'warn': (253, 243, 226), 'bad': (252, 233, 233),
                    'neutral': C_SOFT}
            y0 = self.get_y()
            h_total = 9 + rh * len(rows)
            if y0 + h_total > 268 and h_total < 230:
                self.add_page()
                y0 = self.get_y()
            self.set_draw_color(*C_LINE)
            self.set_fill_color(255, 255, 255)
            self.rect(M, y0, W, min(h_total, 268 - y0), 'DF', round_corners=True, corner_radius=3)
            self.set_fill_color(*C_BG)
            self.rect(M, y0, W, 9, 'F', round_corners=True, corner_radius=3)
            self.set_font(FONT, BOLD(), 8.8)
            self.set_text_color(*C_MUTED)
            self.set_xy(M + 4, y0 + 0.5)
            if rtl:
                self.cell(wv - 4, 8, fmt(T['h_val']), 0, 0, 'C')
                self.cell(wl - 4, 8, fmt(T['h_item']), 0, 1, 'R')
            else:
                self.cell(wl - 4, 8, fmt(T['h_item']), 0, 0, 'L')
                self.cell(wv - 4, 8, fmt(T['h_val']), 0, 1, 'C')
            y = y0 + 9
            for i, (label, value, stt) in enumerate(rows):
                if y + rh > 268:
                    self.add_page()
                    y = self.get_y()
                if i:
                    self.set_draw_color(*C_SOFT)
                    self.line(M + 4, y, 210 - M - 4, y)
                pill_w = min(wv - 10, max(22, self.get_string_width(fmt(value)) + 8))
                px = (M + (wv - pill_w) / 2) if rtl else (M + wl + (wv - pill_w) / 2)
                self.set_fill_color(*soft.get(stt, C_SOFT))
                self.rect(px, y + 1.6, pill_w, rh - 3.2, 'F', round_corners=True, corner_radius=2.9)
                self.set_font(FONT, BOLD(), 8.8)
                self.set_text_color(*STATUS_RGB.get(stt, C_INK) if stt != 'neutral' else C_INK)
                self.set_xy(px, y + 1.6)
                self.cell(pill_w, rh - 3.2, fmt(value), align="C")
                self.set_font(FONT, "", 9.2)
                self.set_text_color(*C_INK)
                self.set_xy((M + wv) if rtl else (M + 5), y)
                self.cell(wl - 5, rh, fmt(label), align=ALIGN)
                y += rh
            self.set_y(y + 7)

        def fit(self, txt, width, size=8.5):
            """يقصّ النص من نهايته حتى يتسع للعرض المتاح."""
            self.set_font(FONT, "", size)
            t = str(txt)
            if self.get_string_width(fmt(t)) <= width:
                return t
            while t and self.get_string_width(fmt(t + '…')) > width:
                t = t[:-1]
            return t + '…'

        def link_list(self, rows, limit=30):
            """قائمة روابط: المسار، مكان ظهوره، كود الاستجابة."""
            wc, ww = 16, 44
            wu = W - wc - ww
            head = [(T['h_code'], wc, 'C'), (T['h_where'], ww, 'C'), (T['h_url'], wu, ALIGN)]
            if not rtl:
                head = list(reversed(head))
            self.set_font(FONT, BOLD(), 9)
            self.set_fill_color(*C_INK)
            self.set_text_color(255, 255, 255)
            self.set_x(M)
            for i, (h, w, a) in enumerate(head):
                self.cell(w, 8, fmt(h), 0, 1 if i == len(head) - 1 else 0, a, fill=True)
            for i, r in enumerate(rows[:limit]):
                if self.get_y() > 262:
                    self.add_page()
                y = self.get_y()
                if i % 2 == 0:
                    self.set_fill_color(*C_BG)
                    self.rect(M, y, W, 7, 'F')
                # بلا شرطة في البداية: في الاتجاه العربي تنتقل الشرطة لآخر السطر فتربك القراءة
                path = unquote(urlparse(str(r.get('الرابط', ''))).path).strip('/') or '/'
                act = str(r.get('الإجراء المقترح', ''))
                where = T['w_both'] if ('تحويل' in act and 'تصحيح' in act) else \
                    T['w_redirect'] if 'تحويل' in act else T['w_fix']
                code = str(r.get('كود الاستجابة', '404')).replace('خطأ ', '')
                cells = [(code, wc, 'C', C_BAD), (where, ww, 'C', C_MUTED),
                         (self.fit(path, wu - 3), wu, ALIGN, C_INK)]
                if not rtl:
                    cells = list(reversed(cells))
                self.set_x(M)
                for j, (txt, w, a, col) in enumerate(cells):
                    self.set_font(FONT, "", 8.5)
                    self.set_text_color(*col)
                    self.cell(w, 7, fmt(txt), 0, 1 if j == len(cells) - 1 else 0, a)
                self.set_draw_color(*C_LINE)
                self.line(M, self.get_y(), 210 - M, self.get_y())
            if len(rows) > limit:
                self.ln(2)
                self.para(T['more_links'].format(n=len(rows) - limit), size=8.5)
            self.ln(5)

        def impact(self, key):
            txt = S[key].get('impact')
            if not txt:
                return
            lines = self.wrap(txt, W - 14, 9)
            h = len(lines) * 5.0 + 13
            if self.get_y() + h > 265:
                self.add_page()
            y = self.get_y()
            self.set_fill_color(236, 248, 246)
            self.rect(M, y, W, h, 'F', round_corners=True, corner_radius=3)
            self.set_fill_color(*C_ACC)
            if rtl:
                self.rect(210 - M - 2.4, y + 3, 2.4, h - 6, 'F', round_corners=True, corner_radius=1.2)
            else:
                self.rect(M, y + 3, 2.4, h - 6, 'F', round_corners=True, corner_radius=1.2)
            self.set_font(FONT, BOLD(), 9.5)
            self.set_text_color(*C_ACC)
            self.set_xy(M + 7, y + 3.5)
            self.cell(W - 14, 5, fmt(T['impact']), ln=True, align=ALIGN)
            self.set_font(FONT, "", 9)
            self.set_text_color(*C_MUTED)
            yy = y + 9.5
            for line in lines:
                self.set_xy(M + 7, yy)
                self.cell(W - 14, 5, fmt(line), align=ALIGN)
                yy += 5.0
            self.set_y(y + h + 6)

        def mini(self, x, y, w, value, label, color=C_INK, h=22):
            self.set_draw_color(*C_LINE)
            self.set_fill_color(255, 255, 255)
            self.rect(x, y, w, h, 'DF', round_corners=True, corner_radius=3)
            self.set_font(FONT, BOLD(), 17)
            self.set_text_color(*color)
            self.set_xy(x, y + 3.5)
            self.cell(w, 9, fmt(value), align="C")
            self.set_font(FONT, "", 8.2)
            self.set_text_color(*C_MUTED)
            self.set_xy(x, y + 13)
            self.cell(w, 5, fmt(label), align="C")

    pdf = Report()
    if rtl:
        pdf.add_font(AR_FONT_NAME, "", str(FONT_PATH))
        if FONT_BOLD_PATH:
            pdf.add_font(AR_FONT_NAME, "B", str(FONT_BOLD_PATH))
        if use_shaping:
            pdf.set_text_shaping(True, direction="rtl")
    pdf.set_auto_page_break(True, margin=22)

    # ======================= الغلاف =======================
    pdf.add_page()
    verdict_lbl = (T['sc_bad'] if score < 60 else T['sc_warn'] if score < 80 else T['sc_ok'])
    # شريط علوي كحلي بعرض الصفحة
    pdf.set_fill_color(*C_INK)
    pdf.rect(0, 0, 210, 118, 'F')
    pdf.set_fill_color(*C_NAVY2)
    pdf.ellipse(120 if rtl else -40, -50, 130, 130, 'F')
    pdf.set_fill_color(*C_ACC)
    pdf.rect(0, 118, 210, 2.2, 'F')
    if logo_exists:
        try:
            pdf.set_fill_color(255, 255, 255)
            lx = (210 - M - 44) if rtl else M
            pdf.rect(lx, 18, 44, 20, 'F', round_corners=True, corner_radius=3)
            pdf.image(str(LOGO_PATH), x=lx + 4, y=21, h=14)
        except Exception:
            pass
    pdf.set_text_color(255, 255, 255)
    pdf.set_font(FONT, BOLD(), 26)
    pdf.set_xy(M, 52)
    pdf.cell(W, 13, fmt(T['title']), align=ALIGN)
    pdf.set_font(FONT, "", 11.5)
    pdf.set_text_color(203, 213, 225)
    pdf.set_xy(M, 66)
    pdf.cell(W, 7, fmt(T['subtitle']), align=ALIGN)
    # اسم المتجر في شارة
    pdf.set_font(FONT, BOLD(), 12)
    dw = pdf.get_string_width(clean_domain) + 14
    dx = (210 - M - dw) if rtl else M
    pdf.set_fill_color(*C_ACC)
    pdf.rect(dx, 82, dw, 11, 'F', round_corners=True, corner_radius=5.5)
    pdf.set_text_color(255, 255, 255)
    pdf.set_xy(dx, 82)
    pdf.cell(dw, 11, clean_domain, align="C")
    pdf.set_font(FONT, "", 9.5)
    pdf.set_text_color(203, 213, 225)
    pdf.set_xy(M, 98)
    meta = f"{T['platform']}: {stats.get('platform_label', '—')}     {T['date']}: {datetime.now().strftime('%Y-%m-%d')}"
    pdf.cell(W, 6, fmt(meta), align=ALIGN)

    # بطاقة الدرجة: حلقة بيانية + الحكم
    cy = 168
    card_y = 134
    pdf.set_draw_color(*C_LINE)
    pdf.set_fill_color(255, 255, 255)
    pdf.rect(M, card_y, W, 66, 'DF', round_corners=True, corner_radius=4)
    ring_cx = (210 - M - 40) if rtl else (M + 40)
    draw_donut(pdf, ring_cx, cy, 25, 6.5, [(score, verdict_rgb), (100 - score, C_SOFT)])
    pdf.set_font(FONT, BOLD(), 22)
    pdf.set_text_color(*verdict_rgb)
    pdf.set_xy(ring_cx - 20, cy - 7)
    pdf.cell(40, 10, f"{score}%", align="C")
    pdf.set_font(FONT, "", 7.5)
    pdf.set_text_color(*C_MUTED)
    pdf.set_xy(ring_cx - 20, cy + 3)
    pdf.cell(40, 5, fmt('الدرجة' if rtl else 'Score'), align="C")
    tx = M + 8 if rtl else M + 80
    tw_ = W - 88
    pdf.set_font(FONT, BOLD(), 15)
    pdf.set_text_color(*C_INK)
    pdf.set_xy(tx, card_y + 14)
    pdf.cell(tw_, 9, fmt(T['score_lbl']), align=ALIGN)
    pdf.set_fill_color(*verdict_rgb)
    pdf.set_font(FONT, BOLD(), 10)
    vw = pdf.get_string_width(fmt(verdict_lbl)) + 12
    vx = (tx + tw_ - vw) if rtl else tx
    pdf.rect(vx, card_y + 26, vw, 9, 'F', round_corners=True, corner_radius=4.5)
    pdf.set_text_color(255, 255, 255)
    pdf.set_xy(vx, card_y + 26)
    pdf.cell(vw, 9, fmt(verdict_lbl), align="C")
    pdf.set_font(FONT, "", 9)
    pdf.set_text_color(*C_MUTED)
    yy = card_y + 40
    for line in pdf.wrap(T['scope'], tw_, 9):
        pdf.set_xy(tx, yy)
        pdf.cell(tw_, 5, fmt(line), align=ALIGN)
        yy += 5

    # أرقام موجزة
    cards = [
        (str(stats.get('live_pages', stats['total_pages'])), T['m_pages'], C_INK),
        (str(stats['products']), T['m_products'], C_INK),
        (str(stats['categories']), T['m_cats'], C_INK),
        (str(stats.get('total_images', 0)), T['m_images'], C_INK),
        (str(quote_units(stats)), T['m_issues'], C_BAD),
    ]
    gap, cw = 3.5, (W - 4 * 3.5) / 5
    order = list(reversed(cards)) if rtl else cards
    for i, (v, l, c) in enumerate(order):
        pdf.mini(M + i * (cw + gap), 210, cw, v, l, c)

    pdf.set_y(262)
    pdf.set_font(FONT, "", 9)
    pdf.set_text_color(*C_MUTED)
    pdf.cell(0, 5, fmt(T['prepared']), ln=True, align="C")
    pdf.set_text_color(*C_ACC)
    pdf.cell(0, 5, "anasrashed.com   |   anas@anasrashed.com", align="C")

    # ======================= النظرة العامة (رسوم بيانية) =======================
    OV = {
        'ar': {'title': 'النظرة العامة', 'intro': 'صورة سريعة لحالة المتجر: ما هو سليم، وما يحتاج تحسيناً، وما يحتاج إصلاحاً عاجلاً.',
               'health': 'صحة عناصر السيو', 'titles': 'عناوين الميتا', 'descs': 'أوصاف الميتا', 'imgs': 'نصوص الصور البديلة',
               'g': 'سليم', 'i': 'يحتاج تحسيناً', 'u': 'يحتاج إصلاحاً', 'work': 'حجم العمل المطلوب', 'mix': 'مكوّنات المتجر',
               'w_t': 'عناوين', 'w_d': 'أوصاف', 'w_i': 'صور', 'w_b': 'روابط معطلة',
               'p': 'منتجات', 'c': 'أقسام', 'b': 'مقالات', 'f': 'تعريفية', 'o': 'أخرى'},
        'en': {'title': 'Overview', 'intro': "A quick picture of the store's health: what is fine, what can improve, and what needs fixing now.",
               'health': 'SEO element health', 'titles': 'Meta titles', 'descs': 'Meta descriptions', 'imgs': 'Image alt texts',
               'g': 'Good', 'i': 'Can improve', 'u': 'Needs fixing', 'work': 'Work required', 'mix': 'Store composition',
               'w_t': 'Titles', 'w_d': 'Descriptions', 'w_i': 'Images', 'w_b': 'Broken links',
               'p': 'Products', 'c': 'Categories', 'b': 'Articles', 'f': 'Info', 'o': 'Other'},
    }[lang]
    live_n = int(stats.get('live_pages', stats['total_pages']) or 0)
    pdf.add_page()
    pdf.section('', None, OV['title'], OV['intro'])

    # (1) صحة العناصر: أشرطة مكدسة
    y = pdf.get_y()
    pdf.set_draw_color(*C_LINE)
    pdf.set_fill_color(255, 255, 255)
    pdf.rect(M, y, W, 66, 'DF', round_corners=True, corner_radius=3)
    pdf.set_font(FONT, BOLD(), 11)
    pdf.set_text_color(*C_INK)
    pdf.set_xy(M + 6, y + 4)
    pdf.cell(W - 12, 7, fmt(OV['health']), align=ALIGN)
    crit_t = int(stats.get('critical_titles', 0)); bad_t = int(stats.get('bad_titles', 0))
    crit_d = int(stats.get('critical_descs', 0)); bad_d = int(stats.get('bad_descs', 0))
    rows_h = [
        (OV['titles'], [(max(live_n - bad_t, 0), C_OK), (max(bad_t - crit_t, 0), C_WARN), (crit_t, C_BAD)]),
        (OV['descs'], [(max(live_n - bad_d, 0), C_OK), (max(bad_d - crit_d, 0), C_WARN), (crit_d, C_BAD)]),
        (OV['imgs'], [(int(stats.get('good_alts', 0)), C_OK), (int(stats.get('weak_alts', 0)), C_WARN),
                      (int(stats.get('missing_alts', 0)), C_BAD)]),
    ]
    by = y + 15
    lab_w = 42
    bar_w = W - 12 - lab_w - 22
    for lbl, parts in rows_h:
        tot = sum(v for v, _ in parts) or 1
        good_pct = round(parts[0][0] / tot * 100)
        pdf.set_font(FONT, "", 9.2)
        pdf.set_text_color(*C_INK)
        if rtl:
            pdf.set_xy(210 - M - 6 - lab_w, by)
            pdf.cell(lab_w, 8, fmt(lbl), align="R")
            draw_stack(pdf, M + 6 + 22, by + 1.5, bar_w, 5, parts, rtl=True)
            pdf.set_font(FONT, BOLD(), 9.2)
            pdf.set_text_color(*C_OK)
            pdf.set_xy(M + 6, by)
            pdf.cell(20, 8, f"{good_pct}%", align="L")
        else:
            pdf.set_xy(M + 6, by)
            pdf.cell(lab_w, 8, fmt(lbl), align="L")
            draw_stack(pdf, M + 6 + lab_w, by + 1.5, bar_w, 5, parts)
            pdf.set_font(FONT, BOLD(), 9.2)
            pdf.set_text_color(*C_OK)
            pdf.set_xy(210 - M - 6 - 20, by)
            pdf.cell(20, 8, f"{good_pct}%", align="R")
        by += 12
    # مفتاح الألوان
    legend = [(OV['g'], C_OK), (OV['i'], C_WARN), (OV['u'], C_BAD)]
    pdf.set_font(FONT, "", 8.2)
    lxp = (210 - M - 8) if rtl else (M + 8)
    for name, col in legend:
        tw2 = pdf.get_string_width(fmt(name))
        pdf.set_fill_color(*col)
        if rtl:
            pdf.ellipse(lxp - 3, by + 2.2, 3, 3, 'F')
            pdf.set_text_color(*C_MUTED)
            pdf.set_xy(lxp - 5 - tw2, by)
            pdf.cell(tw2, 7.5, fmt(name))
            lxp -= tw2 + 12
        else:
            pdf.ellipse(lxp, by + 2.2, 3, 3, 'F')
            pdf.set_text_color(*C_MUTED)
            pdf.set_xy(lxp + 5, by)
            pdf.cell(tw2, 7.5, fmt(name))
            lxp += tw2 + 12
    pdf.set_y(y + 72)

    # (2) حجم العمل (أعمدة أفقية) + (3) مكوّنات المتجر (حلقة)
    y = pdf.get_y()
    half = (W - 6) / 2
    left_x = M if not rtl else M + half + 6       # البطاقة الأولى في جهة القراءة
    right_x = M + half + 6 if not rtl else M
    for bx in (left_x, right_x):
        pdf.set_draw_color(*C_LINE)
        pdf.set_fill_color(255, 255, 255)
        pdf.rect(bx, y, half, 88, 'DF', round_corners=True, corner_radius=3)
    # حجم العمل
    pdf.set_font(FONT, BOLD(), 11)
    pdf.set_text_color(*C_INK)
    pdf.set_xy(left_x + 6, y + 4)
    pdf.cell(half - 12, 7, fmt(OV['work']), align=ALIGN)
    work = [(OV['w_t'], int(stats.get('fix_titles_urls', stats.get('bad_titles', 0)) or 0)),
            (OV['w_d'], int(stats.get('fix_descs', stats.get('bad_descs', 0)) or 0)),
            (OV['w_i'], int(stats.get('missing_alts', 0) or 0) + int(stats.get('weak_alts', 0) or 0)),
            (OV['w_b'], int(stats.get('broken_actionable', 0) or 0))]
    mx = max([v for _, v in work] + [1])
    wy = y + 16
    for lbl, v in work:
        pdf.set_font(FONT, "", 8.8)
        pdf.set_text_color(*C_INK)
        pdf.set_xy(left_x + 6, wy)
        pdf.cell(half - 12, 5, fmt(lbl), align=ALIGN)
        pdf.set_font(FONT, BOLD(), 8.8)
        pdf.set_text_color(*C_INK)
        pdf.set_xy(left_x + 6, wy)
        pdf.cell(half - 12, 5, f"{v:,}", align="L" if rtl else "R")
        bw = (half - 12) * (v / mx if mx else 0)
        pdf.set_fill_color(*C_SOFT)
        pdf.rect(left_x + 6, wy + 6.5, half - 12, 4.5, 'F', round_corners=True, corner_radius=2.25)
        if bw > 0:
            pdf.set_fill_color(*C_ACC)
            bxx = (left_x + 6 + (half - 12) - bw) if rtl else (left_x + 6)
            pdf.rect(bxx, wy + 6.5, max(bw, 4.5), 4.5, 'F', round_corners=True, corner_radius=2.25)
        wy += 17
    # مكوّنات المتجر
    pdf.set_font(FONT, BOLD(), 11)
    pdf.set_text_color(*C_INK)
    pdf.set_xy(right_x + 6, y + 4)
    pdf.cell(half - 12, 7, fmt(OV['mix']), align=ALIGN)
    cats_all = int(stats.get('categories', 0)) + int(stats.get('brand_pages', 0) or 0) + int(stats.get('listing_pages', 0) or 0)
    known = int(stats.get('products', 0)) + cats_all + int(stats.get('blog_pages', 0)) + int(stats.get('info_pages', 0))
    mix = [(OV['p'], int(stats.get('products', 0)), C_INK), (OV['c'], cats_all, C_ACC),
           (OV['b'], int(stats.get('blog_pages', 0)), (99, 102, 241)), (OV['f'], int(stats.get('info_pages', 0)), C_WARN),
           (OV['o'], max(live_n - known, 0), (148, 163, 184))]
    rcx = right_x + half / 2
    draw_donut(pdf, rcx, y + 36, 19, 6, [(v, c) for _, v, c in mix])
    pdf.set_font(FONT, BOLD(), 13)
    pdf.set_text_color(*C_INK)
    pdf.set_xy(rcx - 15, y + 31)
    pdf.cell(30, 7, f"{live_n:,}", align="C")
    pdf.set_font(FONT, "", 7)
    pdf.set_text_color(*C_MUTED)
    pdf.set_xy(rcx - 15, y + 37.5)
    pdf.cell(30, 4, fmt(T['m_pages']), align="C")
    ly = y + 60
    col_w = (half - 12) / 2
    for i, (name, v, col) in enumerate([m for m in mix if m[1] > 0]):
        cxx = i % 2
        rxx = i // 2
        if rtl:
            ix = right_x + half - 6 - (cxx + 1) * col_w
        else:
            ix = right_x + 6 + cxx * col_w
        iy = ly + rxx * 7
        pdf.set_fill_color(*col)
        if rtl:
            pdf.ellipse(ix + col_w - 3.5, iy + 1.8, 3, 3, 'F')
            pdf.set_xy(ix, iy)
            pdf.set_font(FONT, "", 8)
            pdf.set_text_color(*C_MUTED)
            pdf.cell(col_w - 5, 6.5, fmt(f"{name} {v:,}"), align="R")
        else:
            pdf.ellipse(ix, iy + 1.8, 3, 3, 'F')
            pdf.set_xy(ix + 5, iy)
            pdf.set_font(FONT, "", 8)
            pdf.set_text_color(*C_MUTED)
            pdf.cell(col_w - 5, 6.5, fmt(f"{name} {v:,}"), align="L")
    pdf.set_y(y + 94)

    n = 0

    # ======================= البنية =======================
    n += 1
    pdf.add_page()
    pdf.section(n, 'structure')
    pdf.table([
        ('إجمالي الصفحات المعروضة والمفحوصة' if rtl else 'Total visible pages audited',
         f"{stats.get('live_pages', stats['total_pages'])} {T['u_page']}", 'neutral'),
        ('صفحات المنتجات' if rtl else 'Product pages',
         f"{stats['products']} {T['u_product']}", 'neutral'),
        ('أقسام المتجر' if rtl else 'Store categories',
         f"{stats['categories']} {T['u_cat']}", 'neutral'),
    ] + ([
        ('صفحات الماركات' if rtl else 'Brand pages',
         f"{stats['brand_pages']} {T['u_page']}", 'neutral'),
    ] if stats.get('brand_pages') else []) + ([
        ('قوائم عامة (أحدث المنتجات، العروض)' if rtl else 'General listings (latest, offers)',
         f"{stats['listing_pages']} {T['u_page']}", 'neutral'),
    ] if stats.get('listing_pages') else []) + [
        ('مقالات وصفحات المدونة' if rtl else 'Blog posts and articles',
         f"{stats.get('blog_pages', 0)} {T['u_article']}",
         'warn' if not stats.get('blog_pages') else 'neutral'),
        ('صفحات أرشيف (وسوم وقوائم)' if rtl else 'Archive pages (tags and lists)',
         f"{stats.get('archive_pages', 0)} {T['u_page']}",
         'warn' if stats.get('archive_pages', 0) > 20 else 'neutral'),
        ('الصفحات التعريفية والسياسات' if rtl else 'Info and policy pages',
         f"{stats['info_pages']} {T['u_page']}", 'neutral'),
        ('روابط لا تعمل تحتاج معالجة (404)' if rtl else 'Broken links to handle (404)',
         f"{stats.get('broken_actionable', 0)} {T['u_link']}",
         'bad' if stats.get('broken_actionable') else 'ok'),
        ('صفحات ممنوعة من الأرشفة' if rtl else 'Pages blocked from indexing',
         f"{stats.get('noindex_pages', 0)} {T['u_page']}",
         'bad' if stats.get('noindex_pages') else 'ok'),
        ('عناوين تختلف عن عنوان الصفحة' if rtl else 'Titles differing from page heading',
         f"{stats.get('h1_mismatch', 0)} {T['u_page']}",
         'warn' if stats.get('h1_mismatch') else 'ok'),
        ('صفحات بمحتوى نصي ضعيف' if rtl else 'Pages with thin text content',
         f"{stats.get('thin_pages', 0)} {T['u_page']}",
         'warn' if stats.get('thin_pages') else 'ok'),
    ])
    pdf.impact('structure')

    # ======================= الميتا =======================
    n += 1
    pdf.add_page()
    pdf.section(n, 'meta')
    tot = max(int(stats.get('live_pages', stats['total_pages'] - stats.get('broken_pages', 0))), 1)
    ok_t = max(tot - stats.get('bad_titles', 0), 0)
    ok_d = max(tot - stats.get('bad_descs', 0), 0)
    pdf.table([
        ('عناوين ضمن الطول المثالي (50-60)' if rtl else
         'Titles within optimal length (50-60)',
         (f"{ok_t} من {tot}" if rtl else f"{ok_t} of {tot}"),
         'ok' if ok_t / tot > 0.7 else 'warn'),
        ('عناوين تحتاج إصلاحاً عاجلاً' if rtl else 'Titles needing urgent work',
         f"{stats.get('critical_titles', 0)} {T['u_title']}",
         'bad' if stats.get('critical_titles') else 'ok'),
        ('عناوين مجرد رموز أو قيمة قالب' if rtl else
         'Titles that are symbols or placeholders',
         f"{stats.get('title_symbols', 0)} {T['u_title']}",
         'bad' if stats.get('title_symbols') else 'ok'),
        ('عناوين لا تحمل سوى اسم المتجر' if rtl else 'Titles with only the store name',
         f"{stats.get('title_brand_only', 0)} {T['u_title']}",
         'bad' if stats.get('title_brand_only') else 'ok'),
        ('صفحات تتشارك نفس العنوان' if rtl else 'Pages sharing the same title',
         f"{stats.get('title_dup', 0)} {T['u_page']}",
         'warn' if stats.get('title_dup') else 'ok'),
        ('أوصاف ضمن الطول المثالي (120-160)' if rtl else
         'Descriptions within optimal length (120-160)',
         (f"{ok_d} من {tot}" if rtl else f"{ok_d} of {tot}"),
         'ok' if ok_d / tot > 0.7 else 'warn'),
        ('أوصاف تحتاج إصلاحاً عاجلاً' if rtl else 'Descriptions needing urgent work',
         f"{stats.get('critical_descs', 0)} {T['u_desc']}",
         'bad' if stats.get('critical_descs') else 'ok'),
        ('صفحات بنفس العنوان والوصف حرفياً' if rtl else
         'Pages with identical title and description',
         f"{stats.get('dup_content', 0)} {T['u_page']}",
         'bad' if stats.get('dup_content') else 'ok'),
        ('منتجات مستنسخة من منتج واحد' if rtl else 'Cloned products',
         f"{stats.get('url_clone', 0)} {T['u_product']}",
         'bad' if stats.get('url_clone') else 'ok'),
        ('صفحات بلا وسم كانونيكال' if rtl else 'Pages without a canonical tag',
         f"{stats.get('canon_missing', 0)} {T['u_page']}",
         'warn' if stats.get('canon_missing') else 'ok'),
    ])
    pdf.impact('meta')

    # ======================= الصور =======================
    n += 1
    pdf.add_page()
    pdf.section(n, 'images')
    imgs = stats.get('total_images', 0)
    noalt = stats.get('missing_alts', 0)
    weak = stats.get('weak_alts', 0)
    good = stats.get('good_alts', 0)
    ratio = round((noalt + weak) / imgs * 100, 1) if imgs else 0
    fmts = ' · '.join(f"{k.upper()} {v}" for k, v in
                      list((stats.get('img_formats') or {}).items())[:4]) or '—'
    pdf.table([
        ('إجمالي صور المحتوى والمنتجات' if rtl else 'Total content and product images',
         f"{imgs} {T['u_img']}", 'neutral'),
        ('صور بلا نص بديل إطلاقاً' if rtl else 'Images with no alt text at all',
         f"{noalt} {T['u_img']}", 'bad' if noalt else 'ok'),
        ('صور بنص بديل غير وصفي أو مكرر' if rtl else
         'Images with non-descriptive or duplicated alt text',
         f"{weak} {T['u_img']}", 'warn' if weak else 'ok'),
        ('صور بنص بديل سليم' if rtl else 'Images with sound alt text',
         f"{good} {T['u_img']}", 'ok' if good else 'neutral'),
        ('نسبة الصور غير المهيأة' if rtl else 'Share of images not optimised',
         f"{ratio}%", 'bad' if ratio > 50 else 'warn' if ratio else 'ok'),
    ])
    pdf.impact('images')

    # ======================= خريطة الموقع =======================
    # يظهر القسم فقط إذا وُجد ما يمكن معالجته: صفحات في الخريطة بلا رابط داخلي
    if stats.get('coverage_enabled') and (stats.get('hidden_count') or stats.get('scroll_only_count')):
        n += 1
        pdf.add_page()
        pdf.section(n, 'sitemap')
        pdf.table([
            ('صفحات في الخريطة لا يصل إليها الزائر' if rtl else
             'Sitemap pages with no internal link',
             f"{stats.get('hidden_count', 0)} {T['u_page']}",
             'warn' if stats.get('hidden_count') else 'ok'),
            ('منتجات لا تظهر روابطها إلا بالتمرير' if rtl else
             'Products linked only via scrolling',
             f"{stats.get('scroll_only_count', 0)} {T['u_product']}",
             'warn' if stats.get('scroll_only_count') else 'ok'),
        ])
        pdf.impact('sitemap')

    # ======================= روابط لا تعمل بلا تحويل =======================
    if stats.get('broken_actionable'):
        n += 1
        pdf.add_page()
        key = 'broken' if stats.get('redirect_qty') else 'broken_internal'
        pdf.section(n, key)
        rows = [r for r in (stats.get('broken_links') or [])
                if not str(r.get('الإجراء المقترح', '')).startswith('لا إجراء')]
        if rows:
            pdf.link_list(rows)
        else:
            pdf.table([(('روابط لا تعمل تحتاج معالجة' if rtl else 'Broken links to handle'),
                        f"{stats['broken_actionable']} {T['u_link']}", 'bad')])
        pdf.impact(key)

    # ======================= التشخيص =======================
    n += 1
    pdf.add_page()
    pdf.section(n, 'diagnosis')
    intro, points, close = build_diagnosis(score, stats, lang)
    pdf.para(intro, size=9.5, color=C_INK)
    pdf.ln(3)
    for k, pt in enumerate(points, 1):
        lines = pdf.wrap(pt, W - 22, 9)
        h = len(lines) * 5 + 6
        if pdf.get_y() + h > 266:
            pdf.add_page()
        y = pdf.get_y()
        pdf.set_fill_color(*(C_BG if k % 2 else (255, 255, 255)))
        pdf.rect(M, y, W, h, 'F', round_corners=True, corner_radius=2.5)
        d = 6.5
        cx = (210 - M - 4 - d) if rtl else (M + 4)
        pdf.set_fill_color(*C_ACC)
        pdf.ellipse(cx, y + (h - d) / 2, d, d, 'F')
        pdf.set_font(FONT, BOLD(), 8)
        pdf.set_text_color(255, 255, 255)
        pdf.set_xy(cx, y + (h - d) / 2)
        pdf.cell(d, d, str(k), align="C")
        pdf.set_font(FONT, "", 9)
        pdf.set_text_color(*C_INK)
        for i, line in enumerate(lines):
            pdf.set_xy((M + 4) if rtl else (M + 4 + d + 4), y + 3 + i * 5)
            pdf.cell(W - 22, 5, fmt(line), align=ALIGN)
        pdf.set_y(y + h + 1.8)
    pdf.ln(4)

    lines = pdf.wrap(close, W - 16, 9.8)
    h = len(lines) * 5.4 + 10
    if pdf.get_y() + h > 266:
        pdf.add_page()
    y = pdf.get_y()
    pdf.set_fill_color(*C_INK)
    pdf.rect(M, y, W, h, 'F', round_corners=True, corner_radius=3)
    pdf.set_fill_color(*verdict_rgb)
    if rtl:
        pdf.rect(210 - M - 3, y + 3, 3, h - 6, 'F', round_corners=True, corner_radius=1.5)
    else:
        pdf.rect(M, y + 3, 3, h - 6, 'F', round_corners=True, corner_radius=1.5)
    pdf.set_font(FONT, "", 9.8)
    pdf.set_text_color(255, 255, 255)
    yy = y + 5
    for line in lines:
        pdf.set_xy(M + 8, yy)
        pdf.cell(W - 16, 5.4, fmt(line), align=ALIGN)
        yy += 5.4

    return bytes(pdf.output())



# ==============================================================
#  التسعير والفاتورة
#  أسعار السوق السعودي لخدمة إعادة تهيئة المتجر لمحركات البحث.
#  الأسعار قابلة للتعديل من الواجهة قبل إصدار الفاتورة.
# ==============================================================
DEFAULT_PRICES = {
    'meta_title': 12.0,   # عنوان الميتا مع تحديث الرابط ليطابقه: خدمة واحدة لكل صفحة
    'meta_desc': 10.0,    # وصف الميتا لكل صفحة
    'image_alt': 5.0,     # النص البديل لكل صورة
    'broken_link_fix': 5.0,    # معالجة رابط معطل: تحويل 301 و/أو تصحيح الرابط الداخلي، حسب حاجته
    'redirect_fix': 5.0,       # (للتوافق مع الإصدارات السابقة)
    'internal_link_fix': 5.0,  # (للتوافق مع الإصدارات السابقة)
}
PAYMENT = {
    'iban': 'SA87 1000 0026 5571 0000 0103',
    'stc': '+966 55 354 1890',
}
# خصم الكمية: المتاجر الكبيرة تحصل على سعر أفضل
VOLUME_TIERS = [(1000, 0.20), (500, 0.15), (200, 0.10), (0, 0.0)]


def volume_discount(units):
    for threshold, rate in VOLUME_TIERS:
        if units >= threshold:
            return rate
    return 0.0


def build_quote(summary, prices=None, discount_rate=0.0):
    """بنود الفاتورة: ما يحتاج إصلاحاً فعلياً فقط، لا كل صفحات المتجر."""
    pr = dict(DEFAULT_PRICES)
    pr.update(prices or {})

    # الكميات = عدد الصفوف في ملفي «العناوين والروابط» و«أوصاف الميتا» بالضبط
    titles = int(summary.get('fix_titles_urls', summary.get('bad_titles', 0)))
    descs = int(summary.get('fix_descs', summary.get('bad_descs', 0)))
    alts = int(summary.get('missing_alts', 0)) + int(summary.get('weak_alts', 0))
    # بند واحد لكل رابط معطل يحتاج عملاً (تحويل، أو تصحيح، أو الاثنان معاً)
    broken = int(summary.get('broken_actionable', 0))
    zid = summary.get('platform') == 'zid'

    items = []
    if titles:
        items.append({'key': 'meta_title', 'qty': titles, 'unit': pr['meta_title'],
                      'desc_key': 'meta_title_d_salla' if summary.get('platform') == 'salla'
                      else 'meta_title_d_redirect'})
    if descs:
        items.append({'key': 'meta_desc', 'qty': descs, 'unit': pr['meta_desc']})
    if alts:
        items.append({'key': 'image_alt', 'qty': alts, 'unit': pr['image_alt']})
    if broken:
        items.append({'key': 'broken_link_fix', 'qty': broken, 'unit': pr['broken_link_fix'],
                      'desc_key': 'broken_link_fix_d_zid' if zid else 'broken_link_fix_d'})
    for it in items:
        it['total'] = round(it['qty'] * it['unit'], 2)

    subtotal = round(sum(i['total'] for i in items), 2)
    units = titles + descs + alts + broken
    rate = max(0.0, min(float(discount_rate or 0.0), 0.9))
    disc = round(subtotal * rate, 2)
    return {'items': items, 'subtotal': subtotal, 'units': units,
            'discount_rate': rate, 'discount': disc,
            'total': round(subtotal - disc, 2), 'prices': pr}


INVOICE_TXT = {
    'ar': {
        'title': 'عرض سعر', 'sub': 'إعادة تهيئة المتجر لمحركات البحث',
        'to': 'العميل', 'date': 'التاريخ', 'no': 'رقم العرض',
        'valid': 'العرض ساري لمدة 14 يوماً من تاريخه',
        'h_item': 'الخدمة', 'h_qty': 'الكمية', 'h_unit': 'سعر الوحدة',
        'h_total': 'الإجمالي', 'currency': 'ريال',
        'meta_title': 'كتابة عناوين الميتا وروابط الصفحات',
        'meta_title_d_salla': 'صياغة عنوان بحثي لكل صفحة ضمن الطول المثالي، وتحديث رابطها '
                              'ليطابقه (سلة تحوّل الرابط القديم تلقائياً)',
        'meta_title_d_redirect': 'صياغة عنوان بحثي لكل صفحة ضمن الطول المثالي، وتحديث رابطها '
                                 'ليطابقه مع تحويل 301 من الرابط القديم',
        'meta_title_d': 'صياغة عنوان بحثي لكل صفحة ضمن الطول المثالي، '
                        'مع ضبط الرابط ليكون وصفياً ومطابقاً للمنتج',
        'meta_desc': 'كتابة أوصاف الميتا',
        'meta_desc_d': 'وصف تسويقي لكل صفحة ضمن الطول المثالي يرفع نسبة النقر '
                       'من نتائج البحث',
        'image_alt': 'كتابة النصوص البديلة للصور',
        'image_alt_d': 'وصف دقيق لكل صورة يُظهرها في بحث صور جوجل',
        'broken_link_fix': 'معالجة الروابط التي لا تعمل',
        'broken_link_fix_d_zid': 'لكل رابط معطل: تحويل 301 إلى أقرب صفحة بديلة، وتصحيح الروابط '
                                 'الداخلية التي تقود إليه، مع التحقق من عمل كل تحويل',
        'broken_link_fix_d': 'تصحيح كل رابط داخل المتجر يقود إلى صفحة غير موجودة ليشير '
                             'إلى الصفحة المناسبة',
        'redirect_fix': 'تحويل الروابط التي لا تعمل (301)',
        'redirect_fix_d': 'تحويل 301 لكل رابط معطل إلى أقرب صفحة بديلة في المتجر، '
                          'مع التحقق من عمل كل تحويل بعد تنفيذه',
        'internal_link_fix': 'تصحيح الروابط الداخلية المعطلة',
        'internal_link_fix_d': 'تعديل كل رابط داخل المتجر يقود إلى صفحة غير موجودة '
                               'ليشير إلى الصفحة المناسبة',
        'unit_page': 'صفحة', 'unit_img': 'صورة', 'unit_link': 'رابط',
        'subtotal': 'المجموع', 'discount': 'خصم الكمية', 'total': 'الإجمالي المستحق',
        'novat': 'الأسعار غير شاملة ضريبة القيمة المضافة',
        'pay': 'بيانات الدفع', 'iban': 'الآيبان', 'stc': 'STC Bank',
        'note': 'يبدأ التنفيذ بعد تأكيد الطلب.',
        'scope': 'الكميات مبنية على نتائج الفحص الفني، وتشمل ما يحتاج إصلاحاً فقط.',
    },
    'en': {
        'title': 'Quotation', 'sub': 'Search engine optimisation for your store',
        'to': 'Client', 'date': 'Date', 'no': 'Quote No.',
        'valid': 'This quotation is valid for 14 days',
        'h_item': 'Service', 'h_qty': 'Qty', 'h_unit': 'Unit price',
        'h_total': 'Amount', 'currency': 'SAR',
        'meta_title': 'Meta titles and page URLs',
        'meta_title_d_salla': 'A search-optimised title per page within the ideal length, with '
                              'its URL updated to match (Salla redirects the old URL automatically)',
        'meta_title_d_redirect': 'A search-optimised title per page within the ideal length, with '
                                 'its URL updated to match and a 301 from the old URL',
        'meta_title_d': 'A search-optimised title for each page within the ideal '
                        'length, with the URL corrected to match the product',
        'meta_desc': 'Meta descriptions',
        'meta_desc_d': 'A marketing description per page within the ideal length '
                       'to raise click-through from search results',
        'image_alt': 'Image alt texts',
        'image_alt_d': 'A precise description per image so it appears in '
                       'Google Image search',
        'broken_link_fix': 'Broken link repair',
        'broken_link_fix_d_zid': 'For each broken URL: a 301 to the closest alternative page, '
                                 'internal links pointing to it corrected, and every redirect verified',
        'broken_link_fix_d': 'Every link inside the store that leads to a missing page, '
                             'pointed to the right page',
        'redirect_fix': 'Broken link redirects (301)',
        'redirect_fix_d': 'A 301 redirect for each broken URL to the closest alternative '
                          'page in the store, verified after setup',
        'internal_link_fix': 'Broken internal link fixes',
        'internal_link_fix_d': 'Every link inside the store that leads to a missing page, '
                               'pointed to the right page',
        'unit_page': 'pages', 'unit_img': 'images', 'unit_link': 'links',
        'subtotal': 'Subtotal', 'discount': 'Volume discount', 'total': 'Total due',
        'novat': 'Prices exclude VAT',
        'pay': 'Payment details', 'iban': 'IBAN', 'stc': 'STC Bank',
        'note': 'Work begins upon confirmation.',
        'scope': 'Quantities are based on the technical audit and cover only '
                 'what needs fixing.',
    },
}


def generate_invoice_pdf(domain, quote, lang='ar', store_name=''):
    """عرض سعر بصفحة واحدة: الهوية وبيانات التواصل أعلى، والمبالغ برمز الريال."""
    rtl = (lang == 'ar')
    if rtl and not FONT_PATH.exists():
        raise FileNotFoundError(f"ملف الخط غير موجود: {FONT_PATH}")
    T = INVOICE_TXT[lang]

    def _latin(t):
        t = str(t)
        for a_, b_ in [('—', '-'), ('–', '-'), ('·', '|'), ('…', '...')]:
            t = t.replace(a_, b_)
        return t.encode('latin-1', 'replace').decode('latin-1')

    _base_fmt = (lambda t: str(t)) if (rtl and HAS_SHAPING) else (shape_ar if rtl else _latin)
    fmt = (lambda t: _base_fmt(ar_counts(t))) if rtl else _latin
    FONT = AR_FONT_NAME if rtl else "Helvetica"
    B = "B" if (FONT_BOLD_PATH if rtl else True) else ""
    ALIGN = "R" if rtl else "L"
    M, W = 18, 174
    dom = urlparse(domain).netloc or domain
    riyal = RIYAL_PATH.exists()

    class _Invoice(FPDF):
        def footer(self):
            # الموقع والبريد أسفل كل صفحة، مثل تقرير العميل
            self.set_y(-18)
            self.set_draw_color(*C_LINE)
            self.line(M, self.get_y(), 210 - M, self.get_y())
            self.ln(3)
            self.set_font(FONT, "", 9)
            self.set_text_color(*C_MUTED)
            self.cell(0, 5, "anasrashed.com   |   anas@anasrashed.com", align="C")

    pdf = _Invoice()
    if rtl:
        pdf.add_font(AR_FONT_NAME, "", str(FONT_PATH))
        if FONT_BOLD_PATH:
            pdf.add_font(AR_FONT_NAME, "B", str(FONT_BOLD_PATH))
        if HAS_SHAPING:
            pdf.set_text_shaping(True, direction="rtl")
    pdf.set_auto_page_break(True, margin=26)
    pdf.add_page()

    # رمز الريال بنسختين: داكن للخلفية الفاتحة، وأبيض للبطاقة الكحلية
    sym_dark = sym_white = None
    if riyal:
        try:
            from PIL import Image as _Img
            base = _Img.open(str(RIYAL_PATH)).convert('RGBA')
            sym_dark = base
            white = _Img.new('RGBA', base.size, (255, 255, 255, 0))
            white.putalpha(base.getchannel('A'))
            px = white.load()
            for xx in range(base.size[0]):
                for yy in range(base.size[1]):
                    a_ = base.getpixel((xx, yy))[3]
                    px[xx, yy] = (255, 255, 255, a_)
            sym_white = white
        except Exception:
            sym_dark = str(RIYAL_PATH)
            sym_white = str(RIYAL_PATH)

    def money(value, x, w, y, size=10, bold=False, color=C_MUTED, align='C', light=False):
        """المبلغ مع رمز الريال: يسار الرقم في العربية، ويمينه في الإنجليزية."""
        txt = f"{value:,.0f}"
        pdf.set_font(FONT, B if bold else "", size)
        pdf.set_text_color(*color)
        sym_h = size * 0.32
        sym_w = sym_h * 0.92
        gap = 1.3
        tw = pdf.get_string_width(txt)
        total = tw + (sym_w + gap if riyal else pdf.get_string_width(" " + T['currency']))
        start = x + (w - total) / 2 if align == 'C' else (x + w - total if align == 'R' else x)
        line_h = size * 0.5
        sym = sym_white if light else sym_dark
        if riyal:
            sx, nx = (start, start + sym_w + gap) if rtl else (start + tw + gap, start)
            try:
                pdf.image(sym, x=sx, y=y + (line_h - sym_h) / 2 + 0.25, h=sym_h)
            except Exception:
                pass
            pdf.set_xy(nx, y)
            pdf.cell(tw, line_h, txt, 0, 0, 'L')
        else:
            cur = fmt(T['currency'])
            pdf.set_xy(start, y)
            pdf.cell(total, line_h, (f"{cur} {txt}" if rtl else f"{txt} {cur}"), 0, 0, 'L')

    # ---------- الترويسة: شريط كحلي ----------
    pdf.set_fill_color(*C_INK)
    pdf.rect(0, 0, 210, 58, 'F')
    pdf.set_fill_color(*C_NAVY2)
    pdf.ellipse(-25 if rtl else 135, -62, 100, 100, 'F')
    pdf.set_fill_color(*C_ACC)
    pdf.rect(0, 58, 210, 1.8, 'F')
    if LOGO_PATH.exists():
        try:
            lx = M if rtl else 210 - M - 40
            pdf.set_fill_color(255, 255, 255)
            pdf.rect(lx, 14, 40, 18, 'F', round_corners=True, corner_radius=3)
            pdf.image(str(LOGO_PATH), x=lx + 3.5, y=16.5, h=13)
        except Exception:
            pass
    tx = M + 50 if rtl else M
    tw = W - 50
    pdf.set_xy(tx, 14)
    pdf.set_font(FONT, B, 24)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(tw, 11, fmt(T['title']), 0, 2, ALIGN)
    pdf.set_font(FONT, "", 10)
    pdf.set_text_color(203, 213, 225)
    pdf.cell(tw, 6, fmt(T['sub']), 0, 0, ALIGN)
    ref = datetime.now().strftime('%Y%m%d-') + f"{abs(hash(dom)) % 9000 + 1000}"
    pdf.set_font(FONT, "", 9)
    pdf.set_xy(tx, 40)
    pdf.cell(tw, 6, fmt(f"{T['no']}: {ref}     {T['date']}: {datetime.now().strftime('%Y-%m-%d')}"), 0, 0, ALIGN)

    # ---------- بطاقة العميل ----------
    y = 68
    pdf.set_draw_color(*C_LINE)
    pdf.set_fill_color(*C_BG)
    pdf.rect(M, y, W, 18, 'F', round_corners=True, corner_radius=3)
    pdf.set_font(FONT, "", 9)
    pdf.set_text_color(*C_MUTED)
    pdf.set_xy(M + 6, y + 2.5)
    pdf.cell(W - 12, 6, fmt(T['to']), 0, 2, ALIGN)
    pdf.set_font(FONT, B, 12.5)
    pdf.set_text_color(*C_INK)
    pdf.cell(W - 12, 7, store_name or dom, 0, 0, ALIGN)
    pdf.set_y(y + 25)

    # ---------- جدول البنود ----------
    wq, wu, wt = 26, 30, 34
    wn = W - wq - wu - wt
    yh = pdf.get_y()
    pdf.set_fill_color(*C_INK)
    pdf.rect(M, yh, W, 10, 'F', round_corners=True, corner_radius=3)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font(FONT, B, 9.5)
    heads = ([(T['h_total'], wt), (T['h_unit'], wu), (T['h_qty'], wq), (T['h_item'], wn)] if rtl else
             [(T['h_item'], wn), (T['h_qty'], wq), (T['h_unit'], wu), (T['h_total'], wt)])
    xx = M
    for h_, w_ in heads:
        pdf.set_xy(xx + (4 if w_ == wn and not rtl else 0), yh + 1)
        pdf.cell(w_ - (4 if w_ == wn else 0), 8, fmt(h_), 0, 0, 'C' if w_ != wn else ALIGN)
        xx += w_
    pdf.set_y(yh + 12)
    for idx, it in enumerate(quote['items']):
        name = T[it['key']]
        unit_lbl = {'image_alt': T['unit_img'], 'redirect_fix': T['unit_link'], 'broken_link_fix': T['unit_link'],
                    'internal_link_fix': T['unit_link']}.get(it['key'], T['unit_page'])
        pdf.set_font(FONT, "", 8.5)
        lines, cur = [], ""
        for word in T.get(it.get('desc_key') or '', T[it['key'] + '_d']).split():
            trial = (cur + " " + word).strip()
            if pdf.get_string_width(fmt(trial)) <= wn - 8:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
        h = 10 + len(lines) * 4.4 + 3
        y = pdf.get_y()
        pdf.set_fill_color(*(C_BG if idx % 2 == 0 else (255, 255, 255)))
        pdf.rect(M, y, W, h, 'F', round_corners=True, corner_radius=2.5)
        name_x = (M + wt + wu + wq) if rtl else (M + 4)
        qty_x = (M + wt + wu) if rtl else (M + wn)
        unit_x = (M + wt) if rtl else (M + wn + wq)
        tot_x = M if rtl else (M + wn + wq + wu)
        pdf.set_font(FONT, B, 10.5)
        pdf.set_text_color(*C_INK)
        pdf.set_xy(name_x, y + 2.5)
        pdf.cell(wn - 4, 6, fmt(name), 0, 0, ALIGN)
        # الكمية في شارة
        qtxt = fmt(f"{it['qty']:,} {unit_lbl}")
        pdf.set_font(FONT, "", 9)
        qw = min(wq - 3, pdf.get_string_width(qtxt) + 7)
        pdf.set_fill_color(*C_SOFT)
        pdf.rect(qty_x + (wq - qw) / 2, y + 2.6, qw, 6.5, 'F', round_corners=True, corner_radius=3.2)
        pdf.set_text_color(*C_INK)
        pdf.set_xy(qty_x + (wq - qw) / 2, y + 2.6)
        pdf.cell(qw, 6.5, qtxt, 0, 0, 'C')
        money(it['unit'], unit_x, wu, y + 3.4, 10, False, C_MUTED)
        money(it['total'], tot_x, wt, y + 3.4, 10.5, True, C_INK)
        pdf.set_font(FONT, "", 8.5)
        pdf.set_text_color(*C_MUTED)
        yy = y + 10
        for ln_ in lines:
            pdf.set_xy(name_x if rtl else M + 4, yy)
            pdf.cell(wn - 4, 4.4, fmt(ln_), 0, 0, ALIGN)
            yy += 4.4
        pdf.set_y(y + h + 1.5)

    # ---------- المجاميع (بطاقة كحلية) والدفع بجانبها ----------
    pdf.ln(3)
    box_w = 92
    pay_w = W - box_w - 6
    y0 = pdf.get_y()
    if y0 + 40 > 262:
        pdf.add_page()
        y0 = pdf.get_y()
    bx = M if rtl else 210 - M - box_w
    px_ = (M + box_w + 6) if rtl else M
    y = y0
    rows_ = [(T['subtotal'], quote['subtotal'])]
    if quote['discount']:
        rows_.append((f"{T['discount']} {int(quote['discount_rate'] * 100)}%", -quote['discount']))
    for lbl, val in rows_:
        pdf.set_font(FONT, "", 10)
        pdf.set_text_color(*C_MUTED)
        pdf.set_xy(bx + 5, y)
        pdf.cell(box_w - 10, 7, fmt(lbl), 0, 0, ALIGN)
        money(val, bx + 5, box_w - 10, y + 1.2, 10, False, C_MUTED, align='L' if rtl else 'R')
        y += 8
    pdf.set_fill_color(*C_INK)
    pdf.rect(bx, y + 1, box_w, 17, 'F', round_corners=True, corner_radius=3)
    pdf.set_font(FONT, B, 11)
    pdf.set_text_color(255, 255, 255)
    pdf.set_xy(bx + 6, y + 5)
    pdf.cell(box_w - 12, 8, fmt(T['total']), 0, 0, ALIGN)
    money(quote['total'], bx + 6, box_w - 12, y + 6.2, 14, True, (255, 255, 255),
          align='L' if rtl else 'R', light=True)
    pdf.set_font(FONT, "", 8)
    pdf.set_text_color(*C_MUTED)
    pdf.set_xy(bx, y + 20)
    pdf.cell(box_w, 5, fmt(T['novat']), 0, 0, ALIGN)
    y_end = y + 26

    # بطاقة الدفع
    ph = max(y_end - y0 - 6, 30)
    pdf.set_fill_color(236, 248, 246)
    pdf.rect(px_, y0, pay_w, ph, 'F', round_corners=True, corner_radius=3)
    pdf.set_fill_color(*C_ACC)
    pdf.rect((px_ + pay_w - 3) if rtl else px_, y0 + 3, 3, ph - 6, 'F', round_corners=True, corner_radius=1.5)
    pdf.set_font(FONT, B, 10.5)
    pdf.set_text_color(*C_ACC)
    pdf.set_xy(px_ + 7, y0 + 4)
    pdf.cell(pay_w - 14, 6, fmt(T['pay']), 0, 2, ALIGN)
    for lbl, val in [(T['iban'], PAYMENT['iban']), (T['stc'], PAYMENT['stc'])]:
        pdf.set_font(FONT, "", 8.3)
        pdf.set_text_color(*C_MUTED)
        pdf.set_x(px_ + 7)
        pdf.cell(pay_w - 14, 5, fmt(lbl), 0, 2, ALIGN)
        pdf.set_font(FONT, B, 9.3)
        pdf.set_text_color(*C_INK)
        pdf.set_x(px_ + 7)
        if rtl and HAS_SHAPING:
            pdf.set_text_shaping(False)      # الأرقام والرمز + تُكتب من اليسار كما هي
        pdf.cell(pay_w - 14, 5.5, val, 0, 2, ALIGN)
        if rtl and HAS_SHAPING:
            pdf.set_text_shaping(True, direction="rtl")
    pdf.set_y(max(y_end, y0 + ph) + 5)

    pdf.set_font(FONT, "", 8.5)
    pdf.set_text_color(*C_MUTED)
    for line in (T['scope'], T['note'], T['valid']):
        pdf.set_x(M)
        pdf.cell(W, 5, fmt(line), ln=True, align=ALIGN)
    return bytes(pdf.output())


# ==============================================================
