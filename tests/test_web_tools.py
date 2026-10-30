"""The small web tools of 0.7.1: the variant stripper, the isolated dev server, the touch controls file, the shot
alignment (`arek shots --align`) and the long-run check's hook contract (playwright, when installed)."""
import http.client
import json
import os
import shutil
import subprocess
import threading

import pytest

from arek import cli, parity, web

WEB = os.path.dirname(os.path.abspath(web.__file__))
SRC = """const a = 1;
const full = 2; //@FULL
//@LEVEL1{
const only1 = 3;
//@}LEVEL1
//@FULL{
const onlyFull = 4;
const more = 5;
//@}FULL
const b = 6; //@LEVEL1
end();
"""


def test_strip_keeps_one_variant(tmp_path):
    level1 = web.strip(SRC, ('FULL',))
    assert level1 == "const a = 1;\nconst only1 = 3;\nconst b = 6;\nend();\n"
    full = web.strip(SRC, ('LEVEL1',))
    assert full == "const a = 1;\nconst full = 2;\nconst onlyFull = 4;\nconst more = 5;\nend();\n"
    assert '//@' not in level1 + full
    src, out = tmp_path / 'p.js', tmp_path / 'o.js'
    src.write_text(SRC)
    assert cli.main(['web', 'strip', str(src), str(out), '--drop', 'LEVEL1']) == 0 and out.read_text() == full


SRC2 = """a //@A
b //@B
c
//@A{
aa
//@}A
//@B{
bb
//@}B
"""
HTML = """<p>always</p>
<p>dev only</p> <!--@DEV-->
<!--@DEV{-->
<div id="debug">x</div>
<!--@}DEV-->
<!--@FULL{-->
<p>full</p>
<!--@}FULL-->
<p>end</p> <!--@FULL-->
"""


def test_strip_drops_several_variants_in_one_pass(tmp_path):
    """Alien Breed II G51: after one pass the markers are gone, so two passes cannot drop A and then B; one pass
    with both does, and the CLI's --drop repeats."""
    assert web.strip(SRC2, ('A',)) == "b\nc\nbb\n"
    assert web.strip(web.strip(SRC2, ('A',)), ('B',)) == "b\nc\nbb\n"        # the second pass finds no markers
    assert web.strip(SRC2, ('A', 'B')) == "c\n"
    src, out = tmp_path / 'p.js', tmp_path / 'o.js'
    src.write_text(SRC2)
    assert cli.main(['web', 'strip', str(src), str(out), '--drop', 'A', '--drop', 'B']) == 0 and out.read_text() == "c\n"


def test_strip_html_markers():
    """0.8.6: the same markers as HTML comments, for a page's index.html."""
    assert web.strip(HTML, ('DEV',)) == "<p>always</p>\n<p>full</p>\n<p>end</p>\n"
    assert web.strip(HTML, ('DEV', 'FULL')) == "<p>always</p>\n"
    assert web.strip(HTML, ()) == "<p>always</p>\n<p>dev only</p>\n<div id=\"debug\">x</div>\n<p>full</p>\n<p>end</p>\n"


def _get(port, path):
    c = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
    c.request('GET', path)
    r = c.getresponse()
    body = r.read()
    c.close()
    return r.status, dict((k.lower(), v) for k, v in r.getheaders()), body


def test_serve_isolated_sends_the_headers(tmp_path):
    (tmp_path / 'index.html').write_text('<p>x</p>')
    (tmp_path / 'd.adf').write_bytes(b'\x01' * 1024)
    for isolated in (False, True):
        srv = web.serve(tmp_path, 0, {'ADF1': str(tmp_path / 'd.adf')}, isolated=isolated)
        port = srv.server_address[1]
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        try:
            st, h, body = _get(port, '/index.html')
            assert st == 200 and body == b'<p>x</p>' and h['cache-control'] == 'no-store'
            assert ('cross-origin-opener-policy' in h) == isolated and h.get('cross-origin-embedder-policy') == ('require-corp' if isolated else None)
            st, h, body = _get(port, '/local-disks/disk1.adf')
            assert st == 200 and body == b'\x01' * 1024 and h['cache-control'] == 'no-store'
        finally:
            srv.shutdown()
            srv.server_close()


