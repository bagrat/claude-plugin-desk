// A step only the owner can do off the page (kind step, rule 10): its link is the card's main
// button, 👍 reads Done and tells the keeper it's done; other kinds keep "Go with the
// recommended". Run: node page/tests/step.mjs [shots-dir]
import { browser, open, ok, done } from './harness.mjs';
const out = process.argv[2] || '/tmp';
const FORM = 'https://example.com/forms/new';
const rows = {
  'send-form': { state: 'waiting', kind: 'step', rank: 1, title: 'Submit the form', context: 'It is filled in; only you can send it.', ask: 'Open the form and submit it.', updatedAt: '2026-10-26T10:00:00Z',
    links: [{ label: 'Open the form', url: FORM }, { label: 'The draft', url: 'https://example.com/draft' }] },
  'ship-date': { state: 'waiting', kind: 'decide', rank: 2, title: 'Pick the ship date', ask: 'Which day?', recommend: 'Tuesday.', updatedAt: '2026-10-25T10:00:00Z' },
};
const b = await browser();
for (const scheme of ['dark', 'light']) {
  const s = await open(b, { db: { tasks: rows }, scheme });
  const card = '.stage > .card';
  ok(await s.p.textContent(card + ' .t-title') === 'Submit the form', `${scheme}: the step comes first`);
  ok(await s.p.textContent(card + ' .chip') === 'Your step', `${scheme}: its kind reads Your step`);
  const main = await s.p.$eval(card + ' a.btn.primary.step', (a) => ({ href: a.href, text: a.textContent, target: a.target }));
  ok(main.href === FORM && main.text.includes('Open the form') && main.target === '_blank', `${scheme}: the link is the main button`);
  ok(JSON.stringify(await s.p.$$eval(card + ' .links a', (l) => l.map((a) => a.textContent))) === '["The draft"]', `${scheme}: the other links, without the step's`);
  ok(await s.p.$eval('.dock .btn.go', (n) => n.getAttribute('aria-label')) === 'Done', `${scheme}: 👍 reads Done`);
  if (scheme === 'dark') await s.p.screenshot({ path: `${out}/step-${scheme}.png` });
  await s.p.click('.dock .btn.go'); await s.p.waitForTimeout(300);
  const log = await s.log();
  const up = log.find((x) => x[0] === 'update' && x[2] === 'send-form');
  ok(up && up[3].state === 'working' && up[3].answer === 'Done.' && up[3].quick === 'done', 'Done moves it to In progress, answer "Done."');
  ok(log.some((x) => x[0] === 'comment' && x[1] === '[Desk] Submit the form (task send-form): Done.'), 'the keeper is told it is done');
  ok(await s.p.textContent(card + ' .t-title') === 'Pick the ship date', 'then the next card');
  ok(await s.p.$eval('.dock .btn.go', (n) => n.getAttribute('aria-label')) === 'Go with the recommended', 'a decision keeps Go with the recommended');
  ok(!(await s.p.$(card + ' a.step')), 'and has no step button');
  ok(s.errs.length === 0, `${scheme}: no errors ${s.errs.join(' ')}`);
  await s.ctx.close();
}
// The list view (In progress after Done is the same card; check the Waiting list on a wide page).
{ const s = await open(b, { db: { tasks: rows }, width: 1200 });
  const go = await s.p.$$eval('.btn.go', (l) => l.map((n) => n.getAttribute('aria-label')));
  ok(go.includes('Done'), 'wide: the step reads Done');
  ok(await s.p.$$eval('a.btn.primary.step', (l) => l.filter((a) => a.href === 'https://example.com/forms/new').length) >= 1, 'wide: the step button shows');
  ok(s.errs.length === 0, 'wide: no errors ' + s.errs.join(' ')); await s.ctx.close(); }
await done(b);
