import os, sys, io
sys.argv = ['x']
exec(open('/tmp/sim/zidmaps.py').read().split("sm = res['crawl_meta']")[0])
os.chdir('/home/claude/work')
import pandas as pd
from streamlit.testing.v1 import AppTest
at = AppTest.from_file('/home/claude/work/app.py', default_timeout=180)
for k, v in {'audit_df': res['df'], 'images_df': res['images_df'], 'summary': res['summary'], 'coverage': res['coverage'], 'selfcheck': res['selfcheck'],
             'platform': res['platform'], 'structured': res['structured'], 'dup_groups': res['dup_groups'], 'brand': res['brand'], 'current_url': B,
             'sitemap_report': res['crawl_meta']['sitemap_report']}.items():
    at.session_state[k] = v
at.run()
print('exceptions:', [str(x.value)[:200] for x in at.exception])
print('before tajhiz downloads:', len([b for b in at.get('download_button') if 'المرحلة' in b.label]))
at.text_input(key='ph_name').input('محمد العتيبي').run()
[b for b in at.button if 'تجهيز' in b.label][0].click().run()
dl = [b.label for b in at.get('download_button') if 'المرحلة' in b.label]
print('after tajhiz downloads:', len(dl), '| exceptions:', [str(x.value)[:120] for x in at.exception])
print('whatsapp messages:', len([c for c in at.code if 'السلام عليكم' in c.value]))
# ملفات المهام مجتمعة = ملفات التصدير بالضبط
import export_utils as x, phases as ph
exp = x.build_filtered_exports(res['df'], res['images_df'], 'ar', 'zid')
tabs_ = ph.work_tables(exp)
parts = ph.split_phases(tabs_, 2, 'priority')
same = all(sum(len(p.get(k, [])) for p in parts) == len(tabs_[k]) for k in ('titles', 'descs', 'alt_missing', 'alt_weak', 'broken'))
cols_same = all(list(parts[0][k].columns) == list(exp[k][1].columns) for k in parts[0] if k in exp)
print('task files cover all rows:', same, '| same columns as export:', cols_same)
