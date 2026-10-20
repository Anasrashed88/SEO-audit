import sys, json; sys.path.insert(0, '/home/claude/work')
import pandas as pd, audit_engine as e, export_utils as x, pdf_generator as g
fails = []
def check(n, c):
    print(('✅' if c else '❌'), n); c or fails.append(n)
B = 'https://s.com'
k = e.url_key(B + '/عباية/p1234567')
check('صيغ الرابط الواحد = صفحة واحدة', all(e.url_key(v) == k for v in ['http://www.s.com/%D8%B9%D8%A8%D8%A7%D9%8A%D8%A9/p1234567/', B + '/ar/عباية/p1234567?utm=1']))
check('زد /ar-sa/', e.url_key(B + '/ar-sa/products/Snow-White') == e.url_key(B + '/products/snow-white'))
check('أنواع الروابط القاطعة', [e.decisive_type(B + u) for u in ['/x/brand-1460042538', '/blog/m/a-12345', '/x/page-5555', '/products/y']] == ['category', 'blog', 'info', 'product'])
check('زد: القسم برقمه مع اسمه وبدونه = قسم واحد', e.url_key(B + '/categories/1689986/') == e.url_key(B + '/categories/1689986/عروض') != e.url_key(B + '/categories/51962/سرير'))
check('الماركة ليست قسماً', [e.listing_kind(B + u) for u in ['/x/brand-146004', '/latest-products', '/c/c1906874517']] == ['brand', 'listing', 'category'])
d = pd.DataFrame([{'متاحة': True, 'طول العنوان': 55, 'حالة العنوان': 'optimal', 'طول الوصف': n, 'حالة الوصف': 'long'} for n in (155, 165)])
check('الوصف 155 سليم و165 طويل', list(e.regrade_lengths(d)['حالة الوصف']) == ['optimal', 'long'])
check('وصف صور عام/رموز/فارغ', [e.grade_alt(a)[0] for a in ('Link Image', '---', '', 'عباية سوداء')] == ['alt_generic', 'alt_generic', 'alt_missing', 'alt_ok'])
names = ['طقم هدية قهوة زجاج وسيراميك', 'غلاية من ستانليس ستيل', 'أداة فتح المعلبات والقارورات 5 في 1 بنفسجي',
         'أداة فتح المعلبات والقارورات 5 في 1 برتقالي', 'كوب قهوة النمو 350 مل', 'كوب قهوة خزفي لون أخضر مطفي', 'مفتاح علب ستانلس']
pdf_ = pd.DataFrame([{'الرابط': B + f'/products/p{i}', 'نوع الصفحة': 'product', 'متاحة': True, 'اسم المنتج المعروض': n, 'اسم منظم': ''} for i, n in enumerate(names)])
im = pd.DataFrame([{'رابط الصفحة': B + f'/products/p{p}', 'نوع الصفحة': 'product', 'رابط الصورة': f'i{j}', 'النص البديل الحالي (Alt)': a, '_own': True, 'حالة النص البديل': 'alt_ok'}
                   for j, (p, a) in enumerate([(0, 'غلاية من ستانليس ستيل'), (2, 'أداة فتح المعلبات والقارورات 5 في 1 برتقالي'), (2, 'مفتاح علب'), (4, 'كوب قهوة خزفي لون أخضر')])])
check('طقم/ألوان/اسم بديل سليم، واسم منتج آخر خطأ', list(e.mark_wrong_product_alts(im, pdf_)['حالة النص البديل']) == ['alt_ok', 'alt_ok', 'alt_ok', 'alt_wrong_product'])
gal = pd.DataFrame([{'رابط الصفحة': B + '/products/p1', 'نوع الصفحة': 'product', 'رابط الصورة': f'g{i}', 'النص البديل الحالي (Alt)': 'عباية كلوش', 'حالة النص البديل': 'alt_ok'} for i in range(5)]
                   + [{'رابط الصفحة': B + '/blog/x', 'نوع الصفحة': 'blog', 'رابط الصورة': f'b{i}', 'النص البديل الحالي (Alt)': 'عنوان المقال', 'حالة النص البديل': 'alt_ok'} for i in range(3)])
