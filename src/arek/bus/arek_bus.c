/* arek_bus.c - model sbernice: procesor (pristupy instrukci do volnych slotu), rozpracovana instrukce, blitter a snimek (API arek_bus.h).
 * Mapa DMA snimku a blitter po taktech jsou v arek_bus_vamiga.c (odvozeno z vAmiga, MPL-2.0).
 * Overeni a kalibrace: README.md (stopy long1, long2, lv2b Alien Breed SE92 proti VAHL_BUSLOG vAmiga 899da5d). */
#include <string.h>
#include "arek_bus.h"

void arek_bus_init(ArekBus *b, int hpos, int lines, int maxlines, uint8_t *own, uint16_t *regs, arek_bus_rd16_fn rd16, void *ctx) {
    memset(b, 0, sizeof *b);
    b->hpos = hpos; b->lines = lines; b->maxlines = maxlines; b->own = own; b->regs = regs; b->rd16 = rd16; b->ctx = ctx;
    b->chipmask = 0x7fffe; b->slotoff = 1; b->cop_int = -1; b->cop_irq_n = 0; b->cdang = -1;
    memset(own, 0, (size_t)maxlines * hpos);
}

void arek_bus_frame(ArekBus *b, int lines) {
    uint32_t fend = (uint32_t)(b->lines * b->hpos);   /* konec predchoziho snimku */
    if (b->bl.on) { arek_bus_blt_advance(b, fend - 1); if (b->bl.on) b->bl.bt = b->bl.bt >= fend ? b->bl.bt - fend : 0; }
    b->lines = lines; b->cpu_n = b->wait_n = 0;
    arek_bus_frame_map(b);
}

/* Moira (procesor vAmigy): SYNC(2) = 1 takt, pristup (Agnus: volny slot?), SYNC(2). Procesor si slot bere az po udalostech Agnusu
 * v taktu (blitter je vidi jako volne); po 2 taktech cekani blitter bez BLTPRI ustoupi (bls). */
double arek_bus_access(ArekBus *b, double tt) {
    /* 1.0.7 (Turrican II KIT-GAPS 10): a wait for a free slot may run past the frame end by at most one line (the rows the
     * caller premapped): time must not flow further inside the model - the caller rolls the frame, and a blit that
     * holds the bus (BLTPRI) goes on in the next frame's real map, where its slots are recorded. Before, the wait ran to
     * the end of the overflow rows: the blit finished there unrecorded and the CPU re-entered the new frame lines later. */
    uint32_t cap = (uint32_t)(b->maxlines * b->hpos);
    { uint32_t lim = (uint32_t)(b->lines * b->hpos) + (uint32_t)b->hpos; if (lim < cap) cap = lim; }
    uint32_t t = (uint32_t)tt; if ((double)t < tt) t++; t += b->slotoff;
    b->prev_t0 = b->last_t0; b->prev_slot = b->last_slot; b->last_t0 = tt; b->last_slot = -1;
    arek_bus_blt_advance(b, t); b->last_wait = 0;
#define AREK_BUS_TAKEN(o) ((o) && !(b->cpu_fast && (o) == AREK_BUS_CPU))
    if (t < cap && AREK_BUS_TAKEN(b->own[t])) {
        int delay = 0;
        do { t++; arek_bus_blt_advance(b, t); if (++delay == 2) b->bls = 1; } while (t < cap && AREK_BUS_TAKEN(b->own[t]));
        b->bls = 0; b->wait_n += delay; b->last_wait = delay;
    }
    if (t < cap) { b->own[t] = AREK_BUS_CPU; b->last_slot = (long)t; }
    b->cpu_n++; return t + 2 - b->slotoff;
}

double arek_bus_undo_last(ArekBus *b) {
    if (b->last_slot >= 0 && b->own[b->last_slot] == AREK_BUS_CPU) { b->own[b->last_slot] = AREK_BUS_FREE; b->cpu_n--; }
    double t = b->last_t0; b->last_t0 = b->prev_t0; b->last_slot = b->prev_slot; b->prev_slot = -1; return t;
}

double arek_bus_insn_end(ArekBus *b, double t) {
    int rem = (int)b->in_n - (int)b->in_pre - 4 * (int)(b->in_l + b->in_da + b->in_tail); if (rem > 0) t += rem * 0.5;
    /* 1.0.47 (SWIV KIT-GAP 2): the reads an instruction makes after its internal clocks - move to SR / CCR reads two
     * words after 4 clocks, andi/ori/eori to SR / CCR after 8, lea d8(An,Xn) its last word after 2. They were made at the
     * instruction's start: the same length on a free bus, another slot (and another wait) beside bitplane DMA */
    { uint32_t n = b->in_tail; b->in_n = b->in_l = b->in_da = b->in_pre = b->in_tail = 0; for (uint32_t k = 0; k < n; k++) t = arek_bus_access(b, t); }
    return t;
}

double arek_bus_insn(ArekBus *b, double t, uint32_t cycles, uint32_t accesses, uint32_t pre) {
    t = arek_bus_insn_end(b, t);
    t += pre * 0.5; b->in_pre = pre;
    b->in_n = cycles; b->in_l = accesses;
    for (uint32_t k = 0; k < accesses; k++) t = arek_bus_access(b, t);
    return t;
}

double arek_bus_data(ArekBus *b, double t) { b->in_da++; return arek_bus_access(b, t); }
double arek_bus_slow(ArekBus *b, double t, double cck) { b->in_da++; return t + cck; }

/* 1.0.43: the slot the blitter has reached at time t. In the first colour clocks of a frame t - 2 + slotoff is below
 * zero; as an unsigned number that was slot 4 294 967 295 and a blit crossing the frame end finished at once. */
static uint32_t arek_bus_slot_of(ArekBus *b, double t) { double s = (double)(uint32_t)t - 2 + (double)b->slotoff; return s < 0 ? 0 : (uint32_t)s; }
double arek_bus_blit(ArekBus *b, double t, uint16_t con0, uint16_t con1, uint16_t size) {
    uint32_t h = size >> 6, w = size & 0x3f; if (!h) h = 1024; if (!w) w = 64;
    if (con1 & 1) return t + (double)h * 8;   /* rezim car: zatim jen odhad casu procesoru, bez slotu */
    arek_bus_blt_start(b, arek_bus_slot_of(b, t), con0, h * w);
    return t;
}

int arek_bus_bbusy(ArekBus *b, double t) { arek_bus_blt_advance(b, arek_bus_slot_of(b, t)); return b->bl.busy; }
