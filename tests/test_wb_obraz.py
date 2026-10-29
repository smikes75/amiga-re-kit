"""The reference wb-obraz.js (display contract 1.5): its pure functions in Node, the package
files, `arek web copy`. The browser checks (arek web test) need Chromium and run separately."""
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from arek import cli, webtest

WEB = Path(__file__).parent.parent / 'src' / 'arek' / 'web'
node = shutil.which('node')


def js(expr):
    if not node:
        pytest.skip('no node')
    code = "const O = require(%s); const r = (%s); console.log(JSON.stringify(r));" % (json.dumps(str(WEB / 'wb-obraz.js')), expr)
    return json.loads(subprocess.run([node, '-e', code], capture_output=True, text=True, check=True).stdout)


def test_version_and_scale():
    assert js('O.VERSION') == '1.5'
    assert js('O.deviceScale(2, 320, 320, 1.25, 10)') == 3          # round(2 * 1.25)
    assert js('O.deviceScale(2, 336, 448, 2, 10)') == 3             # wider window: zoom counts in W0
    assert js('O.deviceScale(6, 320, 320, 2, 2.4)') == 4            # limited by the window
    assert js('O.deviceScale(0, 320, 320, 1.5, 2.4)') == 3          # fit: floor(2.4 * 1.5)
    # 1.4: an aspect divides the zoom (the picture is wider), fit is the page's limit as before
    assert js('O.deviceScale(2, 320, 320, 2, 10, 1.015)') == 4 and js('O.deviceScale(3, 320, 320, 1, 10, 1.5)') == 2
    assert js('O.deviceScale(0, 320, 320, 1, 2.9, 1.5)') == 2 and js('O.deviceScale(2, 320, 320, 1, 10, 0)') == 2


def test_content_size_and_patterns_with_an_aspect():
    assert js('O.contentSize(320, 256, 3, 1)') == [960, 768] and js('O.contentSize(320, 256, 3, 1.015)') == [974, 768]
    assert js('O.contentSize(320, 200, 2, 0.857)') == [548, 400] and js('O.contentSize(320, 256, 3)') == [960, 768]
    # a fake canvas records the fills: rows stay S high and content wide, columns are round(x*S*par) wide and crisp
    rects = js("""(() => { const rects = []; const c = { width: 40, height: 8, getContext: () => ({ fillRect(x, y, w, h) {
        rects.push([this.fillStyle, x, y, w, h]); } }) };
        O.testPattern(c, 'rows', 8, 2, 2, 1.5); O.testPattern(c, 'cols', 8, 2, 2, 1.25); return rects; })()""")
    rows = [r for r in rects if r[0].startswith('rgb(') and r[3] == 24]
    assert [r[1:] for r in rows] == [[0, 0, 24, 2], [0, 2, 24, 2]] and [r[0] for r in rows] == ['rgb(32,32,32)', 'rgb(56,56,56)']
    cols = [r for r in rects if r[0].startswith('rgb(') and r[4] == 4]
    assert [(r[1], r[3]) for r in cols] == [(0, 3), (3, 2), (5, 3), (8, 2), (10, 3), (13, 2), (15, 3), (18, 2)]   # 20 px over 8 columns
    assert sum(r[3] for r in cols) == 20


def test_layout_quantum():
    # whole CSS pixels: dpr 2 needs even device pixels (Alien Breed: 617 = 308.5 CSS px painted a row off)
    assert js('[1, 1.25, 1.5, 1.75, 2, 3].map(O.quantum)') == [1, 5, 3, 7, 2, 3]
    assert js('[O.padded(768, 1.25), O.padded(768, 1.5), O.padded(768, 2), O.padded(879, 2)]') == [770, 768, 768, 880]
    dx, dy = js('O.snap(10, 308.5, 2)')
    assert abs((308.5 + dy) * 2 - round((308.5 + dy) * 2)) < 1e-9 and ((308.5 + dy) * 2) % 2 == 0
    # 208.796875 CSS px at dpr 1.25 = 260.996 device px -> moved to 260 (a multiple of 5)
    dx, dy = js('O.snap(256, 208.796875, 1.25)')
    assert abs(dx) < 1e-9 and abs((208.796875 + dy) * 1.25 - 260) < 1e-9
    for dpr in (1.25, 1.5):
        assert webtest.quantum(dpr) == js('O.quantum(%s)' % dpr)