check('معرض المنتج سليم وتكرار صور المقال مكرر', list(e.apply_duplicate_alt(gal)['حالة النص البديل']) == ['alt_ok'] * 5 + ['alt_page_dup'] * 3)
rows = []
for u, t in [(B, 'متجر العناية'), (B + '/a/p3000004', 'كريم مرطب | متجر العناية'), (B + '/a/p3000005', 'كريم مرطب | متجر العناية'), (B + '/a/p3000007', 'سمرز ايف غسول نسائي ليلي برائحة الزهور 266 جم - كوبون خصم | متجر العناية')]:
    rows.append({'الرابط': u, 'نوع الصفحة': 'home' if u == B else 'product', 'متاحة': True, 'عنوان الميتا': t, 'طول العنوان': len(t), 'حالة العنوان': e.grade_length(len(t), 30, 50, 60),
                 'وصف الميتا': 'و' * 130, 'طول الوصف': 130, 'حالة الوصف': 'optimal', 'حالة المحتوى': 'good', 'اسم المنتج المعروض': 'متجر العناية' if u == B else '', 'درجة السيو': 50, 'الرابط الكانوني': ''})
tq, _ = e.analyze_text_quality(pd.DataFrame(rows)); reasons = ' | '.join(x.build_titles_urls_list(tq, 'ar', 'salla')['ما يحتاج إصلاحاً'])
check('أسباب العناوين قابلة للقياس فقط', 'ترويجي' not in reasons and 'طويل (' in reasons and 'مكرر في صفحتين' in reasons and 'اسم المتجر فقط' in reasons)
check('العدد والمعدود', [g.ar_counts(t) for t in ('3 عنوان', '15 منتج', '101 منتج')] == ['3 عناوين', '15 منتجاً', '101 منتج'])
check('روابط الملفات قابلة للفتح', x.clickable_urls(pd.DataFrame({'الرابط': [B + '/blog/اي سي ام/a-1']}))['الرابط'][0].count('%20') == 2)
A = 'https://matjar-afkar.com'
live = ['/products/bifold-practical-wallet-pink', '/products/women-wallet-leaves-Sky-Blue', '/categories/3323/cups', '/products']
brk = ['/products/Bifold-Practical-Wallet-Sky-Blue', '/products/c3323', '/products/zzz-unknown']
rr = [{'الرابط': A + u, 'نوع الصفحة': e._detect_type_by_url(A + u, A), 'متاحة': True, 'اسم المنتج المعروض': '', 'كود الاستجابة': 200, 'سلسلة التحويل': '', 'الوجهة النهائية': '', 'قابلة للأرشفة': True} for u in live]
rr += [{'الرابط': A + u, 'نوع الصفحة': 'broken', 'نوع الرابط': 'product', 'متاحة': False, 'اسم المنتج المعروض': '', 'كود الاستجابة': 'خطأ 404', 'سلسلة التحويل': '', 'الوجهة النهائية': '', 'قابلة للأرشفة': True} for u in brk]
bdf = pd.DataFrame(rr); sg = e.suggest_alternatives(bdf)
check('بديل الرابط المعطل: نفس المنتج، ورقم القسم، ولا اختراع', [sg.get(i, ('',))[0].split('.com')[-1] for i in bdf[e.broken_no_redirect_mask(bdf)].index] == ['/products/bifold-practical-wallet-pink', '/categories/3323/cups', ''])
M = 'https://midhal-oud.store'
h = f'<a href="/products/Women-Leaves-Black-">x</a><script>var d={json.dumps({"u": M + "/products/copy-of-مبخرة"})};var t={json.dumps({"t": "عروض 🔥"})};</script><p>{chr(0xD83D)}</p>'
l = {e.unquote(u).split('.store')[1] for u in e.extract_all_links(e.make_soup(h), h, M + '/', 'midhal-oud.store')}
check('حروف عربية ورموز مشفرة: لا قطع ولا انهيار', '/products/copy-of-مبخرة' in l and '/products/copy-of-' not in l and '/products/Women-Leaves-Black-' in l)
z = ''.join(f'<img srcset="https://media.zid.store/cdn-cgi/image/w=620,q=85/b/p{i}.jpg 620w, https://media.zid.store/cdn-cgi/image/w=1240/b/p{i}.jpg 1240w">' for i in range(3))
check('صور زد بروابط التحجيم', {e.clean_image_url(e.get_image_src(t)) for t in e.make_soup(z).find_all('img')} == {f'https://media.zid.store/b/p{i}.jpg' for i in range(3)})
lz = e.make_soup('<img src="data:x" data-lazyload="https://c.com/a.jpg"><img src=""><noscript><img src="https://c.com/c.jpg"></noscript>')
check('صور مؤجلة التحميل و noscript', [e.get_image_src(t) for t in lz.find_all('img') if t.parent.name != 'noscript'] == ['https://c.com/a.jpg', 'https://c.com/c.jpg'])
_df = pd.DataFrame([{'الرابط': f'https://z.com/products/p{i}', 'نوع الصفحة': 'product', 'متاحة': True, 'عنوان الميتا': f'م {i}', 'وصف الميتا': f'و {i}'} for i in range(20)])
_bad = pd.DataFrame([{'رابط الصفحة': f'https://z.com/products/p{i}', 'رابط الصورة': 'https://media.zid.store/cdn-cgi/image/w=620'} for i in range(20)])
_ok = pd.DataFrame([{'رابط الصفحة': f'https://z.com/products/p{i}', 'رابط الصورة': f'https://m.z/{i}-{j}.jpg'} for i in range(20) for j in range(2)])
check('كاشف قراءة القالب', len(e.template_reading_checks(_df, _bad)) >= 2 and not e.template_reading_checks(_df, _ok))
check('إعلان المتجر «إجمالي N منتجات»', [e.extract_declared_count(e.make_soup(f'<p>{t}</p>')) for t in ('إجمالي 8 منتجات', 'اجمالي ٣٥ منتج', 'Total 120 products')] == [8, 35, 120])

