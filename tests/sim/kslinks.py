import sys; sys.path.insert(0, '/home/claude/work')
import pandas as pd, audit_engine as e
K = 'https://furniture-ks.com'
live = [('/categories/53202/اثاث-الاطفال', 'اثاث الاطفال'), ('/categories/51977/مكتب', 'مكتب'), ('/blogs/غرف-نوم-اطفال', 'غرف نوم اطفال'),
        ('/products/multi-functional-bed-for-children-with-desk', 'سرير اطفال متعدد الوظائف مع مكتب'),
        ('/products/إطار-تسلق-زحليقة-أطفال-للشقق-الصغيرة', 'إطار تسلق أطفال للشقق الصغيرة'), ('/products/modern-living-room-furniture-12', 'Modern Living Room Furniture 12')]
T = lambda u: e.decisive_type(K + u) or e._detect_type_by_url(K + u, K)
rows = [{'الرابط': K + u, 'نوع الصفحة': T(u), 'متاحة': True, 'اسم المنتج المعروض': n, 'كود الاستجابة': 200, 'سلسلة التحويل': '', 'الوجهة النهائية': '', 'قابلة للأرشفة': True} for u, n in live]
rows += [{'الرابط': K + f'/products/sofa-{i}', 'نوع الصفحة': 'product', 'متاحة': True, 'اسم المنتج المعروض': f'كنبة مودرن {i}', 'كود الاستجابة': 200, 'سلسلة التحويل': '', 'الوجهة النهائية': '', 'قابلة للأرشفة': True} for i in range(30)]
brk = ['/غرف-اطفال-صغيرة', '/مكتب-اطفال', '/غرف-نوم-اطفال', '/products/modern-living-room-furniture-collection']
rows += [{'الرابط': K + u, 'نوع الصفحة': 'broken', 'نوع الرابط': '', 'متاحة': False, 'اسم المنتج المعروض': '', 'كود الاستجابة': 'خطأ 404', 'سلسلة التحويل': '', 'الوجهة النهائية': '', 'قابلة للأرشفة': True} for u in brk]
df = pd.DataFrame(rows); sg = e.suggest_alternatives(df)
for i in df[e.broken_no_redirect_mask(df)].index:
    dst, conf = sg.get(i, ('—', ''))
    print(f"{e.unquote(df.at[i, 'الرابط']).split('.com')[1]} → {e.unquote(dst).split('.com')[-1]} {conf}")
