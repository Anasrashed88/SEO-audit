import sys, json, tempfile, shutil
sys.path.insert(0, '/home/claude/work')
import ai_writer as ai
ai.time.sleep = lambda s: None

class R:
    def __init__(self, code, data): self.status_code, self._d = code, data
    def json(self): return self._d
    def raise_for_status(self):
        if self.status_code >= 400: raise RuntimeError(self.status_code)

class FakeGemini:
    def __init__(self, quota=99): self.calls, self.quota = 0, quota
    def get(self, url, params=None, timeout=None, headers=None):
        assert 'key' not in (params or {}), 'key leaked into URL'
        return R(200, {'models': [{'name': f'models/{n}', 'supportedGenerationMethods': ['generateContent']}
                                  for n in ('gemini-3.8-flash', 'gemini-3.5-flash-lite', 'gemini-3.5-flash', 'gemini-3.8-flash-preview', 'text-embedding-004')]})
    def post(self, url, params=None, json=None, timeout=None, headers=None):
        assert 'key' not in (params or {}), 'key leaked into URL'
        self.calls += 1
        if getattr(self, 'busy', 0) > 0:
            self.busy -= 1
            return R(503, {})
        if self.calls > self.quota:
            return R(429, {'error': {'details': [{'retryDelay': '3600s'}]}})
        prompt = json['contents'][0]['parts'][0]['text']
        fixing = 'أعد كتابة' in prompt
        data = __import__('json').loads(prompt[prompt.rindex('\n[') + 1:])
        out = []
        for d in data:
            _m = __import__('re').search(r'(\d+)$', d['id']); i = int(_m.group(1)) if _m else 1
            core = f"مبخرة خشبية رقم {i} بنقوش تراثية أنيقة"               # 31-35 حرفاً
            core = (core + ' للمجالس الراقية')[:42]                        # ~40 حرفاً: مع « | مدهال عود» = 52
            desc = f"اكتشف مبخرة خشبية رقم {i} مصنوعة يدوياً بنقوش تراثية، تضفي لمسة دافئة على مجلسك وتناسب الإهداء في كل المناسبات. تسوق الآن."
            if not fixing and i % 10 == 3:
                core = 'مبخرة'                                            # قصير → يُعاد
            if i % 10 == 7:
                desc = desc[:100] + ' بسعر 99 ريال'                       # سعر → يبقى للمراجعة
            if not fixing and i % 10 == 5:
                desc = d['current_description']                          # منسوخ → يُعاد
            out.append({'id': d['id'], 'title': core, 'description': desc})
        return R(200, {'candidates': [{'content': {'parts': [{'text': __import__('json').dumps(out, ensure_ascii=False)}]}}]})

# اكتشاف اسم المتجر
zid = ['مبخرة | مدهال عود'] * 25 + ['بوكس فيروز'] * 23
salla = ['غسول | متجر العناية'] * 95 + ['متجر العناية'] * 3
print('zid suffix:', ai.detect_title_suffix(zid), '| salla suffix:', ai.detect_title_suffix(salla), '| none:', ai.detect_title_suffix(['أ', 'ب']))
print('budget for " | مدهال عود":', ai.title_budget(' | مدهال عود'))
models = ai.list_models('K', FakeGemini())
print('models (no lite/preview):', models, '| default:', ai.default_model(models))
base = tempfile.mkdtemp()
items = [{'id': f'https://m.s/products/p{i}', 'type': 'صفحة منتج', 'name': f'مبخرة {i}', 'title': f'مبخرة {i}',
          'desc': f'وصف حالي قديم للمبخرة رقم {i} ' * 6, 'excerpt': '', 'pdesc': f'مبخرة خشبية رقم {i} مصنوعة يدوياً', 'category': 'المباخر',
          'brand': '', 'need': {'title', 'desc'}} for i in range(30)]
fg = FakeGemini()
cache, info = ai.generate(items, 'K', 'مدهال', base, 'https://m.s', 'gemini-3.8-flash', session=fg, suffix=' | مدهال عود', suffix_mode='add')
sg = ai.suggestions(cache)
print('done:', info['done'], '| requests:', fg.calls, '| run ids:', len(info['run_ids']))
t3 = sg['https://m.s/products/p3']; print('p3 title:', t3['title'], '| len:', len(t3['title_full']), '| notes:', t3['title_notes'] or '-')
print('p7 desc notes (price):', sg['https://m.s/products/p7']['desc_notes'])
print('p5 copied desc fixed:', sg['https://m.s/products/p5']['desc_notes'] or 'ok')
print('title notes never in desc notes:', all('العنوان' not in v['desc_notes'] for v in sg.values()))
try:
    ai.generate(items, 'K', 'مدهال', base, 'https://m.s', 'gemini-3.5-flash', session=FakeGemini())
    print('model lock: NOT enforced')
