import sys, requests
sys.path.insert(0, '/home/claude/work')
import audit_engine as e
e.HAS_PLAYWRIGHT = False; e.HAS_USP = False; e.time.sleep = lambda s: None
def mk(url, status=200, body='', ctype='text/html; charset=utf-8', hist=()):
    r = requests.Response(); r.status_code = status; r.url = url; r._content = body.encode(); r.encoding = 'utf-8'
    r.headers = requests.structures.CaseInsensitiveDict({'Content-Type': ctype}); r.history = list(hist); return r
def path_of(url):
    return e.unquote(e.urlparse(e.clean_url(url)).path).rstrip('/')
def product(title, extra=''):
    return f'<html><head><meta property="og:type" content="product"><title>{title}</title></head><body><h1>{title}</h1>{extra}</body></html>'
def scan(fake, base, **kw):
    e.safe_get = fake
    kw.setdefault('use_cache', False)
    return e.run_full_scan(base, max_pages=kw.pop('max_pages', 300), workers=3, **kw)
def check_line(res, title):
    return [c for c in res['selfcheck']['checks'] if c['title'] == title]
