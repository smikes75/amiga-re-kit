"""1.0.41 (the audit of 2026-11-10): what happens to a page outside the pixel-exact core - a lost WebGL context, a
canvas resized by the stylesheet, shared memory on the 2D path, keys behind the page's back, the caller's sound
buffer, an older frame's sprite, and what `arek web copy` leaves in a game's folder."""
import json
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

from arek import cli, web, webtest

WEB = Path(web.__file__).parent
node = shutil.which('node')


def js(module, expr):
    if not node:
        pytest.skip('no node')
    code = "const M = require(%s); const r = (%s); console.log(JSON.stringify(r));" % (json.dumps(str(WEB / module)), expr)
    return json.loads(subprocess.run([node, '-e', code], capture_output=True, text=True, check=True).stdout)


# ------------------------------------------------------------------ keys
KB = """(() => { const H = {}, W = {}, D = {};
    globalThis.window = { addEventListener: (k, f) => { W[k] = f; }, removeEventListener: () => {} };
    globalThis.document = { hidden: false, addEventListener: (k, f) => { D[k] = f; }, removeEventListener: () => {} };
    const target = { addEventListener: (k, f) => { H[k] = f; }, removeEventListener: () => {} };
    const seen = [], prevented = []; const kb = M.keyboard(target, { ArrowRight: 1, KeyR: 2 }, (b) => seen.push(b));
    const ev = (code, mod) => Object.assign({ code, key: code, preventDefault() { prevented.push(code); } }, mod || {});
    %s
    return { seen, prevented, bits: kb.bits() }; })()"""


def test_a_key_with_a_modifier_is_the_browsers():
    r = js('wb-takt.js', KB % "H.keydown(ev('KeyR', { metaKey: true })); H.keydown(ev('KeyR', { ctrlKey: true })); H.keydown(ev('ArrowRight', { altKey: true }));")
    assert r == {'seen': [], 'prevented': [], 'bits': 0}                    # Cmd+R reloads: not taken, not prevented


def test_a_modifier_the_map_names_is_the_games_key():
    """wb-takt 1.6 (kit 1.0.66; SWIV, Xenon 2 and Turrican II map ControlLeft to fire): the keydown of Control itself
    has ctrlKey set and was dropped with the browser's keys - fire by Ctrl never went down. A mapped modifier is the
    game's, and so are the mapped keys pressed while it is held; an unmapped key with it stays the browser's."""
    kb = KB.replace("{ ArrowRight: 1, KeyR: 2 }", "{ ArrowRight: 1, KeyR: 2, ControlLeft: 16, ControlRight: 16 }")
    r = js('wb-takt.js', kb % ("H.keydown(ev('ControlLeft', { ctrlKey: true })); H.keydown(ev('ArrowRight', { ctrlKey: true })); H.keydown(ev('KeyW', { ctrlKey: true }));"
                               "H.keyup(ev('ArrowRight', { ctrlKey: true })); H.keyup(ev('ControlLeft'));"))
    assert r == {'seen': [16, 17, 16, 0], 'prevented': ['ControlLeft', 'ArrowRight'], 'bits': 0}
    r = js('wb-takt.js', kb % "H.keydown(ev('ArrowRight', { metaKey: true })); H.keydown(ev('ArrowRight', { altKey: true }));")
    assert r == {'seen': [], 'prevented': [], 'bits': 0}                    # Cmd and Alt are not in the map: still the browser's


def test_no_key_stays_down_behind_the_pages_back():
    r = js('wb-takt.js', KB % "H.keydown(ev('ArrowRight')); H.keyup({ code: 'MetaLeft', key: 'Meta' });")       # macOS: no keyup while Cmd is held
    assert r['seen'] == [1, 0] and r['bits'] == 0
    r = js('wb-takt.js', KB % "H.keydown(ev('ArrowRight')); W.blur();")                                          # the window's blur (it does not bubble to a canvas)
    assert r['seen'] == [1, 0]
    r = js('wb-takt.js', KB % "H.keydown(ev('ArrowRight')); document.hidden = true; D.visibilitychange();")      # the tab is hidden
    assert r['seen'] == [1, 0]


