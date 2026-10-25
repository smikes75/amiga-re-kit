"""Static recompilation of 68000 code to C (prototype, "M7" in the game docs).

One 68k routine becomes one C function; registers live in an ``M68`` context,
memory in ``MEM[]`` with a write log (``WRLOG``) so that a run can be compared
address by address against a RAM dump taken from the emulator. The embedded
runtime models only what the games used of the custom chips (DMACON,
BLTSIZE and an area-mode blitter); everything else is logged as
``HW_UNMODELLED`` rather than silently faked.

Verification recipe (see docs/RECOMP.md of the Turrican II project):
capture RAM + registers at the routine's call and at its return with
``arek.headless.bpstate``, run the recompiled function over the first
state and diff registers, CCR and every written address against the second.
"""
import re

from . import decoder
from .decoder import (SZ_B, SZ_W, SZ_L, SZNAME, FLOW_MODES, NOFLOW, Flow, Inline, JumpTable,
                      jtab_targets, Unsupported, decode, successors, call_tree)
from .timing import cycles, ea_class, ea_time

# ---------------------------------------------------------------- generator

TIMING_RT = r'''
#ifndef AREK_TIMING
#define AREK_TIMING
/* 68000 clocks of the translated code (generate(timing=True); arek.m68k.timing, no DMA
   contention). Compile with -DTICK_HOOK to route every instruction to the host instead. */
uint64_t CYCLES = 0;
#ifndef PROF_TICK
#define PROF_TICK(n) ((void)0)
#endif
#ifndef COV_TICK                /* generate(cover=..., cover_in_tick=True): the coverage mark rides in TICK */
#define COV_TICK(pc) ((void)0)
#endif
#ifndef TICK                    /* a host may define its own TICK(pc, n) before this */
#ifdef TICK_HOOK
void tick_hook(M68 *m, uint32_t pc, uint32_t clocks);
#define TICK(pc, n) (COV_TICK(pc), PROF_TICK(n), tick_hook(m, (pc), (n)))
#else
#define TICK(pc, n) (COV_TICK(pc), PROF_TICK(n), CYCLES += (n))
#endif
#endif
static uint32_t mulu_t(uint32_t s) { return 38 + 2 * (uint32_t)__builtin_popcount(s & 0xffff); }
static uint32_t muls_t(uint32_t s) { uint32_t v = (s & 0xffff) << 1; return 38 + 2 * (uint32_t)__builtin_popcount((v ^ (v >> 1)) & 0xffff); }
/* DIVU/DIVS clocks: Jorge Cwik's analysis of the microcode, in the form of Moira's cyclesDiv (MIT) */
static uint32_t divu_t(uint32_t dividend, uint32_t divisor) {
    divisor &= 0xffff;
    if ((dividend >> 16) >= divisor) return 10;
    uint32_t mc = 38, hdivisor = divisor << 16;
    for (int i = 0; i < 15; i++) {
        if (dividend & 0x80000000u) dividend = (dividend << 1) - hdivisor;
        else { dividend <<= 1; if (dividend >= hdivisor) { dividend -= hdivisor; mc += 1; } else mc += 2; }
    }
    return 2 * mc;
}
static uint32_t divs_t(uint32_t dividend, uint32_t divisor) {
    int64_t dv = (int32_t)dividend, ds = (int16_t)divisor;
    int64_t adv = dv < 0 ? -dv : dv, ads = ds < 0 ? -ds : ds;
    uint32_t mc = dv < 0 ? 7 : 6;
    if ((adv >> 16) >= ads) return (mc + 2) * 2;
    mc += 55;
    if (ds >= 0) mc = dv < 0 ? mc + 1 : mc - 1;
    uint32_t aq = (uint32_t)(adv / ads);
    for (int i = 0; i < 15; i++) { if (!(aq & 0x8000)) mc++; aq = (aq << 1) & 0xffff; }
    return 2 * mc;
}
#endif
'''

PROFILE_RT = r'''
/* Routine profile (generate(profile=True)): per translated entry the calls, the 68000 clocks
   (with timing) and the bytes and 1 KB pages it wrote - chip RAM pages first, slow RAM pages
   from MEMSZ/1024. prof_dump(f, frame) appends one row per entry, prof_reset() starts over:
   a host calls them per frame, the verification driver at exit (AREK_PROFILE=file).
   Attribution follows the translated call tree: a routine's own instructions and writes. */
#define PROF_N %(n)du
#define PROF_PAGEBYTES (((MEMSZ + SLOWSZ) / 1024 + 7) / 8)
static const uint32_t PROF_ADDR[PROF_N] = { %(addrs)s };
static uint64_t PROF_CALLS[PROF_N], PROF_CYC[PROF_N], PROF_WR[PROF_N];
static uint8_t PROF_PAGES[PROF_N][PROF_PAGEBYTES];
static int PROF_CUR = -1, PROF_STACK[512], PROF_SP = 0;
#define PROF_TICK(n) (PROF_CUR >= 0 ? (void)(PROF_CYC[PROF_CUR] += (n)) : (void)0)
#define PROF_WRITE(a) do { if (PROF_CUR >= 0) { PROF_WR[PROF_CUR]++; \
    PROF_PAGES[PROF_CUR][(a) >> 13] |= (uint8_t)(1u << (((a) >> 10) & 7)); } } while (0)
static void prof_enter(int i) { PROF_CALLS[i]++; if (PROF_SP < 512) PROF_STACK[PROF_SP++] = PROF_CUR; PROF_CUR = i; }
static void prof_leave(void) { PROF_CUR = PROF_SP ? PROF_STACK[--PROF_SP] : -1; }
void prof_reset(void) {
    memset(PROF_CALLS, 0, sizeof PROF_CALLS); memset(PROF_CYC, 0, sizeof PROF_CYC);
    memset(PROF_WR, 0, sizeof PROF_WR); memset(PROF_PAGES, 0, sizeof PROF_PAGES);
}
void prof_dump(FILE *f, long frame) {
    static int header = 0;
    if (!header) { header = 1; fprintf(f, "H %%x %%x %%x\n", (unsigned)MEMSZ, (unsigned)SLOWBASE, (unsigned)SLOWSZ); }
    for (unsigned i = 0; i < PROF_N; i++) {
        if (!PROF_CALLS[i] && !PROF_WR[i]) continue;
        fprintf(f, "R %%ld %%x %%llu %%llu %%llu", frame, PROF_ADDR[i], (unsigned long long)PROF_CALLS[i],
                (unsigned long long)PROF_CYC[i], (unsigned long long)PROF_WR[i]);
        int run = -1;
        for (unsigned p = 0; p <= 8 * PROF_PAGEBYTES; p++) {
            int on = p < 8 * PROF_PAGEBYTES && (PROF_PAGES[i][p >> 3] >> (p & 7)) & 1;
            if (on && run < 0) run = (int)p;
            if (!on && run >= 0) { if ((int)p - 1 == run) fprintf(f, " %%x", run); else fprintf(f, " %%x-%%x", run, p - 1); run = -1; }
        }
        fputc('\n', f);
    }
}
'''

COVER_RT = r'''
/* Coverage (generate(cover=True)): one bit per instruction word of the image [COV_LO, COV_LO + 2 * COV_N),
   set when the instruction at that address runs. cov_dump(f) writes the addresses that ran as ranges,
   cov_reset() clears them; the verification driver writes the dump to $AREK_COVER at exit, a host per
   run. `arek cover` turns it into executed / translated instructions per routine. */
#define COV_LO 0x%(lo)xu
#define COV_N %(n)du
static uint8_t COV[(COV_N + 7) / 8];
static inline void cov_mark(uint32_t pc) { uint32_t i = (pc - COV_LO) >> 1; if (i < COV_N) COV[i >> 3] |= (uint8_t)(1u << (i & 7)); }
#define COV_MARK(pc) cov_mark(pc)
%(in_tick)s
void cov_reset(void) { memset(COV, 0, sizeof COV); }
void cov_dump(FILE *f) {
    fprintf(f, "H %%x %%x\n", (unsigned)COV_LO, (unsigned)COV_N);
    long run = -1;
    for (uint32_t i = 0; i <= COV_N; i++) {
        int on = i < COV_N && (COV[i >> 3] >> (i & 7)) & 1;
        if (on && run < 0) run = (long)i;
        if (!on && run >= 0) { fprintf(f, "%%x-%%x\n", (unsigned)(COV_LO + 2 * run), (unsigned)(COV_LO + 2 * (i - 1))); run = -1; }
    }
}
'''

WAIT_RT = r'''
/* A wait loop "L: tst/btst/cmp/cmpa/cmpi <mem> ; bcc L" polls memory or a hardware register:
   statically translated, time must move on inside it (an interrupt, the beam) or it never
   ends. WAIT_LOOP(m, pc, addr) runs on every repeat; pc = L, addr = the polled address.
   Empty unless the host defines it. */
#ifndef WAIT_LOOP
#define WAIT_LOOP(m, pc, addr) ((void)0)
#endif
'''

