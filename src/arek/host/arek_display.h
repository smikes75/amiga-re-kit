/* arek_display.h - the OCS picture line by line for a host of a translation (amiga-re-kit): arek.display (Python, 0 px
 * against vAmiga screenshots) in C, drawn as the host's beam passes each line, so CPU writes to the display registers
 * in mid-frame take effect from that line on. Copper from COP1LC at the start of the frame, lowres bitplanes 1-6 with
 * DDF/DIW/modulo/BPLCON1, dual playfield, EHB, HAM6, hires (two pixels per lowres pixel, ARD_PIXH), sprites 0-7 with
 * attached pairs and priorities, vAmiga's colours.
 *   Measured additions (Alien Breed II against VAHL_SHOTS / VAHL_BUSLOG, arek selftest display): with DDFSTRT not a
 *   multiple of 8 the first pixel is delayed by (scroll + 2 * (DDFSTRT & 7)) & 15; the sprites' DMA as vAmiga's Agnus and
 *   Denise do it: on line 25 (with sprite DMA on) VSTOP of every sprite is forced to 25 so its control words are fetched,
 *   VSTART turns the data DMA on and VSTOP off, the words are taken in the sprite's slots of the line ($15 + 4n: POS or
 *   the first data word, $17 + 4n: CTL or the second; lines 25-310) after the Copper's writes before them, a data word
 *   arms Denise and a CTL word (by DMA or a register write) disarms it; a slot is not served without DMACON SPREN and
 *   DMAEN (DMACON known; a Copper write to DMACON sets or clears bits) or, on a line with bitplane DMA, from DDFSTRT - 1
 *   on (DDFSTRT $24: sprite 3 gets one word, sprites 4-7 none; the missing word keeps the old register - a striped
 *   sprite and a vertical line on the screen, as the emulator shows), and a sprite whose VSTOP passes while its slots
 *   are not served keeps showing its last data; sprites only inside the display window; with 6 lowres planes the Copper
 *   gets both free even slots of a fetch group; the Copper's WAIT/SKIP comparator sees the beam two CCK ahead (h + 2);
 *   HAM6 bits 4-5 = palette / blue / red / green from the previous pixel, the chain starting at COLOR00 on every line;
 *   hires: 2 words per 8-CCK block, 4 planes, the first pixel at 2 * DDFSTRT + 9, the Copper's slots in 4-CCK blocks.
 * Output: the 12-bit colour of every lowres pixel (ARD_PIX[v][h]) and 716 x 285 RGB24 like a VAHeadless screenshot
 * (x = 2h - 196, y = v - 26). Header-only, MIT. No game data.
 *
 * Needs before it: MEM / MEMSZ (chip RAM) and CREG (the custom registers, for DMACON) of the runtime, or ARD_RD16(a),
 * ARD_DMACON and ARD_DMACON_WRITE(v) defined by the host. Calls: ard_write(off, v) for every write to a display register
 * ($080-$086, $08E-$094, $0E0-$10A, $120-$1BE) from the Copper (inside) and the CPU (the host, after ard_until(line of
 * the write)); ard_frame_start() at the start of a frame; ard_until(v) draws the lines before v; ard_to_rgb() converts
 * the frame; ARD_LAST = the frame's last line (311; the host sets it from its LOF), where sprite DMA stops.
 * Hooks: ard_line_cb(v) before a line is drawn, ard_spr_cb(v, sprites, n) with the sprites of the line, ARD_SPR_FULL = 1
 * draws the sprites as if every slot were served (a rebuild's enhanced mode), ard_overlay() lets a renderer-only RAM
 * window replace a range of chip RAM (smooth scrolling without touching the game's RAM). */
