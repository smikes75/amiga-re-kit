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
        json.dumps(str(WEB / 'wb-zvuk.js')), json.dumps(str(WEB / 'wb-nastaveni.js')), expr)
    return json.loads(subprocess.run([node, '-e', code], capture_output=True, text=True, check=True).stdout)


def test_mix_rule():
    assert js('Z.VERSION') == '1.1' and js('Z.RAMP_MS') == 20
    assert js('Z.mix(1, 0, 100)') == [1, 0] and js('Z.mix(1, 0, 0)') == [0.5, 0.5] and js('Z.mix(0.5, -0.5, 50)') == [0.25, -0.25]
    g = js('Z.gains(70)')
    assert abs(g['a'] - 0.85) < 1e-12 and abs(g['b'] - 0.15) < 1e-12
    assert js('Z.gains(-5)') == {'a': 0.5, 'b': 0.5} and js('Z.gains(undefined)') == {'a': 1, 'b': 0}
    assert js('Array.from(Z.mixArrays([1, 2], [3, 4], 0)[0])') == [2, 3]


def test_filters_and_process():
    c = js('Z.coefficients(44100)')
    ff, fb = c['fixed']['feedforward'], c['fixed']['feedback']
    assert abs(sum(ff) / (1 + fb[1]) - 1) < 1e-9                              # low-pass: DC gain 1
    import math
    a = 1 - math.exp(-2 * math.pi * 4420.97 / 44100)
    assert abs(ff[0] - a) < 1e-12 and abs(fb[1] + (1 - a)) < 1e-12            # y += a (x - y), the schematic's RC
    assert js('Z.FILTERS') == {'fixed': {'hz': 4420.97, 'order': 1}, 'led': {'hz': 3090.53, 'order': 2, 'q': 0.660225}, 'hp': {'hz': 5.2041, 'order': 1}}
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
    assert js('M.VERSION') == '1.4' and js('M.MODES') == ['original', 'enhanced']
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
    assert js('[M.coerce(%s, 2.2), M.coerce(%s, "5.5"), M.coerce(%s, 0.1), M.coerce(%s, 0)]' % (zoom, zoom, zoom, zoom)) == [2, 6, 1, 0]   # nearest option
    assert js("M.coerce(M.ITEMS.sound[0], 'false')") is False and js("M.coerce(M.ITEMS.sound[0], 1)") is True
    m = js("M.merge('sound', 'enhanced', {enhanced: {sound: {stereo: 55, bogus: 1}}})")
    assert m['stereo'] == 55 and 'bogus' not in m and m['volume'] == 80
    assert set(js("Object.keys(M.TEXTS.cs.display)")) >= {'zoom', 'par', 'smooth', 'defaults', 'fit'} and js("M.TEXTS.cs.sound._") == 'Zvuk'


def test_menu_zoom_snap():
    """spec.zoom = 'snap': the zoom only takes the values spec.zoomSteps() lists (whole device pixels), nearest wins, fit stays."""
    snap = lambda tail, spec="{zoom: 'snap', zoomSteps: () => [3, 1, {value: 2, label: '2 px'}, 4.5]}": \
        js("(() => { const m = new M.Menu(null, %s); return %s; })()" % (spec, tail))
    assert snap("m.zoomSteps()") == [{'value': 1, 'label': '1×'}, {'value': 2, 'label': '2 px'}, {'value': 3, 'label': '3×'}, {'value': 4.5, 'label': '4.5×'}]
    assert snap("[m.snapZoom(2.4), m.snapZoom(2.6), m.snapZoom(9), m.snapZoom(0), m.snapZoom(0.2)]") == [2, 3, 4.5, 0, 1]
    assert snap("(m.set('display', 'zoom', 2.6), m.get('display').zoom)") == 3
    assert snap("(m.set('display', 'zoom', '0'), m.get('display').zoom)") == 0                                    # fit
    assert snap("(m.set('display', 'zoom', 2.6), [m.zoomSteps(), m.get('display').zoom])", "{}") == [[], 2.5]    # no snapping: the nearest option
    assert snap("m.snapZoom(2.4)", "{zoom: 'snap'}") == 2.4                                                      # snap without steps: unchanged
    # an exact zoom survives a reload (Alien Breed K2: 2 * 448 / 293 fell back to options[0] = 1 in 0.6.2)
    r = js("""(() => { const box = {}; globalThis.localStorage = { getItem: (k) => box[k] ?? null, setItem: (k, v) => { box[k] = String(v); } };
        const steps = () => [1, 2, 3].map((S) => S * 448 / 293), spec = {zoom: 'snap', zoomSteps: steps, store: 'g', mode: 'enhanced'};
        new M.Menu(null, spec).set('display', 'zoom', 3.05802);
        const m = new M.Menu(null, spec), before = m.getMode('enhanced', 'display').zoom; m.refreshZoom();
        const plain = new M.Menu(null, {store: 'g', mode: 'enhanced'});
        return [before, m.get('display').zoom, plain.get('display').zoom, M.coerce(M.ITEMS.display[0], 9, true), M.coerce(M.ITEMS.display[0], 'x', true)]; })()""")
    assert abs(r[0] - 2 * 448 / 293) < 1e-9 and abs(r[1] - 2 * 448 / 293) < 1e-9 and r[2] == 3 and r[3] == 6 and r[4] == 1


