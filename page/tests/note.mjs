// The note tab's send: the keeper is woken only once the note is saved; a failed or slow save
// keeps the note (and a retry rewrites the same row); words typed or screenshots picked while
// it saves stay for the next note; a screenshot that can't upload holds the note until it's
// removed; an unsent note survives a reload. Run: node page/tests/note.mjs
import { browser, open, ok, done } from './harness.mjs';
const b = await browser();
const png = (name) => ({ name, mimeType: 'image/png', buffer: Buffer.from('x') });
const sets = (log) => log.filter((e) => e[0] === 'set' && e[1] === 'inbox');
const comments = (log) => log.filter((e) => e[0] === 'comment');

// Saved first, woken after; what's typed meanwhile stays in the box.
{ const s = await open(b, { hash: '#note' });
  await s.p.evaluate(() => { window.__hook = { upload: () => new Promise((r) => setTimeout(r, 200)), set: () => new Promise((r) => setTimeout(r, 400)) }; });
  await s.p.setInputFiles('#note-pick', png('a.png'));
  await s.p.fill('#note-text', 'First thought'); await s.p.click('#note-send'); // waits for the upload, then saves
  await s.p.waitForTimeout(100); await s.p.click('#note-text'); await s.p.keyboard.press('End'); await s.p.keyboard.type(' and a second');
  await s.p.waitForTimeout(700);
  const log = await s.log(), i = log.findIndex((e) => e[0] === 'set' && e[1] === 'inbox'), j = log.findIndex((e) => e[0] === 'comment');
  ok(i >= 0 && j > i, 'the note is saved before the keeper is woken');
  ok(sets(log)[0][3].text === 'First thought' && sets(log)[0][3].images?.length === 1, 'it carries its text and screenshot');
  ok(await s.p.inputValue('#note-text') === 'and a second', 'words typed while it saved stay in the box');
  ok(s.errs.length === 0, 'no errors ' + s.errs.join(' ')); await s.ctx.close(); }

