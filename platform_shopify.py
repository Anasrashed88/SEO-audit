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
