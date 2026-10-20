import sys, json, tempfile
sys.path.insert(0, '/home/claude/work')
import zid_api as z
class R:
    def __init__(self, code, data=None, headers=None, url=''): self.status_code, self._d, self.headers, self.url, self.text = code, data, headers or {}, url, ''
    def json(self):
        if self._d is None: raise ValueError
        return self._d
class AppsScript:
    """مثل Google: الإرسال يرد بتحويل 302، وفتح التحويل بإرسال آخر = 404، وبطلب قراءة = النتيجة."""
    def __init__(self): self.body = None
    def post(self, url, data=None, headers=None, timeout=None, allow_redirects=True):
        self.body = json.loads(data)
        if 'googleusercontent' in url: return R(404)
        r = R(302, headers={'Location': 'https://script.googleusercontent.com/macros/echo?user_content_key=abc'})
        return self.post('https://script.googleusercontent.com/x', data, headers) if allow_redirects else r
    def get(self, url, timeout=None, allow_redirects=True, params=None, headers=None):
        ok = self.body and self.body.get('key') == 'PICKUP-KEY-LONG-ENOUGH'
        return R(200, {'ok': True, 'stores': [{'key': 'store_1', 'store': {}, 'tokens': {'obtained': 'x'}}]} if ok else {'ok': False, 'error': 'unauthorized'})
b = tempfile.mkdtemp(); z.save_bridge(b, 'https://script.google.com/macros/s/X/exec', 'PICKUP-KEY-LONG-ENOUGH')
print('pulled through Google redirect:', len(z.pull_stores(b, AppsScript())))