// A failed save keeps the note and wakes no one; the retry rewrites the same row.
{ const s = await open(b, { hash: '#note' });
  await s.p.evaluate(() => { let n = 0; window.__hook = { set: async () => { if (!n++) throw { code: 'unavailable' }; } }; });
  await s.p.fill('#note-text', 'Rename the strip'); await s.p.click('#note-send'); await s.p.waitForTimeout(200);
  ok(/Couldn't save it/.test(await s.p.textContent('#note-st')) && await s.p.inputValue('#note-text') === 'Rename the strip', 'a failed save says so and keeps the note');
  ok(comments(await s.log()).length === 0, 'and wakes no one');
  await s.p.click('#note-send'); await s.p.waitForTimeout(200);
  const log = await s.log();
  ok(sets(log).length === 1 && comments(log).length === 1, 'the retry saves it once and wakes the keeper once');
  ok(s.errs.length === 0, 'no errors ' + s.errs.join(' ')); await s.ctx.close(); }

// A screenshot that can't upload holds the note, says why, and can be removed.
{ const s = await open(b, { hash: '#note' });
  await s.p.evaluate(() => { window.__hook = { upload: async (f) => { if (/heic/.test(f.name)) throw { code: 'unsupported_type' }; } }; });
  await s.p.setInputFiles('#note-pick', [png('ok.png'), png('phone.heic')]); await s.p.waitForTimeout(100);
  await s.p.fill('#note-text', 'Look'); await s.p.click('#note-send'); await s.p.waitForTimeout(200);
  ok(/couldn't upload \(unsupported_type\)/.test(await s.p.textContent('#note-picked')) && sets(await s.log()).length === 0, 'a bad screenshot holds the note and says why');
  await s.p.click('[aria-label="Remove phone.heic"]'); await s.p.click('#note-send'); await s.p.waitForTimeout(200);
  const log = await s.log();
  ok(sets(log).length === 1 && sets(log)[0][3].images.length === 1 && log.filter((e) => e[0] === 'upload').length === 1, 'removed, the note goes with the good one, uploaded once');
  ok(s.errs.length === 0, 'no errors ' + s.errs.join(' ')); await s.ctx.close(); }

// A wake that can't go is said plainly and noted on the row; no "tap again" for a saved note.
{ const s = await open(b, { hash: '#note' });
  await s.p.evaluate(() => { window.__hook = { send: async () => { throw { code: 'consent_required' }; } }; });
  await s.p.fill('#note-text', 'Needs consent'); await s.p.click('#note-send'); await s.p.waitForTimeout(200);
  const st = await s.p.textContent('#note-st'), log = await s.log();
  ok(/Saved on the Inbox/.test(st) && !/tap again/.test(st), 'consent needed: saved, no tap again (' + st + ')');
  ok(log.some((e) => e[0] === 'update' && e[1] === 'inbox' && e[3].sendErr === 'consent_required'), 'the row says the keeper was not woken');
  ok(s.errs.length === 0, 'no errors ' + s.errs.join(' ')); await s.ctx.close(); }

// Send is off while a screenshot uploads, so the wake stays close to the tap: once it's on,
// the only wait between the tap and the wake is the row write.
{ const s = await open(b, { hash: '#note' });
  await s.p.evaluate(() => { window.__hook = { upload: () => new Promise((r) => { window.__release = r; }) }; });
  await s.p.fill('#note-text', 'With a picture'); await s.p.setInputFiles('#note-pick', png('a.png')); await s.p.waitForTimeout(100);
  ok(await s.p.isDisabled('#note-send') && /Uploading…/.test(await s.p.textContent('#note-send')), 'Send is off and reads Uploading… while a screenshot uploads');
  ok(!(await s.p.isVisible('#note-send .kbd')), 'and shows no shortcut meanwhile');
  await s.p.focus('#note-text'); await s.p.keyboard.press('Control+Enter'); await s.p.keyboard.press('Meta+Enter'); await s.p.waitForTimeout(100);
  ok(sets(await s.log()).length === 0, 'Cmd/Ctrl-Enter does nothing while it uploads');
  await s.p.evaluate(() => window.__release()); await s.p.waitForTimeout(100);
  ok(await s.p.isEnabled('#note-send') && /Send to the keeper/.test(await s.p.textContent('#note-send')) && /↵/.test(await s.p.textContent('#note-send')), 'Send comes back, with its shortcut, once the upload is done');
  await s.p.evaluate(() => { window.__t = {}; window.__hook = {
    upload: () => new Promise((r) => setTimeout(r, 1000)),
    set: async () => { window.__t.set = performance.now(); await new Promise((r) => setTimeout(r, 150)); },
    send: async () => { window.__t.send = performance.now(); } }; });
  const t0 = await s.p.evaluate(() => performance.now());
  await s.p.click('#note-send'); await s.p.waitForTimeout(400);
  const t = await s.p.evaluate(() => window.__t), log = await s.log();
  ok(t.set - t0 < 100 && t.send - t.set < 300, 'the row is written at the tap and the wake follows it (' + Math.round(t.set - t0) + 'ms, ' + Math.round(t.send - t.set) + 'ms)');
  ok(log.filter((e) => e[0] === 'upload').length === 1 && sets(log)[0][3].images?.length === 1, 'with no second upload');
  ok(s.errs.length === 0, 'no errors ' + s.errs.join(' ')); await s.ctx.close(); }

// A failed upload leaves Send on; a tap tries the screenshot again and sends nothing until it's up.
{ const s = await open(b, { hash: '#note' });
  await s.p.evaluate(() => { let n = 0; window.__hook = { upload: () => n++ ? new Promise((r) => { window.__release = r; }) : Promise.reject({ code: 'network' }) }; });
  await s.p.fill('#note-text', 'Retry it'); await s.p.setInputFiles('#note-pick', png('b.png')); await s.p.waitForTimeout(100);
  ok(await s.p.isEnabled('#note-send') && /couldn't upload \(network\)/.test(await s.p.textContent('#note-picked')) && await s.p.isVisible('[aria-label="Remove b.png"]'), 'a failed upload shows its chip and ×, and Send stays on');
  await s.p.click('#note-send'); await s.p.waitForTimeout(100);
  ok(await s.p.isDisabled('#note-send') && sets(await s.log()).length === 0, 'Send tries it again and is off while it uploads; nothing is saved yet');
  await s.p.evaluate(() => window.__release()); await s.p.waitForTimeout(100);
  await s.p.click('#note-send'); await s.p.waitForTimeout(200);
  const log = await s.log();
  ok(sets(log).length === 1 && sets(log)[0][3].images?.length === 1 && comments(log).length === 1, 'once it is up, Send saves the note and wakes the keeper');
  ok(s.errs.length === 0, 'no errors ' + s.errs.join(' ')); await s.ctx.close(); }

// An unsent note survives a reload.
{ const s = await open(b, { hash: '#note' });
  await s.p.fill('#note-text', 'Half-written'); await s.p.reload(); await s.p.waitForTimeout(400);
  ok(await s.p.inputValue('#note-text') === 'Half-written', 'an unsent note survives a reload');
  ok(s.errs.length === 0, 'no errors ' + s.errs.join(' ')); await s.ctx.close(); }

await done(b);