def test_package_files_and_copy(tmp_path, capsys):
    assert cli.main(['web', 'copy', str(tmp_path)]) == 0
    for name in ('wb-obraz.js', 'wb-seal.js', 'wb-nastaveni.js', 'wb-zvuk.js', 'wb-atn.js', 'wb-bytekiller.js', 'wb-content.js', 'wb-touch.js', 'wb-takt.js', 'wb-zvuk-out.js', 'wb-zvuk-worklet.js'):
        assert (tmp_path / name).exists()
    import tomllib                                                            # every file web copy ships is in the wheel
    data = tomllib.loads((Path(__file__).parent.parent / 'pyproject.toml').read_text())['tool']['setuptools']['package-data']['arek.web']
    assert set(data) >= {'wb-obraz.js', 'wb-seal.js', 'wb-nastaveni.js', 'wb-zvuk.js', 'wb-atn.js', 'wb-bytekiller.js', 'wb-content.js', 'wb-touch.js', 'wb-takt.js', 'wb-zvuk-out.js', 'wb-zvuk-worklet.js', 'demo.html', 'smooth-demo.html', 'wb-menu.js', 'wb.css'}   # 1.0.17: the Workbench bar ships too (KIT-GAP 25)
    assert webtest.MENU_IDS[0] == 'wb-zoom' and len(webtest.MENU_IDS) == 21 and 'wb-blue' in webtest.MENU_IDS
    assert "globalThis.WBNASTAVENI" in (WEB / 'wb-nastaveni.js').read_text() and "globalThis.WBZVUK" in (WEB / 'wb-zvuk.js').read_text()
    assert 'wbMenuTest' in (WEB / 'demo.html').read_text() and 'wbZvukTest' in (WEB / 'demo.html').read_text()
    assert js("[M.ITEMS.display.map((i) => i.id).slice(7, 11), M.ITEMS.display.find((i) => i.id === 'saturation').max]") == [['saturation', 'red', 'green', 'blue'], 200]
    # the games' own file under a kit name (their Workbench bar was wb-menu.js) is never overwritten
    own = tmp_path / 'wb-nastaveni.js'
    own.write_text("// the game's own bar\n")
    assert cli.main(['web', 'copy', str(tmp_path)]) == 1 and own.read_text().startswith("// the game's own")
    assert 'kept, not a kit file' in capsys.readouterr().out
    assert cli.main(['web', 'copy', str(tmp_path), '--force']) == 0 and 'WBNASTAVENI' in own.read_text()


