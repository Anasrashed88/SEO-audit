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
    """انتهت الحصة اليومية أو الدقيقة، أو خوادم جوجل مشغولة طويلاً: نتوقف ونحفظ ما أُنجز."""


def _hdr(key):
    # المفتاح في الترويسة لا في الرابط: فلا يظهر أبداً في رسائل الخطأ
    return {'x-goog-api-key': key}


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


def list_models(key, session=None):
    """النماذج المتاحة لهذا المفتاح للكتابة، بلا Lite (جودته أقل)، الأحدث أولاً."""
    http = session or requests
    r = http.get(f'{API}/models', params={'pageSize': 200}, headers=_hdr(key), timeout=20)
    if r.status_code in (400, 401, 403):
        raise ValueError('المفتاح غير صحيح أو غير مفعّل.')
    r.raise_for_status()
    names = [m['name'].split('/', 1)[-1] for m in r.json().get('models', [])
             if 'generateContent' in m.get('supportedGenerationMethods', [])]
    bad = ('lite', 'preview', 'exp', 'tts', 'image', 'live', 'audio', 'embedding', 'gemma', 'learnlm')
    names = [n for n in names if n.startswith('gemini') and not any(b in n for b in bad)]

    def version(n):
        nums = re.findall(r'\d+(?:\.\d+)?', n)
        return float(nums[0]) if nums else 0.0
    return sorted(set(names), key=lambda n: (version(n), 'pro' in n, -len(n)), reverse=True)


def default_model(models):
    """الافتراضي: أحدث Flash (جودة عالية بحصة يومية معقولة)."""
    flash = [m for m in models if 'flash' in m]
    return (flash or models or [''])[0]


def pick_model(key, session=None):
    """(للتوافق) أحدث Flash متاح، بلا Lite."""
    if key in _MODEL_CACHE:
        return _MODEL_CACHE[key]
    best = default_model(list_models(key, session))
    if not best:
        raise ValueError('لم يُعثر على نموذج Gemini مناسب لهذا المفتاح.')
    _MODEL_CACHE[key] = best
    return best


def _generate(key, model, prompt, session=None):
    http = session or requests
    body = {'contents': [{'role': 'user', 'parts': [{'text': prompt}]}],
            'generationConfig': {'temperature': 0.5, 'responseMimeType': 'application/json'}}
    busy_waits = [5, 15, 30, 60]          # خوادم جوجل مشغولة (500/503): ننتظر ونعيد، بفترات متزايدة
    for attempt in range(len(busy_waits) + 1):
        try:
            r = http.post(f'{API}/models/{model}:generateContent', json=body, headers=_hdr(key), timeout=120)
        except requests.exceptions.RequestException:
            if attempt < len(busy_waits):
                time.sleep(busy_waits[attempt])
                continue
            raise QuotaExhausted('تعذّر الاتصال بخوادم جوجل. تحقق من الإنترنت، ثم أكمل وسيُكمل من حيث توقف.')
        if r.status_code == 429:
            delay = _retry_delay(r)
            if delay is None or delay > 70 or attempt >= 2:
                raise QuotaExhausted('انتهت الحصة المتاحة الآن. أكمل لاحقاً، وسيُكمل من حيث توقف.')
            time.sleep(delay + 1)
            continue
        if r.status_code >= 500:
            if attempt < len(busy_waits):
                time.sleep(busy_waits[attempt])
                continue
            raise QuotaExhausted('خوادم جوجل مشغولة الآن (خطأ مؤقت منهم). حاول بعد دقائق، وسيُكمل من حيث توقف.')
        if r.status_code in (400, 401, 403):
            raise ValueError(f'رفض Gemini الطلب ({r.status_code}): تحقق من المفتاح.')
        if r.status_code >= 400:
            raise ValueError(f'رد Gemini بخطأ {r.status_code}.')
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


# ---------------- اسم المتجر في العناوين ----------------
_SEP_RE = re.compile(r'\s+[|\-–—]\s+')


def detect_title_suffix(titles):
    """يكتشف العبارة التي تنتهي بها عناوين المتجر (« | مدهال عود»).
    يعيد (العبارة بفاصلها، الوضع): 'auto' = المنصة تضيفها تلقائياً (90% من العناوين أو أكثر)،
    'add' = يكتبها التاجر فنضيفها نحن، None = لا عبارة."""
    tails = []
    for t in titles:
        parts = _SEP_RE.split(str(t or '').strip())
        if len(parts) >= 2 and 2 <= len(parts[-1]) <= 40:
            m = list(_SEP_RE.finditer(str(t).strip()))[-1]
            tails.append(str(t).strip()[m.start():])
    valid = [t for t in titles if str(t or '').strip()]
    if not tails or not valid:
        return '', None
    from collections import Counter
    top, cnt = Counter(tails).most_common(1)[0]
    share = cnt / len(valid)
    if share >= 0.9:
        return top, 'auto'
    if share >= 0.3:
        return top, 'add'
    return '', None


