from simlib import *
B = 'https://z.com'; N = 20
links = ''.join(f'<a href="/products/item-{i}">x</a><a href="/ar-sa/products/item-{i}">x</a>' for i in range(1, N + 1))
def fake(url, timeout=14, retries=2, headers=None):
    p = path_of(url)
    if url.endswith('/robots.txt'): return mk(url, 200, f'Sitemap: {B}/sitemap.xml', 'text/plain')
    if p == '/sitemap.xml': return mk(url, 200, '<urlset>' + ''.join(f'<url><loc>{B}/products/item-{i}</loc></url>' for i in range(1, N + 1)) + '</urlset>', 'application/xml')
    if p in ('', '/ar-sa'): return mk(url, 200, f'<html><head><title>متجر أفكار للهدايا والقهوة</title></head><body><script src="https://cdn.zid.store/x.js"></script>{links}</body></html>')
    if '/products/item-' in p:
        i = int(p.rsplit('-', 1)[1])
        return mk(url, 200, f'<html><head><meta property="og:type" content="product"><title>منتج رقم {i} من متجر أفكار</title><meta name="description" content="وصف {i} {"تفاصيل " * 15}"></head><body><h1>منتج {i}</h1>{links}</body></html>')
    return mk(url, 404, 'nf')
s = scan(fake, B)['summary']; print(f"products={s['products']} | same title={s['title_dup']} | same title+desc={s['dup_content']}")