def test_crt_params_and_drawing():
    assert js("O.crtParams('original', 'strong', 3)") == {'P': 3, 'D': 2}
    assert js("O.crtParams('original', 'fine', 1)") == {'P': 2, 'D': 1}
    assert js("O.crtParams('enhanced', 'standard', 5)") == {'P': 3, 'D': 1}
    # a fake canvas records the dark rows: Original S=4 standard -> P 4, D 2, rows 2-3, 6-7
    rows = js("""(() => { const rects = []; const c = { getContext: () => ({ clearRect() {}, fillRect(x, y, w, h) {
        if (this.fillStyle.startsWith('rgba(0,0,0')) rects.push([x, y, w, h]); } }) };
        const r = O.drawCrt(c, 'original', 'standard', 4, 2, 12, 8); return [r, rects]; })()""")
    assert rows[0] == {'P': 4, 'D': 2, 'shape': 'lines'} and rows[1] == [[0, 2, 12, 2], [0, 6, 12, 2]]
    grid = js("""(() => { const rects = []; const c = { getContext: () => ({ clearRect() {}, fillRect(x, y, w, h) {
        if (this.fillStyle.startsWith('rgba(0,0,0')) rects.push([x, y, w, h]); } }) };
        O.drawCrt(c, 'original', 'standard', 4, 2, 8, 4, 'grid'); return rects; })()""")
    assert [2, 0, 2, 2] in grid and [0, 2, 8, 2] in grid               # a column end and a row


def test_zoom_label_with_an_aspect():
    assert js("O.zoomLabel(2, 4, 2, 320, 320, null, 1)") == '2×'
    assert js("O.zoomLabel(2, 4, 2, 320, 320, null, 1.5)") == '2× · actually 3×'
    assert js("O.zoomLabel(0, 2, 1, 320, 320, null, 1.5)") == 'fit (3×)'


def test_check_layout_with_an_aspect():
    fails = []
    info = {'scale': 3, 'W': 320, 'H': 256, 'par': 1.04, 'content': [998, 768], 'backing': [998, 768], 'origin': [10, 20],
            'crtLayer': [998, 768], 'crtOrigin': [10, 20], 'P': 2, 'D': 1}
    webtest.check_layout(info, 'enhanced', 'fine', 1, fails, 't')
    assert fails == []
    info['content'] = [960, 768]
    webtest.check_layout(info, 'enhanced', 'fine', 1, fails, 't')
    assert fails and 'content' in fails[0] and 'par 1.04' in fails[0]


def test_filter_and_labels():
    assert js("O.filter({blur: 0}, 2)") == 'none'
    assert js("O.filter({blur: 20, brightness: 110}, 1.5)") == 'brightness(1.100) blur(0.24px)'
    assert js("O.zoomLabel(3, 5, 2, 320, 320)") == '3× · limited to 2.5×'
    assert js("O.zoomLabel(0, 4, 2, 320, 320, {fit: 'do okna'})") == 'do okna (2×)'
    assert js("[O.crtOn(0, 1, 1), O.crtOn(0.5, 1, 1), O.crtOn(1, 1, 1), O.crtOn(0.5, 1, 0)]") == [1, 0.4, 1, 0.5]


def test_web_copy_and_package_files(tmp_path, capsys):
    assert (WEB / 'demo.html').exists() and 'wbObrazTest' in (WEB / 'demo.html').read_text()
    assert cli.main(['web', 'copy', str(tmp_path / 'web')]) == 0
    out = capsys.readouterr().out
    data = (tmp_path / 'web' / 'wb-obraz.js').read_bytes()
    assert hashlib.sha256(data).hexdigest() in out and 'wb-obraz 1.5' in out


def test_png_decoder_reads_the_kits_png():
    from arek.headless import shot
    import tempfile, os
    rgb = bytes([10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120])
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, 'x.png')
        shot.write_png(p, 2, 2, rgb)
        w, h, rows = webtest.png_rgb(open(p, 'rb').read())
    assert (w, h) == (2, 2) and rows == [[(10, 20, 30), (40, 50, 60)], [(70, 80, 90), (100, 110, 120)]]


def test_global_name_for_es_modules():
    # an ES module that imports nothing reads the module through globalThis (SF-sonet KIT-GAPS 15)
    assert js("(() => { delete globalThis.WBOBRAZ; delete require.cache[require.resolve(%s)]; require(%s); "
              "return typeof globalThis.WBOBRAZ.quantum; })()" % ((json.dumps(str(WEB / 'wb-obraz.js')),) * 2)) == 'function'
    assert 'wbObrazTest.set(mode' in (WEB / 'wb-obraz.js').read_text()


