"""wb-scene.js (the canon's scene, module G, kit 0.9.0): the pure parts in Node (the view camera inside the game's
limits, the means that soften a stop and smooth the vertical camera, the pairs by identity with older frames, the
CPU reference composition), and in Chromium the GPU band against that reference pixel for pixel on the synthetic
page, with `arek web smooth` over it. No game data."""
import json
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

from arek import web

WEB = Path(web.__file__).parent
node = shutil.which('node')


def js(expr):
    if not node:
        pytest.skip('no node')
    code = "const S = require(%s); const r = (%s); console.log(JSON.stringify(r));" % (json.dumps(str(WEB / 'wb-scene.js')), expr)
    return json.loads(subprocess.run([node, '-e', code], capture_output=True, text=True, check=True).stdout)


def test_version_and_files():
    assert js('S.VERSION') == '1.1' and 'wb-scene.js' in web.FILES and (WEB / 'scene-demo.html').exists()


def test_view_camera_inside_the_limits():
    lim, win, ext = '{x0: 0, x1: 1000, y0: 0, y1: 500}', '{w: 320, h: 200}', '{x: 64, y: 16}'
    assert js('S.clampCam(100, 50, %s, %s, %s)' % (lim, win, ext)) == [36, 34]            # the window minus the extension
    assert js('S.clampCam(10, 5, %s, %s, %s)' % (lim, win, ext)) == [0, 0]               # stopped at the map's edge
    assert js('S.clampCam(990, 495, %s, %s, %s)' % (lim, win, ext)) == [1000 + 320 - 448, 500 + 200 - 232]
    assert js('S.clampCam(0, 0, {x0: 0, x1: 0, y0: 0, y1: 0}, %s, %s)' % (win, ext)) == [-64, -16]   # a map narrower than the view: centred


def test_window_mean_over_the_interpolated_value():
    """1.1 (Superfrog KIT-GAPS 41): the mean is taken over the value interpolated between the frames and sampled every
    5 ms, not over the 2 or 3 frames that happen to fall into the window; past the newest frame the value continues
    with the last velocity for at most tau; 'past' = a triangle over the last tau ms (the vertical smoothing)."""
    fr = '[{t: 0, v: 0}, {t: 20, v: 10}, {t: 40, v: 20}]'
    assert js('S.windowMean(%s, 20, 20, (f) => f.v)' % fr) == 10                               # a ramp: its middle
    assert abs(js('S.windowMean(%s, 60, 20, (f) => f.v)' % fr) - 245 / 9) < 1e-9             # 40..80: 20, 22.5, 25, 27.5, then 30 (capped at tau)
    assert js('S.windowMean(%s, 200, 20, (f) => f.v)' % fr) == 30                              # far past the newest: tau only
    assert js('S.windowMean(%s, 40, 20, (f) => f.v, { shape: "past" })' % fr) == 17.5          # the triangle over 20..40 of the ramp
    assert js('[S.valueAt(%s.map((x) => x), 10, (f) => f.v, 20), S.valueAt(%s, -5, (f) => f.v, 20), S.valueAt(%s, 50, (f) => f.v, 20)]' % (fr, fr, fr)) == [5, 0, 25]
    assert js('S.windowMean([], 5, 20, (f) => f.v)') is None
    # a phase test: the mean must not jump by 2.5 px when a third frame enters the window (the old mean of the frames did)
    seq = js('(() => { const fr = []; for (let i = 0; i < 12; i++) fr.push({ t: i * 20, v: i * 10 }); const out = []; for (let t = 100; t <= 140; t += 4) out.push(S.windowMean(fr, t, 20, (f) => f.v)); return out; })()')
    steps = [b - a for a, b in zip(seq, seq[1:])]
    assert max(steps) - min(steps) < 1e-9 and abs(steps[0] - 2) < 1e-9                        # 4 ms at 0.5 px/ms = 2 px, every step


