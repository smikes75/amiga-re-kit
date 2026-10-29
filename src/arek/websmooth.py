"""Smoothness of a rebuild's page as the canon measures it (docs/WB-PLYNULOST.md, module F): dropped display
frames, the evenness of the camera's and the objects' steps between display frames, missing interpolation
passes, the key-to-camera latency and sound dropouts under artificial stalls of the main thread - in Chromium
and WebKit (Playwright), each limit passed or failed.

The page provides ``globalThis.WBLONGRUN`` (1.1; ``arek web longrun`` reads the same):
  ready() -> bool; cam() -> [x, y] the camera in game pixels in this display frame (fractional when interpolated);
  objs() -> [[id, x, y], ...] the objects on screen with an identity, in the world in game pixels so that
  x - cam()[0] is where the object is drawn on the screen (optional; 1.2, G44: objects are judged on the screen);
  scale() -> S, device pixels per game pixel, when the page draws on whole device pixels (optional, 1.2: an object's
  steps on the screen are then judged within 1/S);
  missing() -> display frames drawn without the next game frame / pass for the interpolation, so far (optional);
  ahead() -> game frames computed ahead of the display (optional); audio() -> {reserve: ms, dropouts: n, latency: ms,
  simulated?: bool} (optional); status() -> text (optional); keys: {left, right} the key codes that move the camera
  (default ArrowLeft / ArrowRight).

    arek web smooth http://127.0.0.1:8920/smooth-demo.html [--seconds 30] [--browser chromium|webkit|all] [--json]

Limits (the canon, A): 0 dropped frames in the run; the camera's and the objects' jitter < 0.05 game px - the mean
deviation of a step from the median of the 3 steps around it within a moving stretch (1.1, G43: a change of speed
is not jitter; a step is judged per nominal display interval, so the display's own timing jitter does not count);
0 % missing passes; key -> camera latency (median of 5, left and right in turn) <= 70 ms; 0 sound dropouts over 10
stalls of 150 ms. More hooks (1.1): focus (a selector or [x, y] to click into the game; default the largest canvas),
prepare() (brings the page into the game, may return a promise), route ([[key, ms], ...] cycled while sampling).
1.2: while ready() is false (a map fly-over after a death, a menu) nothing is sampled or judged, and a latency probe
waits for it (up to 10 s) or is void and repeated (up to 10 more).
"""
import json
import statistics

LIMITS = {'dropped': 0, 'cam_jitter': 0.05, 'obj_jitter': 0.05, 'missing_pct': 0.0, 'latency_ms': 70, 'dropouts': 0}
BROWSERS = ('chromium', 'webkit')
OBJ_JUMP = 1.0                     # game px: a larger step of an object against the screen is a jump (animation, a new place), not jitter

SAMPLE_START_JS = """() => { const H = globalThis.WBLONGRUN; const S = globalThis.__wbSmooth = { out: [], on: true };
    const f = (ts) => { if (!S.on) return;
        if (H.ready && !H.ready()) { if (S.out.length && S.out[S.out.length - 1] !== null) S.out.push(null); }   // 1.2: outside the game - a gap
        else S.out.push([ts, H.cam(), H.objs ? H.objs() : null, H.missing ? H.missing() : null, H.ahead ? H.ahead() : null]);
        requestAnimationFrame(f); };
    requestAnimationFrame(f); return true; }"""
SAMPLE_STOP_JS = "() => { const S = globalThis.__wbSmooth; S.on = false; return S.out; }"
FOCUS_JS = """() => { const H = globalThis.WBLONGRUN, f = H.focus; let el = null;
    if (Array.isArray(f)) return f;
    if (typeof f === 'string') el = document.querySelector(f);
    if (!el) { let best = 0; for (const c of document.querySelectorAll('canvas')) { const r = c.getBoundingClientRect(); if (r.width * r.height > best) { best = r.width * r.height; el = c; } } }
    if (!el) return [10, 10];
    const r = el.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; }"""