def test_lifecycle_tells_hide_and_show():
    r = js('wb-takt.js', """(() => { const D = {}; globalThis.document = { hidden: false, addEventListener: (k, f) => { D[k] = f; }, removeEventListener: () => {} };
        const log = []; const lc = M.lifecycle({ onHide: () => log.push('hide'), onShow: (ms) => log.push('show ' + (ms >= 0)) });
        document.hidden = true; D.visibilitychange(); D.visibilitychange(); const h = lc.hidden();
        document.hidden = false; D.visibilitychange(); return [log, h, lc.hidden()]; })()""")
    assert r == [['hide', 'show true'], True, False]


# ------------------------------------------------------------------ sound
def test_push_leaves_the_callers_buffer_alone():
    """wb-zvuk-out 1.1: a view into a larger buffer was transferred with all of it (the page's buffer detached), a view
    into the engine's memory (WebAssembly.Memory) threw DataCloneError - the natural call of an engine without threads."""
    code = """const M = require(%s); (async () => { const sent = [];
        globalThis.AudioWorkletNode = class { constructor() { this.port = { postMessage: (m, t) => { const n = m && m.length; if (t && t.length) structuredClone(m, { transfer: t }); if (n) sent.push(n); } }; } };
        const out = await M.create({ audioWorklet: { addModule: async () => {} } });
        const big = new ArrayBuffer(4096), part = new Int16Array(big, 64, 100); out.push(part);
        const mem = new WebAssembly.Memory({ initial: 1 }), wv = new Int16Array(mem.buffer, 0, 50); out.push(wv);
        const whole = new Int16Array(64); out.push(whole);
        console.log(JSON.stringify([big.byteLength, mem.buffer.byteLength, whole.buffer.byteLength, sent])); })()""" % json.dumps(str(WEB / 'wb-zvuk-out.js'))
    if not node:
        pytest.skip('no node')
    r = json.loads(subprocess.run([node, '-e', code], capture_output=True, text=True, check=True).stdout)
    assert r == [4096, 65536, 0, [100, 50, 64]]          # the part and the wasm view were copied; a whole plain buffer is still transferred


# ------------------------------------------------------------------ the scene
def test_a_sprite_from_an_older_frame_keeps_that_frames_camera():
    """wb-scene 2.11: the camera moves 2 px a frame, a sprite stands in the world at x = 500 and is drawn every other
    frame (pairOlder 2). Its world x must stay 500 across the pair; it took the camera of frame A instead of the frame it
    came from and swung by half the camera step at every blink."""
    r = js('wb-scene.js', """(() => { const win = { w: 320, h: 200, idx: new Uint8Array(64000), pal: new Uint8Array(200 * 128) }, lim = { x0: 0, x1: 2000, y0: 0, y1: 0 };
        const fr = (n, s) => ({ n, t: n * 20, cam: [100 + 2 * n, 0], limits: lim, window: win, sprites: s ? [{ k: 0, h: 8, idx: new Uint8Array(128), x: 500 - (100 + 2 * n), y: 50 }] : [] });
        const frames = [fr(1, true), fr(2, false), fr(3, true)];
        return [40, 45, 50, 55, 60].map((ts) => M.compose(frames, ts, { S: 1, extX: 0, extY: 0 }, { pairOlder: 2 }, null).sprs.map((s) => +s.x.toFixed(3))); })()""")
    assert r == [[500], [500], [500], [500], [500]]


# ------------------------------------------------------------------ arek web copy
def test_web_copy_writes_a_manifest_and_keeps_an_edited_file(tmp_path, capsys):
    d = str(tmp_path)
    assert cli.main(['web', 'copy', d]) == 0
    man = json.loads((tmp_path / 'wb-kit.json').read_text())
    assert man['kit'] and set(man['files']) == set(web.FILES) and man['files']['wb-obraz.js']['version'] == '1.9'
    assert cli.main(['web', 'copy', d, '--check']) == 0 and all(st == 'current' for _, st, _ in web.status(d))
    takt = tmp_path / 'wb-takt.js'
    takt.write_text(takt.read_text() + '\n// the game changed this\n')
    assert dict((n, s) for n, s, _ in web.status(d))['wb-takt.js'] == 'modified'
    assert cli.main(['web', 'copy', d, '--check']) == 1
    capsys.readouterr()
    assert cli.main(['web', 'copy', d]) == 1                                  # was exit 0 and the edit was gone
    assert 'the game changed this' in takt.read_text() and 'EDITED' in capsys.readouterr().out
    assert cli.main(['web', 'copy', d, '--force']) == 0 and 'the game changed this' not in takt.read_text()