#ifndef AREK_DISPLAY_H
#define AREK_DISPLAY_H
#include <math.h>
#include <stdint.h>
#include <string.h>
#define ARD_LINES 313
#define ARD_CCKS 228
#define ARD_WIDTH (2 * ARD_CCKS)
#define ARD_HALF 0x1000
#define ARD_SHOT_W 716
#define ARD_SHOT_H 285
#ifndef ARD_DMACON
#define ARD_DMACON (CREG[0x096 >> 1])
#define ARD_DMACON_WRITE(x) (CREG[0x096 >> 1] = (uint16_t)(((x) & 0x8000) ? (CREG[0x096 >> 1] | ((x) & 0x7fff)) : (CREG[0x096 >> 1] & ~(x))))
#endif
#define ARD_VBLANK_END 25                              /* the first line with sprite DMA (PAL) */
static int ARD_LAST = 311;                             /* the frame's last line: sprite DMA stops there */
typedef struct { uint32_t pt; uint16_t pos, ctl, da, db; int armed, dma, vstop; } ArdSprite;   /* armed: Denise shows it; dma, vstop: Agnus */
#define ARD_VSTART(s) (((s)->pos >> 8) | ((((s)->ctl >> 2) & 1) << 8))
#define ARD_VSTOP(s) (((s)->ctl >> 8) | ((((s)->ctl >> 1) & 1) << 8))
typedef struct { int k, hs; uint16_t da, db; int att; } ArdSpriteLine;   /* a sprite on the current line */
static uint16_t ARD_R[0x100];                          /* the display registers as the renderer sees them */
static uint32_t ARD_BPL[6], ARD_LC[2];
static ArdSprite ARD_SPR[8], ARD_SPRI[8];              /* ARD_SPRI: the sprites at full DMA (ard_spri_cb) */
static struct { uint32_t pc; int need, waiting, skip, done; int wv, wh, vm, hm; } ARD_COP;
static uint16_t ARD_PIX[ARD_LINES][ARD_WIDTH];
static uint16_t ARD_PIXH[ARD_LINES][2 * ARD_WIDTH];    /* hires lines: both pixels of every lowres pixel */
static uint8_t ARD_HR[ARD_LINES];                      /* 1 = the line was drawn in hires (ARD_PIX holds the pair averages) */
static int ARD_NEXT = 0;                               /* the next line to draw */
static uint8_t ARD_RGB[ARD_SHOT_W * ARD_SHOT_H * 3];
static uint8_t ARD_PAL[0x2000][3];
static int ARD_READY = 0;
static int ARD_SPR_FULL = 0;                           /* 1 = sprites as if the bitplanes took no slot; 0 = the slot rule like the emulator */
static void (*ard_line_cb)(int v) = 0;
static void (*ard_spr_cb)(int v, const ArdSpriteLine *sl, int n) = 0;
static void (*ard_spri_cb)(int v, const ArdSpriteLine *sl, int n) = 0;
static int ARD_OVL_ON = 0; static const uint8_t *ARD_OVL = 0; static uint32_t ARD_OVL_LO = 0, ARD_OVL_HI = 0;

