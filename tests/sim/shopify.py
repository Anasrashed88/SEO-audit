# متجر شوبيفاي مثل المتاجر الثلاثة: .oembed، روابط مشاركة (&via و&amp)، نص كرابط، agents.md، صور بأحجام، و/products.json
from simlib import *
import json
B = 'https://shop.example.com'; N = 6
names = [f'cap-{i}' for i in range(N)]
def page(title, body):
    return (f'<html lang="en"><head><title>{title} – Example</title><meta name="description" content="Short">'
            f'<script>var Shopify = Shopify || {{}}; Shopify.theme = {{"name":"Dawn"}};</script>'
            f'<script src="https://cdn.shopify.com/s/x.js"></script></head><body><h1>{title}</h1>{body}</body></html>')
def fake(url, timeout=14, retries=2, headers=None):
    p = path_of(url)
    if url.endswith('/robots.txt'): return mk(url, 200, '', 'text/plain')
    if p == '/sitemap.xml': return mk(url, 200, f'<sitemapindex><sitemap><loc>{B}/sitemap_products_1.xml</loc></sitemap></sitemapindex>', 'application/xml')
    if p == '/sitemap_products_1.xml':
        return mk(url, 200, '<urlset>' + ''.join(f'<url><loc>{B}/products/{n}</loc></url>' for n in names) + '</urlset>', 'application/xml')
    if p == '/products.json':
        if 'page=1' in url:
            return mk(url, 200, json.dumps({'products': [{'handle': n, 'title': n, 'body_html': f'<p>Organic cotton cap {n}, handmade in Leeds.</p>'} for n in names + ['hidden-extra']]}), 'application/json')
        return mk(url, 200, json.dumps({'products': []}), 'application/json')
    if p in ('', '/'):
        return mk(url, 200, page('Home', ''.join(f'<a href="/products/{n}">{n}</a>' for n in names) + '<a href="/collections/caps">Caps</a><a href="/agents.md">ai</a>'))
    if p == '/collections/caps':
        return mk(url, 200, page('Caps', ''.join(f'<a href="/collections/caps/products/{n}">{n}</a>' for n in names)))
    if p.endswith('.oembed') or p.endswith('.md'): return mk(url, 200, '{}', 'application/json')
    if p.startswith('/collections/caps/products/') or p.startswith('/products/'):
        n = p.rsplit('/', 1)[-1]
        if n not in names + ['hidden-extra']: return mk(url, 404, 'nf')
        share = (f'<a href="https://twitter.com/intent/tweet?url={B}/products/{n}&via=example">t</a>'
                 f'<script>var s = "{B}/products/{n}&amp;media=x"; var d = "products/This pattern has docs";</script>'
                 f'<link rel="alternate" type="application/json+oembed" href="{B}/products/{n}.oembed">')
        imgs = ''.join(f'<img src="{B}/cdn/shop/files/{n}_{j}_{w}x.jpg?v=1" alt="">' for j in range(2) for w in (1600, 2000))
        return mk(url, 200, page(f'Cap {n}', share + imgs))
    return mk(url, 404, 'nf')
res = scan(fake, B)
df = res['df']
bad = df[df['متاحة'] == False]
print('platform:', res['summary']['platform'], '| failed pages:', len(bad), [path_of(u) for u in bad['الرابط']][:5])
print('hidden product discovered from products.json:', any('hidden-extra' in u for u in df[df['متاحة'] == True]['الرابط']))
print('products:', res['summary']['products'], '| RECON:', check_line(res, 'مطابقة الأرقام')[0]['msg'])
im = res['images_df']
print('unique missing-alt images:', im[im['حالة النص البديل'] == 'alt_missing']['رابط الصورة'].nunique() if not im.empty else 0)
pd_ = df[(df['نوع الصفحة'] == 'product') & (df['متاحة'] == True)]['_pdesc'].tolist()
print('descriptions from products.json:', sum('handmade in Leeds' in str(x) for x in pd_), 'of', len(pd_))