LATENCY_JS = """([code, maxMs]) => new Promise((res) => { const H = globalThis.WBLONGRUN; const x0 = H.cam()[0];
    const out = () => H.ready && !H.ready();
    const t0 = performance.now();
    const ev = (type) => new KeyboardEvent(type, { key: code.replace('Arrow', ''), code, bubbles: true, cancelable: true });
    window.dispatchEvent(ev('keydown')); document.dispatchEvent(ev('keydown'));
    const f = () => { const dt = performance.now() - t0;
        if (out()) { window.dispatchEvent(ev('keyup')); document.dispatchEvent(ev('keyup')); res(-1); }   // the game left the screen: void
        else if (Math.abs(H.cam()[0] - x0) > 0.01) { window.dispatchEvent(ev('keyup')); document.dispatchEvent(ev('keyup')); res(dt); }
        else if (dt > maxMs) { window.dispatchEvent(ev('keyup')); document.dispatchEvent(ev('keyup')); res(null); }
        else requestAnimationFrame(f); };
    requestAnimationFrame(f); })"""
STALL_JS = "(ms) => { const t = performance.now(); while (performance.now() - t < ms) {} return ms; }"


def _dev(steps):
    return statistics.pstdev(steps) if len(steps) > 1 else 0.0


def jitter(steps, window=3, jump=None, grid=0.0):
    """The jitter of a series of steps (1.1, G43): the deviation of every step from the median of the ``window`` steps
    around it - an even motion that changes its speed (a camera catching up with the player, an alien turning) is no
    jitter, a single uneven step is, and so is a step pattern that alternates (1.4 0.6 1.4 ...; a median of 5 would
    hide it). Returns ``(mean, max)`` of the absolute deviations."""
    h = window // 2
    devs = [abs(steps[i] - statistics.median(steps[i - h:i + h + 1])) for i in range(h, len(steps) - h)]
    if jump is not None:                                  # 1.2 (G44): a jump (an animation frame's offset) is no jitter
        devs = [d for d in devs if d <= jump]
    if grid:                                              # 1.2 (G44): drawn on whole device pixels, a step is off by up to 1/S
        devs = [max(0.0, d - grid - 1e-9) for d in devs]
    return (statistics.fmean(devs), max(devs)) if devs else (0.0, 0.0)


def analyse(samples, scale=None):
    """``[[ts, cam, objs, missing, ahead], ...]`` of one run -> the metrics; ``scale``: S, device px per game px, when
    the page draws its objects on whole device pixels (their steps on the screen are then judged within 1/S)."""
    # 1.2: None marks a gap - the page's ready() was false (a map fly-over after a death, a menu); nothing is
    # judged across it
    pairs = [(i, a, b) for i, (a, b) in enumerate(zip(samples, samples[1:])) if a is not None and b is not None]
    gaps = sum(1 for s in samples if s is None)
    samples_in = [s for s in samples if s is not None]
    dts = [b[0] - a[0] for _, a, b in pairs]
    nominal = statistics.median(dts) if dts else 16.7
    dropped = sum(1 for d in dts if d > 1.5 * nominal)
    # a step is judged per nominal display interval (step / dt * nominal): the display's own timing jitter (the
    # requestAnimationFrame timestamps, which a page interpolates by) does not count, an uneven motion does
    norm = {i: (nominal / (b[0] - a[0]) if b[0] > a[0] else 1.0) for i, a, b in pairs}
    steps, last = [], None
    for i, a, b in pairs:
        if last is not None and i != last + 1:
            steps.append(0.0)                             # a gap ends a stretch of motion
        steps.append((b[1][0] - a[1][0]) * norm[i])
        last = i
    # the camera's moving stretches (a stop - a wall, the map's edge, a key let go - ends a stretch); the jitter is
    # judged within the stretches
    runs, cur = [], []
    for st in steps:
        if abs(st) > 1e-6:
            cur.append(st)
        else:
            if len(cur) >= 5:
                runs.append(cur)
            cur = []
    if len(cur) >= 5:
        runs.append(cur)
    moving = [st for r in runs for st in r]
    cam_dev = _dev(moving)
    jm = [jitter(r) for r in runs]
    cam_jit = max((m for m, _ in jm), default=0.0)
    cam_jit_max = max((x for _, x in jm), default=0.0)
    obj_dev = obj_jit = 0.0
    if samples_in and samples_in[0][2] is not None:
        # 1.2 (G44): an object is judged on the screen (its world position less the camera): its steps there are within
        # 1/S of each other when the page draws on whole device pixels (scale), a step over OBJ_JUMP game px (an
        # animation frame's offset, an object placed anew) is left out of the jitter
        tracks = {}
        for i, s in enumerate(samples):
            if s is None:
                continue
            cx, cy = s[1][0], s[1][1]
            for o in s[2] or []:
                tracks.setdefault(o[0], []).append((i, o[1] - cx, o[2] - cy))
        devs, jits = [], []
        for pts in tracks.values():
            sx = [(b[1] - a[1]) * norm[a[0]] for a, b in zip(pts, pts[1:]) if b[0] == a[0] + 1]
            sy = [(b[2] - a[2]) * norm[a[0]] for a, b in zip(pts, pts[1:]) if b[0] == a[0] + 1]
            if len(sx) > 6:
                devs.append(max(_dev(sx[1:-1]), _dev(sy[1:-1])))
                g = 1.0 / scale if scale else 0.0
                jits.append(max(jitter(sx, jump=OBJ_JUMP, grid=g)[0], jitter(sy, jump=OBJ_JUMP, grid=g)[0]))
        obj_dev = max(devs) if devs else 0.0
        obj_jit = max(jits) if jits else 0.0
    miss = [s[3] for s in samples_in if s[3] is not None]
    missing_pct = 100.0 * (miss[-1] - miss[0]) / max(1, len(samples_in) - 1) if len(miss) > 1 else None
    ahead = [s[4] for s in samples_in if s[4] is not None]
    return {'frames': len(samples_in), 'gaps': gaps, 'refresh_hz': round(1000.0 / nominal, 1) if nominal else None, 'dropped': dropped,
            'cam_dev': round(cam_dev, 4), 'cam_jitter': round(cam_jit, 4), 'cam_jitter_max': round(cam_jit_max, 4), 'cam_moving': len(moving),
            'obj_dev': round(obj_dev, 4), 'obj_jitter': round(obj_jit, 4), 'missing_pct': missing_pct,
            'ahead': statistics.median(ahead) if ahead else None}


