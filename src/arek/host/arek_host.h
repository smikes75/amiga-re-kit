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
 * Inputs: H_JOY0 / H_JOY1 (JOYxDAT), H_CIAA_PRA bits 6/7 (fire), H_POTGOR (POTGO's output bits read back - G40). The CIAs:
 * CIA-A PRA / DDRA / SDR / ICR and both CIAs' timers A and B (latch, one-shot or continuous, START, FORCE LOAD, the ICR
 * status and mask, an E tick = 5 CCK; CIA-A raises PORTS, CIA-B EXTER - a loader waiting on CIA-B timer A, G38); other
 * CIA registers answer $FF and count in H_IO_UNKNOWN unless the host defines HOST_CIA_READ(a, &v) / HOST_CIA_WRITE(a, v)
 * (return 1 when handled). HOST_ACK_HANDLER(name, bits) makes a handler that only acknowledges INTREQ bits (a level the
 * game serves through Kickstart, e.g. -DHOST_L4=host_ack_audio). No game data: nothing of a game but HOST_L3. */
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
static int    H_LINES = 313;             /* PAL long frame (LOF 1, VPOSR bit 15); 312 for a short one; with BPLCON0 LACE the fields alternate */
static int    H_LOF = 1;
static int    H_LINES_FORCED = 0;        /* HOST_LINES given: the frame length stays */
static uint16_t H_INTREQ = 0;            /* Paula INTREQ (read back as INTREQR) */
static long   H_FRAME = 0;               /* frames since the host started */
static long   H_FRAME0 = 0;              /* the original's frame number at the start (records, shots) */
static int    H_COP_DONE = 0;            /* the copper's interrupt of this frame already raised */
static int    H_COP_IDX = 0;             /* 1.0.6: how many of the bus model's cop_irq[] of this frame were raised (any INTREQ bits the Copper sets, Turrican II KIT-GAPS 7) */
static int    H_BLIT_PEND = 0;           /* 1.0.5: a blit the CPU started is running; INTREQ BLIT when it ends (Turrican II KIT-GAPS 3) */
static int    H_IRQ_DEPTH = 0;
/* 1.0.50 (SWIV KIT-GAPS 7), OPT-IN with -DHOST_IPL_MODEL=1 (or HOST_IRQ_POLL=1 in the environment): which instruction an
 * interrupt is taken after. The 68000 samples its IPL pins in the last bus cycle of an instruction (Moira: POLL_IPL
 * before the access, 2 clocks into the cycle) and Paula's level reaches the pins some colour clocks after INTREQ /
 * INTENA change (vAmiga: iplPipe). Without the model the host takes an interrupt at the first instruction boundary at
 * which the request is there (VERTB: H_VBL_LAT colour clocks into the frame, 10, fitted). With it: at the boundary of
 * the first instruction whose sample point (its end - H_IRQ_POLL - the wait of its last access) is at or after the
 * request's time + H_IPL_PIPE. Request times: VERTB at H_VBL_LAT (0 with the model), a CPU write to INTENA / INTREQ
 * at the write, anything else at the boundary that found it. Measured on SWIV's boot (frame 790, vAmiga): after
 * `move.w #$8020,INTENA` the original runs one more instruction before the pending VERTB is taken - the model does
 * too; the first VBL entry of the next frame falls on the original's slot. NOT measured: other request sources,
 * instructions that sample earlier than their last bus cycle (shifts, mulu, dbf...). Hence opt-in. */
/* 1.0.55: the request times are vAmiga's own, nothing fitted: Paula's level reaches the pins 3 colour clocks after
 * INTREQ / INTENA change (iplPipe); VERTB is requested at colour clock 0 of the frame, a CIA's interrupt in the E cycle
 * in which its counter reaches 0, a CPU write to INTENA / INTREQ lands one colour clock after its slot. (1.0.50-1.0.54
 * had 2 + 2 for VERTB and 6 + 2 for a CIA: one clock late and right - SWIV's boot met the difference at frame 2146.) */
#ifdef HOST_IPL_MODEL
static double H_IRQ_POLL = 1, H_IPL_PIPE = 3;
#else
static double H_IRQ_POLL = -1, H_IPL_PIPE = 3;
#endif
static double H_POLL_T = 0, H_EVT_T = -1e30, H_PEND_T[7]; static uint8_t H_PEND_ON[7], H_PEND_INIT = 0;
static void h_irq_mark(void);
#ifdef HOST_IPL_MODEL
static int H_CIA_SYNC = 1;
#else
static int H_CIA_SYNC = 0;
#endif
/* 1.0.51 (Turrican II KIT-GAPS 34): a faster CPU for a game mode that asks more of it than the original (more live
 * objects in a wider field). H_CPU_NUM sixteenths of the time between two instruction boundaries count (16 = the
 * 68000, to the byte; 8 = twice the instructions a frame). The frame, the Copper, the blitter, the CIAs and Paula keep
 * their times; an interrupt comes at the same beam position and its handler runs faster too. The time an extern
 * spends (host_spend) is not scaled. Set it at a frame's start: the engine's engine_cpu_speed(n), HOST_CPU_SPEED in
 * the environment for host_trace and the native engine. */
static int    H_CPU_NUM = 16; static double H_CPU_PREV = -1, H_CPU_CREDIT = 0;
#define H_CIA_START (H_CIA_SYNC ? H_CIA_START_N : 0)   /* extra E cycles from the write that starts a timer to its first count: 0 measured (SWIV, one-shot restarted by its handler: intervals 17 751-17 767 against the original's 17 752-17 771); HOST_CIA_START to try others */
static int    H_CIA_START_N = 0;
static double H_CIA_IRQ_LAT = 5.0;       /* colour clocks from the model's underflow to the CIA's interrupt request: one E cycle - vAmiga requests it in the cycle its counter reaches 0, the model counts one further; HOST_CIA_IRQ to try others */
static long   H_TICKS = 0;              /* instructions run (1.0.51: which accesses belong to one instruction) */
static int    H_JDEPTH = 0; static uint8_t H_JLEV[8];   /* 1.0.48: handlers entered by a jump (HOST_VECTOR_JUMP), by level */
static uint8_t H_CIAA_PRA = 0xfe;        /* $BFE001: bits 6/7 = fire port 0/1 (0 = pressed), bit 1 = LED output */
static uint8_t H_CIAA_SDR = 0, H_CIAA_ICR = 0, H_CIAA_DDRA = 0x03, H_CIAB_ICR = 0;
typedef struct { uint16_t latch, cnt; uint8_t cr; int64_t e0; } HCiaTimer;   /* e0 in E ticks: 64 bits (G47: a long is 32 bits in wasm32) */   /* e0: the E tick of the last update */
typedef struct { HCiaTimer t[2]; uint8_t mask; } HCia;
static HCia H_CIA[2] = { { { { 0xffff, 0xffff, 0, 0 }, { 0xffff, 0xffff, 0, 0 } }, 0 }, { { { 0xffff, 0xffff, 0, 0 }, { 0xffff, 0xffff, 0, 0 } }, 0 } };   /* 0 = CIA-A, 1 = CIA-B */
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
/* 1.0.55: the absolute colour clock of the chip-bus access a register hook is called for - its own slot; the model's time
 * is already behind the cycle. What happens in a later slot (the disk's DMA word that raises DSKBLK in slot 7, 9 or 11)
 * is not visible to a read in the slot before it: SWIV's poll loop left its 31st read one pass (13 colour clocks) early */
