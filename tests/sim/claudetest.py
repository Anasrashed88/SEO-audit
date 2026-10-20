import sys, json, tempfile
sys.path.insert(0, '/home/claude/work')
import ai_writer as ai
ai.time.sleep = lambda s: None
class R:
    def __init__(self, c, d, h=None): self.status_code, self._d, self.headers = c, d, h or {}
    def json(self): return self._d
class FakeClaude:
    def __init__(self, mode='ok'): self.mode, self.calls, self.bodies = mode, 0, []
    def post(self, url, json=None, headers=None, timeout=None, params=None):
        self.calls += 1
        assert url == 'https://api.anthropic.com/v1/messages', url
        assert headers['x-api-key'] == 'CLAUDE-KEY' and headers['anthropic-version'] == '2023-06-01'
        assert 'temperature' not in json, 'temperature must not be sent'
        self.bodies.append(json)
        if self.mode == 'credit': return R(400, {'error': {'message': 'Your credit balance is too low to access the API.'}})
        if self.mode == 'busy': return R(529, {'error': {'message': 'Overloaded'}})
        if self.mode == 'badkey': return R(401, {'error': {'message': 'invalid x-api-key'}})
        content = json['messages'][0]['content']
        texts = [b['text'] for b in content if b['type'] == 'text']
        if any('"id"' in t and 'cdn' in t for t in texts[1:]):          # صور
            ids = [__import__('json').loads(t)['id'] for t in texts[1:]]
            out = [{'id': i, 'alt': f'حقيبة جلدية سوداء من زاوية أمامية رقم {n}'} for n, i in enumerate(ids)]
        else:
            data = __import__('json').loads(texts[0][texts[0].index('['):])
            out = [{'id': d['id'], 'title': 'مبخرة خشبية بنقش هندسي ذهبي مصنوعة يدوياً', 'description': 'مبخرة خشبية صغيرة مصنوعة يدوياً بنقش هندسي ذهبي، مناسبة لتبخير العود والبخور في المجلس والضيافة، وتضفي لمسة تراثية أنيقة على المكان.'} for d in data]
        return R(200, {'content': [{'type': 'text', 'text': '```json\n' + __import__('json').dumps(out, ensure_ascii=False) + '\n```'}]})

base = tempfile.mkdtemp()
ai.save_claude_key(base, 'CLAUDE-KEY')
items = [{'id': f'https://m.s/products/p{i}', 'type': 'product', 'name': f'مبخرة {i}', 'title': 'مبخرة', 'desc': '', 'excerpt': '', 'pdesc': 'مبخرة خشبية مصنوعة يدوياً بنقش هندسي ذهبي', 'category': '', 'brand': '', 'need': {'title', 'desc'}} for i in range(3)]
fc = FakeClaude()
cache, info = ai.generate(items, 'GEMINI-KEY-IGNORED', 'م', base, 'https://m.s', 'claude-sonnet-5-5', session=fc, suffix=' | مدهال عود', suffix_mode='add')
b = fc.bodies[0]
print('claude text ok:', len(info['run_ids']), '| rules cached in system:', b['system'][0]['cache_control'] == {'type': 'ephemeral'} and 'كاتب سيو' in b['system'][0]['text'], '| fenced JSON parsed:', bool(ai.suggestions(cache)))
imgs = [{'id': f'https://cdn/b-{i}.jpg', 'page': 'https://m.s/products/bag', 'product': 'حقيبة', 'type': 'product', 'alt': ''} for i in range(2)]
fc2 = FakeClaude()
c2, i2 = ai.generate_alts(imgs, 'GEMINI-KEY-IGNORED', base, 'https://m.s', 'claude-sonnet-5-5', session=fc2, fetch=lambda u: ('image/jpeg', 'AAAA'))
blocks = fc2.bodies[0]['messages'][0]['content']
print('claude images ok:', len(i2['run_ids']), '| image blocks:', sum(1 for x in blocks if x['type'] == 'image'), '| source:', blocks[2]['source']['type'] if len(blocks) > 2 else '-')
for mode in ('credit', 'busy'):
    d_ = tempfile.mkdtemp(); ai.save_claude_key(d_, 'CLAUDE-KEY')
    _, inf = ai.generate(items, 'X', 'م', d_, 'https://z.s', 'claude-sonnet-5-5', session=FakeClaude(mode))
    print(mode, '→ stops gracefully:', (inf['stopped'] or '')[:45])
try:
    ai.test_claude_key('CLAUDE-KEY', FakeClaude('badkey'))
except ValueError as e:
    print('bad key message:', str(e))
print('model list has Sonnet 5.5:', ai.CLAUDE_MODELS)