def verdict(r):
    """The limits applied: ``(passed, fails)``."""
    fails = []
    if r.get('dropped', 0) > LIMITS['dropped']:
        fails.append('dropped frames %d' % r['dropped'])
    if r.get('cam_moving', 0) < 10:
        fails.append('the camera hardly moved (%d steps): hold a key, or set keys' % r.get('cam_moving', 0))
    elif r['cam_jitter'] >= LIMITS['cam_jitter']:
        fails.append('camera jitter %.3f px' % r['cam_jitter'])
    if r.get('obj_jitter', 0) >= LIMITS['obj_jitter']:
        fails.append('object jitter %.3f px' % r['obj_jitter'])
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
    """The phases on an open page: (1.1) focus - a click into the game (``WBLONGRUN.focus``: a selector or [x, y],
    default the largest canvas; G41), prepare - ``WBLONGRUN.prepare()`` brings the page into the game and resolves
    when it is there (a promise or a value; G42); scroll - the keys of ``WBLONGRUN.route`` ([[key, ms], ...], cycled;
    default the right key for the whole run) held in turn while every display frame is sampled; latency - key presses
    dispatched in the page, alternating left and right; stalls - busy loops in the main thread, the sound's counters
    before and after. Returns the metrics dict."""
    page.wait_for_function('globalThis.WBLONGRUN', timeout=30000)
    if page.evaluate('typeof globalThis.WBLONGRUN.prepare === "function"'):
        page.evaluate('async () => { await globalThis.WBLONGRUN.prepare(); return true; }')
    page.wait_for_function('!WBLONGRUN.ready || WBLONGRUN.ready()', timeout=120000)
    keys = page.evaluate("Object.assign({left: 'ArrowLeft', right: 'ArrowRight'}, globalThis.WBLONGRUN.keys || {})")
    x, y = page.evaluate(FOCUS_JS)
    page.mouse.click(x, y)
    route = page.evaluate('globalThis.WBLONGRUN.route || null') or [[keys['right'], seconds * 1000]]
    page.wait_for_timeout(200)
    page.evaluate(SAMPLE_START_JS)
    left, i, held = seconds * 1000.0, 0, None
    while left > 0:
        key, ms = route[i % len(route)]
        ms = min(float(ms), left)
        if held:
            page.keyboard.up(held)
        held = key
        page.keyboard.down(key)
        page.wait_for_timeout(ms)
        left -= ms
        i += 1
    if held:
        page.keyboard.up(held)
    samples = page.evaluate(SAMPLE_STOP_JS)
    r = analyse(samples, page.evaluate('globalThis.WBLONGRUN.scale ? WBLONGRUN.scale() : null'))
    page.wait_for_timeout(400)
    lats, void = [], 0
    for k in range(reps + 10):                            # 1.2: a probe outside the game does not count; up to 10 more
        if len(lats) >= reps:
            break
        try:                                              # wait until the page is in the game again (10 s)
            page.wait_for_function('!WBLONGRUN.ready || WBLONGRUN.ready()', timeout=10000)
        except Exception:
            void += 1
            continue
        lat = page.evaluate(LATENCY_JS, [keys['right'] if k % 2 == 0 else keys['left'], 1000])
        if lat is not None and lat >= 0:
            lats.append(lat)
        elif lat is not None:
            void += 1
        page.wait_for_timeout(400)
    r['latency_void'] = void
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