static inline double h_acc_abs(void) { return H_CIA_SYNC ? h_abs() - 2 + arek_glue_bus()->slotoff : h_abs(); }
static double h_ephase(void) { double t2 = 2.0 * h_abs(); return fmod(floor(t2), 10.0); }
static int64_t h_eticks(void) { return (int64_t)floor(h_abs() / 5.0); }   /* E clock cycles: 10 CPU clocks = 5 CCK; 64 bits - in wasm32 a long passed 2^31 after ~151 000 frames (G47) */
/* the CIAs' timers: counted lazily in E ticks; an underflow reloads the latch, sets the ICR bit and, with the mask bit,
 * raises PORTS (CIA-A) or EXTER (CIA-B); one-shot mode stops the timer */
static uint8_t *h_cia_icr(int i) { return i ? &H_CIAB_ICR : &H_CIAA_ICR; }
static void h_cia_raise(int i) { if (*h_cia_icr(i) & H_CIA[i].mask) H_INTREQ |= i ? 0x2000 : 0x0008; }
static void h_cia_run(int i, int k) {
    HCiaTimer *t = &H_CIA[i].t[k]; int64_t now = h_eticks();
    if (!(t->cr & 1)) { t->e0 = now; return; }
    if (now <= t->e0) return;                              /* 1.0.52: also a timer that starts counting later (H_CIA_START) */
    int64_t n = now - t->e0; t->e0 = now;
    if (n <= t->cnt) { t->cnt = (uint16_t)(t->cnt - n); return; }
    *h_cia_icr(i) |= (uint8_t)(1 << k); h_cia_raise(i);
    if (t->cr & 8) { t->cr &= ~1; t->cnt = t->latch; return; }   /* one-shot: stops */
    int64_t per = (int64_t)t->latch + 1, m = (n - t->cnt - 1) % per;
    t->cnt = (uint16_t)(t->latch - m);
}
/* 1.0.40: a running timer whose ICR mask bit is set underflows at a known time - H_CIA_DUE, the absolute CCK of the
 * earliest one (0: not yet worked out, -1: none). host_events runs the timers then, so the interrupt (PORTS / EXTER)
 * comes when the timer runs out and not when the game next touches the CIA: a timer that is only waited for by its
 * interrupt (a music routine on CIA-B) never fired before. Timers the game polls (no mask bit) stay lazy. */
static double H_CIA_DUE = 0;
static void h_cia_due(void) {
    int64_t best = -1;
    for (int i = 0; i < 2; i++) for (int k = 0; k < 2; k++) { HCiaTimer *t = &H_CIA[i].t[k];
        if ((t->cr & 1) && (H_CIA[i].mask & (1 << k))) { int64_t d = t->e0 + t->cnt + 1; if (best < 0 || d < best) best = d; } }
    H_CIA_DUE = best < 0 ? -1 : (double)best * 5.0;
}
/* 1.0.49 (SWIV): the CIAs of a captured state - state.txt's last line, 8 values for CIA-A then CIA-B: latch, counter
 * and control register of timer A, of timer B, the interrupt mask, the ICR. After host_init (which resets them). The
 * counters go on from the state's time; the emulator's own start delay of a few E ticks is not modelled. */
static void host_cia_state(const unsigned v[16]) {
    for (int i = 0; i < 2; i++) { const unsigned *c = v + 8 * i;
        for (int k = 0; k < 2; k++) { HCiaTimer *t = &H_CIA[i].t[k];
            t->latch = (uint16_t)c[3 * k]; t->cnt = (uint16_t)c[3 * k + 1]; t->cr = (uint8_t)c[3 * k + 2];
            /* 1.0.56: the emulator's counter is two E cycles ahead of the model's (which counts from the write that starts a
             * timer; the 8520 from two cycles later) - a running timer of a capture underflowed two cycles late (SWIV, a
             * capture in the game: the first level 6 entry 2 colour clocks late, the next ones right) */
            t->e0 = h_eticks() - ((H_CIA_SYNC && (t->cr & 1)) ? 2 : 0); }
        H_CIA[i].mask = (uint8_t)(c[6] & 0x7f); *h_cia_icr(i) = (uint8_t)(c[7] & 0x7f); }
    H_CIA_DUE = 0; h_cia_due();
}
static void h_cia_poll(void) {
    if (H_CIA_DUE < 0 || h_abs() < H_CIA_DUE) return;
    double due = H_CIA_DUE;
    h_irq_mark();
    for (int i = 0; i < 2; i++) for (int k = 0; k < 2; k++) h_cia_run(i, k);
    if (H_CIA_SYNC) { H_EVT_T = due + H_CIA_IRQ_LAT; h_irq_mark(); }   /* 1.0.52: the request comes an E cycle after the model's underflow (vAmiga raises it in the cycle its counter reaches 0) */
    h_cia_due();
}
static int h_cia_reg(uint32_t a, int *i) {           /* the CIA and register of an address, or -1 */
    if ((a & 0xbfe001) == 0xbfe001 && (a & 0xfff0ff) == 0xbfe001) { *i = 0; return (int)((a >> 8) & 15); }
    if ((a & 0xfff0ff) == 0xbfd000) { *i = 1; return (int)((a >> 8) & 15); }
    return -1;
}
static void h_sample(void *ctx, int ch, double t, int value) { (void)ctx; ara_event(ch, t, value); if (h_sample_cb) h_sample_cb(ch, t, value); }
static void h_audio_irq(void *ctx, int ch, double t) { (void)ctx; (void)t; H_INTREQ |= (uint16_t)(0x80 << ch); }   /* AUDx: level 4 (HOST_L4) */