RUNTIME = r'''
/* Vygenerovano tools/recomp.py - neupravovat rucne. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifndef MEMSZ
#define MEMSZ 0x80000u                  /* chip RAM from address 0 */
#endif
#ifndef SLOWSZ
#define SLOWSZ 0u                       /* slow RAM at SLOWBASE (e.g. 0x80000u), 0 = none */
#endif
#ifndef SLOWBASE
#define SLOWBASE 0xc00000u
#endif
uint8_t MEM[MEMSZ];
uint8_t WRLOG[MEMSZ];
#if SLOWSZ
uint8_t SLOW[SLOWSZ];
uint8_t SLOWLOG[SLOWSZ];
#endif

typedef struct { uint32_t d[8], a[8]; int x, n, z, v, c; uint32_t srhi; } M68;
void exit_point(M68 *m, uint32_t at);   /* a Flow.exits routine was called: the host ends the run */

%%PROFILE%%
%%TIMING%%

#ifdef BUS_HOOK                          /* the bus model behind the hooks (bus/arek_bus_glue.h, -DTICK_HOOK -DBUS_HOOK) */
void bus_access_hook(uint32_t a);
void bus_blit_hook(uint16_t con0, uint16_t con1, uint16_t size);
int bus_bbusy_hook(void);
double bus_time_hook(void);
#define BUS_ACCESS(a) bus_access_hook(a)
#define BUS_BLIT(c0, c1, sz) bus_blit_hook((uint16_t)(c0), (uint16_t)(c1), (uint16_t)(sz))
#define BUS_BBUSY() bus_bbusy_hook()
#else
#define BUS_ACCESS(a) ((void)0)
#define BUS_BLIT(c0, c1, sz) ((void)0)
#define BUS_BBUSY() 0
#endif
#ifndef OOB_ZERO
#define OOB_ZERO 0                      /* generate(oob='zero'): reads outside the modelled RAM give 0, writes are dropped */
#endif
static long OOB_COUNT = 0;
static void oob(uint32_t a) {
#if OOB_ZERO
    static uint32_t seen[64];
    static int n = 0;
    OOB_COUNT++;
    for (int i = 0; i < n; i++) if (seen[i] == (a & ~0x3ffu)) return;      /* one line per KB */
    if (n < 64) seen[n++] = a & ~0x3ffu;
    fprintf(stderr, "access outside the modelled RAM (MEMSZ %x, SLOWBASE %x SLOWSZ %x): %08x - reads 0, writes dropped\n",
            MEMSZ, SLOWBASE, SLOWSZ, a);
#else
    fprintf(stderr, "access outside the modelled RAM (MEMSZ %x, SLOWBASE %x SLOWSZ %x): %08x\n",
            MEMSZ, SLOWBASE, SLOWSZ, a);
    exit(3);
#endif
}
static uint8_t *slow_at(uint32_t a) {   /* NULL outside slow RAM */
#if SLOWSZ
    if (a - SLOWBASE < SLOWSZ) return &SLOW[a - SLOWBASE];
#endif
    (void)a;
    return 0;
}

/* --- model hardwaru: jen to, co hra pouziva (docs/RECOMP.md 8) ------------ */
#define CUSTOM(a) (((a) & 0xfff000u) == 0xdff000u)
static uint16_t CREG[0x100];            /* $dff000-$dff1fe po slovech */
static uint8_t  HW_UNMODELLED[0x100];   /* registry, ktere jsme jen predstirali */
static char HW_NOTE[16][80];
static int HW_NOTES = 0, BZERO = 1;
static long BLITS = 0;

static void hw_note(const char *s) {
    for (int i = 0; i < HW_NOTES; i++) if (!strcmp(HW_NOTE[i], s)) return;
    if (HW_NOTES < 16) snprintf(HW_NOTE[HW_NOTES++], 80, "%s", s);
}
static uint32_t rd16(uint32_t a);
static void wr16(uint32_t a, uint32_t v);
static void run_blit(void);

static uint32_t hw_read(uint32_t off) {
    switch (off) {
    case 0x002:                          /* DMACONR: blitter u nas dobehne hned */
        return (CREG[0x096 >> 1] & 0x1fff) | (BZERO ? 0x2000 : 0) | (BUS_BBUSY() ? 0x4000 : 0);
    case 0x01c:                          /* INTENAR = shadow of INTENA writes */
        return CREG[0x09a >> 1] & 0x7fff;
    default:
        HW_UNMODELLED[off >> 1] = 1;
        return CREG[off >> 1];
    }
}
static void hw_write(uint32_t off, uint32_t v) {
    v &= 0xffff;
    switch (off) {
    case 0x096:                          /* DMACON: bit 15 = nastav/smaz */
    case 0x09a:                          /* INTENA: likewise, read back through INTENAR */
        if (v & 0x8000) CREG[off >> 1] |= v & 0x7fff;
        else CREG[off >> 1] &= ~(v & 0x7fff);
        return;
    case 0x058:                          /* BLTSIZE: zapis spousti blit */
        CREG[off >> 1] = v;
        BUS_BLIT(CREG[0x040 >> 1], CREG[0x042 >> 1], v);
        run_blit();
        return;
    default:
        if (off < 0x040 || off > 0x077) HW_UNMODELLED[off >> 1] = 1;
        CREG[off >> 1] = v;
        return;
    }
}
/* every access of the CPU to the chip bus is one BUS_ACCESS (a word or a byte); the _raw halves of a word do not count twice */
static uint32_t rd8_raw(uint32_t a) {
    if (CUSTOM(a)) { uint32_t w = hw_read(a & 0x1fe); return (a & 1) ? (w & 0xff) : (w >> 8); }
    if (a < MEMSZ) return MEM[a];
    uint8_t *p = slow_at(a);
    if (!p) { oob(a); return 0; }
    return *p;
}
static uint32_t rd8(uint32_t a) { BUS_ACCESS(a); return rd8_raw(a); }
static uint32_t rd16(uint32_t a) {
    BUS_ACCESS(a);
    if (CUSTOM(a)) return hw_read(a & 0x1fe);
    if (a + 1 < MEMSZ) return (MEM[a] << 8) | MEM[a + 1];
    return (rd8_raw(a) << 8) | rd8_raw(a + 1);
}
static uint32_t rd32(uint32_t a) { return (rd16(a) << 16) | rd16(a + 2); }
static void wr8_raw(uint32_t a, uint32_t v) {
    if (CUSTOM(a)) { v &= 0xff; hw_write(a & 0x1fe, (v << 8) | v); return; }   /* 68000: the byte on both halves of the bus */
    if (a < MEMSZ) { MEM[a] = v; WRLOG[a] = 1; PROF_WRITE(a); return; }
    uint8_t *p = slow_at(a);
    if (!p) { oob(a); return; }
    *p = v;
#if SLOWSZ
    SLOWLOG[a - SLOWBASE] = 1;
    PROF_WRITE(MEMSZ + (a - SLOWBASE));
#endif
}
static void wr8(uint32_t a, uint32_t v) { BUS_ACCESS(a); wr8_raw(a, v); }
static void wr16(uint32_t a, uint32_t v) {
    BUS_ACCESS(a);
    if (CUSTOM(a)) { hw_write(a & 0x1fe, v); return; }
    wr8_raw(a, v >> 8); wr8_raw(a + 1, v);
}
static void wr32(uint32_t a, uint32_t v) { wr16(a, v >> 16); wr16(a + 2, v); }

/* Blitter v rezimu oblasti: A/B/C -> D podle minterm tabulky (BLTCON0 bity 7-0),
   posun A o ASH a B o BSH, prvni a posledni slovo radku maskovane AFWM/ALWM,
   po kazdem radku se k ukazatelum pricte modulo. Tri rezimy, ktere hra pouziva
   (kopie $09f0, vypln $01f0, cookie cut $0fca), jsou jen ruzne mintermy. */
static uint16_t minterm(int lf, uint32_t a, uint32_t b, uint32_t c) {
    uint32_t d = 0;
    if (lf & 0x01) d |= ~a & ~b & ~c;
    if (lf & 0x02) d |= ~a & ~b &  c;
    if (lf & 0x04) d |= ~a &  b & ~c;
    if (lf & 0x08) d |= ~a &  b &  c;
    if (lf & 0x10) d |=  a & ~b & ~c;
    if (lf & 0x20) d |=  a & ~b &  c;
    if (lf & 0x40) d |=  a &  b & ~c;
    if (lf & 0x80) d |=  a &  b &  c;
    return d & 0xffff;
}
static uint32_t bltptr(int off) {
    return (((uint32_t)CREG[off >> 1] << 16) | CREG[(off + 2) >> 1]) & 0x7fffeu;   /* DMA ignores bit 0 */
}
static void set_bltptr(int off, uint32_t v) {
    CREG[off >> 1] = (v >> 16) & 0xffff; CREG[(off + 2) >> 1] = v & 0xffff;
}
/* Line mode (BLTCON1 bit 0; Hardware Reference Manual ch. 6): A = the dot (BLTADAT >> ASH), B = the
   pattern (BLTBDAT rotated by BSH), C/D = the word holding the dot, BLTAPTL = the error term (its sign
   starts in BLTCON1 bit 6), BLTAMOD = 4(dmin - dmax), BLTBMOD = 4 dmin, BLTCMOD = the row width.
   SUD (bit 4) set: X is the axis stepped every time (AUL, bit 2 = left), Y the one stepped when the
   error is not negative (SUL, bit 3 = up); SUD clear swaps the axes. SING (bit 1) = one dot per row. */
static void run_blit_line(void) {
    uint16_t con0 = CREG[0x040 >> 1], con1 = CREG[0x042 >> 1];
    int lf = con0 & 0xff, sh = con0 >> 12, bsh = con1 >> 12, sing = (con1 >> 1) & 1, sign = (con1 >> 6) & 1, onedot = 0;
    int h = CREG[0x058 >> 1] >> 6; if (!h) h = 1024;
    int16_t err = (int16_t)CREG[0x052 >> 1], amod = CREG[0x064 >> 1], bmod = CREG[0x062 >> 1], cmod = CREG[0x060 >> 1];
    uint16_t adat = CREG[0x074 >> 1] & CREG[0x044 >> 1], bdat = CREG[0x072 >> 1];
    uint16_t lb = (uint16_t)((bdat >> bsh) | (bdat << ((16 - bsh) & 15)));
    uint32_t cpt = bltptr(0x048), dpt = bltptr(0x054);
    BZERO = 1; BLITS++;
    for (int i = 0; i < h; i++) {
        uint16_t c = rd16(cpt), a = (uint16_t)(adat >> sh), b = (lb & 1) ? 0xffff : 0;
        uint16_t d = minterm(lf, a, b, c);
        int pix = !sing || !onedot; onedot = 1;
        #define LX_INC() do { if (++sh == 16) { sh = 0; cpt += 2; } } while (0)
        #define LX_DEC() do { if (sh-- == 0) { sh = 15; cpt -= 2; } } while (0)
        #define LY_INC() do { cpt += cmod; onedot = 0; } while (0)
        #define LY_DEC() do { cpt -= cmod; onedot = 0; } while (0)
        if (!sign) { err += amod; if (con1 & 0x10) { if (con1 & 0x08) LY_DEC(); else LY_INC(); } else { if (con1 & 0x08) LX_DEC(); else LX_INC(); } }
        else err += bmod;
        if (con1 & 0x10) { if (con1 & 0x04) LX_DEC(); else LX_INC(); } else { if (con1 & 0x04) LY_DEC(); else LY_INC(); }
        sign = err < 0;
        lb = (uint16_t)((lb << 1) | (lb >> 15));
        if (pix) { wr16(dpt, d); if (d) BZERO = 0; }
        dpt = cpt;
        #undef LX_INC
        #undef LX_DEC
        #undef LY_INC
        #undef LY_DEC
    }
    CREG[0x052 >> 1] = (uint16_t)err; set_bltptr(0x048, cpt); set_bltptr(0x054, dpt);
    CREG[0x040 >> 1] = (uint16_t)((con0 & 0x0fff) | (sh << 12));
    CREG[0x042 >> 1] = (uint16_t)((con1 & ~0x40) | (sign ? 0x40 : 0));
}
static void run_blit(void) {
    uint16_t con0 = CREG[0x040 >> 1], con1 = CREG[0x042 >> 1];
    int ash = con0 >> 12, bsh = con1 >> 12, lf = con0 & 0xff;
    int usea = (con0 >> 11) & 1, useb = (con0 >> 10) & 1;
    int usec = (con0 >> 9) & 1, used = (con0 >> 8) & 1;
    int desc = (con1 >> 1) & 1;
    if (con1 & 1) { run_blit_line(); return; }
    int fill = (con1 >> 3) & 3;                 /* fill (descending): bit 3 IFE inclusive, bit 4 EFE exclusive; bit 2 FCI = carry at row start */
    uint16_t size = CREG[0x058 >> 1];
    int h = size >> 6, w = size & 0x3f;
    if (!h) h = 1024;
    if (!w) w = 64;
    uint32_t apt = bltptr(0x050), bpt = bltptr(0x04c);
    uint32_t cpt = bltptr(0x048), dpt = bltptr(0x054);
    int16_t amod = CREG[0x064 >> 1], bmod = CREG[0x062 >> 1];
    int16_t cmod = CREG[0x060 >> 1], dmod = CREG[0x066 >> 1];
    uint16_t afwm = CREG[0x044 >> 1], alwm = CREG[0x046 >> 1];
    int step = desc ? -2 : 2;
    BZERO = 1;
    BLITS++;
    for (int y = 0; y < h; y++) {
        uint32_t aold = 0, bold = 0; int fc = (con1 >> 2) & 1;
        for (int x = 0; x < w; x++) {
            uint32_t adat = usea ? rd16(apt) : CREG[0x074 >> 1];
            uint32_t bdat = useb ? rd16(bpt) : CREG[0x072 >> 1];
            uint32_t cdat = usec ? rd16(cpt) : CREG[0x070 >> 1];
            if (x == 0) adat &= afwm;
            if (x == w - 1) adat &= alwm;
            uint32_t as, bs;
            if (!desc) {
                as = ((aold << 16) | adat) >> ash;
                bs = ((bold << 16) | bdat) >> bsh;
            } else {
                as = (((adat << 16) | aold) << ash) >> 16;
                bs = (((bdat << 16) | bold) << bsh) >> 16;
            }
            aold = adat; bold = bdat;
            uint16_t d = minterm(lf, as & 0xffff, bs & 0xffff, cdat);
            if (fill) {                         /* bit 0 to 15: an edge toggles the fill carry (HRM ch. 6) */
                uint16_t o = 0;
                for (int j = 0; j < 16; j++) { int b = (d >> j) & 1; if (b) fc ^= 1; if ((fill & 1) ? (b | fc) : fc) o |= (uint16_t)(1u << j); }
                d = o;
            }
            if (d) BZERO = 0;
            if (used) wr16(dpt, d);
            if (usea) apt += step;
            if (useb) bpt += step;
            if (usec) cpt += step;
            if (used) dpt += step;
        }
        if (usea) apt += amod;
        if (useb) bpt += bmod;
        if (usec) cpt += cmod;
        if (used) dpt += dmod;
    }
    set_bltptr(0x050, apt); set_bltptr(0x04c, bpt);
    set_bltptr(0x048, cpt); set_bltptr(0x054, dpt);
}

static const uint32_t MASK[3] = { 0xffu, 0xffffu, 0xffffffffu };
static const int BITS[3] = { 8, 16, 32 };

static void setd(M68 *m, int r, int sz, uint32_t v) {
    m->d[r] = (m->d[r] & ~MASK[sz]) | (v & MASK[sz]);
}
static void seta(M68 *m, int r, int sz, uint32_t v) {
    m->a[r] = (sz == 2) ? v : (uint32_t)(int32_t)(int16_t)v;   /* .w se rozsiruje znamenkem */
}
static int msb(uint32_t v, int sz) { return (v >> (BITS[sz] - 1)) & 1; }

static uint32_t sr_get(M68 *m) {
    return m->srhi | (m->x << 4) | (m->n << 3) | (m->z << 2) | (m->v << 1) | m->c;
}
static void sr_set(M68 *m, uint32_t v, int with_hi) {
    if (with_hi) m->srhi = v & 0xff00;       /* T/S/maska preruseni jen ulozime */
    m->x = (v >> 4) & 1; m->n = (v >> 3) & 1;
    m->z = (v >> 2) & 1; m->v = (v >> 1) & 1; m->c = v & 1;
}

static uint32_t f_logic(M68 *m, uint32_t r, int sz) {
    r &= MASK[sz];
    m->n = msb(r, sz); m->z = (r == 0); m->v = 0; m->c = 0;
    return r;
}
static uint32_t f_add(M68 *m, uint32_t s, uint32_t d, int sz) {
    uint32_t r = (s + d) & MASK[sz];
    int sm = msb(s, sz), dm = msb(d, sz), rm = msb(r, sz);
    m->n = rm; m->z = (r == 0);
    m->v = (sm == dm) && (rm != dm);
    m->c = (sm && dm) || (!rm && (sm || dm));
    m->x = m->c;
    return r;
}
static uint32_t f_sub(M68 *m, uint32_t s, uint32_t d, int sz) {   /* d - s */
    uint32_t r = (d - s) & MASK[sz];
    int sm = msb(s, sz), dm = msb(d, sz), rm = msb(r, sz);
    m->n = rm; m->z = (r == 0);
    m->v = (sm != dm) && (rm != dm);
    m->c = (sm && !dm) || (rm && (!dm || sm));
    m->x = m->c;
    return r;
}
static void f_cmp(M68 *m, uint32_t s, uint32_t d, int sz) {       /* jako sub, bez X */
    int x = m->x; f_sub(m, s, d, sz); m->x = x;
}
/* ADDX/SUBX: C, X and V from the whole operation d + s + X (d - s - X); Z is only cleared */
static uint32_t f_addx(M68 *m, uint32_t s, uint32_t d, int sz) {
    uint64_t full = (uint64_t)(s & MASK[sz]) + (d & MASK[sz]) + (uint32_t)m->x;
    uint32_t r = (uint32_t)full & MASK[sz];
    int sm = msb(s, sz), dm = msb(d, sz), rm = msb(r, sz);
    m->c = m->x = full > MASK[sz];
    m->v = (sm == dm) && (rm != dm); m->n = rm;
    if (r) m->z = 0;
    return r;
}
static uint32_t f_subx(M68 *m, uint32_t s, uint32_t d, int sz) {
    uint64_t sub = (uint64_t)(s & MASK[sz]) + (uint32_t)m->x;
    uint32_t r = (uint32_t)((d & MASK[sz]) - sub) & MASK[sz];
    int sm = msb(s, sz), dm = msb(d, sz), rm = msb(r, sz);
    m->c = m->x = (uint64_t)(d & MASK[sz]) < sub;
    m->v = (sm != dm) && (rm != dm); m->n = rm;
    if (r) m->z = 0;
    return r;
}
/* ABCD/SBCD: X and C from the decimal carry, Z only cleared. N and V are
   undefined in the Motorola manual; modelled as Musashi does. */
static uint32_t f_bcd(M68 *m, uint32_t s, uint32_t d, int sub) {
    uint32_t r, v;
    s &= 0xff; d &= 0xff;
    if (!sub) {
        r = (s & 15) + (d & 15) + m->x; v = ~r;
        if (r > 9) r += 6;
        r += (s & 0xf0) + (d & 0xf0);
        m->c = m->x = r > 0x99;
        if (m->c) r -= 0xa0;
        v &= r;
    } else {
        r = (d & 15) - (s & 15) - m->x; v = ~r;
        if (r > 9) r -= 6;
        r += (d & 0xf0) - (s & 0xf0);
        m->c = m->x = r > 0x99;
        if (m->c) r += 0xa0;
        v &= ~r;
    }
    m->v = (v >> 7) & 1; m->n = (r >> 7) & 1;
    r &= 0xff;
    if (r) m->z = 0;
    return r;
}
static uint32_t f_negx(M68 *m, uint32_t d, int sz) {
    uint32_t s = m->x;                       /* 0 - d - X */
    uint32_t r = f_sub(m, d, 0, sz);
    int z0 = m->z;
    r = f_sub(m, s, r, sz);
    m->z = z0 && m->z;                       /* Z se jen nuluje, nikdy nenastavuje */
    return r;
}
static void do_divu(M68 *m, int reg, uint32_t src) {
    src &= 0xffff;
    if (src == 0) { fprintf(stderr, "deleni nulou\n"); exit(5); }
    uint32_t q = m->d[reg] / src, r = m->d[reg] % src;
    if (q > 0xffff) { m->v = 1; m->c = 0; return; }   /* pretecni: registr zustava */
    m->d[reg] = (r << 16) | (q & 0xffff);
    m->n = (q >> 15) & 1; m->z = (q == 0); m->v = 0; m->c = 0;
}
/* DIVS: quotient rounded toward zero, remainder has the sign of the dividend */
static void do_divs(M68 *m, int reg, uint32_t src) {
    int32_t sv = (int16_t)(src & 0xffff), dv = (int32_t)m->d[reg];
    if (sv == 0) { fprintf(stderr, "deleni nulou\n"); exit(5); }
    if (dv == INT32_MIN && sv == -1) { m->v = 1; m->c = 0; return; }
    int32_t q = dv / sv, r = dv % sv;
    if (q > 32767 || q < -32768) { m->v = 1; m->c = 0; return; }   /* pretecni: registr zustava */
    m->d[reg] = ((uint32_t)(r & 0xffff) << 16) | ((uint32_t)q & 0xffff);
    m->n = q < 0; m->z = (q == 0); m->v = 0; m->c = 0;
}
static uint32_t f_neg(M68 *m, uint32_t d, int sz) {
    uint32_t r = f_sub(m, d, 0, sz); return r;
}
static uint32_t f_shift(M68 *m, const char *k, uint32_t v, int cnt, int sz) {
    int b = BITS[sz]; uint32_t r = v & MASK[sz]; int last = 0;
    cnt &= 63;
    if (k[0] == 'l' || k[0] == 'a') {              /* lsl/lsr/asl/asr */
        int left = (k[2] == 'l');
        for (int i = 0; i < cnt; i++) {
            if (left) { last = msb(r, sz); r = (r << 1) & MASK[sz]; }
            else {
                last = r & 1;
                if (k[0] == 'a') r = (uint32_t)(((int32_t)(r << (32 - b)) >> (32 - b)) >> 1) & MASK[sz];
                else r = (r >> 1) & MASK[sz];
            }
        }
    } else if (k[2] == 'x') {                       /* roxl/roxr: through X; the bit shifted out goes to X and C */
        int left = (k[3] == 'l');
        for (int i = 0; i < cnt; i++) {
            if (left) { last = msb(r, sz); r = ((r << 1) | (uint32_t)m->x) & MASK[sz]; }
            else { last = r & 1; r = ((r >> 1) | ((uint32_t)m->x << (b - 1))) & MASK[sz]; }
            m->x = last;
        }
        m->n = msb(r, sz); m->z = (r == 0); m->v = 0;
        m->c = m->x;                                /* count 0: C = X */
        return r;
    } else {                                        /* rol/ror */
        int left = (k[strlen(k) - 1] == 'l');
        for (int i = 0; i < cnt; i++) {
            if (left) { last = msb(r, sz); r = ((r << 1) | last) & MASK[sz]; }
            else { last = r & 1; r = ((r >> 1) | ((uint32_t)last << (b - 1))) & MASK[sz]; }
        }
    }
    m->n = msb(r, sz); m->z = (r == 0); m->v = 0;
    m->c = cnt ? last : 0;
    if (cnt && (k[0] == 'l' || k[0] == 'a')) m->x = last;
    if (k[0] == 'a' && k[2] == 'l') {               /* asl: V = the sign bit changed at any step */
        uint32_t t = v & MASK[sz];
        for (int i = 0; i < cnt && i < b; i++) { if (msb(t, sz) != msb((t << 1) & MASK[sz], sz)) m->v = 1; t = (t << 1) & MASK[sz]; }
    }
    return r;
}
static int cond(M68 *m, int c) {
    switch (c) {
    case 0: return 1;                 case 1: return 0;
    case 2: return !m->c && !m->z;    case 3: return m->c || m->z;
    case 4: return !m->c;             case 5: return m->c;
    case 6: return !m->z;             case 7: return m->z;
    case 8: return !m->v;             case 9: return m->v;
    case 10: return !m->n;            case 11: return m->n;
    case 12: return m->n == m->v;     case 13: return m->n != m->v;
    case 14: return !m->z && (m->n == m->v);
    default: return m->z || (m->n != m->v);
    }
}
static void push32(M68 *m, uint32_t v) { m->a[7] -= 4; wr32(m->a[7], v); }
static void unknown_call(uint32_t a) { fprintf(stderr, "unknown routine %06x\n", a); exit(4); }
static uint32_t INLINE_RET = 0;     /* where a routine with data after its call returned to */

/* Overlays: code the program loads at run time into a fixed area. Each translated module registers
   under the FNV-1a 64 of its first bytes (Flow.module); overlay_call hashes the area as it is now. */
typedef void (*OvlFn)(M68 *m, uint32_t a);
static struct { uint64_t fp; OvlFn fn; const char *name; } OVL[64];
static int OVL_N = 0;
void overlay_register(uint64_t fp, OvlFn fn, const char *name) {
    if (OVL_N < 64) { OVL[OVL_N].fp = fp; OVL[OVL_N].fn = fn; OVL[OVL_N].name = name; OVL_N++; }
}
static uint32_t rd8(uint32_t a);
static uint64_t overlay_fp(uint32_t base, uint32_t n) {
    uint64_t h = 0xcbf29ce484222325ull;
    for (uint32_t i = 0; i < n; i++) { h ^= rd8(base + i); h *= 0x100000001b3ull; }
    return h;
}
'''
RUNTIME = RUNTIME.replace('%%TIMING%%', TIMING_RT + WAIT_RT)
PROFILE_OFF = '#define PROF_WRITE(a) ((void)0)\n'


