"""Smoothness of a rebuild's page as the canon measures it (docs/WB-PLYNULOST.md, module F): dropped display
frames, the evenness of the camera's and the objects' steps between display frames, missing interpolation
passes, the key-to-camera latency and sound dropouts under artificial stalls of the main thread - in Chromium
and WebKit (Playwright), each limit passed or failed.

The page provides ``globalThis.WBLONGRUN`` (1.1; ``arek web longrun`` reads the same):
  ready() -> bool; cam() -> [x, y] the camera in game pixels as drawn in this display frame (fractional when
  interpolated); objs() -> [[id, x, y], ...] the objects on screen with an identity, game pixels as drawn (optional);
  missing() -> display frames drawn without the next game frame / pass for the interpolation, so far (optional);
  ahead() -> game frames computed ahead of the display (optional); audio() -> {reserve: ms, dropouts: n, latency: ms,
  simulated?: bool} (optional); status() -> text (optional); keys: {left, right} the key codes that move the camera
  (default ArrowLeft / ArrowRight).

    arek web smooth http://127.0.0.1:8920/smooth-demo.html [--seconds 30] [--browser chromium|webkit|all] [--json]

Limits (the canon, A): 0 dropped frames in the run; the camera's and the objects' step deviation < 0.05 game px
(a step judged per nominal display interval, so the display's own timing jitter does not count); 0 % missing
passes; key -> camera latency (median of 5) <= 70 ms; 0 sound dropouts over 10 stalls of 150 ms.
"""
import json
import statistics

LIMITS = {'dropped': 0, 'cam_dev': 0.05, 'obj_dev': 0.05, 'missing_pct': 0.0, 'latency_ms': 70, 'dropouts': 0}
BROWSERS = ('chromium', 'webkit')

SAMPLE_JS = """(ms) => new Promise((res) => { const out = []; const H = globalThis.WBLONGRUN; const t0 = performance.now();
    const f = (ts) => { out.push([ts, H.cam(), H.objs ? H.objs() : null, H.missing ? H.missing() : null, H.ahead ? H.ahead() : null]);
        if (performance.now() - t0 < ms) requestAnimationFrame(f); else res(out); };
    requestAnimationFrame(f); })"""
LATENCY_JS = """([code, maxMs]) => new Promise((res) => { const H = globalThis.WBLONGRUN; const x0 = H.cam()[0];
    const t0 = performance.now();
    const ev = (type) => new KeyboardEvent(type, { key: code.replace('Arrow', ''), code, bubbles: true, cancelable: true });
    window.dispatchEvent(ev('keydown')); document.dispatchEvent(ev('keydown'));
    const f = () => { const dt = performance.now() - t0;
        if (Math.abs(H.cam()[0] - x0) > 0.01) { window.dispatchEvent(ev('keyup')); document.dispatchEvent(ev('keyup')); res(dt); }
        else if (dt > maxMs) { window.dispatchEvent(ev('keyup')); document.dispatchEvent(ev('keyup')); res(null); }
        else requestAnimationFrame(f); };
    requestAnimationFrame(f); })"""
STALL_JS = "(ms) => { const t = performance.now(); while (performance.now() - t < ms) {} return ms; }"


def _dev(steps):
    return statistics.pstdev(steps) if len(steps) > 1 else 0.0


def analyse(samples):
    """``[[ts, cam, objs, missing, ahead], ...]`` of one run -> the metrics."""
    dt = [b[0] - a[0] for a, b in zip(samples, samples[1:])]
    nominal = statistics.median(dt) if dt else 16.7
    dropped = sum(1 for d in dt if d > 1.5 * nominal)
    # a step is judged per nominal display interval (step / dt * nominal): the display's own timing jitter (the
    # requestAnimationFrame timestamps, which a page interpolates by) does not count, an uneven motion does
    norm = [nominal / d if d > 0 else 1.0 for d in dt]
    xs = [s[1][0] for s in samples]
    steps = [(b - a) * k for a, b, k in zip(xs, xs[1:], norm)]
    moving = [s for i, s in enumerate(steps) if abs(s) > 1e-6 and 0 < i < len(steps) - 1 and abs(steps[i - 1]) > 1e-6 and abs(steps[i + 1]) > 1e-6]
    cam_dev = _dev(moving)
    obj_dev = 0.0
    if samples and samples[0][2] is not None:
        tracks = {}
        for i, s in enumerate(samples):
            for o in s[2] or []:
                tracks.setdefault(o[0], []).append((i, o[1], o[2]))
        devs = []
        for pts in tracks.values():
            sx = [(b[1] - a[1]) * norm[a[0]] for a, b in zip(pts, pts[1:]) if b[0] == a[0] + 1]
            sy = [(b[2] - a[2]) * norm[a[0]] for a, b in zip(pts, pts[1:]) if b[0] == a[0] + 1]
            if len(sx) > 2:
                devs.append(max(_dev(sx[1:-1]), _dev(sy[1:-1])))
        obj_dev = max(devs) if devs else 0.0
    miss = [s[3] for s in samples if s[3] is not None]
    missing_pct = 100.0 * (miss[-1] - miss[0]) / max(1, len(samples) - 1) if len(miss) > 1 else None
    ahead = [s[4] for s in samples if s[4] is not None]
    return {'frames': len(samples), 'refresh_hz': round(1000.0 / nominal, 1) if nominal else None, 'dropped': dropped,
            'cam_dev': round(cam_dev, 4), 'cam_moving': len(moving), 'obj_dev': round(obj_dev, 4), 'missing_pct': missing_pct,
            'ahead': statistics.median(ahead) if ahead else None}


