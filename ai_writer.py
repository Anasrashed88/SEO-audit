"""الذكاء الاصطناعي: اقتراح عناوين وأوصاف الميتا عبر Gemini.

مستقل عن المنصات: يأخذ بيانات الصفحات من نتائج الفحص، ويعيد اقتراحات بعد التحقق منها.
- يرسل 20 صفحة في الطلب الواحد (توفيراً للحصة اليومية المجانية).
- يتحقق من كل اقتراح: الطول، والتكرار، وعدم اختراع أرقام غير موجودة في بيانات الصفحة.
- يعيد كتابة المخالف مرة واحدة، وما بقي مخالفاً يُعلَّم «يحتاج مراجعتك».
- يحفظ الاقتراحات على جهازك، فلا يُعاد طلب ما وُلّد سابقاً.
"""
import json
import re
import time
from pathlib import Path

import requests

API = 'https://generativelanguage.googleapis.com/v1beta'
BATCH = 20
TITLE_MIN, TITLE_MAX = 50, 60
DESC_MIN, DESC_MAX = 120, 160
STATUS_OK = 'مطابق للقواعد'
STATUS_REVIEW = 'يحتاج مراجعتك'


class QuotaExhausted(Exception):
    """انتهت الحصة اليومية أو الدقيقة: نتوقف ونحفظ ما أُنجز."""


# ---------------- المفتاح (على جهازك فقط) ----------------
def key_path(base_dir):
    return Path(base_dir) / '.gemini_key'


def load_key(base_dir):
    p = key_path(base_dir)
    return p.read_text(encoding='utf-8').strip() if p.exists() else ''


def save_key(base_dir, key):
    key_path(base_dir).write_text((key or '').strip(), encoding='utf-8')


# ---------------- اختيار النموذج ----------------
_MODEL_CACHE = {}


def pick_model(key, session=None):
    """يختار تلقائياً أحدث نموذج Flash-Lite متاح (أعلى حصة مجانية يومية)، ثم Flash."""
    if key in _MODEL_CACHE:
        return _MODEL_CACHE[key]
    http = session or requests
    r = http.get(f'{API}/models', params={'key': key, 'pageSize': 200}, timeout=20)
    if r.status_code in (400, 401, 403):
        raise ValueError('المفتاح غير صحيح أو غير مفعّل.')
    r.raise_for_status()
    names = [m['name'].split('/', 1)[-1] for m in r.json().get('models', [])
             if 'generateContent' in m.get('supportedGenerationMethods', [])]

    def version(n):
        nums = re.findall(r'\d+(?:\.\d+)?', n)
        return float(nums[0]) if nums else 0.0

    for pref in ('flash-lite', 'flash'):
        cands = [n for n in names if pref in n and 'preview' not in n and 'exp' not in n
                 and 'tts' not in n and 'image' not in n and 'live' not in n and 'audio' not in n]
        if pref == 'flash':
            cands = [n for n in cands if 'lite' not in n]
        if cands:
            best = sorted(cands, key=lambda n: (version(n), len(n)), reverse=True)[0]
            _MODEL_CACHE[key] = best
            return best
    raise ValueError('لم يُعثر على نموذج Gemini مناسب لهذا المفتاح.')


def _generate(key, model, prompt, session=None):
    http = session or requests
    body = {'contents': [{'role': 'user', 'parts': [{'text': prompt}]}],
            'generationConfig': {'temperature': 0.5, 'responseMimeType': 'application/json'}}
    for attempt in range(3):
        r = http.post(f'{API}/models/{model}:generateContent', params={'key': key}, json=body, timeout=90)
        if r.status_code == 429:
            delay = _retry_delay(r)
            if delay is None or delay > 70 or attempt == 2:
                raise QuotaExhausted('انتهت الحصة المتاحة الآن. أكمل لاحقاً، وسيُكمل من حيث توقف.')
            time.sleep(delay + 1)
            continue
        if r.status_code >= 500 and attempt < 2:
            time.sleep(4)
            continue
        if r.status_code in (400, 401, 403):
            raise ValueError(f'رفض Gemini الطلب ({r.status_code}): تحقق من المفتاح.')
        r.raise_for_status()
        data = r.json()
        try:
            return data['candidates'][0]['content']['parts'][0]['text']
        except (KeyError, IndexError):
            return '[]'
    return '[]'


def _retry_delay(r):
    try:
        for d in r.json().get('error', {}).get('details', []):
            if 'retryDelay' in d:
                return float(str(d['retryDelay']).rstrip('s'))
    except Exception:
        pass
    return 30.0


def test_key(key, session=None):
    """يتحقق من المفتاح ويعيد اسم النموذج الذي ستستخدمه الأداة."""
    model = pick_model(key, session)
    _generate(key, model, 'Reply with JSON: {"ok": true}', session)
    return model