static void host_reset(void);
/* the host starts: t0 = beam time of the first instruction (line * 227 + slot); the environment can recalibrate */
static void host_init(double t0) {
    host_reset();
    if (getenv("HOST_IRQ_POLL")) H_IRQ_POLL = atof(getenv("HOST_IRQ_POLL"));
    if (getenv("HOST_CPU_SPEED")) { int n = atoi(getenv("HOST_CPU_SPEED")); if (n >= 2 && n <= 16) H_CPU_NUM = n; }
    if (getenv("HOST_CIA_SYNC")) H_CIA_SYNC = atoi(getenv("HOST_CIA_SYNC"));
    if (getenv("HOST_CIA_START")) H_CIA_START_N = atoi(getenv("HOST_CIA_START"));
    if (getenv("HOST_CIA_IRQ")) H_CIA_IRQ_LAT = atof(getenv("HOST_CIA_IRQ"));
    if (getenv("HOST_IPL_PIPE")) H_IPL_PIPE = atof(getenv("HOST_IPL_PIPE"));
    H_VBL_LAT = H_IRQ_POLL >= 0 ? 0 : 10;
    if (getenv("HOST_VBL_LAT")) H_VBL_LAT = atof(getenv("HOST_VBL_LAT"));
    if (getenv("HOST_IRQ_PRE")) H_IRQ_PRE = (uint32_t)atoi(getenv("HOST_IRQ_PRE"));
    if (getenv("HOST_IRQ_CYC")) H_IRQ_CYC = (uint32_t)atoi(getenv("HOST_IRQ_CYC"));
    if (getenv("HOST_IRQ_ACC")) H_IRQ_ACC = (uint32_t)atoi(getenv("HOST_IRQ_ACC"));
    if (getenv("HOST_CIA_LOG")) H_CIA_LOG = fopen(getenv("HOST_CIA_LOG"), "w");
    if (getenv("HOST_CIA_A")) H_CIA_A = atoi(getenv("HOST_CIA_A"));
    if (getenv("HOST_CIA_B")) H_CIA_B = atoi(getenv("HOST_CIA_B"));
    if (getenv("HOST_IRQ_E")) H_IRQ_E = atoi(getenv("HOST_IRQ_E"));
    if (getenv("HOST_LINES")) { H_LINES = atoi(getenv("HOST_LINES")); H_LOF = H_LINES == 313; H_LINES_FORCED = 1; }
    arek_glue_init(HOST_HPOS, H_LINES, HOST_MAXLINES, OWN, CREG, h_rd16cb, 0);
    arek_glue_frame(H_LINES);
    arek_glue_set_time(t0);
    { ArekBus *b = arek_glue_bus(); if (b->cop_int >= 0 && t0 >= b->cop_int) H_COP_DONE = 1;
      H_COP_IDX = 0; while (H_COP_IDX < b->cop_irq_n && b->cop_irq[H_COP_IDX].t <= t0) H_COP_IDX++; }   /* 1.0.5: a start past the copper's INTREQ write of this frame (the state carries that COPER) - no second one (Turrican II KIT-GAPS 2) */
    arek_paula_init(&H_PAULA, arek_glue_bus(), h_sample, 0);
    H_PAULA.irq_cb = h_audio_irq;
    arek_paula_frame(&H_PAULA, (double)H_FRAME0 * H_LINES * HOST_HPOS);
    ara_reset();
}
#define ARD_DMACON_KNOWN 1               /* 1.0.40: the host's DMACON is the machine's - 0 is all DMA off, not "unknown" */
#include "arek_display.h"
/* after CREG holds the capture's registers: the picture starts from them, drawn from the current line on */
static void host_display_init(void) {
    ard_reset();                                       /* 1.0.43: no register, pointer or sprite of an earlier run */
    for (int i = 0x40; i < 0xe0; i++) { uint32_t off = 2u * i;
        if ((off >= 0x080 && off <= 0x086) || (off >= 0x08e && off <= 0x094) || (off >= 0x0e0 && off <= 0x10a) || (off >= 0x120 && off <= 0x1be)) ard_write(off, CREG[i]); }
    ard_frame_start(); ARD_NEXT = (int)(h_now() / HOST_HPOS); ARD_LAST = H_LINES - 1;
}

/* the runtime's hooks: custom registers it does not model, every register write, the CIAs */
#ifdef HOST_FLOPPY                       /* 1.0.53: drive DF0 and the disk controller, for a game that reads the disk with its own loader */
#include "arek_host_disk.h"
#include "arek_host_floppy.h"
#endif
static void h_premap_next(void); static int H_NEXTMAP;
int hw_read_hook(uint32_t off, uint32_t *v) {
    double t = h_now(); long tt = (long)t; int vp = (int)(tt / HOST_HPOS), hp = (int)(tt % HOST_HPOS), lof = H_LOF;
    /* 1.0.40: the frame rolls at an instruction boundary; a read made past the frame's end inside the instruction is
     * already in the next field - line 0 on, not a line 313 (whose low byte $39 a wait for line $39 took for its line) */
    /* 1.0.55, with the timing model: the position is the one of the access's own slot (not of the time behind it) and
     * Agnus reports it five colour clocks ahead; in the first two of a line still with the old line number (vAmiga's
     * peekVHPOSR / peekVPOSR). SWIV's level 6 handler adds VHPOSR to its random seed: every entry at the original's
     * colour clock, the value 4 too low, another branch nine frames later */
    if (H_CIA_SYNC) { ArekBus *bb = arek_glue_bus(); long sl = bb->last_slot >= 0 ? bb->last_slot : tt - 2 + bb->slotoff; if (sl < 0) sl = 0;
        vp = (int)(sl / HOST_HPOS); hp = (int)(sl % HOST_HPOS); }
    if (vp >= H_LINES) { vp -= H_LINES; if (ARD_R[0x100 >> 1] & 0x0004) lof ^= 1; else if (!H_LINES_FORCED) lof = 1; }
    if (H_CIA_SYNC) { int v0 = vp; hp += 5; if (hp >= HOST_HPOS) { hp -= HOST_HPOS; vp++; } if (vp >= H_LINES) vp = 0; if (hp <= 1) vp = v0; }
    switch (off) {
    case 0x004: *v = (lof << 15) | ((vp >> 8) & 1); return 1;                   /* VPOSR (OCS PAL Agnus id 0) */
    case 0x006: *v = ((vp & 0xff) << 8) | (hp & 0xff); return 1;                 /* VHPOSR */
#ifdef HOST_FLOPPY
    case 0x01e: hfl_run(h_acc_abs()); *v = H_INTREQ; return 1;                      /* INTREQR: a loader polls DSKBLK here */
    case 0x01a: *v = hfl_dskbytr(); return 1;                                    /* DSKBYTR */
#else
    case 0x01e: *v = H_INTREQ; return 1;                                         /* INTREQR */
#endif
    case 0x00a: *v = H_JOY0; return 1;
    case 0x00c: *v = H_JOY1; return 1;
    case 0x016: *v = H_POTGOR; return 1;
    }
    return 0;
}
void hw_write_hook(uint32_t off, uint32_t v) {
#ifdef HOST_FLOPPY
    hfl_reg_write(off, (uint16_t)v);
#endif
    arek_bus_cpu_write(arek_glue_bus(), off);                     /* the CPU's write is the later one (G50) */
    { ArekBus *bb = arek_glue_bus(); bb->journal_on = H_CIA_SYNC;
      if (arek_bus_cpu_reg(bb, off, (uint16_t)v, (uint32_t)h_now()) && H_NEXTMAP) h_premap_next(); }   /* 1.0.56: the re-map cleared the next frame's first lines behind the end */   /* 1.0.52: DMA registers written in the middle of a frame (with the timing model) */
    if ((off >= 0x080 && off <= 0x086) || (off >= 0x08e && off <= 0x094) || (off >= 0x0e0 && off <= 0x10a) ||
        (off >= 0x120 && off <= 0x1be)) { ard_until((int)(h_now() / HOST_HPOS)); ard_write(off, (uint16_t)v); }
    if (off == 0x02e) { ard_until((int)(h_now() / HOST_HPOS)); ARD_CDANG = (int)((v >> 1) & 1); arek_glue_bus()->cdang = ARD_CDANG; }   /* 1.0.47: COPCON */
    if (off == 0x096) ard_until((int)(h_now() / HOST_HPOS));   /* the lines before a DMACON write see the old value (the runtime applies it) */
    if (h_wr_cb) h_wr_cb(off, v);
    if (off == 0x09a || off == 0x09c) { h_irq_mark(); H_EVT_T = h_abs(); }
    if (off == 0x09c) {
        if (v & 0x0780) arek_paula_run(&H_PAULA, h_abs());      /* 1.0.43: Paula up to the write first - a request it raises inside this instruction is older than the write that clears it (it survived the acknowledge) */
        if (v & 0x8000) H_INTREQ |= v & 0x7fff; else H_INTREQ &= ~(v & 0x7fff); }
    if (off == 0x058) H_BLIT_PEND = 1;                                             /* 1.0.5: BLTSIZE by the CPU - INTREQ BLIT when the bus model's blit ends */
    if (off == 0x034) { for (int k = 8; k <= 14; k += 2) if (v & (1u << (k + 1))) H_POTGOR = (uint16_t)((H_POTGOR & ~(1u << k)) | (v & (1u << k))); }   /* POTGO: an output pin reads back (G40) */
    if ((off >= 0x0a0 && off < 0x0e0) || (off == 0x096 && (v & 0x000f)) || (off == 0x09c && (v & 0x0780))) arek_paula_write(&H_PAULA, h_acc_abs() + (H_CIA_SYNC ? (off == 0x096 ? 2 : off == 0x09c ? 1 : 0) : 0), off, (uint16_t)v);   /* 1.0.56: at the write's slot (with the timing model); 1.0.60: the chip takes DMACON two colour clocks later and INTREQ one (vAmiga recordRegisterChange) - a channel switched on at slot 225 starts in the next line */
}
/* the E clock (10 CPU clocks = 5 CCK): a CIA access waits for its phase.
 * 1.0.51 (SWIV KIT-GAPS 7), with -DHOST_IPL_MODEL=1 (or HOST_CIA_SYNC=1 in the environment): vAmiga's rule
 * (Agnus::syncWithEClock, OCS) - at the access the CPU waits until E clock position 2, and takes the position of the
 * next E cycle when that one is less than 6 clocks away: 6 to 15 clocks, then the bus cycle. The position at a frame's
 * start is (2 * frame) mod 10 (142 102 CPU clocks a frame). The access is placed where the 68000 makes it: the model
 * performs an instruction's prefetches first, the 68000 reads its operand BEFORE the last prefetch (4 clocks earlier);
 * the write of a read-modify-write instruction (bclr, addq to memory) comes after that prefetch. Measured on SWIV's
 * VBL handler against vAmiga: bclr #6,$BFEE01 20 colour clocks (the old rule: 17), move.b $BFED01,d0 12 (10).
 * Without the switch: the rule fitted on three instructions (H_CIA_A + ((H_CIA_B - phase) mod 10) clocks). */
