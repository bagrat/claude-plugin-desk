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
// A viewer's sheet (2026-10-28): with nothing focused, its visual viewport is 90px shorter than
// innerHeight and 60px down. That's no keyboard: the shell fills the viewport, header at the top,
// no band under it. Focus a box and the visual viewport shrinks further: that's the keyboard.
{ const s = await open(b, { db: { tasks: rows }, height: 874 });
  await s.p.addInitScript(() => {
    const vv = new EventTarget(); Object.assign(vv, { height: innerHeight - 90, width: innerWidth, offsetTop: 60, offsetLeft: 0, scale: 1 });
    Object.defineProperty(window, 'visualViewport', { get: () => vv }); window.__kb = (h) => { vv.height = h; vv.dispatchEvent(new Event('resize')); };
  });
  await s.p.reload(); await s.p.waitForTimeout(500);
  const shell = () => s.p.evaluate(() => [document.querySelector('.wrap').getBoundingClientRect(), document.querySelector('header.bar').getBoundingClientRect().top, document.querySelector('.dock-row').getBoundingClientRect().bottom]);
  let [w, head, dock] = await shell();
  ok(w.top === 0 && w.bottom === 874, `in the sheet, no keyboard: the shell fills the viewport, no band (${w.top}–${w.bottom})`);
  ok(head === 0, `and the header is at the top (${head})`);
  await s.p.evaluate(() => window.__kb(innerHeight - 90)); await s.p.waitForTimeout(100);
  [w, head] = await shell();
  ok(w.bottom === 874 && head === 0, `a resize with nothing focused changes nothing (${w.bottom}, ${head})`);
  const ta = '.stage > .card .answer textarea';
  await s.p.click('.stage > .card .more > summary'); await s.p.click(ta);
  [w, head] = await shell();
  ok(w.bottom === 874 && head === 0, `focusing a box alone isn't a keyboard (${w.bottom}, ${head})`);
  await s.p.evaluate(() => window.__kb(400)); await s.p.waitForTimeout(200);
  [w, head, dock] = await shell();
  ok(w.height === 400 && dock <= 400, `the keyboard comes up: the shell fits above it (${w.height}, bar ${dock})`);
  await s.p.evaluate(() => window.__kb(innerHeight - 90)); await s.p.$eval(ta, (n) => n.blur()); await s.p.waitForTimeout(200);
  [w, head] = await shell();
  ok(w.top === 0 && w.bottom === 874 && head === 0, `it goes down: full again, header at the top (${w.top}–${w.bottom})`);
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
  await s.p.click('.stage > .card .more > summary'); await s.p.waitForTimeout(100);
  const t = await s.p.textContent('.stage > .card .vp-text');
  ok(/^viewport: 874 × 402 · visual \d+ · safe-area \d+\/\d+ · root pad \d+\/\d+ · dock bottom gap \d+$/.test(t), 'the readout gives the numbers: ' + t);
  ok(/gap (4[6-9]|[5-9]\d)$/.test(t), 'and the gap is the touch one');
  ok(await s.p.isVisible('.stage > .card .vp button'), 'with a Copy button');
  ok(await s.p.$eval('.stage > .card .vp', (n) => !n.querySelector('*:not(span):not(button)')), 'built of plain text');
  ok(s.errs.length === 0, 'no errors ' + s.errs.join(' ')); await s.ctx.close(); }
