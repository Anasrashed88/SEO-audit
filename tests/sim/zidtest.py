import sys, json, tempfile
sys.path.insert(0, '/home/claude/work')
import zid_api as z

SECRET_A, SECRET_B = 'TOKEN-AUTH-SECRET-123', 'MANAGER-TOKEN-SECRET-456'
class R:
    def __init__(self, code, data): self.status_code, self._d = code, data
    def json(self): return self._d
class Fake:
    def __init__(self): self.calls = []
    def post(self, url, data=None, headers=None, timeout=None, allow_redirects=True):
        body = json.loads(data)
        if body['key'] != 'PICKUP-KEY-LONG-ENOUGH':
            return R(200, {'ok': False, 'error': 'unauthorized'})
        if body['action'] == 'list':
            return R(200, {'ok': True, 'stores': [{'key': 'store_abc', 'store': {'id': '', 'name': '', 'url': ''},
                     'tokens': {'access_token': SECRET_B, 'authorization': SECRET_A, 'obtained': '2026-10-07T19:00:00Z'}}]})
        return R(200, {'ok': True})
    def get(self, url, params=None, headers=None, timeout=None):
        assert headers['Authorization'] == 'Bearer ' + SECRET_A and headers['X-Manager-Token'] == SECRET_B
        self.calls.append(url)
        if url.endswith('/managers/account/profile'):
            return R(200, {'user': {'name': 'أنس', 'store': {'id': 3257423, 'title': 'متجر أنس التجريبي', 'url': 'https://test.zid.store'}}})
        return R(200, {'results': [{'id': 11, 'name': {'ar': 'مبخرة خشبية', 'en': 'Wooden burner'}, 'slug': 'مبخرة-خشبية',
                                    'seo': {'title': 'x', 'description': 'y'}, 'images': [{'image': {'full_size': 'u'}, 'alt_text': ''}]}]})

base = tempfile.mkdtemp()
fake = Fake()
z.save_bridge(base, 'https://script.google.com/macros/s/X/exec', 'WRONG-KEY-0000000000')
try:
    z.pull_stores(base, fake); print('wrong key: NOT rejected')
except ValueError as e:
    print('wrong key rejected:', 'لا تطابق' in str(e))
z.save_bridge(base, 'https://script.google.com/macros/s/X/exec', 'PICKUP-KEY-LONG-ENOUGH')
stores = z.pull_stores(base, fake)
print('pulled:', len(stores), '| listing has no tokens:', SECRET_A not in json.dumps(stores) and SECRET_B not in json.dumps(stores))
res = z.test_connection(base, 'store_abc', fake)
print('store identified:', res['store']['name'], res['store']['id'])
print('products:', res['products'])
print('fields shape:', json.dumps(res['product_fields'], ensure_ascii=False)[:160])
print('no secrets in test result:', SECRET_A not in json.dumps(res, ensure_ascii=False) and SECRET_B not in json.dumps(res, ensure_ascii=False))
print('local listing updated with name:', z.local_stores(base)[0]['name'])
z.disconnect(base, 'store_abc', fake)
print('after disconnect local stores:', len(z.local_stores(base)))
