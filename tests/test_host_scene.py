"""1.0.77: the scene recorder of the host (arek_scene.h) on a synthetic game - two ring buffers of 4 planes scrolled by the
Copper, a background ring the game restores from with copy blits, objects drawn with cookie-cut blits by one routine (the
hint), one of them in two parts, one with a shadow (a silhouette blit without B), one across the left edge (the previous
row's margin), pictures cut by the ring's end, and a score line in a fifth plane on the first lines. The display model
of the kit draws every frame; the record must explain the shown picture to the pixel (the clean playfield, the objects in
their order, the score line - nothing left for wb-scene's over), keep the camera's row continuous and place every object
where it was drawn, with its logical position from the hint. No game data."""
import json
import subprocess

import pytest

from arek import bus
from arek.host import __file__ as HOST_INIT
import os

HOST = os.path.dirname(HOST_INIT)

HARNESS = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#define MEMSZ 0x80000u
static uint8_t MEM[MEMSZ];
static uint16_t CREG[0x100];
typedef struct { uint32_t d[8], a[8]; } M68;
static uint32_t rd16_raw(uint32_t a) { return (uint32_t)((MEM[a & (MEMSZ - 1)] << 8) | MEM[(a + 1) & (MEMSZ - 1)]); }
static double h_now(void) { return 1000.0; }
static void (*h_pc_cb)(M68 *m, uint32_t pc) = 0;
static void (*h_wr_cb)(uint32_t off, uint32_t v) = 0;
#define H_IN_IRQ 0
#include "arek_display.h"
#include "arek_scene.h"

