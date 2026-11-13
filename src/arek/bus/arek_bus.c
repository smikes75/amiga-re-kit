/* arek_bus.c - model sbernice: procesor (pristupy instrukci do volnych slotu), rozpracovana instrukce, blitter a snimek (API arek_bus.h).
 * Mapa DMA snimku a blitter po taktech jsou v arek_bus_vamiga.c (odvozeno z vAmiga, MPL-2.0).
 * Overeni a kalibrace: README.md (stopy long1, long2, lv2b Alien Breed SE92 proti VAHL_BUSLOG vAmiga 899da5d). */
#include <string.h>
#include "arek_bus.h"

void arek_bus_init(ArekBus *b, int hpos, int lines, int maxlines, uint8_t *own, uint16_t *regs, arek_bus_rd16_fn rd16, void *ctx) {
    memset(b, 0, sizeof *b);
    b->hpos = hpos; b->lines = lines; b->maxlines = maxlines; b->own = own; b->regs = regs; b->rd16 = rd16; b->ctx = ctx;
    b->chipmask = 0x7fffe; b->slotoff = 1; b->cop_int = -1; b->cop_irq_n = 0; b->cdang = -1;
    for (int n = 0; n < 8; n++) b->spr_ve0[n] = b->spr_ve_end[n] = -1;
    memset(own, 0, (size_t)maxlines * hpos);
}

void arek_bus_frame(ArekBus *b, int lines) {
    uint32_t fend = (uint32_t)(b->lines * b->hpos);   /* konec predchoziho snimku */
    if (b->bl.on) { arek_bus_blt_advance(b, fend - 1); if (b->bl.on) b->bl.bt = b->bl.bt >= fend ? b->bl.bt - fend : 0; }
    b->carry_fend = fend;
    b->lines = lines; b->cpu_n = b->wait_n = 0;
    memcpy(b->spr_ve0, b->spr_ve_end, sizeof b->spr_ve0);   /* 1.0.73: the sprites' VSTOP as the frame that ends left it */
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
    b->acc_t[3] = b->acc_t[2]; b->acc_t[2] = b->acc_t[1]; b->acc_t[1] = b->acc_t[0]; b->acc_t[0] = tt;
    /* 1.0.56: the host's other DMA (the disk's slots, marked a little ahead of the CPU's time) must be in the map before
     * the blitter passes - a CPU access can wait for a blit for lines, and the blit then took the disk's slots */
#define AREK_BUS_AHEAD(s) if (b->ahead && (s) >= b->ahead_to) b->ahead(b, (s))
    /* 1.0.58: the blitter is not moved to the cap or past it - from there on it and the instruction's remaining accesses
     * compete in the new frame's map (arek_bus_frame_carry), slot by slot as anywhere else. 1.0.56 / 1.0.57 let the blit
     * run on behind the map's premapped rows and guessed where the first carried access may stand: right for a lea (two
     * accesses), 10 colour clocks late for a movem that waited with 15 registers to go (SWIV, frame 5179) */
    AREK_BUS_AHEAD(t);
    if (t < cap) arek_bus_blt_advance(b, t);
    b->last_wait = 0;
#define AREK_BUS_TAKEN(o) ((o) && !(b->cpu_fast && (o) == AREK_BUS_CPU))
    if (t < cap && AREK_BUS_TAKEN(b->own[t])) {
        int delay = 0;
        do { t++; delay++; if (t >= cap) break; AREK_BUS_AHEAD(t); arek_bus_blt_advance(b, t); if (delay == 2) b->bls = 1; } while (AREK_BUS_TAKEN(b->own[t]));
        b->bls = 0; b->wait_n += delay; b->last_wait = delay;
    }
    if (t < cap) { b->own[t] = AREK_BUS_CPU; b->last_slot = (long)t; b->cpu_n++; }
    else {                                                   /* 1.0.56: no slot before the cap - arek_bus_frame_carry serves it in the next frame */
        if (!b->unserved) b->carry_k = -1;
        if (b->unserved < AREK_BUS_CARRY) { b->carry_ask[b->unserved] = tt; b->carry_ret[b->unserved] = (double)t + 2 - b->slotoff; }   /* 1.0.61: with the clocks between them */
        b->unserved++; }
    return t + 2 - b->slotoff;
}

/* 1.0.56: after arek_bus_frame, with the CPU's time t already in the new frame: the accesses that found no slot up to one
 * line past the old frame's end (a blit with BLTPRI that holds the bus across the frame's end) wait on in the new frame's
 * map, from line 1 on. They were counted as served at the cap and then forgotten - the instruction ended a bus cycle
 * early (SWIV in the game, frame 4101: a lea beside a blit, 5 colour clocks). Returns the CPU's time. */
