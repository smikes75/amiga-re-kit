"""wb-mixer.js 1.0 (kit 1.0.93, SWIV): the sound mixer window - the state and the engine's levels in Node, the window in
Chromium. Synthetic groups, no game data."""
import json
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

WEB = Path(__file__).parent.parent / 'src' / 'arek' / 'web'
node = shutil.which('node')
GROUPS = "[{ id: 'fire', label: 'player shots' }, { id: 'expl', label: { en: 'explosions', cs: 'výbuchy' } }, { id: 'jet' }]"
DEFAULTS = "{ master: 1.35, extra: 0.95, fire: 2, expl: 0.7 }"


def js(expr):
    if not node:
        pytest.skip('no node')
    code = ("const X = require(%s); const box = {}; globalThis.localStorage = { getItem: (k) => box[k] ?? null, "
            "setItem: (k, v) => { box[k] = String(v); } }; const r = (%s); console.log(JSON.stringify(r));") % (json.dumps(str(WEB / 'wb-mixer.js')), expr)
    return json.loads(subprocess.run([node, '-e', code], capture_output=True, text=True, check=True).stdout)


def test_values_defaults_and_the_players_own():
    """A row never moved follows the page's default (1 without one); set / unset / reset('unity' | 'defaults'); values
    coerced to 0..2 in 5 % steps; the store keeps only the player's own values, so new defaults reach old visitors."""
    r = js("""(() => { const spec = { groups: %s, defaults: %s, store: 'g-mix' }, m = X.build(null, spec), o = [];
        o.push(m.get(), m.testHooks().ids());
        m.set('jet', 0.43); m.set('fire', 9); m.set('nope', 1); m.set('expl', 'x'); o.push(m.get());
        const again = X.build(null, Object.assign({}, spec, { defaults: { master: 1, fire: 1.5 } })); o.push(again.get());
        again.unset('jet'); o.push(again.get().jet);
        again.reset('unity'); o.push(again.get());
        again.reset('defaults'); o.push(again.get(), JSON.parse(localStorage.getItem('g-mix')));
        return o; })()""" % (GROUPS, DEFAULTS))
    assert r[0] == {'master': 1.35, 'extra': 0.95, 'fire': 2, 'expl': 0.7, 'jet': 1}
    assert r[1] == ['master', 'extra', 'fire', 'expl', 'jet']
    assert r[2] == {'master': 1.35, 'extra': 0.95, 'fire': 2, 'expl': 0.7, 'jet': 0.45}          # 9 -> 2, 0.43 -> 0.45, junk ignored
    assert r[3] == {'master': 1, 'extra': 1, 'fire': 2, 'expl': 1, 'jet': 0.45}                    # own values kept, the rest new defaults
    assert r[4] == 1
    assert r[5] == {'master': 1, 'extra': 1, 'fire': 1, 'expl': 1, 'jet': 1}
    assert r[6] == {'master': 1, 'extra': 1, 'fire': 1.5, 'expl': 1, 'jet': 1} and r[7] == {'version': '1.0', 'own': {}}


def test_engine_levels_apply_and_original():
    """levels(): kind i = master * group, kind 32 + i = master * extra * group (at most 4), the rest 1; Original: all 1.
    apply(fn) sends only the kinds that changed (all 64 the first time)."""
    r = js("""(() => { const m = X.build(null, { groups: %s, defaults: %s }), sent = [], o = [];
        const lv = m.levels(); o.push([lv[0], lv[1], lv[2], lv[3], lv[32], lv[33], lv[34], lv[35], lv[63]].map((x) => +x.toFixed(6)));
        o.push(m.apply((k, v) => sent.push([k, v])));
        o.push(m.apply((k, v) => sent.push([k, v])));
        m.set('expl', 0); o.push(m.apply((k, v) => sent.push([k, +v.toFixed(6)])), sent.slice(64));
        m.set('master', 2); m.set('fire', 2); m.set('extra', 2); o.push(m.levels()[0], m.levels()[32]);
        m.setMode('original'); o.push(Array.from(m.levels()).every((x) => x === 1), m.get().fire);
        return o; })()""" % (GROUPS, DEFAULTS))
    assert r[0] == [2.7, 0.945, 1.35, 1, 2.565, 0.89775, 1.2825, 1, 1]
    assert r[1] == 64 and r[2] == 0 and r[3] == 2 and r[4] == [[1, 0], [33, 0]]
    assert r[5] == 4 and r[6] == 4                                                                  # 2 * 2 (* 2) at most 4
    assert r[7] is True and r[8] == 2                                                               # Original: 1, the values stay


def test_lights_from_the_engines_counts():
    """lights(counts) (engine_aud_counts: int32 [64][3]) lights the groups whose counts moved since the last call - a
    group's Paula kind and its extra kind together; silenced over extra over played; the first call only takes note."""
    r = js("""(() => { const m = X.build(null, { groups: %s }), c = new Int32Array(192), o = [];
        c[0] = 5; o.push(m.lights(c));
        c[0] = 6; c[1 * 3 + 2] = 1; c[(32 + 2) * 3 + 1] = 1; o.push(m.lights(c));
        o.push(m.lights(c));
        c[(32 + 0) * 3 + 1] = 1; c[0] = 7; o.push(m.lights(c));
        return o; })()""" % GROUPS)
    assert r == [{}, {'fire': 'played', 'expl': 'silenced', 'jet': 'extra'}, {}, {'fire': 'extra'}]