def title_budget(suffix):
    """طول الجزء الذي يكتبه النموذج، ليكتمل العنوان كاملاً بين 50 و60 مع اسم المتجر."""
    n = len(suffix or '')
    return TITLE_MIN - n, TITLE_MAX - n


# ---------------- الكتابة ----------------
TYPE_GUIDE = {
    'صفحة منتج': 'منتج: صف المنتج نفسه وما يميزه.',
    'صفحة تصنيف': 'قسم: صف مجموعة المنتجات في هذا القسم ولمن تناسب، لا منتجاً واحداً.',
    'صفحة رئيسية': 'الصفحة الرئيسية: عرّف بالمتجر وتخصصه وأهم ما يقدمه.',
    'صفحة مدونة': 'مقال: لخّص موضوع المقال وفائدته للقارئ.',
    'صفحة تعريفية': 'صفحة تعريفية أو سياسة: وضّح محتواها بدقة ووضوح.',
}


def rules_text(t_min, t_max):
    return f"""أنت كاتب سيو محترف لمتاجر إلكترونية سعودية. اكتب لكل صفحة في المدخلات:
- "title": الجزء الوصفي من عنوان الميتا، بين {t_min} و{t_max} حرفاً بالضبط (المسافات محسوبة). لا تكتب اسم المتجر فيه: الأداة تضيفه.
- "description": وصف ميتا بين {DESC_MIN} و{DESC_MAX} حرفاً.
القواعد:
1. افهم المنتج أو الصفحة من "product_description" و"category" و"excerpt" أولاً، ثم اكتب. استخدم فقط الحقائق الموجودة فيها؛ لا تخترع مقاساً أو مادة أو رقماً.
1-ب. في الوصف: اذكر حقيقتين محددتين على الأقل من بيانات الصفحة (المادة، الاستخدام، المكونات، الرائحة، الحجم، طريقة الصنع، المنشأ...). الوصف الذي يصلح لأي منتج آخر مرفوض.
1-ج. تجنب الحشو العام: «بكل سهولة»، «تجربة شراء مميزة»، «بجودة عالية»، «لا تفوت الفرصة»، «أنيق وفاخر» بلا سبب.
مثال وصف مرفوض: «مبخرة خشبية بتصميم أنيق تناسب المجالس، تسوق الآن بكل سهولة وجودة عالية.»
مثال وصف جيد: «مبخرة خشبية صغيرة مصنوعة يدوياً بنقش هندسي ملون، مناسبة لتبخير العود والبخور في المجلس والضيافة. اطلبها الآن من المتجر.»
2. لا سعر ولا خصم ولا عرض ولا كوبون في العنوان أو الوصف: الأسعار والعروض تتغير.
3. ابدأ العنوان بالعبارة التي يبحث بها الزبون عن هذا المنتج أو القسم، ثم ما يميزه.
4. لا تنسخ العنوان أو الوصف الحالي: اكتب صياغة جديدة أفضل.
5. اكتب بلغة الصفحة نفسها (عربية فصحى سهلة، أو إنجليزية إن كانت الصفحة إنجليزية). لا رموز تعبيرية ولا علامات تنصيص.
6. كل عنوان ووصف مختلف عن غيره.
7. حسب نوع الصفحة: {' '.join(TYPE_GUIDE.values())}
أعد JSON فقط بالشكل: [{{"id": "...", "title": "...", "description": "..."}}]"""


def _item_payload(it):
    return {'id': it['id'], 'type': it.get('type', ''), 'name': it.get('name', ''),
            'category': it.get('category', ''), 'brand': it.get('brand', ''),
            'product_description': (it.get('pdesc') or '')[:1200],
            'current_title': it.get('title', ''), 'current_description': it.get('desc', ''),
            'excerpt': (it.get('excerpt') or '')[:400]}


