// A sent answer or note moves its card at once: the box that had focus no longer holds the card
// back (#40's hold is for typing, not for a box already sent). A failed save keeps the box, the
// draft and focus as they are. By click, by a tap that leaves focus in the box, and by Ctrl-Enter. Run: node page/tests/sent.mjs
import { browser, open, ok, done } from './harness.mjs';
const rows = {
  'ship-date': { state: 'waiting', kind: 'decide', rank: 1, title: 'Pick the ship date', ask: 'Which day?', updatedAt: '2026-10-25T10:00:00Z' },
  'name-it': { state: 'waiting', kind: 'decide', rank: 2, title: 'Name the tool', ask: 'Which name?', updatedAt: '2026-10-25T09:00:00Z' },
  'release-12': { state: 'news', title: 'Version 1.2 is out', since: '2026-10-26T09:00:00Z', updatedAt: '2026-10-26T09:00:00Z' },
  'search-box': { state: 'news', title: 'Merged: the search box', since: '2026-10-25T10:00:00Z', updatedAt: '2026-10-25T10:00:00Z' },
};
const b = await browser();
const ids = (s, sel) => s.p.$$eval(sel, (l) => l.map((n) => n.id).join());
const send = async (s, box, how) => {
  if (how === 'click') await s.p.click(box + ' button');
  // A tap on a phone leaves focus in the box (the button doesn't take it), as Ctrl-Enter does.
  else if (how === 'tap') { await s.p.focus(box + ' textarea'); await s.p.$eval(box + ' button', (n) => n.click()); }
  else { await s.p.focus(box + ' textarea'); await s.p.keyboard.press('Control+Enter'); }
  await s.p.waitForTimeout(150);
};

for (const how of ['click', 'tap', 'key']) {
  // A Waiting card's answer box.
  { const s = await open(b, { db: { tasks: rows }, hash: '#waiting' });
    await s.p.click('.stage > .card .more > summary');
    await s.p.click('.stage > .card .answer textarea'); await s.p.keyboard.type('Tuesday');
    await send(s, '.stage > .card .answer', how);
    ok(await s.p.$eval('#l-waiting .card', (n) => n.id) === 't-name-it', how + ': the answered card leaves Waiting at once');
    ok(await s.p.textContent('#n-waiting') === '1' && /ship-date/.test(await ids(s, '#l-working > details')), how + ': and is In progress');
    ok(s.errs.length === 0, 'no errors ' + s.errs.join(' ')); await s.ctx.close(); }
  // The same answer from the All tab's list card.
  { const s = await open(b, { db: { tasks: rows }, hash: '#all' });
    await s.p.click('#a-ship-date > summary'); await s.p.click('#a-ship-date .more > summary');
    await s.p.fill('#a-ship-date .answer textarea', 'Tuesday');
    await send(s, '#a-ship-date .answer', how);
    ok(await ids(s, '#a-waiting > details') === 'a-name-it', how + ': a list card leaves its list at once');
    ok(s.errs.length === 0, 'no errors ' + s.errs.join(' ')); await s.ctx.close(); }
  // A news card's note.
  { const s = await open(b, { db: { tasks: rows }, hash: '#news' });
    await s.p.click('#n-release-12 details.note > summary');
    await s.p.fill('#n-release-12 .answer textarea', 'Tell me more');
    await send(s, '#n-release-12 .answer', how);
    ok(await ids(s, '#l-news > .ncard') === 'n-search-box', how + ': the noted news card leaves News at once');
    ok(await s.p.textContent('#n-news') === '1', how + ': the count follows');
    ok(s.errs.length === 0, 'no errors ' + s.errs.join(' ')); await s.ctx.close(); }
}

// A failed save: the card stays, with its box, draft and focus.
{ const s = await open(b, { db: { tasks: rows }, hash: '#news' });
  await s.p.click('#n-release-12 details.note > summary');
  const ta = '#n-release-12 .answer textarea';
  await s.p.click(ta); await s.p.keyboard.type('Tell me more');
  await s.p.evaluate((ta) => { document.querySelector(ta).__mine = 1; window.__failSave = true; }, ta);
  await s.p.keyboard.press('Control+Enter'); await s.p.waitForTimeout(150);
  ok(await s.p.evaluate((ta) => document.activeElement === document.querySelector(ta) && document.activeElement.__mine === 1, ta), 'failed save: focus stays in the box');
  ok(await s.p.inputValue(ta) === 'Tell me more', 'and the draft is kept');
  ok(await ids(s, '#l-news > .ncard') === 'n-release-12,n-search-box', 'and the card stays');
  await s.p.evaluate(() => { window.__failSave = false; });
  await s.p.keyboard.press('Control+Enter'); await s.p.waitForTimeout(150);
  ok(await ids(s, '#l-news > .ncard') === 'n-search-box', 'sent again, it leaves at once');
  ok(s.errs.length === 0, 'no errors ' + s.errs.join(' ')); await s.ctx.close(); }

await done(b);