def test_menu_units_events_and_keep():
    """SF KIT-GAPS 32 (units, Czech decimals), 35 (why a listener was called), 36 (refreshZoom keeps the wish)."""
    r = js("""(() => { const m = new M.Menu(null, {lang: 'cs'}), e = new M.Menu(null, {}), it = (s, id) => M.ITEMS[s].find((i) => i.id === id);
        return [m.valueText(it('display', 'par'), 1.04), m.valueText(it('sound', 'stereo'), 70), e.valueText(it('display', 'par'), 1.04),
                e.valueText(it('sound', 'volume'), 80), m.optionText('display', 1.5), e.optionText('display', 1.5)]; })()""")
    assert r == ['1,04', '70\u00a0%', '1.04', '80%', '1,5×', '1.5×']
    ev = js("""(() => { const m = new M.Menu(null, {}), seen = []; m.on('change', (st, what, info) => seen.push([what, info]));
        m.set('sound', 'stereo', 40); m.reset('sound'); m.setMode('enhanced'); return seen; })()""")
    assert ev == [['sound', {'cause': 'set', 'id': 'stereo'}], ['sound', {'cause': 'reset', 'section': 'sound'}], ['mode', {'cause': 'mode'}]]
    keep = js("""(() => { let steps = [1, 2, 3]; const m = new M.Menu(null, {zoom: 'snap', zoomSteps: () => steps});
        m.set('display', 'zoom', 3); steps = [1.4, 2.8];                 // the window got smaller
        m.refreshZoom({keep: true}); const kept = m.get('display').zoom; m.refreshZoom(); return [kept, m.get('display').zoom]; })()""")
    assert keep == [3, 2.8]


def test_rows_a_page_leaves_out():
    """wb-nastaveni 1.3 (the Atari page's request): spec.omit leaves rows out - the Amiga's filters on a machine that has
    none. Such a row has the item's `none` (the filters off) whatever is stored or given as a default, cannot be set, and
    the test hooks list only the rows the menu has; an item without `none` keeps the mode's default."""
    om = "{ sound: ['filter-fixed', 'filter-led'], display: ['crt-shape'] }"
    d = js("M.defaults('sound', 'enhanced', { sound: { enhanced: { 'filter-fixed': true } } }, false, %s)" % om)
    assert d['filter-fixed'] is False and d['filter-led'] == 'off' and d['filter-hp'] is True and d['stereo'] == 70
    m = js("M.merge('sound', 'original', { original: { sound: { 'filter-fixed': true, 'filter-led': 'on', stereo: 40 } } }, null, false, %s)" % om)
    assert m['filter-fixed'] is False and m['filter-led'] == 'off' and m['stereo'] == 40
    assert js("M.defaults('display', 'original', null, false, %s)['crt-shape']" % om) == 'lines'      # no `none`: the default
    r = js("(() => { const menu = M.build(null, { omit: %s }); menu.set('sound', 'filter-fixed', true); menu.set('sound', 'volume', 30); menu.reset('display');"
           " const h = menu.testHooks(); return { s: menu.get('sound'), ids: h.ids(), all: M.build(null, {}).testHooks().ids().length }; })()" % om)
    assert r['s']['filter-fixed'] is False and r['s']['filter-led'] == 'off' and r['s']['volume'] == 30
    assert 'wb-filter-fixed' not in r['ids'] and 'wb-filter-led' not in r['ids'] and 'wb-crt-shape' not in r['ids'] and 'wb-filter-hp' in r['ids']
    assert len(r['ids']) == r['all'] - 3 == 16
    assert js("M.defaults('sound', 'enhanced')") == {'sound': True, 'volume': 80, 'filter-fixed': True, 'filter-led': 'auto', 'filter-hp': True, 'stereo': 70}


