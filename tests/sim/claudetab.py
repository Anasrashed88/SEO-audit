import os, sys
sys.argv = ['x']
exec(open('/tmp/sim/zidmaps.py').read().split("sm = res['crawl_meta']")[0])
os.chdir('/home/claude/work'); sys.path.insert(0, '/home/claude/work')
import ai_writer as ai, audit_engine as eng
from streamlit.testing.v1 import AppTest
ai.key_path(eng.BASE_DIR).unlink(missing_ok=True); ai.cache_file(eng.BASE_DIR, B).unlink(missing_ok=True)
ai.save_claude_key(eng.BASE_DIR, 'CLAUDE-TEST')
at = AppTest.from_file('/home/claude/work/app.py', default_timeout=200)
for k, v in {'audit_df': res['df'], 'images_df': res['images_df'], 'summary': res['summary'], 'coverage': res['coverage'], 'selfcheck': res['selfcheck'],
             'platform': res['platform'], 'structured': res['structured'], 'dup_groups': res['dup_groups'], 'brand': res['brand'], 'current_url': B,
             'sitemap_report': res['crawl_meta']['sitemap_report']}.items():
    at.session_state[k] = v
at.run()
sb = [x for x in at.selectbox if x.key == 'ai_model']
print('claude only → model list:', sb[0].options if sb else None, '| selected:', sb[0].value if sb else None, '| exceptions:', [str(e.value)[:100] for e in at.exception])
print('gemini key box still offered:', any(t.key == 'gem_key_in' for t in at.text_input))
ai.claude_key_path(eng.BASE_DIR).unlink(missing_ok=True)