// Inside the platform's skeleton on an iPhone (2026-10-28): the root is padded by the safe area
// (47 top, 34 bottom here). The header starts under the top padding; the cards run on under the
// bottom one to the viewport's bottom edge (2026-10-29: no empty strip under the list), the bar
// floats a home-indicator gap above that edge, the document doesn't scroll, and nothing outside
// the shell shows in another color.
{ const s = await open(b, { db: { tasks: rows }, width: 402, height: 874, insets: { top: 47, bottom: 34 } });
  const g = await s.p.evaluate(() => {
    const r = (q) => document.querySelector(q).getBoundingClientRect(), bg = (n) => getComputedStyle(n).backgroundColor;
    return { sh: document.scrollingElement.scrollHeight, vh: innerHeight, head: r('header.bar').top, wrap: r('.wrap'), scroller: r('.scroller'), dock: r('.dock-row').bottom,
      html: bg(document.documentElement), body: bg(document.body) };
  });
  ok(g.sh === g.vh, `the document is exactly the viewport (${g.sh} = ${g.vh})`);
  ok(g.head === 47, `the header starts under the root's top padding (${g.head})`);
  ok(g.wrap.top === 47 && g.wrap.bottom === 874, `the shell runs from under the top padding to the bottom edge (${g.wrap.top}–${g.wrap.bottom})`);
  ok(g.scroller.bottom === 874, `the card list reaches the viewport's bottom, no strip under it (${g.scroller.bottom})`);
  // What shows at the bottom edge is the list, not bare root under a clipped shell (getBoundingClientRect ignores clipping).
  const inList = () => s.p.evaluate(() => [873, 864, 844].map((y) => { const n = document.elementFromPoint(200, y); return n && n.closest('.scroller') ? 'list' : (n ? n.nodeName : 'none'); }));
  { const h = await inList(); ok(h.every((x) => x === 'list'), `Waiting: the bottom 1, 10 and 30px show the list (${h})`); }
  ok(g.dock <= 874 - 34 - 12 && g.dock > 874 - 34 - 120, `the bar sits on screen, clear of the bottom inset (${g.dock})`);
  ok(g.html === g.body, `the root's padding bands are the page's color (${g.html} / ${g.body})`);
  await s.p.mouse.move(200, 400); await s.p.mouse.wheel(0, 3000); await s.p.waitForTimeout(300);
  ok(await s.p.evaluate(() => document.scrollingElement.scrollTop === 0) && (await s.p.$eval('header.bar', (n) => n.getBoundingClientRect().top)) === 47, 'a wheel scrolls the card, not the document');
  await s.p.click('.stage > .card .more > summary'); await s.p.waitForTimeout(100);
  const t = await s.p.textContent('.stage > .card .vp-text');
  ok(/ · root pad 47\/34 · /.test(t), 'the readout shows the root padding: ' + t);
  // Scrolled to the end, the last of the card clears the bar.
  await s.p.$eval('.scroller', (n) => { n.scrollTop = n.scrollHeight; }); await s.p.waitForTimeout(200);
  const [last, barTop] = await s.p.evaluate(() => [document.querySelector('.stage > .card').getBoundingClientRect().bottom, document.querySelector('.dock-row').getBoundingClientRect().top]);
  ok(last <= barTop, `scrolled to the end, the card ends above the bar (${last} ≤ ${barTop})`);
  // Other tabs: the list also runs to the bottom edge, and its last row scrolls into full view.
  await s.p.click('#tab-working'); await s.p.waitForTimeout(200);
  await s.p.$eval('.scroller', (n) => { n.scrollTop = n.scrollHeight; }); await s.p.waitForTimeout(200);
  const [sb, lastRow] = await s.p.evaluate(() => { const rows = document.querySelectorAll('#p-working .list > *'); return [document.querySelector('.scroller').getBoundingClientRect().bottom, rows[rows.length - 1].getBoundingClientRect().bottom]; });
  ok(sb === 874 && lastRow <= 874 - 34, `In progress: the list reaches the bottom edge and its last row clears the inset (${sb}, ${lastRow})`);
  { const h = await inList(); ok(h.every((x) => x === 'list'), `In progress: the bottom 1, 10 and 30px show the list (${h})`); }
  ok(await s.p.evaluate(() => document.scrollingElement.scrollTop === 0 && document.scrollingElement.scrollHeight === innerHeight), 'and the document still does not scroll');
  // A keyboard (stand-in visual viewport 400px): the shell still ends at its top.
  await s.p.addInitScript(() => {
    const vv = new EventTarget(); Object.assign(vv, { height: innerHeight, width: innerWidth, offsetTop: 0, offsetLeft: 0, scale: 1 });
    Object.defineProperty(window, 'visualViewport', { get: () => vv }); window.__kb = (h) => { vv.height = h; vv.dispatchEvent(new Event('resize')); };
  });
  await s.p.reload(); await s.p.waitForTimeout(500);
  const ta = '.stage > .card .answer textarea';
  await s.p.click('.stage > .card .more > summary'); await s.p.click(ta);
  await s.p.evaluate(() => window.__kb(400)); await s.p.waitForTimeout(200);
  const [w, bar] = await s.p.evaluate(() => [document.querySelector('.wrap').getBoundingClientRect(), document.querySelector('.dock-row').getBoundingClientRect().bottom]);
  ok(w.top === 47 && w.bottom === 400 && bar <= 400, `keyboard up: the shell ends at the keyboard (${w.top}–${w.bottom}, bar ${bar})`);
  ok(await s.p.evaluate(() => document.scrollingElement.scrollTop === 0), 'and the document still does not scroll');
  ok(s.errs.length === 0, 'no errors ' + s.errs.join(' ')); await s.ctx.close(); }
await done(b);
