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
            'intro': 'يبدأ الفحص من الصفحة الرئيسية ويتصفح المتجر كما يتصفحه الزائر، '
                     'متتبعاً الروابط الداخلية وصفحات الأقسام. لا تدخل التقرير أي صفحة '
                     'لا يمكن للزائر الوصول إليها بالنقر.',
            'impact': 'هذه الأرقام هي ما تراه محركات البحث فعلياً عند زحفها للمتجر. أي '
                      'رابط معطل يصل إليه الزائر يهدر جزءاً من ميزانية الزحف المخصصة '
                      'للمتجر، ويقلل فرص أرشفة الصفحات المهمة.',
        },
        'meta': {
            'title': 'عناوين وأوصاف الميتا',
            'intro': 'عنوان الميتا هو السطر الأزرق القابل للنقر في نتائج البحث، والوصف '
                     'هو السطران تحته. المعيار المعتمد: العنوان بين 50 و60 حرفاً، والوصف '
                     'بين 120 و150 حرفاً، ويُحسب الطول بالحروف شاملاً المسافات وعلامات '
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
                     'لا ترى الصورة، بل تقرأ هذا النص. ويفحص هذا القسم أيضاً صيغة الصور، '
                     'إذ تؤثر مباشرة في حجم الصفحة وسرعتها.',
            'impact': 'بحث صور جوجل مصدر زيارات مهم في المتاجر البصرية كالأزياء والعطور '
                      'والهدايا، حيث يبحث الزبون بالصورة قبل الكلمة. الصورة بلا نص بديل '
                      'غير موجودة بالنسبة لجوجل. كما أن الصيغ الحديثة تخفض حجم الصورة '
                      'بنحو الثلث بنفس الجودة، فتتحسن سرعة الجوال تلقائياً.',
        },
        'sitemap': {
            'title': 'مقارنة المعروض بخريطة الموقع',
            'intro': 'خريطة الموقع هي القائمة التي يعلنها المتجر لمحركات البحث. يقارن '
                     'هذا القسم ما يراه الزائر فعلاً بما تعلنه الخريطة، في الاتجاهين.',
            'impact': 'المنتج المعروض وغير المدرج في الخريطة قد لا تعلم به محركات البحث '
                      'أصلاً. والصفحة المدرجة في الخريطة ولا يصل إليها الزائر بأي رابط '
                      'داخلي تبقى بلا قيمة: لا تستفيد من قوة المتجر ولا تجلب زيارات.',
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
                     'between 50 and 60 characters, descriptions between 120 and 150, '
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
            'title': 'Visible catalogue vs sitemap',
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

C_INK = (15, 23, 42)
C_MUTED = (100, 116, 139)
C_LINE = (226, 232, 240)
C_BG = (248, 250, 252)
C_OK = (5, 150, 105)
C_WARN = (217, 119, 6)
C_BAD = (220, 38, 38)
STATUS_RGB = {'ok': C_OK, 'warn': C_WARN, 'bad': C_BAD, 'neutral': C_MUTED}


def shape_ar(text):
    return get_display(arabic_reshaper.reshape(str(text)))


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
        if missing and imgs:
            points.append(f"{missing} صورة من أصل {imgs} بلا نص بديل إطلاقاً "
                          f"({round(missing / imgs * 100, 1)}%)، فلا تظهر في بحث صور جوجل.")
        if weak:
            points.append(f"{weak} صورة نصها البديل موجود لكنه غير وصفي أو مكرر، "
                          "فلا يضيف قيمة لمحركات البحث.")
        if stats.get('title_symbols'):
            points.append(f"{stats['title_symbols']} عنوان ميتا مجرد رموز أو قيمة قالب "
                          "افتراضية بدل النص، أي أن الصفحة بلا عنوان فعلي "
                          "في نتائج البحث.")
        if stats.get('title_brand_only'):
            points.append(f"{stats['title_brand_only']} عنوان لا يحمل سوى اسم المتجر "
                          "بلا أي وصف للمنتج، فلا يطابق أي بحث للزبون.")
        if stats.get('title_promo'):
            points.append(f"{stats['title_promo']} عنوان بصياغة ترويجية (سعر أو عرض) بدل كلمات "
                          "يبحث بها الزبون، فلا يظهر حين يبحث عن المنتج نفسه.")
        if stats.get('title_dup'):
            points.append(f"{stats['title_dup']} صفحة تتشارك نفس عنوان الميتا، "
                          "فلا تميّز محركات البحث بينها.")
        if stats.get('desc_same'):
            points.append(f"{stats['desc_same']} وصف ميتا نسخة حرفية من العنوان، "
                          "فيضيع سطر إضافي مجاني في نتيجة البحث.")
        if crit_t:
            points.append(f"{crit_t} عنوان ميتا يحتاج إصلاحاً عاجلاً: مفقود أو أقصر من "
                          f"{TITLE_MIN_OK} حرفاً أو يتجاوز {TITLE_MAX} حرفاً فيُقتطع "
                          "في نتائج البحث.")
        if imp_t:
            points.append(f"{imp_t} عنوان ضمن الحد المقبول ويمكن رفعه إلى الطول المثالي "
                          f"({TITLE_MIN_OPTIMAL}-{TITLE_MAX} حرفاً) لاستغلال كامل "
                          "المساحة المعروضة.")
        if crit_d:
            points.append(f"{crit_d} وصف ميتا يحتاج إصلاحاً عاجلاً: مفقود أو أقصر من "
                          f"{DESC_MIN_OK} حرفاً أو يتجاوز {DESC_MAX} حرفاً.")
        if imp_d:
            points.append(f"{imp_d} وصف ضمن الحد المقبول ويمكن رفعه إلى الطول المثالي "
                          f"({DESC_MIN_OPTIMAL}-{DESC_MAX} حرفاً).")
        if stats.get('url_clone'):
            points.append(f"{stats['url_clone']} منتجاً مستنسخاً: رابطه يحمل بادئة "
                          "النسخ أو لاحقة رقمية، وهي نسخ مكررة من منتج واحد تتنافس "
                          "مع أصلها في نتائج البحث.")
        if stats.get('dup_content'):
            points.append(f"{stats['dup_content']} صفحة تتشارك نفس العنوان والوصف "
                          "حرفياً، فتُعدّ محتوى مكرراً ويختار جوجل واحدة ويتجاهل الباقي.")
        if stats.get('url_wrongname'):
            points.append(f"{stats['url_wrongname']} رابط يحمل اسم منتج مختلف عن المنتج "
                          "المعروض في الصفحة، غالباً لأن المنتج نُسخ ثم غُيّر اسمه دون "
                          "تحديث الرابط. الزبون يصل لصفحة لا تطابق ما نقر عليه.")
        if stats.get('url_style'):
            points.append(f"{stats['url_style']} رابط بصياغة غير مثالية: شرطة سفلية "
                          "أو حروف كبيرة أو طول مفرط أو تكرار كلمة داخل الرابط.")
        if stats.get('url_malformed'):
            points.append(f"{stats['url_malformed']} رابط معطوب يحتوي عنوان موقع داخل "
                          "مساره (لصق خاطئ في حقل الرابط)، فيظهر للزبون في نتائج البحث "
                          "بشكل مشوّه ويضعف الثقة.")
        if stats.get('url_generic'):
            points.append(f"{stats['url_generic']} رابط مكوّن من أرقام أو رموز بلا "
                          "كلمات وصفية.")
        if stats.get('img_legacy') and stats.get('img_modern_pct', 100) < 50:
            points.append(f"{stats['img_legacy']} صورة بصيغة قديمة ثقيلة بدل الصيغ "
                          "الحديثة الخفيفة، ما يزيد حجم الصفحة ويبطئ تحميلها "
                          "على الجوال.")
        if stats.get('noindex_pages'):
            points.append(f"{stats['noindex_pages']} صفحة تحمل وسم noindex الذي يطلب "
                          "من محركات البحث تجاهلها، فلا تظهر في النتائج مهما كان "
                          "محتواها جيداً.")
        if stats.get('deleted_pages'):
            points.append(f"{stats['deleted_pages']} رابط لمنتجات محذوفة أو مخفية "
                          "يُحوَّل إلى الصفحة الرئيسية بدل إظهار صفحة «غير موجود»، "
                          "وهو ما يربك محركات البحث ويهدر ميزانية الزحف.")
        if stats.get('h1_mismatch'):
            points.append(f"{stats['h1_mismatch']} صفحة عنوانها في نتائج البحث يختلف "
                          "عن العنوان المعروض فيها، فيصل الزبون لصفحة لا تطابق ما "
                          "نقر عليه.")
        if stats.get('canon_broken'):
            points.append(f"{stats['canon_broken']} صفحة تشير بوسم الكانونيكال إلى "
                          "صفحة واحدة بدل نفسها، فتطلب من محركات البحث تجاهلها "
                          "جميعاً. هذا أخطر خلل في التقرير ويعالج من القالب.")
        if stats.get('canon_missing'):
            points.append(f"{stats['canon_missing']} صفحة بلا وسم كانونيكال، "
                          "ما يعرّض المتجر لتكرار المحتوى.")
        if stats.get('hidden_count'):
            points.append(f"{stats['hidden_count']} صفحة منشورة في خريطة الموقع لا يصل "
                          "إليها الزائر بأي رابط داخلي، فتفقد قيمتها.")
        if stats.get('unlisted_count'):
            points.append(f"{stats['unlisted_count']} صفحة معروضة في المتجر وغير مدرجة "
                          "في خريطة الموقع، فقد لا تعلم بها محركات البحث.")
        if stats.get('scroll_only_count'):
            points.append(f"{stats['scroll_only_count']} منتجاً لا يظهر رابطه في صفحات "
                          "الأقسام ويصل إليه الزائر بالتمرير فقط، فيضعف ترابطه الداخلي "
                          "وتقل قوته في نتائج البحث.")
        if stats.get('not_indexed_count'):
            points.append(f"{stats['not_indexed_count']} منتجاً معروضاً في المتجر "
                          "لا يظهر في خريطة الموقع.")
        if stats.get('redirect_qty'):
            points.append(f"{stats['redirect_qty']} رابط لا يعمل (404) وله بديل قريب في المتجر، "
                          "يحتاج تحويل 301 إلى هذا البديل.")
        if stats.get('internal_fix_qty'):
            points.append(f"{stats['internal_fix_qty']} رابط داخلي يقود الزائر إلى صفحة غير "
                          "موجودة، يحتاج تصحيحاً ليشير إلى الصفحة المناسبة.")
        if stats.get('archive_pages', 0) > 20:
            points.append(f"{stats['archive_pages']} صفحة أرشيف (وسوم وقوائم) تعرض "
                          "محتوى مكرراً بعنوان واحد، وتستهلك ميزانية الزحف دون أن "
                          "تجلب زيارات. يوصى بحصر الوسوم في المفيد منها.")
        if stats.get('thin_pages'):
            points.append(f"{stats['thin_pages']} صفحة بمحتوى نصي أقل من 50 كلمة.")

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
    if stats.get('url_wrongname'):
        points.append(f"{stats['url_wrongname']} URLs carry a different product name than "
                      "the page displays, usually because a product was cloned and "
                      "renamed without updating its URL.")
    if stats.get('url_style'):
        points.append(f"{stats['url_style']} URLs have imperfect formatting: underscores, "
                      "uppercase letters, excessive length, or a repeated word.")
    if stats.get('url_malformed'):
        points.append(f"{stats['url_malformed']} URLs are malformed and contain a full "
                      "web address inside the slug, showing distorted in search results.")
    if stats.get('url_generic'):
        points.append(f"{stats['url_generic']} URLs consist of numbers or codes with no "
                      "descriptive words.")
    if stats.get('img_legacy') and stats.get('img_modern_pct', 100) < 50:
        points.append(f"{stats['img_legacy']} images use legacy formats (JPEG/PNG) "
                      "instead of WebP, increasing page weight on mobile.")
    if stats.get('noindex_pages'):
        points.append(f"{stats['noindex_pages']} pages carry a noindex tag asking "
                      "search engines to ignore them.")
    if stats.get('deleted_pages'):
        points.append(f"{stats['deleted_pages']} deleted or hidden product URLs "
                      "redirect to the homepage instead of returning a not-found "
                      "page, confusing search engines.")
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
    if stats.get('not_indexed_count'):
        points.append(f"{stats['not_indexed_count']} visible products are absent "
                      "from the sitemap.")
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
    fmt = (lambda t: str(t)) if use_shaping else (shape_ar if rtl else _latin)
    if not rtl:
        fmt = _latin
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
            self.set_y(10)
            self.set_font(FONT, "", 8)
            self.set_text_color(*C_MUTED)
            self.cell(W, 4, fmt(f"{T['owner']}  ·  {clean_domain}"), align=ALIGN)
            self.set_draw_color(*C_LINE)
            self.line(M, 17, 210 - M, 17)
            self.set_y(26)

        def footer(self):
            if self.page_no() <= 1:
                return
            self.set_y(-16)
            self.set_draw_color(*C_LINE)
            self.line(M, 282, 210 - M, 282)
            self.set_font(FONT, "", 8)
            self.set_text_color(*C_MUTED)
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

        def section(self, num, key):
            """ترويسة قسم: مربع رقم ملوّن + عنوان + شرح."""
            y = self.get_y()
            box = 9
            bx = (210 - M - box) if rtl else M
            self.set_fill_color(*C_INK)
            self.rect(bx, y, box, box, 'F')
            self.set_font(FONT, "", 10)
            self.set_text_color(255, 255, 255)
            self.set_xy(bx, y + 0.6)
            self.cell(box, box - 1, str(num), align="C")
            self.set_font(FONT, BOLD(), 15)
            self.set_text_color(*C_INK)
            tw = W - box - 4
            self.set_xy(M if rtl else M + box + 4, y + 0.4)
            self.cell(tw, box, fmt(S[key]['title']), align=ALIGN)
            self.set_y(y + box + 4)
            self.para(S[key]['intro'])
            self.ln(3)

        def table(self, rows):
            """جدول نتائج: عمود العنصر وعمود النتيجة بلون دلالي."""
            wv, wl = 52, W - 52
            self.set_font(FONT, BOLD(), 9.5)
            self.set_fill_color(*C_INK)
            self.set_text_color(255, 255, 255)
            self.set_x(M)
            if rtl:
                self.cell(wv, 8, fmt(T['h_val']), 0, 0, 'C', fill=True)
                self.cell(wl, 8, fmt(T['h_item']), 0, 1, 'R', fill=True)
            else:
                self.cell(wl, 8, fmt(T['h_item']), 0, 0, 'L', fill=True)
                self.cell(wv, 8, fmt(T['h_val']), 0, 1, 'C', fill=True)
            self.set_font(FONT, "", 9)
            for i, (label, value, stt) in enumerate(rows):
                if self.get_y() > 250:
                    self.add_page()
                self.set_x(M)
                if i % 2 == 0:
                    self.set_fill_color(*C_BG)
                    self.rect(M, self.get_y(), W, 7.5, 'F')
                self.set_text_color(*STATUS_RGB.get(stt, C_MUTED))
                self.set_font(FONT, "", 9)
                if rtl:
                    self.cell(wv, 7.5, fmt(value), 0, 0, 'C')
                    self.set_text_color(*C_INK)
                    self.cell(wl, 7.5, fmt(label), 0, 1, 'R')
                else:
                    self.set_text_color(*C_INK)
                    self.cell(wl, 7.5, fmt(label), 0, 0, 'L')
                    self.set_text_color(*STATUS_RGB.get(stt, C_MUTED))
                    self.cell(wv, 7.5, fmt(value), 0, 1, 'C')
                self.set_draw_color(*C_LINE)
                self.line(M, self.get_y(), 210 - M, self.get_y())
            self.ln(6)

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
            self.set_fill_color(*C_BG)
            self.rect(M, y, W, h, 'F')
            self.set_fill_color(*C_INK)
            if rtl:
                self.rect(210 - M - 2.2, y, 2.2, h, 'F')
            else:
                self.rect(M, y, 2.2, h, 'F')
            self.set_font(FONT, BOLD(), 9.5)
            self.set_text_color(*C_INK)
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

        def mini(self, x, y, w, value, label, color=C_INK):
            self.set_fill_color(*C_BG)
            self.rect(x, y, w, 20, 'F')
            self.set_font(FONT, BOLD(), 15)
            self.set_text_color(*color)
            self.set_xy(x, y + 3)
            self.cell(w, 8, fmt(value), align="C")
            self.set_font(FONT, "", 8)
            self.set_text_color(*C_MUTED)
            self.set_xy(x, y + 11.5)
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
    if logo_exists:
        try:
            pdf.image(str(LOGO_PATH), x=(210 - 40) / 2, y=22, h=15)
        except Exception:
            pass
    pdf.set_y(48)
    pdf.set_draw_color(*C_LINE)
    pdf.line(M + 55, 46, 210 - M - 55, 46)

    pdf.set_font(FONT, BOLD(), 23)
    pdf.set_text_color(*C_INK)
    pdf.cell(0, 12, fmt(T['title']), ln=True, align="C")
    pdf.set_font(FONT, "", 11)
    pdf.set_text_color(*C_MUTED)
    pdf.cell(0, 7, fmt(T['subtitle']), ln=True, align="C")
    pdf.ln(6)

    # بطاقة الدرجة
    y = pdf.get_y()
    pdf.set_fill_color(*C_BG)
    pdf.rect(M, y, W, 44, 'F')
    pdf.set_fill_color(*verdict_rgb)
    pdf.rect(M, y, W, 1.6, 'F')
    pdf.set_font(FONT, BOLD(), 40)
    pdf.set_text_color(*verdict_rgb)
    pdf.set_xy(M, y + 7)
    pdf.cell(W, 18, f"{score}%", align="C")
    pdf.set_font(FONT, "", 10.5)
    pdf.set_text_color(*C_INK)
    pdf.set_xy(M, y + 25)
    pdf.cell(W, 6, fmt(T['score_lbl']), align="C")
    pdf.set_font(FONT, "", 9)
    pdf.set_text_color(*C_MUTED)
    pdf.set_xy(M, y + 32)
    verdict_lbl = (T['sc_bad'] if score < 60 else
                   T['sc_warn'] if score < 80 else T['sc_ok'])
    pdf.cell(W, 6, fmt(verdict_lbl), align="C")
    pdf.set_y(y + 52)

    # بطاقات موجزة
    cards = [
        (str(stats['total_pages']), T['m_pages'], C_INK),
        (str(stats['products']), T['m_products'], C_INK),
        (str(stats['categories']), T['m_cats'], C_INK),
        (str(stats.get('total_images', 0)), T['m_images'], C_INK),
        (str(stats.get('critical_titles', 0) + stats.get('missing_alts', 0)),
         T['m_issues'], C_BAD),
    ]
    gap, cw = 4, (W - 2 * 4) / 3
    y0 = pdf.get_y()
    for i, (v, l, c) in enumerate(cards):
        col, row = i % 3, i // 3
        pdf.mini(M + col * (cw + gap), y0 + row * 24, cw, v, l, c)
    pdf.set_y(y0 + 56)

    # بيانات المتجر
    pdf.set_draw_color(*C_LINE)
    pdf.line(M, pdf.get_y(), 210 - M, pdf.get_y())
    pdf.ln(5)
    pdf.set_font(FONT, "", 10)
    pdf.set_text_color(*C_INK)
    for lbl, val in [(T['store'], clean_domain),
                     (T['platform'], stats.get('platform_label', '—')),
                     (T['date'], datetime.now().strftime('%Y-%m-%d'))]:
        pdf.set_x(M)
        pdf.cell(W, 6.5, fmt(f"{lbl}: {val}"), ln=True, align=ALIGN)
    pdf.ln(3)
    pdf.set_font(FONT, "", 8.5)
    pdf.set_text_color(*C_MUTED)
    pdf.set_x(M)
    pdf.cell(W, 5, fmt(T['scope']), ln=True, align=ALIGN)

    pdf.set_y(265)
    pdf.set_font(FONT, "", 9)
    pdf.set_text_color(*C_MUTED)
    pdf.cell(0, 5, fmt(T['prepared']), ln=True, align="C")
    pdf.cell(0, 5, "anasrashed.com   |   anas@anasrashed.com", align="C")

    n = 0

    # ======================= البنية =======================
    n += 1
    pdf.add_page()
    pdf.section(n, 'structure')
    pdf.table([
        ('إجمالي الصفحات المعروضة والمفحوصة' if rtl else 'Total visible pages audited',
         f"{stats['total_pages']} {T['u_page']}", 'neutral'),
        ('صفحات المنتجات' if rtl else 'Product pages',
         f"{stats['products']} {T['u_product']}", 'neutral'),
        ('صفحات الأقسام والكولكشنات' if rtl else 'Category and collection pages',
         f"{stats['categories']} {T['u_cat']}", 'neutral'),
        ('مقالات وصفحات المدونة' if rtl else 'Blog posts and articles',
         f"{stats.get('blog_pages', 0)} {T['u_article']}",
         'warn' if not stats.get('blog_pages') else 'neutral'),
        ('صفحات أرشيف (وسوم وقوائم)' if rtl else 'Archive pages (tags and lists)',
         f"{stats.get('archive_pages', 0)} {T['u_page']}",
         'warn' if stats.get('archive_pages', 0) > 20 else 'neutral'),
        ('الصفحات التعريفية والسياسات' if rtl else 'Info and policy pages',
         f"{stats['info_pages']} {T['u_page']}", 'neutral'),
        ('روابط منتجات محذوفة تُحوَّل للرئيسية' if rtl else
         'Deleted product URLs redirecting home',
         f"{stats.get('deleted_pages', 0)} {T['u_link']}",
         'bad' if stats.get('deleted_pages') else 'ok'),
        ('روابط لا تعمل تحتاج معالجة (404)' if rtl else 'Broken links to handle (404)',
         f"{stats.get('broken_actionable', 0)} {T['u_link']}",
         'bad' if stats.get('broken_actionable') else 'ok'),
        ('صفحات تعذّر الاتصال بها أثناء الفحص' if rtl else
         'Pages unreachable during the scan',
         f"{stats.get('unreachable_pages', 0)} {T['u_page']}",
         'warn' if stats.get('unreachable_pages') else 'ok'),
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
    tot = max(stats['total_pages'] - stats.get('broken_pages', 0), 1)
    ok_t = tot - stats['bad_titles']
    ok_d = tot - stats['bad_descs']
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
        ('أوصاف ضمن الطول المثالي (120-150)' if rtl else
         'Descriptions within optimal length (120-150)',
         (f"{ok_d} من {tot}" if rtl else f"{ok_d} of {tot}"),
         'ok' if ok_d / tot > 0.7 else 'warn'),
        ('أوصاف تحتاج إصلاحاً عاجلاً' if rtl else 'Descriptions needing urgent work',
         f"{stats.get('critical_descs', 0)} {T['u_desc']}",
         'bad' if stats.get('critical_descs') else 'ok'),
        ('صفحات بلا وسم كانونيكال' if rtl else 'Pages without a canonical tag',
         f"{stats.get('canon_missing', 0)} {T['u_page']}",
         'warn' if stats.get('canon_missing') else 'ok'),
    ])
    pdf.impact('meta')

    # ======================= الروابط =======================
    n += 1
    pdf.add_page()
    pdf.section(n, 'urls')
    good_u = max(tot - stats.get('url_bad', 0), 0)
    pdf.table([
        ('روابط سليمة الصياغة' if rtl else 'Well-formed URLs',
         (f"{good_u} من {tot}" if rtl else f"{good_u} of {tot}"),
         'ok' if good_u / tot > 0.8 else 'warn'),
        ('منتجات مستنسخة من منتج واحد' if rtl else 'Cloned products',
         f"{stats.get('url_clone', 0)} {T['u_product']}",
         'bad' if stats.get('url_clone') else 'ok'),
        ('صفحات بنفس العنوان والوصف حرفياً' if rtl else
         'Pages with identical title and description',
         f"{stats.get('dup_content', 0)} {T['u_page']}",
         'bad' if stats.get('dup_content') else 'ok'),
        ('روابط تحمل اسم منتج مختلف' if rtl else 'URLs naming a different product',
         f"{stats.get('url_wrongname', 0)} {T['u_link']}",
         'bad' if stats.get('url_wrongname') else 'ok'),
        ('روابط معطوبة فيها عنوان موقع' if rtl else 'Malformed URLs containing an address',
         f"{stats.get('url_malformed', 0)} {T['u_link']}",
         'bad' if stats.get('url_malformed') else 'ok'),
        ('روابط بأرقام أو رموز بلا كلمات' if rtl else 'URLs with no descriptive words',
         f"{stats.get('url_generic', 0)} {T['u_link']}",
         'warn' if stats.get('url_generic') else 'ok'),
        ('روابط بصياغة غير مثالية' if rtl else 'URLs with imperfect formatting',
         f"{stats.get('url_style', 0)} {T['u_link']}",
         'warn' if stats.get('url_style') else 'ok'),
    ])
    pdf.impact('urls')

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
        ('صيغ الصور المستخدمة' if rtl else 'Image formats in use', fmts, 'neutral'),
        ('نسبة الصور بالصيغ الحديثة الخفيفة' if rtl else
         'Share of modern lightweight formats',
         f"{stats.get('img_modern_pct', 0)}%",
         'ok' if stats.get('img_modern_pct', 0) > 50 else 'warn'),
    ])
    pdf.impact('images')

    # ======================= خريطة الموقع =======================
    if stats.get('coverage_enabled'):
        n += 1
        pdf.add_page()
        pdf.section(n, 'sitemap')
        pdf.table([
            ('روابط معلنة في خريطة الموقع' if rtl else 'URLs declared in sitemap',
             f"{stats.get('sitemap_products', 0)} {T['u_link']}", 'neutral'),
            ('منها تعمل ويصل إليها الزائر' if rtl else 'Of those, live and reachable',
             f"{stats.get('sitemap_live', 0)} {T['u_link']}", 'neutral'),
            ('صفحات في الخريطة لا يصل إليها الزائر' if rtl else
             'Sitemap pages with no internal link',
             f"{stats.get('hidden_count', 0)} {T['u_page']}",
             'warn' if stats.get('hidden_count') else 'ok'),
            ('منتجات لا تظهر روابطها إلا بالتمرير' if rtl else
             'Products linked only via scrolling',
             f"{stats.get('scroll_only_count', 0)} {T['u_product']}",
             'warn' if stats.get('scroll_only_count') else 'ok'),
            ('صفحات معروضة وغير مدرجة في الخريطة' if rtl else
             'Live pages missing from the sitemap',
             f"{stats.get('unlisted_count', 0)} {T['u_page']}",
             'bad' if stats.get('unlisted_count') else 'ok'),
            ('نسبة المنتجات المعروضة المدرجة' if rtl else
             'Visible products included in sitemap',
             f"{stats.get('indexed_pct', 0)}%",
             'ok' if stats.get('indexed_pct', 0) >= 95 else 'warn'),
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
    for pt in points:
        lines = pdf.wrap(pt, W - 10, 9)
        need = len(lines) * 5 + 3
        if pdf.get_y() + need > 262:
            pdf.add_page()
        y = pdf.get_y()
        pdf.set_fill_color(*C_INK)
        dot = (210 - M - 2.4) if rtl else M
        pdf.rect(dot, y + 1.6, 2.4, 2.4, 'F')
        pdf.set_font(FONT, "", 9)
        pdf.set_text_color(*C_MUTED)
        for i, line in enumerate(lines):
            pdf.set_xy(M if rtl else M + 6, y + i * 5)
            pdf.cell(W - 6, 5, fmt(line), align=ALIGN)
        pdf.set_y(y + len(lines) * 5 + 2.5)
    pdf.ln(3)

    lines = pdf.wrap(close, W - 14, 9.5)
    h = len(lines) * 5.2 + 8
    if pdf.get_y() + h > 265:
        pdf.add_page()
    y = pdf.get_y()
    pdf.set_fill_color(*C_BG)
    pdf.rect(M, y, W, h, 'F')
    pdf.set_fill_color(*verdict_rgb)
    if rtl:
        pdf.rect(210 - M - 2.2, y, 2.2, h, 'F')
    else:
        pdf.rect(M, y, 2.2, h, 'F')
    pdf.set_font(FONT, "", 9.5)
    pdf.set_text_color(*C_INK)
    yy = y + 4
    for line in lines:
        pdf.set_xy(M + 7, yy)
        pdf.cell(W - 14, 5.2, fmt(line), align=ALIGN)
        yy += 5.2

    return bytes(pdf.output())



# ==============================================================
#  التسعير والفاتورة
#  أسعار السوق السعودي لخدمة إعادة تهيئة المتجر لمحركات البحث.
#  الأسعار قابلة للتعديل من الواجهة قبل إصدار الفاتورة.
# ==============================================================
DEFAULT_PRICES = {
    'meta_title': 15.0,   # عنوان الميتا + الرابط: خدمة واحدة لكل صفحة
    'meta_desc': 10.0,    # وصف الميتا لكل صفحة
    'image_alt': 5.0,     # النص البديل لكل صورة
    'redirect_fix': 5.0,       # تحويل 301 لرابط معطل له بديل قريب (زد)
    'internal_link_fix': 5.0,  # تصحيح رابط داخلي يقود لصفحة غير موجودة
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
    redirects = int(summary.get('redirect_qty', 0))
    internal = int(summary.get('internal_fix_qty', 0))

    items = []
    if titles:
        items.append({'key': 'meta_title', 'qty': titles, 'unit': pr['meta_title']})
    if descs:
        items.append({'key': 'meta_desc', 'qty': descs, 'unit': pr['meta_desc']})
    if alts:
        items.append({'key': 'image_alt', 'qty': alts, 'unit': pr['image_alt']})
    if redirects:
        items.append({'key': 'redirect_fix', 'qty': redirects, 'unit': pr['redirect_fix']})
    if internal:
        items.append({'key': 'internal_link_fix', 'qty': internal, 'unit': pr['internal_link_fix']})
    for it in items:
        it['total'] = round(it['qty'] * it['unit'], 2)

    subtotal = round(sum(i['total'] for i in items), 2)
    units = titles + descs + alts + redirects + internal
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
        'meta_title_d': 'صياغة عنوان بحثي لكل صفحة ضمن الطول المثالي، '
                        'مع ضبط الرابط ليكون وصفياً ومطابقاً للمنتج',
        'meta_desc': 'كتابة أوصاف الميتا',
        'meta_desc_d': 'وصف تسويقي لكل صفحة ضمن الطول المثالي يرفع نسبة النقر '
                       'من نتائج البحث',
        'image_alt': 'كتابة النصوص البديلة للصور',
        'image_alt_d': 'وصف دقيق لكل صورة يُظهرها في بحث صور جوجل',
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
        'meta_title_d': 'A search-optimised title for each page within the ideal '
                        'length, with the URL corrected to match the product',
        'meta_desc': 'Meta descriptions',
        'meta_desc_d': 'A marketing description per page within the ideal length '
                       'to raise click-through from search results',
        'image_alt': 'Image alt texts',
        'image_alt_d': 'A precise description per image so it appears in '
                       'Google Image search',
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

    fmt = (lambda t: str(t)) if (rtl and HAS_SHAPING) else (shape_ar if rtl else _latin)
    if not rtl:
        fmt = _latin
    FONT = AR_FONT_NAME if rtl else "Helvetica"
    B = "B" if (FONT_BOLD_PATH if rtl else True) else ""
    ALIGN = "R" if rtl else "L"
    M, W = 18, 174
    dom = urlparse(domain).netloc or domain
    riyal = RIYAL_PATH.exists()

    pdf = FPDF()
    if rtl:
        pdf.add_font(AR_FONT_NAME, "", str(FONT_PATH))
        if FONT_BOLD_PATH:
            pdf.add_font(AR_FONT_NAME, "B", str(FONT_BOLD_PATH))
        if HAS_SHAPING:
            pdf.set_text_shaping(True, direction="rtl")
    pdf.set_auto_page_break(True, margin=18)
    pdf.add_page()

    def money(value, x, w, y, size=10, bold=False, color=C_MUTED, center=True):
        """يكتب المبلغ ثم رمز الريال بجانبه بحجم متناسب مع الخط."""
        txt = f"{value:,.0f}"
        pdf.set_font(FONT, B if bold else "", size)
        pdf.set_text_color(*color)
        sym_h = size * 0.30
        sym_w = sym_h * 0.92
        gap = 1.2
        tw = pdf.get_string_width(txt)
        total = tw + (sym_w + gap if riyal else
                      pdf.get_string_width(" " + T['currency']))
        start = x + (w - total) / 2 if center else x
        pdf.set_xy(start, y)
        pdf.cell(tw, size * 0.5, txt, 0, 0, 'L')
        if riyal:
            try:
                pdf.image(str(RIYAL_PATH), x=start + tw + gap,
                          y=y + (size * 0.5 - sym_h) / 2 + 0.2, h=sym_h)
            except Exception:
                pass
        else:
            pdf.set_xy(start + tw, y)
            pdf.cell(total - tw, size * 0.5, fmt(T['currency']), 0, 0, 'L')

    # ---------- الترويسة: الشعار وتحته الرابط والبريد ----------
    head_y = 14
    if LOGO_PATH.exists():
        try:
            pdf.image(str(LOGO_PATH), x=(M if rtl else 210 - M - 34), y=head_y, h=12)
        except Exception:
            pass
    pdf.set_font(FONT, "", 8.5)
    pdf.set_text_color(*C_MUTED)
    pdf.set_xy(M if rtl else 210 - M - 60, head_y + 14)
    pdf.cell(60, 4.5, "anasrashed.com", 0, 2, "L" if rtl else "R")
    pdf.cell(60, 4.5, "anas@anasrashed.com", 0, 0, "L" if rtl else "R")

    # العنوان في الجهة المقابلة للشعار حتى لا يتداخلا
    tx = (M + 70) if rtl else M
    tw = W - 70
    pdf.set_xy(tx, head_y + 1)
    pdf.set_font(FONT, B, 20)
    pdf.set_text_color(*C_INK)
    pdf.cell(tw, 9, fmt(T['title']), 0, 2, ALIGN)
    pdf.set_font(FONT, "", 10)
    pdf.set_text_color(*C_MUTED)
    pdf.cell(tw, 6, fmt(T['sub']), 0, 0, ALIGN)

    pdf.set_y(head_y + 24)
    pdf.set_draw_color(*C_LINE)
    pdf.line(M, pdf.get_y(), 210 - M, pdf.get_y())
    pdf.ln(5)

    ref = datetime.now().strftime('%Y%m%d-') + f"{abs(hash(dom)) % 9000 + 1000}"
    pdf.set_font(FONT, "", 10)
    pdf.set_text_color(*C_INK)
    for lbl, val in [(T['to'], store_name or dom), (T['no'], ref),
                     (T['date'], datetime.now().strftime('%Y-%m-%d'))]:
        pdf.set_x(M)
        pdf.cell(W, 6.2, fmt(f"{lbl}: {val}"), ln=True, align=ALIGN)
    pdf.ln(4)

    # ---------- جدول البنود ----------
    wq, wu, wt = 24, 32, 32
    wn = W - wq - wu - wt
    pdf.set_fill_color(*C_INK)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font(FONT, B, 9.5)
    pdf.set_x(M)
    heads = ([(T['h_total'], wt), (T['h_unit'], wu), (T['h_qty'], wq),
              (T['h_item'], wn)] if rtl else
             [(T['h_item'], wn), (T['h_qty'], wq), (T['h_unit'], wu),
              (T['h_total'], wt)])
    for i, (h, w) in enumerate(heads):
        pdf.cell(w, 8, fmt(h), 0, 1 if i == len(heads) - 1 else 0,
                 'C' if w != wn else ALIGN, fill=True)

    for idx, it in enumerate(quote['items']):
        name = T[it['key']]
        unit_lbl = {'image_alt': T['unit_img'],
                    'redirect_fix': T['unit_link'],
                    'internal_link_fix': T['unit_link']}.get(it['key'], T['unit_page'])
        pdf.set_font(FONT, "", 8.5)
        lines, cur = [], ""
        for word in T[it['key'] + '_d'].split():
            trial = (cur + " " + word).strip()
            if pdf.get_string_width(fmt(trial)) <= wn - 4:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
        h = 7.5 + len(lines) * 4.4 + 2
        y = pdf.get_y()
        if idx % 2 == 0:
            pdf.set_fill_color(*C_BG)
            pdf.rect(M, y, W, h, 'F')
        pdf.set_font(FONT, B, 10)
        pdf.set_text_color(*C_INK)
        if rtl:
            money(it['total'], M, wt, y + 2, 10, True, C_INK)
            money(it['unit'], M + wt, wu, y + 2, 10, False, C_MUTED)
            pdf.set_xy(M + wt + wu, y + 1.5)
            pdf.set_font(FONT, "", 10)
            pdf.set_text_color(*C_MUTED)
            pdf.cell(wq, 6, fmt(f"{it['qty']} {unit_lbl}"), 0, 0, 'C')
            pdf.set_font(FONT, B, 10)
            pdf.set_text_color(*C_INK)
            pdf.cell(wn, 6, fmt(name), 0, 1, 'R')
        else:
            pdf.set_xy(M, y + 1.5)
            pdf.cell(wn, 6, fmt(name), 0, 0, 'L')
            pdf.set_font(FONT, "", 10)
            pdf.set_text_color(*C_MUTED)
            pdf.cell(wq, 6, fmt(f"{it['qty']} {unit_lbl}"), 0, 0, 'C')
            money(it['unit'], M + wn + wq, wu, y + 2, 10, False, C_MUTED)
            money(it['total'], M + wn + wq + wu, wt, y + 2, 10, True, C_INK)
        pdf.set_font(FONT, "", 8.5)
        pdf.set_text_color(*C_MUTED)
        yy = y + 8
        for ln_ in lines:
            pdf.set_xy(M + (0 if rtl else 2), yy)
            pdf.cell(wn, 4.4, fmt(ln_), 0, 0, ALIGN)
            yy += 4.4
        pdf.set_y(y + h)
        pdf.set_draw_color(*C_LINE)
        pdf.line(M, pdf.get_y(), 210 - M, pdf.get_y())

    # ---------- المجاميع ----------
    pdf.ln(4)
    rows = [(T['subtotal'], quote['subtotal'], False)]
    if quote['discount']:
        rows.append((f"{T['discount']} {int(quote['discount_rate'] * 100)}%",
                     -quote['discount'], False))
    rows.append((T['total'], quote['total'], True))
    for lbl, val, strong in rows:
        y = pdf.get_y()
        pdf.set_font(FONT, B if strong else "", 12 if strong else 10)
        pdf.set_text_color(*(C_INK if strong else C_MUTED))
        if rtl:
            pdf.set_xy(M + 60, y)
            pdf.cell(W - 60, 8, "", 0, 0)
            money(val, M, 70, y + 1.5, 12 if strong else 10, strong,
                  C_INK if strong else C_MUTED, center=False)
            pdf.set_xy(M + 90, y)
            pdf.cell(W - 90, 8, fmt(lbl), 0, 1, 'R')
        else:
            pdf.set_xy(M, y)
            pdf.cell(70, 8, fmt(lbl), 0, 0, 'L')
            money(val, M + 80, 70, y + 1.5, 12 if strong else 10, strong,
                  C_INK if strong else C_MUTED, center=False)
            pdf.ln(8)
    pdf.set_font(FONT, "", 8.5)
    pdf.set_text_color(*C_MUTED)
    pdf.set_x(M)
    pdf.cell(W, 5, fmt(T['novat']), ln=True, align=ALIGN)
    pdf.ln(4)

    # ---------- الدفع ----------
    y = pdf.get_y()
    pdf.set_fill_color(*C_BG)
    pdf.rect(M, y, W, 25, 'F')
    pdf.set_font(FONT, B, 10)
    pdf.set_text_color(*C_INK)
    pdf.set_xy(M + 5, y + 3)
    pdf.cell(W - 10, 6, fmt(T['pay']), ln=True, align=ALIGN)
    pdf.set_font(FONT, "", 9.5)
    pdf.set_text_color(*C_MUTED)
    for lbl, val in [(T['iban'], PAYMENT['iban']), (T['stc'], PAYMENT['stc'])]:
        pdf.set_x(M + 5)
        pdf.cell(W - 10, 6, fmt(f"{lbl}: {val}"), ln=True, align=ALIGN)
    pdf.set_y(y + 29)

    pdf.set_font(FONT, "", 8.5)
    pdf.set_text_color(*C_MUTED)
    for line in (T['scope'], T['note'], T['valid']):
        pdf.set_x(M)
        pdf.cell(W, 5, fmt(line), ln=True, align=ALIGN)
    return bytes(pdf.output())


# ==============================================================