static long H_CIA_RD_N = -1, H_CIA_UNDO_N = -1;
static void h_cia_wait2(int write) {
    if (H_CIA_SYNC) {
        int rmw = write && H_CIA_RD_N == H_TICKS;                              /* this instruction read a CIA before: its write comes last */
        if (!write) H_CIA_RD_N = H_TICKS;
        ArekBus *bb = arek_glue_bus(); int redo = !rmw && H_CIA_UNDO_N != H_TICKS && !bb->in_defer && !bb->pat_on;   /* 1.0.53: with the table's order the last prefetch has not been made yet */
        arek_glue_set_time(arek_bus_undo_last(bb)); if (bb->in_da) bb->in_da--;   /* the runtime counted this access as one on the chip bus (bus_access_hook): it is not */
        if (redo) { H_CIA_UNDO_N = H_TICKS; arek_glue_set_time(arek_bus_undo_last(bb)); }   /* the last prefetch comes after this access */
        long clk = (long)floor(2.0 * h_now()) + 2;                             /* the sync is worked out 2 clocks into the bus cycle */
        int e = (int)(((2 * (H_FRAME0 + H_FRAME) + clk) % 10 + 10) % 10), d = ((2 - e) % 10 + 10) % 10; if (d < 6) d += 10;
        if (H_CIA_LOG) fprintf(H_CIA_LOG, "%06x %.1f %d %d\n", H_PC, h_abs(), e, d + 4);
        arek_glue_slow((d + 4) * 0.5);
        if (redo) arek_glue_set_time(arek_bus_access(bb, arek_glue_time()));
        return;
    }
    if (H_CIA_A < 0) { arek_glue_slow(7); return; }
    int ph = (int)h_ephase(); int clk = H_CIA_A + ((H_CIA_B - ph) % 10 + 10) % 10;
    if (H_CIA_LOG) fprintf(H_CIA_LOG, "%06x %.1f %d %d\n", H_PC, h_abs(), ph, clk);
    arek_glue_slow(clk * 0.5);
}
static void h_cia_wait(void) { h_cia_wait2(0); }
uint8_t cia_read_hook(uint32_t a) {
    h_cia_wait();
#ifdef HOST_CIA_READ
    { uint8_t hv; if (HOST_CIA_READ(a, &hv)) return hv; }
#endif
    int i, reg = h_cia_reg(a, &i);
    if (reg >= 4 && reg <= 7) { h_cia_run(i, (reg - 4) >> 1); h_cia_due(); HCiaTimer *t = &H_CIA[i].t[(reg - 4) >> 1]; return (uint8_t)((reg & 1) ? t->cnt >> 8 : t->cnt); }
    if (reg == 13) { h_cia_run(i, 0); h_cia_run(i, 1); h_cia_due(); uint8_t *icr = h_cia_icr(i), r = (uint8_t)(*icr | ((*icr & H_CIA[i].mask) ? 0x80 : 0)); *icr = 0; return r; }
    if (reg == 14 || reg == 15) { int k = reg - 14; h_cia_run(i, k); h_cia_due(); return H_CIA[i].t[k].cr; }
    switch (a) {
#ifdef HOST_FLOPPY
    case 0xbfe001: hfl_run(h_abs()); return (uint8_t)((H_CIAA_PRA & 0xc3) | (hfl_pra() & 0x3c));   /* /CHNG /WPRO /TK0 /RDY from the drive */
    case 0xbfd100: return HFL.prb;
#else
    case 0xbfe001: return H_CIAA_PRA;
#endif
    case 0xbfec01: return H_CIAA_SDR;
    }
    H_IO_UNKNOWN++; H_IO_LAST = a; return 0xff;
}
void cia_write_hook(uint32_t a, uint8_t v) {
#ifdef HOST_CIA_WRITE
    if (HOST_CIA_WRITE(a, v)) { h_cia_wait2(1); return; }
#endif
    if (H_CIA_SYNC) h_cia_wait2(1);                     /* 1.0.52: the write lands after its wait for the E clock - a timer it starts, starts then */
#ifdef HOST_FLOPPY
    if (a == 0xbfd100) { hfl_run(h_abs()); hfl_prb(HFL.prb, v); }                /* CIA-B PRB: motor, select, side, direction, step */
#endif
    int i, reg = h_cia_reg(a, &i);
    if (reg >= 4 && reg <= 7) {                         /* the latch; the high byte loads a stopped timer (and starts a one-shot) */
        int k = (reg - 4) >> 1; HCiaTimer *t = &H_CIA[i].t[k]; h_cia_run(i, k);
        if (reg & 1) { t->latch = (uint16_t)((t->latch & 0xff) | (v << 8)); if (!(t->cr & 1)) { t->cnt = t->latch; if (t->cr & 8) { t->cr |= 1; t->e0 = h_eticks() + H_CIA_START + H_CIA_SYNC; } } }   /* 1.0.55: a start that also loads counts one E cycle later (vAmiga: the load clears CountA2) */
        else t->latch = (uint16_t)((t->latch & 0xff00) | v);
    } else if (reg == 13) { if (v & 0x80) H_CIA[i].mask |= v & 0x7f; else H_CIA[i].mask &= (uint8_t)~v; h_cia_raise(i); }
    else if (reg == 14 || reg == 15) {                 /* control: START (0), ONESHOT (3), FORCE LOAD (4, not stored) */
        int k = reg - 14; HCiaTimer *t = &H_CIA[i].t[k]; h_cia_run(i, k);
        if (v & 0x10) { t->cnt = t->latch; if (H_CIA_SYNC && (t->cr & 1)) t->e0 = h_eticks() + 1; }   /* a forced load skips a count */
        if ((v & 1) && !(t->cr & 1)) t->e0 = h_eticks() + H_CIA_START + ((v & 0x10) ? H_CIA_SYNC : 0);
        t->cr = (uint8_t)(v & 0xef);
    }
    if (reg >= 4 && reg <= 15) h_cia_due();           /* a latch, the mask or a control register changed what is due */
    if (a == 0xbfe201) H_CIAA_DDRA = v;
    if (a == 0xbfe001 && (H_CIAA_DDRA & 2)) { H_LED_OFF = (v >> 1) & 1; H_CIAA_PRA = (uint8_t)((H_CIAA_PRA & ~2) | (v & 2)); }
    if (a == 0xbfec01) H_CIAA_SDR = v;                 /* SDR is loaded by a write: the keyboard handshake writes $FF and reads it back (G53 - a held key repeated) */
    if (!H_CIA_SYNC) h_cia_wait2(1);
}

