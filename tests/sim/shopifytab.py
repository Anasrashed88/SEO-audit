import os, sys, json
sys.argv = ['x']
exec(open('/tmp/sim/zidmaps.py').read().split("sm = res['crawl_meta']")[0])
os.chdir('/home/claude/work'); sys.path.insert(0, '/home/claude/work')
import zid_api as z, audit_engine as eng
from streamlit.testing.v1 import AppTest
f = z._tokens_dir(eng.BASE_DIR) / 'shopify_anas-dev.myshopify.com.json'
f.write_text(json.dumps({'key': 'shopify_anas-dev.myshopify.com', 'platform': 'shopify', 'store': {'id': 'anas-dev.myshopify.com', 'name': 'Dev Store', 'url': 'https://dev.example.com'}, 'tokens': {'obtained': '2026-10-18T00:00:00Z'}}))
at = AppTest.from_file('/home/claude/work/app.py', default_timeout=200)
for k, v in {'audit_df': res['df'], 'images_df': res['images_df'], 'summary': res['summary'], 'coverage': res['coverage'], 'selfcheck': res['selfcheck'],
             'platform': res['platform'], 'structured': res['structured'], 'dup_groups': res['dup_groups'], 'brand': res['brand'], 'current_url': B,
             'sitemap_report': res['crawl_meta']['sitemap_report']}.items():
    at.session_state[k] = v
at.run()
print('connect tab card:', [m.value for m in at.markdown if 'Dev Store' in m.value], '| exceptions:', [str(e.value)[:100] for e in at.exception])
at.sidebar.radio[0].set_value("🔗 المتاجر المربوطة").run()
print('linked page platform:', [(m.label, m.value) for m in at.metric if m.label == 'المنصة'])
f.unlink()
