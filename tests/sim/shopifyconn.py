import sys, json, tempfile
sys.path.insert(0, '/home/claude/work')
import zid_api as z
class R:
    def __init__(self, c, d): self.status_code, self._d = c, d
    def json(self): return self._d
class Shop:
    def post(self, url, json=None, headers=None, timeout=None):
        assert url == 'https://anas-dev.myshopify.com/admin/api/2026-10/graphql.json' and headers['X-Shopify-Access-Token'] == 'shpat_SECRET'
        return R(200, {'data': {'shop': {'name': 'Dev Store', 'primaryDomain': {'url': 'https://dev.example.com'}},
                                'products': {'nodes': [{'id': 'gid://shopify/Product/1', 'title': 'Organic Cap', 'handle': 'organic-cap',
                                                        'seo': {'title': None, 'description': None}, 'media': {'nodes': [{'alt': ''}]}}]}}})
b = tempfile.mkdtemp()
(z._tokens_dir(b) / 'shopify_anas-dev.myshopify.com.json').write_text(json.dumps({'key': 'shopify_anas-dev.myshopify.com', 'platform': 'shopify',
    'store': {'id': 'anas-dev.myshopify.com', 'name': '', 'url': 'https://anas-dev.myshopify.com'}, 'tokens': {'access_token': 'shpat_SECRET', 'obtained': 'x'}}))
r = z.test_connection(b, 'shopify_anas-dev.myshopify.com', Shop())
print('shopify ok:', r['store']['name'], r['products'][0]['name'], '| fields:', list(r['product_fields']), '| leak:', 'shpat_SECRET' in json.dumps(r))
print('listed as:', z.local_stores(b)[0]['platform'])