/* the next frame's map behind the end of the current one, so an instruction crossing the frame end sees the refresh
 * and the copper of line 0 (measured: a cmpi on 312:219 takes 18 CCK in the original, 11 without this) */
static uint8_t OWN_NEXT[HOST_MAXLINES * HOST_HPOS];
static void h_premap_next(void) {
    ArekBus *b = arek_glue_bus(); ArekBus t = *b; static uint16_t R2[0x100];
    memcpy(R2, b->regs, sizeof R2); t.regs = R2; t.own = OWN_NEXT; t.lines = H_LINES;
    arek_bus_frame_map(&t);
    for (int k = 0; k < 2 * HOST_HPOS; k++) { uint32_t j = (uint32_t)H_LINES * HOST_HPOS + k; if (j < (uint32_t)HOST_MAXLINES * HOST_HPOS && !b->own[j]) b->own[j] = OWN_NEXT[k]; }
}
/* the events of time: the end of the frame (VERTB), the copper's INTREQ write (COPER) */
/* 1.0.56: called by the bus model at a CPU access and while it waits (for a blit that holds the bus, for lines): the
 * disk's slots up to 160 colour clocks past the slot the wait has reached, before the blitter gets there. The disk's
 * slots were only marked 160 colour clocks ahead of the instruction's start and a longer blit took them: it ended two
 * slots early for every line it crossed (SWIV in the game, loading while it draws).
 * 1.0.58: and the next frame's first lines behind the map's end, when the instruction that reaches the last two lines
 * began before them (a lea waiting for a blit from line 310 on: no Copper, no refresh behind the frame's end) */
static void h_bus_ahead(ArekBus *b, uint32_t slot) {
    if (!H_NEXTMAP && (double)slot >= (double)H_LINES * HOST_HPOS - 2 * HOST_HPOS) { h_premap_next(); H_NEXTMAP = 1; }
#ifdef HOST_FLOPPY
    hfl_ahead(H_PAULA.frame_base + (double)slot, 160.0);
#endif
    b->ahead_to = slot + 96;
}
static void host_events(void) {
    double len = (double)H_LINES * HOST_HPOS;
    if (!H_NEXTMAP && h_now() >= len - 2 * HOST_HPOS) { h_premap_next(); H_NEXTMAP = 1; }
#ifdef HOST_FLOPPY
    { double fe = H_PAULA.frame_base + len, ta = h_abs(); hfl_run(ta < fe ? ta : fe); if (ta < fe) hfl_ahead(ta, 160.0); }   /* the disk up to now (to the frame's end before it rolls) and its slots ahead */
#endif
    { ArekBus *bb = arek_glue_bus(); bb->ahead = h_bus_ahead; bb->ahead_to = (uint32_t)h_now() + 96; }   /* 1.0.56: and further ahead inside a long instruction */
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
        if (ARD_R[0x100 >> 1] & 0x0004) { H_LOF ^= 1; H_LINES = H_LOF ? 313 : 312; }   /* LACE (by the CPU or the Copper, G39): the fields alternate long / short */
        else if (!H_LINES_FORCED) { H_LOF = 1; H_LINES = 313; }                      /* without LACE every field is long (G35) */
        ARD_LAST = H_LINES - 1;
        arek_glue_frame(H_LINES);
        arek_paula_frame(&H_PAULA, H_PAULA.frame_base + len);
        arek_glue_bus()->ahead_to = 0; arek_glue_frame_carry();     /* 1.0.56: an access that waited for a blit across the frame's end, after the audio slots are planned */
        H_FRAME++; H_COP_DONE = 0; H_COP_IDX = 0; H_NEXTMAP = 0;
        if (H_VBL_LAT <= 0 && H_IRQ_POLL < 0) H_INTREQ |= 0x0020; else H_VERTB_PEND = 1;
        if (h_frame_cb) h_frame_cb();
    }
    if (H_VERTB_PEND && h_now() >= H_VBL_LAT) { h_irq_mark(); H_INTREQ |= 0x0020; H_VERTB_PEND = 0; H_EVT_T = H_PAULA.frame_base + H_VBL_LAT; h_irq_mark(); }
