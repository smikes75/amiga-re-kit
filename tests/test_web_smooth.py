"""`arek web smooth` (the canon's module F): the analysis of sampled frames, the verdict against the limits, and the
measurement on the kit's synthetic page in Chromium (playwright, when installed)."""
import os
import threading

import pytest

from arek import cli, web, websmooth

WEB = os.path.dirname(os.path.abspath(web.__file__))


def _samples(n=120, dt=16.7, step=1.0, jitter=0.0, drop_at=(), obj_step=0.5, missing=0):
    out, t, x, ox = [], 0.0, 0.0, 10.0
    for i in range(n):
        d = dt * (2.2 if i in drop_at else 1)
        t += d
        x += step + (jitter if i % 2 else -jitter)
        ox += obj_step
        out.append([t, [x, 0], [[1, ox, 5.0], [2, 100 - ox, 7.0]], missing * (i // 10), 1])
    return out


def test_analysis_and_verdict():
    r = websmooth.analyse(_samples())
    assert r['frames'] == 120 and r['dropped'] == 0 and r['cam_jitter'] == 0 and r['obj_jitter'] == 0 and r['missing_pct'] == 0 and r['ahead'] == 1
    assert abs(r['refresh_hz'] - 59.9) < 0.2
    r['latency_ms'], r['audio'] = 40, {'dropouts': 0}
    assert websmooth.verdict(r) == (True, [])
    r = websmooth.analyse(_samples(drop_at=(30, 70), jitter=0.4, missing=1))
    assert r['dropped'] == 2 and r['cam_jitter'] > 0.3 and r['missing_pct'] > 0
    r['latency_ms'], r['audio'] = 90, {'dropouts': 3}
    ok, fails = websmooth.verdict(r)
    assert not ok and len(fails) == 6 and any('90 ms' in f for f in fails) and any('dropouts 3' in f for f in fails)   # objects on a jittery camera jitter too
    r = websmooth.analyse(_samples(step=0.0))
    r['latency_ms'], r['audio'], r['latency_all'] = None, None, []
    ok, fails = websmooth.verdict(r)
    r['passed'], r['fails'] = ok, fails
    assert not ok and any('hardly moved' in f for f in fails) and any('no camera move' in f for f in fails)
    assert 'FAILED' in websmooth.format_result('chromium', r) and 'no sound hook' in websmooth.format_result('chromium', r)
    assert 'not available' not in websmooth.format_result('x', {'error': 'gone'}) and 'gone' in websmooth.format_result('x', {'error': 'gone'})


def _run(isolated, page='smooth-demo.html', **kw):
    srv = web.serve(WEB, 0, isolated=isolated)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        return websmooth.run('http://127.0.0.1:%d/%s' % (port, page), browsers=('chromium',), log=lambda *a: None, **kw)['chromium']
    finally:
        srv.shutdown()


def test_measure_the_synthetic_page_in_chromium():
    """With COOP/COEP the page's sound runs over shared memory from a worker: stalls of the main thread leave it alone."""
    pytest.importorskip('playwright')
    r = _run(True, seconds=3, stalls=3, stall_ms=150)
    assert 'error' not in r, r
    assert r['frames'] > 100 and r['cam_moving'] > 50 and r['latency_ms'] is not None
    assert r['audio'] and not r['audio']['simulated'] and r['audio']['dropouts'] == 0 and r['audio']['reserve_ms'] > 10, r['audio']
    assert r['passed'], r['fails']


def test_messages_mode_runs_dry_under_stalls():
    """Without shared memory the page feeds the sound by messages: a 150 ms stall is longer than the 50 ms reserve."""
    pytest.importorskip('playwright')
    r = _run(False, seconds=2, stalls=3, stall_ms=150)
    assert 'error' not in r, r
    assert r['audio'] and not r['audio']['simulated'] and r['audio']['dropouts'] >= 1 and not r['passed']
    assert any('dropouts' in f for f in r['fails'])


def test_cli_smooth_needs_a_url():
    assert cli.main(['web', 'smooth']) != 0


def test_a_change_of_speed_is_no_jitter():
    """G43 (Alien Breed II): a camera at 1.66 px per display frame, then 0.83 (catching up with the player) has a speed
    deviation of 0.415 px but no jitter; a single uneven step is jitter."""
    steps = [1.66] * 60 + [0.83] * 60
    assert abs(websmooth._dev(steps) - 0.415) < 1e-9 and websmooth.jitter(steps) == (0.0, 0.0)
    bumpy = [1.0] * 30
    bumpy[15] = 1.5
    m, x = websmooth.jitter(bumpy)
    assert x == 0.5 and 0 < m < 0.05
    assert websmooth.jitter([1.4, 0.6] * 20)[0] > 0.7                            # alternating steps are jitter
    t, x0, samples = 0.0, 0.0, []
    for st in [0.0] * 5 + [1.66] * 60 + [0.0] * 3 + [0.83] * 60:                     # a stop between the stretches
        t += 16.7
        x0 += st
        samples.append([t, [x0, 0], None, None, None])
    r = websmooth.analyse(samples)
    assert r['cam_dev'] > 0.4 and r['cam_jitter'] == 0 and r['cam_moving'] == 120


def test_objects_judged_on_the_screen():
    """G44 (Alien Breed II): the camera scrolls 1.66 px per frame (fractional), the objects are drawn on whole device
    pixels (S = 2): one standing on the terrain and one walking 0.5 px per frame have steps on the screen within 1/S of
    each other - no jitter; an animation frame's 3 px offset is a jump, not jitter; without the scale they jitter."""
    t, cam, samples = 0.0, 0.0, []
    for i in range(120):
        t += 16.7
        cam -= 1.66
        drawn = lambda wx: round((wx - cam) * 2) / 2 + cam                            # where it is drawn, as world x
        oy = 50.0 + (3.0 if (i // 30) % 2 else 0.0)                                   # animation: 3 px every 30 frames
        samples.append([t, [cam, 0.0], [[7, drawn(100.0), oy], [8, drawn(140.0 + 0.5 * i), 60.0]], 0, 0])
    r = websmooth.analyse(samples, scale=2)
    assert r['obj_jitter'] == 0 and r['cam_jitter'] < 1e-6
    assert websmooth.analyse(samples)['obj_jitter'] > 0.05


def test_gaps_outside_the_game_are_not_judged():
    """1.2 (Alien Breed II): a map fly-over after a death (ready() false) is a gap: no dropped frame, no step across it."""
    t, x, samples = 0.0, 0.0, []
    for i in range(100):
        t += 16.7
        if 40 <= i < 70:
            if samples[-1] is not None:
                samples.append(None)
            x += 50.0                                                                 # the camera jumps meanwhile
            continue
        x += 1.0
        samples.append([t, [x, 0.0], None, 3, 1])
    r = websmooth.analyse(samples)
    assert r['gaps'] == 1 and r['frames'] == 70 and r['dropped'] == 0 and r['cam_jitter'] == 0 and r['missing_pct'] == 0


def test_renderer_load_and_gpu_flags():
    assert websmooth.load_average() is None or websmooth.load_average() >= 0
    assert '--use-angle=metal' in websmooth.GPU_ARGS['chromium'] and 'UNMASKED_RENDERER_WEBGL' in websmooth.RENDERER_JS
    r = {'passed': True, 'fails': [], 'frames': 10, 'refresh_hz': 60, 'dropped': 0, 'cam_jitter': 0, 'cam_jitter_max': 0, 'cam_moving': 9,
         'cam_dev': 0, 'obj_jitter': 0, 'missing_pct': 0, 'latency_ms': 40, 'latency_all': [40], 'audio': None,
         'renderer': 'ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device))', 'load': [1.0, 1.5], 'notes': ['WebGL drawn in software']}
    line = websmooth.format_result('chromium', r)
    assert 'SwiftShader' in line and 'load 1.0 -> 1.5' in line and 'software' in line


def test_without_interpolation_jitter_is_reported_not_judged():
    """1.4 (Superfrog KIT-GAPS 38): an original mode draws a 50 Hz game's frames as they are - on a 60 Hz display every
    sixth display frame repeats the last game frame. The camera's 0 step ends a stretch of motion (its stretches are
    even), but an object moving on the screen steps 1 1 1 1 1 0 - jitter. With interp false the jitter and the missing
    passes are reported only; dropped frames, the latency and the sound still fail."""
    steps = [0.0 if i % 6 == 5 else 2.0 for i in range(120)]
    t, x, smp = 0.0, 0.0, []
    for i, st in enumerate(steps):
        t += 16.7
        x += st
        smp.append([t, [x, 0], [[1, 1.5 * x + 10, 5.0]], i // 4, 1])      # the object runs 1 px per game frame on the screen
    r = websmooth.analyse(smp)
    assert r['cam_jitter'] == 0 and r['obj_jitter'] > 0.1 and r['missing_pct'] > 0
    snd = {'reserve_ms': 30, 'latency_ms': 20, 'dropouts': 0, 'stalls': '10 x 150 ms', 'simulated': False}
    r.update(latency_ms=40, latency_all=[40], audio=snd)
    ok, fails = websmooth.verdict(r)
    assert not ok and any('object jitter' in f for f in fails) and any('missing' in f for f in fails)
    r['interp'] = False
    assert websmooth.verdict(r) == (True, [])
    r['passed'], r['fails'] = True, []
    assert 'not judged: no interpolation' in websmooth.format_result('chromium', r)
    r.update(dropped=3, latency_ms=95, audio=dict(snd, dropouts=2))
    ok, fails = websmooth.verdict(r)
    assert not ok and len(fails) == 3 and not any('jitter' in f or 'missing' in f for f in fails)


def test_cli_smooth_has_no_interp():
    assert cli.build_parser().parse_args(['web', 'smooth', 'http://x/', '--no-interp']).no_interp
    assert not cli.build_parser().parse_args(['web', 'smooth', 'http://x/']).no_interp


def test_measure_the_synthetic_page_without_interpolation():
    """The synthetic page with ?interp=0 says so by the hook: its objects' 50-on-60 steps on the screen are jitter,
    reported and not judged; the same page interpolating meets the limit."""
    pytest.importorskip('playwright')
    r = _run(True, page='smooth-demo.html?interp=0', seconds=3, stalls=2, stall_ms=100)
    assert 'error' not in r, r
    assert r['interp'] is False and r['obj_jitter'] > LIM, (r['obj_jitter'], r['fails'])
    assert not any('jitter' in f or 'missing' in f for f in r['fails']), r['fails']
    r2 = _run(True, seconds=3, stalls=2, stall_ms=100)
    assert r2['interp'] is True and r2['obj_jitter'] < LIM and r2['cam_jitter'] < LIM, (r2['obj_jitter'], r2['cam_jitter'])


LIM = websmooth.LIMITS['cam_jitter']
