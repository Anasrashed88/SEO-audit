import os, sys
sys.argv = ['x']
exec(open('/tmp/sim/zidmaps.py').read().split("sm = res['crawl_meta']")[0])
os.chdir('/home/claude/work'); sys.path.insert(0, '/home/claude/work')
from streamlit.testing.v1 import AppTest
at = AppTest.from_file('/home/claude/work/app.py', default_timeout=200)
for k, v in {'audit_df': res['df'], 'images_df': res['images_df'], 'summary': res['summary'], 'coverage': res['coverage'], 'selfcheck': res['selfcheck'],
             'platform': res['platform'], 'structured': res['structured'], 'dup_groups': res['dup_groups'], 'brand': res['brand'], 'current_url': B,
             'sitemap_report': res['crawl_meta']['sitemap_report']}.items():
    at.session_state[k] = v
at.run()
print('exceptions:', [str(e.value)[:120] for e in at.exception])
at.radio(key='price_currency').set_value('دولار أمريكي').run()
print('usd total metric:', [m.value for m in at.metric if m.label == 'الإجمالي المستحق'], '| exceptions:', [str(e.value)[:120] for e in at.exception])
at.sidebar.checkbox(key='marketplace_mode').check().run()
import pdf_generator as g
print('marketplace hides contact:', g.SETTINGS['show_contact'] is False, '| exceptions:', [str(e.value)[:120] for e in at.exception])
