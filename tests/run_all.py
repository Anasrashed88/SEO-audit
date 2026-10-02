import subprocess, shutil, re, sys
W, S = '/home/claude/work', '/tmp/sim'
CASES = [
 ('زد مثل KS: 5 خرائط (منها مجلدات فرعية) وصفحات تعريفية تحوّل', 'python3 zidmaps.py', [r'sitemap files: 5', r'الأقسام: فُحص 1 — في الخريطة 1 \|', r'المقالات: فُحص 3 — في الخريطة 3 \|', r'والأداة فحصت 30 ✓']),
 ('مطابقة الأرقام: نقص منتجين يُنبَّه عليه', 'python3 recon.py 22', [r'^warn', r'أقل بـ 2']),
 ('مطابقة الأرقام: تطابق تام', 'python3 recon.py 20', [r'^pass', r'فحصت 20 ✓']),
 ('زد /ar-sa/: كل صفحة مرة واحدة', 'python3 arsa.py', [r'products=20 \| same title=0 \| same title\+desc=0']),
 ('التحويل للرئيسية: كشف التقييد ثم الاستكمال', 'python3 homered.py', [r'suspicious=True', r'نجح فحص 42', r'resume: products=60 requests=35']),
 ('مدونة سلة بصفحات مرقمة', 'python3 blog.py', [r'blog articles: 13']),
 ('التطبيق والتقارير', 'python3 apptest.py', [r"app exceptions: \[\]", r'PDFs ok']),
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
