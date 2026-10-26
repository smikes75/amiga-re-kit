/* arek_host.h - the host of a translation (path B of amiga-re-kit): time from the bus model per DMA slot, the beam,
 * interrupts, the CIAs with the E clock, Paula's audio DMA (arek_bus_paula.h) and output (arek_audio.h), the picture
 * line by line (arek_display.h). Extracted from the Alien Breed II project (docs/HOST.md); every constant was measured
 * against the original (vAmiga 899da5d) per instruction.
 *
 * One translation unit, in this order:
 *   #include "arek_host_pre.h"      -- the hook macros
 *   #include GAME_SRC               -- arek recomp ... --timing --bus-table (no --main)
 *   #include "arek_bus_glue.h"      -- arek bus copy
 *   #define HOST_L3 f_xxxxxx        -- the translated level-3 handler (the vector at $6C, measured); HOST_L1, HOST_L2,
 *                                      HOST_L4, HOST_L5, HOST_L6 likewise when the game uses them
 *   #include "arek_host.h"
 * Then: host_init(t0) with the beam time of the start (line * 227 + slot), host_display_init() after CREG is loaded,
 * and the host calls the translated entry; tick_hook() does the rest on every instruction. Callbacks: h_frame_cb (the
 * start of a frame: inputs), h_frame_done_cb (the picture is in ARD_PIX), h_wr_cb (every CPU register write), h_pc_cb
 * (every instruction's pc, before an interrupt is accepted - as a breakpoint of the emulator), h_sample_cb (bytes).
 * Inputs: H_JOY0 / H_JOY1 (JOYxDAT), H_CIAA_PRA bits 6/7 (fire), H_POTGOR. No game data: nothing of a game but HOST_L3. */
#ifndef AREK_HOST_H
#define AREK_HOST_H
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "arek_bus_paula.h"
#include "arek_audio.h"

#ifndef HOST_L3
#error "define HOST_L3 (the translated level-3 interrupt handler, e.g. f_c13e1c) before arek_host.h"
#endif
#define HOST_HPOS 227
#ifndef HOST_MAXLINES
#define HOST_MAXLINES 400
#endif
static int    H_LINES = 313;             /* PAL long frame (LOF 1, VPOSR bit 15); 312 for a short one */
static int    H_LOF = 1;
static uint16_t H_INTREQ = 0;            /* Paula INTREQ (read back as INTREQR) */
static long   H_FRAME = 0;               /* frames since the host started */
static long   H_FRAME0 = 0;              /* the original's frame number at the start (records, shots) */
static int    H_COP_DONE = 0;            /* the copper's interrupt of this frame already raised */
static int    H_IRQ_DEPTH = 0;
static uint8_t H_CIAA_PRA = 0xfe;        /* $BFE001: bits 6/7 = fire port 0/1 (0 = pressed), bit 1 = LED output */
static uint8_t H_CIAA_SDR = 0, H_CIAA_ICR = 0, H_CIAA_DDRA = 0x03;
static int    H_LED_OFF = -1;            /* CIA-A PRA bit 1 as the game wrote it: 1 = LED off = filter off; -1 = not yet */
static uint16_t H_JOY0 = 0, H_JOY1 = 0, H_POTGOR = 0x5500;
static long   H_IO_UNKNOWN = 0;
static uint32_t H_IO_LAST = 0;
static uint8_t OWN[HOST_MAXLINES * HOST_HPOS];
static long   H_IRQS = 0;
static double H_VBL_LAT = 10;            /* VERTB visible to the CPU this many CCK after the frame start (measured) */
static int    H_VERTB_PEND = 0;
static uint32_t H_IRQ_PRE = 0, H_IRQ_CYC = 44, H_IRQ_ACC = 7;   /* interrupt entry: internal half-clocks before, clocks, accesses */
static int    H_CIA_A = 4, H_CIA_B = 4, H_IRQ_E = -1;           /* E clock: a CIA access costs H_CIA_A + ((H_CIA_B - phase) mod 10) CPU clocks */
static FILE  *H_CIA_LOG = 0, *H_OWN_DUMP = 0;
static uint32_t H_PC = 0;
static void (*h_frame_cb)(void) = 0;
static void (*h_frame_done_cb)(void) = 0;
static void (*h_wr_cb)(uint32_t off, uint32_t v) = 0;
static void (*h_pc_cb)(M68 *m, uint32_t pc) = 0;
static void (*h_sample_cb)(int ch, double t, int value) = 0;
static ArekPaula H_PAULA;
static char *H_SHOT_PREFIX = 0; static long H_SHOT_FIRST = 0, H_SHOT_LAST = -1;

