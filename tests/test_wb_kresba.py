"""wb-kresba.js 1.0 (kit 1.0.87), 1.1 (kit 1.0.100: the view at compose()'s cam with margins, hardware sprites, the window layer): wb-scene's composition drawn from the game's state (decision 2026-11-17, docs/WB-KRESBA.md).
At a whole camera, alpha 1 and whole device pixels it is wb-scene's reference picture pixel for pixel; the shadow / flash
colours, the foreground cover, the extras after an object and a fractional camera are checked on their own pixels."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from arek import web

WEB = Path(web.__file__).parent

PAGE = r"""
(() => {
  const W = 48, H = 32, CY = 100, S = 2;
  let seed = 7; const rnd = () => (seed = (seed * 1103515245 + 12345) >>> 0) / 4294967296;
  const idx = new Uint8Array(W * H); for (let i = 0; i < idx.length; i++) idx[i] = Math.floor(rnd() * 16);
  const pal = new Uint8Array(H * 32 * 4);
  for (let r = 0; r < H; r++) for (let c = 0; c < 32; c++) { const q = (r * 32 + c) * 4; pal[q] = (c * 8 + r) & 255; pal[q + 1] = (r * 7) & 255; pal[q + 2] = (c * 3 + 50) & 255; pal[q + 3] = 255; }
  const pic = (w, h, f) => { const a = new Uint8Array(w * h); for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) a[y * w + x] = f(x, y); return a; };
  const ob1 = { id: 8, w: 6, h: 5, idx: pic(6, 5, (x, y) => (x + y) % 4 === 0 ? 255 : 16 + ((x * 3 + y) % 15)), x: 10, y: CY + 5, pass: 0 };
  const ob2 = { id: 16, w: 8, h: 3, idx: pic(8, 3, (x, y) => 17 + ((x + y) % 7)), x: 2, y: CY + 1, pass: 0, screen: true };
  const frame = (cam) => ({ n: 1, t: 0, cam, limits: { x0: 0, x1: 0, y0: 0, y1: 1000 }, window: { w: W, h: H, idx, pal }, objects: [ob1, ob2], sprites: [] });
  const terrain = (cy) => (wy, x0, w, out) => { const y = wy - cy; if (y < 0 || y >= H) return false; for (let i = 0; i < w; i++) { const x = x0 + i; out[i] = x >= 0 && x < W ? idx[y * W + x] : 0; } return true; };
  const K = WBKRESBA.create(document), cv = document.createElement('canvas');
  const draw = (c, game, opt) => { cv.width = Math.round(c.W * S); cv.height = Math.round(c.H * S); const g = cv.getContext('2d'); const r = K.paint(g, c, S, game, opt);
    return { px: g.getImageData(0, 0, cv.width, cv.height).data, r }; };
  const out = {};
  // 1. the reference: whole camera, alpha 1, whole device pixels
  const c = WBSCENE.compose([frame([0, CY])], 0, { S, extX: 0, extY: 0 }, {}, null), ref = WBSCENE.reference(c);
  const a = draw(c, { terrain: terrain(CY) }, { subpixel: false });
  let bad = 0; for (let i = 0; i < ref.length; i++) if (ref[i] !== a.px[i]) bad++;
  out.ref = { bad, n: ref.length, objs: c.objs.length, pos: a.r.pos };
  const at = (px, x, y) => Array.from(px.slice((y * c.W * S + x) * 4, (y * c.W * S + x) * 4 + 3));
  const palAt = (row, col) => Array.from(pal.slice((row * 32 + col) * 4, (row * 32 + col) * 4 + 3));
  // 2. a shadow (colour 0 of the row) and a flash (colour 9): object 8's pixel (1, 0) at world (11, 105) = window row 5
  const sh = draw(c, { terrain: terrain(CY), op: (ob) => ob.id === 8 ? 1 : ob.id === 16 ? 2 : 0 }, { subpixel: false });
  out.shadow = [at(sh.px, 11 * S, 5 * S), palAt(5, 0)];
  out.flash = [at(sh.px, 2 * S, 1 * S), palAt(1, 9)];
  // 3. behind the foreground: columns 11-12 covered - object 8's pixels there show the terrain
  const cov = draw(c, { terrain: terrain(CY), behind: (ob) => ob.id === 8, cover: (wy, x0, w, o) => { for (let i = 0; i < w; i++) o[i] = x0 + i === 11 || x0 + i === 12 ? 1 : 0; return true; } }, { subpixel: false });
  out.cover = [at(cov.px, 11 * S, 5 * S), palAt(5, idx[5 * W + 11]), at(cov.px, 13 * S, 5 * S), at(a.px, 13 * S, 5 * S)];
  // 4. after(): a 1 x 1 picture of colour 5 at the object's anchor + (2, 1), the object's palette rows
  const af = draw(c, { terrain: terrain(CY), after: (ob, put) => { if (ob.id === 8) put({ pix: new Uint8Array([5]), w: 1, h: 1, ox: 0, oy: 0 }, 'dot', 1, 2, 1); } }, { subpixel: false });
  out.after = [at(af.px, 12 * S, 6 * S), palAt(6, 5)];
  // 5. a fractional camera, a quarter of a game row: S = 2 -> half a device row, the two rows blended half and half
  const cf = WBSCENE.compose([frame([0, CY])], 0, { S, extX: 0, extY: 0 }, {}, null); cf.cam = [0, CY + 0.25];
  const fr = draw(cf, { terrain: terrain(CY) }, { subpixel: false });
  const col = 30, y0 = 20;   // device row 20 of the view at camera +0.5 device px: game row 10 (rows 20, 21 of row 10), blended with row 11 below
  out.blend = [at(fr.px, col * S, y0 + 1), palAt(10, idx[10 * W + col]), palAt(11, idx[11 * W + col])];
  // 6. a fractional camera on x (Turrican scrolls both ways): a quarter of a game column - device column 2 col + 1 blends col and col + 1
  const cx = WBSCENE.compose([frame([0, CY])], 0, { S, extX: 0, extY: 0 }, {}, null); cx.cam = [0.25, CY];
  const fx = draw(cx, { terrain: terrain(CY) }, { subpixel: false });
  out.blendX = [at(fx.px, col * S + 1, 8 * S), palAt(8, idx[8 * W + col]), palAt(8, idx[8 * W + col + 1]), at(fx.px, col * S, 8 * S)];
  return out;
})()
"""


def test_version_and_files():
    node = shutil.which('node')
    if not node:
        pytest.skip('no node')
    r = subprocess.run([node, '-e', "const K = require(%s); console.log(JSON.stringify([K.VERSION, typeof K.create, K.usedOf(new Uint8Array([1, 255, 3]))]))"
                        % json.dumps(str(WEB / 'wb-kresba.js'))], capture_output=True, text=True, check=True)
    assert json.loads(r.stdout) == ['1.1', 'function', 10] and 'wb-kresba.js' in web.FILES


def test_kresba_is_the_reference_and_its_colours_cover_and_blend():
    pytest.importorskip('playwright')
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            p = b.new_page()
            errs = []
            p.on('pageerror', lambda e: errs.append(str(e)))
            p.set_content('<!doctype html><html><body></body></html>')
            p.add_script_tag(path=str(WEB / 'wb-scene.js'))
            p.add_script_tag(path=str(WEB / 'wb-kresba.js'))
            out = p.evaluate(PAGE)
            b.close()
    except Exception as e:
        if 'Executable doesn' in str(e) or 'playwright install' in str(e):
            pytest.skip('no chromium for playwright')
        raise
    assert not errs, errs
    ref = out['ref']
    assert ref['bad'] == 0 and ref['n'] == 48 * 2 * 32 * 2 * 4 and ref['objs'] == 2, ref
    assert sorted(p[0] for p in ref['pos']) == [8, 16] and [p for p in ref['pos'] if p[0] == 8][0][1:] == [10, 105]   # where each object was drawn: its logical anchor
    assert out['shadow'][0] == out['shadow'][1] and out['flash'][0] == out['flash'][1], out
    assert out['cover'][0] == out['cover'][1] and out['cover'][2] == out['cover'][3], out['cover']   # covered: the terrain; next to it the object as before
    assert out['after'][0] == out['after'][1], out['after']
    got, a, b2 = out['blend']
    assert all(abs(g - (x + y) / 2) <= 1 for g, x, y in zip(got, a, b2)) and a != b2, out['blend']
    got, a, b2, left = out['blendX']
    assert all(abs(g - (x + y) / 2) <= 1 for g, x, y in zip(got, a, b2)) and a != b2 and left == a, out['blendX']


PAGE11 = r"""
(() => {
  // 1.1 (Turrican II KIT-GAP): margins (ext), hardware sprites, the window layer - each the reference pixel for pixel
  const W = 48, H = 32, CX = 20, CY = 100, S = 2;
  let seed = 11; const rnd = () => (seed = (seed * 1103515245 + 12345) >>> 0) / 4294967296;
  const idx = new Uint8Array(W * H); for (let i = 0; i < idx.length; i++) idx[i] = 1 + Math.floor(rnd() * 15);
  const pal = new Uint8Array(H * 32 * 4);   // colour 0 black: the reference shows black where nothing is, the terrain's false is colour 0
  for (let r = 0; r < H; r++) for (let c = 0; c < 32; c++) { const q = (r * 32 + c) * 4; pal[q] = c ? (c * 8 + r) & 255 : 0; pal[q + 1] = c ? (r * 7 + 1) & 255 : 0; pal[q + 2] = c ? (c * 3 + 50) & 255 : 0; pal[q + 3] = 255; }
  const pic = (w, h, f) => { const a = new Uint8Array(w * h); for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) a[y * w + x] = f(x, y); return a; };
  const ob = { id: 8, w: 6, h: 5, idx: pic(6, 5, (x, y) => (x + y) % 4 === 0 ? 255 : 16 + ((x * 3 + y) % 15)), x: CX + 10, y: CY + 5, pass: 0 };
  const sprW = { k: 1, h: 6, idx: pic(16, 6, (x, y) => x < 5 && y > 0 ? 17 + ((x + y) % 3) : 255), x: 30, y: 7 };            // with the ground
  const sprS = { k: 0, h: 3, idx: pic(16, 3, (x, y) => x > 9 ? 25 + y : 255), x: 2, y: 2, screen: true };                    // fixed on the screen
  const over = new Uint8Array(W * H).fill(255); for (let x = 3; x < 9; x++) over[4 * W + x] = 30;
  const frame = (sprites, ov) => ({ n: 1, t: 0, cam: [CX, CY], limits: { x0: -100, x1: 100, y0: 0, y1: 1000 }, window: Object.assign({ w: W, h: H, idx, pal }, ov ? { over: ov } : {}), objects: [ob], sprites });
  const terrain = (wy, x0, w, out) => { const y = wy - CY; if (y < 0 || y >= H) return false; for (let i = 0; i < w; i++) { const x = x0 + i - CX; out[i] = x >= 0 && x < W ? idx[y * W + x] : 0; } return true; };
  const junk = (wy, x0, w, out) => { const y = wy - CY; if (y < 0 || y >= H) return false; for (let i = 0; i < w; i++) { const x = x0 + i - CX; out[i] = x >= 0 && x < W ? 7 : 0; } return true; };
  const K = WBKRESBA.create(document), cv = document.createElement('canvas');
  const cmp = (c, game, opt) => { const ref = WBSCENE.reference(c); cv.width = Math.round(c.W * S); cv.height = Math.round(c.H * S); const g = cv.getContext('2d'); K.paint(g, c, S, game, Object.assign({ subpixel: false }, opt));
    const px = g.getImageData(0, 0, cv.width, cv.height).data; let bad = 0; for (let i = 0; i < ref.length; i++) if (ref[i] !== px[i]) bad++; return { bad, n: ref.length, px, W: c.W }; };
  const out = {};
  const c1 = WBSCENE.compose([frame([])], 0, { S, extX: 8, extY: 4 }, {}, null);
  out.margins = (({ bad, n }) => ({ bad, n, cam: c1.cam }))(cmp(c1, { terrain }));
  const c2 = WBSCENE.compose([frame([sprW, sprS])], 0, { S, extX: 8, extY: 4 }, {}, null);
  const s2 = cmp(c2, { terrain }), s2off = cmp(c2, { terrain }, { sprites: false });
  out.sprites = { bad: s2.bad, sprs: c2.sprs.length, off: s2off.bad, drawn: K.st.sprs };
  const c3 = WBSCENE.compose([frame([], over)], 0, { S, extX: 8, extY: 4 }, {}, null);
  out.over = { on: cmp(c3, { terrain }, { window: 'over' }).bad, off: cmp(c3, { terrain }).bad, all: cmp(c3, { terrain: junk }, { window: 'all' }).bad, junkOver: cmp(c3, { terrain: junk }, { window: 'over' }).bad };
  return out;
})()
"""


def test_kresba_1_1_margins_sprites_and_the_window_are_the_reference():
    pytest.importorskip('playwright')
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            p = b.new_page()
            errs = []
            p.on('pageerror', lambda e: errs.append(str(e)))
            p.set_content('<!doctype html><html><body></body></html>')
            p.add_script_tag(path=str(WEB / 'wb-scene.js'))
            p.add_script_tag(path=str(WEB / 'wb-kresba.js'))
            out = p.evaluate(PAGE11)
            b.close()
    except Exception as e:
        if 'Executable doesn' in str(e) or 'playwright install' in str(e):
            pytest.skip('no chromium for playwright')
        raise
    assert not errs, errs
    m = out['margins']
    assert m['bad'] == 0 and m['n'] == 64 * 2 * 40 * 2 * 4 and m['cam'] == [12, 96], m   # 1.0 drew the view ext px off (23 204 bytes in this probe)
    sp = out['sprites']
    assert sp['bad'] == 0 and sp['sprs'] == 2 and sp['off'] > 0 and sp['drawn'] >= 2, sp   # both sprites as the reference; without them it differs
    ov = out['over']
    assert ov['on'] == 0 and ov['off'] > 0 and ov['all'] == 0 and ov['junkOver'] > 0, ov   # 'over' / 'all' = the reference's playfield; default off