#define RR 130                 /* ring rows */
#define RB 44                  /* bytes a row: 40 shown + 4 margin */
#define PLSZ (RR * RB)
#define WH 96                  /* window lines: DIW $2C-$8C (a stop under $80 would be line 256 and more) */
#define BUF0 0x10000u
#define BUF1 0x20000u
#define CLN 0x30000u
#define HUDM 0x3f000u
#define IMG 0x40000u
#define NODES 0x60000u
#define COP0 0x70000u
#define COP1 0x71000u
#define OBJPC 0x1234u
#define SP 0x7f000u
static void w16(uint32_t a, uint16_t v) { MEM[a] = (uint8_t)(v >> 8); MEM[a + 1] = (uint8_t)v; }
static uint16_t r16(uint32_t a) { return (uint16_t)((MEM[a] << 8) | MEM[a + 1]); }
static M68 CPU;
static void wr(uint32_t off, uint16_t v) { if (h_wr_cb) h_wr_cb(off, v); CREG[off >> 1] = v; }
static void blit(uint16_t size) {        /* the runtime: the hook first, then the blit (area mode, ascending) */
    if (h_wr_cb) h_wr_cb(0x058, size);
    uint16_t c0 = CREG[0x40 >> 1], c1 = CREG[0x42 >> 1], fwm = CREG[0x44 >> 1], lwm = CREG[0x46 >> 1]; uint8_t mt = (uint8_t)c0;
    int h = size >> 6, w = size & 63, ash = c0 >> 12, bsh = c1 >> 12, ua = (c0 >> 11) & 1, ub = (c0 >> 10) & 1, uc = (c0 >> 9) & 1;
    uint32_t pa = ((uint32_t)CREG[0x50 >> 1] << 16) | CREG[0x52 >> 1], pb = ((uint32_t)CREG[0x4c >> 1] << 16) | CREG[0x4e >> 1],
             pc = ((uint32_t)CREG[0x48 >> 1] << 16) | CREG[0x4a >> 1], pd = ((uint32_t)CREG[0x54 >> 1] << 16) | CREG[0x56 >> 1];
    int16_t ma = (int16_t)CREG[0x64 >> 1], mb = (int16_t)CREG[0x62 >> 1], mc = (int16_t)CREG[0x60 >> 1], md = (int16_t)CREG[0x66 >> 1];
    uint16_t ao = 0, bo = 0;
    for (int y = 0; y < h; y++) { for (int i = 0; i < w; i++) {
            uint16_t a = ua ? r16(pa) : CREG[0x74 >> 1], b = ub ? r16(pb) : CREG[0x72 >> 1], c = uc ? r16(pc) : CREG[0x70 >> 1];
            if (i == 0) a &= fwm; if (i == w - 1) a &= lwm;
            uint16_t as = (uint16_t)(((uint32_t)ao << 16 | a) >> ash), bs = (uint16_t)(((uint32_t)bo << 16 | b) >> bsh); ao = a; bo = b;
            uint16_t d = 0; for (int k = 0; k < 8; k++) if (mt & (1 << k)) d |= (uint16_t)(((k & 4) ? as : ~as) & ((k & 2) ? bs : ~bs) & ((k & 1) ? c : ~c));
            w16(pd, d); if (ua) pa += 2; if (ub) pb += 2; if (uc) pc += 2; pd += 2; }
        if (ua) pa += ma; if (ub) pb += mb; if (uc) pc += mc; pd += md; }
}
static void setp(int off, uint32_t a) { wr(off, (uint16_t)(a >> 16)); wr(off + 2, (uint16_t)a); }
/* a picture: w words, h rows, 4 planes one after another, then the mask */
typedef struct { int w, h; uint32_t at; } Img;
static Img mkimg(uint32_t at, int w, int h, int seed) {
    Img im = { w, h, at };
    for (int y = 0; y < h; y++) for (int i = 0; i < w; i++) {
        uint16_t m = 0; for (int b = 0; b < 16; b++) { int x = i * 16 + b, cx = w * 8, cy = h / 2; if ((x - cx) * (x - cx) * h * h / (w * w * 64) + (y - cy) * (y - cy) * 4 < h * h) m |= (uint16_t)(0x8000 >> b); }
        w16(at + (uint32_t)(4 * w * h + y * w + i) * 2, m);
        for (int p = 0; p < 4; p++) w16(at + (uint32_t)(p * w * h + y * w + i) * 2, (uint16_t)(m & (uint16_t)(0x9e37u * (uint32_t)(y + 3 * i + 7 * p + seed))));
    }
    return im;
}
static uint32_t rowaddr(uint32_t buf, int p, int row) { return buf + (uint32_t)p * PLSZ + (uint32_t)(((row % RR) + RR) % RR) * RB; }
typedef struct { int sx, sy, w, h, top; } Rect;
static Rect DRAWN[2][64]; static int NDRAWN[2];
/* rows y0..y0+n-1 of the picture at screen (sx, sy) of a buffer whose top row is top: one blit per plane and piece of the ring */
static void draw(uint32_t buf, int top, Img im, int sx, int sy, int shadow) {
    int sh = sx & 15, col = (sx >> 4) * 2;   /* sx may be negative: the previous row's margin */
    for (int r0 = 0; r0 < im.h;) {
        int row = ((top + sy + r0) % RR + RR) % RR, n = im.h - r0; if (row + n > RR) n = RR - row;   /* the ring's end cuts the picture */
        for (int p = 0; p < 4; p++) {
            uint32_t d = rowaddr(buf, p, row) + (uint32_t)col;
            setp(0x50, im.at + (uint32_t)(4 * im.w * im.h + r0 * im.w) * 2); setp(0x4c, im.at + (uint32_t)(p * im.w * im.h + r0 * im.w) * 2);
            setp(0x48, d); setp(0x54, d);
            wr(0x40, (uint16_t)(sh << 12 | (shadow ? 0x0b0a : 0x0fca))); wr(0x42, (uint16_t)(sh << 12));
            wr(0x44, 0xffff); wr(0x46, 0x0000); wr(0x64, (uint16_t)-2); wr(0x62, (uint16_t)-2); wr(0x60, (uint16_t)(RB - 2 * (im.w + 1))); wr(0x66, (uint16_t)(RB - 2 * (im.w + 1)));
            blit((uint16_t)(n << 6 | (im.w + 1)));
        }
        r0 += n;
    }
}
static void restore(uint32_t buf, Rect r) {   /* copy the background back, whole words, piece by piece, where the picture went */
    int top = r.top, col = (r.sx >> 4) * 2, w = r.w + 1;
    for (int r0 = 0; r0 < r.h;) {
        int row = ((top + r.sy + r0) % RR + RR) % RR, n = r.h - r0; if (row + n > RR) n = RR - row;
        for (int p = 0; p < 4; p++) {
            setp(0x50, rowaddr(CLN, p, row) + (uint32_t)col); setp(0x54, rowaddr(buf, p, row) + (uint32_t)col);
            wr(0x40, 0x09f0); wr(0x42, 0); wr(0x44, 0xffff); wr(0x46, 0xffff); wr(0x64, (uint16_t)(RB - 2 * w)); wr(0x66, (uint16_t)(RB - 2 * w));
            blit((uint16_t)(n << 6 | w));
        }
        r0 += n;
    }
}
static void copper(uint32_t at, uint32_t buf, int top) {
    uint32_t c = at; int wrapy = RR - top;   /* the window line where the ring starts again */
#define MOVE(r, v) do { w16(c, (uint16_t)(r)); w16(c + 2, (uint16_t)(v)); c += 4; } while (0)
    for (int p = 0; p < 4; p++) { uint32_t a = rowaddr(buf, p, top); MOVE(0xe0 + 4 * p, a >> 16); MOVE(0xe2 + 4 * p, a); }
    MOVE(0xf0, HUDM >> 16); MOVE(0xf2, HUDM); MOVE(0x100, 0x5200);
    w16(c, (uint16_t)((0x2c + 4) << 8 | 0x07)); w16(c + 2, 0xfffe); c += 4; MOVE(0x100, 0x4200);
    if (wrapy > 4 && wrapy < WH) { w16(c, (uint16_t)((0x2c + wrapy - 1) << 8 | 0xdf)); w16(c + 2, 0xfffe); c += 4;
        for (int p = 0; p < 4; p++) { uint32_t a = buf + (uint32_t)p * PLSZ; MOVE(0xe0 + 4 * p, a >> 16); MOVE(0xe2 + 4 * p, a); } }
    w16(c, 0xffff); w16(c + 2, 0xfffe);
}
int main(void) {
    for (int p = 0; p < 4; p++) for (int row = 0; row < RR; row++) for (int b = 0; b < RB; b += 2) {
        uint16_t v = (uint16_t)(((row * 7 + b * 3) >> p) & 1 ? 0xf0f0 >> (row & 3) : 0x0ff0 << (b & 2));
        w16(rowaddr(CLN, p, row) + (uint32_t)b, v); w16(rowaddr(BUF0, p, row) + (uint32_t)b, v); w16(rowaddr(BUF1, p, row) + (uint32_t)b, v); }
    for (int y = 0; y < 4; y++) for (int b = 0; b < RB; b += 2) w16(HUDM + (uint32_t)(y * RB + b), (uint16_t)(b < 12 ? 0x7ffe : 0));
    for (int c = 0; c < 32; c++) ard_write((uint32_t)(0x180 + 2 * c), (uint16_t)(c * 0x111 + 0x13));
    ard_write(0x08e, 0x2c81); ard_write(0x090, (uint16_t)((0x2c + WH) << 8 | 0xc1)); ard_write(0x092, 0x38); ard_write(0x094, 0xd0);
    ard_write(0x102, 0); ard_write(0x104, 0x3f); ard_write(0x108, RB - 40); ard_write(0x10a, RB - 40); CREG[0x96 >> 1] = 0x0300;
    Img body = mkimg(IMG, 2, 12, 1), blade = mkimg(IMG + 0x400, 3, 5, 2), small = mkimg(IMG + 0x800, 1, 9, 3);
    ArsConf cf = { OBJPC, 8, 12, 14, 10, 0, 0 }; ars_conf(&cf); ars_on(1);
    int reasons[4] = { 0, 0, 0, 0 };
    int camy = 1000, bad_cam = 0, bad_clean = 0, bad_compose = 0, bad_obj = 0, nobj = 0, valid = 0, prevcam = 0, frames = 0, parts = 0, shadows = 0, left = 0, cut = 0;
    for (int f = 0; f < 120; f++) {
        int pass = f / 2, buf = pass & 1; uint32_t B = buf ? BUF1 : BUF0; int top = ((camy - pass) % RR + RR) % RR, cy = camy - pass;
        static int EX[8][4];   /* expected per node: screen x, y of the picture's corner */
        if (!(f & 1)) {
            for (int i = 0; i < NDRAWN[buf]; i++) restore(B, DRAWN[buf][i]);
            NDRAWN[buf] = 0;
            for (int i = 0; i < 5; i++) {
                uint32_t nd = NODES + (uint32_t)i * 32; int wx = 30 + 60 * i + pass * (i - 2), wy = cy + 8 + ((i * 13 + pass * (i + 1)) % 50);
                if (i == 0) wx = -9 + (pass % 7);                                   /* across the left edge */
                if (i == 1) wy = cy + 86 + (pass % 12);                             /* through the window's bottom */
                if (i == 4) { wy = cy - 8 + (pass % 12); wx = 200 + pass % 40; }    /* through its top (a game draws nothing into the right margin: there it is the next row's left edge) */
                w16(nd + 12, (uint16_t)wx); w16(nd + 14, (uint16_t)wy); w16(nd + 10, (uint16_t)(i == 2 ? (pass & 1) : 0));
                int sx = wx - 3, sy = wy - cy - 2;
                CPU.a[0] = nd; CPU.a[7] = SP; ars_pc(&CPU, OBJPC); CPU.a[7] = SP - 8;   /* the routine and the calls inside it */
                if (i == 3) { draw(B, top, small, sx + 5, sy + 6, 1); DRAWN[buf][NDRAWN[buf]++] = (Rect){ sx + 5, sy + 6, 1, 9, top }; }   /* its shadow first */
                draw(B, top, body, sx, sy, 0); DRAWN[buf][NDRAWN[buf]++] = (Rect){ sx, sy, 2, 12, top };
                if (i == 2 && (pass & 1)) { draw(B, top, blade, sx - 8, sy - 4, 0); DRAWN[buf][NDRAWN[buf]++] = (Rect){ sx - 8, sy - 4, 3, 5, top }; }   /* a second part every other pass */
                CPU.a[7] = SP + 4; ars_pc(&CPU, 0x2000);   /* returned */
                EX[i][0] = sx; EX[i][1] = sy; EX[i][2] = wx; EX[i][3] = wy;
            }
            copper(buf ? COP1 : COP0, B, top);
            ard_write(0x080, (uint16_t)((buf ? COP1 : COP0) >> 16)); ard_write(0x082, (uint16_t)(buf ? COP1 : COP0));
        }
        ard_frame_start(); ard_until(ARD_LINES); ars_line(ARD_LINES);
        ars_record(f);
        ArsRec *R = &ARS_REC[f % ARS_NR];
        if (f < 4) continue;
        frames++;
        if (!R->valid) { reasons[R->reason & 3]++; continue; }
        valid++;
        if (valid > 1 && R->camy != prevcam - (f & 1 ? 0 : 1)) bad_cam++;
        prevcam = R->camy;
        int W = R->w, H = R->h;
        for (int y = 4; y < H; y++) for (int x = 0; x < W; x++) {   /* the clean playfield = the background ring at the camera */
            int row = (top + y) % RR, idx = 0;
            for (int p = 0; p < 4; p++) idx |= ((r16(rowaddr(CLN, p, row) + (uint32_t)(x >> 4) * 2) >> (15 - (x & 15))) & 1) << p;
            if (R->clean[y * W + x] != idx) bad_clean++; }
        static uint8_t comp[ARS_HMAX * ARS_WMAX]; memcpy(comp, R->clean, (size_t)(W * H));
        for (int i = 0; i < R->nobj; i++) { ArsObj *o = &R->obj[i]; nobj++;
            for (int y = 0; y < o->h; y++) for (int x = 0; x < o->w; x++) { int X = o->sx + x, Y = o->sy + y; uint8_t c = R->pix[o->pix + y * o->w + x];
                if (c != 255 && X >= 0 && X < W && Y >= 0 && Y < H) comp[Y * W + X] = c; }
            int nd = (int)((o->node - NODES) / 32); if (nd < 0 || nd > 4) { bad_obj++; continue; }
            if (o->x != EX[nd][2] || o->y != EX[nd][3]) bad_obj++;
            if (o->kind == 0) { int ex = EX[nd][0] - (nd == 2 && (pass & 1) ? 8 : 0), ey = EX[nd][1] - (nd == 2 && (pass & 1) ? 4 : 0);
                /* the corner of the drawn pixels: the masks' first set column / row */
                if (o->sx < ex || o->sx > ex + 16 || o->sy < ey || o->sy > ey + 4) bad_obj++;
                if (nd == 2 && (pass & 1)) parts++; if (nd == 0 && o->sx < 0) left++; if (o->sy < 0 || o->sy + o->h > H) cut++; }
            else shadows++;
        }
        for (int y = 0; y < H; y++) for (int x = 0; x < W; x++) { uint8_t c = R->hud[y * W + x]; if (c != 255) comp[y * W + x] = c; }
        for (int i = 0; i < W * H; i++) if (comp[i] != R->raw[i]) bad_compose++;
    }
    if (getenv("ARS_DUMP")) { FILE *df = fopen(getenv("ARS_DUMP"), "wb"); fwrite(&ARS_REC[119 % ARS_NR], sizeof(ArsRec), 1, df); fclose(df); }
    printf("{\"layout\": [%d", ars_layout(0)); for (int i = 1; i < 14; i++) printf(", %d", ars_layout(i)); printf("], ");
    printf("\"frames\": %d, \"valid\": %d, \"bad_cam\": %d, \"bad_clean\": %d, \"bad_compose\": %d, \"bad_obj\": %d, \"objects\": %d, \"parts\": %d, \"shadows\": %d, \"left\": %d, \"cut\": %d, \"rings\": %d, \"reasons\": [%d, %d, %d]}\n",
           frames, valid, bad_cam, bad_clean, bad_compose, bad_obj, nobj, parts, shadows, left, cut, ARS_NRING, reasons[0], reasons[1], reasons[2]);
    return 0;
}
'''


def run_harness(tmp_path):
    cc = bus.compiler()
    if not cc:
        pytest.skip('no C compiler')
    (tmp_path / 'h.c').write_text(HARNESS)
    exe = tmp_path / 'h'
    r = subprocess.run([cc, '-O1', '-w', '-I', HOST, str(tmp_path / 'h.c'), '-o', str(exe), '-lm'], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    out = subprocess.run([str(exe)], capture_output=True, text=True, timeout=120, env=dict(os.environ, ARS_DUMP=str(tmp_path / 'rec.bin')))
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_the_scene_recorder_explains_a_synthetic_game(tmp_path):
    res = run_harness(tmp_path)
    print(res)
    assert res['valid'] == res['frames'] and res['rings'] == 2
    assert res['bad_cam'] == 0 and res['bad_clean'] == 0 and res['bad_obj'] == 0
    assert res['bad_compose'] == 0
    assert res['parts'] > 0 and res['shadows'] > 0 and res['left'] > 0 and res['cut'] > 0


NODE_CHECK = r"""
const fs = require('fs'), R = require(process.argv[2]), L = JSON.parse(process.argv[4]), rec = fs.readFileSync(process.argv[3]);
const n = 119, heap = new Uint8Array(L[0] * L[9]); heap.set(rec, (n % L[9]) * L[0]);
const M = { HEAPU8: heap, _ars_rec: () => 0, _ars_layout: (i) => L[i] };
const r = R.reader(M).rec(n), st = {}, sc = R.toScene(r, st, null, { runOf: (img) => img & 0xff });
const W = r.w, H = r.h, comp = sc.window.idx.slice();
let over = 0; for (const v of sc.window.over) if (v !== 255) over++;
let place = 0, hud = 0, objs = 0;
for (const o of sc.objects) {
  if (o.node === undefined) { hud += o.screen ? 1 : 0; }
  else { objs++; const ro = r.objs.find((q) => q.node === o.node && q.kind === o.kind); if (!ro || o.x + o.ox !== r.camx + ro.sx || o.y + o.oy !== r.camy + ro.sy) place++; }
  const sx = o.x + o.ox - r.camx, sy = o.y + o.oy - r.camy;
  for (let y = 0; y < o.h; y++) for (let x = 0; x < o.w; x++) { const c = o.idx[y * o.w + x], X = sx + x, Y = sy + y; if (c !== 255 && X >= 0 && X < W && Y >= 0 && Y < H) comp[Y * W + X] = c; }
}
let diff = 0; for (let i = 0; i < W * H; i++) if (comp[i] !== r.raw[i]) diff++;
const groups = new Set(sc.objects.filter((o) => o.node !== undefined).map((o) => o.group)).size;
console.log(JSON.stringify({ valid: r.valid, w: W, h: H, objs, hud, over, place, diff, groups, pal: sc.window.pal.length, runs: sc.objects.filter((o) => o.run !== undefined).length }));
"""


def test_the_web_side_turns_a_record_into_wb_scenes(tmp_path):
    """wb-scenerec.js reads the record from the engine's memory (here: the harness's last record in a heap of its own) and
    gives wb-scene's record: the clean window with its palettes, every object at its logical position with the drawing's
    offset (x + ox = the camera + its place on the screen), a group per object and kind, the score line as one object fixed
    on the screen - and the composition of all that equals the picture as shown, so `over` stays empty."""
    from arek import web
    import shutil
    if not shutil.which('node'):
        pytest.skip('no node')
    res = run_harness(tmp_path)
    (tmp_path / 'check.js').write_text(NODE_CHECK)
    out = subprocess.run(['node', str(tmp_path / 'check.js'), os.path.join(os.path.dirname(web.__file__), 'wb-scenerec.js'), str(tmp_path / 'rec.bin'), json.dumps(res['layout'])],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    v = json.loads(out.stdout)
    print(v)
    assert v['valid'] == 1 and v['w'] == 320 and v['h'] == 96 and v['pal'] == 96 * 32 * 4
    assert v['objs'] >= 5 and v['hud'] == 1 and v['place'] == 0 and v['over'] == 0 and v['diff'] == 0
    assert v['groups'] == v['objs'] and v['runs'] == v['objs']
    assert 'wb-scenerec.js' in web.FILES