import io as _io
_t = pd.DataFrame({'م': range(1, 1726), 'رابط الصورة': [f'https://m.z/{i}.jpg' for i in range(1725)]})
import zipfile as _zf
_d, _m, _n = x.table_payload('00_صور_بلا_وصف.csv', _t)
_z = _zf.ZipFile(_io.BytesIO(_d))
check('CSV: كل 500 صف في ملف داخل ZIP ولا يضيع صف (1725 = 500+500+500+225)', _n.endswith('.zip') and [len(pd.read_csv(_io.BytesIO(_z.read(f)))) for f in _z.namelist()] == [500, 500, 500, 225])
check('ملف تحويلات زد يبقى Excel', x.table_payload('8_ملف_تحويلات_زد_للاستيراد.xlsx', _t.head(3))[2].endswith('.xlsx'))
import pdf_generator as _g
_st = {'fix_titles_urls': 48, 'fix_descs': 30, 'missing_alts': 81, 'weak_alts': 0, 'broken_actionable': 3, 'platform': 'zid'}
_pq = _g.build_quote(_st, package={'label': 'ص', 'price': 990})
check('التسعير: خدمة منفردة، وباقة بقيمة مرجعية، وحدود العينة', _g.build_quote(_st, services=['image_alt'])['total'] == 405
      and _pq['total'] == 990 and _pq['reference'] == 1296 and [_g.sample_size(n) for n in (2, 10, 20, 3000)] == [2, 3, 5, 10]
      and _g.package_for(62)['price'] == 990 and _g.package_for(3296)['price'] is None)

