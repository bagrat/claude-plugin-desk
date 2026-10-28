// The page is an app shell (2026-10-28): always exactly the viewport's height, the header (and
// on Waiting the dashes) pinned at the top, the answer bar pinned at the bottom and fully on
// screen, and only the region between them scrolls; the document itself never does.
// Run: node page/tests/shell.mjs
import { browser, open, ok, done } from './harness.mjs';
const para = Array.from({ length: 40 }, (_, i) => 'Paragraph ' + (i + 1) + ' of the background, long enough to wrap onto a second line on a phone.').join('\n\n');
const rows = {
  'ship-date': { state: 'waiting', kind: 'decide', rank: 1, title: 'Pick the ship date', ask: 'Which day?', recommend: 'Tuesday.', context: para, updatedAt: '2026-10-25T10:00:00Z' },
  'name-it': { state: 'waiting', kind: 'decide', rank: 2, title: 'Name the tool', ask: 'Which name?', updatedAt: '2026-10-25T09:00:00Z' },
  ...Object.fromEntries(Array.from({ length: 30 }, (_, i) => ['job-' + i, { state: 'working', title: 'Build part ' + (i + 1), workingSince: '2026-10-25T08:00:00Z' }])),
};
const b = await browser();
const geo = (p) => p.evaluate(() => {
  const r = (s) => { const n = document.querySelector(s); return n && n.getBoundingClientRect(); };
  const d = document.documentElement, sc = document.querySelector('.scroller');
  return { vh: innerHeight, sh: d.scrollHeight, bsh: document.body.scrollHeight, head: r('header.bar').top, dashes: r('#count')?.top, headBottom: r('header.bar').bottom,
    dock: r('.dock-row')?.bottom, scrolls: !!sc && sc.scrollHeight > sc.clientHeight + 100 && getComputedStyle(sc).overflowY === 'auto' };
});

for (const height of [874, 600]) {
  const s = await open(b, { db: { tasks: rows }, height });
  let g = await geo(s.p);
  ok(g.sh === height && g.bsh <= height, `${height}: the document is the viewport's height (${g.sh}, body ${g.bsh})`);
  ok(g.head === 0, `${height}: the header is at the top (${g.head})`);
  ok(g.dock != null && g.dock <= height && g.dock > height - 120, `${height}: the answer bar is on screen at the bottom (${g.dock})`);
  ok(g.scrolls, `${height}: the card region scrolls`);
  // Scroll the card: the header, the dashes and the bar stay put; the document doesn't move.
  await s.p.mouse.move(200, height / 2); await s.p.mouse.wheel(0, 3000); await s.p.waitForTimeout(300);
  const after = await geo(s.p);
  ok(await s.p.$eval('.scroller', (n) => n.scrollTop > 500), `${height}: a wheel scrolls the card`);
  ok(await s.p.evaluate(() => scrollY === 0 && document.scrollingElement.scrollTop === 0), `${height}: and not the document`);
  ok(after.head === 0 && after.dashes === g.dashes && after.dock === g.dock, `${height}: header, dashes and bar stay pinned`);
  ok(after.dashes >= after.headBottom - 1, `${height}: the dashes sit under the header`);
  // Another card starts at the top.
  await s.p.click('.dash:not(.on)'); await s.p.waitForTimeout(400);
  ok(await s.p.$eval('.scroller', (n) => n.scrollTop === 0), `${height}: the next card starts at the top`);
  // Other tabs: pinned header, the list scrolls beneath it.
  await s.p.click('#tab-working'); await s.p.waitForTimeout(200);
  g = await geo(s.p);
  ok(g.sh === height && g.head === 0 && g.scrolls, `${height}: In progress: same shell, its list scrolls`);
  await s.p.mouse.wheel(0, 2000); await s.p.waitForTimeout(300);
  ok((await geo(s.p)).head === 0 && await s.p.evaluate(() => scrollY === 0), `${height}: In progress: the header stays`);
  ok(s.errs.length === 0, 'no errors ' + s.errs.join(' ')); await s.ctx.close();
}

// A grown answer box stays above the bar.
{ const s = await open(b, { db: { tasks: rows }, height: 600 });
  const ta = '.stage > .card .answer textarea';
  await s.p.click('.stage > .card .more > summary');
  await s.p.click(ta); await s.p.fill(ta, Array.from({ length: 30 }, (_, i) => 'line ' + i).join('\n'));
  await s.p.$eval(ta, (n) => n.scrollIntoView({ block: 'end' })); await s.p.waitForTimeout(200);
  const [box, bar] = await s.p.evaluate((ta) => [document.querySelector(ta).getBoundingClientRect().bottom, document.querySelector('.dock-row').getBoundingClientRect().top], ta);
  ok(box <= bar, `a grown box scrolled into view ends above the bar (${box} ≤ ${bar})`);
  ok(s.errs.length === 0, 'no errors ' + s.errs.join(' ')); await s.ctx.close(); }