static void ard_pal_init(void) {                       /* vAmiga's monitor: YUV matrix, gamma 2.8 in / 2.2 out */
    double y[3] = { 0.299, 0.587, 0.114 }, u[3] = { -0.147, -0.289, 0.436 }, v[3] = { 0.615, -0.515, -0.100 }, m[3][3];
    for (int i = 0; i < 3; i++) { m[0][i] = y[i] + 1.140 * v[i]; m[1][i] = y[i] - 0.396 * u[i] - 0.581 * v[i]; m[2][i] = y[i] + 2.029 * u[i]; }
    static long adj[3][3][256]; int gamma[256];
    for (int o = 0; o < 3; o++) for (int i = 0; i < 3; i++) for (int x = 0; x < 256; x++)
        adj[o][i][x] = lround(m[o][i] * pow(x / 255.0, 2.8) * 255.0 * 65536.0);
    for (int i = 0; i < 256; i++) { double g = pow(i / 255.0, 1 / 2.2) * 255.0; if (g > 255) g = 255; gamma[i] = (int)lround(g); }
    for (int c = 0; c < 0x2000; c++) {
        int rgb8[3] = { ((c >> 8) & 15) << 4, ((c >> 4) & 15) << 4, (c & 15) << 4 };
        if (c & ARD_HALF) for (int i = 0; i < 3; i++) rgb8[i] >>= 1;
        for (int o = 0; o < 3; o++) {
            long acc = adj[o][0][rgb8[0]] + adj[o][1][rgb8[1]] + adj[o][2][rgb8[2]];
            ARD_PAL[c][o] = (uint8_t)gamma[acc < 0 ? 0 : acc > (255L << 16) ? 255 : (int)(acc >> 16)];
        }
    }
    ARD_READY = 1;
}
static inline uint16_t ard_rd(uint32_t a) {
    a &= 0x1ffffe;
    if (ARD_OVL_ON && a >= ARD_OVL_LO && a + 1 < ARD_OVL_HI) return (uint16_t)((ARD_OVL[a - ARD_OVL_LO] << 8) | ARD_OVL[a - ARD_OVL_LO + 1]);
#ifdef ARD_RD16
    return ARD_RD16(a);
#else
    return a + 1 < MEMSZ ? (uint16_t)((MEM[a] << 8) | MEM[a + 1]) : 0;
#endif
}
/* a renderer-only window over chip RAM [lo, hi): the renderer reads `bytes` there instead (on = 0 switches it off) */
static void ard_overlay(uint32_t lo, uint32_t hi, const uint8_t *bytes, int on) { ARD_OVL_LO = lo; ARD_OVL_HI = hi; ARD_OVL = bytes; ARD_OVL_ON = on && bytes; }
static void ard_write(uint32_t off, uint16_t v) {
    off &= 0x1fe;
    if (off == 0x096) { ARD_DMACON_WRITE(v); return; }   /* the Copper's DMACON write: set / clear */
    ARD_R[off >> 1] = v;
    if (off >= 0x0e0 && off <= 0x0f6) {
        int k = (off - 0x0e0) >> 2;
        ARD_BPL[k] = !(off & 2) ? (ARD_BPL[k] & 0xffff) | ((uint32_t)(v & 0x1f) << 16) : (ARD_BPL[k] & 0x1f0000) | (v & 0xfffe);
    } else if (off >= 0x120 && off <= 0x13e) {
        for (int q = 0; q < 2; q++) {
            ArdSprite *s = q ? &ARD_SPRI[(off - 0x120) >> 2] : &ARD_SPR[(off - 0x120) >> 2];
            s->pt = !(off & 2) ? (s->pt & 0xffff) | ((uint32_t)(v & 0x1f) << 16) : (s->pt & 0x1f0000) | (v & 0xfffe);
        }
    } else if (off >= 0x140 && off <= 0x17e) {
        for (int q = 0; q < 2; q++) {
            ArdSprite *s = q ? &ARD_SPRI[(off - 0x140) >> 3] : &ARD_SPR[(off - 0x140) >> 3]; int kind = off & 6;
            if (kind == 0) s->pos = v; else if (kind == 2) { s->ctl = v; s->armed = 0; s->vstop = ARD_VSTOP(s); }   /* a CTL write sets VSTOP, disarms */
        }
    } else if (off == 0x080) ARD_LC[0] = (ARD_LC[0] & 0xffff) | ((uint32_t)(v & 0x1f) << 16);
    else if (off == 0x082) ARD_LC[0] = (ARD_LC[0] & 0x1f0000) | (v & 0xfffe);
    else if (off == 0x084) ARD_LC[1] = (ARD_LC[1] & 0xffff) | ((uint32_t)(v & 0x1f) << 16);
    else if (off == 0x086) ARD_LC[1] = (ARD_LC[1] & 0x1f0000) | (v & 0xfffe);
}
static void ard_frame_start(void) {
    ARD_COP.pc = ARD_LC[0] & 0x1ffffe; ARD_COP.need = 2; ARD_COP.waiting = 0; ARD_COP.skip = 0; ARD_COP.done = 0;
    ARD_NEXT = 0;                                      /* the sprites keep their state: Agnus forces VSTOP on line 25 */
}
static void ard_copper(int line, int cck) {
    if (ARD_COP.done) return;
    int hc = cck < 0xe0 ? cck + 2 : cck - 0xe0;        /* the comparator sees h + 2 (vAmiga, the bus model) */
    if (ARD_COP.waiting) {
        int a1 = (line & 0xff) & ARD_COP.vm, a2 = hc & ARD_COP.hm, b1 = ARD_COP.wv & ARD_COP.vm, b2 = ARD_COP.wh & ARD_COP.hm;
        if (a1 > b1 || (a1 == b1 && a2 >= b2)) ARD_COP.waiting = 0;   /* waking costs this slot */
        return;
    }
    if (--ARD_COP.need) return;
    ARD_COP.need = 2;
    uint16_t w1 = ard_rd(ARD_COP.pc), w2 = ard_rd(ARD_COP.pc + 2); ARD_COP.pc += 4;
    if (ARD_COP.skip) { ARD_COP.skip = 0; return; }
    if (!(w1 & 1)) {                                   /* MOVE */
        uint32_t off = w1 & 0x1fe;
        if (off == 0x088 || off == 0x08a) ARD_COP.pc = ARD_LC[(off - 0x088) >> 1] & 0x1ffffe;
        else ard_write(off, w2);
        return;
    }
    if (w1 == 0xffff && w2 == 0xfffe) { ARD_COP.done = 1; return; }
    int wv = w1 >> 8, wh = w1 & 0xfe, vm = ((w2 >> 8) & 0x7f) | 0x80, hm = w2 & 0xfe;
    if (w2 & 1) { int a1 = (line & 0xff) & vm, a2 = hc & hm, b1 = wv & vm, b2 = wh & hm; ARD_COP.skip = a1 > b1 || (a1 == b1 && a2 >= b2); }
    else { ARD_COP.waiting = 1; ARD_COP.wv = wv; ARD_COP.wh = wh; ARD_COP.vm = vm; ARD_COP.hm = hm; }
}
static uint16_t ard_avg12(uint16_t a, uint16_t b) {       /* two hires pixels in one lowres pixel */
    return (uint16_t)(((((a >> 8) & 15) + ((b >> 8) & 15) + 1) >> 1 << 8) | ((((a >> 4) & 15) + ((b >> 4) & 15) + 1) >> 1 << 4) | (((a & 15) + (b & 15) + 1) >> 1));
}
/* the colour of lowres pixel h (sub 0/1: the hires half of it); ham = the line's HAM chain state; vwin = the line lies in
 * the display window (outside it, vertically or horizontally, everything is COLOR00) */
