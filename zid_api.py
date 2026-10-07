"""ربط زد: سحب المتاجر المربوطة من خادمك (جسر زد على Google Apps Script)، والاتصال بواجهة زد.

لا يعرض أي مفتاح أبداً، ولا يكتبه في رسائل الأخطاء. المفاتيح تُحفظ على جهازك فقط.
"""
import json
from pathlib import Path

import requests

API = 'https://api.zid.sa/v1'


# ---------------- إعدادات الجسر (على جهازك فقط) ----------------
def _cfg_path(base_dir):
    return Path(base_dir) / '.zid_bridge.json'


def load_bridge(base_dir):
    p = _cfg_path(base_dir)
    try:
        return json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
    except Exception:
        return {}


def save_bridge(base_dir, url, key):
    _cfg_path(base_dir).write_text(json.dumps({'url': url.strip(), 'key': key.strip()}), encoding='utf-8')


def _tokens_dir(base_dir):
    d = Path(base_dir) / 'zid_tokens'
    d.mkdir(exist_ok=True)
    return d


# ---------------- الجسر ----------------
def _bridge_call(cfg, payload, session=None):
    http = session or requests
    r = http.post(cfg['url'], data=json.dumps({**payload, 'key': cfg['key']}),
                  headers={'Content-Type': 'application/json'}, timeout=40, allow_redirects=True)
    try:
        data = r.json()
    except Exception:
        final = str(getattr(r, 'url', '') or '')
        text = (getattr(r, 'text', '') or '')[:3000].lower()
        if 'accounts.google.com' in final or 'servicelogin' in text or 'accounts.google.com' in text:
            raise ValueError('الجسر يطلب تسجيل دخول Google. في Apps Script: نشر ← إدارة عمليات النشر ← ✏️ ← '
                             '«من يمكنه الوصول» = «أي شخص» (Anyone)، ثم إصدار جديد ونشر.')
        if 'dopost' in text or 'script function not found' in text:
            raise ValueError('الجسر لا يحتوي الكود كاملاً. الصق كود zid_bridge.gs كاملاً، ثم انشر إصداراً جديداً.')
        raise ValueError(f'رد الخادم غير مفهوم (رمز {getattr(r, "status_code", "؟")}). '
                         'تأكد أن رابط الجسر صحيح وينتهي بـ /exec، وأن النشر «أي شخص».')
    if not data.get('ok'):
        if data.get('error') == 'unauthorized':
            raise ValueError('كلمة السر (PICKUP_KEY) لا تطابق ما في خادمك.')
        raise ValueError('رفض الخادم الطلب.')
    return data


def pull_stores(base_dir, session=None):
    """يسحب المتاجر المربوطة من الجسر ويحفظ مفاتيحها على جهازك. يعيد قائمة بلا مفاتيح."""
    cfg = load_bridge(base_dir)
    if not cfg.get('url') or not cfg.get('key'):
        raise ValueError('أدخل رابط الجسر وكلمة السر أولاً.')
    data = _bridge_call(cfg, {'action': 'list'}, session)
    out = []
    for s in data.get('stores', []):
        key = s.get('key', '')
        (_tokens_dir(base_dir) / f'{key}.json').write_text(json.dumps(s), encoding='utf-8')
        st = s.get('store') or {}
        out.append({'key': key, 'id': st.get('id', ''), 'name': st.get('name', ''), 'url': st.get('url', ''),
                    'obtained': (s.get('tokens') or {}).get('obtained', '')})
    return out


def local_stores(base_dir):
    out = []
    for f in sorted(_tokens_dir(base_dir).glob('*.json')):
        try:
            s = json.loads(f.read_text(encoding='utf-8'))
        except Exception:
            continue
        st = s.get('store') or {}
        out.append({'key': s.get('key', f.stem), 'id': st.get('id', ''), 'name': st.get('name', ''),
                    'url': st.get('url', ''), 'obtained': (s.get('tokens') or {}).get('obtained', '')})
    return out