// A keyboard comes up (a stand-in visual viewport shrinks to 330px): the shell fits above it,
// the bar on screen and the box being typed in above the bar; it goes down: back to full.
{ const s = await open(b, { db: { tasks: rows }, height: 874 });
  await s.p.addInitScript(() => {
    const vv = new EventTarget(); Object.assign(vv, { height: innerHeight, width: innerWidth, offsetTop: 0, offsetLeft: 0, scale: 1 });
    Object.defineProperty(window, 'visualViewport', { get: () => vv }); window.__kb = (h) => { vv.height = h; vv.dispatchEvent(new Event('resize')); };
  });
  await s.p.reload(); await s.p.waitForTimeout(500);
  const ta = '.stage > .card .answer textarea';
  await s.p.click('.stage > .card .more > summary');
  await s.p.click(ta); await s.p.fill(ta, Array.from({ length: 6 }, (_, i) => 'line ' + i).join('\n'));
  await s.p.evaluate(() => window.__kb(330)); await s.p.waitForTimeout(200);
  const [shellH, bar, box, boxTop, headTop] = await s.p.evaluate((ta) => [document.querySelector('.wrap').getBoundingClientRect().height, document.querySelector('.dock-row').getBoundingClientRect(), document.querySelector(ta).getBoundingClientRect().bottom, document.querySelector(ta).getBoundingClientRect().top, document.querySelector('header.bar').getBoundingClientRect().top], ta);
  ok(shellH === 330 && headTop === 0, `keyboard up: the shell fits above it (${shellH})`);
  ok(bar.bottom <= 330, `the bar sits above the keyboard (${bar.bottom})`);
  ok(boxTop >= 0 && box <= bar.top, `the box being typed in shows above the bar (${boxTop}–${box}, bar ${bar.top})`);
  ok(await s.p.evaluate(() => scrollY === 0), 'the document still does not scroll');
  await s.p.evaluate(() => window.__kb(874)); await s.p.waitForTimeout(200);
  ok(await s.p.$eval('.wrap', (n) => n.getBoundingClientRect().height) === 874, 'keyboard down: full height again');
  ok(s.errs.length === 0, 'no errors ' + s.errs.join(' ')); await s.ctx.close(); }
// On a touch phone (2026-10-28, an iPhone's artifact viewer hides a strip at the bottom of its
// frame that env(safe-area-inset-bottom) doesn't report): the bar keeps a home-indicator-sized
// gap under it, and the end of the card still clears it.
{ const s = await open(b, { db: { tasks: rows }, width: 402, height: 874 });
  const g = await s.p.evaluate(() => ({ coarse: matchMedia('(pointer: coarse)').matches, bar: document.querySelector('.dock-row').getBoundingClientRect() }));
  ok(g.coarse, 'the phone context is a touch one');
  ok(g.bar.bottom <= 874 - 46, `the bar's bottom edge is at least 46px above the viewport's bottom (${g.bar.bottom})`);
  await s.p.$eval('.scroller', (n) => { n.scrollTop = n.scrollHeight; }); await s.p.waitForTimeout(200);
  const [last, top] = await s.p.evaluate(() => { const c = document.querySelector('.stage > .card'); return [c.getBoundingClientRect().bottom, document.querySelector('.dock-row').getBoundingClientRect().top]; });
  ok(last <= top, `scrolled to the end, the card ends above the bar (${last} ≤ ${top})`);
  // The readout in More: numbers for the next device report, and a Copy.
  ok(!(await s.p.isVisible('.stage > .card .vp')), 'the readout is hidden while More is closed');
  await s.p.click('.stage > .card .more > summary');
  const t = await s.p.textContent('.stage > .card .vp-text');
  ok(/^viewport: 874 × 402 · visual \d+ · safe-area \d+\/\d+ · dock bottom gap \d+$/.test(t), 'the readout gives the numbers: ' + t);
  ok(/gap (4[6-9]|[5-9]\d)$/.test(t), 'and the gap is the touch one');
  ok(await s.p.isVisible('.stage > .card .vp button'), 'with a Copy button');
  ok(await s.p.$eval('.stage > .card .vp', (n) => !n.querySelector('*:not(span):not(button)')), 'built of plain text');
  ok(s.errs.length === 0, 'no errors ' + s.errs.join(' ')); await s.ctx.close(); }
await done(b);