def test_web_copy_check_names_a_stale_module(tmp_path):
    d = str(tmp_path)
    assert cli.main(['web', 'copy', d]) == 0
    old = tmp_path / 'wb-seal.js'
    text = old.read_text().replace('amiga-re-kit', 'amiga-re-kit (an older release)', 1)
    old.write_text(text)
    man = json.loads((tmp_path / 'wb-kit.json').read_text())
    man['kit'] = '1.0.30'
    man['files']['wb-seal.js']['sha256'] = web._sha(str(old))               # as an older kit copied it
    (tmp_path / 'wb-kit.json').write_text(json.dumps(man))
    row = [r for r in web.status(d) if r[0] == 'wb-seal.js'][0]
    assert row[1] == 'stale' and '1.0.30' in row[2]
    assert cli.main(['web', 'copy', d]) == 0 and web.status(d)[web.FILES.index('wb-seal.js')][1] == 'current'   # a stale file is simply updated


# ------------------------------------------------------------------ the browser
LOST_PAGE = """<!doctype html><meta charset="utf-8"><body style="margin:0;background:#000"><canvas id="c"></canvas>
<script src="wb-obraz.js"></script><script src="wb-scene.js"></script><script>
const W = 40, H = 30, px = new Uint8Array(W * H * 4); for (let i = 0; i < W * H; i++) { px[4 * i] = 200; px[4 * i + 1] = 100; px[4 * i + 2] = 50; px[4 * i + 3] = 255; }
const pr = new WBOBRAZ.Presenter(document.getElementById('c'), { gl: 'on', preserve: true });
const scene = new WBSCENE.Scene({}); const attached = scene.attach(pr);
const log = []; pr.onLost(() => log.push('lost')); pr.onRestore(() => log.push('restored'));
pr.size(W, H, 2, 1, 1); pr.present({ pixels: px });
const ext = pr.g.getExtension('WEBGL_lose_context');
window.lose = () => new Promise((res) => { document.getElementById('c').addEventListener('webglcontextlost', () => setTimeout(() => res({ lost: pr.lost, present: pr.present({ pixels: px }), scene: !!scene.gl, info: pr.info().lost }), 0), { once: true }); ext.loseContext(); });
window.restore = () => new Promise((res) => { document.getElementById('c').addEventListener('webglcontextrestored', () => setTimeout(() => res({ lost: pr.lost, restores: pr.restores, present: pr.present({ pixels: px }), scene: !!scene.gl, log }), 0), { once: true }); ext.restoreContext(); });
window.ready = { attached, ext: !!ext };
</script>"""

SHARED_PAGE = """<!doctype html><meta charset="utf-8"><body style="margin:0;background:#000"><canvas id="c"></canvas>
<script src="wb-obraz.js"></script><script>
const W = 40, H = 30, sab = new SharedArrayBuffer(W * H * 4), px = new Uint8Array(sab);
for (let i = 0; i < W * H; i++) { px[4 * i] = 200; px[4 * i + 1] = 100; px[4 * i + 2] = 50; px[4 * i + 3] = 255; }
const pr = new WBOBRAZ.Presenter(document.getElementById('c'), { gl: 'off' });
pr.size(W, H, 2, 1, 1);
try { window.result = { ok: pr.present({ pixels: px }), gl: pr.gl, isolated: crossOriginIsolated }; } catch (e) { window.result = { error: String(e) }; }
</script>"""

CSS_PAGE = """<!doctype html><meta charset="utf-8"><link rel="stylesheet" href="wb.css"><body>
<div class="game"><canvas id="c"></canvas><canvas class="crt-layer" aria-hidden="true"></canvas></div>
<script src="wb-obraz.js"></script><script>
const cv = document.getElementById('c'), pr = new WBOBRAZ.Presenter(cv, { gl: 'off' }), sc = new WBOBRAZ.Screen(document.querySelector('.game'), cv);
pr.size(320, 256, 2, 1, devicePixelRatio);
window.result = { box: sc.info().box, backing: sc.info().backing, client: [cv.clientWidth * devicePixelRatio, cv.clientHeight * devicePixelRatio] };
</script>"""


