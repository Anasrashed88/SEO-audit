from simlib import *
B = 'https://l.com'; N = 60; PH = {'n': 1}; net = []
HOME = f'<html><head><title>متجر لفتة للعبايات</title><link rel="canonical" href="{B}"></head><body><script>window.salla={{}}</script></body></html>'
def fake(url, timeout=14, retries=2, headers=None):
    p = path_of(url)
    if url.endswith('/robots.txt'): return mk(url, 200, f'Sitemap: {B}/sitemap.xml', 'text/plain')
    if p == '/sitemap.xml': return mk(url, 200, '<urlset>' + ''.join(f'<url><loc>{B}/abaya-{i}/p10000{i:03d}</loc></url>' for i in range(1, N + 1)) + '</urlset>', 'application/xml')
    if p == '': return mk(url, 200, HOME)
    if '/abaya-' in p:
        net.append(p); i = int(p.rsplit('p10000', 1)[1])
        if PH['n'] == 1 and i > 25: return mk(B, 200, HOME, hist=[mk(url, 302)])
        return mk(url, 200, product(f'عباية موديل {i} سوداء فاخرة بقماش كريب'))
    return mk(url, 404, 'nf')
e.cache_clear(B)
r1 = scan(fake, B, use_cache=True)
print(f"first: products={r1['summary']['products']} suspicious={r1['crawl_meta']['home_suspicious']}")
print('completion:', check_line(r1, 'اكتمال الفحص')[0]['msg'][:40])
PH['n'] = 2; net.clear()
r2 = scan(fake, B, use_cache=True)
print(f"resume: products={r2['summary']['products']} requests={len(net)} cached={r2['crawl_meta']['cache_hits']}")
e.cache_clear(B)
