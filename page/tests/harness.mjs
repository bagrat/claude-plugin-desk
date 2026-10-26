// Shared by the page's tests: the template filled in for a test Desk, served at https://x.test/
// with a stand-in for the viewer (db by collection, user, comments, assets). Chromium is
// /opt/pw-browsers/chromium when it exists (cloud sessions), else Playwright's own.
import { createRequire } from 'module'; import fs from 'fs';
const { chromium } = createRequire(import.meta.url)('playwright');
const tpl = fs.readFileSync(new URL('../desk.html', import.meta.url), 'utf8');
export const render = ({ title = 'Test Desk', theme = 'frost', keeper = '', icon = {} } = {}) =>
  tpl.replaceAll('{{DESK_TITLE}}', title).replaceAll('{{DESK_THEME}}', theme).replaceAll('{{DESK_KEEPER}}', keeper).replaceAll('{{DESK_ICON}}', JSON.stringify(icon));
const exe = fs.existsSync('/opt/pw-browsers/chromium') ? '/opt/pw-browsers/chromium' : undefined;
export const browser = () => chromium.launch(exe ? { executablePath: exe } : {});
let fails = 0;
export const ok = (cond, what) => { console.log((cond ? 'ok   ' : 'FAIL ') + what); if (!cond) fails++; };
export const done = async (b) => { await b.close(); console.log(fails ? `${fails} failed` : 'all passed'); process.exit(fails ? 1 : 0); };

// db: {collection: {id: row}}; the page's writes land in window.__log and in the store.
export async function open(b, { db = {}, scheme = 'dark', hash = '', canDelete = true, width = 402, page = {}, owner = true, assets = true } = {}) {
  const ctx = await b.newContext({ viewport: { width, height: 874 }, deviceScaleFactor: 2, colorScheme: scheme, hasTouch: true, isMobile: width < 500 });
  const p = await ctx.newPage();
  const errs = []; p.on('pageerror', (e) => errs.push(String(e)));
  await p.addInitScript(({ db, canDelete, owner, assets }) => {
    const live = JSON.parse(JSON.stringify(db)); window.__log = []; const subs = {}; const dsubs = {};
    const col = (c) => (live[c] ||= {});
    const snap = (c) => ({ docs: Object.entries(col(c)).map(([id, d]) => ({ id, exists: true, data: () => JSON.parse(JSON.stringify(d)) })) });
    const dsnap = (c, id) => ({ id, exists: id in col(c), data: () => col(c)[id] && JSON.parse(JSON.stringify(col(c)[id])) });
    const fire = (c) => setTimeout(() => { (subs[c] || []).forEach((f) => f(snap(c))); Object.entries(dsubs).forEach(([k, fs]) => { const [cc, id] = k.split('\n'); if (cc === c) fs.forEach((f) => f(dsnap(c, id))); }); }, 30);
    window.__put = (c, id, d) => { if (d == null) delete col(c)[id]; else col(c)[id] = d; fire(c); };
    const doc = (c, id) => ({
      update: async (p) => { window.__log.push(['update', c, id, p]); Object.assign(col(c)[id], p); fire(c); },
      delete: async () => { window.__log.push(['delete', c, id]); if (!canDelete) throw Object.assign(new Error('no'), { code: 'not_granted' }); delete col(c)[id]; fire(c); },
      set: async (d) => { window.__log.push(['set', c, id, d]); col(c)[id] = d; fire(c); },
      onSnapshot: (f) => { ((dsubs[c + '\n' + id]) ||= []).push(f); setTimeout(() => f(dsnap(c, id)), 10); return () => {}; },
    });
    const dbo = { collection: (c) => ({ onSnapshot: (f) => { (subs[c] ||= []).push(f); setTimeout(() => f(snap(c)), 10); return () => {}; }, doc: (id) => doc(c, id) }) };
    const cm = { anchorFor: async () => ({}), canSendToClaude: async () => 'available', sendToClaude: async (x) => { window.__log.push(['comment', x.text]); } };
    const as = { upload: async (blob) => { window.__log.push(['upload', blob.name]); return { id: 'f'.repeat(32), url: '/_blob/' + 'f'.repeat(32) }; } };
    window.claude = { use: async (n) => n === 'db' ? dbo : n === 'user' ? { isOwner: () => owner } : n === 'comments' ? cm : n === 'assets' && assets ? as : null };
  }, { db, canDelete, owner, assets });
  const html = render(page);
  await p.route('https://x.test/', (r) => r.fulfill({ contentType: 'text/html', body: '<!doctype html><html><head><meta charset=utf8><meta name=viewport content="width=device-width,initial-scale=1,viewport-fit=cover"></head><body>' + html + '</body></html>' }));
  await p.route('https://x.test/_blob/*', (r) => r.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="30" height="30"><rect width="30" height="30" fill="#c33"/></svg>' }));
  await p.goto('https://x.test/' + hash); await p.waitForTimeout(500);
  return { p, ctx, errs, tab: () => p.$eval('[role=tab][aria-selected=true]', (n) => n.dataset.tab), log: () => p.evaluate(() => window.__log) };
}
