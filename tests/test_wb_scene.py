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
    assert js('S.VERSION') == '1.6' and 'wb-scene.js' in web.FILES and (WEB / 'scene-demo.html').exists()


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


def test_jumps_sprite_ids_and_the_symmetric_mean():
    """1.2 (Superfrog KIT-GAPS 44-46): a camera jump (a teleport after a death) is shown, not crossed - and so are jumps
    of objects and sprites; sprites[].id pairs several runs of one sprite number; camMean smooths both axes with a
    symmetric mean (no lag on a ramp) while the sprites keep the original's screen position plus the hard stop."""
    r = js(with_mk("""(() => { const a = mk(1, 0, [110, 0], 0), b = mk(2, 20, [2000, 0], 200); b.limits = a.limits = { x0: 0, x1: 5000, y0: 0, y1: 0 };
        const mid = S.compose([a, b], 10, { S: 1 }, {}, null), off = S.compose([a, b], 10, { S: 1 }, { jumpMax: 0 }, null);
        const near = S.compose([a, mk(2, 20, [2000, 0], 9)], 10, { S: 1 }, {}, null);
        return [mid.cam[0], mid.objs[0].x, mid.sprs[0].x, off.cam[0], off.objs[0].x, near.objs[0].x]; })()"""))
    assert r[0] == 2000 and r[1] == 200 and r[2] == 2002 and r[3] == 1055 and r[4] == 100   # shown at B; without the guard crossed half way
    assert r[5] == 4.5                                                                      # an object that moved 9 px still interpolates while the camera jumped
    r = js(with_mk("""(() => { const a = mk(1, 0, [0, 0], 0), b = mk(2, 20, [0, 0], 0);
        a.sprites = [{ k: 0, id: 'frog', h: 1, idx: a.sprites[0].idx, x: 10, y: 0 }, { k: 0, id: 'rest', h: 1, idx: a.sprites[0].idx, x: 100, y: 0 }];
        b.sprites = [{ k: 0, id: 'rest', h: 1, idx: a.sprites[0].idx, x: 100, y: 0 }, { k: 0, id: 'frog', h: 1, idx: a.sprites[0].idx, x: 20, y: 0 }];
        const c = S.compose([a, b], 10, { S: 1 }, {}, null); return c.sprs.map((s) => [s.s.id, s.x]); })()"""))
    assert sorted(r) == [['frog', 15], ['rest', 100]]                                       # paired by id, not by the shared k
    r = js(with_mk("""(() => { const fr = []; for (let i = 0; i < 8; i++) fr.push(mk(i + 1, i * 20, [i * 10, 0], 0));
        const m = S.compose(fr, 70, { S: 1 }, { camMean: { tau: 20 } }, null), p = S.compose(fr, 70, { S: 1 }, {}, null);
        const turn = []; for (let i = 0; i < 8; i++) turn.push(mk(i + 1, i * 20, [Math.min(i, 6 - i) * 10, 0], 0));   // up to 30 at t = 60, then back
        const t = S.compose(turn, 60, { S: 1 }, { camMean: { tau: 20 } }, null);
        return [m.cam, p.cam, m.spriteCam, t.cam[0], t.spriteCam[0]]; })()"""))
    assert r[0] == r[1] == [35, 0] and r[2] == [35, 0]                                      # a ramp: the symmetric mean has no lag
    assert r[3] < 30 and r[4] == 30                                                         # at a turn the terrain's camera rounds the corner, the sprites keep the game's