#ifdef HOST_FLOPPY
    hfl_run(h_abs()); hfl_ahead(h_abs(), 160.0);                                 /* after a frame roll: in the new frame's map */
#endif
    arek_glue_bus()->ahead_to = (uint32_t)h_now() + 96;
    h_cia_poll();
    ArekBus *b = arek_glue_bus();
    if (!H_COP_DONE && b->cop_int >= 0 && h_now() >= b->cop_int) { H_INTREQ |= 0x0010; H_COP_DONE = 1; }
    while (H_COP_IDX < b->cop_irq_n && h_now() >= b->cop_irq[H_COP_IDX].t) { H_INTREQ |= b->cop_irq[H_COP_IDX].bits; H_COP_IDX++; }   /* 1.0.6: the Copper's other INTREQ bits (e.g. RBF: level 5) at their times*/
    if (H_BLIT_PEND && !arek_bus_bbusy(b, h_now())) { H_INTREQ |= 0x0040; H_BLIT_PEND = 0; }   /* 1.0.5: the blit finished (as BBUSY sees it) */
}

/* 1.0.43: a start is a clean start. Everything of the host the state does NOT carry goes back to its first value, so a
 * second run in the same process (the page's restart: engine_stop, engine_init, engine_run) is the first run again -
 * before, the frame count went on, the CIA timers kept their latch, mode and mask, a pending blit raised BLIT at the
 * first instruction, a stop in a short field started the next run with 312 lines. What the state carries (INTREQ,
 * CIA-A PRA / SDR / ICR, the joysticks, POTGOR, the first frame's number) is set by the caller before host_init. */
static void host_reset(void) {
    static const HCia cia0 = { { { 0xffff, 0xffff, 0, 0 }, { 0xffff, 0xffff, 0, 0 } }, 0 };
    H_LINES = 313; H_LOF = 1; H_LINES_FORCED = 0;
    H_FRAME = 0; H_COP_DONE = 0; H_COP_IDX = 0; H_BLIT_PEND = 0; H_IRQ_DEPTH = 0; H_VERTB_PEND = 0; H_NEXTMAP = 0;
    H_CIA[0] = cia0; H_CIA[1] = cia0; H_CIAB_ICR = 0; H_CIAA_DDRA = 0x03; H_CIA_DUE = 0;
    H_IO_UNKNOWN = 0; H_IO_LAST = 0; H_IRQS = 0; H_PC = 0;
    RET_PC = NO_RET;
    H_JDEPTH = 0;
    H_CPU_NUM = 16; H_CPU_PREV = -1; H_CPU_CREDIT = 0;
#ifdef HOST_FLOPPY
    hfl_reset(); if (getenv("HOST_ADF0") && !AHD_IMG[0]) ahd_set_file(0, getenv("HOST_ADF0"));   /* natively: the disk of DF0 from a file */
    HFL.dmacon = CREG[0x096 >> 1]; HFL.adkcon = CREG[0x09e >> 1]; if (CREG[0x07e >> 1]) HFL.dsksync = CREG[0x07e >> 1];
    HFL.dskpt = ((uint32_t)(CREG[0x020 >> 1] & 0x1f) << 16) | (CREG[0x022 >> 1] & 0xfffeu);
#endif
    H_PEND_INIT = 0; H_EVT_T = -1e30; for (int i = 0; i < 7; i++) { H_PEND_ON[i] = 0; H_PEND_T[i] = -1e30; }
}

/* an interrupt at an instruction boundary: the highest enabled level above the mask; SR and PC to the stack, the
 * translated handler runs, its rte restores SR. Levels: 1 TBE DSKBLK SOFT, 2 PORTS, 3 COPER VERTB BLIT, 4 AUD0-3 (the
 * Paula model's requests: the first word after DMA on, the last word of every block), 5 RBF DSKSYNC, 6 EXTER. Only the
 * levels the host defines (HOST_Lx) are taken, the highest pending first. */
static const uint16_t H_LEVEL_MASK[7] = { 0, 0x0007, 0x0008, 0x0070, 0x0780, 0x1800, 0x2000 };
/* the entry (the stack frame, SR, the entry's time) and the exit; the handler is called directly through H_ENTER so a
 * browser build with ASYNCIFY_IGNORE_INDIRECT can sleep in a wait loop inside it (Alien Breed II, G37) */
static void h_enter_pre(M68 *m, uint32_t pc, int level) {
    uint32_t sr = sr_get(m);
    if (H_IRQ_E >= 0) { int ph = (int)h_ephase(); arek_glue_add_clocks((uint32_t)(((H_IRQ_E - ph) % 10 + 10) % 10)); }
    if (H_CIA_SYNC) {      /* 1.0.52, with the timing model: the 44 clocks as the 68000 spends them (Moira execInterrupt + jumpToVector) - 6 idle, PC low
                            * to the stack, 8 idle (the autovector), SR and PC high, the vector's two words, a prefetch, 2 idle, a prefetch.
                            * Beside the Copper's slots at a frame's start the accesses wait where the original's do (SWIV: entry slot 34, not 32) */
        ArekBus *bb = arek_glue_bus(); double tt = arek_glue_time() + 3.0;
        tt = arek_bus_access(bb, tt); tt += 4.0;
        for (int k = 0; k < 5; k++) tt = arek_bus_access(bb, tt);
        tt += 1.0; tt = arek_bus_access(bb, tt);
        arek_glue_set_time(tt);
    } else
    { ArekBus *bb = arek_glue_bus(); double tt = arek_bus_insn(bb, arek_glue_time(), H_IRQ_CYC, H_IRQ_ACC, H_IRQ_PRE);
      arek_glue_set_time(arek_bus_insn_end(bb, tt)); }
    m->a[7] -= 4; wr16_raw(m->a[7], pc >> 16); wr16_raw(m->a[7] + 2, pc & 0xffff);
    m->a[7] -= 2; wr16_raw(m->a[7], sr);
    m->srhi = (m->srhi & ~0x0700u) | 0x2000u | ((uint32_t)level << 8);
    if (getenv("HOST_IRQ_DEBUG") && H_IRQS < 12) fprintf(stderr, "irq level %d frame %ld t %.1f intreq %04x pc %06x\n", level, H_FRAME, h_now(), H_INTREQ, pc);
    H_IRQS++; H_IRQ_DEPTH++;
}
static void h_enter_post(void) { H_IRQ_DEPTH--; }
#define H_ENTER(m, pc, level, handler) do { h_enter_pre(m, pc, level); handler(m); h_enter_post(); } while (0)
/* rte as the translation does it; HOST_ACK_HANDLER(name, bits) = a handler that only acknowledges INTREQ bits, for a
 * level the game leaves to Kickstart (otherwise its request would be taken again and again) */
