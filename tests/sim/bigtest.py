import os, sys
sys.argv = ['x']
exec(open('/tmp/sim/zidmaps.py').read().split("sm = res['crawl_meta']")[0])
os.chdir('/home/claude/work'); sys.path.insert(0, '/home/claude/work')
import phases
from streamlit.testing.v1 import AppTest
def run(units):
    phases.work_units = lambda t, _u=units: _u
    at = AppTest.from_file('/home/claude/work/app.py', default_timeout=200)
    for k, v in {'audit_df': res['df'], 'images_df': res['images_df'], 'summary': res['summary'], 'coverage': res['coverage'], 'selfcheck': res['selfcheck'],
                 'platform': res['platform'], 'structured': res['structured'], 'dup_groups': res['dup_groups'], 'brand': res['brand'], 'current_url': B,
                 'sitemap_report': res['crawl_meta']['sitemap_report']}.items():
        at.session_state[k] = v
    at.run(); return at
at = run(2000)
print('over 1500 → itemised notice:', any('التسعير المفرد' in i.value for i in at.info), '| package price box hidden:', not any(n.key == 'pkg_price' for n in at.number_input), '| exceptions:', [str(e.value)[:100] for e in at.exception])
print('total equals itemised:', [m.value for m in at.metric if m.label == 'الإجمالي المستحق'])
at = run(60)
print('60 units → package price box:', any(n.key == 'pkg_price' for n in at.number_input), [m.value for m in at.metric if m.label == 'الإجمالي المستحق'])
