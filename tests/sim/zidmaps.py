# متجر زد مثل KS FURNITURE: خرائط غير معلنة، منها خريطتان في مجلدات فرعية،
# وصفحات تعريفية مكتوبة في الخريطة بصيغة /blogs/ وتحوّل إلى /pages/
from simlib import *
B = 'https://furniture-ks.com'
prods = [f'خزانة-ملابس-{i}' for i in range(1, 16)] + [f'Console-Table-{i}' for i in range(1, 16)]
arts = ['دليل-اختيار-اثاث-غرفة-نوم', 'غرف-نوم-اطفال', 'خزانة-أحذية-مودرن']
pages = ['سياسة-ضمان-المنتج', 'سياسة-الشحن', 'الشروط-والاحكام', 'خدمة-تركيب-الاثاث']
def fake(url, timeout=14, retries=2, headers=None):
    p = path_of(url)
    if url.endswith('/robots.txt'): return mk(url, 200, 'User-agent: *\nDisallow: /cart', 'text/plain')
    if p == '/sitemap_products.xml': return mk(url, 200, '<urlset>' + ''.join(f'<url><loc>{B}/products/{x}</loc></url>' for x in prods) + '</urlset>', 'application/xml')
    if p == '/sitemap_categories.xml': return mk(url, 200, f'<urlset><url><loc>{B}/categories/51968/wardrobes</loc></url></urlset>', 'application/xml')
    if p == '/sitemap_pages.xml': return mk(url, 200, '<urlset>' + ''.join(f'<url><loc>{B}/blogs/{x}</loc></url>' for x in pages) + '</urlset>', 'application/xml')
    if p == '/blog/sitemap.xml': return mk(url, 200, f'<urlset><url><loc>{B}/blogs</loc></url>' + ''.join(f'<url><loc>{B}/blogs/{x}</loc></url>' for x in arts) + '</urlset>', 'application/xml')
    if p == '/brands/sitemap.xml': return mk(url, 200, f'<urlset><url><loc>{B}/brands/ks</loc></url></urlset>', 'application/xml')
    if p == '': return mk(url, 200, f'<html><head><title>KS FURNITURE للأثاث المنزلي الفاخر</title></head><body><script src="https://cdn.zid.store/x.js"></script><a href="/products">الكل</a><a href="/blogs">المدونة</a><a href="/categories/51968/">خزائن</a>' + ''.join(f'<a href="/pages/{x}">.</a>' for x in pages) + '</body></html>')
    if p == '/products': return mk(url, 200, f'<html><head><title>جميع المنتجات</title></head><body>إجمالي {len(prods)} منتجات</body></html>')
    if p in ('/categories/51968/wardrobes', '/categories/51968'): return mk(url, 200, '<html><head><title>خزائن الملابس</title></head><body>.</body></html>')
    if p == '/brands/ks': return mk(url, 200, '<html><head><title>علامة KS</title></head><body>.</body></html>')
    if p == '/blogs': return mk(url, 200, '<html><head><title>المدونة</title></head><body>' + ''.join(f'<a href="/blogs/{x}">.</a>' for x in arts) + '</body></html>')
    for x in pages:
        if p == f'/blogs/{x}':   # الصفحة التعريفية بصيغة المدونة تحوّل إلى /pages/
            return mk(f'{B}/pages/{x}', 200, f'<html><head><title>{x}</title></head><body><h1>{x}</h1><p>{"نص " * 60}</p></body></html>', hist=[mk(url, 301)])
        if p == f'/pages/{x}':
            return mk(url, 200, f'<html><head><title>{x}</title></head><body><h1>{x}</h1><p>{"نص " * 60}</p></body></html>')
    if p.startswith('/blogs/'): return mk(url, 200, f'<html><head><meta property="og:type" content="article"><title>مقال {p}</title></head><body><h1>مقال</h1><p>{"نص " * 80}</p></body></html>')
    if p.startswith('/products/'): return mk(url, 200, product(f'{p} من متجر الأثاث الفاخر'))
    return mk(url, 404, 'nf')
res = scan(fake, B)
sm = res['crawl_meta']['sitemap_report']
print('sitemap files:', sm['files_ok'], '| urls:', sm['total_urls'])
print('RECON:', check_line(res, 'مطابقة الأرقام')[0]['msg'])
print('blog pages:', res['summary']['blog_pages'], '| info pages:', res['summary']['info_pages'])