static void h_rte(M68 *m) { uint32_t sp = m->a[7], sr = rd16_raw(sp); sr_set(m, sr, 1); m->a[7] = sp + 6; }
#define HOST_ACK_HANDLER(name, bits) void name(M68 *m) { H_INTREQ &= (uint16_t)~(bits); h_rte(m); }
HOST_ACK_HANDLER(host_ack_audio, 0x0780)
/* 1.0.6: HOST_VECTOR_HANDLER(name, vec) = a handler that jumps through the game's own vector in RAM (the game changes
 * $6c / $70 / $74 at run time - an intro and a level with different handlers): call_addr() of the translation reaches
 * the handler as any other entry; the handler's rte returns here (Turrican II). -DHOST_L3=host_vec_l3 etc. */
#define HOST_VECTOR_HANDLER(name, vec) void name(M68 *m) { call_addr(m, ((uint32_t)rd16_raw((uint32_t)(vec)) << 16) | rd16_raw((uint32_t)(vec) + 2)); }
HOST_VECTOR_HANDLER(host_vec_l1, 0x64)
HOST_VECTOR_HANDLER(host_vec_l2, 0x68)             /* 1.0.12: CIA-A / PORTS - the keyboard (Turrican II KIT-GAPS 19) */
HOST_VECTOR_HANDLER(host_vec_l3, 0x6c)
HOST_VECTOR_HANDLER(host_vec_l4, 0x70)
HOST_VECTOR_HANDLER(host_vec_l5, 0x74)
HOST_VECTOR_HANDLER(host_vec_l6, 0x78)
/* 1.0.48 (SWIV KIT-GAPS 4), with recomp --resume: HOST_VECTOR_JUMP(name, vec) = the handler is entered by a JUMP, as the
 * 68000 enters it - no C frame waits for its rte. For a game whose handlers leave on another stack by other means than
 * their own rte: a scheduler called by jsr that ends in rts on the next task's stack, a sound handler that moves a7
 * from channel to channel. Called from C, such an rts above the routine's entry reads as a plain return, the C callers
 * return one after another and the interrupted routine goes on with a foreign stack. Entered by a jump, the frame the
 * host pushed is all there is: the handler's rte (or whatever ends it) goes on at the stacked PC through TASK_RUN.
 * -DHOST_L3=host_jmp_l3 etc. Not for a host that takes interrupts inside a C routine of its own which must go on
 * afterwards (host_spend in an extern): its frame is dropped too and the interrupted instruction runs again - the
 * routine has to remember where it was. "Inside an interrupt" (H_IN_IRQ, the trace's tick records) is kept by the
 * level: a handler entered at level n is over at the first instruction that runs below n. */
#define H_IN_IRQ (H_IRQ_DEPTH || H_JDEPTH)
#ifdef AREK_RESUME
#define HOST_VECTOR_JUMP(name, vec) void name(M68 *m) { \
    if (H_JDEPTH < 8) H_JLEV[H_JDEPTH++] = (uint8_t)((m->srhi >> 8) & 7); \
    task_jump(m, ((uint32_t)rd16_raw((uint32_t)(vec)) << 16) | rd16_raw((uint32_t)(vec) + 2)); }
HOST_VECTOR_JUMP(host_jmp_l1, 0x64)
HOST_VECTOR_JUMP(host_jmp_l2, 0x68)
HOST_VECTOR_JUMP(host_jmp_l3, 0x6c)
HOST_VECTOR_JUMP(host_jmp_l4, 0x70)
HOST_VECTOR_JUMP(host_jmp_l5, 0x74)
HOST_VECTOR_JUMP(host_jmp_l6, 0x78)
#endif
static void h_irq_mark(void) {
    double t = H_EVT_T > -1e29 ? H_EVT_T : h_abs(); H_EVT_T = -1e30;
    if (!H_PEND_INIT) { H_PEND_INIT = 1; t = -1e30; }              /* what the state brings is on the pins already */
    uint16_t intena = CREG[0x09a >> 1], pend = (intena & 0x4000) ? (uint16_t)(intena & H_INTREQ & 0x3fff) : 0;
    for (int level = 1; level <= 6; level++) { int on = (pend & H_LEVEL_MASK[level]) != 0;
        if (on && !H_PEND_ON[level]) H_PEND_T[level] = t;
        H_PEND_ON[level] = (uint8_t)on; }
}
/* 1.0.53: state.txt's "@drive CYL BYTE DUE MOTOR PRB" line (arek host state, from the capture's `? df0` and events) - the
 * drive where the original's stood. After host_init. Without HOST_FLOPPY: ignored. */
static void host_drive_state(const char *line) {
#ifdef HOST_FLOPPY
    int cyl = 0, motor = 0; long off = 0; double due = 55; unsigned prb = 0xff;
    if (!line || sscanf(line, " @drive %d %ld %lf %d %x", &cyl, &off, &due, &motor, &prb) < 3) return;
    host_floppy_start(cyl, off, due);
    HFL.prb = (uint8_t)prb; HFL.side = (prb & 4) ? 0 : 1;
    if (motor) { HFL.motor = 1; HFL.sw_speed = 100.0; HFL.sw_t = h_abs(); }
#else
    (void)line;
#endif
}
/* 1.0.60: state.txt's "@audio CH ON ST IP REQ PERFIN LC PTR LEN AUDLEN PER VOL VOLLATCH DAT OUT ENHI ENLO INTREQ2" lines
 * (arek host state, from a capture made with a build that has vamiga-audstate-899da5d.patch): Paula's four channels where
 * the original's stood - a channel in the middle of a sample goes on fetching in its slots. REQ / PERFIN: absolute colour
 * clocks, -1 = none. After host_init. Without the lines the channels are idle until the game starts them (SWIV, a
 * capture in the desert: 34 audio slots a frame in the original, none in the host, the first difference 33 lines on). */
