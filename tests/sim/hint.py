from simlib import *
exec(open('/tmp/sim/zidmaps.py').read().split("res = scan(fake, B)")[0].split("from simlib import *")[1])
for hint in (None, 'shopify'):
    r = scan(fake, B, platform_hint=hint)
    print(f"hint={hint} -> platform={r['summary']['platform']} products={r['summary']['products']}")
