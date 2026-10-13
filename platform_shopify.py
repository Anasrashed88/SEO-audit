"""قواعد منصة شوبيفاي — عدّل هنا ما يخص متاجر شوبيفاي فقط، دون أن يتأثر زد أو سلة.

هذا الملف جاهز للمرحلة القادمة. نضيف قواعده من فحص متاجر شوبيفاي حقيقية.
ما نعرفه مبدئياً:
- الخرائط مرقّمة: sitemap_products_1.xml، sitemap_collections_1.xml ...
- الأقسام اسمها collections: /collections/اسم-القسم (يعالجها المحرك العام).
"""
NAME = 'shopify'

SITEMAP_NAMES = [
    'sitemap_products_1.xml', 'sitemap_collections_1.xml', 'sitemap_pages_1.xml', 'sitemap_blogs_1.xml',
]


def url_key(segs, host):
    return None


def decisive_type(segs, T):
    return ''


def is_product_subpage(segs):
    return False


# ---------------- قواعد الفحص الخاصة بشوبيفاي (تعمل فقط حين يُكتشف المتجر شوبيفاي) ----------------
import re as _re
from urllib.parse import urlparse as _urlparse, unquote as _unquote

# ملفات تصنعها شوبيفاي وليست صفحات: بيانات المشاركة، والأخبار، وملف وكلاء الذكاء الاصطناعي
JUNK_EXT = ('.oembed', '.atom', '.rss', '.json', '.js', '.md')


def skip_url(url):
    """روابط لا تُفحص في شوبيفاي:
    - ملفات ليست صفحات (.oembed و/agents.md ...).
    - بقايا أزرار المشاركة: رابط المنتج داخل رابط تويتر أو بنترست، فيلتصق به &via= أو &amp.
    - نص وصف قرأه الكود رابطاً (فيه مسافات)."""
    path = _unquote(_urlparse(str(url)).path)
    low = path.lower()
    if low.endswith(JUNK_EXT):
        return True
    if '&' in path or ' ' in path or '"' in path or '<' in path:
        return True
    # /collections/قسم/products/منتج = نفس المنتج /products/منتج بعنوان ثانٍ: نفحص الأصلي فقط
    segs = [x for x in low.split('/') if x]
    if len(segs) >= 4 and segs[0] == 'collections' and segs[2] == 'products':
        return True
    return False


# شوبيفاي تضع حجم الصورة في اسم الملف: photo_1600x.jpg وphoto_2000x.jpg = صورة واحدة
_SIZE_SUFFIX = _re.compile(r'_(?:\d{2,4}x\d{0,4}|x\d{2,4})(?:@\dx)?(?:_crop_[a-z]+)?$')


def image_stem_extra(base):
    return _SIZE_SUFFIX.sub('', base)


def fetch_products(base_url, get, max_pages=40):
    """قائمة المنتجات المنشورة من /products.json (عامة في شوبيفاي): عددها الرسمي، ووصف كل منتج.
    يعيد None إن كان الملف مغلقاً في هذا المتجر، فتعمل الأداة كالمعتاد."""
    import json as _json
    out = []
    root = str(base_url).rstrip('/')
    for page in range(1, max_pages + 1):
        try:
            r = get(f'{root}/products.json?limit=250&page={page}')
            if getattr(r, 'status_code', 0) != 200:
                return out or None
            items = _json.loads(r.text).get('products') or []
        except Exception:
            return out or None
        if not items:
            break
        out.extend(items)
        if len(items) < 250:
            break
    return out


def product_descriptions(products):
    """{handle: وصف المنتج كنص عادي} — يكتب منه الذكاء الاصطناعي بدل المقتطف."""
    out = {}
    for p in products or []:
        t = _re.sub(r'<[^>]+>', ' ', str(p.get('body_html') or ''))
        t = t.replace('&nbsp;', ' ').replace('&amp;', '&')
        out[str(p.get('handle') or '').lower()] = _re.sub(r'\s+', ' ', t).strip()[:1200]
    return out
