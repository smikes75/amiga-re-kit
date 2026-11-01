"""The display must never touch the game: a page replayed under controlled clocks (docs/WB-PLYNULOST.md, module H).

The page's requestAnimationFrame and performance.now are replaced by a virtual clock before any script runs; the
replay then ticks it at 50, 60, 120 and 144 Hz (any list) with the same inputs scheduled by GAME frame, and reads
the page's own fingerprint of the game state after N game frames. Equal fingerprints across the rates prove that
the number of display frames drawn between two game frames - the interpolation, the transitions, a sub-pixel shift,
every presentation option - changes nothing in the game. A difference names the rate that differs.

The page provides, besides ``globalThis.WBLONGRUN`` 1.4 (ready, status, prepare, ...), the hooks of 1.5:
  done() -> the number of game frames computed so far;
  state() -> a string: the fingerprint of the game's state (a hash of its RAM or of what moves - camera, objects);
  inputs(schedule) (optional) -> accepts [[frame, mask], ...]: from game frame `frame` on, the keys `mask` are held
  (the page's own bit layout) until the next entry; a page without it is replayed without input.

    arek web replay http://127.0.0.1:8920/scene-demo.html --hz 50,60,120,144 --frames 300 --route 1:120,2:60,0:120

The route is mask:frames pairs in game frames (here: the right key 120 frames, the left key 60, nothing 120). The
run is as fast as the page computes - the clock is virtual - and needs no display at all (headless).
"""
import json

HZ_DEFAULT = (50, 60, 120, 144)

CLOCK_JS = """(() => {
    // the virtual clock: installed before the page's scripts; performance.now and requestAnimationFrame follow it
    let now = 0; const queue = []; let next = 1;
    const perf = performance;
    try { Object.defineProperty(perf, 'now', { value: () => now, configurable: true, writable: true }); } catch (e) { perf.now = () => now; }
    const realDateNow = Date.now; const t0 = realDateNow();
    Date.now = () => t0 + now;
    window.requestAnimationFrame = (cb) => { const id = next++; queue.push([id, cb]); return id; };
    window.cancelAnimationFrame = (id) => { const i = queue.findIndex((q) => q[0] === id); if (i >= 0) queue.splice(i, 1); };
    window.__wbClock = {
        tick(dt) { now += dt; const cbs = queue.splice(0); for (const [, cb] of cbs) { try { cb(now); } catch (e) { console.error('rAF callback: ' + e); } } return now; },
        now: () => now, pending: () => queue.length, ticks: 0,
    };
})();"""


def parse_route(text):
    """``"1:120,2:60,0:120"`` -> ``[[0, 1], [120, 2], [180, 0]]`` (frame, mask), cumulative."""
    out, at = [], 0
    if not text:
        return out
    for part in text.split(','):
        mask, n = part.split(':')
        out.append([at, int(mask, 0)])
        at += int(n)
    return out


def replay_one(page, hz, frames, schedule, settle_ms=0):
    """Tick the page's virtual clock at `hz` until the page has computed `frames` game frames; returns the metrics."""
    dt = 1000.0 / hz
    page.wait_for_function('globalThis.WBLONGRUN', timeout=30000)
    if page.evaluate('typeof globalThis.WBLONGRUN.prepare === "function"'):
        page.evaluate('async () => { await globalThis.WBLONGRUN.prepare(); return true; }')
    has_inputs = page.evaluate('typeof globalThis.WBLONGRUN.inputs === "function"')
    if schedule and has_inputs:
        page.evaluate('(s) => globalThis.WBLONGRUN.inputs(s)', schedule)
    for name in ('done', 'state'):
        if not page.evaluate('typeof globalThis.WBLONGRUN.%s === "function"' % name):
            raise ValueError('the page has no WBLONGRUN.%s() hook (replay needs done() and state(), 1.5)' % name)
    ticks, drawn0 = 0, None
    while True:
        done = page.evaluate('globalThis.WBLONGRUN.done()')
        if done >= frames:
            break
        page.evaluate('(dt) => { __wbClock.tick(dt); __wbClock.ticks++; }', dt)
        ticks += 1
        if ticks > frames * 10 + 1000:
            raise RuntimeError('%d Hz: the page made only %d of %d game frames after %d display frames (does the engine run on the page\'s clock?)' % (hz, done, frames, ticks))
    return {'hz': hz, 'ticks': ticks, 'done': page.evaluate('globalThis.WBLONGRUN.done()'), 'state': str(page.evaluate('globalThis.WBLONGRUN.state()')),
            'inputs': bool(schedule and has_inputs), 'status': page.evaluate('globalThis.WBLONGRUN.status ? String(WBLONGRUN.status()) : ""')}


def run(url, hz_list=HZ_DEFAULT, frames=300, route=None, log=print, browser='chromium', viewport=(1280, 800)):
    """Replay the page at every rate; ``{'runs': [...], 'equal': bool, 'reference': state}``."""
    from playwright.sync_api import sync_playwright
    schedule = parse_route(route) if isinstance(route, str) else (route or [])
    runs = []
    with sync_playwright() as pw:
        br = getattr(pw, browser).launch()
        for hz in hz_list:
            ctx = br.new_context(viewport={'width': viewport[0], 'height': viewport[1]})
            ctx.add_init_script(CLOCK_JS)
            page = ctx.new_page()
            errs = []
            page.on('pageerror', lambda e: errs.append(str(e)[:200]))
            page.goto(url)
            r = replay_one(page, hz, frames, schedule)
            r['errors'] = errs[:5]
            runs.append(r)
            log('%d Hz: %d display frames for %d game frames, state %s%s' % (hz, r['ticks'], r['done'], r['state'][:24], ' (no inputs hook)' if schedule and not r['inputs'] else ''))
            ctx.close()
        br.close()
    states = {r['state'] for r in runs}
    equal = len(states) == 1 and all(not r['errors'] for r in runs)
    log('state %s across %s Hz' % ('EQUAL' if equal else 'DIFFERS', ', '.join(str(h) for h in hz_list)) + ('' if equal else ': ' + ', '.join('%d Hz %s' % (r['hz'], r['state'][:16]) for r in runs)))
    return {'runs': runs, 'equal': equal, 'reference': runs[0]['state'] if runs else None}
