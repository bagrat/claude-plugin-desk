// The dependsOn checklist: renders under the context, a tap opens the linked card. Run: node page/tests/deps.mjs
import { browser, open, ok, done } from './harness.mjs';
const rows = {
  'ship-date': { state: 'waiting', kind: 'decide', rank: 1, handle: 'ship date', title: 'Pick the ship date', context: 'The release waits on these.', ask: 'Which day?', recommend: 'Tuesday.', updatedAt: '2026-10-25T10:00:00Z',
    details: [{ title: 'Why that day', text: 'Because.' }],
    dependsOn: [{ item: 'version 1.2 released', state: 'open' }, { item: 'the docs pass', card: 'docs-pass', state: 'building' }, { item: 'the hand test', card: 'hand-test', state: 'open' }, { item: 'the post', state: 'done' }] },
  'hand-test': { state: 'waiting', kind: 'check', rank: 2, title: 'Hand test 1.2', ask: 'Ready?', recommend: 'Yes', updatedAt: '2026-10-25T10:00:00Z' },
  'docs-pass': { state: 'working', kind: 'do', title: 'A pass over the docs', sessions: [{ label: 's', url: 'https://claude.ai/code/session_01A' }], workingSince: '2026-10-25T09:00:00Z', updatedAt: '2026-10-25T10:00:00Z' },
};
const b = await browser();
for (const scheme of ['dark', 'light']) {
  const s = await open(b, { db: { tasks: rows }, scheme });
  const items = await s.p.$$eval('.stage > .card .deps li', (l) => l.map((x) => x.className));
  ok(JSON.stringify(items) === JSON.stringify(['d-open', 'd-building', 'd-open', 'd-done']), `${scheme}: four items, each with its state`);
  ok(await s.p.$eval('.stage > .card .body > .field .lbl', (n) => n.textContent) === 'The ask', `${scheme}: the ask first (rule 3)`);
  if (scheme === 'dark') {
    await s.p.click('.stage > .card .deps button:has-text("the hand test")'); await s.p.waitForTimeout(400);
    ok(await s.p.textContent('.stage > .card .t-title') === 'Hand test 1.2', 'a tap opens the waiting card');
    await s.p.click('.dash >> nth=0'); await s.p.waitForTimeout(400);
    await s.p.click('.stage > .card .deps button:has-text("the docs pass")'); await s.p.waitForTimeout(400);
    ok(await s.p.$eval('#p-working', (n) => !n.hidden) && await s.p.$eval('#w-docs-pass', (n) => n.open), 'a tap opens the card in progress');
  }
  ok(s.errs.length === 0, `${scheme}: no errors ${s.errs.join(' ')}`);
  await s.ctx.close();
}
await done(b);