def test_subpixel_shift_of_the_playfield():
    """1.5: with subpixel the composition carries the snapped camera and the weights; the reference blends the playfield's
    device pixels by them (x, y and both), objects and sprites stay where the plain drawing puts them; on a whole device
    pixel the two drawings are identical."""
    body = """(() => { const a = mk(1, 0, [0, 0], 50), b = mk(2, 20, [1, %s], 50); const c = S.compose([a, b], %s, { S: 2 }, { subpixel: true }, null); const px = S.reference(c);
        const d = S.compose([a, b], %s, { S: 2 }, {}, null), py = S.reference(d); let same = px.length === py.length; for (let i = 0; same && i < px.length; i++) same = px[i] === py[i];
        const R = (x, y) => px[(y * c.W * 2 + x) * 4], G = (x, y) => px[(y * c.W * 2 + x) * 4 + 1];
        return { sub: c.sub, dsub: d.sub, cam: c.cam, same, obj: c.objs[0].x, r0: [0, 1, 2, 3, 4, 5, 6, 7].map((x) => R(x, 0)), r2: [0, 1, 2, 3, 4, 5, 6, 7].map((x) => R(x, 2)), r3: [R(3, 3), R(7, 2), G(1, 1), G(1, 3)] }; })()"""
    r = js(with_mk(body % (0, 5, 5)))                                                   # camera x 0.25 game px = 0.5 device px: wx = 128
    assert r['sub'] == {'cam': [0, 0], 'w': [128, 0]} and r['dsub'] is None and r['cam'] == [0.25, 0] and r['obj'] == 50 and r['same'] is False
    assert r['r0'] == [20, 15, 10, 15, 40, 40, 10, 10] and r['r2'] == [20, 15, 10, 10, 10, 10, 10, 10]   # the window's edges (it sits at B's camera, x 1) halfway between the colours; the sprite on top at 4, 5
    r = js(with_mk(body % (1, 5, 5)))                                                   # camera (0.25, 0.25): both weights 128, four taps
    assert r['sub'] == {'cam': [0, 0], 'w': [128, 128]} and r['r0'][:4] == [20, 20, 20, 20] and r['r3'] == [13, 10, 0, 1]   # (10 + 20 + 10 + 10 + 2) / 4; the palette row blends too
    r = js(with_mk(body % (1, 0, 0)))                                                   # on the device grid: the same picture as without the option
    assert r['sub'] == {'cam': [0, 0], 'w': [0, 0]} and r['same'] is True
    r = js(with_mk(body % (1, 20, 20)))
    assert r['sub'] == {'cam': [1, 1], 'w': [0, 0]} and r['same'] is True


def test_objects_move_with_the_ground_under_subpixel():
    """1.6: under subpixel an object is drawn into the shifted picture (its edge blends like the ground's), an object marked
    steady is drawn after the shift on whole device pixels relative to the view's camera."""
    body = """(() => { const a = mk(1, 0, [0, 0], 0), b = mk(2, 20, [1, 0], 0); if (%s) { a.objects[0].steady = true; b.objects[0].steady = true; }
        const c = S.compose([a, b], 5, { S: 2 }, { subpixel: true }, null); const px = S.reference(c); const R = (x, y) => px[(y * c.W * 2 + x) * 4];
        return { r0: [0, 1, 2, 3, 4, 5, 6, 7].map((x) => R(x, 0)), r2: [0, 1, 2].map((x) => R(x, 2)), obj: [c.objs[0].x, !!c.objs[0].o.steady] }; })()"""
    r = js(with_mk(body % 'false'))
    assert r['r0'] == [30, 20, 10, 15, 40, 40, 10, 10] and r['r2'] == [20, 15, 10] and r['obj'] == [0, False]   # the object's right edge halfway (30 -> 10) like the ground
    r = js(with_mk(body % 'true'))
    assert r['r0'] == [30, 30, 10, 15, 40, 40, 10, 10] and r['obj'] == [0, True]                                 # steady: sharp on whole pixels at round((0 - 0.25) * 2) = 0