def disconnect(base_dir, store_key, session=None):
    """يحذف مفاتيح المتجر من الخادم ومن جهازك."""
    cfg = load_bridge(base_dir)
    if cfg.get('url') and cfg.get('key'):
        _bridge_call(cfg, {'action': 'delete', 'store_key': store_key}, session)
    f = _tokens_dir(base_dir) / f'{store_key}.json'
    if f.exists():
        f.unlink()


# ---------------- واجهة زد ----------------
def _tokens(base_dir, store_key):
    f = _tokens_dir(base_dir) / f'{store_key}.json'
    if not f.exists():
        raise ValueError('مفاتيح هذا المتجر غير موجودة على جهازك. اسحب المتاجر من جديد.')
    s = json.loads(f.read_text(encoding='utf-8'))
    return s.get('tokens') or {}, s.get('store') or {}


def _headers(t, store_id=''):
    h = {'Authorization': f"Bearer {t.get('authorization', '')}", 'X-Manager-Token': t.get('access_token', ''),
         'Access-Token': t.get('access_token', ''), 'Accept-Language': 'ar', 'Accept': 'application/json'}
    if store_id:
        h['Store-Id'] = str(store_id)
        h['Role'] = 'Manager'
    return h


def _get(base_dir, store_key, path, params=None, session=None, store_id=''):
    http = session or requests
    t, st = _tokens(base_dir, store_key)
    r = http.get(f'{API}{path}', params=params or {}, headers=_headers(t, store_id or st.get('id', '')), timeout=40)
    try:
        body = r.json()
    except Exception:
        body = {}
    return r.status_code, body


def _shape(obj, depth=0, max_depth=2):
    """شكل البيانات بلا قيم: أسماء الحقول وأنواعها فقط (لا يكشف أي محتوى حساس)."""
    if isinstance(obj, dict):
        if depth >= max_depth:
            return '{…}'
        return {k: _shape(v, depth + 1, max_depth) for k, v in list(obj.items())[:60]}
    if isinstance(obj, list):
        return [_shape(obj[0], depth + 1, max_depth)] if obj else []
    return type(obj).__name__


def _find_store(d):
    """يبحث عن بيانات المتجر في رد الملف الشخصي أياً كان شكله."""
    if isinstance(d, dict):
        for k in ('store', 'Store'):
            if isinstance(d.get(k), dict) and (d[k].get('id') or d[k].get('title') or d[k].get('name')):
                return d[k]
        for v in d.values():
            r = _find_store(v)
            if r:
                return r
    return None


def test_connection(base_dir, store_key, session=None):
    """يختبر الاتصال: اسم المتجر من الملف الشخصي، وأول خمسة منتجات، وأسماء حقول المنتج."""
    result = {'store': {}, 'products': [], 'product_fields': None, 'profile_status': None, 'products_status': None}
    code, prof = _get(base_dir, store_key, '/managers/account/profile', session=session)
    result['profile_status'] = code
    st = _find_store(prof) or {}
    result['store'] = {'id': str(st.get('id', '') or ''), 'name': st.get('title') or st.get('name') or '',
                       'url': st.get('url') or st.get('domain') or ''}
    if result['store']['id']:
        f = _tokens_dir(base_dir) / f'{store_key}.json'
        s = json.loads(f.read_text(encoding='utf-8'))
        s['store'] = {**(s.get('store') or {}), **{k: v for k, v in result['store'].items() if v}}
        f.write_text(json.dumps(s), encoding='utf-8')
    code, body = _get(base_dir, store_key, '/products/', {'page': 1, 'per_page': 5}, session=session,
                      store_id=result['store']['id'])
    result['products_status'] = code
    items = body.get('results') or body.get('products') or body.get('data') or []
    if isinstance(items, dict):
        items = items.get('data') or items.get('results') or []
    for p in items[:5]:
        nm = p.get('name')
        if isinstance(nm, dict):
            nm = nm.get('ar') or nm.get('en') or next(iter(nm.values()), '')
        result['products'].append({'id': p.get('id'), 'name': nm, 'slug': p.get('slug') or p.get('html_url', '')})
    if items:
        result['product_fields'] = _shape(items[0])
    elif body:
        result['product_fields'] = _shape(body)
    return result
