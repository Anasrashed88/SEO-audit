import os, sys
exec(open('/tmp/sim/homered.py').read().split("PH['n'] = 2")[0])
os.chdir('/home/claude/work')
from streamlit.testing.v1 import AppTest
at = AppTest.from_file('/home/claude/work/app.py', default_timeout=180)
for k, v in {'audit_df': r1['df'], 'images_df': r1['images_df'], 'summary': r1['summary'], 'coverage': r1['coverage'], 'selfcheck': r1['selfcheck'],
             'platform': r1['platform'], 'structured': r1['structured'], 'dup_groups': r1['dup_groups'], 'brand': r1['brand'], 'current_url': B,
             'sitemap_report': r1['crawl_meta']['sitemap_report']}.items():
    at.session_state[k] = v
at.run()
before = [b.label for b in at.get('download_button') if 'عرض السعر' in b.label or 'تقرير العميل' in b.label]
cb = [c for c in at.checkbox if 'مسؤولية' in c.label or 'ناقص' in c.label]
cb[0].check().run()
after = [b.label for b in at.get('download_button') if 'عرض السعر' in b.label or 'تقرير العميل' in b.label]
print('locked before confirm:', before == [], '| unlocked after:', len(after) == 2, '| exceptions:', [str(x.value)[:80] for x in at.exception])
e.cache_clear(B)