def test_copy_text_and_bad_groups():
    """copyText(): the values that are not 100 %, as spec.defaults takes them; group ids unique, not master / extra, 32 at most."""
    r = js("""(() => { const m = X.build(null, { groups: %s, defaults: %s, name: 'TEST' }); m.set('jet', 0.5);
        const bad = [[{ id: 'master' }], [{ id: 'a' }, { id: 'a' }], [{}], Array.from({ length: 33 }, (_, i) => ({ id: 'g' + i }))].map((groups) => {
            try { X.build(null, { groups }); return 'built'; } catch (e) { return e.message; } });
        return [m.copyText(), bad, X.build(null, { groups: %s, extra: false }).testHooks().ids()]; })()""" % (GROUPS, DEFAULTS, GROUPS))
    assert r[0] == 'TEST mixer {"master":1.35,"extra":0.95,"fire":2,"expl":0.7,"jet":0.5}'
    assert 'taken' in r[1][0] and 'taken' in r[1][1] and 'without an id' in r[1][2] and 'at most 32' in r[1][3]
    assert r[2] == ['master', 'fire', 'expl', 'jet']


def test_the_window_in_the_browser(tmp_path):
    """The window: a row per value with its lamp, name, slider and value; a slider sets the value, a double-click gives the
    row its default, "all 100 %" and "defaults"; a changed row is marked; Original disables the sliders; Esc closes and
    gives the focus back to the game; a lamp lights; Czech texts; the state survives a reload."""
    pw = pytest.importorskip('playwright.sync_api')
    from arek import web
    shutil.copy(WEB / 'wb-mixer.js', tmp_path / 'wb-mixer.js')
    shutil.copy(WEB / 'wb.css', tmp_path / 'wb.css')
    (tmp_path / 'mix.html').write_text("""<!doctype html><meta charset="utf-8"><link rel="stylesheet" href="wb.css">
<canvas id="game" tabindex="0" width="32" height="32"></canvas><script src="wb-mixer.js"></script><script>
window.mixer = WBMIXER.build(undefined, { groups: %s, defaults: %s, store: 'b-mix', lang: 'cs', focusGame: () => document.getElementById('game').focus() });
</script>""" % (GROUPS, DEFAULTS))
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
            pg.goto('http://127.0.0.1:%d/mix.html' % port)
            r = pg.evaluate("""() => { const q = (s) => document.querySelector(s), o = {};
                o.hidden = q('.wb-mixer').hidden; mixer.open(); o.open = !q('.wb-mixer').hidden;
                o.names = [...document.querySelectorAll('.wb-mixer-name')].map((e) => e.textContent);
                o.values = [...document.querySelectorAll('.wb-mixer-value')].map((e) => e.textContent);
                o.changed = [...document.querySelectorAll('.wb-mixer-row.changed')].map((e) => e.dataset.mix);
                const s = q('#wb-mix-jet'); s.value = '150'; s.dispatchEvent(new Event('input'));
                o.jet = mixer.get().jet; o.jetChanged = q('[data-mix=jet]').classList.contains('changed');
                mixer.set('fire', 0.5); q('[data-mix=fire]').dispatchEvent(new MouseEvent('dblclick', { bubbles: true })); o.fire = mixer.get().fire;
                q('.wb-mixer-unity').click(); o.unity = Object.values(mixer.get()).every((v) => v === 1);
                o.unityValues = [...document.querySelectorAll('.wb-mixer-value')].map((e) => e.textContent);
                q('.wb-mixer-defaults').click(); o.defaults = mixer.get().fire;
                s.value = '50'; s.dispatchEvent(new Event('input'));
                mixer.setMode('original'); o.disabled = [...document.querySelectorAll('.wb-mixer-row input')].every((e) => e.disabled);
                o.note = q('.wb-mixer-note').textContent; mixer.setMode('enhanced'); o.enabled = !s.disabled;
                const c = new Int32Array(192); mixer.lights(c); c[(32 + 1) * 3 + 2] = 1; mixer.lights(c);
                o.lamp = q('[data-mix=expl] .wb-mixer-light').dataset.light;
                o.box = q('.wb-mixer').getBoundingClientRect().width;
                return o; }""")
            pg.keyboard.press('Escape')
            r['afterEsc'] = pg.evaluate("() => [document.querySelector('.wb-mixer').hidden, document.activeElement.id]")
            pg.reload()
            r['reload'] = pg.evaluate("() => mixer.get().jet")
            b.close()
    finally:
        srv.shutdown()
    assert r['hidden'] and r['open']
    assert r['names'] == ['celková hlasitost', 'hlasy navíc', 'player shots', 'výbuchy', 'jet']
    assert r['values'] == ['135 %', '95 %', '200 %', '70 %', '100 %'] and r['changed'] == []
    assert r['jet'] == 1.5 and r['jetChanged'] and r['fire'] == 2
    assert r['unity'] and r['unityValues'] == ['100 %'] * 5 and r['defaults'] == 2
    assert r['disabled'] and r['note'].startswith('Originál') and r['enabled']
    assert r['lamp'] == 'silenced' and 300 < r['box'] <= 420
    assert r['afterEsc'] == [True, 'game'] and r['reload'] == 0.5