static uint16_t h_rd16cb(void *ctx, uint32_t a) { (void)ctx; return (uint16_t)rd16_raw(a & 0x7fffe); }
static inline double h_now(void) { return arek_glue_time(); }
static inline double h_abs(void) { return H_PAULA.frame_base + h_now(); }
static double h_ephase(void) { double t2 = 2.0 * h_abs(); return fmod(floor(t2), 10.0); }
static void h_sample(void *ctx, int ch, double t, int value) { (void)ctx; ara_event(ch, t, value); if (h_sample_cb) h_sample_cb(ch, t, value); }

/* the host starts: t0 = beam time of the first instruction (line * 227 + slot); the environment can recalibrate */
static void host_init(double t0) {
    if (getenv("HOST_VBL_LAT")) H_VBL_LAT = atof(getenv("HOST_VBL_LAT"));
    if (getenv("HOST_IRQ_PRE")) H_IRQ_PRE = (uint32_t)atoi(getenv("HOST_IRQ_PRE"));
    if (getenv("HOST_IRQ_CYC")) H_IRQ_CYC = (uint32_t)atoi(getenv("HOST_IRQ_CYC"));
    if (getenv("HOST_IRQ_ACC")) H_IRQ_ACC = (uint32_t)atoi(getenv("HOST_IRQ_ACC"));
    if (getenv("HOST_CIA_LOG")) H_CIA_LOG = fopen(getenv("HOST_CIA_LOG"), "w");
    if (getenv("HOST_CIA_A")) H_CIA_A = atoi(getenv("HOST_CIA_A"));
    if (getenv("HOST_CIA_B")) H_CIA_B = atoi(getenv("HOST_CIA_B"));
    if (getenv("HOST_IRQ_E")) H_IRQ_E = atoi(getenv("HOST_IRQ_E"));
    if (getenv("HOST_LINES")) { H_LINES = atoi(getenv("HOST_LINES")); H_LOF = H_LINES == 313; }
    arek_glue_init(HOST_HPOS, H_LINES, HOST_MAXLINES, OWN, CREG, h_rd16cb, 0);
    arek_glue_frame(H_LINES);
    arek_glue_set_time(t0);
    arek_paula_init(&H_PAULA, arek_glue_bus(), h_sample, 0);
    arek_paula_frame(&H_PAULA, (double)H_FRAME0 * H_LINES * HOST_HPOS);
    ara_reset();
}
#include "arek_display.h"
/* after CREG holds the capture's registers: the picture starts from them, drawn from the current line on */
static void host_display_init(void) {
    for (int i = 0x40; i < 0xe0; i++) { uint32_t off = 2u * i;
        if ((off >= 0x080 && off <= 0x086) || (off >= 0x08e && off <= 0x094) || (off >= 0x0e0 && off <= 0x10a) || (off >= 0x120 && off <= 0x1be)) ard_write(off, CREG[i]); }
    ard_frame_start(); ARD_NEXT = (int)(h_now() / HOST_HPOS);
}