static uint16_t ard_pixel(int h, uint16_t words[6][64], int nw, const int base[2], int n, const ArdSpriteLine *sl, int ns, int sub, uint16_t *ham, int vwin) {
    uint16_t con0 = ARD_R[0x100 >> 1], con2 = ARD_R[0x104 >> 1]; int dual = !!(con0 & 0x400);
    int pf1 = 0, pf2 = 0, idx = 0;
    int diwstrt = ARD_R[0x08e >> 1] ? ARD_R[0x08e >> 1] : 0x2c81, diwstop = ARD_R[0x090 >> 1] ? ARD_R[0x090 >> 1] : 0x2cc1;
    int inwin = vwin && (diwstrt & 0xff) <= h && h < ((diwstop & 0xff) | 0x100);
    if (!inwin) { if (ham && n == 6 && (con0 & 0x0800)) *ham = ARD_R[0x180 >> 1] & 0xfff; return ARD_R[0x180 >> 1] & 0xfff; }
    if (nw) {
        for (int k = 0; k < n; k++) { int i = h - base[k & 1]; if (sub >= 0) i = 2 * i + sub; if (i >= 0 && i < nw * 16) idx |= ((words[k][i >> 4] >> (15 - (i & 15))) & 1) << k; }
        if (dual) { pf1 = (idx & 1) | (idx >> 1 & 2) | (idx >> 2 & 4); pf2 = (idx >> 1 & 1) | (idx >> 2 & 2) | (idx >> 3 & 4); }
    }
    int spc = -1, spair = 4;
    for (int j = 0; j < ns; j++) {
        const ArdSpriteLine *x = &sl[j];
        if ((x->k & 1) && x->att) continue;
        if (x->hs <= h && h < x->hs + 16) {
            int b = 15 - (h - x->hs), s = ((x->da >> b) & 1) | (((x->db >> b) & 1) << 1), col;
            const ArdSpriteLine *mate = 0;
            if (!(x->k & 1)) for (int q = 0; q < ns; q++) if (sl[q].k == x->k + 1 && sl[q].att) { mate = &sl[q]; break; }
            if (mate) { s |= (((mate->da >> b) & 1) << 2) | (((mate->db >> b) & 1) << 3); col = 16 + s; }
            else col = 16 + 4 * (x->k >> 1) + s;
            if (s) { spc = col; spair = x->k >> 1; break; }   /* lower numbered sprites win */
        }
    }
    if (dual) {
        int pf2pri = !!(con2 & 0x40);
        int nz[2], col[2], pri[2];
        if (pf2pri) { nz[0] = pf2; col[0] = 8 + pf2; pri[0] = (con2 >> 3) & 7; nz[1] = pf1; col[1] = pf1; pri[1] = con2 & 7; }
        else { nz[0] = pf1; col[0] = pf1; pri[0] = con2 & 7; nz[1] = pf2; col[1] = 8 + pf2; pri[1] = (con2 >> 3) & 7; }
        for (int i = 0; i < 2; i++) {
            if (spc >= 0 && spair < pri[i]) return ARD_R[(0x180 >> 1) + spc] & 0xfff;
            if (nz[i]) return ARD_R[(0x180 >> 1) + col[i]] & 0xfff;
        }
        return spc >= 0 ? ARD_R[(0x180 >> 1) + spc] & 0xfff : ARD_R[0x180 >> 1] & 0xfff;
    }
    int pri = (con2 >> 3) & 7;
    if (n == 6 && (con0 & 0x0800) && ham) {            /* HAM6 */
        int c = idx & 15, ctl = (idx >> 4) & 3; uint16_t prev = *ham;
        uint16_t col = ctl == 0 ? (ARD_R[(0x180 >> 1) + c] & 0xfff) : ctl == 1 ? (uint16_t)((prev & 0xff0) | c)
            : ctl == 2 ? (uint16_t)((prev & 0x0ff) | (c << 8)) : (uint16_t)((prev & 0xf0f) | (c << 4));
        *ham = col;
        if (spc >= 0 && (spair < pri || !idx)) return ARD_R[(0x180 >> 1) + spc] & 0xfff;
        return col;
    }
    if (spc >= 0 && (spair < pri || !idx)) return ARD_R[(0x180 >> 1) + spc] & 0xfff;
    if (n == 6 && !(con0 & 0x0c00) && (idx & 32)) return (ARD_R[(0x180 >> 1) + (idx & 31)] & 0xfff) | ARD_HALF;
    return ARD_R[(0x180 >> 1) + idx] & 0xfff;
}
static const int ARD_PLANE_AT[8] = { 99, 4, 6, 2, 99, 3, 5, 1 };
static const int ARD_PLANE_AT_HR[4] = { 4, 2, 3, 1 };    /* hires: a block of 4 CCK */
static int ard_sdma(void) { return ARD_DMACON ? (ARD_DMACON & 0x220) == 0x220 : 1; }   /* sprite DMA: SPREN and DMAEN (DMACON unknown = on) */
static inline uint16_t ard_sprite_word(ArdSprite *s) { uint16_t w = ard_rd(s->pt); s->pt = (s->pt + 2) & 0x1ffffe; return w; }
/* Agnus sets the sprite's DMA state for line v before the line: line 25 forces VSTOP (with sprite DMA on), the last line
 * stops the DMA, otherwise VSTART starts it and VSTOP stops it */