def test_presenter_2d_path_and_patterns():
    """1.5: the Presenter falls back to the 2D path when the canvas has no WebGL2 (a fake canvas records the fills), the
    pixel patterns match testPattern's greys, and the shaders are there for the WebGL path."""
    rows = js("Array.from(O.patternPixels('rows', 2, 3)).filter((v, i) => i % 4 === 0)")
    assert rows == [32, 32, 56, 56, 80, 80]
    cols = js("Array.from(O.patternPixels('cols', 3, 1)).filter((v, i) => i % 4 === 0)")
    assert cols == [32, 56, 80] and js("O.patternPixels('grey', 1, 1)[0]") == 128 and js("O.patternPixels('grey', 1, 1)[3]") == 255
    assert js("[O.GLSL.vs, O.GLSL.scale, O.GLSL.final].every((s) => s.startsWith('#version 300 es'))")
    assert js("O.GLSL.final.includes('par') && O.GLSL.final.includes('look') && O.GLSL.scale.includes('geo')")
    r = js("""(() => { const calls = []; const c = { width: 0, height: 0, style: {}, getContext(kind) {
        if (kind !== '2d') return null; return { fillStyle: '', fillRect(x, y, w, h) { calls.push(['fill', this.fillStyle, x, y, w, h]); },
            drawImage() { calls.push(['draw']); }, putImageData() { calls.push(['put']); } }; } };
        const p = new O.Presenter(c, { gl: 'auto' }); const sz = p.size(8, 2, 2, 1, 1.25);
        const noDraw = p.present({ draw: () => {} }); p.fill('rows');
        return { gl: p.gl, sz, noDraw, css: c.style, w: c.width, h: c.height, calls: calls.length, rows: calls.filter((k) => k[0] === 'fill' && k[1].startsWith('rgb(')).map((k) => k.slice(2)), info: p.info() }; })()""")
    assert r['gl'] is False and r['noDraw'] is False and r['sz'] == {'backing': [20, 5], 'content': [16, 4], 'redrawn': False}
    assert r['w'] == 20 and r['h'] == 5 and r['css']['width'] == '16px' and r['css']['height'] == '4px'   # padded to the quantum 5 at dpr 1.25
    assert r['rows'] == [[0, 0, 16, 2], [0, 2, 16, 2]] and r['info'] == {'gl': False, 'content': [16, 4], 'backing': [20, 5]}
    assert js("(() => { try { new O.Presenter({ getContext: () => null }, { gl: 'on' }); return 'no'; } catch (e) { return e.message; } })()") == 'wb-obraz: no WebGL2'


def test_webtest_gl_url():
    assert webtest.with_gl('http://x/demo.html', 1) == 'http://x/demo.html?gl=1'
    assert webtest.with_gl('http://x/demo.html?test=1', 0) == 'http://x/demo.html?test=1&gl=0'


RESIZE_PAGE = """<!doctype html><meta charset="utf-8"><body style="margin:0;background:#000">
<canvas id="c" style="display:block;image-rendering:pixelated"></canvas><script src="wb-obraz.js"></script><script>
const GL = new URLSearchParams(location.search).get('gl'), W = 40, H = 20;
const pr = new WBOBRAZ.Presenter(document.getElementById('c'), { gl: GL === '1' ? 'on' : 'off' });
const px = new Uint8ClampedArray(W * H * 4); for (let i = 0; i < W * H; i++) { px[4 * i] = 200; px[4 * i + 1] = 100; px[4 * i + 2] = 50; px[4 * i + 3] = 255; }
window.step = (s, draw) => pr.size(W, H, s, 1, 1).redrawn || (draw ? pr.present({ pixels: px }) : false);
pr.size(W, H, 2, 1, 1); pr.present({ pixels: px }); window.ready = true;
</script>"""


def test_presenter_redraws_after_a_resize(tmp_path):
    """1.5.1 (Alien Breed II in Safari): a resize without a present shows the last picture, not a blank canvas -
    on both paths, for a change of S (a new framebuffer, redrawn from the last frame) and of the backing only."""
    pytest.importorskip('playwright')
    import threading
    from playwright.sync_api import sync_playwright
    from arek import web
    shutil.copy(WEB / 'wb-obraz.js', tmp_path / 'wb-obraz.js')
    (tmp_path / 'r.html').write_text(RESIZE_PAGE)
    srv = web.serve(tmp_path, 0)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as pw:
            br = pw.chromium.launch()
            for gl in (0, 1):
                page = br.new_page(viewport={'width': 400, 'height': 200})
                page.goto('http://127.0.0.1:%d/r.html?gl=%d' % (port, gl))
                page.wait_for_function('window.ready')
                assert page.evaluate('step(3, false)') is True                     # S 2 -> 3: redrawn without a present
                page.wait_for_timeout(100)
                w, h, rows = webtest.png_rgb(page.screenshot())
                assert rows[30][100] == (200, 100, 50) and rows[59][119] == (200, 100, 50), (gl, rows[30][100])
                page.close()
            br.close()
    finally:
        srv.shutdown()
