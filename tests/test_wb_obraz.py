"""The reference wb-obraz.js (display contract 1.3): its pure functions in Node, the package
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
    assert js('O.VERSION') == '1.3'
    assert js('O.deviceScale(2, 320, 320, 1.25, 10)') == 3          # round(2 * 1.25)
    assert js('O.deviceScale(2, 336, 448, 2, 10)') == 3             # wider window: zoom counts in W0
    assert js('O.deviceScale(6, 320, 320, 2, 2.4)') == 4            # limited by the window
    assert js('O.deviceScale(0, 320, 320, 1.5, 2.4)') == 3          # fit: floor(2.4 * 1.5)


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
    assert hashlib.sha256(data).hexdigest() in out and 'wb-obraz 1.3' in out


def test_png_decoder_reads_the_kits_png():
    from arek.headless import shot
    import tempfile, os
    rgb = bytes([10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120])
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, 'x.png')
        shot.write_png(p, 2, 2, rgb)
        w, h, rows = webtest.png_rgb(open(p, 'rb').read())
    assert (w, h) == (2, 2) and rows == [[(10, 20, 30), (40, 50, 60)], [(70, 80, 90), (100, 110, 120)]]