double arek_bus_frame_carry(ArekBus *b, double t) {
    int n = b->unserved; b->unserved = 0;
    if (n <= 0) return t;
    /* the first of them stood at the cap (line 1, slot 0 of the new frame) and asks there again; the others follow with
     * the idle clocks the instruction has between them, and behind the last one come the clocks that followed it
     * (1.0.61: an interrupt entry that waited for a blit across the frame's end has 4 and 1 colour clocks between its
     * seven cycles - they were run back to back, 5 colour clocks short; SWIV, frame 18009) */
    double t0 = (double)b->hpos - b->slotoff, end = t + (double)b->carry_fend;
    for (int i = 0; i < n; i++) {
        if (i > 0 && i < AREK_BUS_CARRY) { double gap = b->carry_ask[i] - b->carry_ret[i - 1]; if (gap > 0) t0 += gap; }
        /* 1.0.61: the cycle in which the instruction samples the interrupt level, when it is one of the carried ones, is
         * made HERE - behind the wait of the cycles before it. Its sample time was taken where the cycle first asked, one
         * line past the old frame's end: an interrupt that came during a 400-clock wait for a blit was missed at this
         * instruction's end and a lower one, older, taken first (SWIV: level 3 before level 6, frame 6690) */
        int k = (b->carry_k >= 0 && i > 0) ? b->carry_k + i : -1;   /* the first carried cycle began (and sampled) before its wait, in the old frame */
        if (k >= 0 && k == b->pat_pj && b->pat_pd < 4) { b->pat_poll = t0 + b->pat_pd * 0.5; b->poll_carried = 1; }
        t0 = arek_bus_access(b, t0);
        if (k >= 0 && k == b->pat_pj && b->pat_pd >= 4) { b->pat_poll = t0 + (b->pat_pd - 4) * 0.5; b->poll_carried = 1; }
    }
    if (n <= AREK_BUS_CARRY) { double rest = end - b->carry_ret[n - 1]; if (rest > 0) t0 += rest; }
    return t0 > t ? t0 : t;
}

double arek_bus_undo_last(ArekBus *b) {
    if (b->last_slot >= 0 && b->own[b->last_slot] == AREK_BUS_CPU) { b->own[b->last_slot] = AREK_BUS_FREE; b->cpu_n--; }
    double t = b->last_t0; b->last_t0 = b->prev_t0; b->last_slot = b->prev_slot; b->prev_slot = -1;
    b->acc_t[0] = b->acc_t[1]; b->acc_t[1] = b->acc_t[2]; b->acc_t[2] = b->acc_t[3]; return t;
}

static double arek_pat_access(ArekBus *b, double t) {
    int k = b->pat_acc++, u0 = b->unserved;
    if (k == b->pat_pj && b->pat_pd < 4) b->pat_poll = t + b->pat_pd * 0.5;        /* inside the cycle, before its access (and its wait) */
    t = arek_bus_access(b, t);
    if (k == b->pat_pj && b->pat_pd >= 4) b->pat_poll = t + (b->pat_pd - 4) * 0.5; /* behind the cycle */
    if (!u0 && b->unserved) b->carry_k = k;                  /* 1.0.61: which bus cycle of the pattern is the first one carried into the next frame */
    return t;
}
static double arek_pat_run(ArekBus *b, double t, int to_data) {
    while (b->pat_i < b->pat_n) {
        uint8_t x = b->pat[b->pat_i];
        if (x == 0x81 && to_data) return t;
        b->pat_i++;
        if (x == 0x80 || x == 0x81) t = arek_pat_access(b, t);
        else if (x == 0xfe) { if (b->pat_v > 0) t += b->pat_v * 0.5; }
        else t += x * 0.5;
    }
    return t;
}
double arek_bus_pat_begin(ArekBus *b, double t, const uint8_t *p, uint32_t clocks) {
    t = arek_bus_insn_end(b, t);
    int fixed = 0;
    for (int i = 0; i < p[0]; i++) { uint8_t x = p[3 + i]; fixed += (x == 0x80 || x == 0x81) ? 4 : x == 0xfe ? 0 : x; }
    b->pat = p + 3; b->pat_n = p[0]; b->pat_i = 0; b->pat_pj = p[1] == 255 ? -1 : p[1]; b->pat_pd = p[2]; b->pat_acc = 0;
    b->pat_v = (int)clocks - fixed; b->pat_on = 1;
    b->pat_poll = t + (b->pat_pj < 0 ? b->pat_pd * 0.5 : 0);
    return arek_pat_run(b, t, 1);
}

double arek_bus_insn_end(ArekBus *b, double t) {
    if (b->pat_on) { t = arek_pat_run(b, t, 0); b->pat_on = 0; b->poll_valid = 1; }   /* 1.0.55: the rest of the instruction's pattern */
    if (b->in_defer) { b->in_defer = 0; b->in_l++; t = arek_bus_access(b, t); }   /* 1.0.53: the last prefetch, after the operand's accesses and before the idle clocks */
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

double arek_bus_data(ArekBus *b, double t) {
    if (b->pat_on) {                                         /* 1.0.55: the pattern's next data cycle (none left: the translation made an access the 68000 does not) */
        t = arek_pat_run(b, t, 1);
        if (b->pat_i < b->pat_n) { b->pat_i++; t = arek_pat_access(b, t); }
        return t;
    }
    if (b->in_defer >= 2 && b->in_da == b->in_defer - 1) { b->in_defer = 0; b->in_l++; t = arek_bus_access(b, t); }   /* read, PREFETCH, write */
    b->in_da++; return arek_bus_access(b, t);
}
double arek_bus_slow(ArekBus *b, double t, double cck) {
    if (b->pat_on) return t + cck;                           /* 1.0.55: the host took the pattern's data cycle back (arek_bus_undo_last) and spends its own time */
    if (b->in_defer >= 2 && b->in_da == b->in_defer - 1) { b->in_defer = 0; b->in_l++; t = arek_bus_access(b, t); }
    b->acc_t[3] = b->acc_t[2]; b->acc_t[2] = b->acc_t[1]; b->acc_t[1] = b->acc_t[0]; b->acc_t[0] = t;   /* a CIA access is a bus cycle of the instruction too */
    b->in_da++; return t + cck;
}

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