def test_unexplained_pixels_of_the_window():
    """1.6: the model of the window (clean picture, map through the holes, the record's objects) against what the game drew:
    equal -> nothing; extra pixels -> over carries them; an object the game drew elsewhere -> both places differ."""
    r = js(with_mk("""(() => { const rec = mk(1, 0, [0, 0], 1); const game = new Uint8Array([1, 3, 1, 1, 1, 1, 1, 1]);
        const same = S.unexplained(rec, game), more = S.unexplained(rec, new Uint8Array([1, 3, 1, 5, 1, 1, 9, 1]));
        const moved = S.unexplained(mk(1, 0, [0, 0], 2), game), noMap = S.unexplained(Object.assign({}, rec, { map: null }), game);
        return [Array.from(same.model), same.count, Array.from(same.over), more.count, Array.from(more.over), moved.count, Array.from(moved.over), noMap.count, Array.from(noMap.model)]; })()"""))
    assert r[0] == [1, 3, 1, 1, 1, 1, 1, 1] and r[1] == 0 and r[2] == [255] * 8
    assert r[3] == 2 and r[4] == [255, 255, 255, 5, 255, 255, 9, 255]
    assert r[5] == 2 and r[6] == [255, 3, 1, 255, 255, 255, 255, 255]                 # the model has the object at 2 (over the hole's map at 1 it shows 2): the game's 3 at 1 and 1 at 2 are unexplained
    assert r[7] == 0 and r[8] == [1, 3, 1, 1, 1, 1, 1, 1]                            # without a map the hole would stay 255, but the object covers it at x 1


def test_object_drawing_offset():
    """1.3: objects[].ox/oy place the drawing relative to the object's logical position, which is what interpolates."""
    r = js(with_mk("""(() => { const a = mk(1, 0, [0, 0], 0), b = mk(2, 20, [0, 0], 2); a.objects[0].ox = 1; b.objects[0].ox = 1; a.sprites[0].x = 3; b.sprites[0].x = 3;
        const c = S.compose([a, b], 10, { S: 1 }, {}, null); const px = S.reference(c); return [c.objs[0].x, px[0], px[1 * 4], px[2 * 4], px[3 * 4]]; })()"""))
    assert r[0] == 1 and r[1] == 10 and r[2] == 20 and r[3] == 30 and r[4] == 40            # logical x 1 (half way 0 -> 2), the drawing at x 2; x 1 shows the map through the hole, the sprite at x 3


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


@pytest.mark.parametrize('tail', ['?s=1', '?s=2&pair=2&soft=1&smooth=1', '?s=2&pair=2&mean=1', '?s=2&pair=2&fine=1', '?s=3&mean=1&fine=1'])
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
        assert r['bad'] == 0 and r['pixels'] > 100000 and r['objs'] >= 2 and r['sprs'] == 2 and r['glErr'] == 0, r   # the frog and the screen-fixed badge; no GL error since the page's first draw (KIT-GAPS 50)
        assert ('fine' in tail) == (r['glued'] >= 1), r                                                              # 1.6: under the shift the objects (but the steady one) went with the ground


def test_sprites_above_the_hud_rows():
    """1.4 (Superfrog KIT-GAPS 49): with hud.under the HUD is drawn before the sprites, so a sprite reaching into the HUD
    rows shows above them (the hardware draws sprites over the playfield, HUD included); without it the HUD covers it."""
    pytest.importorskip('playwright')
    from PIL import Image
    import io
    def go(p):
        p.wait_for_timeout(400)
        box = p.locator('#screen').bounding_box()
        png = p.locator('#screen').screenshot()
        im = Image.open(io.BytesIO(png)).convert('RGB')
        S = p.evaluate('wbSceneTest.size().S')
        dpr = p.evaluate('window.devicePixelRatio') or 1
        # the frog's head: sprite x 152 + ext 64 = view px 216..231, rows -6..-1 of the band = the last rows of the top HUD (12 rows)
        x, y = int((216 + 8) * S * dpr), int((12 - 3) * S * dpr)
        return im.getpixel((x, y)), im.size, S
    (px_under, size, S) = _run_page('?s=1&under=1', go)
    (px_over, _, _) = _run_page('?s=1', go)
    assert px_under != px_over and px_under[2] > 100                 # the sprite's colour (index 30: blue-ish) over the HUD only with under
    assert px_over == (40, 120, 30) or px_over == (200, 120, 30)      # the HUD's own stripes otherwise


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