_fx = pd.DataFrame([{'الرابط': 'https://m.s/pages/سياسة-الخصوصية', 'نوع الصفحة': 'info', 'متاحة': True, 'عنوان الميتا': t, 'حالة العنوان': 'short', 'جودة العنوان': q}
                    for t, q in (('[-]', 'q_symbols'), ('سياسة الخصوصية', 'q_ok'))])
check('الصفحات الثابتة: تُصلح فقط إن كان عنوانها بلا معنى، وعنوانها اسمها المعروف',
      list(e.title_url_fix_mask(_fx)) == [True, False] and e.fixed_page_title('https://m.s/blogs', '', 'archive') == 'المدونة'
      and e.fixed_page_title('https://m.s/pages/تواصل-معنا', '', 'info') == 'تواصل معنا' and e.fixed_page_title('https://m.s/products/x', '', 'product') == '')

import ai_writer as _ai
from urllib.parse import quote as _q, unquote as _uq
_M = 'https://midhal-oud.store/products/'
_pr = [('copy-of-copy-of-مبخرة-خشبية', 'مبخرة خشبية بنقش ذهبي'), ('بوكس-المها-1', 'بوكس فيروز'), ('بوكس-المها', 'بوكس المها'),
       ('مبخرة-حائلية-لون-فضي-1', 'مبخرة حائلية خشبية'), ('6deef1ae', 'مجموعة لك ولها'), ('مبخره-خشبيه-صغيره', 'مبخرة خشبية صغيرة'), ('عطر-100-مل', 'عطر 100 مل')]
_dfu = pd.DataFrame([{'الرابط': _M + _q(a), 'نوع الصفحة': 'product', 'متاحة': True, 'اسم المنتج المعروض': b} for a, b in _pr])
_ch = _ai.url_changes(_dfu, {})
_new = [_uq(u).split('/products/')[1] for u in _ch['الرابط الجديد']]
check('الروابط: الحالات الواضحة فقط، والرابط الجديد عربي من العنوان',
      len(_ch) == 4 and 'اسم منتج آخر' in ' '.join(_ch['سبب التغيير']) and all(not any(c.isascii() and c.isalpha() for c in n) for n in _new)
      and _ai.zid_url_redirects(_ch)['التوجيه من'].iloc[0].startswith('/products/'))

import tempfile as _tf
_b = _tf.mkdtemp(); _U = 'https://m.s/products/a'
_ai.save_cache(_b, 'https://m.s', {'__meta__': {'model': 'm', 'suffix': ' | م', 'suffix_mode': 'add'},
    _U: {'title': 'عنوان', 'title_full': 'x', 'description': 'و' * 130, 'status': 'مطابق للقواعد', 'title_notes': '', 'desc_notes': ''}})
_n = _ai.apply_edits(_b, 'https://m.s', 'titles', [(_U, 'عنوان قصير')])
_c = _ai.load_cache(_b, 'https://m.s')[_U]
check('التعديل اليدوي: يُحفظ ويُعاد فحصه ويُعلَّم معدّلاً', _n == 1 and _c['title'] == 'عنوان قصير' and 'طول العنوان' in _c['title_notes'] and _c.get('edited'))

check('الصفحات الثابتة بالإنجليزية للصفحات الإنجليزية فقط',
      e.fixed_page_title('https://s.com/policies/privacy-policy', '', 'info', 'en') == 'Privacy Policy'
      and e.fixed_page_title('https://s.com/policies/privacy-policy', '', 'info', 'ar') == 'سياسة الخصوصية')
e.set_active_platform('shopify')
_shop_ok = (not e.is_crawlable('https://s.com/products/x.oembed', 's.com') and not e.is_crawlable('https://s.com/products/x&via=y', 's.com')
            and e.is_crawlable('https://s.com/products/x', 's.com'))
e.set_active_platform('zid')
check('قواعد شوبيفاي لا تعمل إلا في شوبيفاي', _shop_ok and e.is_crawlable('https://s.com/products/x.oembed', 's.com'))
e.set_active_platform(None)
print('\nكل الاختبارات ناجحة' if not fails else f'\nفشل: {fails}'); sys.exit(1 if fails else 0)
