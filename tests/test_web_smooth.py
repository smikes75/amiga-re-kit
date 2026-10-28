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
    assert r['frames'] == 120 and r['dropped'] == 0 and r['cam_dev'] == 0 and r['obj_dev'] == 0 and r['missing_pct'] == 0 and r['ahead'] == 1
    assert abs(r['refresh_hz'] - 59.9) < 0.2
    r['latency_ms'], r['audio'] = 40, {'dropouts': 0}
    assert websmooth.verdict(r) == (True, [])
    r = websmooth.analyse(_samples(drop_at=(30, 70), jitter=0.4, missing=1))
    assert r['dropped'] == 2 and r['cam_dev'] > 0.3 and r['missing_pct'] > 0
    r['latency_ms'], r['audio'] = 90, {'dropouts': 3}
    ok, fails = websmooth.verdict(r)
    assert not ok and len(fails) == 5 and any('90 ms' in f for f in fails) and any('dropouts 3' in f for f in fails)
    r = websmooth.analyse(_samples(step=0.0))
    r['latency_ms'], r['audio'], r['latency_all'] = None, None, []
    ok, fails = websmooth.verdict(r)
    r['passed'], r['fails'] = ok, fails
    assert not ok and any('hardly moved' in f for f in fails) and any('no camera move' in f for f in fails)
    assert 'FAILED' in websmooth.format_result('chromium', r) and 'no sound hook' in websmooth.format_result('chromium', r)
    assert 'not available' not in websmooth.format_result('x', {'error': 'gone'}) and 'gone' in websmooth.format_result('x', {'error': 'gone'})


def _run(isolated, **kw):
    srv = web.serve(WEB, 0, isolated=isolated)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        return websmooth.run('http://127.0.0.1:%d/smooth-demo.html' % port, browsers=('chromium',), log=lambda *a: None, **kw)['chromium']
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