def test_pairs_by_identity_with_older_frames():
    r = js("""S.pairById({t: 0, objects: [{id: 1, x: 0}]}, {t: 20, objects: [{id: 1, x: 10}, {id: 2, x: 5}]}, 0.5, (f) => f.objects, 2,
              [{t: -40, objects: [{id: 2, x: 1}]}, {t: -20, objects: []}])""")
    assert r[0]['from']['x'] == 0 and r[0]['f'] == 0.5
    assert r[1]['from']['x'] == 1 and abs(r[1]['f'] - 50 / 60) < 1e-9     # a blinking thing: paired with the frame two back
    r = js("S.pairById({t: 0, objects: []}, {t: 20, objects: [{id: 9, x: 3}]}, 0.5, (f) => f.objects, 0, [{t: -20, objects: [{id: 9, x: 0}]}])")
    assert r[0]['from'] is None and r[0]['f'] == 1                         # without pairOlder: drawn where it is


def test_colours_and_hud_widening():
    assert js('S.x17(0xfff)') == [255, 255, 255, 255] and js('S.x17(0x123)') == [17, 34, 51, 255]
    assert js('Array.from(S.widenColumns(4, 8, [1]))') == [0, 1, 1, 1, 1, 1, 2, 3]   # the cut column repeats
    assert js('Array.from(S.widenColumns(4, 4, [1]))') == [0, 1, 2, 3]
    assert js('S.fnv1a(new Uint8Array([1, 2, 3]))') == js('S.fnv1a(new Uint8Array([1, 2, 3]))') != js('S.fnv1a(new Uint8Array([1, 2, 4]))')


REC = """(() => { const pal = new Uint8Array(2 * 32 * 4); for (let r = 0; r < 2; r++) for (let i = 0; i < 32; i++) { pal[(r * 32 + i) * 4] = i * 10; pal[(r * 32 + i) * 4 + 1] = r; pal[(r * 32 + i) * 4 + 3] = 255; }
    const win = { w: 4, h: 2, idx: new Uint8Array([1, 255, 1, 1, 1, 1, 1, 1]), pal };
    const map = { gen: 1, atlas: new Uint8Array(256).fill(2), nslots: 1, dirty: null, cols: 8, rows: 8, cells: new Uint16Array(64).fill(0), origin: [0, 0] };
    const mk = (n, t, cam, ox, lim) => ({ n, t, cam, limits: lim || { x0: 0, x1: 100, y0: 0, y1: 100 }, window: win, map,
        objects: [{ id: 7, w: 2, h: 1, idx: new Uint8Array([3, 255]), x: ox, y: 0, pass: t }], sprites: [{ k: 0, h: 1, idx: new Uint8Array(16).fill(255).map((v, i) => i === 0 ? 4 : 255), x: 2, y: 0 }] });
    return { mk }; })()"""


def with_mk(body):
    return '(() => { const mk = ' + REC + '.mk; return ' + body + '; })()'


