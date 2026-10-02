from simlib import *
B = 'https://b.com'
def arts(a, b): return ''.join(f'<a href="{B}/blog/مقال-{i}/a10000{i:03d}">م</a>' for i in range(a, b))
def fake(url, timeout=14, retries=2, headers=None):
    p = path_of(url)
    if url.endswith('/robots.txt'): return mk(url, 200, f'Sitemap: {B}/sitemap.xml', 'text/plain')
    if p == '/sitemap.xml': return mk(url, 200, f'<urlset><url><loc>{B}/x/p1000001</loc></url></urlset>', 'application/xml')
    if p == '': return mk(url, 200, '<html><head><title>متجر</title></head><body><script>window.salla={}</script><a href="/blog">المدونة</a><a href="/x/p1000001">م</a></body></html>')
    if p == '/blog':
        if 'page=2' in url: return mk(url, 200, f'<html><body>{arts(6, 11)}</body></html>')
        if 'page=3' in url: return mk(url, 200, f'<html><body>{arts(11, 14)}</body></html>')
        if '?' in url: return mk(url, 200, '<html><body></body></html>')
        return mk(url, 200, f'<html><head><title>المدونة</title></head><body>{arts(1, 6)}</body></html>')
    if p.startswith('/blog/'): return mk(url, 200, f'<html><head><meta property="og:type" content="article"><title>مقال مفيد عن العناية</title></head><body><h1>م</h1><p>{"نص " * 60}</p></body></html>')
    if 'p1000001' in p: return mk(url, 200, product('منتج'))
    return mk(url, 404, 'nf')
print('blog articles:', scan(fake, B)['summary']['blog_pages'])
