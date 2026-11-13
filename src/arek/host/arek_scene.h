/* arek_scene.h - the scene recorder of the kit's host (1.0.77): a record for wb-scene, every frame, from what the game does
 * to the hardware, with one hint from the game. Header-only, MIT. No game data.
 *
 * What the kit finds by itself:
 *   - the picture as the display fetched it, line by line (ard_fetch_cb): the window (DIW), the palette of every row (the
 *     colour registers at the line's end), the planes of the playfield and the ones above it (a line with more planes than
 *     most lines of the window - a score line in a fifth plane - or a line outside the playfield's chain = HUD);
 *   - the camera: the playfield's chain of plane-0 addresses runs through a ring of rows (a pointer reloaded back to the
 *     ring's start inside the window; learnt the first time a frame shows the wrap, per buffer); the top row of the window in
 *     its ring, unwrapped over the frames, is the camera's y; its column and the fine scroll are its x;
 *   - the objects: every blit whose D is masked by A (C = D and one value of A keeps C: A = 0 - minterm & $0F = $0A, a
 *     cookie-cut picture with B, an OR; A = 1 - minterm & $F0 = $A0, a shadow cut with an inverted mask, SWIV) inside the
 *     hinted routine is a part of the object drawing then; its words, the mask of every word and the word after the blit
 *     are kept, and placed on the screen when a frame shows them (plane, row and column in the displayed ring - also the
 *     rows the window does not show, and the margin at a row's end, which is the next row's left edge); all parts of one
 *     call of the routine are one picture (the parts of a helicopter, the two pieces of a picture split by the ring's
 *     end) - kind 0 with B, kind 1 without (a shadow, a flash), in the order drawn;
 *   - the clean playfield: the word under the first object blit, kept until something else writes the word (a restore
 *     blit, a full copy), so the window shows the background under the objects without knowing the game's buffers;
 *   - which objects a frame shows: a call with a word in the shown ring that nothing but objects wrote since (every other
 *     write - a restore, a copy - makes the word's generation new, so a pass that was restored over is gone; another
 *     object drawn over a part of it is not); of one object (the address, k) the newest call; the frame's pass is the
 *     one most of its objects come from (SWIV draws a piece of the next pass into the shown buffer);
 *   - the hardware sprites of every line (ard_spr_cb).
 * Measured on SWIV (kit 1.0.77, city, 1000 frames, its own recorder src/swiv_scene.c beside it in one engine): the camera
 * at one constant offset in every frame, 14 181 objects at SWIV's place to the pixel (19 more wholly in the margin or the
 * hidden rows), 0 pixels the record does not explain (SWIV's 72), wb-scene's motion of all 42 common objects equal to
 * three decimals; the kit has 2 small objects SWIV leaves in its window and not SWIV's empty shadows.
 * The hint (ArsConf, ars_conf): obj_pc - the first instruction of the routine that draws one object (its blits happen with
 * the stack at or under the entry's: the routine's own calls count, its return ends the object), obj_reg - the register
 * with the object's address at that instruction (0-7 d0-d7, 8-15 a0-a7), obj_x / obj_y - the word offsets of its logical
 * x and y (the position the game moves, in the game's units), obj_img (-1 none) - a word that names its picture (a change
 * starts a new run for wb-scene's objMean). Optional: pass_pc - where a pass of the game's loop starts (the pass's time,
 * wb-scene passTime), logic_pc - where the pass's logic is done and its drawing begins (every object's new position is in
 * RAM: rec.next), cam_x / cam_y - the addresses of the game's own camera words (read there with logic_pc: the next pass's
 * camera for rec.next, so an object the game keeps on the screen stays there). A routine called twice for one object in a
 * pass (the same address) gives two objects (k 0, 1 - counted over the calls that drew something).
 *
 * Use: the project includes this after the host (ENGINE_SRC), calls ars_conf(&c) and ars_on(1), and ars_record(n) from its
 * ENGINE_FRAME_RECORD (or defines ENGINE_FRAME_RECORD=ars_record); the page reads ars_rec() / ars_layout() with
 * wb-scenerec.js, which turns a record into wb-scene's. The hooks it takes (h_pc_cb, h_wr_cb, ard_line_cb, ard_spr_cb,
 * ard_fetch_cb) call the ones set before it.
 * Not covered (the record says so in reason): hires, dual playfield, HAM and EHB lines (2), a playfield chain whose ring was
 * not seen yet (1). Line-mode blits are ignored; a CPU's drawing into the buffer shows as the difference (wb-scene's over). */
#ifndef AREK_SCENE_H
#define AREK_SCENE_H
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#ifndef ARS_CREG
#define ARS_CREG(off) (CREG[(off) >> 1])
#endif
#ifndef ARS_IN_IRQ                                /* inside an interrupt handler: the stack is not the drawing routine's */
#define ARS_IN_IRQ() (H_IN_IRQ)
#endif
#ifndef ARS_RDW                                   /* a word anywhere (the object's fields) */
#define ARS_RDW(a) ((uint16_t)rd16_raw(a))
#endif
#ifndef ARS_NOW
#define ARS_NOW() (h_now())
#endif
#ifndef ARS_WMAX
#define ARS_WMAX 384
#endif
#ifndef ARS_HMAX
#define ARS_HMAX 288
#endif
#ifndef ARS_NO
#define ARS_NO 256                               /* objects in a record */
#endif
#ifndef ARS_POOL
#define ARS_POOL 196608                          /* their pixels */
#endif
#define ARS_NR 8                                 /* records kept (the page reads every frame) */
#define ARS_NSL 2048                             /* sprite lines of a frame */
#define ARS_NN 256                               /* rec.next: objects */
#define ARS_NOCC 4096                            /* calls kept */
#define ARS_NWR (1u << 19)                       /* words drawn kept */
#define ARS_NWORD (MEMSZ >> 1)
#define ARS_SHADOW (1u << 31)

