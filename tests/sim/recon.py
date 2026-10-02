from simlib import *
DECL = int(sys.argv[1]); B = 'https://z.com'
def fake(url, timeout=14, retries=2, headers=None):
    p = path_of(url)
    if url.endswith('/robots.txt'): return mk(url, 200, f'Sitemap: {B}/sitemap.xml', 'text/plain')
    if p == '/sitemap.xml': return mk(url, 200, '<urlset>' + ''.join(f'<url><loc>{B}/products/item-{i}</loc></url>' for i in range(1, 21)) + '</urlset>', 'application/xml')
    if p == '': return mk(url, 200, f'<html><head><title>متجر تجريبي للهدايا والقهوة</title></head><body><script src="https://cdn.zid.store/x.js"></script><a href="/products">الكل</a><a href="/products/item-21">جديد</a></body></html>')
    if p == '/products': return mk(url, 200, f'<html><head><title>الكل</title></head><body>ترتيب إجمالي {DECL} منتجات</body></html>')
    if p.startswith('/products/item-'):
        i = int(p.rsplit('-', 1)[1])
        return mk(url, 404, 'nf') if i == 20 else mk(url, 200, product(f'منتج رقم {i} من متجر الهدايا'))
    return mk(url, 404, 'nf')
c = check_line(scan(fake, B), 'مطابقة الأرقام')[0]; print(c['level'], '|', c['msg'])