/* the runtime's hooks: custom registers it does not model, every register write, the CIAs */
int hw_read_hook(uint32_t off, uint32_t *v) {
    double t = h_now(); long tt = (long)t; int vp = (int)(tt / HOST_HPOS), hp = (int)(tt % HOST_HPOS);
    switch (off) {
    case 0x004: *v = (H_LOF << 15) | ((vp >> 8) & 1); return 1;                 /* VPOSR (OCS PAL Agnus id 0) */
    case 0x006: *v = ((vp & 0xff) << 8) | (hp & 0xff); return 1;                 /* VHPOSR */
    case 0x01e: *v = H_INTREQ; return 1;                                         /* INTREQR */
    case 0x00a: *v = H_JOY0; return 1;
    case 0x00c: *v = H_JOY1; return 1;
    case 0x016: *v = H_POTGOR; return 1;
    }
    return 0;
}
void hw_write_hook(uint32_t off, uint32_t v) {
    if ((off >= 0x080 && off <= 0x086) || (off >= 0x08e && off <= 0x094) || (off >= 0x0e0 && off <= 0x10a) ||
        (off >= 0x120 && off <= 0x1be)) { ard_until((int)(h_now() / HOST_HPOS)); ard_write(off, (uint16_t)v); }
    if (h_wr_cb) h_wr_cb(off, v);
    if (off == 0x09c) { if (v & 0x8000) H_INTREQ |= v & 0x7fff; else H_INTREQ &= ~(v & 0x7fff); }
    if ((off >= 0x0a0 && off < 0x0e0) || (off == 0x096 && (v & 0x000f))) arek_paula_write(&H_PAULA, h_abs(), off, (uint16_t)v);
}
/* the E clock (10 CPU clocks = 5 CCK): a CIA access and an autovector wait for its phase (measured on 3 instructions) */
static void h_cia_wait(void) {
    if (H_CIA_A < 0) { arek_glue_slow(7); return; }
    int ph = (int)h_ephase(); int clk = H_CIA_A + ((H_CIA_B - ph) % 10 + 10) % 10;
    if (H_CIA_LOG) fprintf(H_CIA_LOG, "%06x %.1f %d %d\n", H_PC, h_abs(), ph, clk);
    arek_glue_slow(clk * 0.5);
}
uint8_t cia_read_hook(uint32_t a) {
    h_cia_wait();
    switch (a) {
    case 0xbfe001: return H_CIAA_PRA;
    case 0xbfec01: return H_CIAA_SDR;
    case 0xbfed01: { uint8_t r = H_CIAA_ICR; H_CIAA_ICR = 0; return r; }
    }
    H_IO_UNKNOWN++; H_IO_LAST = a; return 0xff;
}
void cia_write_hook(uint32_t a, uint8_t v) {
    if (a == 0xbfe201) H_CIAA_DDRA = v;
    if (a == 0xbfe001 && (H_CIAA_DDRA & 2)) { H_LED_OFF = (v >> 1) & 1; H_CIAA_PRA = (uint8_t)((H_CIAA_PRA & ~2) | (v & 2)); }
    h_cia_wait();
}

/* the next frame's map behind the end of the current one, so an instruction crossing the frame end sees the refresh
 * and the copper of line 0 (measured: a cmpi on 312:219 takes 18 CCK in the original, 11 without this) */
static uint8_t OWN_NEXT[HOST_MAXLINES * HOST_HPOS]; static int H_NEXTMAP = 0;
static void h_premap_next(void) {
    ArekBus *b = arek_glue_bus(); ArekBus t = *b; static uint16_t R2[0x100];
    memcpy(R2, b->regs, sizeof R2); t.regs = R2; t.own = OWN_NEXT; t.lines = H_LINES;
    arek_bus_frame_map(&t);
    for (int k = 0; k < 2 * HOST_HPOS; k++) { uint32_t j = (uint32_t)H_LINES * HOST_HPOS + k; if (j < (uint32_t)HOST_MAXLINES * HOST_HPOS && !b->own[j]) b->own[j] = OWN_NEXT[k]; }
}
/* the events of time: the end of the frame (VERTB), the copper's INTREQ write (COPER) */
static void host_events(void) {
    double len = (double)H_LINES * HOST_HPOS;
    if (!H_NEXTMAP && h_now() >= len - 2 * HOST_HPOS) { h_premap_next(); H_NEXTMAP = 1; }
    if (h_now() >= len) {
        if (H_OWN_DUMP) { fwrite(&H_FRAME, sizeof H_FRAME, 1, H_OWN_DUMP); fwrite(OWN, 1, (size_t)H_LINES * HOST_HPOS, H_OWN_DUMP); }
        arek_paula_run(&H_PAULA, H_PAULA.frame_base + len - 1e-9);
        ard_until(ARD_LINES);
        { long fr = H_FRAME0 + H_FRAME;
          if (H_SHOT_PREFIX && fr >= H_SHOT_FIRST && fr <= H_SHOT_LAST) {
              ard_to_rgb(); char pth[600]; snprintf(pth, sizeof pth, "%s_%06ld.raw", H_SHOT_PREFIX, fr);
              FILE *sf = fopen(pth, "wb"); if (sf) { fwrite(ARD_RGB, 1, sizeof ARD_RGB, sf); fclose(sf); } } }
        if (h_frame_done_cb) h_frame_done_cb();
        ard_frame_start();
        arek_glue_frame(H_LINES);
        arek_paula_frame(&H_PAULA, H_PAULA.frame_base + len);
        H_FRAME++; H_COP_DONE = 0; H_NEXTMAP = 0;
        if (H_VBL_LAT <= 0) H_INTREQ |= 0x0020; else H_VERTB_PEND = 1;
        if (h_frame_cb) h_frame_cb();
    }
    if (H_VERTB_PEND && h_now() >= H_VBL_LAT) { H_INTREQ |= 0x0020; H_VERTB_PEND = 0; }
    ArekBus *b = arek_glue_bus();
    if (!H_COP_DONE && b->cop_int >= 0 && h_now() >= b->cop_int) { H_INTREQ |= 0x0010; H_COP_DONE = 1; }
}

