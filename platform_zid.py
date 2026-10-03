"""قواعد منصة زد — عدّل هنا ما يخص متاجر زد فقط، دون أن يتأثر سلة أو شوبيفاي.

ما تعلمناه من متاجر زد حقيقية (أفكار، KS FURNITURE، مدهال، اروماتك):
- الأقسام برقم ثابت: /categories/1689986/ و/categories/1689986/اسم-القسم = قسم واحد.
- الخرائط غالباً غير معلنة في robots.txt، وبعضها في مجلدات فرعية (blog/، brands/).
- لكل منتج صفحة مراجعات فرعية /products/<رقم>/reviews ليست منتجاً.
- بادئات اللغة بالدولة (/ar-sa/، /en-sa/) يعالجها المحرك العام لكل المنصات.
"""
NAME = 'zid'

SITEMAP_NAMES = [
    'sitemap_products.xml', 'sitemap_categories.xml', 'sitemap_pages.xml', 'sitemap_blogs.xml',
    'blog/sitemap.xml', 'blogs/sitemap.xml', 'brands/sitemap.xml', 'pages/sitemap.xml',
]

# صفحات فرعية تصنعها زد لكل منتج: ليست منتجات، والتاجر لا يتحكم في عناوينها
PRODUCT_SUBPAGES = {'reviews', 'review', 'ratings', 'rating', 'questions', 'qa'}


def url_key(segs, host):
    """القسم برقمه الثابت، أو None."""
    low = [x.lower() for x in segs]
    if len(low) >= 2 and low[0] in ('categories', 'category') and low[1].isdigit():
        return f"{host}/#cat{low[1]}"
    return None


def decisive_type(segs, T):
    return ''


def is_product_subpage(segs):
    low = [x.lower() for x in segs]
    return len(low) >= 3 and low[0] in ('products', 'product') and low[-1] in PRODUCT_SUBPAGES