class Gen:
    # (registr, posun) -> jmeno stubu: sdileno s decoder.STUBS
    @property
    def STUBS(self):
        return decoder.STUBS

    def __init__(self, data, base, funcs, cfg=None, flow=NOFLOW, timing=False, profile=False, cover=False,
                 cover_in_tick=False, bus_table=False):
        self.data, self.base, self.flow, self.timing = data, base, flow, timing
        self.bus_table = bus_table and not flow.lib      # the table lives with the main runtime
        self.tab_insns = {}                              # pc -> Insn of every translated instruction
        self.profile = profile and not flow.lib          # the profile lives in the main runtime
        self.cover = cover and not flow.lib              # so does the coverage bitmap
        self.cover_in_tick = cover_in_tick and timing    # the mark rides in TICK: no extra lines in the body
        self.cov_pcs = {}                                # entry -> [instruction addresses translated]
        self.funcs = funcs                  # [(start, end, entry)] - linearni useky
        self.cfg = cfg or {}                # entry -> {adresa: Insn} z grafu toku
        self.entries = {e: (s, en) for s, en, e in funcs}
        for e in self.cfg:
            self.entries.setdefault(e, None)
        self.out = []
        self.stats = {}
        self.cur = None                     # entry of the routine being generated

    def emit(self, s=''):
        self.out.append(s)

    def gen(self):
        if not self.flow.lib:
            prof = ''
            if self.profile:
                entries = sorted(set(self.all_entries()))
                prof = PROFILE_RT % {'n': max(1, len(entries)), 'addrs': ', '.join('0x%xu' % e for e in entries) or '0'}
                self.prof_index = {e: k for k, e in enumerate(entries)}
            cov = COVER_RT % {'lo': self.base, 'n': max(1, len(self.data) // 2),
                              'in_tick': '#define COV_TICK(pc) cov_mark(pc)' if self.cover_in_tick else ''} if self.cover else ''
            self.emit(RUNTIME.replace('%%PROFILE%%', cov + (prof or PROFILE_OFF)))
        else:                               # guarded: a main translation included before wins
            self.emit((TIMING_RT if self.timing else '') + WAIT_RT)
        for name in sorted(set(self.flow.externs.values())):
            self.emit('void %s(M68 *m);' % name)
        for entry in self.all_entries():
            self.emit('void %s(M68 *m);' % self.flow.fname(entry))
            if self.profile:
                self.emit('static void %s_body(M68 *m);' % self.flow.fname(entry))
        self.emit('void overlay_call(M68 *m, uint32_t a);')
        self.emit('void call_addr(M68 *m, uint32_t a);')
        if self.flow.module:
            self.emit('void overlay_register(uint64_t fp, void (*fn)(M68 *, uint32_t), const char *name);')
        self.emit()
        for s, e, entry in self.funcs:
            self.gen_func(s, e, entry)
        for entry in sorted(self.cfg):
            self.gen_cfg_func(entry)
        if self.bus_table:
            self.gen_bus_table()
        if not self.flow.lib:
            self.gen_dispatch()
        if self.flow.module:
            self.gen_module()
        return '\n'.join(self.out)

    def gen_bus_table(self):
        """BUS_TAB[(pc - BUS_LO) / 2] = {words, extra accesses, flags} (timing.bus_table_entry) for
        every translated instruction; a host's arek_bus_glue.h reads it in tick_hook."""
        from .timing import bus_table_entry
        n = max(1, len(self.data) // 2)
        rows = ['0,0,0'] * n
        for pc, i in self.tab_insns.items():
            k = (pc - self.base) // 2
            if 0 <= k < n:
                try:
                    rows[k] = '%d,%d,%d' % bus_table_entry(i)
                except Unsupported:
                    rows[k] = '%d,0,0' % ((i.end - i.addr) // 2)
        self.emit('/* bus table (recomp --bus-table): words, extra accesses, flags per instruction word of the image */')
        self.emit('#define BUS_LO 0x%xu' % self.base)
        self.emit('#define BUS_N %du' % n)
        self.emit('static const uint8_t BUS_TAB[BUS_N][3] = {')
        for k in range(0, n, 16):
            self.emit('  ' + ','.join('{%s}' % r for r in rows[k:k + 16]) + ',')
        self.emit('};')
        self.emit()

    def gen_dispatch(self):
        """overlay_call (the areas of Flow.overlays) and call_addr (every entry of this
        translation, the overlay areas, else unknown_call) for run-time targets."""
        self.emit('void overlay_call(M68 *m, uint32_t a) {')
        self.emit('    uint32_t base = 0, key = 0;')
        for b, n, k in self.flow.overlays:
            self.emit('    if (a - 0x%xu < 0x%xu) { base = 0x%xu; key = %du; }' % (b, n, b, k))
        self.emit('    if (!key) unknown_call(a);')
        self.emit('    uint64_t fp = overlay_fp(base, key);')
        self.emit('    for (int i = 0; i < OVL_N; i++) if (OVL[i].fp == fp) { OVL[i].fn(m, a); return; }')
        self.emit('    fprintf(stderr, "overlay_call: unknown module %016llx at %06x, entry %06x\\n", '
                  '(unsigned long long)fp, base, a);')
        self.emit('    exit(5);')
        self.emit('}')
        self.emit('void call_addr(M68 *m, uint32_t a) {')
        self.emit('    switch (a) {')
        for e in sorted(set(self.all_entries())):
            self.emit('    case 0x%xu: %s(m); return;' % (e, self.flow.fname(e)))
        self.emit('    }')
        for b, n, k in self.flow.overlays:
            self.emit('    if (a - 0x%xu < 0x%xu) { overlay_call(m, a); return; }' % (b, n))
        self.emit('    unknown_call(a);')
        self.emit('}')
        self.emit()

    def gen_module(self):
        """An overlay module: a dispatcher over its entries, registered at start-up under the
        FNV-1a 64 of its first ``key`` bytes at ``base`` (as overlay_call will hash the area)."""
        from ..headless.trace import fnv1a64
        base, key = self.flow.module
        off = base - self.base
        if off < 0 or off + key > len(self.data):
            raise Unsupported('overlay module: $%x+%d is outside the image' % (base, key))
        fp = fnv1a64(self.data[off:off + key])
        name = self.flow.prefix[0] or 'module_%x' % base
        self.emit('static void ovl_%s(M68 *m, uint32_t a) {' % name)
        self.emit('    switch (a) {')
        for e in sorted(set(x for x in self.all_entries() if self.flow.in_module(x))):
            self.emit('    case 0x%xu: %s(m); return;' % (e, self.flow.fname(e)))
        self.emit('    }')
        self.emit('    unknown_call(a);')
        self.emit('}')
        self.emit('__attribute__((constructor)) static void ovl_%s_register(void) '
                  '{ overlay_register(0x%016xull, ovl_%s, "%s"); }' % (name, fp, name, name))
        self.emit()

    def all_entries(self):
        return [e for _, _, e in self.funcs] + sorted(self.cfg)

    def func_head(self, entry):
        """The function head; with the profile the body is a static function wrapped by the
        entry, which counts the call and keeps the current routine for clocks and writes."""
        name = self.flow.fname(entry)
        if not self.profile:
            return 'void %s' % name
        self.emit('void %s(M68 *m) { prof_enter(%d); %s_body(m); prof_leave(); }'
                  % (name, self.prof_index[entry], name))
        return 'static void %s_body' % name

    def gen_cfg_func(self, entry):
        """Telo z grafu toku: emituji se jen dosazitelne instrukce, propad na
        dalsi adresu se v poradi hlida a jinak se doplni `goto`."""
        ins = self.cfg[entry]
        self.cur = entry
        order = sorted(ins)
        idx = {a: k for k, a in enumerate(order)}
        self.emit('/* vstup $%06x, %d instrukci z grafu toku */' % (entry, len(ins)))
        self.emit('%s(M68 *m) {' % self.func_head(entry))
        if order and order[0] != entry:
            self.emit('    goto L%06x;' % entry)
        for k, a in enumerate(order):
            i = ins[a]
            self.stats[i.kind] = self.stats.get(i.kind, 0) + 1
            self.tab_insns[a] = i
            self.emit('L%06x: ; /* %s */' % (a, i.text))
            if self.cover:
                self.cov_pcs.setdefault(entry, []).append(a)
                if not self.cover_in_tick or self.tick(i) is None:
                    self.emit('    COV_MARK(0x%xu);' % a)
            if self.timing and self.tick(i):
                self.emit('    ' + self.tick(i))
            for line in self.body(i, None, None, ins):
                self.emit('    ' + line)
            nxt = [] if self.inline_target(i) is not None else successors(i)
            if i.end in nxt and (k + 1 >= len(order) or order[k + 1] != i.end):
                self.emit('    goto L%06x;' % i.end)
        self.emit('    return;')
        self.emit('}')
        self.emit()

    def gen_func(self, start, end, entry):
        self.emit('/* $%06x - $%06x, vstup $%06x */' % (start, end, entry))
        self.emit('%s(M68 *m) {' % self.func_head(entry))
        self.cur = entry
        if entry != start:
            self.emit('    goto L%06x;' % entry)
        addr = start
        while addr < end:
            ins = decode(self.data, self.base, addr)
            self.stats[ins.kind] = self.stats.get(ins.kind, 0) + 1
            self.tab_insns[addr] = ins
            self.emit('L%06x: ; /* %s */' % (addr, ins.text))
            if self.cover:
                self.cov_pcs.setdefault(entry, []).append(addr)
                if not self.cover_in_tick or self.tick(ins) is None:
                    self.emit('    COV_MARK(0x%xu);' % addr)
            if self.timing and self.tick(ins):
                self.emit('    ' + self.tick(ins))
            for line in self.body(ins, start, end):
                self.emit('    ' + line)
            addr = ins.end
        self.emit('    return;')
        self.emit('}')
        self.emit()

    def br(self, target, start, end, ins=None):
        fl = self.flow
        if target in fl.stops:
            return 'unknown_call(0x%xu); return;' % target
        if target in fl.rets:
            return 'return;'
        if target in fl.exits:
            return 'exit_point(m, 0x%xu); return;' % target
        if target in fl.externs:
            return '%s(m); return;' % fl.externs[target]       # jmp into an external routine = tail call
        if ins is not None:
            if target in ins:
                return 'goto L%06x;' % target
        elif start <= target < end:
            return 'goto L%06x;' % target
        if fl.overlay_of(target):
            return 'overlay_call(m, 0x%xu); return;' % target
        if target in self.entries:
            return '%s(m); return;' % fl.fname(target)
        if fl.lib and not fl.in_module(target):
            return '%s(m); return;' % fl.fname(target)          # into the main translation
        raise Unsupported('skok mimo funkci na $%x' % target)

    def body(self, i, start, end, ins=None):
        k = i.kind
        L = []

        def pre(*eas):
            for e in eas:
                L.extend(e.pre)

        if k == 'rts':
            L.append('m->a[7] += 4;')          # navratova adresa ulozena pri bsr/jsr
            L.append('return;')
        elif k == 'nop':
            L.append(';')
        elif k == 'move':
            pre(i.src, i.dst)
            t = 'v%06x' % i.addr
            L.append('uint32_t %s = %s;' % (t, i.src.read(i.sz)))
            if not i.movea:
                L.append('%s = f_logic(m, %s, %d);' % (t, t, i.sz))
            L.append(i.dst.write(i.sz, t))
        elif k == 'moveq':
            L.append('m->d[%d] = 0x%xu;' % (i.reg, i.imm))
            L.append('f_logic(m, 0x%xu, 2);' % i.imm)
        elif k == 'lea':
            L.append('m->a[%d] = %s;' % (i.an, i.ea.addr))
        elif k == 'tst':
            pre(i.ea)
            L.append('f_logic(m, %s, %d);' % (i.ea.read(i.sz), i.sz))
        elif k == 'clr':
            pre(i.ea)
            L.append(i.ea.write(i.sz, '0'))
            L.append('m->n = 0; m->z = 1; m->v = 0; m->c = 0;')
        elif k in ('neg', 'not', 'negx'):
            pre(i.ea)
            if k == 'neg':
                L.append(i.ea.write(i.sz, 'f_neg(m, %s, %d)' % (i.ea.read(i.sz), i.sz)))
            elif k == 'not':
                L.append(i.ea.write(i.sz, 'f_logic(m, ~%s, %d)' % (i.ea.read(i.sz), i.sz)))
            else:
                L.append(i.ea.write(i.sz, 'f_negx(m, %s, %d)' % (i.ea.read(i.sz), i.sz)))
        elif k == 'scc':
            pre(i.ea)
            L.append(i.ea.write(SZ_B, 'cond(m, %d) ? 0xff : 0x00' % i.cond))
        elif k == 'addq':
            pre(i.ea)
            if i.ea.kind == 'a':                     # adresovy registr: bez priznaku, 32 bitu
                L.append('m->a[%d] %s= %d;' % (i.ea.reg, '-' if i.sub else '+', i.imm))
            else:
                f = 'f_sub' if i.sub else 'f_add'
                L.append(i.ea.write(i.sz, '%s(m, %du, %s, %d)' % (f, i.imm, i.ea.read(i.sz), i.sz)))
        elif k == 'alui':
            pre(i.ea)
            nm = i.name
            if nm == 'cmpi':
                L.append('f_cmp(m, 0x%xu, %s, %d);' % (i.imm, i.ea.read(i.sz), i.sz))
            elif nm in ('addi', 'subi'):
                f = 'f_add' if nm == 'addi' else 'f_sub'
                L.append(i.ea.write(i.sz, '%s(m, 0x%xu, %s, %d)' % (f, i.imm, i.ea.read(i.sz), i.sz)))
            else:
                opc = {'ori': '|', 'andi': '&', 'eori': '^'}[nm]
                L.append(i.ea.write(i.sz, 'f_logic(m, %s %s 0x%xu, %d)'
                                    % (i.ea.read(i.sz), opc, i.imm, i.sz)))
        elif k == 'alu':
            pre(i.ea)
            nm, sz = i.name, i.sz
            dn = 'm->d[%d]' % i.reg
            dnr = {SZ_B: '(uint8_t)' + dn, SZ_W: '(uint16_t)' + dn, SZ_L: dn}[sz]
            if nm == 'cmp':
                L.append('f_cmp(m, %s, %s, %d);' % (i.ea.read(sz), dnr, sz))
            elif nm in ('add', 'sub'):
                f = 'f_add' if nm == 'add' else 'f_sub'
                if i.to_ea:
                    L.append(i.ea.write(sz, '%s(m, %s, %s, %d)' % (f, dnr, i.ea.read(sz), sz)))
                else:
                    L.append('setd(m, %d, %d, %s(m, %s, %s, %d));'
                             % (i.reg, sz, f, i.ea.read(sz), dnr, sz))
            else:
                opc = {'or': '|', 'and': '&'}[nm]
                if i.to_ea:
                    L.append(i.ea.write(sz, 'f_logic(m, %s %s %s, %d)' % (i.ea.read(sz), opc, dnr, sz)))
                else:
                    L.append('setd(m, %d, %d, f_logic(m, %s %s %s, %d));'
                             % (i.reg, sz, i.ea.read(sz), opc, dnr, sz))
        elif k in ('adda', 'suba', 'cmpa'):
            pre(i.ea)
            src = i.ea.read(i.sz)
            if i.sz == SZ_W:
                src = '(uint32_t)(int32_t)(int16_t)(%s)' % src
            if k == 'cmpa':
                L.append('f_cmp(m, %s, m->a[%d], 2);' % (src, i.an))
            else:
                L.append('m->a[%d] = m->a[%d] %s %s;'
                         % (i.an, i.an, '+' if k == 'adda' else '-', src))
        elif k == 'eor':
            pre(i.ea)
            L.append(i.ea.write(i.sz, 'f_logic(m, %s ^ m->d[%d], %d)' % (i.ea.read(i.sz), i.reg, i.sz)))
        elif k == 'pea':
            pre(i.ea)
            L.append('push32(m, %s);' % i.ea.addr)
        elif k == 'link':
            if i.an == 7:                              # pushes the already decremented a7
                L.append('m->a[7] -= 4; wr32(m->a[7], m->a[7]); m->a[7] = (uint32_t)(m->a[7] + (%d));' % i.disp)
            else:
                L.append('push32(m, m->a[%d]); m->a[%d] = m->a[7]; m->a[7] = (uint32_t)(m->a[7] + (%d));'
                         % (i.an, i.an, i.disp))
        elif k == 'unlk':
            if i.an == 7:                              # a7 <- (a7); the +4 is overwritten
                L.append('m->a[7] = rd32(m->a[7]);')
            else:
                L.append('m->a[7] = m->a[%d]; m->a[%d] = rd32(m->a[7]); m->a[7] += 4;' % (i.an, i.an))
        elif k == 'exg':
            L.append('{ uint32_t t = m->%s[%d]; m->%s[%d] = m->%s[%d]; m->%s[%d] = t; }'
                     % (i.kx, i.rx, i.kx, i.rx, i.ky, i.ry, i.ky, i.ry))
        elif k == 'cmpm':
            pre(i.src, i.dst)
            L.append('f_cmp(m, %s, %s, %d);' % (i.src.read(i.sz), i.dst.read(i.sz), i.sz))
        elif k == 'bcd':
            sub = 1 if i.sub else 0
            if i.mem:
                L.append('m->a[%d] -= %d; m->a[%d] -= %d;' % (i.ry, 2 if i.ry == 7 else 1, i.rx, 2 if i.rx == 7 else 1))
                L.append('wr8(m->a[%d], f_bcd(m, rd8(m->a[%d]), rd8(m->a[%d]), %d));' % (i.rx, i.ry, i.rx, sub))
            else:
                L.append('setd(m, %d, 0, f_bcd(m, m->d[%d], m->d[%d], %d));' % (i.rx, i.ry, i.rx, sub))
        elif k == 'shift':
            if getattr(i, 'mem', False):               # <ea> shifted by one, word
                pre(i.ea)
                L.append(i.ea.write(i.sz, 'f_shift(m, "%s", %s, 1, %d)' % (i.name, i.ea.read(i.sz), i.sz)))
            else:
                L.append('setd(m, %d, %d, f_shift(m, "%s", m->d[%d], %s, %d));'
                         % (i.reg, i.sz, i.name, i.reg, i.cnt, i.sz))
        elif k == 'swap':
            L.append('m->d[%d] = (m->d[%d] >> 16) | (m->d[%d] << 16);' % ((i.reg,) * 3))
            L.append('f_logic(m, m->d[%d], 2);' % i.reg)
        elif k == 'ext':
            if i.sz == SZ_W:
                L.append('setd(m, %d, 1, (uint32_t)(int32_t)(int8_t)m->d[%d]);' % (i.reg, i.reg))
                L.append('f_logic(m, (uint16_t)m->d[%d], 1);' % i.reg)
            else:
                L.append('m->d[%d] = (uint32_t)(int32_t)(int16_t)m->d[%d];' % (i.reg, i.reg))
                L.append('f_logic(m, m->d[%d], 2);' % i.reg)
        elif k == 'bit':
            pre(i.ea)
            sz = SZ_L if i.ea.kind == 'd' else SZ_B
            bits = 32 if sz == SZ_L else 8
            L.append('uint32_t b%06x = (%s) %% %d;' % (i.addr, i.src, bits))
            L.append('uint32_t o%06x = %s;' % (i.addr, i.ea.read(sz)))
            L.append('m->z = ((o%06x >> b%06x) & 1) == 0;' % (i.addr, i.addr))
            if i.bitop != 0:
                op = {1: '^', 2: '& ~', 3: '|'}[i.bitop]
                expr = ('o%06x %s (1u << b%06x)' % (i.addr, op, i.addr)) if i.bitop != 2 else \
                       ('o%06x & ~(1u << b%06x)' % (i.addr, i.addr))
                L.append(i.ea.write(sz, expr))
        elif k == 'movem':
            step = 2 if i.sz == SZ_W else 4
            if i.mode == 4:          # -(An): poradi A7..A0, D7..D0, adresa se snizuje pred zapisem
                names = [('a', r) for r in range(7, -1, -1)] + [('d', r) for r in range(7, -1, -1)]
            else:
                names = [('d', r) for r in range(8)] + [('a', r) for r in range(8)]
            in_list = any((i.mask >> b) & 1 and names[b] == ('a', i.reg) for b in range(16))
            if i.mode in (3, 4):     # (An)+ / -(An): vlastni ukazatel, ne pre z decode_ea
                L.append('uint32_t ma%06x = m->a[%d];' % (i.addr, i.reg))
                for bit, (kind, rg) in enumerate(names):
                    if not (i.mask >> bit) & 1:
                        continue
                    tgt = 'm->%s[%d]' % (kind, rg)
                    if i.mode == 4:
                        L.append('ma%06x -= %d;' % (i.addr, step))
                        L.append(('wr16(ma%06x, %s);' if i.sz == SZ_W else 'wr32(ma%06x, %s);')
                                 % (i.addr, tgt))
                    else:
                        if i.sz == SZ_W:
                            L.append('%s = (uint32_t)(int32_t)(int16_t)rd16(ma%06x);' % (tgt, i.addr))
                        else:
                            L.append('%s = rd32(ma%06x);' % (tgt, i.addr))
                        L.append('ma%06x += %d;' % (i.addr, step))
                if not in_list:      # kdyz je bazovy registr v seznamu, plati nactena hodnota
                    L.append('m->a[%d] = ma%06x;' % (i.reg, i.addr))
            else:
                pre(i.ea)
                L.append('uint32_t ma%06x = %s;' % (i.addr, i.ea.addr))
                off = 0
                for bit, (kind, rg) in enumerate(names):
                    if not (i.mask >> bit) & 1:
                        continue
                    tgt = 'm->%s[%d]' % (kind, rg)
                    if i.to_mem:
                        L.append((('wr16(ma%06x + %d, %s);' if i.sz == SZ_W
                                   else 'wr32(ma%06x + %d, %s);')) % (i.addr, off, tgt))
                    elif i.sz == SZ_W:   # cteni .w se vzdy rozsiruje znamenkem do 32 bitu
                        L.append('%s = (uint32_t)(int32_t)(int16_t)rd16(ma%06x + %d);'
                                 % (tgt, i.addr, off))
                    else:
                        L.append('%s = rd32(ma%06x + %d);' % (tgt, i.addr, off))
                    off += step
        elif k == 'rte':
            L.append('{ uint32_t sp = m->a[7]; uint32_t sr = rd16(sp);')
            L.append('  m->srhi = sr & 0xff00; m->x = (sr >> 4) & 1; m->n = (sr >> 3) & 1;')
            L.append('  m->z = (sr >> 2) & 1; m->v = (sr >> 1) & 1; m->c = sr & 1;')
            L.append('  m->a[7] = sp + 6; }')
            L.append('return;')
        elif k == 'sr':
            pre(i.ea)
            if i.which == 'from_sr':
                L.append(i.ea.write(SZ_W, 'sr_get(m)'))
            elif i.which == 'to_sr':
                L.append('sr_set(m, %s, 1);' % i.ea.read(SZ_W))
            else:
                L.append('sr_set(m, %s, 0);' % i.ea.read(SZ_W))
        elif k == 'addx':
            f = 'f_subx' if i.sub else 'f_addx'
            if i.mem:
                def n(reg):                            # -(a7).b keeps the stack even
                    return 2 if i.sz == SZ_W else (4 if i.sz == SZ_L else (2 if reg == 7 else 1))
                L.append('m->a[%d] -= %d; m->a[%d] -= %d;' % (i.ry, n(i.ry), i.rx, n(i.rx)))
                rd = {SZ_B: 'rd8', SZ_W: 'rd16', SZ_L: 'rd32'}[i.sz]
                wr = {SZ_B: 'wr8', SZ_W: 'wr16', SZ_L: 'wr32'}[i.sz]
                L.append('%s(m->a[%d], %s(m, %s(m->a[%d]), %s(m->a[%d]), %d));'
                         % (wr, i.rx, f, rd, i.ry, rd, i.rx, i.sz))
            else:
                dn = {SZ_B: '(uint8_t)m->d[%d]', SZ_W: '(uint16_t)m->d[%d]',
                      SZ_L: 'm->d[%d]'}[i.sz]
                L.append('setd(m, %d, %d, %s(m, %s, %s, %d));'
                         % (i.rx, i.sz, f, dn % i.ry, dn % i.rx, i.sz))
        elif k == 'bra':
            L.append(self.br(i.target, start, end, ins))
        elif k == 'bcc':
            w = self.wait_loop(i)
            hook = 'WAIT_LOOP(m, 0x%xu, %s); ' % (i.target, w) if w else ''
            L.append('if (cond(m, %d)) { %s%s }' % (i.cond, hook, self.br(i.target, start, end, ins)))
        elif k == 'dbcc':
            L.append('if (!cond(m, %d)) { setd(m, %d, 1, (uint16_t)m->d[%d] - 1);'
                     % (i.cond, i.reg, i.reg))
            L.append('    if ((uint16_t)m->d[%d] != 0xffff) { %s } }'
                     % (i.reg, self.br(i.target, start, end, ins)))
        elif k == 'bsr':
            if i.target in self.flow.inline:
                return L + self.inline_call(i, i.target, start, end, ins)
            L.append(self.callseq(i.target, i.end))
        elif k == 'jsr':
            nm = self.stub_name(i.ea)
            if nm:
                L.append('%s(m);' % nm)
                return L
            if i.ea.kind != 'mem':
                raise Unsupported('jsr %s' % i.ea.kind)
            if i.addr in self.flow.dynamic:
                L.append('{ uint32_t t = %s, sp0 = m->a[7]; push32(m, 0x%xu); call_addr(m, t); '
                         'if (m->a[7] > sp0) return; }' % (i.ea.addr, i.end))
                return L
            if i.addr in self.flow.jtabs:
                return L + self.jump_table(i, lambda t: self.callseq(t, i.end) + ' break;',
                                           'break;')
            if i.addr in self.flow.indirect:
                L.append('{ uint32_t t = %s; switch (t) {' % i.ea.addr)
                for t in self.flow.indirect[i.addr]:
                    L.append('  case 0x%xu: %s break;' % (t, self.callseq(t, i.end)))
                L.append('  default: unknown_call(t); } }')
                return L
            if getattr(i.ea, 'mode', None) in FLOW_MODES:
                if i.ea.absval in self.flow.inline:
                    return L + self.inline_call(i, i.ea.absval, start, end, ins)
                L.append(self.callseq(i.ea.absval, i.end))
            else:
                L.append('push32(m, 0x%xu);' % i.end)
                L.append('unknown_call(%s);' % i.ea.addr)
        elif k == 'jmp':
            nm = self.stub_name(i.ea)
            if nm:
                L.append('%s(m); return;' % nm)
                return L
            mode = getattr(i.ea, 'mode', None)
            if i.addr in self.flow.dynamic and mode not in FLOW_MODES:
                L.append('call_addr(m, %s); return;' % i.ea.addr)
                return L
            if i.addr in self.flow.jtabs:
                return L + self.jump_table(i, lambda t: '%s(m); return;' % self.flow.fname(t),
                                           'm->a[7] += 4; return;')
            if i.addr in self.flow.indirect:
                if mode in FLOW_MODES:                     # the program rewrites the operand
                    t = ('rd32(0x%xu)' % (i.addr + 2)) if i.end - i.addr == 6 else \
                        ('(uint32_t)(int16_t)rd16(0x%xu)' % (i.addr + 2))
                else:
                    t = i.ea.addr
                L.append('{ uint32_t t = %s; switch (t) {' % t)
                for t in self.flow.indirect[i.addr]:
                    L.append('  case 0x%xu: %s' % (t, self.br(t, start, end, ins)))
                L.append('  default: unknown_call(t); } }')
                return L
            if mode in FLOW_MODES:
                L.append(self.br(i.ea.absval, start, end, ins))
            elif self.cur in self.flow.inline and mode in (2, 5):
                L.append('INLINE_RET = %s; return;' % i.ea.addr)     # back behind the caller's data
            else:
                raise Unsupported('neprimy jmp @%x' % i.addr)
        elif k in ('mulu', 'divu', 'muls', 'divs') and self.timing:
            pre(i.ea)
            ea_t = ea_time(i.ea)
            L.append('{ uint32_t s_ = (uint16_t)(%s);' % i.ea.read(SZ_W))
            if k == 'mulu':
                L.append('  TICK(0x%xu, mulu_t(s_) + %d); m->d[%d] = (uint32_t)((uint16_t)m->d[%d] * s_); }'
                         % (i.addr, ea_t, i.reg, i.reg))
                L.append('f_logic(m, m->d[%d], 2);' % i.reg)
            elif k == 'muls':
                L.append('  TICK(0x%xu, muls_t(s_) + %d); m->d[%d] = (uint32_t)((int32_t)(int16_t)m->d[%d] * (int32_t)(int16_t)s_); }'
                         % (i.addr, ea_t, i.reg, i.reg))
                L.append('f_logic(m, m->d[%d], 2);' % i.reg)
            else:
                L.append('  if (s_) TICK(0x%xu, %s_t(m->d[%d], s_) + %d); do_%s(m, %d, s_); }'
                         % (i.addr, k, i.reg, ea_t, k, i.reg))
        elif k in ('mulu', 'divu', 'muls', 'divs'):
            pre(i.ea)
            if k == 'mulu':
                L.append('m->d[%d] = (uint32_t)((uint16_t)m->d[%d] * (uint16_t)(%s));'
                         % (i.reg, i.reg, i.ea.read(SZ_W)))
                L.append('f_logic(m, m->d[%d], 2);' % i.reg)
            elif k == 'muls':
                L.append('m->d[%d] = (uint32_t)((int32_t)(int16_t)m->d[%d] * (int32_t)(int16_t)(%s));'
                         % (i.reg, i.reg, i.ea.read(SZ_W)))
                L.append('f_logic(m, m->d[%d], 2);' % i.reg)
            else:
                L.append('do_%s(m, %d, %s);' % (k, i.reg, i.ea.read(SZ_W)))
        else:
            raise Unsupported('generator neumi %s @%x' % (k, i.addr))
        return L

    def wait_loop(self, i):
        """``L: tst/btst/cmp/cmpa/cmpi <mem> ; bcc L``: the C address of the polled memory
        (a loop that only waits for it to change), else None."""
        if not (i.target < i.addr):
            return None
        try:
            p = decode(self.data, self.base, i.target)
        except Unsupported:
            return None
        if p.end != i.addr:
            return None
        test = (p.kind in ('tst', 'cmpa') or (p.kind == 'bit' and p.bitop == 0)
                or (p.kind == 'alu' and p.name == 'cmp') or (p.kind == 'alui' and p.name == 'cmpi'))
        e = getattr(p, 'ea', None)
        if not test or e is None or e.kind != 'mem' or e.pre:
            return None                     # a register, or (An)+ / -(An): not a pure poll
        return e.addr

    def stub_name(self, ea):
        """Neprime volani pres pevnou bazi registru (skokova tabulka zavadece):
        prelozi se na volani stubu, ktery se doplni zvenci."""
        if getattr(ea, 'mode', None) in (2, 5) and ea.areg is not None:
            return decoder.STUBS.get((ea.areg, ea.disp or 0))
        return None

    def tick(self, i):
        """TICK statement for instruction i (before its body runs); mul/div tick in the body."""
        k, pc = i.kind, i.addr
        if k in ('mulu', 'muls', 'divu', 'divs'):
            return None
        if k == 'bcc':
            return 'TICK(0x%xu, cond(m, %d) ? 10 : %d);' % (pc, i.cond, cycles(i, taken=False))
        if k == 'dbcc':
            return 'TICK(0x%xu, cond(m, %d) ? 12 : ((m->d[%d] & 0xffff) == 0 ? 14 : 10));' % (pc, i.cond, i.reg)
        if k == 'scc' and ea_class(i.ea) == 'dn':
            return 'TICK(0x%xu, cond(m, %d) ? 6 : 4);' % (pc, i.cond)
        if k == 'shift' and not getattr(i, 'mem', False) and not i.cnt.isdigit():
            return 'TICK(0x%xu, %d + 2 * (%s));' % (pc, cycles(i, count=0), i.cnt)
        if k == 'bit' and i.bitop and ea_class(i.ea) == 'dn':
            if i.src.startswith('m->d['):
                return 'TICK(0x%xu, %d + ((%s & 31) >= 16 ? 2 : 0));' % (pc, cycles(i, count=0), i.src)
            return 'TICK(0x%xu, %d);' % (pc, cycles(i, count=int(i.src.rstrip('u'), 16)))
        return 'TICK(0x%xu, %d);' % (pc, cycles(i))

    def jump_table(self, i, case, empty):
        """jsr/jmp (d8,An,Dn) or (d8,PC,Dn) into a JumpTable: a switch on the slot index."""
        if getattr(i.ea, 'mode', None) not in (6, 73):
            raise Unsupported('jump table at $%x: unexpected operand %s' % (i.addr, i.ea.text))
        jt = self.flow.jtabs[i.addr]
        reg = ('m->a[%d]' if i.ea.xa else 'm->d[%d]') % i.ea.xr
        ix = ('(int32_t)%s' if i.ea.xl else '(int32_t)(int16_t)%s') % reg
        if i.ea.mode == 73:
            base = '(%d)' % (i.ea.pcbase - jt.table)
        elif jt.base_reg:                                  # An = table + an offset the program chose
            base = '(int32_t)(m->a[%d] - 0x%xu)' % (i.ea.areg, jt.table)
        else:
            base = '(%d)' % (jt.origin - jt.table)
        L = ['{ int32_t off = %s + (%d) + %s; if (off < 0 || off %% %d) unknown_call((uint32_t)off); '
             'switch (off / %d) {' % (ix, i.ea.disp, base, jt.stride, jt.stride)]
        for k, t in enumerate(jt.targets):
            L.append('  case %d: %s' % (k, empty if t is None else case(t)))
        L.append('  default: unknown_call((uint32_t)off); } }')
        return L

    def callseq(self, target, ret):
        """bsr/jsr: push the return address and call. A callee that removed more than its
        return address (``addq.l #4,a7 ; rts`` = return to the caller's caller) makes
        this routine return at once, as the 68000 would."""
        if target in self.flow.inline:
            raise Unsupported('routine $%x reads data after its call; only a direct call has a known '
                              'place to go on' % target)
        if target in self.flow.exits:
            return 'exit_point(m, 0x%xu);' % target
        if target in self.flow.externs:
            return ('{ uint32_t sp0 = m->a[7]; push32(m, 0x%xu); %s(m); if (m->a[7] > sp0) return; }'
                    % (ret, self.flow.externs[target]))
        return '{ uint32_t sp0 = m->a[7]; push32(m, 0x%xu); %s if (m->a[7] > sp0) return; }' % (ret, self.call(target))

    def inline_target(self, i):
        """The routine a direct call ``i`` goes to when that routine has data after its call."""
        if i.kind == 'bsr':
            t = i.target
        elif i.kind == 'jsr' and getattr(i.ea, 'mode', None) in FLOW_MODES:
            t = i.ea.absval
        else:
            return None
        return t if t in self.flow.inline else None

    def inline_call(self, i, target, start, end, ins):
        """A direct call to a routine that reads the data stored after the call (Flow.inline)
        and returns behind it with ``jmp (An)``: the callee leaves its return point in
        INLINE_RET, which must be the end of the data (an --extern replacement sets it too)."""
        nxt = self.flow.inline[target].end(self.data, self.base, i.end, self.base + len(self.data))
        if nxt is None:
            raise Unsupported('data after call $%x @%x runs past the end' % (target, i.addr))
        return ['{ uint32_t sp0 = m->a[7]; push32(m, 0x%xu); INLINE_RET = 0; %s if (m->a[7] > sp0) return;'
                % (i.end, ('%s(m);' % self.flow.externs[target]) if target in self.flow.externs
                   else self.call(target)),
                '  if (INLINE_RET != 0x%xu) unknown_call(INLINE_RET); }' % nxt,
                self.br(nxt, start, end, ins)]

    def call(self, target):
        if self.flow.overlay_of(target):
            return 'overlay_call(m, 0x%xu);' % target
        if target in self.entries:
            return '%s(m);' % self.flow.fname(target)
        if self.flow.lib and not self.flow.in_module(target):
            return '%s(m);' % self.flow.fname(target)        # a routine of the main translation
        return 'unknown_call(0x%xu);' % target

MAIN_C = r'''
/* --- driver for verification against the emulator --------------------------------- */
#include <setjmp.h>
static jmp_buf EXIT_JB;
static uint32_t EXIT_AT = 0;
void exit_point(M68 *m, uint32_t at) { (void)m; EXIT_AT = at; longjmp(EXIT_JB, 1); }
int main(int argc, char **argv) {
    if (argc < 5) { fprintf(stderr, "recomp RAM.bin regs.txt out.bin wrlog.txt [SLOW.bin SLOWOUT.bin]\n"); return 1; }
    FILE *f = fopen(argv[1], "rb");
    if (!f || fread(MEM, 1, MEMSZ, f) != MEMSZ) { fprintf(stderr, "RAM?\n"); return 1; }
    fclose(f);
#if SLOWSZ
    if (argc > 5) {                                  /* slow RAM image (zeros when not given) */
        f = fopen(argv[5], "rb");
        if (!f || fread(SLOW, 1, SLOWSZ, f) != SLOWSZ) { fprintf(stderr, "SLOW RAM?\n"); return 1; }
        fclose(f);
    }
#endif
    M68 m; memset(&m, 0, sizeof m);
    f = fopen(argv[2], "r");
    for (int i = 0; i < 8; i++) if (fscanf(f, "%x", &m.d[i]) != 1) return 1;
    for (int i = 0; i < 8; i++) if (fscanf(f, "%x", &m.a[i]) != 1) return 1;
    if (fscanf(f, "%d %d %d %d %d", &m.x, &m.n, &m.z, &m.v, &m.c) != 5) return 1;
    char name[64];
    uint32_t ret = 0;
    if (fscanf(f, "%63s", name) != 1) return 1;
    if (fscanf(f, "%x", &ret) == 1) push32(&m, ret);   /* jako bsr od volajiciho */
    fclose(f);
    if (!setjmp(EXIT_JB)) ENTRY(name, &m);
    f = fopen(argv[3], "wb"); fwrite(MEM, 1, MEMSZ, f); fclose(f);
#if SLOWSZ
    if (argc > 6) { f = fopen(argv[6], "wb"); fwrite(SLOW, 1, SLOWSZ, f); fclose(f); }
#endif
    f = fopen(argv[4], "w");
    for (int i = 0; i < 8; i++) fprintf(f, "%08x\n", m.d[i]);
    for (int i = 0; i < 8; i++) fprintf(f, "%08x\n", m.a[i]);
    fprintf(f, "%d %d %d %d %d\n", m.x, m.n, m.z, m.v, m.c);
    fprintf(f, "blits %ld\n", BLITS);
    if (EXIT_AT) fprintf(f, "exit %x\n", EXIT_AT);
    fprintf(f, "cycles %llu\n", (unsigned long long)CYCLES);
#ifdef PROF_N
    if (getenv("AREK_PROFILE")) { FILE *pf = fopen(getenv("AREK_PROFILE"), "w"); if (pf) { prof_dump(pf, -1); fclose(pf); } }
#endif
#ifdef COV_N
    if (getenv("AREK_COVER")) { FILE *cf = fopen(getenv("AREK_COVER"), "w"); if (cf) { cov_dump(cf); fclose(cf); } }
#endif
    if (OOB_COUNT) fprintf(f, "oob %ld\n", OOB_COUNT);
#ifdef BUS_HOOK
    fprintf(f, "bus %.1f\n", bus_time_hook());
#endif
    for (int i = 0; i < HW_NOTES; i++) fprintf(f, "note %s\n", HW_NOTE[i]);
    for (int i = 0; i < 0x100; i++)
        if (HW_UNMODELLED[i]) fprintf(f, "hwreg %03x\n", i * 2);
    for (uint32_t a = 0; a < MEMSZ; a++) if (WRLOG[a]) fprintf(f, "w %x\n", a);
#if SLOWSZ
    for (uint32_t a = 0; a < SLOWSZ; a++) if (SLOWLOG[a]) fprintf(f, "w %x\n", SLOWBASE + a);
#endif
    fclose(f);
    return 0;
}
'''


def parse_func_spec(spec):
    """'START:END[:ENTRY]' (hex) -> (start, end, entry)."""
    p = spec.split(':')
    s, e = _hex(p[0]), _hex(p[1])
    return s, e, _hex(p[2]) if len(p) > 2 else s


def add_stub(spec):
    """'An:DISP:NAME' - indirect calls through a fixed base register become calls to NAME."""
    reg, disp, name = spec.split(':')
    decoder.STUBS[(int(reg.lstrip('aA')), int(disp))] = name


def _hex(x):
    return int(str(x).strip().lstrip('$'), 16)


def flow_from_specs(data, base, jtab=(), indirect=(), stop=(), exitat=(), extern=(), ret=(),
                    prefix=None, lib=False, inline=(), overlay=(), dynamic=(), module=None):
    """Build a decoder.Flow from the command-line spellings (all addresses hex):

    jtab     'SITE[,SITE..]:TABLE:COUNT:STRIDE:bra|ptr[:AN|an]' - jsr/jmp (d8,An,Dn) into a table;
             AN = the value of An at the jump when the table starts below it, 'an' = An is
             only known at run time (slot = (An - TABLE + Dn) / STRIDE)
    indirect 'SITE=T1,T2,...' - possible targets of jsr/jmp (An), or of a rewritten jmp abs
    stop, exitat, ret   addresses;   extern 'ADDR=c_name';   prefix 'NAME:LO:HI'
    inline   'ROUTINE[,ROUTINE..]:until=HHHH|words=N|longs=N|string' - the routine reads data
             stored after its call and returns behind it (decoder.Inline)
    overlay  'BASE:SIZE[:KEY]' - an area code is loaded into at run time (KEY bytes hashed, 256)
    dynamic  'SITE' - jsr/jmp (An) resolved at run time by address (call_addr)
    module   'BASE[:KEY]' - this translation is an overlay module (with lib and prefix)
    """
    jtabs = {}
    for spec in jtab:
        p = spec.split(':')
        sites, table, count, stride, kind = p[:5]
        table, stride = _hex(table), int(stride)
        origin = p[5] if len(p) > 5 else None
        jt = JumpTable(jtab_targets(data, base, table, int(count), stride, kind), stride, table,
                       None if origin in (None, 'an') else _hex(origin), base_reg=origin == 'an')
        for site in sites.split(','):
            jtabs[_hex(site)] = jt
    ind = {}
    for spec in indirect:
        site, targets = spec.split('=')
        ind[_hex(site)] = [_hex(t) for t in targets.split(',') if t]
    ext = {}
    for spec in extern:
        a, name = spec.split('=')
        ext[_hex(a)] = name
    pf = None
    if prefix:
        name, plo, phi = prefix.split(':')
        pf = (name, _hex(plo), _hex(phi))
    inl = {}
    for spec in inline:
        sites, _, kind = spec.partition(':')
        it = Inline.parse(kind)
        for site in sites.split(','):
            inl[_hex(site)] = it
    ovl = []
    for spec in overlay:
        p = spec.split(':')
        ovl.append((_hex(p[0]), _hex(p[1]), int(p[2]) if len(p) > 2 else 256))
    mod = None
    if module:
        p = module.split(':')
        mod = (_hex(p[0]), int(p[1]) if len(p) > 1 else 256)
    return Flow(stops=map(_hex, stop), rets=map(_hex, ret), exits=map(_hex, exitat), externs=ext,
                jtabs=jtabs, indirect=ind, prefix=pf, lib=lib, inline=inl, overlays=ovl,
                dynamic=map(_hex, dynamic), module=mod)


def _ranges(pcs):
    """Sorted addresses as [[first, last], ...] of consecutive instruction words."""
    out = []
    for a in sorted(set(pcs)):
        if out and a <= out[-1][1] + 2:
            out[-1][1] = max(out[-1][1], a)
        else:
            out.append([a, a])
    return out


def refusal_json(e):
    """An Unsupported as JSON-ready data: the message and every frontier, addresses as hex strings."""
    return {'message': str(e), 'frontiers': [{k: ('%x' % v if k in ('routine', 'site', 'target') else v)
                                              for k, v in f.items()} for f in e.frontiers]}


def generate(data, base, funcs=(), auto=(), lo=0, hi=None, with_main=False, flow=NOFLOW,
             stub_impl=None, timing=False, memsz=None, slow=None, profile=False, cover=None, oob='stop',
             cover_in_tick=False, bus_table=False):
    """Return (c_source, stats, entries). ``funcs`` are (start, end, entry) linear ranges,
    ``auto`` are entry addresses whose bodies are discovered by walking the
    flow graph (transitively over bsr/jsr). ``flow`` (a decoder.Flow) carries what the
    bytes do not say: jump tables, indirect targets, external routines, overlay modules.
    ``stub_impl``: None = the stubs (decoder.STUBS) are defined elsewhere, 'notes' = empty
    stubs that record a hardware note, or C source with their bodies.
    ``timing``: every instruction adds its 68000 clocks (arek.m68k.timing, branch outcome and
    MUL/DIV operands included) through TICK(pc, n) into CYCLES or the host's tick_hook.
    ``profile``: per routine the calls, clocks and written bytes/pages (prof_dump, prof_reset;
    the driver writes it to $AREK_PROFILE) - what to rewrite first; not for lib modules.
    ``cover``: a dict to fill - the runtime then keeps one bit per translated instruction
    (cov_dump, cov_reset; the driver writes it to $AREK_COVER) and the dict gets
    ``{'lo', 'routines': {entry: [[first, last], ...]}}`` for ``arek cover``; not for lib modules.
    ``cover_in_tick`` (with ``timing``): the mark is part of TICK instead of a line of its own before
    it, so the body text of each instruction stays as without coverage (a host that patches the
    generated text by exact match keeps working); mul/div with a zero divisor are then not marked.
    A host of its own must call ``cov_dump`` itself (atexit); only the verification driver does.
    ``bus_table``: BUS_TAB with words, extra bus accesses and flags per translated instruction
    (timing.bus_table_entry) for the bus model (bus/arek_bus_glue.h, -DTICK_HOOK -DBUS_HOOK); the
    runtime always has the hooks BUS_ACCESS (every CPU access to the chip bus), BUS_BLIT and
    BUS_BBUSY, empty unless BUS_HOOK is defined. Not for lib modules.
    ``oob``: what an access outside the modelled RAM does - ``'stop'`` (exit 3, the default) or
    ``'zero'`` (reads give 0, writes are dropped, one note per KB, the driver reports ``oob N``).
    A refusal raises Unsupported with the first frontier as its text and all of them in
    ``.frontiers`` (decoder.frontier), so one run lists every place that needs a Flow entry.
    ``memsz``: chip RAM bytes from 0 (default 512 KB); ``slow``: (base, size) of slow RAM, e.g.
    (0xc00000, 0x80000) - the driver then reads/writes it as optional files 5 and 6. Both can
    also be set when compiling (-DMEMSZ=..., -DSLOWBASE=..., -DSLOWSZ=...).
    Raises Unsupported / SystemExit-free."""
    hi = min(hi if hi is not None else base + len(data), base + len(data))
    lo = max(lo, base)                           # nothing outside the image can be walked
    cfg = {}
    if auto:
        tree = call_tree(data, base, list(auto), lo, hi, flow)
        first, found, seen = None, [], set()
        for e, (ins, calls, bad, ind) in tree.items():
            for site, why in bad + ind:
                if (site, why) not in seen:
                    seen.add((site, why))
                    found.append(decoder.frontier(e, site, why))
            if bad and first is None:
                first = 'routine $%x, %s @%x' % (e, bad[0][1], bad[0][0])
            elif ind and first is None:
                what = '' if ind[0][1].startswith('data after') else 'indirect jump: '
                first = 'routine $%x, %s%s @%x' % (e, what, ind[0][1], ind[0][0])
            cfg[e] = ins
        if found:
            raise Unsupported(first, found)
    if oob not in ('stop', 'zero'):
        raise ValueError("oob is 'stop' or 'zero'")
    g = Gen(data, base, list(funcs), cfg, flow, timing, profile, cover is not None, cover_in_tick, bus_table)
    src = g.gen()
    if cover is not None:
        cover['lo'] = base
        cover['routines'] = {'%x' % e: _ranges(pcs) for e, pcs in sorted(g.cov_pcs.items())}
    if stub_impl is not None and decoder.STUBS:
        names = sorted(set(decoder.STUBS.values()))
        impl = stub_impl if stub_impl != 'notes' else '\n'.join(
            'static void %s(M68 *m) { (void)m; hw_note("stub %s"); }' % (n, n) for n in names)
        cut = src.find('\nvoid f_')
        cut = len(src) if cut < 0 else cut
        src = (src[:cut] + '\n/* --- stubs --- */\n' + ''.join('static void %s(M68 *m);\n' % n for n in names)
               + impl + '\n' + src[cut:])
    if flow.lib:          # prototypes of main-translation routines this module calls
        defined = set(re.findall(r'\nvoid (f_\w+)\(M68 \*m\) \{', src))
        called = set(re.findall(r'\b(f_\w+)\(m\)', src))
        src = ('/* --- overlay module (Flow.lib): include after the main translation, shares its runtime --- */\n'
               + ''.join('void %s(M68 *m);\n' % f for f in sorted(called - defined)) + src)
    from .. import identity
    ident = identity()
    mem = ''
    if flow.lib and (memsz is not None or slow is not None):
        raise ValueError('memsz/slow belong to the main translation, not to a --lib module')
    if oob == 'zero' and not flow.lib:
        mem += '#define OOB_ZERO 1\n'
    if memsz is not None:
        mem += '#define MEMSZ 0x%xu\n' % memsz
    if slow is not None:
        mem += '#define SLOWBASE 0x%xu\n#define SLOWSZ 0x%xu\n' % tuple(slow)
    src = ('/* generated by amiga-re-kit %s, decoder sha256 %s, recomp sha256 %s */\n'
           % (ident['version'], ident['decoder_sha256'], ident['recomp_sha256'])) + mem + src
    if with_main:
        disp = '\n'.join('    if (!strcmp(n, "%s")) { %s(m); return; }' % (flow.fname(e), flow.fname(e))
                         for e in g.all_entries())
        src += ('\nstatic void ENTRY(const char *n, M68 *m) {\n%s\n'
                '    fprintf(stderr, "unknown entry %%s\\n", n); exit(2);\n}\n' % disp)
        src += MAIN_C
    return src, dict(g.stats), g.all_entries()
