# متجر زد مثل sso.zid.store: كل منتج له صفحة مراجعات /products/<رقم>/reviews
from simlib import *
import uuid
B = 'https://sso.zid.store'; N = 12
ids = [str(uuid.UUID(int=i + 1)) for i in range(N)]
def fake(url, timeout=14, retries=2, headers=None):
    p = path_of(url)
    if url.endswith('/robots.txt'): return mk(url, 200, '', 'text/plain')
    if p == '/sitemap_products.xml':
        return mk(url, 200, '<urlset>' + ''.join(f'<url><loc>{B}/products/عطر-{i}</loc></url>' for i in range(N)) + f'<url><loc>{B}/products/{ids[0]}/reviews</loc></url></urlset>', 'application/xml')
    if p == '': return mk(url, 200, f'<html><head><title>اروماتك لأجهزة التعطير والزيوت العطرية</title></head><body><script src="https://cdn.zid.store/x.js"></script><a href="/products">الكل</a></body></html>')
    if p == '/products': return mk(url, 200, f'<html><head><title>الكل</title></head><body>إجمالي {N} منتجات</body></html>')
    if p.endswith('/reviews'): return mk(url, 200, product('المراجعات - مجموعة تعطير | اروماتك'))
    if p.startswith('/products/عطر-'):
        i = int(p.rsplit('-', 1)[1])
        return mk(url, 200, product(f'عطر فاخر رقم {i} من اروماتك للتعطير', f'<a href="/products/{ids[i]}/reviews">المراجعات</a>'))
    return mk(url, 404, 'nf')
res = scan(fake, B)
print('products:', res['summary']['products'], '| review pages:', int(res['df']['الرابط'].str.endswith('/reviews').sum()))
print('RECON:', check_line(res, 'مطابقة الأرقام')[0]['msg'])
