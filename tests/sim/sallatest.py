import sys, json, tempfile
sys.path.insert(0, '/home/claude/work')
import zid_api as z
class R:
    def __init__(self, c, d): self.status_code, self._d = c, d
    def json(self): return self._d
class Salla:
    def get(self, url, params=None, headers=None, timeout=None):
        if 'user/info' in url: return R(200, {'data': {'merchant': {'id': 777, 'name': 'متجر سلة التجريبي', 'domain': 'd'}}})
        return R(200, {'data': [{'id': 9, 'name': 'عباية', 'url': 'u'}]})
b = tempfile.mkdtemp()
(z._tokens_dir(b) / 'salla_777.json').write_text(json.dumps({'key': 'salla_777', 'platform': 'salla', 'store': {}, 'tokens': {'access_token': 'SECRET-AT', 'obtained': 'x'}}))
r = z.test_connection(b, 'salla_777', Salla())
print('salla ok:', r['store']['name'], len(r['products']), '| leak:', 'SECRET-AT' in json.dumps(r, ensure_ascii=False))