/* an interrupt at an instruction boundary: the highest enabled level above the mask; SR and PC to the stack, the
 * translated handler runs, its rte restores SR. Levels: 1 TBE DSKBLK SOFT, 2 PORTS, 3 COPER VERTB BLIT, 4 AUD0-3,
 * 5 RBF DSKSYNC, 6 EXTER. Only the levels the host defines (HOST_Lx) are taken. */
static const uint16_t H_LEVEL_MASK[7] = { 0, 0x0007, 0x0008, 0x0070, 0x0780, 0x1800, 0x2000 };
static void h_enter(M68 *m, uint32_t pc, int level, void (*handler)(M68 *)) {
    uint32_t sr = sr_get(m);
    if (H_IRQ_E >= 0) { int ph = (int)h_ephase(); arek_glue_add_clocks((uint32_t)(((H_IRQ_E - ph) % 10 + 10) % 10)); }
    { ArekBus *bb = arek_glue_bus(); double tt = arek_bus_insn(bb, arek_glue_time(), H_IRQ_CYC, H_IRQ_ACC, H_IRQ_PRE);
      arek_glue_set_time(arek_bus_insn_end(bb, tt)); }
    m->a[7] -= 4; wr16_raw(m->a[7], pc >> 16); wr16_raw(m->a[7] + 2, pc & 0xffff);
    m->a[7] -= 2; wr16_raw(m->a[7], sr);
    m->srhi = (m->srhi & ~0x0700u) | 0x2000u | ((uint32_t)level << 8);
    if (getenv("HOST_IRQ_DEBUG") && H_IRQS < 12) fprintf(stderr, "irq level %d frame %ld t %.1f intreq %04x pc %06x\n", level, H_FRAME, h_now(), H_INTREQ, pc);
    H_IRQS++; H_IRQ_DEPTH++;
    handler(m);
    H_IRQ_DEPTH--;
}
static void host_irq(M68 *m, uint32_t pc) {
    uint16_t intena = CREG[0x09a >> 1];
    if (!(intena & 0x4000)) return;
    uint16_t pend = intena & H_INTREQ & 0x3fff;
    if (!pend) return;
    int ipl = (m->srhi >> 8) & 7;
    for (int level = 6; level > ipl; level--) {
        if (!(pend & H_LEVEL_MASK[level])) continue;
        switch (level) {
#ifdef HOST_L6
        case 6: h_enter(m, pc, 6, HOST_L6); return;
#endif
#ifdef HOST_L5
        case 5: h_enter(m, pc, 5, HOST_L5); return;
#endif
#ifdef HOST_L4
        case 4: h_enter(m, pc, 4, HOST_L4); return;
#endif
        case 3: h_enter(m, pc, 3, HOST_L3); return;
#ifdef HOST_L2
        case 2: h_enter(m, pc, 2, HOST_L2); return;
#endif
#ifdef HOST_L1
        case 1: h_enter(m, pc, 1, HOST_L1); return;
#endif
        default: break;                                   /* a level the host does not serve stays pending */
        }
    }
}

void tick_hook(M68 *m, uint32_t pc, uint32_t clocks) {
    /* an instruction boundary: finish the previous instruction's internal cycles first (arek_bus_insn_end is idempotent),
       so interrupts, time events and records see the time of its end (measured: VBL only after the bmi of a wait loop) */
    { ArekBus *bb = arek_glue_bus(); arek_glue_set_time(arek_bus_insn_end(bb, arek_glue_time())); }
    host_events();
    arek_paula_run(&H_PAULA, h_abs());
    { int ln = (int)(h_now() / HOST_HPOS); if (ln > ARD_NEXT) ard_until(ln); }
    H_PC = pc;
    if (h_pc_cb) h_pc_cb(m, pc);          /* before an interrupt is accepted: as the emulator's breakpoint (pc reached) */
    { long n0 = H_IRQS; host_irq(m, pc);
      if (H_IRQS != n0 && h_pc_cb) h_pc_cb(m, pc); }   /* after the rte the pc is reached again: the breakpoint fires twice */
    arek_glue_insn(pc, clocks);
}
#endif
