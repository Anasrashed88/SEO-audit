import os, sys
sys.argv = ['x']
exec(open('/tmp/sim/zidmaps.py').read().split("sm = res['crawl_meta']")[0])
os.chdir('/home/claude/work')
from streamlit.testing.v1 import AppTest
at = AppTest.from_file('/home/claude/work/app.py', default_timeout=180)
for k, v in {'audit_df': res['df'], 'images_df': res['images_df'], 'summary': res['summary'], 'coverage': res['coverage'], 'selfcheck': res['selfcheck'],
             'platform': res['platform'], 'structured': res['structured'], 'dup_groups': res['dup_groups'], 'brand': res['brand'], 'current_url': B,
             'sitemap_report': res['crawl_meta']['sitemap_report']}.items():
    at.session_state[k] = v
at.run()
print('app exceptions:', [str(x.value)[:150] for x in at.exception])
print('downloads:', len([b for b in at.get('download_button')]))
import pdf_generator as g
st = dict(res['summary']); st['platform_label'] = 'زد (Zid)'
from audit_engine import build_broken_links
st['broken_links'] = build_broken_links(res['df'], res['platform']).to_dict('records')
for lang in ('ar', 'en'):
    g.generate_client_pdf(B, st['score'], st, lang); g.generate_invoice_pdf(B, g.build_quote(st), lang)
print('PDFs ok')
