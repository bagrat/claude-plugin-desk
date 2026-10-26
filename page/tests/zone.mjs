// The owner's time zone (desk.json's timezone): the page shows times in it and Later means
// tomorrow 9:00 there, whatever zone the viewer's browser is in; without one, the browser's.
// Run: node page/tests/zone.mjs
import { browser, open as openPage, ok, done } from './harness.mjs';
const rows = {
  'pick-day': { state: 'waiting', kind: 'decide', rank: 1, title: 'Pick a day', ask: 'Which?', recommend: 'Tuesday.', updatedAt: '2026-10-26T00:00:00Z' },
  'plan-trip': { state: 'scheduled', kind: 'do', title: 'Plan the trip', when: '2026-10-28T00:00:00Z', updatedAt: '2026-10-25T00:00:00Z' },
};
const b = await browser();
// The owner is in Tokyo; the viewer's browser is in Los Angeles.
const tapLater = async (s) => { await s.p.tap('#p-waiting .btn.later'); await s.p.waitForTimeout(300);
  return (await s.log()).find((e) => e[0] === 'update' && e[3].quick === 'later')?.[3].snoozeUntil; };
const nineTomorrowIn = (zone) => new Date().toLocaleString('en-US', { timeZone: zone }); // only its date matters

{
  const s = await openPage(b, { db: { tasks: rows }, zone: 'America/Los_Angeles', page: { timezone: 'Asia/Tokyo' } });
  ok(s.errs.length === 0, 'no page errors: ' + s.errs.join('; '));
  ok(/Last changed .*9:00/.test(await s.p.textContent('#stamp')), 'stamp in the owner\'s zone (09:00 Tokyo): ' + await s.p.textContent('#stamp'));
  const until = await tapLater(s);
  const t = new Date(until);
  const local = t.toLocaleString('en-GB', { timeZone: 'Asia/Tokyo', hour: '2-digit', minute: '2-digit', year: 'numeric', month: '2-digit', day: '2-digit' });
  const today = new Date(nineTomorrowIn('Asia/Tokyo')); today.setDate(today.getDate() + 1);
  ok(local.endsWith('09:00') && local.startsWith(String(today.getDate()).padStart(2, '0')), 'Later: tomorrow 9:00 in Tokyo, got ' + until + ' = ' + local);
  await s.ctx.close();
}
{
  const s = await openPage(b, { db: { tasks: rows }, zone: 'America/Los_Angeles' });
  ok(/Last changed .*5:00/.test(await s.p.textContent('#stamp')), 'no timezone: the browser\'s zone (17:00 LA): ' + await s.p.textContent('#stamp'));
  const until = await tapLater(s);
  const local = new Date(until).toLocaleString('en-GB', { timeZone: 'America/Los_Angeles', hour: '2-digit', minute: '2-digit' });
  ok(local === '09:00', 'no timezone: Later is 9:00 in the browser\'s zone, got ' + local);
  await s.ctx.close();
}
await done(b);
