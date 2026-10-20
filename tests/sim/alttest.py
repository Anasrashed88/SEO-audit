import sys, json, tempfile, shutil
sys.path.insert(0, '/home/claude/work')
import ai_writer as ai
import pandas as pd
ai.time.sleep = lambda s: None

class R:
    def __init__(self, code, data): self.status_code, self._d = code, data
    def json(self): return self._d
    def raise_for_status(self): pass

class FakeVision:
    def __init__(self): self.calls, self.images_seen = 0, 0
    def post(self, url, params=None, json=None, timeout=None, headers=None):
        assert 'key' not in (params or {})
        self.calls += 1
        parts = json['contents'][0]['parts']
        ids = [__import__('json').loads(p['text'])['id'] for p in parts[1:] if 'text' in p]
        self.images_seen += sum(1 for p in parts if 'inline_data' in p)
        out = []
        for i, img in enumerate(ids):
            n = int(img.rsplit('-', 1)[1].split('.')[0])
            alt = 'صورة مبخرة' if n == 2 else f'مبخرة خشبية بنقوش هندسية ملونة من زاوية جانبية رقم {n}'
            if n == 4: alt = 'مبخرة خشبية بنقوش هندسية ملونة من زاوية جانبية رقم 3'   # مكرر مع صورة أخرى في نفس الصفحة
            out.append({'id': img, 'alt': alt})
        return R(200, {'candidates': [{'content': {'parts': [{'text': __import__('json').dumps(out, ensure_ascii=False)}]}}]})

def fetch(u):
    return None if u.endswith('-9.svg') else ('image/jpeg', 'AAAA')

P = 'https://m.s/products/مبخرة'
miss = pd.DataFrame([{'م': i, 'رابط الصفحة': P, 'نوع الصفحة': 'صفحة منتج', 'رابط الصورة': f'https://cdn/m-{i}.jpg' if i != 9 else 'https://cdn/m-9.svg',
                      'النص البديل الحالي (Alt)': 'لا يوجد (فارغ)'} for i in range(1, 10)])
weak = pd.DataFrame([{'م': 1, 'رابط الصفحة': 'https://m.s/', 'نوع الصفحة': 'صفحة رئيسية', 'رابط الصورة': 'https://cdn/home-11.jpg', 'النص البديل الحالي (Alt)': 'image'}])
ex = {'alt_missing': ('x', miss), 'alt_weak': ('y', weak)}
df = pd.DataFrame([{'الرابط': P, 'نوع الصفحة': 'product', 'اسم المنتج المعروض': 'مبخرة خشبية بنقوش'}, {'الرابط': 'https://m.s/', 'نوع الصفحة': 'home', 'اسم المنتج المعروض': 'الأقسام'}])
items = ai.items_from_images(ex, df)
print('items:', len(items), '| home named:', [i['product'] for i in items if i['page'] == 'https://m.s/'], '| weak current alt kept:', items[-1]['alt'])
base = tempfile.mkdtemp(); fv = FakeVision()
cache, info = ai.generate_alts(items, 'K', base, 'https://m.s', 'gemini-3.6-flash', session=fv, fetch=fetch)
alts = ai.alt_suggestions(cache)
print('requests:', fv.calls, '| images sent:', fv.images_seen, '| generated:', len(info['run_ids']))
print('starts with صورة flagged:', cache['img::https://cdn/m-2.jpg']['alt_notes'])
print('duplicate on same page flagged:', cache['img::https://cdn/m-4.jpg']['alt_notes'])
print('unreadable image noted:', cache['img::https://cdn/m-9.svg']['alt_notes'])
f = ai.compact_alt_file(ex, cache, df)
print('alt file columns:', list(f.columns), '| rows:', len(f))
fv2 = FakeVision(); ai.generate_alts(items, 'K', base, 'https://m.s', 'gemini-3.6-flash', session=fv2, fetch=fetch)
print('second run requests:', fv2.calls)
shutil.rmtree(base)
