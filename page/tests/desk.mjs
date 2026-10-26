// The Desk's own parts: its look (theme and icon, live from settings/look), the Inbox strip and
// the note tab, the keeper link. Run: node page/tests/desk.mjs [shots-dir]
import { browser, open, ok, done } from './harness.mjs';
import fs from 'fs';
const out = process.argv[2] || '/tmp';
const tasks = { 'ship-date': { state: 'waiting', kind: 'decide', rank: 1, title: 'Pick the ship date', context: 'One line.', ask: 'Which day?', recommend: 'Tuesday.', updatedAt: '2026-10-25T10:00:00Z' } };
const accent = (p) => p.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--accent').trim());
const bg = (p) => p.evaluate(() => getComputedStyle(document.body).backgroundColor);
const b = await browser();

// No look row: the page's own, a letter icon, Frost.
{ const s = await open(b, { db: { tasks }, page: { title: 'Work Desk' } });
  ok(await s.p.title() === 'Work Desk', 'title is the Desk\'s');
  ok(await s.p.$eval('#logo', (n) => n.className + '|' + n.textContent) === 'logo letter|W', 'default icon: its first letter');
  ok(await s.p.evaluate(() => document.documentElement.dataset.deskTheme) === 'frost' && await accent(s.p) === '#88c0d0', 'default theme: Frost (dark accent)');
  ok(!(await s.p.$('#strip:not([hidden])')), 'no notes: no strip');
  ok(await s.p.$eval('#tab-note', (n) => !n.hidden), 'owner: the note tab shows');
  ok(await s.p.$eval('.tabs', (n) => n.lastElementChild.id) === 'tab-note', 'the note tab is last');
  ok(await s.p.$eval('#note-box', (n) => n.closest('[role=tabpanel]')?.id) === 'p-note', 'the note box is in its own tab');
  ok(!(await s.p.isVisible('#note-box')), 'no note box above the cards');
  await s.p.click('#tab-note');
  ok(await s.p.isVisible('#note-text') && await s.p.isVisible('#note-send') && !(await s.p.isVisible('#p-waiting')), 'the note tab shows the box, not the cards');
  await s.p.click('#tab-waiting');
  await s.p.click('#t-ship-date .more > summary');
  ok(!(await s.p.$('a.btn:has-text("Open the keeper")')), 'no keeper: no keeper link');
  ok(s.errs.length === 0, 'no errors ' + s.errs.join(' ')); await s.ctx.close(); }

// What the page was made with, then the look row, live.
{ const s = await open(b, { db: { tasks }, page: { theme: 'plum', icon: { emoji: '🗂️' }, keeper: 'https://claude.ai/code/session_01K' } });
  ok(await s.p.evaluate(() => document.documentElement.dataset.deskTheme) === 'plum', 'made-with theme applies');
  ok(await s.p.$eval('#logo', (n) => n.className + '|' + n.textContent) === 'logo emoji|🗂️', 'made-with emoji icon');
  const before = await bg(s.p);
  await s.p.evaluate(() => window.__put('settings', 'look', { theme: 'lagoon', icon: { image: 'a'.repeat(32) } })); await s.p.waitForTimeout(150);
  ok(await s.p.evaluate(() => document.documentElement.dataset.deskTheme) === 'lagoon' && await accent(s.p) === '#2AA198', 'the look row changes the theme live');
  ok(await bg(s.p) !== before, 'and the ground with it');
  ok(await s.p.$eval('#logo img', (n) => n.getAttribute('src')) === '/_blob/' + 'a'.repeat(32), 'image icon from the page\'s assets');
  await s.p.click('#t-ship-date .more > summary');
  ok(await s.p.$eval('a.btn:has-text("Open the keeper")', (n) => n.href) === 'https://claude.ai/code/session_01K', 'keeper link');
  ok(s.errs.length === 0, 'no errors ' + s.errs.join(' ')); await s.ctx.close(); }

// Every theme, both schemes: applies without errors; screenshots to compare.
const names = await (async () => { const s = await open(b, { db: { tasks } }); const n = await s.p.evaluate(() => Object.keys(THEMES)); await s.ctx.close(); return n; })();
ok(names.length === 15, '15 themes');
for (const scheme of ['dark', 'light']) {
  for (const t of names) {
    const s = await open(b, { db: { tasks, inbox: { 'n-1': { text: 'The dashes hide behind the header', from: 'page', at: '2026-10-26T09:00:00Z' } }, settings: { look: { theme: t, icon: { emoji: '💼' } } } }, scheme });
    ok(await s.p.evaluate(() => document.documentElement.dataset.deskTheme) === t && s.errs.length === 0, `${scheme} ${t}`);
    await s.p.screenshot({ path: `${out}/theme-${t}-${scheme}.png` });
    await s.ctx.close();
  }
}

