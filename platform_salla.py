"""قواعد منصة سلة — عدّل هنا ما يخص متاجر سلة فقط، دون أن يتأثر زد أو شوبيفاي.

سلة تضع رقماً ثابتاً في آخر كل رابط:
  منتج  /اسم-المنتج/p123456      قسم   /اسم-القسم/c123456
  ماركة /اسم-الماركة/brand-123   صفحة  /اسم-الصفحة/page-123
  مقال  /blog/عنوان-المقال/a-123
فالرابط يبقى نفس الصفحة حتى لو تغيّر الاسم، وسلة تحوّل الاسم القديم تلقائياً.
"""
import re

NAME = 'salla'

PRODUCT_ID_RE = re.compile(r'^p-?\d{3,}$', re.I)
CATEGORY_ID_RE = re.compile(r'^c-?\d{3,}$', re.I)
INFO_ID_RE = re.compile(r'^page-?\d+$', re.I)
BRAND_ID_RE = re.compile(r'^brand-?\d+$', re.I)
ARTICLE_ID_RE = re.compile(r'^a-?\d{4,}$', re.I)
# مفتاح الصفحة: الرقم الثابت، لا الاسم
PLATFORM_ID_RE = re.compile(r'^(p|c|a|page|tag|category|product|brand)-?(\d{4,})$', re.I)

# أسماء ملفات خرائط إضافية تُجرَّب دائماً (سلة تعلن خرائطها في robots.txt عادة)
SITEMAP_NAMES = []


def url_key(segs, host):
    """مفتاح موحّد للصفحة برقمها الثابت، أو None إن لم يكن الرابط بصيغة سلة."""
    if segs:
        mo = PLATFORM_ID_RE.match(segs[-1])
        if mo:
            return f"{host}/#{mo.group(1).lower()}{mo.group(2)}"
    return None


def decisive_type(segs, T):
    """نوع الصفحة من رقمها الثابت. T: أنواع الصفحات من المحرك العام."""
    if not segs:
        return ''
    last = segs[-1]
    if PRODUCT_ID_RE.match(last):
        return T['product']
    if BRAND_ID_RE.match(last) or CATEGORY_ID_RE.match(last):
        return T['category']
    if INFO_ID_RE.match(last):
        return T['info']
    if ARTICLE_ID_RE.match(last) and len(segs) >= 2:
        return T['blog']
    return ''


def is_product_subpage(segs):
    return False
