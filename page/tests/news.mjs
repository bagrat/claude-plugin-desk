// The News tab (rule 14): first and only with news, the page opens on it, Seen deletes the row
// (or sets done where delete is refused) and sends no comment. Run: node page/tests/news.mjs [shots-dir]
import { browser, open as openPage, ok, done } from './harness.mjs';
const out = process.argv[2] || '/tmp';
const news = {
  'release-12': { state: 'news', title: 'Version 1.2 is out', context: 'Published; every keeper picks it up before its next message.', since: '2026-10-26T08:00:00Z', updatedAt: '2026-10-26T09:10:00Z',
    links: [{ label: 'Release notes', url: 'https://example.com/releases/1.2' }] },
  'search-box': { state: 'news', title: 'Merged: the search box', context: 'Live, with the shortcut you picked.', since: '2026-10-25T10:00:00Z', updatedAt: '2026-10-26T07:30:00Z',
    details: [{ title: 'Recap', text: '- Three boards, two rounds\n- The copy you picked' }] },
};
const rest = {
  'ship-date': { state: 'waiting', kind: 'decide', rank: 1, title: 'Pick the ship date', context: 'The release waits on these.', ask: 'Which day?', recommend: 'Tuesday.', updatedAt: '2026-10-25T10:00:00Z',
    dependsOn: [{ item: 'the search box', card: 'search-box', state: 'done' }] },
  'docs-pass': { state: 'working', kind: 'do', title: 'A pass over the docs', sessions: [{ label: 's', url: 'https://claude.ai/code/session_01A' }], workingSince: '2026-10-25T09:00:00Z', updatedAt: '2026-10-25T10:00:00Z' },
};
const b = await browser();
const open = (o) => openPage(b, { ...o, db: { tasks: o.rows } });
const newsTab = (s) => s.p.$eval('#tab-news', (n) => !n.hidden);

for (const scheme of ['dark', 'light']) {
  const s = await open({ rows: { ...news, ...rest }, scheme });
  ok(await newsTab(s), `${scheme}: News tab shown`);
  ok(await s.p.$eval('.tabs', (n) => n.firstElementChild.id) === 'tab-news', `${scheme}: News tab first`);
  ok(await s.tab() === 'news', `${scheme}: opens on News`);
  ok(await s.p.textContent('#n-news') === '2', `${scheme}: count 2`);
  ok(JSON.stringify(await s.p.$$eval('#l-news .ncard .t-title', (l) => l.map((x) => x.textContent))) === JSON.stringify(['Version 1.2 is out', 'Merged: the search box']), `${scheme}: newest first`);
  ok(await s.p.$$eval('#p-news .dock, #p-news .quick', (l) => l.length) === 0, `${scheme}: no answer buttons on news`);
  await s.p.screenshot({ path: `${out}/news-${scheme}.png` });
  if (scheme === 'dark') {
    await s.p.tap('#n-release-12 .btn.seen'); await s.p.waitForTimeout(300);
    ok(JSON.stringify(await s.log()) === JSON.stringify([['delete', 'tasks', 'release-12']]), 'Seen deletes the row, no comment');
    ok(await s.p.textContent('#n-news') === '1', 'count 1 after Seen');
    ok(/Cleared/.test(await s.p.textContent('.toast')), 'toast says Cleared, with Undo');
    await s.p.tap('.toast button'); await s.p.waitForTimeout(300);
    ok(await s.p.textContent('#n-news') === '2' && (await s.log()).at(-1)[0] === 'set', 'Undo puts it back');
    await s.p.tap('#n-release-12 .btn.seen'); await s.p.waitForTimeout(300);
    await s.p.tap('#n-search-box .btn.seen'); await s.p.waitForTimeout(400);
    ok(!(await newsTab(s)) && await s.tab() === 'waiting', 'last Seen: tab gone, on Waiting');
    ok(!(await s.log()).some((e) => e[0] === 'comment'), 'no comment sent at all');
  }
  ok(s.errs.length === 0, `${scheme}: no errors ${s.errs.join(' ')}`);
  await s.ctx.close();
}
{ const s = await open({ rows: rest });
  ok(!(await newsTab(s)) && await s.tab() === 'waiting', 'no news: tab hidden, opens on Waiting');
  ok(await s.p.textContent('.stage > .card .t-title') === 'Pick the ship date', 'no news: the deck shows');
  ok(s.errs.length === 0, 'no errors'); await s.ctx.close(); }
for (const [hash, tab, what] of [['#waiting', 'waiting', '#waiting with news opens Waiting'], ['#working', 'working', '#working opens In progress'], ['#t-search-box', 'news', '#t-<news id> opens News']]) {
  const s = await open({ rows: { ...news, ...rest }, hash }); ok(await s.tab() === tab, what); await s.ctx.close();
}
{ const s = await open({ rows: rest, hash: '#news' }); ok(await s.tab() === 'waiting', '#news with no news falls back to Waiting'); await s.ctx.close(); }
{ const s = await open({ rows: { ...news, ...rest }, hash: '#waiting' });
  await s.p.tap('.stage > .card .deps button'); await s.p.waitForTimeout(200);
  ok(await s.tab() === 'news', 'a linked item opens its news card'); await s.ctx.close(); }
{ const s = await open({ rows: { ...news, ...rest }, canDelete: false });
  await s.p.tap('#n-search-box .btn.seen'); await s.p.waitForTimeout(300);
  const log = await s.log();
  ok(log[0][0] === 'delete' && log[1][0] === 'update' && log[1][3].state === 'done' && log.length === 2, 'no delete: Seen sets done');
  ok(await s.p.textContent('#n-news') === '1', 'and it leaves the tab'); await s.ctx.close(); }
await done(b);