# ---------------- الكتابة ----------------
RULES_AR = f"""أنت كاتب سيو محترف لمتاجر إلكترونية سعودية. اكتب لكل صفحة في المدخلات:
- "title": عنوان ميتا بين {TITLE_MIN} و{TITLE_MAX} حرفاً (المسافات والرموز محسوبة).
- "description": وصف ميتا بين {DESC_MIN} و{DESC_MAX} حرفاً.
القواعد:
1. استخدم فقط الحقائق الموجودة في بيانات الصفحة نفسها (الاسم، المقتطف، العنوان والوصف الحاليان). لا تخترع مقاساً أو مادة أو رقماً أو سعراً أو عرضاً.
2. ابدأ العنوان بالكلمة التي يبحث بها الزبون عن هذا المنتج أو القسم، ثم ما يميزه، واختمه باسم المتجر بعد « | » إن اتسع الطول.
3. الوصف يشرح ما يجده الزبون في الصفحة بلغة طبيعية مقنعة، وينتهي بدعوة لطيفة للتصفح أو الشراء.
4. اكتب بلغة بيانات الصفحة نفسها (عربية فصحى سهلة، أو إنجليزية إن كانت الصفحة إنجليزية).
5. كل عنوان ووصف مختلف عن غيره. لا رموز تعبيرية، ولا علامات تنصيص، ولا حروف كبيرة كاملة.
6. أعد JSON فقط بالشكل: [{{"id": "...", "title": "...", "description": "..."}}]"""


def _item_payload(it, store_name):
    return {'id': it['id'], 'type': it.get('type', ''), 'name': it.get('name', ''),
            'current_title': it.get('title', ''), 'current_description': it.get('desc', ''),
            'excerpt': (it.get('excerpt') or '')[:500], 'store': store_name}