static void ard_sprite_line(ArdSprite *s, int v) {
    if (v == ARD_VBLANK_END) { if (ard_sdma()) s->vstop = ARD_VBLANK_END; }
    else if (v == ARD_LAST) s->dma = 0;
    else if (v > ARD_VBLANK_END) { if (v == ARD_VSTART(s)) s->dma = 1; if (v == s->vstop) s->dma = 0; }
}
/* one of the sprite's two slots on line v (second = the $17 + 4n one); free = the slot is served */
static void ard_sprite_slot(ArdSprite *s, int v, int second, int free) {
    if (v == s->vstop) {
        s->dma = 0;
        if (free && !second) s->pos = ard_sprite_word(s);
        else if (free) { s->ctl = ard_sprite_word(s); s->armed = 0; s->vstop = ARD_VSTOP(s); }
    } else if (s->dma && free) {
        if (!second) { s->da = ard_sprite_word(s); s->armed = 1; } else s->db = ard_sprite_word(s);
    }
}
static int ard_sprite_lines(ArdSprite *spr, ArdSpriteLine *sl) {   /* the armed sprites as Denise draws them on this line */
    int ns = 0;
    for (int k = 0; k < 8; k++) { ArdSprite *s = &spr[k]; if (!s->armed) continue;
        sl[ns].k = k; sl[ns].hs = (((s->pos & 0xff) << 1) | (s->ctl & 1)) + 1; sl[ns].da = s->da; sl[ns].db = s->db; sl[ns].att = (s->ctl >> 7) & 1; ns++; }
    return ns;
}
static void ard_line(int v) {
    if (ard_line_cb) ard_line_cb(v);
    ArdSpriteLine sl[8]; int ns = 0;
    uint16_t ham = ARD_R[0x180 >> 1] & 0xfff;           /* the HAM chain starts the line at COLOR00 */
    ARD_HR[v] = 0;
    for (int k = 0; k < 8; k++) { ard_sprite_line(&ARD_SPR[k], v); ard_sprite_line(&ARD_SPRI[k], v); }
    uint16_t con0 = ARD_R[0x100 >> 1];
    int diwstrt = ARD_R[0x08e >> 1] ? ARD_R[0x08e >> 1] : 0x2c81, diwstop = ARD_R[0x090 >> 1] ? ARD_R[0x090 >> 1] : 0x2cc1;
    int v0 = diwstrt >> 8, sv = diwstop >> 8, vwin = v0 <= v && v < (sv | ((sv & 0x80) ? 0 : 0x100));
    int bpl_line = ((con0 >> 12) & 7) && vwin && (ARD_DMACON & 0x300) == 0x300;   /* bitplane DMA takes slots this line (DMACON known) */
    static uint16_t words[6][64]; int nw = 0, fetch = 0, fetch_end = 0, nplanes = 0, base[2] = { 0, 0 }, hr = 0;
    for (int c = 0; c < ARD_CCKS; c++) {
        int ddfstrt = ARD_R[0x092 >> 1] ? ARD_R[0x092 >> 1] : 0x38, ddfstop = ARD_R[0x094 >> 1] ? ARD_R[0x094 >> 1] : 0xd0;
        if (c >= 0x15 && c <= 0x33 && !((c - 0x15) & 1) && v >= ARD_VBLANK_END && v < ARD_LAST) {   /* a sprite's DMA slot */
            int k = (c - 0x15) >> 2, second = ((c - 0x15) >> 1) & 1, sd = ard_sdma();
            ard_sprite_slot(&ARD_SPR[k], v, second, sd && (ARD_SPR_FULL || !(bpl_line && c >= ddfstrt - 1)));
            ard_sprite_slot(&ARD_SPRI[k], v, second, sd);   /* every slot served */
        }
        if (c == 0x34) {
            ns = ard_sprite_lines(ARD_SPR, sl);
            if (ard_spr_cb) ard_spr_cb(v, sl, ns);
            if (ard_spri_cb) { ArdSpriteLine si[8]; int nsi = ard_sprite_lines(ARD_SPRI, si); ard_spri_cb(v, si, nsi); }
        }
        if (c == ddfstrt) {
            uint16_t con0 = ARD_R[0x100 >> 1]; int n = (con0 >> 12) & 7;
            int diwstrt = ARD_R[0x08e >> 1] ? ARD_R[0x08e >> 1] : 0x2c81, diwstop = ARD_R[0x090 >> 1] ? ARD_R[0x090 >> 1] : 0x2cc1;
            int v0 = diwstrt >> 8, sv = diwstop >> 8, v1 = sv | ((sv & 0x80) ? 0 : 0x100);
            hr = !!(con0 & 0x8000);
            if (n && v0 <= v && v < v1) {
                nw = (ddfstop - ddfstrt) / 8 + 1; if (hr) nw *= 2; if (nw > 64) nw = 64;
                if (n > (hr ? 4 : 6)) n = hr ? 4 : 6;
                for (int k = 0; k < n; k++) for (int i = 0; i < nw; i++) words[k][i] = ard_rd(ARD_BPL[k] + 2 * i);
                for (int k = 0; k < n; k++) { int16_t mod = (int16_t)ARD_R[((k % 2 == 0) ? 0x108 : 0x10a) >> 1]; ARD_BPL[k] = (ARD_BPL[k] + 2 * nw + mod) & 0x1ffffe; }
                uint16_t con1 = ARD_R[0x102 >> 1]; int start = 2 * ddfstrt + 17, ofs = 2 * (ddfstrt & 7);
                if (hr) { start = 2 * ddfstrt + 9; ofs = 0; }   /* hires $3C = lowres $38: the same first pixel */
                base[0] = start + (((con1 & 15) + ofs) & 15); base[1] = start + ((((con1 >> 4) & 15) + ofs) & 15);
                fetch_end = ddfstrt + (hr ? 4 : 8) * nw; nplanes = n; fetch = 1;
                if (hr) { ARD_HR[v] = 1; for (int x = 0; x < 4 * c; x++) ARD_PIXH[v][x] = ARD_PIX[v][x >> 1]; }
            } else fetch = -1;
        }
        if (!(c & 1)) {                                /* the Copper: even slots not taken by bitplane DMA */
            int busy = 0;
            if (fetch == 1 && ddfstrt <= c && c < fetch_end) {
                if (hr) busy = ARD_PLANE_AT_HR[(c - ddfstrt) & 3] <= nplanes;
                else { int pos = (c - ddfstrt) & 7; busy = ARD_PLANE_AT[pos] <= nplanes || (pos == 4 && v >= 1 && nplanes < 6); }   /* 6 planes: both free even slots */
            }
            if (!busy) ard_copper(v, c);
        }
        for (int h = 2 * c; h <= 2 * c + 1; h++) {
            if (hr && fetch == 1) {
                uint16_t a = ard_pixel(h, words, nw, base, nplanes, sl, ns, 0, &ham, vwin), b = ard_pixel(h, words, nw, base, nplanes, sl, ns, 1, &ham, vwin);
                ARD_PIXH[v][2 * h] = a; ARD_PIXH[v][2 * h + 1] = b; ARD_PIX[v][h] = ard_avg12(a, b);
            } else {
                ARD_PIX[v][h] = ard_pixel(h, words, fetch == 1 ? nw : 0, base, nplanes, sl, ns, -1, &ham, vwin);
                if (ARD_HR[v]) ARD_PIXH[v][2 * h] = ARD_PIXH[v][2 * h + 1] = ARD_PIX[v][h];
            }
        }
    }
}
/* every line before v */
static void ard_until(int v) { if (v > ARD_LINES) v = ARD_LINES; while (ARD_NEXT < v) ard_line(ARD_NEXT++); }
static void ard_to_rgb(void) {
    if (!ARD_READY) ard_pal_init();
    for (int y = 0; y < ARD_SHOT_H; y++) {
        int v = y + 26; uint8_t *o = ARD_RGB + y * ARD_SHOT_W * 3;
        for (int x = 0; x < ARD_SHOT_W; x++, o += 3) {
            int h = (x + 196) >> 1; uint16_t c = v >= ARD_LINES || h >= ARD_WIDTH ? 0 : ARD_HR[v] ? ARD_PIXH[v][x + 196] : ARD_PIX[v][h];
            o[0] = ARD_PAL[c][0]; o[1] = ARD_PAL[c][1]; o[2] = ARD_PAL[c][2];
        }
    }
}
#endif
