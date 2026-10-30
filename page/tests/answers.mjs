// Answers per question (2026-10-30): a card whose ask numbers its questions gets a Yes / No per
// question and "All as recommended"; picks and dictated words wait in the tray at the top of
// Waiting, and Send together saves each card's answer, the dictated words as an Inbox note, and
// wakes the keeper once. Run: node page/tests/answers.mjs [shots-dir]
import { browser, open, ok, done } from './harness.mjs';
const out = process.argv[2] || '/tmp';
const rows = {
  launch: { state: 'waiting', kind: 'decide', rank: 1, title: 'Plan the launch', updatedAt: '2026-10-30T10:00:00Z',
    ask: '1. Ship on Tuesday?\n2. Write the release notes first?\n3. Tell the beta group?', recommend: 'Yes to all three.', context: 'Three calls to make before the launch.' },
  font: { state: 'waiting', kind: 'decide', rank: 2, title: 'Pick a font', updatedAt: '2026-10-30T09:00:00Z',
    ask: '(1) Serif for headings? (2) Keep the body sans?', recommend: 'Serif headings, sans body.', context: 'The headings and the body.' },
  plain: { state: 'waiting', kind: 'decide', rank: 3, title: 'One question', updatedAt: '2026-10-30T08:00:00Z', ask: 'Merge it?', recommend: 'Yes.', context: 'One change.' },
};
const comments = (log) => log.filter((e) => e[0] === 'comment');
const b = await browser();
for (const scheme of ['dark', 'light']) {
  const s = await open(b, { db: { tasks: rows }, scheme });
  const card = '.stage > .card';
  ok(await s.p.$$eval(card + ' .qa', (l) => l.length) === 3, `${scheme}: a Yes / No per numbered question`);
  ok(!(await s.p.isHidden('#tray')), `${scheme}: the tray shows in Waiting`);
  ok(/Answer by voice/.test(await s.p.textContent('#tray-sum')), `${scheme}: with nothing ready, it offers the voice box`);
  await s.p.click(card + ' [aria-label="1: yes"]'); await s.p.click(card + ' [aria-label="2: no"]');
  ok(/Answer by voice/.test(await s.p.textContent('#tray-sum')), `${scheme}: a card half answered isn't ready`);
  await s.p.click(card + ' [aria-label="3: yes"]');
  ok(/1 answer ready/.test(await s.p.textContent('#tray-sum')), `${scheme}: all picked, it's ready`);
  ok(await s.p.$eval(card + ' [aria-label="2: no"]', (n) => n.getAttribute('aria-pressed')) === 'true', `${scheme}: the pick shows pressed`);
  ok(comments(await s.log()).length === 0 && !(await s.log()).some((e) => e[0] === 'update'), `${scheme}: nothing is sent on a pick`);
  if (scheme === 'dark') { await s.p.click('#tray-sum'); await s.p.waitForTimeout(100); await s.p.screenshot({ path: `${out}/answers-${scheme}.png` }); await s.p.click('#tray-sum'); }
  if (scheme === 'light') await s.p.screenshot({ path: `${out}/answers-${scheme}.png` });
  await s.ctx.close();
}

// Two cards and dictated words go together: each saved, one wake.
{ const s = await open(b, { db: { tasks: rows } });
  const card = '.stage > .card';
  await s.p.click(card + ' [aria-label="1: yes"]'); await s.p.click(card + ' [aria-label="2: no"]'); await s.p.click(card + ' [aria-label="3: yes"]');
  // Swipe on to the next card with a dash.
  await s.p.click('.dash >> nth=1'); await s.p.waitForTimeout(400);
  ok(await s.p.textContent(card + ' .t-title') === 'Pick a font', 'the next card');
  ok(await s.p.$$eval(card + ' .qa', (l) => l.length) === 2, 'questions on one line, numbered (1) (2), are found');
  await s.p.click(card + ' .allrec');
  await s.p.click('#tray-sum'); await s.p.fill('#tray-text', 'The one question: merge it after lunch.');
  ok(/3 answers ready/.test(await s.p.textContent('#tray-sum')), 'two cards and the dictated words are ready');
  await s.p.screenshot({ path: `${out}/answers-tray.png` });
  // A reload keeps what's picked.
  await s.p.reload(); await s.p.waitForTimeout(600);
  ok(/3 answers ready/.test(await s.p.textContent('#tray-sum')), 'a reload keeps the tray');
  await s.p.click('#tray-sum'); await s.p.click('#tray-send'); await s.p.waitForTimeout(400);
  const log = await s.log(), ups = log.filter((e) => e[0] === 'update' && e[1] === 'tasks' && e[3].state === 'working');
  ok(ups.length === 2, 'each card is saved, moved to In progress');
  ok(ups.find((e) => e[2] === 'launch')?.[3].answer === '1: yes. 2: no. 3: yes.', 'its answer per question');
  ok(ups.find((e) => e[2] === 'font')?.[3].answer === 'All as recommended: Serif headings, sans body.', 'all as recommended');
  const note = log.find((e) => e[0] === 'set' && e[1] === 'inbox');
  ok(note && note[3].text === 'The one question: merge it after lunch.' && note[3].from === 'waiting', 'the dictated words are an Inbox note');
  const cs = comments(log);
  ok(cs.length === 1 && /^\[Desk\] 3 answers, sent together:/.test(cs[0][1]) && cs[0][1].includes('(task launch)') && cs[0][1].includes('(task font)') && cs[0][1].includes('(inbox n-'), 'the keeper is woken once, for all of them');
  ok(log.findIndex((e) => e[0] === 'comment') > log.findIndex((e) => e[0] === 'set'), 'woken only after they are saved');
  ok(log.some((e) => e[0] === 'update' && e[2] === 'launch' && e[3].answerSent === true), 'and marked sent');
  ok(/Answer by voice/.test(await s.p.textContent('#tray-sum')) && await s.p.inputValue('#tray-text') === '', 'the tray empties');
  ok(await s.p.textContent(card + ' .t-title') === 'One question', 'the answered cards leave the deck');
  ok(!(await s.p.$(card + ' .qa')), 'a single question has no per-question chips');
  ok(s.errs.length === 0, 'no errors ' + s.errs.join(' ')); await s.ctx.close(); }

// A failed save keeps the answer in the tray and wakes no one.
{ const s = await open(b, { db: { tasks: rows } });
  const card = '.stage > .card';
  await s.p.click(card + ' .allrec');
  await s.p.evaluate(() => { window.__failSave = true; });
  await s.p.click('#tray-sum'); await s.p.click('#tray-send'); await s.p.waitForTimeout(300);
  ok(comments(await s.log()).length === 0, 'nothing saved: no wake');
  ok(/1 answer ready/.test(await s.p.textContent('#tray-sum')) && /Couldn't save/.test(await s.p.textContent('#tray-st')), 'the answer stays, and it says so');
  ok(s.errs.length === 0, 'no errors ' + s.errs.join(' ')); await s.ctx.close(); }

// Not the owner: no picks, no tray.
{ const s = await open(b, { db: { tasks: rows }, owner: false });
  ok(await s.p.isHidden('#tray') && !(await s.p.$('.qa')), 'a viewer who is not the owner gets neither');
  ok(s.errs.length === 0, 'no errors ' + s.errs.join(' ')); await s.ctx.close(); }
await done(b);
