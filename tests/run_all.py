import subprocess, shutil, re, sys
W, S = '/home/claude/work', '/tmp/sim'
CASES = [
 ('زد مثل KS: 5 خرائط (منها مجلدات فرعية) وصفحات تعريفية تحوّل', 'python3 zidmaps.py', [r'sitemap files: 5', r'الأقسام: فُحص 1 — في الخريطة 1 \|', r'المقالات: فُحص 3 — في الخريطة 3 \|', r'والأداة فحصت 30 ✓']),
 ('مطابقة الأرقام: نقص منتجين يُنبَّه عليه', 'python3 recon.py 22', [r'^warn', r'أقل بـ 2']),
 ('مطابقة الأرقام: تطابق تام', 'python3 recon.py 20', [r'^pass', r'فحصت 20 ✓']),
 ('زد /ar-sa/: كل صفحة مرة واحدة', 'python3 arsa.py', [r'products=20 \| same title=0 \| same title\+desc=0']),
 ('التحويل للرئيسية: كشف التقييد ثم الاستكمال', 'python3 homered.py', [r'suspicious=True', r'نجح فحص 42', r'resume: products=60 requests=35']),
 ('مدونة سلة بصفحات مرقمة', 'python3 blog.py', [r'blog articles: 13']),
 ('KS: الرابط العام يذهب لقسم أو مقال لا لمنتج واحد', 'python3 kslinks.py', [r'/غرف-اطفال-صغيرة → /categories/53202', r'/مكتب-اطفال → /categories/51977', r'/غرف-نوم-اطفال → /blogs/غرف-نوم-اطفال عالية', r'collection → /products/modern-living-room-furniture-12 عالية']),
 ('زد: صفحات المراجعات /products/<رقم>/reviews ليست منتجات', 'python3 reviews.py', [r'products: 12 \| review pages: 0', r'والأداة فحصت 12 ✓']),
 ('اختيار المنصة يدوياً من الواجهة', 'python3 hint.py', [r'hint=None -> platform=zid products=30', r'hint=shopify -> platform=shopify products=30']),
 ('التطبيق والتقارير', 'python3 apptest.py', [r"app exceptions: \[\]", r'PDFs ok']),
 ('تبويب المراحل والفواتير', 'python3 phasetab.py', [r'before tajhiz downloads: 0', r'after tajhiz downloads: 4 \| exceptions: \[\]', r'whatsapp messages: 2', r'task files cover all rows: True \| same columns as export: True']),
 ('الذكاء الاصطناعي: اسم المتجر، الطول، النموذج الثابت، النسخ والسعر، الحصة', 'python3 aitest.py', [r"zid suffix: \(' \| مدهال عود', 'add'\) \| salla suffix: \(' \| متجر العناية', 'auto'\)", r'\(38, 48\)', r"models \(no lite/preview\): \['gemini-3.8-flash', 'gemini-3.5-flash'\]", r'p3 title: .* \| len: (5\d|60) \| notes: -', r'فيه سعر أو عرض', r'p5 copied desc fixed: ok', r'title notes never in desc notes: True', r'model lock enforced: True', r'second run requested: 0', r'quota stop: True \| saved: 20', r'continued: requested 10 \| total 30', r'auto mode: suggestion has no suffix: True \| measured with it: True', r'brief 503 recovered: True', r'persistent 503 stops gracefully: True \| key not in message: True', r'legacy rewritten: True', r'fixed title kept exactly: سياسة الخصوصية \| desc written by AI: True', r'title-only fixed page needs no request: True', r'small edit counts as copy: True']),
 ('تبويب الذكاء الاصطناعي في التطبيق', 'python3 aitab.py', [r'no key -> key input shown: True \| exceptions: \[\]', r'locked model shown: True \| exceptions: \[\]', r'titles preview rows: \[8\]', r'descs preview rows: \[8\] \| exceptions: \[\]', r'regen shows model list on locked store: True', r"titles file columns: \['اسم المنتج', 'الرابط', 'العنوان الحالي', 'العنوان الجديد'\]", r'العناوين الجديدة', r'الأوصاف الجديدة', r'عينة العميل', r'images view exceptions: \[\]', r'links view exceptions: \[\]']),
 ('النصوص البديلة للصور: دفعات بالصور، تحقق، الحفظ', 'python3 alttest.py', [r"home named: \['الصفحة الرئيسية'\]", r'requests: 2 \| images sent: 9 \| generated: 9', r'يبدأ بكلمة «صورة»', r'مكرر مع صورة أخرى في نفس الصفحة', r'تعذّر تحميل الصورة', r"alt file columns: \['اسم المنتج', 'الرابط', 'رابط الصورة', 'النص البديل الحالي', 'النص البديل الجديد'\]", r'second run requests: 0']),
 ('ربط زد: الجسر، كلمة السر، تعرف المتجر، بلا كشف مفاتيح، الإلغاء', 'python3 zidtest.py', [r'wrong key rejected: True', r'pulled: 1 \| listing has no tokens: True', r'store identified: متجر أنس التجريبي 3257423', r'no secrets in test result: True', r'after disconnect local stores: 0']),
 ('جسر Apps Script: تحويل Google يُفتح بطلب قراءة', 'python3 bridgehop.py', [r'pulled through Google redirect: 1']),
 ('سلة: الجسر يستقبل المفاتيح بكلمة سر الرابط ويحذفها عند الإزالة', 'node bridge_test.js', [r'wrong key rejected: true \| saved: false', r'right key accepted: true', r'tool sees platform: salla', r'uninstall removed keys: true', r'zid tool pickup still guarded: true']),
 ('سلة: اختبار الاتصال بمفتاح واحد وبلا كشف مفاتيح', 'python3 sallatest.py', [r'salla ok: متجر سلة التجريبي 1 \| leak: False']),
 ('شوبيفاي: لا ملفات ولا روابط وهمية، المنتجات = products.json، صورة واحدة لكل حجم، الوصف الكامل', 'python3 shopify.py', [r'platform: shopify \| failed pages: 0', r'hidden product discovered from products.json: True', r'المتجر يعلن 7 منتجاً، والأداة فحصت 7 ✓', r'unique missing-alt images: 14', r'descriptions from products.json: 7 of 7']),
 ('الدولار ونسخة المنصات في التطبيق', 'python3 usdtab.py', [r"exceptions: \[\]", r"usd total metric: \['\$264'\]", r'marketplace hides contact: True']),
 ('أكثر من 1,500 وحدة عمل: تسعير مفرد تلقائياً', 'python3 bigtest.py', [r'over 1500 → itemised notice: True \| package price box hidden: True \| exceptions: \[\]', r"60 units → package price box: True \['990'\]"]),
 ('Claude: الترويسات، بلا temperature، القواعد مخزنة، الصور، الرصيد والانشغال والمفتاح', 'python3 claudetest.py', [r'claude text ok: 3 \| rules cached in system: True \| fenced JSON parsed: True', r'claude images ok: 2 \| image blocks: 2 \| source: base64', r'credit → stops gracefully: رصيد حساب Claude', r'busy → stops gracefully: خوادم Claude مشغولة', r'bad key message: مفتاح Claude غير صحيح']),
 ('Claude في التبويب: مفتاح وحده يكفي، وSonnet 5.5 أولاً', 'python3 claudetab.py', [r"claude only → model list: \['claude-sonnet-5-5'\] \| selected: claude-sonnet-5-5 \| exceptions: \[\]", r'gemini key box still offered: True']),
 ('شوبيفاي: الجسر يتحقق من التوقيع ويعرف التطبيق ويحفظ المتجر، وزد سليم', 'node bridge_shopify.js', [r'install → authorize link with our client id: true', r'forged signature rejected: true', r'callback → connected: true \| saved: true \| name: Dev Store', r'tool sees: shopify:Dev Store', r'zid flow untouched: true']),
 ('شوبيفاي: اختبار الاتصال وعرض المنصة في الواجهة', 'python3 shopifyconn.py && python3 shopifytab.py', [r'shopify ok: Dev Store Organic Cap .* leak: False', r'connect tab card: .*شوبيفاي', r"linked page platform: \[\('المنصة', 'شوبيفاي'\)\]"]),
 ('قفل التقرير الناقص', 'python3 gate.py', [r'locked before confirm: True \| unlocked after: True']),
]
fails = 0
for name, cmd, exp in CASES:
    shutil.rmtree(f'{W}/scan_cache', ignore_errors=True)
    out = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=S, timeout=900).stdout
    ok = all(re.search(p, out, re.M) for p in exp); fails += not ok
    print(('✅' if ok else '❌'), name); ok or print('   ', out[-500:])
shutil.rmtree(f'{W}/scan_cache', ignore_errors=True)
print(f'\n{len(CASES) - fails} / {len(CASES)} ناجحة'); sys.exit(1 if fails else 0)
