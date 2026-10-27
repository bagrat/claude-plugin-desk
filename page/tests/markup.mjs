// A card's text (context, folds, ask): fenced code, `inline code`, "> " quotes and "1. " lists
// render as such, from text nodes only, each code block and quote with a Copy button (#39).
// Run: node page/tests/markup.mjs [shots-dir]
import { browser, open, ok, done } from './harness.mjs';
const out = process.argv[2] || '/tmp';
const F = '```';
const fold = [
  'The change:', F + 'python', 'def f(x):', '    if x:', '        return "<b>" * 3', F,
  'Call `render_page` once, not **twice**.',
  '> Nice catch on `f`.', '> Could it return early?',
  '1. Read it', '2. Run it', '3. Merge it',
  '- a bullet',
  '> In a quote:', '> ' + F, '> x = 1', '>   y = 2', '> ' + F,
].join('\n');
const rows = {
  'review-it': { state: 'waiting', kind: 'review', rank: 1, title: 'Review the change', context: 'Uses `desk.py` <i>raw</i>.', ask: 'Run `make test` first?',
    details: [{ title: 'The diff', text: fold }], updatedAt: '2026-10-26T10:00:00Z' },
};
const b = await browser();
for (const scheme of ['dark', 'light']) {
  const s = await open(b, { db: { tasks: rows }, scheme });
  await s.p.evaluate(() => { window.__copied = []; navigator.clipboard.writeText = async (t) => { window.__copied.push(t); }; });
  const card = '.stage > .card';
  await s.p.click(card + ' .fold > summary'); await s.p.waitForTimeout(200);
  const x = card + ' .fold > div';
  const pres = await s.p.$$eval(x + ' pre', (l) => l.map((n) => ({ text: n.textContent, code: !!n.querySelector('code'), ws: getComputedStyle(n).whiteSpace, ox: getComputedStyle(n).overflowX, font: getComputedStyle(n).fontFamily, inQuote: !!n.closest('blockquote') })));
  ok(pres.length === 2, `${scheme}: two code blocks (${pres.length})`);
  ok(pres[0] && pres[0].text === 'def f(x):\n    if x:\n        return "<b>" * 3' && pres[0].code, `${scheme}: the code keeps its lines and indentation, inside <code>`);
  ok(pres[0] && pres[0].ws === 'pre' && pres[0].ox === 'auto' && /mono/i.test(pres[0].font), `${scheme}: monospace, no wrapping, scrolls sideways`);
  ok(pres[1] && pres[1].inQuote && pres[1].text === 'x = 1\n  y = 2', `${scheme}: a fence inside a quote works`);
  ok(!(await s.p.$$eval(x + ' p', (l, F) => l.some((n) => n.textContent.includes(F) || /^\s*(>|\d+\.)\s/.test(n.textContent)), F)), `${scheme}: no fences, > or 1. left as text`);
  ok(await s.p.$$eval(x + ' pre b', (l) => l.length) === 0, `${scheme}: code is text, never markup`);
  ok(JSON.stringify(await s.p.$$eval(x + ' > ol > li', (l) => l.map((n) => n.textContent))) === '["Read it","Run it","Merge it"]', `${scheme}: numbered lines are an ordered list`);
  ok(JSON.stringify(await s.p.$$eval(x + ' > ul > li', (l) => l.map((n) => n.textContent))) === '["a bullet"]', `${scheme}: bullets still a list`);
  const code = await s.p.$$eval(x + ' p code', (l) => l.map((n) => n.textContent));
  ok(code.includes('render_page') && code.includes('f'), `${scheme}: inline code is <code> (${code})`);
  ok(await s.p.$eval(x, (n) => n.textContent.includes('`')) === false, `${scheme}: no backticks show`);
  ok(await s.p.$eval(x + ' p b', (n) => n.textContent) === 'twice', `${scheme}: bold still works beside code`);
  const qs = await s.p.$$eval(x + ' > .quote > blockquote', (l) => l.length);
  ok(qs === 2, `${scheme}: the two runs of > lines are two quotes (${qs})`);
  ok(await s.p.$eval(card + ' .ask code', (n) => n.textContent) === 'make test', `${scheme}: inline code in the ask`);
  ok(await s.p.$$eval(card + ' i', (l) => l.length) === 0, `${scheme}: no markup injected`);
  // Copy buttons: a code block copies its code; a quote copies its text without the "> ".
  await s.p.click(x + ' > .code .copy'); await s.p.click(x + ' > .quote > .copy');
  const copied = await s.p.evaluate(() => window.__copied);
  ok(copied[0] === 'def f(x):\n    if x:\n        return "<b>" * 3', `${scheme}: Copy copies the code`);
  ok(copied[1] === 'Nice catch on `f`.\nCould it return early?', `${scheme}: Copy copies the quote without > markers`);
  if (scheme === 'dark') await s.p.screenshot({ path: `${out}/markup-${scheme}.png`, fullPage: true });
  ok(s.errs.length === 0, `${scheme}: no errors ${s.errs.join(' ')}`);
  await s.ctx.close();
}
await done(b);