RENDERER_JS = """() => { try { const c = document.createElement('canvas'), g = c.getContext('webgl2') || c.getContext('webgl');
    if (!g) return 'no WebGL'; const e = g.getExtension('WEBGL_debug_renderer_info');
    return String(e ? g.getParameter(e.UNMASKED_RENDERER_WEBGL) : g.getParameter(g.RENDERER)); } catch (x) { return 'unknown'; } }"""
GPU_ARGS = {'chromium': ['--use-angle=metal', '--enable-gpu', '--ignore-gpu-blocklist']}   # 1.3 (G45): the Mac's GPU, not SwiftShader


def load_average():
    """The machine's 1-minute load average, None where the platform has none (1.3, G45: a loaded machine drops frames)."""
    import os
    try:
        return round(os.getloadavg()[0], 2)
    except (AttributeError, OSError):
        return None


def run(url, seconds=30.0, browsers=BROWSERS, stalls=10, stall_ms=150, log=print, viewport=(1280, 800), gpu=False):
    """The measurement in every browser of ``browsers`` that is installed: ``{browser: metrics}``. Every result carries
    the WebGL renderer (headless Chromium draws WebGL in software, SwiftShader) and the load average before and after;
    ``gpu``: launch Chromium on the GPU (``GPU_ARGS``; macOS: ANGLE on Metal)."""
    from playwright.sync_api import sync_playwright
    out = {}
    with sync_playwright() as pw:
        for name in browsers:
            try:
                br = getattr(pw, name).launch(args=GPU_ARGS.get(name, []) if gpu else [])
            except Exception as e:                      # not installed: say so, go on
                out[name] = {'error': str(e).splitlines()[0][:160]}
                log('%s: not available (%s)' % (name, out[name]['error']))
                continue
            page = br.new_page(viewport={'width': viewport[0], 'height': viewport[1]})
            page.goto(url)
            la0 = load_average()
            try:
                out[name] = measure(page, seconds, stalls, stall_ms)
                out[name]['renderer'] = page.evaluate(RENDERER_JS)
                out[name]['load'] = [la0, load_average()]
                if 'swiftshader' in out[name]['renderer'].lower():
                    out[name]['notes'] = ['WebGL drawn in software (SwiftShader): the presenter runs on the CPU here; --gpu measures the GPU']
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
    return ('%s: %s - %d frames at %s Hz, %d dropped; camera jitter %.3f px (max %.3f; %d steps, speed deviation %.3f), objects jitter %.3f px, missing passes %s; '
            'key -> camera %s ms %s; %s; %s' % (
                name, 'PASSED' if r['passed'] else 'FAILED', r['frames'], r['refresh_hz'], r['dropped'], r['cam_jitter'], r['cam_jitter_max'], r['cam_moving'], r['cam_dev'], r['obj_jitter'],
                '%.1f %%' % r['missing_pct'] if r['missing_pct'] is not None else 'n/a', r['latency_ms'], r['latency_all'], aud,
                ('; '.join(r['fails']) if r['fails'] else 'every limit met') + (' · ' + r['status'] if r.get('status') else '')
                + (' · WebGL %s' % r['renderer'] if r.get('renderer') else '') + (' · load %s -> %s' % tuple(r['load']) if r.get('load') else '')
                + ''.join(' · ' + n for n in r.get('notes', []))))