def _numbers(text):
    return set(re.findall(r'\d+(?:[.,]\d+)?', str(text or '').translate(str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789'))))


_PROMO_RE = re.compile(r'\d+\s*(?:ريال|ر\.?\s?س|sar|﷼)|خصم|كوبون|تخفيض|عرض خاص|عروض|discount|coupon|% ?off', re.I)


def _norm(t):
    return re.sub(r'[\W_]+', '', str(t or '')).lower()


def _same(a, b):
    from difflib import SequenceMatcher
    na, nb = _norm(a), _norm(b)
    # 0.8: تغيير كلمة أو كلمتين في نص الحالي يُعد نسخاً، ويُطلب صياغة جديدة فعلاً
    return bool(na) and bool(nb) and (na == nb or SequenceMatcher(None, na, nb).ratio() >= 0.8)


def check(item, title_full, desc, seen_titles, seen_descs, need):
    """يعيد (حالة، ملاحظات العنوان، ملاحظات الوصف). title_full: العنوان كما سيظهر في جوجل."""
    t_notes, d_notes = [], []
    source = ' '.join(str(item.get(k, '')) for k in ('name', 'title', 'desc', 'excerpt', 'pdesc', 'category'))
    allowed = _numbers(source)
    if 'title' in need and item.get('fixed_title'):
        pass                                     # صفحة ثابتة: عنوانها اسمها المعروف، لا 50–60
    elif 'title' in need:
        n = len(title_full or '')
        if not (TITLE_MIN <= n <= TITLE_MAX):
            t_notes.append(f'طول العنوان {n} (المطلوب {TITLE_MIN}–{TITLE_MAX})')
        if title_full and title_full.strip() in seen_titles:
            t_notes.append('مكرر مع صفحة أخرى')
        if _numbers(title_full) - allowed:
            t_notes.append('فيه رقم غير موجود في بيانات الصفحة')
        if _same(title_full, item.get('title')):
            t_notes.append('منسوخ من العنوان الحالي')
        if _PROMO_RE.search(title_full or ''):
            t_notes.append('فيه سعر أو عرض')
    if 'desc' in need:
        n = len(desc or '')
        if not (DESC_MIN <= n <= DESC_MAX):
            d_notes.append(f'طول الوصف {n} (المطلوب {DESC_MIN}–{DESC_MAX})')
        if desc and desc.strip() in seen_descs:
            d_notes.append('مكرر مع صفحة أخرى')
        if _numbers(desc) - allowed:
            d_notes.append('فيه رقم غير موجود في بيانات الصفحة')
        if _same(desc, item.get('desc')):
            d_notes.append('منسوخ من الوصف الحالي')
        if _PROMO_RE.search(desc or ''):
            d_notes.append('فيه سعر أو عرض')
    status = STATUS_OK if not (t_notes or d_notes) else STATUS_REVIEW
    return status, t_notes, d_notes


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


def suggestions(cache):
    """الاقتراحات الحالية فقط: ما كُتب بالنسخة القديمة (بلا title_notes) يُعامل كأنه لم يُولّد."""
    return {k: v for k, v in cache.items() if not k.startswith('__') and isinstance(v, dict) and 'title_notes' in v}


def store_model(cache):
    """النموذج الثابت لهذا المتجر (يُحدد مع أول توليد)."""
    return (cache.get('__meta__') or {}).get('model', '')


# ---------------- عدّاد الطلبات اليومي ----------------
def _pacific_day():
    from datetime import datetime
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo('America/Los_Angeles')).strftime('%Y-%m-%d')
    except Exception:
        from datetime import timedelta, timezone
        return datetime.now(timezone(timedelta(hours=-8))).strftime('%Y-%m-%d')


def usage_today(base_dir, model):
    f = Path(base_dir) / 'ai_cache' / '_usage.json'
    try:
        data = json.loads(f.read_text(encoding='utf-8')) if f.exists() else {}
    except Exception:
        data = {}
    return int(data.get(_pacific_day(), {}).get(model, 0))


def _count_request(base_dir, model):
    d = Path(base_dir) / 'ai_cache'
    d.mkdir(exist_ok=True)
    f = d / '_usage.json'
    try:
        data = json.loads(f.read_text(encoding='utf-8')) if f.exists() else {}
    except Exception:
        data = {}
    day = _pacific_day()
    data = {day: data.get(day, {})}                 # نحتفظ باليوم الحالي فقط
    data[day][model] = int(data[day].get(model, 0)) + 1
    f.write_text(json.dumps(data), encoding='utf-8')


def generate(items, key, store_name, base_dir, store_url, model, need=('title', 'desc'), regenerate=False,
             progress=None, session=None, max_items=None, suffix='', suffix_mode=None):
    """items: [{'id': رابط الصفحة, 'type', 'name', 'title', 'desc', 'excerpt', 'pdesc', 'category', 'brand', 'need'}]
    model: نموذج ثابت لهذا المتجر. suffix/suffix_mode: اسم المتجر في العناوين (detect_title_suffix).
    يعيد (المحفوظ كاملاً، معلومات الجولة) — ويحفظ كل دفعة فور إنجازها."""
    cache = load_cache(base_dir, store_url)
    locked = store_model(cache)
    if locked and locked != model and not regenerate:
        raise ValueError(f'هذا المتجر بدأ بنموذج {locked}. أكمل به حتى لا تتفاوت الجودة، '
                         'أو اختر «إعادة توليد الكل» لتبدأ من جديد بالنموذج الجديد.')
    if regenerate:
        cache = {}
    cache['__meta__'] = {'model': model, 'suffix': suffix, 'suffix_mode': suffix_mode}
    sugg = suggestions(cache)
    todo = [it for it in items if it['id'] not in sugg]
    run_ids = []
    if max_items:
        todo = todo[:max_items]
    t_min, t_max = title_budget(suffix if suffix_mode in ('add', 'auto') else '')
    rules = rules_text(t_min, t_max)
    full = (lambda core: f"{core}{suffix}" if suffix_mode in ('add', 'auto') and core else core)
    seen_t = {v.get('title_full', v.get('title', '')).strip() for v in sugg.values()}
    seen_d = {v.get('description', '').strip() for v in sugg.values()}
    done, stopped = 0, None

    def call(prompt):
        _count_request(base_dir, model)
        return _parse(_generate(key, model, prompt, session))

    # صفحات ثابتة تحتاج عنواناً فقط: لا حاجة للنموذج أصلاً
    for it in [x for x in todo if x.get('fixed_title') and set(x.get('need', need)) == {'title'}]:
        cache[it['id']] = {'title': it['fixed_title'], 'title_full': it['fixed_title'], 'description': '',
                           'status': STATUS_OK, 'title_notes': '', 'desc_notes': '', 'model': 'ثابت'}
        run_ids.append(it['id'])
    todo = [x for x in todo if not (x.get('fixed_title') and set(x.get('need', need)) == {'title'})]
    if not todo:
        save_cache(base_dir, store_url, cache)
    for start in range(0, len(todo), BATCH):
        batch = todo[start:start + BATCH]
        try:
            out = call(rules + '\n\nبيانات الصفحات:\n' + json.dumps([_item_payload(it) for it in batch],
                                                                      ensure_ascii=False))
            retry = []
            for it in batch:
                d = out.get(str(it['id']))
                if not d:
                    retry.append((it, ['لم يُكتب']))
                    continue
                st_, tn, dn = check(it, full(d.get('title', '').strip()), d.get('description', ''),
                                    seen_t, seen_d, it.get('need', need))
                if st_ != STATUS_OK:
                    core_len = len(d.get('title', '').strip())
                    hint = []
                    if any('طول العنوان' in x for x in tn):
                        hint.append(f'الجزء الوصفي طوله {core_len}؛ المطلوب بين {t_min} و{t_max} حرفاً')
                    if any('طول الوصف' in x for x in dn):
                        hint.append(f'الوصف طوله {len(d.get("description", ""))}؛ المطلوب بين {DESC_MIN} و{DESC_MAX}')
                    retry.append((it, tn + dn + hint))
            if retry:
                out.update(call(rules + '\n\nأعد كتابة هذه الصفحات فقط، وتجنب المخالفات المذكورة لكل صفحة:\n' +
                                json.dumps([{**_item_payload(it), 'problems': notes} for it, notes in retry],
                                           ensure_ascii=False)))
        except QuotaExhausted as q:
            stopped = str(q)
            break
        for it in batch:
            d = out.get(str(it['id']))
            if not d:
                continue
            core = (d.get('title') or '').strip()
            de = (d.get('description') or '').strip()
            tf = full(core)
            if it.get('fixed_title'):
                core = tf = it['fixed_title']
            st_, tn, dn = check(it, tf, de, seen_t, seen_d, it.get('need', need))
            # العنوان المقترح: ما تكتبه في خانة المنصة. إن كانت المنصة تضيف الاسم تلقائياً، لا نكتبه
            title_out = core if (suffix_mode == 'auto' or it.get('fixed_title')) else tf
            cache[it['id']] = {'title': title_out, 'title_full': tf, 'description': de, 'status': st_,
                               'title_notes': '، '.join(tn), 'desc_notes': '، '.join(dn), 'model': model}
            seen_t.add(tf)
            seen_d.add(de)
            run_ids.append(it['id'])
        save_cache(base_dir, store_url, cache)
        done += len(batch)
        if progress:
            progress(done, len(todo))
    return cache, {'requested': len(todo), 'done': done, 'stopped': stopped, 'model': model, 'run_ids': run_ids}


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
        if r is not None and getattr(r, 'ndim', 1) > 1:
            r = r.iloc[0]
        g = (lambda c: '' if r is None or str(r.get(c, '')) == 'nan' else str(r.get(c, '') or ''))
        from audit_engine import fixed_page_title
        fixed = fixed_page_title(url, g('عنوان الميتا'), g('نوع الصفحة')) if 'title' in fields else ''
        items.append({'id': url, 'fixed_title': fixed, 'type': g('نوع الصفحة'), 'name': g('اسم منظم') or g('اسم المنتج المعروض'),
                      'title': g('عنوان الميتا'), 'desc': g('وصف الميتا'), 'excerpt': g('_excerpt'),
                      'pdesc': g('_pdesc'), 'category': g('_category'), 'brand': g('_brand'), 'need': fields})
    return items


def before_after(exports, cache, only_ids=None):
    """ملفات العمل نفسها مع أعمدة الاقتراح. only_ids: صفوف هذه الجولة فقط."""
    sugg = suggestions(cache)
    out = {}
    for key, field, label, notes_key in (('titles', 'title', 'العنوان', 'title_notes'),
                                         ('descs', 'description', 'الوصف', 'desc_notes')):
        v = exports.get(key)
        if not v:
            continue
        t = v[1].copy()
        if only_ids is not None:
            t = t[t['الرابط'].astype(str).isin(set(only_ids))]
        else:
            t = t[t['الرابط'].astype(str).isin(set(sugg))]
        g = (lambda u, f, d='': (sugg.get(str(u)) or {}).get(f, d))
        t[f'{label} المقترح'] = t['الرابط'].map(lambda u: g(u, field))
        t[f'طول {label} المقترح'] = t['الرابط'].map(
            lambda u: len(g(u, 'title_full' if field == 'title' else field)) if g(u, field) else '')
        t['حالة الاقتراح'] = t['الرابط'].map(lambda u: 'مطابق للقواعد' if not g(u, notes_key) and g(u, field)
                                              else ('يحتاج مراجعتك' if g(u, field) else 'لم يُولَّد بعد'))
        t['ملاحظات الاقتراح'] = t['الرابط'].map(lambda u: g(u, notes_key))
        out[key] = (f"قبل_وبعد_{'العناوين' if key == 'titles' else 'الأوصاف'}", t.reset_index(drop=True))
    return out


def compact_file(exports, cache, df, kind='titles', only_ids=None, with_note=False):
    """ملف مختصر لكل نوع: اسم المنتج ← الرابط ← الحالي ← الجديد.
    kind: 'titles' أو 'descs'. with_note: عمود الملاحظة (للمعاينة في الأداة فقط)."""
    from urllib.parse import unquote, urlparse
    import pandas as pd
    label = 'العنوان' if kind == 'titles' else 'الوصف'
    field = 'title' if kind == 'titles' else 'description'
    cur_col = 'عنوان الميتا' if kind == 'titles' else 'وصف الميتا'
    notes_key = 'title_notes' if kind == 'titles' else 'desc_notes'
    cols = ['اسم المنتج', 'الرابط', f'{label} الحالي', f'{label} الجديد'] + (['ملاحظة'] if with_note else [])
    sugg = suggestions(cache)
    v_ = exports.get(kind)
    if not v_:
        return pd.DataFrame(columns=cols)
    keep = set(only_ids) if only_ids is not None else set(sugg)
    rows = df.set_index('الرابط') if df is not None and 'الرابط' in df.columns else None
    out = []
    for u in dict.fromkeys(str(x) for x in v_[1]['الرابط']):
        if u not in keep or u not in sugg or not sugg[u].get(field):
            continue
        r = rows.loc[u] if rows is not None and u in rows.index else None
        if r is not None and getattr(r, 'ndim', 1) > 1:
            r = r.iloc[0]
        g = (lambda c: '' if r is None or str(r.get(c, '')) in ('nan', 'None') else str(r.get(c, '') or ''))
        name = g('اسم منظم') or g('اسم المنتج المعروض') or unquote(urlparse(u).path).strip('/').split('/')[-1] or 'الرئيسية'
        row = {'اسم المنتج': name, 'الرابط': u, f'{label} الحالي': g(cur_col), f'{label} الجديد': sugg[u][field]}
        if with_note:
            row['ملاحظة'] = sugg[u].get(notes_key, '')
        out.append(row)
    return pd.DataFrame(out, columns=cols)
