import os, sys
sys.argv = ['x']
exec(open('/tmp/sim/zidmaps.py').read().split("sm = res['crawl_meta']")[0])
os.chdir('/home/claude/work'); sys.path.insert(0, '/home/claude/work')
import ai_writer as ai, export_utils as x, audit_engine as eng
from streamlit.testing.v1 import AppTest
def run():
    at = AppTest.from_file('/home/claude/work/app.py', default_timeout=200)
    for k, v in {'audit_df': res['df'], 'images_df': res['images_df'], 'summary': res['summary'], 'coverage': res['coverage'], 'selfcheck': res['selfcheck'],
                 'platform': res['platform'], 'structured': res['structured'], 'dup_groups': res['dup_groups'], 'brand': res['brand'], 'current_url': B,
                 'sitemap_report': res['crawl_meta']['sitemap_report']}.items():
        at.session_state[k] = v
    at.session_state['gem_models'] = ['gemini-3.8-flash', 'gemini-3.5-flash']
    at.run(); return at
at = run()
print('no key -> key input shown:', any(t.label == 'مفتاح Gemini' for t in at.text_input), '| exceptions:', [str(e.value)[:100] for e in at.exception])
ai.save_key(eng.BASE_DIR, 'TEST-KEY')
ex = x.build_filtered_exports(res['df'], res['images_df'], 'ar', 'zid')
items = ai.items_from_scan(res['df'], ex)
cache = {'__meta__': {'model': 'gemini-3.8-flash'}}
for it in items[:8]:
    cache[it['id']] = {'title': 'خزانة ملابس خشبية بتصميم عصري أنيق | KS', 'title_full': 'خزانة ملابس خشبية بتصميم عصري أنيق | KS FURNITURE',
                       'description': 'و' * 130, 'status': ai.STATUS_OK, 'title_notes': '', 'desc_notes': ''}
ai.save_cache(eng.BASE_DIR, B, cache)
at = run()
print('locked model shown:', any('النموذج الثابت' in i.value for i in at.info), '| exceptions:', [str(e.value)[:150] for e in at.exception])
print('titles preview rows:', [len(d.value) for d in at.dataframe if 'العنوان الجديد' in d.value.columns])
at.radio(key='ai_view').set_value('الأوصاف').run()
print('descs preview rows:', [len(d.value) for d in at.dataframe if 'الوصف الجديد' in d.value.columns], '| exceptions:', [str(e.value)[:120] for e in at.exception])
at.checkbox(key='ai_regen').check().run()
import io, pandas as _pd
_t = ai.compact_file(ex, ai.load_cache(eng.BASE_DIR, B), res['df'], 'titles')
print('titles file columns:', list(_t.columns))
print('regen shows model list on locked store:', any(sb.label.startswith('النموذج') for sb in at.selectbox))
print('downloads:', [b.label for b in at.get('download_button') if 'الجديدة' in b.label or 'عينة' in b.label])
at.radio(key='ai_view').set_value('الصور').run()
print('images view exceptions:', [str(e.value)[:120] for e in at.exception])
at.radio(key='ai_view').set_value('الروابط').run()
print('links view exceptions:', [str(e.value)[:120] for e in at.exception])
ai.key_path(eng.BASE_DIR).unlink(missing_ok=True); ai.cache_file(eng.BASE_DIR, B).unlink(missing_ok=True)
