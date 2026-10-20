import os, sys, json
os.chdir('/home/claude/work'); sys.path.insert(0, '/home/claude/work')
import ai_writer as ai, zid_api as z, audit_engine as eng
from streamlit.testing.v1 import AppTest
ai.save_cache(eng.BASE_DIR, 'https://midhal-oud.store', {'__meta__': {'model': 'gemini-3.6-flash'},
    'https://midhal-oud.store/products/a': {'title': 'مبخرة خشبية | مدهال عود', 'title_full': 'x', 'description': 'وصف جديد', 'status': 'مطابق للقواعد', 'title_notes': '', 'desc_notes': ''},
    'img::https://cdn/1.jpg': {'alt': 'مبخرة خشبية بنقش ذهبي', 'status': 'مطابق للقواعد', 'alt_notes': '', 'page': 'p', 'model': 'm'}})
(z._tokens_dir(eng.BASE_DIR) / 'store_t.json').write_text(json.dumps({'key': 'store_t', 'store': {'id': '', 'name': '', 'url': ''}, 'tokens': {'obtained': '2026-10-07T19:00:00Z'}}))
at = AppTest.from_file('/home/claude/work/app.py', default_timeout=120); at.run()
at.sidebar.radio[0].set_value("🔗 المتاجر المربوطة").run()
print('linked page:', [m.value for m in at.markdown if m.value.startswith('**')], '| midhal shown here:', any('midhal' in m.value for m in at.markdown), '| exceptions:', [str(e.value)[:100] for e in at.exception])
at.text_input(key='lbl_store_t').input('شمسه').run(); at.button(key='lbl_save_store_t').click().run()
print('label saved & shown:', any('شمسه' in m.value for m in at.markdown if m.value.startswith('**')))
at.sidebar.radio[0].set_value("🤖 الاقتراحات المحفوظة").run()
print('saved page:', [m.value for m in at.markdown if m.value.startswith('**')], '| metrics:', [(m.label, m.value) for m in at.metric][:4])
at.button(key='ws_open_midhal-oud.store').click().run()
print('rows:', [len(d.value) for d in at.dataframe], '| exceptions:', [str(e.value)[:100] for e in at.exception])
at.button(key='ws_del_midhal-oud.store').click().run(); at.button(key='ws_yes_midhal-oud.store').click().run()
print('deleted after confirm:', not ai.cache_file(eng.BASE_DIR, 'https://midhal-oud.store').exists())
(z._tokens_dir(eng.BASE_DIR) / 'store_t.json').unlink()
