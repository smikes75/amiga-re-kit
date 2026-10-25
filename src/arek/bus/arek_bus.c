/* arek_bus.c - model sbernice: procesor (pristupy instrukci do volnych slotu), rozpracovana instrukce, blitter a snimek (API arek_bus.h).
 * Mapa DMA snimku a blitter po taktech jsou v arek_bus_vamiga.c (odvozeno z vAmiga, MPL-2.0).
 * Overeni a kalibrace: README.md (stopy long1, long2, lv2b Alien Breed SE92 proti VAHL_BUSLOG vAmiga 899da5d). */
#include <string.h>
#include "arek_bus.h"

void arek_bus_init(ArekBus *b, int hpos, int lines, int maxlines, uint8_t *own, uint16_t *regs, arek_bus_rd16_fn rd16, void *ctx) {
    memset(b, 0, sizeof *b);
    b->hpos = hpos; b->lines = lines; b->maxlines = maxlines; b->own = own; b->regs = regs; b->rd16 = rd16; b->ctx = ctx;
    b->chipmask = 0x7fffe; b->slotoff = 1; b->cop_int = -1;
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
    const uint32_t cap = (uint32_t)(b->maxlines * b->hpos);
    uint32_t t = (uint32_t)tt; if ((double)t < tt) t++; t += b->slotoff;
    arek_bus_blt_advance(b, t);
    if (t < cap && b->own[t]) {
        int delay = 0;
        do { t++; arek_bus_blt_advance(b, t); if (++delay == 2) b->bls = 1; } while (t < cap && b->own[t]);
        b->bls = 0; b->wait_n += delay;
    }
    if (t < cap) b->own[t] = AREK_BUS_CPU;
    b->cpu_n++; return t + 2 - b->slotoff;
}

double arek_bus_insn_end(ArekBus *b, double t) {
    int rem = (int)b->in_n - (int)b->in_pre - 4 * (int)(b->in_l + b->in_da); if (rem > 0) t += rem * 0.5;
    b->in_n = b->in_l = b->in_da = b->in_pre = 0;
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

double arek_bus_blit(ArekBus *b, double t, uint16_t con0, uint16_t con1, uint16_t size) {
    uint32_t h = size >> 6, w = size & 0x3f; if (!h) h = 1024; if (!w) w = 64;
    if (con1 & 1) return t + (double)h * 8;   /* rezim car: zatim jen odhad casu procesoru, bez slotu */
    arek_bus_blt_start(b, (uint32_t)t - 2 + b->slotoff, con0, h * w);
    return t;
}

int arek_bus_bbusy(ArekBus *b, double t) { arek_bus_blt_advance(b, (uint32_t)t - 2 + b->slotoff); return b->bl.busy; }