typedef struct { uint32_t obj_pc; int obj_reg, obj_x, obj_y, obj_img; uint32_t pass_pc, logic_pc, cam_x, cam_y; } ArsConf;
typedef struct { uint32_t serial, node, w0, w1; int32_t pass, k; uint16_t x, y, img, pi; } ArsOcc;   /* pi: the node's place in this pass's list */
typedef struct { uint32_t w; uint16_t m, v, g, pad; } ArsWr;               /* w: word index | ARS_SHADOW (no B: kind 1); g: the word's generation */
typedef struct { uint32_t node; int32_t serial, k, kind, x, y, img, pass, sx, sy, w, h, pix; } ArsObj;
typedef struct { int16_t y, k, hs, att; uint16_t da, db; } ArsSl;
typedef struct { uint32_t node; int16_t x, y, img, pad; } ArsNx;
typedef struct {
    int32_t n, valid, reason, pass, pass_f, pass_c, camx, camy, w, h, v0, h0, nobj, pool, nsl, nnx, nx_pass, nx_f, nx_c,
            rows, planes, stride, ring, has_cam, pcam_x, pcam_y, ncam_x, ncam_y, pad[8];   /* 36 x 4 B */
    uint16_t pal[ARS_HMAX][32];                                          /* 12-bit colours of every window row */
    uint8_t raw[ARS_HMAX * ARS_WMAX];                                    /* the window as shown (colour index; w per row) */
    uint8_t clean[ARS_HMAX * ARS_WMAX];                                  /* the playfield under the objects */
    uint8_t hud[ARS_HMAX * ARS_WMAX];                                    /* what lies above the playfield on the screen (255 = none) */
    ArsObj obj[ARS_NO];
    uint8_t pix[ARS_POOL];                                               /* the objects' pictures, 255 = transparent */
    ArsSl sl[ARS_NSL];
    ArsNx nx[ARS_NN];
} ArsRec;
typedef struct { int stamp, n, nw, hr; int base[2]; uint32_t pt[6]; uint16_t con0, con2, diws, diwe; } ArsLine;

static ArsConf ARS_C;
static int ARS_ON = 0;
static uint16_t ARS_BG[ARS_NWORD], ARS_MU[ARS_NWORD];
static uint16_t ARS_GEN[ARS_NWORD];               /* +1 for every write that is not an object's (a restore, a copy): an object's words with an older generation are gone */
static uint8_t ARS_SV[ARS_NWORD];
static ArsOcc ARS_OCC[ARS_NOCC];
static ArsWr ARS_WR[ARS_NWR];
static uint32_t ARS_WRN = 0, ARS_SERIAL = 0, ARS_CUR = 0, ARS_CUR_SP = 0, ARS_CUR_NODE = 0, ARS_LASTEV = 0;
static int ARS_CUR_NB = 0;
static M68 *ARS_M = 0;
static struct { int on, occ, shadow; uint32_t wr0; } ARS_PB;           /* the masked blit not settled yet */
static int32_t ARS_PASS = 0, ARS_NEWPASS = 1, ARS_FRAMENO = 0, ARS_STAMP = 1, ARS_LASTPASS = 0;
static struct { int32_t f, c; } ARS_PT[64];
static uint32_t ARS_PN[2][ARS_NN]; static int ARS_PNN[2] = { 0, 0 }, ARS_PNC[ARS_NN];   /* the nodes of this pass and the last, and how many calls of each drew something */
static struct { int32_t pass, f, c, n, cx, cy; ArsNx e[ARS_NN]; } ARS_NXS;
static struct { int32_t pass; uint16_t cx, cy; } ARS_PCAM[64];   /* the game's camera words when a pass's logic was done */
static ArsLine ARS_LN[ARD_LINES];
static uint16_t ARS_RW[ARD_LINES][6][64], ARS_CW[ARD_LINES][6][64];
static uint16_t ARS_PAL[ARD_LINES][32];
static ArsSl ARS_FSL[ARS_NSL]; static int ARS_FNSL = 0;
static struct { uint32_t r0, e, s; } ARS_RING[8]; static int ARS_NRING = 0;
static int32_t ARS_DK[6] = { 0, 0, 0, 0, 0, 0 }, ARS_P = 0, ARS_CAMY = 0, ARS_ROW0 = -1;
static ArsRec ARS_REC[ARS_NR];
static void (*ars_prev_pc)(M68 *m, uint32_t pc) = 0;
static void (*ars_prev_wr)(uint32_t off, uint32_t v) = 0;
static void (*ars_prev_line)(int v) = 0;
static void (*ars_prev_spr)(int v, const ArdSpriteLine *sl, int n) = 0;
static void (*ars_prev_fetch)(int v, int n, const uint32_t *pt, int nw, const int *base, int hr, uint16_t (*words)[64]) = 0;