def verdict(r):
    """The limits applied: ``(passed, fails)``."""
    fails = []
    if r.get('dropped', 0) > LIMITS['dropped']:
        fails.append('dropped frames %d' % r['dropped'])
    if r.get('cam_moving', 0) < 10:
        fails.append('the camera hardly moved (%d steps): hold a key, or set keys' % r.get('cam_moving', 0))
    elif r['cam_dev'] >= LIMITS['cam_dev']:
        fails.append('camera step deviation %.3f px' % r['cam_dev'])
    if r.get('obj_dev', 0) >= LIMITS['obj_dev']:
        fails.append('object step deviation %.3f px' % r['obj_dev'])
    if r.get('missing_pct') is not None and r['missing_pct'] > LIMITS['missing_pct']:
        fails.append('missing passes %.1f %%' % r['missing_pct'])
    if r.get('latency_ms') is None:
        fails.append('no camera move after the key')
    elif r['latency_ms'] > LIMITS['latency_ms']:
        fails.append('key -> camera %.0f ms' % r['latency_ms'])
    a = r.get('audio')
    if a and a.get('dropouts', 0) > LIMITS['dropouts']:
        fails.append('sound dropouts %d' % a['dropouts'])
    return not fails, fails


def measure(page, seconds=30.0, stalls=10, stall_ms=150, reps=5, log=None):
    """The phases on an open page: scroll (the right key held, sampling), latency (the key dispatched in the page),
    stalls (busy loops in the main thread, the sound's counters before and after). Returns the metrics dict."""
    page.wait_for_function('globalThis.WBLONGRUN && (!WBLONGRUN.ready || WBLONGRUN.ready())', timeout=30000)
    keys = page.evaluate("Object.assign({left: 'ArrowLeft', right: 'ArrowRight'}, globalThis.WBLONGRUN.keys || {})")
    page.mouse.click(10, 10)
    page.keyboard.down(keys['right'])
    page.wait_for_timeout(400)
    samples = page.evaluate(SAMPLE_JS, seconds * 1000)
    page.keyboard.up(keys['right'])
    r = analyse(samples)
    page.wait_for_timeout(400)
    lats = []
    for _ in range(reps):
        lat = page.evaluate(LATENCY_JS, [keys['right'], 1000])
        if lat is not None:
            lats.append(lat)
        page.wait_for_timeout(400)
    r['latency_ms'] = round(statistics.median(lats), 1) if lats else None
    r['latency_all'] = [round(x, 1) for x in lats]
    if page.evaluate('typeof globalThis.WBLONGRUN.audio === "function"'):
        a0 = page.evaluate('globalThis.WBLONGRUN.audio()')
        for _ in range(stalls):
            page.evaluate(STALL_JS, stall_ms)
            page.wait_for_timeout(600)
        a1 = page.evaluate('globalThis.WBLONGRUN.audio()')
        r['audio'] = {'reserve_ms': a1.get('reserve'), 'latency_ms': a1.get('latency'), 'dropouts': (a1.get('dropouts') or 0) - (a0.get('dropouts') or 0),
                      'stalls': '%d x %d ms' % (stalls, stall_ms), 'simulated': bool(a1.get('simulated'))}
    else:
        r['audio'] = None
    r['status'] = page.evaluate('globalThis.WBLONGRUN.status ? String(WBLONGRUN.status()) : ""')
    r['passed'], r['fails'] = verdict(r)
    return r


def run(url, seconds=30.0, browsers=BROWSERS, stalls=10, stall_ms=150, log=print, viewport=(1280, 800)):
    """The measurement in every browser of ``browsers`` that is installed: ``{browser: metrics}``."""
    from playwright.sync_api import sync_playwright
    out = {}
    with sync_playwright() as pw:
        for name in browsers:
            try:
                br = getattr(pw, name).launch()
            except Exception as e:                      # not installed: say so, go on
                out[name] = {'error': str(e).splitlines()[0][:160]}
                log('%s: not available (%s)' % (name, out[name]['error']))
                continue
            page = br.new_page(viewport={'width': viewport[0], 'height': viewport[1]})
            page.goto(url)
            try:
                out[name] = measure(page, seconds, stalls, stall_ms)
            finally:
                br.close()
            log(format_result(name, out[name]))
    return out


def format_result(name, r):
    if 'error' in r:
        return '%s: %s' % (name, r['error'])
    a = r.get('audio')
    fmt = lambda v: ('%.0f' % v) if isinstance(v, (int, float)) else str(v)
    aud = ('sound reserve %s ms, latency %s ms, dropouts %d over %s%s' % (fmt(a['reserve_ms']), fmt(a['latency_ms']), a['dropouts'], a['stalls'], ' (simulated by the page)' if a['simulated'] else '')) if a else 'no sound hook'
    return ('%s: %s - %d frames at %s Hz, %d dropped; camera step deviation %.3f px (%d steps), objects %.3f px, missing passes %s; '
            'key -> camera %s ms %s; %s; %s' % (
                name, 'PASSED' if r['passed'] else 'FAILED', r['frames'], r['refresh_hz'], r['dropped'], r['cam_dev'], r['cam_moving'], r['obj_dev'],
                '%.1f %%' % r['missing_pct'] if r['missing_pct'] is not None else 'n/a', r['latency_ms'], r['latency_all'], aud,
                ('; '.join(r['fails']) if r['fails'] else 'every limit met') + (' · ' + r['status'] if r.get('status') else '')))
