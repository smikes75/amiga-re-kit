"""The shared menu (wb-menu.js) and the sound contract (wb-zvuk.js): pure parts in Node, package files."""
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
    code = "const Z = require(%s), M = require(%s); const r = (%s); console.log(JSON.stringify(r));" % (
        json.dumps(str(WEB / 'wb-zvuk.js')), json.dumps(str(WEB / 'wb-menu.js')), expr)
    return json.loads(subprocess.run([node, '-e', code], capture_output=True, text=True, check=True).stdout)


def test_mix_rule():
    assert js('Z.VERSION') == '1.0' and js('Z.RAMP_MS') == 20
    assert js('Z.mix(1, 0, 100)') == [1, 0] and js('Z.mix(1, 0, 0)') == [0.5, 0.5] and js('Z.mix(0.5, -0.5, 50)') == [0.25, -0.25]
    g = js('Z.gains(70)')
    assert abs(g['a'] - 0.85) < 1e-12 and abs(g['b'] - 0.15) < 1e-12
    assert js('Z.gains(-5)') == {'a': 0.5, 'b': 0.5} and js('Z.gains(undefined)') == {'a': 1, 'b': 0}
    assert js('Array.from(Z.mixArrays([1, 2], [3, 4], 0)[0])') == [2, 3]


def test_filters_and_process():
    c = js('Z.coefficients(44100)')
    ff, fb = c['fixed']['feedforward'], c['fixed']['feedback']
    assert abs(sum(ff) / (1 + fb[1]) - 1) < 1e-9                              # low-pass: DC gain 1
    ff, fb = c['hp']['feedforward'], c['hp']['feedback']
    assert abs(sum(ff)) < 1e-9                                                # high-pass: DC gain 0
    ff, fb = c['led']['feedforward'], c['led']['feedback']
    assert abs(sum(ff) / (1 + fb[1] + fb[2]) - 1) < 1e-9
    # a flat chain is the identity, width 0 is mono, volume scales, off is silence
    r = js("""(() => { const s = Z.testSignal(1024, 44100), flat = {volume: 100, stereo: 100, filterFixed: false, filterLed: 'off', filterHp: false};
        const md = (a, b) => Math.max(...Array.from(a).map((x, i) => Math.abs(x - b[i])));
        const [l, r] = Z.process(s.l, s.r, flat, false, 44100);
        const [m1, m2] = Z.process(s.l, s.r, Object.assign({}, flat, {stereo: 0}), false, 44100);
        const [v] = Z.process(s.l, s.r, Object.assign({}, flat, {volume: 25}), false, 44100);
        const [o] = Z.process(s.l, s.r, Object.assign({}, flat, {on: false}), false, 44100);
        const [f] = Z.process(s.l, s.r, {volume: 100, stereo: 100}, true, 44100);
        return { id: md(l, s.l) + md(r, s.r), mono: md(m1, m2), mid: md(m1, Array.from(s.l).map((x, i) => (x + s.r[i]) / 2)),
                 vol: md(v, Array.from(s.l).map((x) => x / 4)), off: Math.max(...Array.from(o).map(Math.abs)), filt: md(f, s.l) }; })()""")
    assert r['id'] < 1e-12 and r['mono'] < 1e-12 and r['mid'] < 1e-6 and r['vol'] < 1e-7 and r['off'] == 0 and r['filt'] > 1e-3   # float32 arrays


def test_menu_defaults_coerce_merge():
    assert js('M.VERSION') == '1.0' and js('M.MODES') == ['original', 'enhanced']
    d = js("M.defaults('display', 'enhanced')")
    assert d['par'] == 1.04 and d['smooth'] is True and d['zoom'] == 3 and d['crt-detail'] == 'fine'
    assert js("M.defaults('display', 'original').par") == 1 and js("M.defaults('display', 'original').smooth") is False
    s = js("M.defaults('sound', 'enhanced')")
    assert s == {'sound': True, 'volume': 80, 'filter-fixed': True, 'filter-led': 'auto', 'filter-hp': True, 'stereo': 70}
    assert js("M.defaults('sound', 'original').stereo") == 100
    assert js("M.defaults('sound', 'original', {sound: {original: {stereo: 90, volume: '300'}}})")['stereo'] == 90
    assert js("M.defaults('sound', 'original', {sound: {original: {volume: '300'}}})")['volume'] == 100     # clamped
    par = "M.ITEMS.display.find((i) => i.id === 'par')"
    assert js('M.coerce(%s, 1.0449)' % par) == 1.04 and js('M.coerce(%s, 5)' % par) == 1.1 and js('M.coerce(%s, "x")' % par) == 1
    zoom = "M.ITEMS.display.find((i) => i.id === 'zoom')"
    assert js('M.coerce(%s, "2.5")' % zoom) == 2.5 and js('M.coerce(%s, "x")' % zoom) == 1
    assert js("M.coerce(M.ITEMS.sound[0], 'false')") is False and js("M.coerce(M.ITEMS.sound[0], 1)") is True
    m = js("M.merge('sound', 'enhanced', {enhanced: {sound: {stereo: 55, bogus: 1}}})")
    assert m['stereo'] == 55 and 'bogus' not in m and m['volume'] == 80
    assert set(js("Object.keys(M.TEXTS.cs.display)")) >= {'zoom', 'par', 'smooth', 'defaults', 'fit'} and js("M.TEXTS.cs.sound._") == 'Zvuk'


def test_package_files_and_copy(tmp_path, capsys):
    assert cli.main(['web', 'copy', str(tmp_path)]) == 0
    for name in ('wb-obraz.js', 'wb-seal.js', 'wb-menu.js', 'wb-zvuk.js'):
        assert (tmp_path / name).exists()
    assert webtest.MENU_IDS[0] == 'wb-zoom' and len(webtest.MENU_IDS) == 18
    assert "globalThis.WBMENU" in (WEB / 'wb-menu.js').read_text() and "globalThis.WBZVUK" in (WEB / 'wb-zvuk.js').read_text()
    assert 'wbMenuTest' in (WEB / 'demo.html').read_text() and 'wbZvukTest' in (WEB / 'demo.html').read_text()
