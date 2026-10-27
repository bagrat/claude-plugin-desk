// Typing is never interrupted by a refresh (#40): while a card's text box has focus, a change
// to the list or the 5-minute re-render leaves that card in place (focus, caret, folds) and
// redraws the rest; the card catches up once the box loses focus. Run: node page/tests/typing.mjs
import { browser, open, ok, done } from './harness.mjs';
const rows = {
  'ship-date': { state: 'waiting', kind: 'decide', rank: 1, title: 'Pick the ship date', ask: 'Which day?', recommend: 'Tuesday.', updatedAt: '2026-10-25T10:00:00Z' },
  'name-it': { state: 'waiting', kind: 'decide', rank: 2, title: 'Name the tool', ask: 'Which name?', updatedAt: '2026-10-25T09:00:00Z' },
  'build': { state: 'working', title: 'Build the export', workingSince: '2026-10-25T08:00:00Z' },
};
const b = await browser();
const typing = (sel) => (p) => p.evaluate((sel) => { const a = document.activeElement; return a?.matches(sel) && a.__mine === 1 ? [a.value, a.selectionStart, a.selectionEnd] : null; }, sel);

// The waiting card: the keeper changes another card, then this one; the 5-minute refresh runs.
{ const s = await open(b, { db: { tasks: rows } });
  const ta = '.stage > .card .answer textarea';
  await s.p.click('.stage > .card .more > summary');
  await s.p.click(ta); await s.p.keyboard.type('Tuesday, after the demo');
  await s.p.evaluate((ta) => { const t = document.querySelector(ta); t.__mine = 1; t.setSelectionRange(9, 14); }, ta);
  const kept = typing(ta);
  await s.p.evaluate(() => window.__put('tasks', 'name-it', { state: 'waiting', kind: 'decide', rank: 2, title: 'Name the new tool', ask: 'Which name?', updatedAt: '2026-10-26T11:00:00Z' }));
  await s.p.waitForTimeout(200);
  ok(JSON.stringify(await kept(s.p)) === '["Tuesday, after the demo",9,14]', 'another card changes: the box keeps focus, text and selection');
  await s.p.evaluate(() => window.__put('tasks', 'ship-date', { state: 'waiting', kind: 'decide', rank: 1, title: 'Pick the release date', ask: 'Which day?', recommend: 'Tuesday.', updatedAt: '2026-10-26T11:05:00Z' }));
  await s.p.waitForTimeout(200);
  ok(JSON.stringify(await kept(s.p)) === '["Tuesday, after the demo",9,14]', 'its own card changes: still typing undisturbed');
  ok(await s.p.$eval('.stage > .card .more', (n) => n.open), 'its fold stays open');
  ok(await s.p.textContent('.stage > .card .t-title') === 'Pick the ship date', 'the card waits until you are done');
  await s.p.keyboard.type('!');
  ok(await s.p.inputValue(ta) === 'Tuesday, ! the demo', 'typing goes on where the caret was');
  await s.p.evaluate(() => document.activeElement?.blur?.()); await s.p.waitForTimeout(100);
  ok(await s.p.textContent('.stage > .card .t-title') === 'Pick the release date', 'focus leaves: the card catches up');
  ok(await s.p.inputValue(ta) === 'Tuesday, ! the demo', 'and the draft is still there');
  ok(await s.p.$eval('.stage > .card .more', (n) => n.open), 'the fold is still open');
  ok(s.errs.length === 0, 'no errors ' + s.errs.join(' ')); await s.ctx.close(); }

// Send while a change is held: the tap lands, the answer is saved.
{ const s = await open(b, { db: { tasks: rows } });
  const ta = '.stage > .card .answer textarea';
  await s.p.click('.stage > .card .more > summary');
  await s.p.click(ta); await s.p.keyboard.type('Tuesday');
  await s.p.evaluate(() => window.__put('tasks', 'name-it', { state: 'waiting', kind: 'decide', rank: 2, title: 'Name it now', updatedAt: '2026-10-26T11:00:00Z' }));
  await s.p.waitForTimeout(200);
  await s.p.click('.stage > .card .answer button:has-text("Send to the keeper")'); await s.p.waitForTimeout(300);
  const saved = (await s.log()).find((l) => l[0] === 'update' && l[2] === 'ship-date');
  ok(saved && saved[3].answer === 'Tuesday' && saved[3].state === 'working', 'Send works while a change was held');
  ok(s.errs.length === 0, 'no errors ' + s.errs.join(' ')); await s.ctx.close(); }

// A list card (In progress): open, typing, a change elsewhere and the 5-minute refresh leave it be.
{ const s = await open(b, { db: { tasks: rows } });
  await s.p.click('#tab-working');
  await s.p.click('#w-build > summary');
  await s.p.click('#w-build .more > summary');
  const ta = '#w-build .answer textarea';
  await s.p.click(ta); await s.p.keyboard.type('Ship CSV first');
  await s.p.evaluate((ta) => { document.querySelector(ta).__mine = 1; }, ta);
  await s.p.evaluate(() => window.__put('tasks', 'later-one', { state: 'working', title: 'Another job', workingSince: '2026-10-26T09:00:00Z' }));
  await s.p.waitForTimeout(200);
  ok(JSON.stringify(await typing(ta)(s.p)) === '["Ship CSV first",14,14]', 'list card: focus and caret kept');
  ok(await s.p.$eval('#w-build', (n) => n.open), 'list card: stays open');
  ok(await s.p.$$eval('#l-working > details', (l) => l.map((d) => d.id).join()) === 'w-later-one,w-build', 'the rest of the list is redrawn around it');
  await s.p.evaluate(() => render(ui.docs)); await s.p.waitForTimeout(50);
  ok(JSON.stringify(await typing(ta)(s.p)) === '["Ship CSV first",14,14]', 'the periodic re-render leaves it be too');
  ok(s.errs.length === 0, 'no errors ' + s.errs.join(' ')); await s.ctx.close(); }

await done(b);