def test_reference_composition_rules():
    """The window's index where it has one, the map through a 255 hole, black outside the limits; the object on top (255
    transparent), the sprite on top of the object; the palette row of the window row."""
    r = js(with_mk("""(() => { const rec = mk(1, 0, [0, 0], 1); const c = S.compose([rec], 0, { S: 1, extX: 0, extY: 0 }, {}, null); const px = S.reference(c);
        const R = (x, y) => px[(y * c.W + x) * 4], G = (x, y) => px[(y * c.W + x) * 4 + 1]; return [R(0, 0), R(1, 0), R(2, 0), R(3, 0), G(0, 1), c.W, c.H]; })()"""))
    assert r == [10, 30, 40, 10, 1, 4, 2]
    r = js(with_mk("""(() => { const rec = mk(1, 0, [0, 0], 9, { x0: 0, x1: 0, y0: 0, y1: 100 }); const c = S.compose([rec], 0, { S: 1, extX: 2, extY: 0 }, {}, null); const px = S.reference(c);
        const R = (x, y) => px[(y * c.W + x) * 4]; return [c.cam, R(0, 0), R(2, 0), R(3, 0), R(7, 0)]; })()"""))
    assert r[0] == [-2, 0] and r[1] == 0 and r[2] == 10 and r[3] == 20 and r[4] == 20   # a map as wide as the window, centred: black left of it, the hole shows the map (idx 2), the margin from the map
    r = js(with_mk("""(() => { const rec = mk(1, 0, [0, 0], 9); const c = S.compose([rec], 0, { S: 1, extX: 2, extY: 0 }, {}, null); return c.cam; })()"""))
    assert r == [0, 0]                                                                   # a wide map: the view stops at the game's limit, never left of it
    r = js(with_mk("""(() => { const a = mk(1, 0, [0, 0], 0), b = mk(2, 20, [4, 0], 4); const c = S.compose([a, b], 10, { S: 2, extX: 0, extY: 0 }, {}, null);
        return [c.f, c.cam, c.objs[0].x, c.sprs[0].x, S.reference(c).length]; })()"""))
    assert r == [0.5, [2, 0], 2, 4, 4 * 2 * 2 * 2 * 4]                                  # half way: camera, object and the sprite's world x interpolated


def test_screen_sprites_over_layer_and_pass_guard():
    """1.1: a sprite with screen = true stays in the view's corner whatever the clamp does (KIT-GAPS 40); window.over is
    the game's own drawings over the clean window, above the terrain and below the objects (42); a pass that never
    changes for longer than passMax makes every frame a pass (43)."""
    r = js(with_mk("""(() => { const a = mk(1, 0, [0, 0], 0, { x0: 0, x1: 0, y0: 0, y1: 100 }); a.sprites.push({ k: 1, h: 1, idx: new Uint8Array(16).fill(255).map((v, i) => i === 0 ? 5 : 255), x: 1, y: 0, screen: true });
        const c = S.compose([a], 0, { S: 1, extX: 2, extY: 0 }, {}, null); const px = S.reference(c); const R = (x) => px[x * 4];
        return [c.cam, c.sprs.map((s) => [s.x, s.y, !!s.screen]), R(0), R(1), R(2), R(3)]; })()"""))
    assert r[0] == [-2, 0] and [s for s in r[1] if s[2]] == [[1, 0, True]]                  # the badge at window px 1 = view px 3 = world x 1; the frog in the world
    assert r[2] == 0 and r[3] == 0 and r[4] == 30 and r[5] == 50                             # black, black, the object (idx 3) over the window, the badge (idx 5) over the object's hole
    r = js(with_mk("""(() => { const a = mk(1, 0, [0, 0], 9); a.window = Object.assign({}, a.window, { over: new Uint8Array([255, 255, 255, 6, 255, 255, 255, 255]) });
        const c = S.compose([a], 0, { S: 1, extX: 0, extY: 0 }, {}, null); const px = S.reference(c); return [px[3 * 4], px[0], px[1 * 4], px[2 * 4]]; })()"""))
    assert r == [60, 10, 20, 40]                                                              # over idx 6 at x 3 beats the window's idx 1; the window, the map hole and the sprite (x 2) untouched
    r = js(with_mk("""(() => { const fr = []; for (let i = 0; i < 10; i++) { const f = mk(i + 1, i * 20, [0, 0], i); f.pass = 0; fr.push(f); }
        const guard = S.compose(fr, 170, { S: 1 }, {}, null), none = S.compose(fr, 170, { S: 1 }, { passMax: 0 }, null);
        return [guard.OA.n, guard.OB.n, none.OA.n, none.OB.n]; })()"""))
    assert r[0] >= 6 and r[1] == r[0] + 1 and r[2] == 1 and r[3] == 1                         # with the guard the objects follow the frames; without it the stale pass


