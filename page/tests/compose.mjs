// Writing an answer or a note (#44): Cmd-Enter (Ctrl-Enter off a Mac) sends the box as the
// button does, plain Enter adds a line, and the box grows with its text up to 60% of the
// viewport, shrinks back after sending, and a restored draft opens at full height.
// Run: node page/tests/compose.mjs
import { browser, open, ok, done } from './harness.mjs';
const rows = {
  'ship-date': { state: 'waiting', kind: 'decide', rank: 1, title: 'Pick the ship date', ask: 'Which day?', updatedAt: '2026-10-25T10:00:00Z' },
  'name-it': { state: 'waiting', kind: 'decide', rank: 2, title: 'Name the tool', ask: 'Which name?', updatedAt: '2026-10-25T09:00:00Z' },
};
const b = await browser();
const h = (p, sel) => p.$eval(sel, (n) => n.getBoundingClientRect().height);
const lines = (n) => Array.from({ length: n }, (_, i) => 'line ' + (i + 1)).join('\n');

// The answer box: Enter adds a line, it grows, Ctrl-Enter sends it, it shrinks back.
{ const s = await open(b, { db: { tasks: rows } });
  const ta = '.stage > .card .answer textarea';
  await s.p.click('.stage > .card .more > summary');
  const start = await h(s.p, ta);
  ok(Math.round(start) === 76, 'the answer box starts at its minimum height (' + start + ')');
  ok(/↵/.test(await s.p.textContent('.stage > .card .answer button')), 'the button shows the shortcut');
  await s.p.click(ta); await s.p.keyboard.type('Tuesday'); await s.p.keyboard.press('Enter'); await s.p.keyboard.type('after the demo');
  ok(await s.p.inputValue(ta) === 'Tuesday\nafter the demo', 'plain Enter adds a line');
  ok(!(await s.log()).some((l) => l[0] === 'update'), 'and sends nothing');
  await s.p.fill(ta, lines(8));
  const grown = await h(s.p, ta);
  ok(grown > start + 60, 'the box grows with its text (' + grown + ')');
  ok(await s.p.$eval(ta, (n) => n.scrollHeight <= n.clientHeight + 1), 'and shows all of it');
  await s.p.fill(ta, lines(80));
  const max = await h(s.p, ta);
  ok(max <= 874 * 0.6 + 1 && max > 874 * 0.6 - 30, 'it stops at 60% of the viewport (' + max + ')');
  ok(await s.p.$eval(ta, (n) => n.scrollHeight > n.clientHeight && getComputedStyle(n).overflowY !== 'hidden'), 'and scrolls beyond that');
  await s.p.fill(ta, 'Tuesday');
  ok(Math.round(await h(s.p, ta)) === 76, 'it shrinks when the text does');
  await s.p.fill(ta, lines(6));
  await s.p.keyboard.press('Control+Enter'); await s.p.waitForTimeout(300);
  const saved = (await s.log()).find((l) => l[0] === 'update' && l[2] === 'ship-date');
  ok(saved && saved[3].answer === lines(6) && saved[3].state === 'working', 'Ctrl-Enter sends the answer');
  ok((await s.log()).filter((l) => l[0] === 'update' && l[2] === 'ship-date' && l[3].answer).length === 1, 'once');
  ok(s.errs.length === 0, 'no errors ' + s.errs.join(' ')); await s.ctx.close(); }

// Cmd-Enter on a Mac; a draft restored after a re-render opens at its full height.
{ const s = await open(b, { db: { tasks: rows } });
  await s.p.evaluate(() => { drafts['name-it'] = Array.from({ length: 8 }, (_, i) => 'line ' + (i + 1)).join('\n'); render(ui.docs); });
  await s.p.click('#tab-all'); await s.p.click('#a-name-it > summary'); await s.p.click('#a-name-it .more > summary');
  await s.p.waitForTimeout(100);
  ok(await h(s.p, '#a-name-it .answer textarea') > 136, 'a restored draft opens at full height');
  await s.p.click('#a-name-it .answer textarea');
  await s.p.keyboard.press('Meta+Enter'); await s.p.waitForTimeout(300);
  const saved = (await s.log()).find((l) => l[0] === 'update' && l[2] === 'name-it');
  ok(saved && saved[3].answer === lines(8), 'Cmd-Enter sends it too');
  ok(s.errs.length === 0, 'no errors ' + s.errs.join(' ')); await s.ctx.close(); }

// The Inbox note box: grows, Ctrl-Enter sends, shrinks back.
{ const s = await open(b, { db: { tasks: rows }, hash: '#note' });
  const ta = '#note-text';
  const start = await h(s.p, ta);
  ok(Math.round(start) === 140, 'the note box starts at its minimum height (' + start + ')');
  ok(/↵/.test(await s.p.textContent('#note-send')), 'its button shows the shortcut');
  await s.p.fill(ta, lines(14));
  ok(await h(s.p, ta) > start + 60, 'the note box grows');
  await s.p.focus(ta); await s.p.keyboard.press('Control+Enter'); await s.p.waitForTimeout(300);
  const saved = (await s.log()).find((l) => l[0] === 'set' && l[1] === 'inbox');
  ok(saved && saved[3].text === lines(14), 'Ctrl-Enter sends the note');
  ok(await s.p.inputValue(ta) === '' && Math.round(await h(s.p, ta)) === 140, 'and the box shrinks back');
  ok(s.errs.length === 0, 'no errors ' + s.errs.join(' ')); await s.ctx.close(); }

await done(b);
