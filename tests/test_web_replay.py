"""`arek web replay` (module H): a page under a virtual clock at several display rates with the same inputs by game
frame must end in the same game state - the display never touches the game. The synthetic scene page in Chromium,
and the route parser and the clock on their own."""
import threading
from pathlib import Path

import pytest

from arek import cli, web, webreplay

WEB = Path(web.__file__).parent


def test_route_and_hz_parsing():
    assert webreplay.parse_route('1:120,2:60,0:120') == [[0, 1], [120, 2], [180, 0]]
    assert webreplay.parse_route('') == [] and webreplay.parse_route(None) == []
    assert cli.build_parser().parse_args(['web', 'replay', 'http://x/', '--hz', '50,144', '--frames', '10']).hz == '50,144'
    assert cli.main(['web', 'replay']) != 0


def _serve():
    srv = web.serve(str(WEB), 0, isolated=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def test_virtual_clock_drives_the_page():
    """The clock replaces requestAnimationFrame and performance.now before the page's scripts; a tick runs the
    callbacks with the virtual timestamp, and nothing moves between ticks."""
    pytest.importorskip('playwright')
    from playwright.sync_api import sync_playwright
    srv, port = _serve()
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            ctx = b.new_context()
            ctx.add_init_script(webreplay.CLOCK_JS)
            p = ctx.new_page()
            p.goto('http://127.0.0.1:%d/scene-demo.html?s=1' % port)
            p.wait_for_function('globalThis.WBLONGRUN')
            d0 = p.evaluate('WBLONGRUN.done()')
            p.wait_for_timeout(300)
            assert p.evaluate('WBLONGRUN.done()') == d0 and p.evaluate('performance.now()') == 0      # real time passes, the page does not move
            for _ in range(12):
                p.evaluate('__wbClock.tick(1000 / 60)')
            assert p.evaluate('performance.now()') == pytest.approx(200, abs=1e-6)
            assert p.evaluate('WBLONGRUN.done()') > d0 and p.evaluate('WBLONGRUN.ready()')
            b.close()
    finally:
        srv.shutdown()


def test_same_state_at_every_display_rate():
    """300 game frames with the right key, the left key and nothing, at 50 / 60 / 120 / 144 Hz: the same state."""
    pytest.importorskip('playwright')
    srv, port = _serve()
    try:
        r = webreplay.run('http://127.0.0.1:%d/scene-demo.html?s=2&pair=2&mean=1' % port, (50, 60, 120, 144), 300, '1:120,2:60,0:120', log=lambda *a: None)
    finally:
        srv.shutdown()
    assert r['equal'], r['runs']
    ticks = [x['ticks'] for x in r['runs']]
    assert ticks[0] < ticks[1] < ticks[2] < ticks[3] and all(x['done'] >= 300 for x in r['runs']) and all(x['inputs'] for x in r['runs'])
    assert all(not x['errors'] for x in r['runs'])
    # the inputs did something: without the route the state differs
    srv, port = _serve()
    try:
        r2 = webreplay.run('http://127.0.0.1:%d/scene-demo.html?s=2' % port, (60,), 300, None, log=lambda *a: None)
    finally:
        srv.shutdown()
    assert r2['equal'] and r2['reference'] != r['reference']