def test_options_fixed_axis_soft_clamp_and_smoothing():
    r = js(with_mk("""(() => { const fr = [mk(1, 0, [0, 0], 0), mk(2, 20, [0, 10], 0), mk(3, 40, [0, 20], 0)];
        const fixed = S.compose(fr, 20, { S: 1 }, { fixedAxis: { axis: 'y', value: 3 } }, null);
        const smooth = S.compose(fr, 40, { S: 1 }, { smoothY: { tau: 20 } }, null);
        const plain = S.compose(fr, 40, { S: 1 }, {}, null);
        return [fixed.cam, smooth.cam, smooth.spriteCam, plain.cam]; })()"""))
    assert r[0] == [0, 3] and r[3] == [0, 20]
    assert abs(r[1][1] - 17.5) < 1e-9 and r[2][1] == 20                                # the terrain's camera a past triangle over tau, the sprites keep the game's
    r = js(with_mk("""(() => { const fr = [mk(1, 0, [-30, 0], 0), mk(2, 20, [-10, 0], 0), mk(3, 40, [0, 0], 0)];
        const soft = S.compose(fr, 50, { S: 1, extX: 0 }, { softClamp: { tau: 20 } }, null), hard = S.compose(fr, 50, { S: 1, extX: 0 }, {}, null);
        return [hard.cam, soft.cam]; })()"""))
    assert r[0] == [0, 0] and r[1] == [0, 0]                                           # all clamped frames are 0: the mean is 0 too (no overshoot)


def _run_page(url_tail, fn):
    pytest.importorskip('playwright')
    from playwright.sync_api import sync_playwright
    srv = web.serve(str(WEB), 0, isolated=True)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            p = b.new_page(viewport={'width': 1100, 'height': 700})
            errs = []
            p.on('pageerror', lambda e: errs.append(str(e)))
            p.goto('http://127.0.0.1:%d/scene-demo.html%s' % (port, url_tail))
            p.wait_for_function('globalThis.WBLONGRUN && WBLONGRUN.ready()', timeout=20000)
            out = fn(p)
            b.close()
            assert not errs, errs
            return out
    finally:
        srv.shutdown()


@pytest.mark.parametrize('tail', ['?s=1', '?s=2&pair=2&soft=1&smooth=1'])
def test_gpu_equals_the_reference(tail):
    """The GPU band against the CPU reference of the same composition, pixel for pixel, while the camera moves and the
    objects interpolate (as Alien Breed II checked its WebGL path: 0 of 60 M pixels)."""
    def go(p):
        p.keyboard.down('ArrowRight')
        p.wait_for_timeout(600)
        res = [p.evaluate('wbSceneTest.compare()') for _ in range(4)]
        p.keyboard.up('ArrowRight')
        return res, p.evaluate('wbSceneTest.gl()')
    res, gl = _run_page(tail, go)
    if not gl:
        pytest.skip('no WebGL2 in this Chromium')
    for r in res:
        assert r['bad'] == 0 and r['pixels'] > 100000 and r['objs'] >= 2 and r['sprs'] == 2, r      # the frog and the screen-fixed badge


def test_smooth_on_the_scene_page():
    """`arek web smooth` over the synthetic scene: no dropped frames, objects on the screen without jitter beyond 1/S."""
    pytest.importorskip('playwright')
    from arek import websmooth
    srv = web.serve(str(WEB), 0, isolated=True)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        r = websmooth.run('http://127.0.0.1:%d/scene-demo.html?s=2&pair=2' % port, seconds=3, browsers=('chromium',), stalls=1, stall_ms=50, log=lambda *a: None)['chromium']
    finally:
        srv.shutdown()
    assert 'error' not in r, r
    assert r['frames'] > 100 and r['cam_moving'] > 50 and r['missing_pct'] == 0, r
    assert r['obj_jitter'] < 0.05 and r['cam_jitter'] < 0.05, (r['obj_jitter'], r['cam_jitter'], r['fails'])