def test_touch_file_is_shipped_and_loads():
    path = os.path.join(WEB, 'wb-touch.js')
    text = open(path).read()
    assert 'wb-touch.js' in web.FILES and 'amiga-re-kit' in text[:4096]
    for name in ('WBTOUCH', 'init(host, opt)', 'bits: () => bits', 'active: () => !!root', '.wb-touch-stick', 'pointer: coarse'):
        assert name in text
    if not shutil.which('node'):
        pytest.skip('no node')
    r = subprocess.run(['node', '-e', "const T = require(%s); console.log(JSON.stringify([T.version, T.bits(), T.active(), typeof T.init]))" % json.dumps(path)],
                       capture_output=True, text=True, check=True)
    assert json.loads(r.stdout) == ['1.0', 0, False, 'function']


def _frame(seed, dx=0, dy=0, w=716, h=285):
    px = bytearray(w * h * 3)
    for y in range(h):
        for x in range(w):
            sx, sy = x - dx, y - dy
            v = ((sx * 7 + sy * 13 + seed) ^ (sx >> 3)) & 0xff if 0 <= sx < w and 0 <= sy < h else 0
            i = (y * w + x) * 3
            px[i], px[i + 1], px[i + 2] = v, (v * 3) & 0xff, (v >> 1)
    return bytes(px)


def test_shots_align_finds_the_shake(tmp_path):
    a = _frame(1)
    b = _frame(1, 2, 1)
    assert parity.align_shot(a, b, max_shift=4) == (2, 1)
    assert parity.diff_shots(a, b, 0, 2, 1)[0] == 0 and parity.diff_shots(a, b)[0] > 100000
    c = bytearray(b)
    c[(100 * 716 + 300) * 3] ^= 0xff                                   # one pixel changed at (300, 100) of b = (298, 99) of a
    n, box = parity.diff_shots(a, bytes(c), 0, 2, 1)
    assert (n, box) == (1, (298, 99, 298, 99))
    for d, data in (('o', [a, _frame(2)]), ('h', [b, _frame(2, -1, 0)])):
        (tmp_path / d).mkdir()
        for k, fr in enumerate(data):
            (tmp_path / d / ('s_%06d.raw' % (10 + k))).write_bytes(fr)
    r = parity.compare_shots(str(tmp_path / 'o' / 's'), str(tmp_path / 'h' / 's'), align=4)
    assert r['pairs'] == 2 and r['equal'] == 2 and [f[2] for f in r['frames']] == [(2, 1), (-1, 0)]
    assert parity.compare_shots(str(tmp_path / 'o' / 's'), str(tmp_path / 'h' / 's'))['equal'] == 0
    assert cli.main(['shots', str(tmp_path / 'o' / 's'), str(tmp_path / 'h' / 's'), '--align', '4']) == 0
    assert cli.main(['shots', str(tmp_path / 'o' / 's'), str(tmp_path / 'h' / 's')]) == 1
    assert 'frames' in parity.format_shots(r, all_frames=True) or 'pairs' in parity.format_shots(r, all_frames=True)


PAGE = """<!doctype html><title>t</title><body><script>
let x = 0, y = 0; function tick() { x += 2; y += 1; requestAnimationFrame(tick); } requestAnimationFrame(tick);
globalThis.WBLONGRUN = { ready: () => true, cam: () => [x, y], status: () => 'ok ' + x };
</script></body>"""


def test_longrun_samples_the_hook(tmp_path):
    pytest.importorskip('playwright')
    (tmp_path / 'p.html').write_text(PAGE)
    srv = web.serve(tmp_path, 0)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        rows = list(web.longrun('http://127.0.0.1:%d/p.html' % port, minutes=0.1, interval=2.5, sample=1.0))
    finally:
        srv.shutdown()
    assert len(rows) >= 2 and all(r['frames'] > 10 and 1.5 < r['step'] < 2.5 and r['status'].startswith('ok') for r in rows)
    assert 'frames' in web.format_longrun(rows[0])
