const fs = require('fs');
const props = { CLIENT_ID: '8033', CLIENT_SECRET: 'x', PICKUP_KEY: 'PICKUP-KEY-LONG-ENOUGH', SALLA_HOOK_KEY: 'SALLA-HOOK-KEY-LONG-1234' };
global.PropertiesService = { getScriptProperties: () => ({
  getProperty: k => props[k] || null, setProperty: (k, v) => { props[k] = v; }, deleteProperty: k => { delete props[k]; },
  getProperties: () => Object.assign({}, props) }) };
global.UrlFetchApp = { fetch: (url, o) => ({ getResponseCode: () => 200,
  getContentText: () => JSON.stringify({ data: { merchant: { id: 777, name: 'متجر سلة التجريبي', domain: 'https://demo.salla.sa' } } }) }) };
global.ContentService = { MimeType: { JSON: 'json' }, createTextOutput: t => ({ setMimeType: () => JSON.parse(t) }) };
global.HtmlService = { createHtmlOutput: h => ({ setTitle: () => h }) };
global.ScriptApp = { getService: () => ({ getUrl: () => 'https://script.google.com/x/exec' }) };
global.CacheService = { getScriptCache: () => ({ get: () => null, put: () => {}, remove: () => {} }) };
global.Utilities = { getUuid: () => 'uuid-1' };
eval(fs.readFileSync('/mnt/user-data/outputs/zid_bridge.gs', 'utf8') + '\nglobal.doPost = doPost;');
const auth = { event: 'app.store.authorize', merchant: 777, data: { access_token: 'AT', refresh_token: 'RT', expires: 1999999999, scope: 'products.read_write', token_type: 'bearer' } };
const post = (k, body) => doPost({ parameter: k ? { k } : {}, postData: { contents: JSON.stringify(body) } });
console.log('wrong key rejected:', post('WRONG', auth).error === 'unauthorized', '| saved:', !!props['salla_777']);
console.log('right key accepted:', post('SALLA-HOOK-KEY-LONG-1234', auth).ok, '| saved name:', JSON.parse(props['salla_777']).store.name);
const list = post(null, { key: 'PICKUP-KEY-LONG-ENOUGH', action: 'list' });
console.log('tool sees platform:', list.stores.map(s => s.platform + ':' + s.store.name).join(','));
post('SALLA-HOOK-KEY-LONG-1234', { event: 'app.uninstalled', merchant: 777 });
console.log('uninstall removed keys:', !props['salla_777']);
console.log('zid tool pickup still guarded:', post(null, { key: 'WRONG', action: 'list' }).error === 'unauthorized');