def _serve(tmp_path, pages, isolated=False):
    for name in ('wb-obraz.js', 'wb-scene.js', 'wb.css'):
        shutil.copy(WEB / name, tmp_path / name)
    for name, text in pages.items():
        (tmp_path / name).write_text(text)
    srv = web.serve(tmp_path, 0, isolated=isolated)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def test_a_lost_webgl_context_comes_back(tmp_path):
    """wb-obraz 1.9 / wb-scene 2.11: the presenter asks for the context back, draws nothing while it is gone, rebuilds
    everything when it is restored, and the scene attaches again. Before: no preventDefault - the canvas stayed black
    for good, present() went on saying true."""
    pytest.importorskip('playwright')
    from playwright.sync_api import sync_playwright
    srv, port = _serve(tmp_path, {'l.html': LOST_PAGE})
    try:
        with sync_playwright() as pw:
            br = pw.chromium.launch()
            page = br.new_page(viewport={'width': 400, 'height': 200})
            page.goto('http://127.0.0.1:%d/l.html' % port)
            page.wait_for_function('window.ready')
            ready = page.evaluate('window.ready')
            if not ready['ext']:
                pytest.skip('no WEBGL_lose_context in this Chromium')
            assert ready['attached']
            assert page.evaluate('lose()') == {'lost': True, 'present': False, 'scene': False, 'info': True}
            back = page.evaluate('restore()')
            assert back == {'lost': False, 'restores': 1, 'present': True, 'scene': True, 'log': ['lost', 'restored']}
            page.wait_for_timeout(100)
            w, h, rows = webtest.png_rgb(page.screenshot())
            assert rows[30][40] == (200, 100, 50), rows[30][40]                # the picture is there again
            br.close()
    finally:
        srv.shutdown()


def test_the_2d_path_takes_pixels_in_shared_memory(tmp_path):
    """wb-obraz 1.9: a threaded engine's frame lives in a SharedArrayBuffer; without WebGL2 the 2D path gave it to
    ImageData, which refuses shared memory - a TypeError every frame and no picture."""
    pytest.importorskip('playwright')
    from playwright.sync_api import sync_playwright
    srv, port = _serve(tmp_path, {'s.html': SHARED_PAGE}, isolated=True)
    try:
        with sync_playwright() as pw:
            br = pw.chromium.launch()
            page = br.new_page(viewport={'width': 400, 'height': 200})
            page.goto('http://127.0.0.1:%d/s.html' % port)
            page.wait_for_function('window.result')
            assert page.evaluate('window.result') == {'ok': True, 'gl': False, 'isolated': True}
            w, h, rows = webtest.png_rgb(page.screenshot())
            assert rows[30][40] == (200, 100, 50)
            br.close()
    finally:
        srv.shutdown()


@pytest.mark.parametrize('dpr', [1, 2])
def test_the_kits_stylesheet_leaves_the_canvas_its_backing(tmp_path, dpr):
    """wb.css gave `.game canvas` a 1 px border under `* { box-sizing: border-box }`: the content box was 2 CSS px
    smaller than the size the presenter set, and the browser resampled the picture. `arek web test` now checks the box."""
    pytest.importorskip('playwright')
    from playwright.sync_api import sync_playwright
    srv, port = _serve(tmp_path, {'c.html': CSS_PAGE})
    try:
        with sync_playwright() as pw:
            br = pw.chromium.launch()
            page = br.new_context(viewport={'width': 900, 'height': 700}, device_scale_factor=dpr).new_page()
            page.goto('http://127.0.0.1:%d/c.html' % port)
            page.wait_for_function('window.result')
            r = page.evaluate('window.result')
            assert r['client'] == r['backing'] and r['box'] == r['backing'], r
            br.close()
    finally:
        srv.shutdown()
    fails = []
    info = {'scale': 2, 'W': 320, 'H': 256, 'backing': [640, 512], 'content': [640, 512], 'origin': [0, 0], 'crtLayer': [640, 512],
            'crtOrigin': [0, 0], 'P': 2, 'D': 1, 'box': [638, 510]}
    webtest.check_layout(info, 'original', 'standard', 1, fails, 'x')
    assert len(fails) == 1 and 'content box' in fails[0]                   # the check that would have caught it