static inline uint16_t ars_mem(uint32_t w) { return (uint16_t)((MEM[2 * w] << 8) | MEM[2 * w + 1]); }
static inline ArsOcc *ars_occ(uint32_t s) { ArsOcc *o = &ARS_OCC[s % ARS_NOCC]; return s && o->serial == s ? o : 0; }
static void ars_settle(void) {                     /* the blit has run: the words it left */
    if (!ARS_PB.on) return;
    ARS_PB.on = 0;
    for (uint32_t i = ARS_PB.wr0; i != ARS_WRN; i++) {
        ArsWr *r = &ARS_WR[i & (ARS_NWR - 1)]; uint32_t w = r->w & ~ARS_SHADOW; uint16_t now = ars_mem(w);
        if (ARS_PB.occ) { r->v = now; ARS_MU[w] |= r->m; }
        else if (ARS_SV[w]) { ARS_BG[w] = (uint16_t)((ARS_BG[w] & ~r->m) | (now & r->m)); ARS_MU[w] &= (uint16_t)~r->m; }   /* drawn outside an object: background */
    }
    if (ARS_PB.occ) { ArsOcc *o = ars_occ((uint32_t)ARS_PB.occ); if (o) { if (o->w1 == o->w0 && ARS_WRN != o->w0 && o->pass == ARS_PASS && o->pi < ARS_NN) ARS_PNC[o->pi]++; o->w1 = ARS_WRN; } }
    else ARS_WRN = ARS_PB.wr0;
}
/* BLTSIZE: before the blit runs (the runtime's hw_write calls the hook first) */
static void ars_blit(uint16_t size) {
    ars_settle();
    uint16_t con0 = ARS_CREG(0x040), con1 = ARS_CREG(0x042), fwm = ARS_CREG(0x044), lwm = ARS_CREG(0x046);
    if (con1 & 1) return;                          /* line mode */
    int h = size >> 6, wd = size & 63; if (!h) h = 1024; if (!wd) wd = 64;
    int usea = (con0 >> 11) & 1, useb = (con0 >> 10) & 1, usec = (con0 >> 9) & 1, used = (con0 >> 8) & 1, ash = con0 >> 12, desc = (con1 >> 1) & 1;
    uint32_t mask = MEMSZ - 1;
    uint32_t apt = ((uint32_t)ARS_CREG(0x050) << 16 | ARS_CREG(0x052)) & mask & ~1u, cpt = ((uint32_t)ARS_CREG(0x048) << 16 | ARS_CREG(0x04a)) & mask & ~1u,
             dpt = ((uint32_t)ARS_CREG(0x054) << 16 | ARS_CREG(0x056)) & mask & ~1u;
    int16_t amod = (int16_t)ARS_CREG(0x064), cmod = (int16_t)ARS_CREG(0x060), dmod = (int16_t)ARS_CREG(0x066);
    if (!used) return;
    /* masked by A: one value of A keeps C (A = 0: minterm & $0F = $0A, D = A ? f(B, C) : C - a cookie-cut, an OR; A = 1: minterm
     * & $F0 = $A0, D = A ? C : f(B, C) - SWIV's shadow, D = A & C with the mask inverted); the other changes the bits */
    int keep0 = (con0 & 0x0f) == 0x0a, keep1 = (con0 & 0xf0) == 0xa0, inv = keep1;
    int masked = usec && (keep0 ^ keep1) && cpt == dpt && cmod == dmod && !(con1 & 0x1a);
    int st = desc ? -2 : 2;
    ARS_LASTEV = 0;
    if (!masked) {                                 /* a copy, a fill, a clear: whatever was there is gone */
        uint32_t d = dpt;
        for (int y = 0; y < h; y++) { for (int i = 0; i < wd; i++) { uint32_t w = (d & mask) >> 1;
                ARS_SV[w] = 0; ARS_MU[w] = 0; ARS_GEN[w]++; d += (uint32_t)st; }
            d += (uint32_t)(desc ? -dmod : dmod); }
        return;
    }
    int occ = 0;
    if (ARS_CUR && ARS_M && ARS_M->a[7] <= ARS_CUR_SP && ars_occ(ARS_CUR)) { occ = (int)ARS_CUR; ARS_CUR_NB++; }
    ARS_PB.on = 1; ARS_PB.occ = occ; ARS_PB.shadow = !useb; ARS_PB.wr0 = ARS_WRN;
    uint16_t aold = 0; uint32_t a = apt, d = dpt;
    for (int y = 0; y < h; y++) {
        for (int i = 0; i < wd; i++) {
            uint16_t av = usea ? ars_mem((a & mask) >> 1) : ARS_CREG(0x074);
            if (i == 0) av &= fwm;
            if (i == wd - 1) av &= lwm;
            uint16_t m = (uint16_t)((((uint32_t)aold << 16) | av) >> ash);
            aold = av;
            if (inv) m = (uint16_t)~m;
            uint32_t w = (d & mask) >> 1;
            if (m) {
                if (occ && !ARS_SV[w]) { ARS_BG[w] = ars_mem(w); ARS_SV[w] = 1; ARS_MU[w] = 0; }
                ArsWr *r = &ARS_WR[ARS_WRN & (ARS_NWR - 1)]; r->w = w | (useb ? 0 : ARS_SHADOW); r->m = m; r->v = 0; r->g = ARS_GEN[w]; ARS_WRN++;
            }
            if (usea) a += (uint32_t)st;
            d += (uint32_t)st;
        }
        if (usea) a += (uint32_t)(desc ? -amod : amod);
        d += (uint32_t)(desc ? -dmod : dmod);
    }
}
static void ars_newpass(void) {
    ARS_PASS++; ARS_PT[ARS_PASS & 63].f = ARS_FRAMENO; ARS_PT[ARS_PASS & 63].c = (int32_t)ARS_NOW();
    memcpy(ARS_PN[1], ARS_PN[0], sizeof ARS_PN[0]); ARS_PNN[1] = ARS_PNN[0]; ARS_PNN[0] = 0;
}
static void ars_pc(M68 *m, uint32_t pc) {
    if (ARS_ON) {
        if (ARS_CUR && m->a[7] > ARS_CUR_SP && !ARS_IN_IRQ()) {
            ars_settle(); ARS_CUR = 0; }   /* the routine returned: its object is complete */
        if (pc == ARS_C.obj_pc) {
            ars_settle();
            uint32_t node = ARS_C.obj_reg < 8 ? m->d[ARS_C.obj_reg & 7] : m->a[ARS_C.obj_reg & 7];
            if (!(ARS_LASTEV == pc && node == ARS_CUR_NODE && !ARS_CUR_NB && m->a[7] == ARS_CUR_SP)) {   /* after an rte the hook fires again */
                if (ARS_NEWPASS && !ARS_C.pass_pc && !ARS_C.logic_pc) ars_newpass();
                ARS_NEWPASS = 0;
                int k = 0, i = 0;                     /* k: how many calls for this node drew something before in this pass */
                for (; i < ARS_PNN[0]; i++) if (ARS_PN[0][i] == node) { k = ARS_PNC[i]; break; }
                if (i == ARS_PNN[0] && i < ARS_NN) { ARS_PN[0][i] = node; ARS_PNC[i] = 0; ARS_PNN[0]++; }
                uint32_t s = ++ARS_SERIAL; if (!s) s = ++ARS_SERIAL;
                ArsOcc *o = &ARS_OCC[s % ARS_NOCC]; memset(o, 0, sizeof *o);
                o->serial = s; o->node = node; o->pass = ARS_PASS; o->k = k; o->pi = (uint16_t)i; o->w0 = o->w1 = ARS_WRN;
                o->x = ARS_RDW(node + (uint32_t)ARS_C.obj_x); o->y = ARS_RDW(node + (uint32_t)ARS_C.obj_y);
                o->img = ARS_C.obj_img >= 0 ? ARS_RDW(node + (uint32_t)ARS_C.obj_img) : 0;
                ARS_CUR = s; ARS_CUR_SP = m->a[7]; ARS_CUR_NODE = node; ARS_CUR_NB = 0; ARS_M = m;
            }
            ARS_LASTEV = pc;
        }
        if (ARS_C.pass_pc && pc == ARS_C.pass_pc) {
            ars_settle();
            if (ARS_LASTEV != pc) ars_newpass();
            ARS_LASTEV = pc;
        }
        if (ARS_C.logic_pc && pc == ARS_C.logic_pc) {
            ars_settle();
            if (ARS_LASTEV != pc) {
                if (!ARS_C.pass_pc) ars_newpass();
                ARS_NXS.pass = ARS_PASS; ARS_NXS.f = ARS_PT[ARS_PASS & 63].f; ARS_NXS.c = ARS_PT[ARS_PASS & 63].c; ARS_NXS.n = 0;
                ARS_NXS.cx = ARS_C.cam_x ? ARS_RDW(ARS_C.cam_x) : 0; ARS_NXS.cy = ARS_C.cam_y ? ARS_RDW(ARS_C.cam_y) : 0;
                ARS_PCAM[ARS_PASS & 63].pass = ARS_PASS; ARS_PCAM[ARS_PASS & 63].cx = (uint16_t)ARS_NXS.cx; ARS_PCAM[ARS_PASS & 63].cy = (uint16_t)ARS_NXS.cy;
                for (int i = 0; i < ARS_PNN[1]; i++) { uint32_t nd = ARS_PN[1][i]; ArsNx *e = &ARS_NXS.e[ARS_NXS.n++];
                    e->node = nd; e->x = (int16_t)ARS_RDW(nd + (uint32_t)ARS_C.obj_x); e->y = (int16_t)ARS_RDW(nd + (uint32_t)ARS_C.obj_y);
                    e->img = ARS_C.obj_img >= 0 ? (int16_t)ARS_RDW(nd + (uint32_t)ARS_C.obj_img) : 0; e->pad = 0; }
            }
            ARS_LASTEV = pc;
        }
    }
    if (ars_prev_pc) ars_prev_pc(m, pc);
}
static void ars_wr(uint32_t off, uint32_t v) {
    if (ARS_ON && off == 0x058) ars_blit((uint16_t)v);
    if (ars_prev_wr) ars_prev_wr(off, v);
}
static void ars_line(int v) {                      /* before line v: the colours line v - 1 ended with */
    if (ARS_ON && v > 0 && v <= ARD_LINES) for (int c = 0; c < 32; c++) ARS_PAL[v - 1][c] = ARD_R[(0x180 >> 1) + c] & 0xfff;
    if (ars_prev_line) ars_prev_line(v);
}
static void ars_spr(int v, const ArdSpriteLine *sl, int n) {
    if (ARS_ON) for (int i = 0; i < n && ARS_FNSL < ARS_NSL; i++) { ArsSl *e = &ARS_FSL[ARS_FNSL++];
        e->y = (int16_t)v; e->k = (int16_t)sl[i].k; e->hs = (int16_t)sl[i].hs; e->att = (int16_t)sl[i].att; e->da = sl[i].da; e->db = sl[i].db; }
    if (ars_prev_spr) ars_prev_spr(v, sl, n);
}
static void ars_fetch(int v, int n, const uint32_t *pt, int nw, const int *base, int hr, uint16_t (*words)[64]) {
    if (ARS_ON && v >= 0 && v < ARD_LINES) {
        ars_settle();
        ArsLine *L = &ARS_LN[v]; L->stamp = ARS_STAMP; L->n = n; L->nw = nw; L->hr = hr; L->base[0] = base[0]; L->base[1] = base[1];
        L->con0 = ARD_R[0x100 >> 1]; L->con2 = ARD_R[0x104 >> 1]; L->diws = ARD_R[0x08e >> 1] ? ARD_R[0x08e >> 1] : 0x2c81; L->diwe = ARD_R[0x090 >> 1] ? ARD_R[0x090 >> 1] : 0x2cc1;
        for (int k = 0; k < n && k < 6; k++) {
            L->pt[k] = pt[k];
            for (int i = 0; i < nw; i++) {
                uint16_t raw = words[k][i], cl = raw; uint32_t a = (pt[k] + 2u * (uint32_t)i) & 0x1ffffe;
                if (a < MEMSZ) { uint32_t w = a >> 1; if (ARS_SV[w]) cl = (uint16_t)((raw & ~ARS_MU[w]) | (ARS_BG[w] & ARS_MU[w])); }
                ARS_RW[v][k][i] = raw; ARS_CW[v][k][i] = cl;
            }
        }
    }
    if (ars_prev_fetch) ars_prev_fetch(v, n, pt, nw, base, hr, words);
}
static int ars_eff(int idx, uint16_t con0, uint16_t con2, int n) {   /* the colour Denise takes (arek_display.h ard_pixel, no sprites) */
    int pri = (con2 >> 3) & 7;
    if (pri > 4 && (idx & 16) && !(n == 6 && (con0 & 0x0800))) idx &= 0x30;
    return idx;
}
static int ars_bits(const uint16_t (*w)[64], const ArsLine *L, int h, int k0, int k1) {
    int idx = 0;
    for (int k = k0; k < k1 && k < L->n; k++) { int b = h - L->base[k & 1]; if (b < 0 || b >= 16 * L->nw) continue;
        idx |= ((w[k][b >> 4] >> (15 - (b & 15))) & 1) << k; }
    return idx;
}
static int ars_ring_of(uint32_t a) { for (int i = 0; i < ARS_NRING; i++) if (a >= ARS_RING[i].r0 && a < ARS_RING[i].e) return i; return -1; }
static int ars_cmpi(const void *a, const void *b) { int x = *(const int *)a, y = *(const int *)b; return (x > y) - (x < y); }
static int ars_major(int *v, int n) {             /* the most common value */
    if (!n) return 0;
    qsort(v, (size_t)n, sizeof *v, ars_cmpi);
    int best = v[0], bn = 0;
    for (int i = 0; i < n;) { int j = i; while (j < n && v[j] == v[i]) j++; if (j - i > bn) { bn = j - i; best = v[i]; } i = j; }
    return best;
}
static uint32_t ARS_PXK[ARS_NWR];                  /* scratch: a write's plane | row | column, resolved */
/* frame n is done: its record */
static void ars_record(int n) {
    if (!ARS_ON) return;
    ars_settle();
    ArsRec *R = &ARS_REC[n % ARS_NR];
    memset(R, 0, offsetof(ArsRec, pal)); R->n = n; R->valid = 0;
    int v0 = -1, v1 = -1, h0 = 0, W = 0;
    for (int v = 0; v < ARD_LINES; v++) if (ARS_LN[v].stamp == ARS_STAMP) {
        ArsLine *L = &ARS_LN[v]; int dv0 = L->diws >> 8, dv1 = (L->diwe >> 8) | (((L->diwe >> 8) & 0x80) ? 0 : 0x100);
        v0 = dv0; v1 = dv1; h0 = L->diws & 0xff; W = ((L->diwe & 0xff) | 0x100) - h0; break; }
    int H = v1 - v0; if (W > ARS_WMAX) W = ARS_WMAX; if (H > ARS_HMAX) H = ARS_HMAX;
    R->w = W; R->h = H; R->v0 = v0; R->h0 = h0;
    for (int y = 0; y < H && y < ARS_HMAX; y++) memcpy(R->pal[y], ARS_PAL[v0 + y], 64);
    R->nsl = ARS_FNSL; memcpy(R->sl, ARS_FSL, sizeof(ArsSl) * (size_t)ARS_FNSL);
    ARS_FNSL = 0; ARS_FRAMENO = n + 1; ARS_NEWPASS = 1;
    if (v0 < 0 || H <= 0 || W <= 0) { R->reason = 1; ARS_STAMP++; return; }
    /* the playfield's planes, their offsets, the rows' stride, the rings */
    static int tmp[ARD_LINES];
    int nt = 0;
    for (int y = 0; y < H; y++) { ArsLine *L = &ARS_LN[v0 + y]; if (L->stamp == ARS_STAMP) { if (L->hr || (L->con0 & 0x0400) || L->n == 6) { R->reason = 2; ARS_STAMP++; return; } tmp[nt++] = L->n; } }
    int P = ars_major(tmp, nt); if (P < 1) { R->reason = 1; ARS_STAMP++; return; }
    ARS_P = P;
    for (int k = 1; k < P; k++) { nt = 0; for (int y = 0; y < H; y++) { ArsLine *L = &ARS_LN[v0 + y]; if (L->stamp == ARS_STAMP && L->n >= P) tmp[nt++] = (int)(L->pt[k] - L->pt[0]); } ARS_DK[k] = ars_major(tmp, nt); }
    nt = 0;
    for (int y = 0; y + 1 < H; y++) { ArsLine *L = &ARS_LN[v0 + y], *M2 = &ARS_LN[v0 + y + 1];
        if (L->stamp == ARS_STAMP && M2->stamp == ARS_STAMP && M2->pt[0] > L->pt[0]) tmp[nt++] = (int)(M2->pt[0] - L->pt[0]); }
    uint32_t s = (uint32_t)ars_major(tmp, nt); if (!s) { R->reason = 1; ARS_STAMP++; return; }
    for (int y = 0; y + 1 < H; y++) { ArsLine *L = &ARS_LN[v0 + y], *M2 = &ARS_LN[v0 + y + 1];
        if (L->stamp != ARS_STAMP || M2->stamp != ARS_STAMP || M2->pt[0] >= L->pt[0] || L->pt[0] - M2->pt[0] > 0x40000u) continue;
        uint32_t r0 = M2->pt[0], e = L->pt[0] + s;
        if ((e - r0) % s || (e - r0) / s < (uint32_t)H / 2) continue;
        int i = 0; for (; i < ARS_NRING; i++) if (ARS_RING[i].r0 == r0) break;
        if (i == ARS_NRING) { if (ARS_NRING < 8) ARS_NRING++; else i = 7; }
        ARS_RING[i].r0 = r0; ARS_RING[i].e = e; ARS_RING[i].s = s; }
    /* the chain: the first playfield line in a known ring and the lines that continue it */
    int top = -1, ri = -1;
    for (int y = 0; y < H; y++) { ArsLine *L = &ARS_LN[v0 + y]; if (L->stamp != ARS_STAMP) continue; ri = ars_ring_of(L->pt[0]); if (ri >= 0 && ARS_RING[ri].s == s) { top = y; break; } }
    if (top < 0) { R->reason = 1; ARS_STAMP++; return; }
    uint32_t r0 = ARS_RING[ri].r0, E = ARS_RING[ri].e, rows = (E - r0) / s, col0 = (ARS_LN[v0 + top].pt[0] - r0) % s;
    int rtop = (int)((ARS_LN[v0 + top].pt[0] - r0) / s), row0 = (int)(((int64_t)rtop - top) % (int64_t)rows + rows) % (int)rows;
    static uint8_t pf[ARS_HMAX];
    for (int y = 0; y < H; y++) { ArsLine *L = &ARS_LN[v0 + y]; pf[y] = 0;
        if (L->stamp != ARS_STAMP || L->pt[0] < r0 || L->pt[0] >= E) continue;
        uint32_t o = L->pt[0] - r0; if (o % s != col0) continue;
        if ((int)(o / s) == (row0 + y) % (int)rows) pf[y] = 1; }
    if (ARS_ROW0 < 0) ARS_CAMY = row0;
    else { int d = row0 - ARS_ROW0; if (d > (int)rows / 2) d -= (int)rows; if (d < -(int)rows / 2) d += (int)rows; ARS_CAMY += d; }
    ARS_ROW0 = row0;
    int bx = ARS_LN[v0 + top].base[0], camx = (int)col0 * 8 + (h0 - bx);
    R->camx = camx; R->camy = ARS_CAMY; R->rows = (int32_t)rows; R->planes = P; R->stride = (int32_t)s; R->ring = (int32_t)r0;
    /* the window: as shown, the playfield under the objects, what lies above it */
    for (int y = 0; y < H; y++) {
        ArsLine *L = &ARS_LN[v0 + y]; uint8_t *rw = R->raw + y * W, *cl = R->clean + y * W, *hu = R->hud + y * W;
        if (L->stamp != ARS_STAMP) { memset(rw, 0, (size_t)W); memset(cl, 0, (size_t)W); memset(hu, 255, (size_t)W); continue; }
        const uint16_t (*rwd)[64] = (const uint16_t (*)[64])ARS_RW[v0 + y], (*cwd)[64] = (const uint16_t (*)[64])ARS_CW[v0 + y];
        for (int x = 0; x < W; x++) {
            int hh = h0 + x, all = ars_bits(rwd, L, hh, 0, 6), e = ars_eff(all, L->con0, L->con2, L->n);
            rw[x] = (uint8_t)e;
            if (!pf[y]) { cl[x] = 0; hu[x] = (uint8_t)e; continue; }
            cl[x] = (uint8_t)ars_eff(ars_bits(cwd, L, hh, 0, P), L->con0, L->con2, P);
            hu[x] = L->n > P && ars_bits(rwd, L, hh, P, 6) ? (uint8_t)e : 255;
        }
    }
    /* the objects the display shows this frame: the calls with a word still theirs (no restore or copy over it since) in the
     * shown ring - of one object (node, k) the newest only; in the order they were drawn */
    int no = 0, pool = 0, maxpass = -1; uint32_t rowpx = s * 8;
    static uint32_t cand[1024]; int nc = 0;
    uint32_t first = ARS_SERIAL >= 1024 ? ARS_SERIAL - 1023 : 1;
    for (uint32_t sn = ARS_SERIAL; sn >= first && sn; sn--) {
        ArsOcc *o = ars_occ(sn); if (!o || o->w1 == o->w0 || ARS_WRN - o->w0 > ARS_NWR) continue;
        int live = 0;
        for (uint32_t i = o->w0; i != o->w1 && !live; i++) { ArsWr *r = &ARS_WR[i & (ARS_NWR - 1)]; uint32_t w = r->w & ~ARS_SHADOW; if (ARS_GEN[w] != r->g) continue;
            for (int k = 0; k < P; k++) { uint32_t q = w * 2 - (uint32_t)ARS_DK[k]; if (q >= r0 && q < E) { live = 1; break; } } }
        if (!live) continue;
        int dup = 0; for (int j = 0; j < nc && !dup; j++) { ArsOcc *p2 = ars_occ(cand[j]); if (p2 && p2->node == o->node && p2->k == o->k) dup = 1; }
        if (!dup && nc < 1024) cand[nc++] = sn;
    }
    for (int ci = nc - 1; ci >= 0; ci--) {
        uint32_t sn = cand[ci]; ArsOcc *o = ars_occ(sn);
        int k1st = (ARS_WR[o->w0 & (ARS_NWR - 1)].w & ARS_SHADOW) ? 1 : 0;   /* the kinds in the order the routine drew them (a shadow first) */
        for (int kk = 0; kk < 2; kk++) {
            int kind = kk ^ k1st, minc = 1 << 30, maxc = -(1 << 30), any = 0;
            for (uint32_t i = o->w0; i != o->w1; i++) { ArsWr *r = &ARS_WR[i & (ARS_NWR - 1)]; uint32_t j = i & (ARS_NWR - 1); ARS_PXK[j] = 0xffffffffu;
                if (!!(r->w & ARS_SHADOW) != kind || ARS_GEN[r->w & ~ARS_SHADOW] != r->g) continue;
                uint32_t a = (r->w & ~ARS_SHADOW) * 2; int k = 0;
                for (; k < P; k++) { uint32_t q = a - (uint32_t)ARS_DK[k]; if (q >= r0 && q < E) break; }
                if (k == P) continue;
                uint32_t q = a - (uint32_t)ARS_DK[k] - r0, row = q / s, col = q % s;
                ARS_PXK[j] = (uint32_t)k << 28 | row << 12 | col;
                if ((int)col < minc) minc = (int)col; if ((int)col > maxc) maxc = (int)col; any = 1; }
            if (!any) continue;
            int xwrap = (uint32_t)(maxc - minc) * 8 > rowpx / 2, xleft = !xwrap && minc * 8 - camx >= W;   /* wholly in the margin: the next row's left edge */
            int x0 = 1 << 30, y0 = 1 << 30, x1 = -(1 << 30), y1 = -(1 << 30), miny = 1 << 30, maxy = -(1 << 30);
            for (int pass2 = 0; pass2 < 3; pass2++) {
                for (uint32_t i = o->w0; i != o->w1; i++) { uint32_t j = i & (ARS_NWR - 1), pk = ARS_PXK[j]; if (pk == 0xffffffffu) continue;
                    ArsWr *r = &ARS_WR[j]; int k = (int)(pk >> 28), row = (int)((pk >> 12) & 0xffff), col = (int)(pk & 0xfff);
                    int px = col * 8 - camx + (ARS_LN[v0 + top].base[k & 1] - bx), y = row - row0;
                    if (xleft || (xwrap && (uint32_t)col * 8 >= rowpx / 2)) { px -= (int)rowpx; y += 1; }
                    y = ((y % (int)rows) + (int)rows) % (int)rows;
                    if (pass2 == 0) { if (y < miny) miny = y; if (y > maxy) maxy = y; continue; }
                    if ((maxy - miny > (int)rows / 2 && y >= (int)rows / 2) || (miny >= H && miny >= H + ((int)rows - H) / 2)) y -= (int)rows;   /* across the ring's end; wholly in the hidden rows: the nearer edge */
                    for (int b = 0; b < 16; b++) { if (!((r->m >> (15 - b)) & 1)) continue; int xx = px + b;
                        if (pass2 == 1) { if (xx < x0) x0 = xx; if (xx > x1) x1 = xx; if (y < y0) y0 = y; if (y > y1) y1 = y; continue; }
                        uint8_t *p = R->pix + R->obj[no].pix + (y - y0) * (x1 - x0 + 1) + (xx - x0);
                        if (*p == 255) *p = 0;
                        *p = (uint8_t)((*p & ~(1 << k)) | (((r->v >> (15 - b)) & 1) << k)); }
                }
                if (pass2 == 1) {
                    int w = x1 - x0 + 1, hgt = y1 - y0 + 1;
                    if (no >= ARS_NO || w <= 0 || hgt <= 0 || pool + w * hgt > ARS_POOL) goto full;
                    ArsObj *ob = &R->obj[no]; ob->node = o->node; ob->serial = (int32_t)o->serial; ob->k = o->k; ob->kind = kind;
                    ob->x = (int16_t)o->x; ob->y = (int16_t)o->y; ob->img = (int16_t)o->img; ob->pass = o->pass;
                    ob->sx = x0; ob->sy = y0; ob->w = w; ob->h = hgt; ob->pix = pool;
                    memset(R->pix + pool, 255, (size_t)(w * hgt));
                }
            }
            pool += R->obj[no].w * R->obj[no].h;
            no++;
        }
    }
full:
    R->nobj = no; R->pool = pool;
    {   /* the frame's pass: the one most of its objects come from (the game may draw a piece of the next pass into the shown buffer) */
        int bn = 0;
        for (int i = 0; i < no; i++) { int c = 0; for (int j = 0; j < no; j++) c += R->obj[j].pass == R->obj[i].pass; if (c > bn || (c == bn && R->obj[i].pass < maxpass)) { bn = c; maxpass = R->obj[i].pass; } }
    }
    if (maxpass < 0) maxpass = ARS_LASTPASS;
    ARS_LASTPASS = maxpass;
    R->pass = maxpass; R->pass_f = ARS_PT[maxpass & 63].f; R->pass_c = ARS_PT[maxpass & 63].c;
    if (ARS_NXS.pass > maxpass && ARS_NXS.n) { R->nx_pass = ARS_NXS.pass; R->nx_f = ARS_NXS.f; R->nx_c = ARS_NXS.c; R->nnx = ARS_NXS.n; memcpy(R->nx, ARS_NXS.e, sizeof(ArsNx) * (size_t)ARS_NXS.n);
        if ((ARS_C.cam_x || ARS_C.cam_y) && ARS_PCAM[maxpass & 63].pass == maxpass) {   /* the logic's camera of the shown pass and of the next one */
            R->has_cam = 1; R->pcam_x = ARS_PCAM[maxpass & 63].cx; R->pcam_y = ARS_PCAM[maxpass & 63].cy; R->ncam_x = (uint16_t)ARS_NXS.cx; R->ncam_y = (uint16_t)ARS_NXS.cy; } }
    R->valid = 1;
    ARS_STAMP++;
}
static void ars_conf(const ArsConf *c) { ARS_C = *c; }
#ifdef __EMSCRIPTEN__
EMSCRIPTEN_KEEPALIVE
#endif
void ars_on(int on) {
    if (on && !ARS_ON) {
        ars_prev_pc = h_pc_cb; h_pc_cb = ars_pc; ars_prev_wr = h_wr_cb; h_wr_cb = ars_wr;
        ars_prev_line = ard_line_cb; ard_line_cb = ars_line; ars_prev_spr = ard_spr_cb; ard_spr_cb = ars_spr; ars_prev_fetch = ard_fetch_cb; ard_fetch_cb = ars_fetch;
        memset(ARS_SV, 0, sizeof ARS_SV); memset(ARS_MU, 0, sizeof ARS_MU); memset(ARS_GEN, 0, sizeof ARS_GEN); memset(ARS_OCC, 0, sizeof ARS_OCC);
        ARS_WRN = ARS_SERIAL = ARS_CUR = 0; ARS_PB.on = 0; ARS_NRING = 0; ARS_ROW0 = -1; ARS_NXS.pass = 0; ARS_NXS.n = 0; ARS_FNSL = 0;
    }
    if (!on && ARS_ON) {
        if (h_pc_cb == ars_pc) h_pc_cb = ars_prev_pc;
        if (h_wr_cb == ars_wr) h_wr_cb = ars_prev_wr;
        if (ard_line_cb == ars_line) ard_line_cb = ars_prev_line;
        if (ard_spr_cb == ars_spr) ard_spr_cb = ars_prev_spr;
        if (ard_fetch_cb == ars_fetch) ard_fetch_cb = ars_prev_fetch;
    }
    ARS_ON = on;
}
#ifdef __EMSCRIPTEN__
EMSCRIPTEN_KEEPALIVE
#endif
void ars_hint(int obj_pc, int obj_reg, int obj_x, int obj_y, int obj_img, int pass_pc, int logic_pc, int cam_x, int cam_y) {   /* the page may give the hint */
    ArsConf c = { (uint32_t)obj_pc, obj_reg, obj_x, obj_y, obj_img, (uint32_t)pass_pc, (uint32_t)logic_pc, (uint32_t)cam_x, (uint32_t)cam_y }; ars_conf(&c);
}
#ifdef __EMSCRIPTEN__
EMSCRIPTEN_KEEPALIVE
#endif
uint8_t *ars_rec(void) { return (uint8_t *)ARS_REC; }
#ifdef __EMSCRIPTEN__
EMSCRIPTEN_KEEPALIVE
#endif
int ars_layout(int i) {                            /* the record's size and the offsets of its parts (wb-scenerec.js) */
    switch (i) {
    case 0: return (int)sizeof(ArsRec);
    case 1: return (int)offsetof(ArsRec, pal);
    case 2: return (int)offsetof(ArsRec, raw);
    case 3: return (int)offsetof(ArsRec, clean);
    case 4: return (int)offsetof(ArsRec, hud);
    case 5: return (int)offsetof(ArsRec, obj);
    case 6: return (int)offsetof(ArsRec, pix);
    case 7: return (int)offsetof(ArsRec, sl);
    case 8: return (int)offsetof(ArsRec, nx);
    case 9: return ARS_NR;
    case 10: return ARS_WMAX;
    case 11: return (int)sizeof(ArsObj);
    case 12: return (int)sizeof(ArsSl);
    case 13: return (int)sizeof(ArsNx);
    }
    return -1;
}
#endif