// The Inbox: the strip lists notes; a note from the box saves, wakes the keeper, and shows.
{ const s = await open(b, { db: { tasks, inbox: { 'n-2': { text: 'Second', from: 'session_01X', at: '2026-10-26T09:05:00Z' }, 'n-1': { text: 'First', from: 'page', at: '2026-10-26T09:00:00Z', images: [{ id: 'b'.repeat(32) }] } } } });
  ok(await s.p.textContent('#strip-n') === '2 notes being sorted', 'strip: count');
  ok(JSON.stringify(await s.p.$$eval('#strip-l li > div', (l) => l.map((x) => x.textContent))) === '["First","Second"]', 'strip: oldest first');
  ok(/from this page · 1 image/.test(await s.p.textContent('#strip-l li >> nth=0')), 'strip: where from, and images');
  ok(await s.p.$eval('#strip', (n) => !n.closest('[role=tabpanel]')) && await s.p.isVisible('#strip'), 'the strip stays above the cards');
  await s.p.click('#tab-note');
  await s.p.fill('#note-text', 'Make the swipe less eager');
  await s.p.setInputFiles('#note-pick', { name: 'shot.png', mimeType: 'image/png', buffer: fs.readFileSync(new URL('../../README.md', import.meta.url)) }).catch(() => {});
  await s.p.click('#note-send'); await s.p.waitForTimeout(300);
  const log = await s.log();
  const set = log.find((e) => e[0] === 'set' && e[1] === 'inbox');
  ok(set && set[3].text === 'Make the swipe less eager' && set[3].from === 'page' && /^n-\d{14}-[0-9a-f]{4}$/.test(set[2]), 'the note saves to the inbox');
  ok(set && set[3].images?.[0]?.id === 'f'.repeat(32) && log.some((e) => e[0] === 'upload'), 'its screenshot uploads with it');
  ok(log.some((e) => e[0] === 'comment' && e[1].startsWith('[Desk note] Make the swipe less eager')), 'a comment wakes the keeper');
  ok(/Note sent to the keeper/.test(await s.p.textContent('body')), 'it says the note was sent');
  ok(await s.p.textContent('#strip-n') === '3 notes being sorted' && await s.p.inputValue('#note-text') === '', 'the strip shows it; the box clears');
  await s.p.screenshot({ path: `${out}/inbox.png` });
  await s.p.evaluate(() => { window.__put('inbox', 'n-1', null); window.__put('inbox', 'n-2', null); }); await s.p.waitForTimeout(150);
  ok(await s.p.textContent('#strip-n') === '1 note being sorted', 'sorted notes leave the strip');
  ok(s.errs.length === 0, 'no errors ' + s.errs.join(' ')); await s.ctx.close(); }

// Not the owner: no note tab, and #note doesn't open it; no assets: no screenshot button.
{ const s = await open(b, { db: { tasks }, owner: false, hash: '#note' });
  ok(await s.p.$eval('#tab-note', (n) => n.hidden) && !(await s.p.isVisible('#note-box')), 'not the owner: no note tab'); await s.ctx.close(); }
{ const s = await open(b, { db: { tasks }, hash: '#note' });
  ok(await s.p.isVisible('#note-text'), 'owner: #note opens the note tab'); await s.ctx.close(); }
{ const s = await open(b, { db: { tasks }, assets: false });
  ok(await s.p.$eval('#note-pick-l', (n) => n.hidden), 'no assets: no screenshot button'); await s.ctx.close(); }
// A review held until the owner asks: under Later, marked, out of the deck and the count.
{ const held = { ...tasks, 'big-review': { state: 'waiting', kind: 'review', rank: 1, title: 'Review the new layout', ask: 'Does it read well?', recommend: 'Yes.', heldAt: '2026-10-20T10:00:00Z' } };
  const s = await open(b, { db: { tasks: held } });
  ok(await s.p.textContent('.stage > .card .t-title') === 'Pick the ship date', 'held: not in the deck');
  ok(await s.p.textContent('#n-waiting') === '1', 'held: not counted');
  ok(await s.p.textContent('.later-n') === '1', 'held: under Later');
  await s.p.click('.later-n');
  await s.p.waitForTimeout(100);
  await s.p.click('.dash >> nth=1');
  await s.p.waitForTimeout(400);
  ok(/review when you ask/i.test(await s.p.textContent('.stage > .card .head')), 'held: marked "review when you ask"');
  await s.p.click('#tab-all');
  ok(/review when you ask/i.test(await s.p.textContent('#a-big-review')), 'held: marked in All too');
  ok(s.errs.length === 0, 'no errors ' + s.errs.join(' ')); await s.ctx.close(); }
await done(b);
