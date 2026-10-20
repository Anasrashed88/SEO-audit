import sys, os
sys.argv = ['x']
exec(open('/tmp/sim/zidmaps.py').read().split("sm = res['crawl_meta']")[0])
os.chdir('/home/claude/work')
import pdf_generator as g
from audit_engine import build_broken_links
st = dict(res['summary'])
st.update({'platform_label': 'Zid' if False else 'زد (Zid)', 'live_pages': 3296, 'total_pages': 3296, 'products': 3162, 'categories': 70, 'brand_pages': 2, 'listing_pages': 2,
           'blog_pages': 7, 'info_pages': 42, 'bad_titles': 2960, 'critical_titles': 2142, 'bad_descs': 904, 'critical_descs': 300,
           'good_alts': 2400, 'weak_alts': 6674, 'missing_alts': 4206, 'total_images': 13280, 'fix_titles_urls': 2960, 'fix_descs': 904,
           'broken_actionable': 8, 'score': 64.2})
st['broken_links'] = build_broken_links(res['df'], 'zid').to_dict('records')
for lang in ('ar', 'en'):
    open(f'/tmp/sim/rep_{lang}.pdf', 'wb').write(g.generate_client_pdf('https://furniture-ks.com', 64.2, st, lang))
    open(f'/tmp/sim/inv_{lang}.pdf', 'wb').write(g.generate_invoice_pdf('https://furniture-ks.com', g.build_quote(st), lang))
print('rendered')