static void host_audio_state(const char *text) {
    int any = 0;
    for (const char *p = text; p && (p = strstr(p, "@audio")) != 0; p += 6) {
        int ch, on, st, ip, enhi, enlo, i2; double req, perfin; unsigned lc, ptr, len, audlen, per, vol, voll, dat, out;
        if (sscanf(p, "@audio %d %d %d %d %lf %lf %x %x %x %x %x %x %x %x %x %d %d %d", &ch, &on, &st, &ip, &req, &perfin, &lc, &ptr, &len, &audlen,
                   &per, &vol, &voll, &dat, &out, &enhi, &enlo, &i2) != 18 || ch < 0 || ch > 3) continue;
        ArekPaulaChan *c = &H_PAULA.ch[ch];
        c->on = on; c->st = st; c->ip = ip; c->req = req < 0 ? AREK_PAULA_NONE : req; c->perfin = perfin < 0 ? AREK_PAULA_NONE : perfin;
        c->lc = lc; c->ptr = ptr; c->len = (uint16_t)len; c->audlen = (uint16_t)audlen; c->per = (uint16_t)per;
        c->vol = (uint16_t)vol; c->vol_latch = (uint16_t)voll; c->dat = (uint16_t)dat; c->out = (uint16_t)out;
        c->en_hi = enhi; c->en_lo = enlo; c->intreq2 = i2; c->bcount = 0;
        c->sample = (int8_t)(st == AREK_PAULA_011 ? (out & 0xff) : (out >> 8));
        any = 1;
    }
    if (any) for (int ch = 0; ch < 4; ch++) arek_paula_predict(&H_PAULA, ch, h_abs());
}
static void host_irq(M68 *m, uint32_t pc) {
    h_irq_mark();
    uint16_t intena = CREG[0x09a >> 1];
    if (!(intena & 0x4000)) return;
    uint16_t pend = intena & H_INTREQ & 0x3fff;
    if (!pend) return;
    int ipl = (m->srhi >> 8) & 7;
    for (int level = 6; level > ipl; level--) {
        if (!(pend & H_LEVEL_MASK[level])) continue;
        if (H_IRQ_POLL >= 0 && H_POLL_T < H_PEND_T[level] + H_IPL_PIPE) continue;   /* not yet on the IPL pins when this instruction sampled them */
        switch (level) {
#ifdef HOST_L6
        case 6: H_ENTER(m, pc, 6, HOST_L6); return;
#endif
#ifdef HOST_L5
        case 5: H_ENTER(m, pc, 5, HOST_L5); return;
#endif
#ifdef HOST_L4
        case 4: H_ENTER(m, pc, 4, HOST_L4); return;
#endif
        case 3: H_ENTER(m, pc, 3, HOST_L3); return;
#ifdef HOST_L2
        case 2: H_ENTER(m, pc, 2, HOST_L2); return;
#endif
#ifdef HOST_L1
        case 1: H_ENTER(m, pc, 1, HOST_L1); return;
#endif
        default: break;                                   /* a level the host does not serve stays pending */
        }
    }
}

void tick_hook(M68 *m, uint32_t pc, uint32_t clocks) {
    /* an instruction boundary: finish the previous instruction's internal cycles first (arek_bus_insn_end is idempotent),
       so interrupts, time events and records see the time of its end (measured: VBL only after the bmi of a wait loop) */
    { ArekBus *bb = arek_glue_bus(); arek_glue_set_time(arek_bus_insn_end(bb, arek_glue_time()));
      bb->cpu_fast = H_CPU_NUM != 16;
      if (H_CPU_NUM != 16 && H_CPU_PREV >= 0) { double now = h_abs(), dt = now - H_CPU_PREV;
          if (dt > 0) { H_CPU_CREDIT += dt * (16 - H_CPU_NUM) / 16.0; double w = floor(H_CPU_CREDIT);   /* whole colour clocks only: the accesses stay on the slots' grid */
                        if (w > 0) { H_CPU_CREDIT -= w; arek_glue_set_time(arek_glue_time() - w); } } }
      H_CPU_PREV = h_abs();
      if (bb->poll_valid) { H_POLL_T = H_PAULA.frame_base + bb->pat_poll; bb->poll_valid = 0; bb->poll_back = 0; }   /* 1.0.55: by the instruction's pattern */
      else { H_POLL_T = H_PAULA.frame_base + bb->acc_t[bb->poll_back & 3] + H_IRQ_POLL; bb->poll_back = 0; }   /* where the instruction that just ended sampled the IPL pins: H_IRQ_POLL colour clocks into its last bus cycle (1.0.53: by that cycle's start, not by the instruction's end - idle clocks may follow it) */
      bb->order2 = H_CIA_SYNC; { static int po = -1; if (po < 0) po = getenv("HOST_BUS_PAT") && !atoi(getenv("HOST_BUS_PAT")); bb->pat_off = po; } }
    host_events();
    arek_paula_run(&H_PAULA, h_abs());
    { int ln = (int)(h_now() / HOST_HPOS); if (ln > ARD_NEXT) ard_until(ln); }
    H_PC = pc; H_TICKS++;
    while (H_JDEPTH && (int)((m->srhi >> 8) & 7) < H_JLEV[H_JDEPTH - 1]) H_JDEPTH--;   /* a handler entered by a jump is over */
    if (h_pc_cb) h_pc_cb(m, pc);          /* before an interrupt is accepted: as the emulator's breakpoint (pc reached) */
    { long n0 = H_IRQS; host_irq(m, pc);
      if (H_IRQS != n0 && h_pc_cb) h_pc_cb(m, pc); }   /* after the rte the pc is reached again: the breakpoint fires twice */
    arek_glue_insn(pc, clocks);
}

/* 1.0.8 (Turrican II KIT-GAPS 12): an --extern routine that replaces a loader or a decruncher in C spends the time the
 * original took - the game's phase against its interrupts stays. cck = the ELAPSED time from the routine's entry to its
 * return as measured in the original (clocks per decrunched byte, frames per track...), INCLUDING the interrupt handlers
 * taken meanwhile: the spend ends when the host's clock reaches entry + cck, whatever ran inside (a handler longer
 * than what is left ends it right after). access_every > 0 = one CPU access into the slot map every so many CCK (the
 * original's loop took slots: the blitter beside it slows down), 0 = none. Time moves in steps of HOST_SPEND_STEP CCK;
 * at every step the frame's events run and an interrupt is accepted as at an instruction boundary (its handler runs
 * inside the spend, like in a WAIT_LOOP). The routine's own memory effect goes before or after the call (a disk read
 * writes its buffer after, as the hardware). Natively and in the engine alike. host_elapsed() = the host's clock in CCK
 * (absolute, across frames) for an extern that wants to stop at a measured end itself. */
#ifndef HOST_SPEND_STEP
#define HOST_SPEND_STEP 32.0
#endif
double host_elapsed(void) { return h_abs(); }
void host_spend(M68 *m, double cck, double access_every) {
    const double end = floor(h_abs() + cck + 0.5); double acc = 0;   /* 1.0.53: on a whole colour clock - the 68000's bus cycles sit on them; a fraction (13.5 frames = x.5 colour clocks) left every later access half a slot late */
    while (h_abs() < end) {
        double left = end - h_abs(), step = left < HOST_SPEND_STEP ? left : HOST_SPEND_STEP;
        { ArekBus *bb = arek_glue_bus(); double t = arek_glue_time() + step;
          if (access_every > 0) { acc += step; while (acc >= access_every) { acc -= access_every; t = arek_bus_access(bb, t); } }
          arek_glue_set_time(t); }
        host_events();
        arek_paula_run(&H_PAULA, h_abs());
        { int ln = (int)(h_now() / HOST_HPOS); if (ln > ARD_NEXT) ard_until(ln); }
        H_POLL_T = h_abs();                                  /* 1.0.53: inside an extern there is no instruction to sample the level: now (the stale value of the last instruction held every interrupt back for the whole spend) */
        host_irq(m, H_PC);                                   /* a handler taken here advances the clock: its time counts */
    }
    H_CPU_PREV = h_abs();                                    /* 1.0.51: the original's time, not the CPU's work - not scaled */
}
#endif