def _numbers(text):
    return set(re.findall(r'\d+(?:[.,]\d+)?', str(text or '').translate(str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789'))))


def check(item, title, desc, seen_titles, seen_descs, need):
    """يعيد (الحالة، الملاحظات). need: الحقول المطلوبة من هذه الصفحة."""
    notes = []
    source = ' '.join(str(item.get(k, '')) for k in ('name', 'title', 'desc', 'excerpt'))
    allowed = _numbers(source)
    if 'title' in need:
        n = len(title or '')
        if not (TITLE_MIN <= n <= TITLE_MAX):
            notes.append(f'طول العنوان {n} (المطلوب {TITLE_MIN}–{TITLE_MAX})')
        if title and title.strip() in seen_titles:
            notes.append('العنوان مكرر مع صفحة أخرى')
        if _numbers(title) - allowed:
            notes.append('في العنوان رقم غير موجود في بيانات الصفحة')
    if 'desc' in need:
        n = len(desc or '')
        if not (DESC_MIN <= n <= DESC_MAX):
            notes.append(f'طول الوصف {n} (المطلوب {DESC_MIN}–{DESC_MAX})')
        if desc and desc.strip() in seen_descs:
            notes.append('الوصف مكرر مع صفحة أخرى')
        if _numbers(desc) - allowed:
            notes.append('في الوصف رقم غير موجود في بيانات الصفحة')
    return (STATUS_OK if not notes else STATUS_REVIEW), notes


def _parse(text):
    try:
        data = json.loads(text)
    except Exception:
        m = re.search(r'\[.*\]', text or '', re.S)
        try:
            data = json.loads(m.group(0)) if m else []
        except Exception:
            data = []
    if isinstance(data, dict):
        data = data.get('items') or data.get('pages') or [data]
    return {str(d.get('id')): d for d in data if isinstance(d, dict) and d.get('id') is not None}


# ---------------- الحفظ على الجهاز ----------------
def cache_file(base_dir, store_url):
    host = re.sub(r'[^a-z0-9.\-]', '_', re.sub(r'^https?://(www\.)?', '', str(store_url).lower()).split('/')[0])
    d = Path(base_dir) / 'ai_cache'
    d.mkdir(exist_ok=True)
    return d / f'{host}.json'


def load_cache(base_dir, store_url):
    f = cache_file(base_dir, store_url)
    try:
        return json.loads(f.read_text(encoding='utf-8')) if f.exists() else {}
    except Exception:
        return {}


def save_cache(base_dir, store_url, data):
    cache_file(base_dir, store_url).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')


def generate(items, key, store_name, base_dir, store_url, need=('title', 'desc'), regenerate=False,
             progress=None, session=None, max_items=None):
    """items: [{'id': رابط الصفحة, 'type', 'name', 'title', 'desc', 'excerpt', 'need': {'title','desc'}}]
    يعيد {الرابط: {'title', 'description', 'status', 'notes'}} — ويحفظ كل دفعة فور إنجازها."""
    cache = load_cache(base_dir, store_url)
    todo = [it for it in items if regenerate or it['id'] not in cache
            or any(f not in cache[it['id']] for f in ('title', 'description'))]
    if max_items:
        todo = todo[:max_items]
    model = pick_model(key, session)
    seen_t = {v.get('title', '').strip() for v in cache.values()}
    seen_d = {v.get('description', '').strip() for v in cache.values()}
    done, stopped = 0, None
    for start in range(0, len(todo), BATCH):
        batch = todo[start:start + BATCH]
        prompt = RULES_AR + '\n\nبيانات الصفحات:\n' + json.dumps(
            [_item_payload(it, store_name) for it in batch], ensure_ascii=False)
        try:
            out = _parse(_generate(key, model, prompt, session))
            # إعادة كتابة المخالف مرة واحدة، مع ذكر سبب المخالفة
            retry = []
            for it in batch:
                d = out.get(str(it['id']))
                if not d:
                    retry.append((it, ['لم يُكتب']))
                    continue
                st, notes = check(it, d.get('title', ''), d.get('description', ''), seen_t, seen_d,
                                  it.get('need', need))
                if st != STATUS_OK:
                    retry.append((it, notes))
            if retry:
                fix_prompt = RULES_AR + '\n\nأعد كتابة هذه الصفحات فقط، وتجنب المخالفات المذكورة لكل صفحة:\n' + \
                    json.dumps([{**_item_payload(it, store_name), 'problems': notes} for it, notes in retry],
                               ensure_ascii=False)
                out.update(_parse(_generate(key, model, fix_prompt, session)))
        except QuotaExhausted as q:
            stopped = str(q)
            break
        for it in batch:
            d = out.get(str(it['id']))
            if not d:
                continue
            t, de = (d.get('title') or '').strip(), (d.get('description') or '').strip()
            st, notes = check(it, t, de, seen_t, seen_d, it.get('need', need))
            cache[it['id']] = {'title': t, 'description': de, 'status': st, 'notes': '، '.join(notes),
                               'model': model}
            seen_t.add(t)
            seen_d.add(de)
        save_cache(base_dir, store_url, cache)
        done += len(batch)
        if progress:
            progress(done, len(todo))
    return cache, {'requested': len(todo), 'done': done, 'stopped': stopped, 'model': model}


# ---------------- من نتائج الفحص إلى عناصر، ومن الاقتراحات إلى ملفات قبل/بعد ----------------
def items_from_scan(df, exports):
    """الصفحات التي تحتاج عنواناً أو وصفاً (نفس ملفات العمل)، مع بياناتها من الفحص."""
    need = {}
    for key, field in (('titles', 'title'), ('descs', 'desc')):
        v = exports.get(key)
        if v:
            for u in v[1]['الرابط']:
                need.setdefault(str(u), set()).add(field)
    rows = df.set_index('الرابط') if 'الرابط' in df.columns else None
    items = []
    for url, fields in need.items():
        r = rows.loc[url] if rows is not None and url in rows.index else None
        if r is not None and hasattr(r, 'iloc') and getattr(r, 'ndim', 1) > 1:
            r = r.iloc[0]
        g = (lambda c: '' if r is None or str(r.get(c, '')) == 'nan' else str(r.get(c, '') or ''))
        items.append({'id': url, 'type': g('نوع الصفحة'), 'name': g('اسم منظم') or g('اسم المنتج المعروض'),
                      'title': g('عنوان الميتا'), 'desc': g('وصف الميتا'), 'excerpt': g('_excerpt'),
                      'need': fields})
    return items


def before_after(exports, cache):
    """ملفات العمل نفسها، ومعها أعمدة الاقتراح."""
    out = {}
    for key, field, label in (('titles', 'title', 'العنوان'), ('descs', 'description', 'الوصف')):
        v = exports.get(key)
        if not v:
            continue
        t = v[1].copy()
        sug = t['الرابط'].map(lambda u: (cache.get(str(u)) or {}).get(field, ''))
        t[f'{label} المقترح'] = sug
        t[f'طول {label} المقترح'] = sug.map(lambda s: len(s) if s else '')
        t['حالة الاقتراح'] = t['الرابط'].map(lambda u: (cache.get(str(u)) or {}).get('status', 'لم يُولَّد بعد'))
        t['ملاحظات الاقتراح'] = t['الرابط'].map(lambda u: (cache.get(str(u)) or {}).get('notes', ''))
        out[key] = (f"قبل_وبعد_{'العناوين' if key == 'titles' else 'الأوصاف'}.xlsx", t)
    return out