except ValueError as e:
    print('model lock enforced:', 'بدأ بنموذج' in str(e))
print('usage counted today:', ai.usage_today(base, 'gemini-3.8-flash'))
cache2, i2 = ai.generate(items, 'K', 'مدهال', base, 'https://m.s', 'gemini-3.8-flash', session=FakeGemini(), suffix=' | مدهال عود', suffix_mode='add')
print('second run requested:', i2['requested'])
shutil.rmtree(base); base = tempfile.mkdtemp()
c3, i3 = ai.generate(items, 'K', 'مدهال', base, 'https://m.s', 'gemini-3.8-flash', session=FakeGemini(quota=2), suffix=' | مدهال عود', suffix_mode='add')
print('quota stop:', bool(i3['stopped']), '| saved:', len(ai.suggestions(ai.load_cache(base, 'https://m.s'))))
c4, i4 = ai.generate(items, 'K', 'مدهال', base, 'https://m.s', 'gemini-3.8-flash', session=FakeGemini(), suffix=' | مدهال عود', suffix_mode='add')
print('continued: requested', i4['requested'], '| total', len(ai.suggestions(c4)))
auto = ai.generate(items[:3], 'K', 'العناية', tempfile.mkdtemp(), 'https://e.s', 'gemini-3.8-flash', session=FakeGemini(), suffix=' | مدهال عود', suffix_mode='auto')[0]
v = ai.suggestions(auto)['https://m.s/products/p0']
print('auto mode: suggestion has no suffix:', ' | ' not in v['title'], '| measured with it:', v['title_full'].endswith('مدهال عود'))
shutil.rmtree(base)

# خوادم جوجل مشغولة: مؤقتاً (تنجح بعد إعادة)، ودائماً (توقف هادئ مع الحفظ)
base = tempfile.mkdtemp()
fb = FakeGemini(); fb.busy = 2
cb, ib = ai.generate(items[:5], 'SECRET-KEY', 'م', base, 'https://b.s', 'gemini-3.8-flash', session=fb, suffix=' | مدهال عود', suffix_mode='add')
print('brief 503 recovered:', ib['stopped'] is None and len(ai.suggestions(cb)) == 5)
fa = FakeGemini(); fa.busy = 999
ca, ia = ai.generate(items[:5], 'SECRET-KEY', 'م', tempfile.mkdtemp(), 'https://c.s', 'gemini-3.8-flash', session=fa)
print('persistent 503 stops gracefully:', bool(ia['stopped']) and 'مشغولة' in ia['stopped'], '| key not in message:', 'SECRET' not in str(ia['stopped']))

# اقتراحات النسخة القديمة تُكتب من جديد، والصفحات الثابتة تأخذ عنوانها المعروف
base = tempfile.mkdtemp()
ai.save_cache(base, 'https://f.s', {items[0]['id']: {'title': 'قديم', 'description': 'قديم بسعر 26 ريال', 'status': 'مطابق للقواعد', 'notes': ''}})
fixed_items = [dict(items[0]), {'id': 'https://f.s/pages/privacy', 'fixed_title': 'سياسة الخصوصية', 'type': 'info', 'name': '', 'title': '[-]', 'desc': '',
               'excerpt': 'نحمي بيانات العملاء ولا نشاركها', 'pdesc': '', 'category': '', 'brand': '', 'need': {'title', 'desc'}},
               {'id': 'https://f.s/blogs', 'fixed_title': 'المدونة', 'type': 'archive', 'name': '', 'title': 'مدهال عود', 'desc': 'وصف جيد',
                'excerpt': '', 'pdesc': '', 'category': '', 'brand': '', 'need': {'title'}}]
ff = FakeGemini()
cf, inf = ai.generate(fixed_items, 'K', 'م', base, 'https://f.s', 'gemini-3.8-flash', session=ff, suffix=' | مدهال عود', suffix_mode='add')
sg = ai.suggestions(cf)
print('legacy rewritten:', sg[items[0]['id']]['title'] != 'قديم' and 'title_notes' in sg[items[0]['id']])
print('fixed title kept exactly:', sg['https://f.s/pages/privacy']['title'], '| desc written by AI:', bool(sg['https://f.s/pages/privacy']['description']))
print('title-only fixed page needs no request:', sg['https://f.s/blogs']['title'] == 'المدونة', '| requests:', ff.calls)
print('small edit counts as copy:', ai._same('مبخرة خشبية صغيرة بنقشة هندسية أنيقة للمجالس', 'مبخرة خشبية صغيرة بنقشة هندسية جميلة للمجالس'))
shutil.rmtree(base)