@pytest.mark.parametrize('tail,rows', [('', 0), ('?omit=filter-fixed,filter-led', 2)])
def test_the_page_test_follows_the_rows_the_menu_has(tail, rows):
    """arek web test section 6 on the demo page: with every row as before; with the filters' rows left out the rows are
    not in the document, the check does not ask for them and the sound contract is still checked."""
    pytest.importorskip('playwright')
    from playwright.sync_api import sync_playwright
    import threading
    from arek import web as webpkg
    srv = webpkg.serve(str(WEB), 0, isolated=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            p = b.new_page(viewport={'width': 1280, 'height': 900})
            p.goto('http://127.0.0.1:%d/demo.html%s' % (srv.server_address[1], tail))
            p.wait_for_function('window.wbObrazTest && window.wbMenuTest && window.wbZvukTest')
            fails = []
            n = webtest.check_menu_and_sound(p, fails)
            gone = p.evaluate("['wb-filter-fixed', 'wb-filter-led'].filter((i) => !document.getElementById(i)).length")
            b.close()
    finally:
        srv.shutdown()
    assert fails == [] and n == 13 and gone == rows


ROWS = """[{ id: 'shadows', label: 'Shadows', options: [1, 0.75, 0.5], labels: { 1: 'black, as the original' }, def: 0.5, modes: ['enhanced'] },
           { id: 'rotor', label: 'Rotor', options: [4, 2, 0], def: { original: 0, enhanced: 4 }, modes: ['enhanced'] },
           { id: 'fading', label: 'Blade fading', options: ['100/0', '85/30'], when: { rotor: 2 } },
           { id: 'screen', label: 'Screen', options: [0, 32, 64, 'play64'], def: 64, modes: ['enhanced'], changesGame: ['play64'] },
           { id: 'landscape', section: 'debug', label: 'Landscape', options: [0, 1, 2], perMode: false },
           { id: 'lives', section: 'debug', label: 'Unlimited lives', kind: 'check', perMode: false, changesGame: true },
           { id: 'missiles', section: 'debug', kind: 'range', min: 1, max: 6, step: 1, def: 2, perMode: false },
           { id: 'download', section: 'debug', kind: 'button', label: 'Download the recording', run: (m) => { globalThis.ran = (globalThis.ran || 0) + 1; } }]"""


def test_game_rows_state_modes_dependencies_and_store():
    """wb-nastaveni 1.4 (kit 1.0.84, SWIV): spec.rows - the game's rows kept like the kit's: per mode or for both (perMode:
    false), coerced, in get / set / reset / the store and the listeners; shown in their modes and while the row they
    depend on (when) is shown and has the value; ids unique over the kit's items and the rows; a button keeps nothing."""
    r = js("""(() => { const box = {}; globalThis.localStorage = { getItem: (k) => box[k] ?? null, setItem: (k, v) => { box[k] = String(v); } };
        const spec = { store: 'g', rows: %s }, m = new M.Menu(null, spec), seen = [];
        m.on('change', (st, what, info) => seen.push([what, info.id || info.section || info.cause]));
        const o = [m.get('display').rotor, m.get('display').shadows, m.get('debug'), m.testHooks().shown()];
        m.setMode('enhanced'); o.push(m.get('display').rotor, m.testHooks().shown());
        m.set('display', 'rotor', '2'); m.set('display', 'shadows', 0.6); m.set('debug', 'lives', 1); m.set('debug', 'missiles', 9); m.set('debug', 'download', 1);
        o.push(m.get('display').rotor, m.get('display').shadows, m.testHooks().shown(), m.get('debug'));
        m.setMode('original'); o.push(m.get('display').rotor, m.get('debug').lives, m.testHooks().shown());
        const again = new M.Menu(null, spec); again.setMode('enhanced');
        o.push(again.get('display').rotor, again.get('debug'), again.get().debug.missiles);
        again.reset('display'); o.push(again.get('display').rotor, again.get('debug').lives);
        again.reset(); o.push(again.get('debug').lives, again.testHooks().rows().length, again.testHooks().ids().length);
        return { o, seen: seen.slice(0, 7) }; })()""" % ROWS)
    o = r['o']
    assert o[0] == 0 and o[1] == 0.5 and o[2] == {'landscape': 0, 'lives': False, 'missiles': 2}
    assert o[3] == ['wb-landscape', 'wb-lives', 'wb-missiles', 'wb-download']                          # original: no Enhanced rows
    assert o[4] == 4 and o[5] == ['wb-shadows', 'wb-rotor', 'wb-screen', 'wb-landscape', 'wb-lives', 'wb-missiles', 'wb-download']
    assert o[6] == 2 and o[7] == 0.5 and 'wb-fading' in o[8] and o[9] == {'landscape': 0, 'lives': True, 'missiles': 6}
    assert o[10] == 0 and o[11] is True and 'wb-fading' not in o[12]                                    # per mode / for both modes
    assert o[13] == 2 and o[14] == {'landscape': 0, 'lives': True, 'missiles': 6} and o[15] == 6            # kept in the store
    assert o[16] == 4 and o[17] is True                                                                 # reset('display') leaves debug
    assert o[18] is False and o[19] == 8 and o[20] == 19
    assert r['seen'][0] == ['mode', 'mode'] and ['display', 'rotor'] in r['seen'] and ['debug', 'lives'] in r['seen']
    bad = js("""[[{ id: 'zoom' }], [{ id: 'a' }, { id: 'a' }], [{ id: 'b', kind: 'select' }], [{ id: 'c', kind: 'knob' }]].map((rows) => {
        try { new M.Menu(null, { rows }); return 'built'; } catch (e) { return e.message; } })""")
    assert [b.split(': ')[1].split(' ')[0] for b in bad] == ['the', 'the', 'row', 'row'] and 'taken' in bad[0] and 'taken' in bad[1] and 'no options' in bad[2] and 'kind knob' in bad[3]


def test_game_rows_in_the_browser(tmp_path):
    """The rows render as the kit's do: a select with the option texts and the "changes the game" mark, a check, a range, a
    button in the page's Debug host (spec.hosts.debug); hidden rows are hidden, a change of the select shows the row that
    depends on it; Czech marks."""
    pw = pytest.importorskip('playwright.sync_api')
    from arek import web
    shutil.copy(WEB / 'wb-nastaveni.js', tmp_path / 'wb-nastaveni.js')
    (tmp_path / 'rows.html').write_text("""<!doctype html><meta charset="utf-8"><div id="menu"></div><div id="debug"></div>
<script src="wb-nastaveni.js"></script><script>
window.menu = WBNASTAVENI.build(document.getElementById('menu'), { lang: 'cs', mode: 'enhanced', rows: %s, hosts: { debug: document.getElementById('debug') } });
</script>""" % ROWS)
    import threading
    srv = web.serve(str(tmp_path), 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        port = srv.server_address[1]
        with pw.sync_playwright() as p:
            try:
                b = p.chromium.launch()
            except Exception as e:                                # no browser installed
                pytest.skip(str(e))
            pg = b.new_page()
            pg.goto('http://127.0.0.1:%d/rows.html' % port)
            r = pg.evaluate("""() => { const q = (s) => document.querySelector(s), o = {};
                o.shadowOpts = [...q('#wb-shadows').options].map((x) => x.textContent);
                o.screenOpts = [...q('#wb-screen').options].map((x) => x.textContent);
                o.livesLabel = q('label[for=wb-lives]').textContent;
                o.inDebug = ['wb-landscape', 'wb-lives', 'wb-missiles', 'wb-download'].every((id) => q('#debug #' + id));
                o.inDisplay = !!q('#menu .wb-nastaveni-display #wb-rotor');
                o.fadingHidden = q('#wb-fading').closest('.wb-nastaveni-row').hidden;
                const sel = q('#wb-rotor'); sel.value = '2'; sel.dispatchEvent(new Event('change'));
                o.fadingShown = !q('#wb-fading').closest('.wb-nastaveni-row').hidden;
                q('#wb-download').click(); o.ran = globalThis.ran;
                menu.setMode('original'); o.rotorHiddenInOriginal = q('#wb-rotor').closest('.wb-nastaveni-row').hidden;
                return o; }""")
            b.close()
    finally:
        srv.shutdown()
    assert r['shadowOpts'] == ['black, as the original', '0,75', '0,5']                   # labels, else the number in the menu's language
    assert r['screenOpts'][-1] == 'play64 (mění hru)' and r['livesLabel'] == 'Unlimited lives (mění hru)'
    assert r['inDebug'] and r['inDisplay'] and r['fadingHidden'] and r['fadingShown'] and r['ran'] == 1 and r['rotorHiddenInOriginal']
