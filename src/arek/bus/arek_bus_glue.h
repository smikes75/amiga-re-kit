/* arek_bus_glue.h - the bus model (arek_bus.h) behind the hooks of a kit translation (amiga-re-kit).
 *
 * Include it ONCE, after the generated translation (it needs M68 and, with `recomp --bus-table`, BUS_TAB) and build the
 * translation with -DTICK_HOOK -DBUS_HOOK: the runtime then calls tick_hook() per instruction, bus_access_hook() per CPU
 * access to the chip bus (RAM, custom registers), bus_blit_hook() at BLTSIZE and bus_bbusy_hook() when the game reads
 * DMACONR. This file turns them into model calls and keeps the CPU's time (CCK slots from the start of the frame).
 *
 * The host:
 *   static uint8_t OWN[313 * 227]; static uint16_t REGS[0x100];           // REGS: the game's custom registers as the host keeps them
 *   arek_glue_init(227, 313, 313, OWN, REGS, my_rd16, ctx);              // once; cop_default etc. through arek_glue_bus()
 *   per frame: arek_glue_frame(lines);  ... run the translated frame routine ...  if (arek_glue_time() >= frame_slots) overrun
 *   audio slots: arek_bus_mark(arek_glue_bus(), slot, AREK_BUS_AUDIO + n) from the host's Paula model
 * CIA accesses are not on the chip bus: a host that routes them through rd/wr should map them with arek_glue_slow().
 * Without BUS_TAB (no --bus-table) every instruction counts its opcode word as its only prefetch and no internal cycles
 * before the accesses - coarse, but the time still moves.
 *
 * BUS_TAB[i] = {words, extra, flags}; flags (arek.m68k.timing): 1 a taken short branch reads one more word (clocks 10),
 * 2 an expired dbcc reads one more (clocks 14), 4 a jump spends its internal cycles before its accesses, 8 -(An)/d8(An,Xn)
 * wait 2 cycles before the operand, 16 jsr/bsr push two words after the jump. */
#ifndef AREK_BUS_GLUE_H
#define AREK_BUS_GLUE_H
#include "arek_bus.h"

static struct { ArekBus bus; double t; int ready; } AREK_GLUE;

static inline ArekBus *arek_glue_bus(void) { return &AREK_GLUE.bus; }
static inline double arek_glue_time(void) { return AREK_GLUE.t; }
static inline void arek_glue_set_time(double t) { AREK_GLUE.t = t; }

static inline void arek_glue_init(int hpos, int lines, int maxlines, uint8_t *own, uint16_t *regs, arek_bus_rd16_fn rd16, void *ctx) {
    arek_bus_init(&AREK_GLUE.bus, hpos, lines, maxlines, own, regs, rd16, ctx);
    AREK_GLUE.t = 0; AREK_GLUE.ready = 1;
}

/* Start of a frame: the CPU's time wraps by the previous frame's length (an overrun carries into the new frame). */
static inline void arek_glue_frame(int lines) {
    double len = (double)AREK_GLUE.bus.lines * AREK_GLUE.bus.hpos;
    AREK_GLUE.t = AREK_GLUE.t > len ? AREK_GLUE.t - len : 0;
    arek_bus_frame(&AREK_GLUE.bus, lines);
}

/* An access off the chip bus (CIA: 7 CCK on the E clock) counted against the current instruction. */
static inline void arek_glue_slow(double cck) { if (AREK_GLUE.ready) AREK_GLUE.t = arek_bus_slow(&AREK_GLUE.bus, AREK_GLUE.t, cck); }

void tick_hook(M68 *m, uint32_t pc, uint32_t clocks) {
    (void)m;
    if (!AREK_GLUE.ready) return;
    uint32_t words = 1, extra = 0, flags = 0, pre = 0;
#ifdef BUS_N
    uint32_t i = (pc - BUS_LO) >> 1;
    if (i < BUS_N && BUS_TAB[i][0]) { words = BUS_TAB[i][0]; extra = BUS_TAB[i][1]; flags = BUS_TAB[i][2]; }
#else
    (void)pc;
#endif
    if ((flags & 1) && clocks == 10) extra++;
    if ((flags & 2) && clocks == 14) extra++;
    uint32_t acc = words + extra + ((flags & 16) ? 2 : 0);
    if (flags & 4) pre = clocks > 4 * acc ? clocks - 4 * acc : 0;
    else if (flags & 8) pre = 2;
    AREK_GLUE.t = arek_bus_insn(&AREK_GLUE.bus, AREK_GLUE.t, clocks, words + extra, pre);
}

void bus_access_hook(uint32_t a) {
    (void)a;
    if (AREK_GLUE.ready) AREK_GLUE.t = arek_bus_data(&AREK_GLUE.bus, AREK_GLUE.t);
}

void bus_blit_hook(uint16_t con0, uint16_t con1, uint16_t size) {
    if (AREK_GLUE.ready) AREK_GLUE.t = arek_bus_blit(&AREK_GLUE.bus, AREK_GLUE.t, con0, con1, size);
}

int bus_bbusy_hook(void) {
    return AREK_GLUE.ready ? arek_bus_bbusy(&AREK_GLUE.bus, AREK_GLUE.t) : 0;
}

double bus_time_hook(void) { return AREK_GLUE.t; }
#endif
