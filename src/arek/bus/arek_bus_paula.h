/* arek_bus_paula.h - Paula's audio channels for the bus model (amiga-re-kit): when each channel uses its DMA slot
 * ($0D + 2n), which byte is on its output and when it raises its interrupt request, so a host marks the audio slots of
 * the frame map (arek_bus_mark), mixes the sound and serves level 4. The state machine of the hardware (the HRM's
 * states 000 / 001 / 101 / 010 / 011, as vAmiga 899da5d runs it - the model is written from its measured behaviour,
 * no vAmiga code), checked by `arek selftest audio` against VAHL_BUSLOG / VAHL_AUDLOG and the self-test program's
 * record of the interrupt requests (docs/BUS.md "Audio DMA"):
 *   DMA on in state 000: the length counter loads AUDxLEN, a request (001). A request raised in line v is served in the
 *   channel's slot of line v + 1, even if DMA was switched off meanwhile. The first word (001 -> 101) is discarded: the
 *   pointer goes back to AUDxLC, the counter counts it (unless it is 1), the interrupt request is raised and the next
 *   word requested. The second word (101 -> 010) starts the output: byte 0 = its high byte, the volume latched, a
 *   byte every AUDxPER CCK (010 -> 011 the low byte, 011 -> 010 the high byte of the next word, which also requests
 *   the word after it). A word arriving in 010 / 011 counts the length; the one that finds the counter at 1 (the
 *   block's last word) reloads it and the pointer from AUDxLEN / AUDxLC and marks the interrupt, which is raised at
 *   the next high byte (the start of the next word). Each word enables one high and one low byte: a byte whose turn comes before a new word
 *   arrived is skipped (the period still runs), so a word fetched early loses the previous word's low byte. The volume
 *   written to AUDxVOL takes effect at the next high byte. Output = byte * min(volume, 64).
 *   DMA off in 001 / 101 stops the channel at once; in 010 / 011 the word finishes (the pending low byte is output)
 *   and then, at the end of the word, the channel stops when its interrupt request is still pending (AUDxIP) - or
 *   keeps looping in the CPU's mode when the request was cleared: the buffer plays again and the request is raised
 *   on every word (a CPU-driven channel: AUDxDAT written by the CPU in 000 with the request clear starts the same
 *   loop, and DMA switched on in 010 / 011 continues with the pointer and counter as they are). So the model takes
 *   the INTREQ writes ($9C) as well as the audio registers and DMACON. Interrupt requests are reported one CCK after
 *   their event (irq_cb; the host raises INTREQ bit 7 + channel).
 *   Audio has priority on the bus: the slots a channel will use up to the end of the frame are marked ahead
 *   (arek_paula_predict), so a blit scheduled by BLTSIZE does not take them; a register write re-plans them.
 *
 * Time is absolute CCK (frames * lines * hpos + line * hpos + slot), double, the frame base from arek_paula_frame().
 * Header-only, MIT like the kit. Include it after arek_bus.h. A host:
 *   arek_paula_init(&P, &bus, sample_cb, ctx); P.irq_cb = ...;
 *   after every arek_bus_frame(&bus, lines): arek_paula_frame(&P, absolute time of the frame start);
 *   arek_paula_write(&P, t, off, v) for every write to $DFF0A0-$DFF0DE, to DMACON (audio bits) and to INTREQ;
 *   arek_paula_run(&P, t) before anything that depends on the output (instruction boundaries, the end of the frame).
 * Words are read with the bus's rd16 (chip RAM without the bus; the slot itself is in the map). */
#ifndef AREK_BUS_PAULA_H
#define AREK_BUS_PAULA_H
#include <math.h>
#include <stdint.h>
#include "arek_bus.h"

enum { AREK_PAULA_000 = 0, AREK_PAULA_001 = 1, AREK_PAULA_101 = 5, AREK_PAULA_010 = 2, AREK_PAULA_011 = 3 };
#define AREK_PAULA_NONE (-1e300)                /* no pending request / period event (times may be negative: before the log's frame 0) */
#define AREK_PAULA_HAS(t) ((t) > -1e299)
typedef struct {
    int on, st, ip;                /* AUDxON (DMACON), the state, AUDxIP (the INTREQ bit as the model sees it) */
    double req;                    /* time of the pending DMA request, AREK_PAULA_NONE = none */
    double perfin;                 /* time of the next period event (the next output byte), AREK_PAULA_NONE = none */
    long bcount;                   /* bytes output since the channel started (statistics) */
    uint32_t lc, ptr;
    uint16_t len, audlen, per, vol, vol_latch;
    uint16_t dat, out, first;      /* AUDxDAT (the holding latch), the word on the output, the discarded 1st word */
    int8_t sample;                 /* the byte on the output */
    int en_hi, en_lo;              /* a new word enables one high and one low byte */
    int intreq2;                   /* the block ended: the request is raised at the next high byte */
} ArekPaulaChan;

typedef void (*arek_paula_sample_fn)(void *ctx, int ch, double t, int value);   /* byte * volume at absolute time t */
typedef void (*arek_paula_irq_fn)(void *ctx, int ch, double t);                /* the channel's interrupt request at absolute time t */
typedef void (*arek_paula_state_fn)(void *ctx, int ch, double t, int st);      /* the channel's state changed (analysis) */

typedef struct {
    ArekPaulaChan ch[4];
    ArekBus *bus;
    double frame_base;             /* absolute time of the current frame's slot 0 */
    long fetches;                  /* words fetched (statistics) */
    arek_paula_sample_fn sample_cb; void *ctx;
    arek_paula_irq_fn irq_cb;      /* set after arek_paula_init (0 = none) */
    arek_paula_state_fn state_cb;  /* likewise: every state change of a channel */
    long irqs;                     /* interrupt requests raised (statistics) */
} ArekPaula;

static inline double arek_paula_slot(const ArekPaula *p, int ch, double req) {   /* the slot that serves a request raised at req */
    return (floor(req / p->bus->hpos) + 1) * p->bus->hpos + 0x0d + 2 * ch;
}
static inline double arek_paula_per(const ArekPaulaChan *c) { return c->per ? c->per : 0x10000; }

static inline void arek_paula_mark_at(ArekPaula *p, int ch, double req) {   /* the request's slot into the map, if in this frame */
    double rel = arek_paula_slot(p, ch, req) - p->frame_base;
    if (rel >= 0 && rel < (double)p->bus->lines * p->bus->hpos) arek_bus_mark(p->bus, (uint32_t)rel, (uint8_t)(AREK_BUS_AUDIO + ch));
}
static inline void arek_paula_request(ArekPaula *p, ArekPaulaChan *c, int ch, double t) { if (!AREK_PAULA_HAS(c->req)) { c->req = t; arek_paula_mark_at(p, ch, t); } }
static inline void arek_paula_irq(ArekPaula *p, ArekPaulaChan *c, int ch, double t, int quiet) {
    c->ip = 1;
    if (quiet) return;
    p->irqs++; if (p->irq_cb) p->irq_cb(p->ctx, ch, t + 1);
}
static inline void arek_paula_state(ArekPaula *p, ArekPaulaChan *c, int ch, double t, int st, int quiet) {
    c->st = st; if (!quiet && p->state_cb) p->state_cb(p->ctx, ch, t, st);
}
static inline void arek_paula_byte(ArekPaula *p, ArekPaulaChan *c, int ch, double t, int hi, int quiet) {   /* penhi / penlo */
    c->sample = (int8_t)(hi ? (c->out >> 8) : (c->out & 0xff));
    c->bcount++;
    if (hi ? !c->en_hi : !c->en_lo) return;
    if (hi) c->en_hi = 0; else c->en_lo = 0;
    if (!quiet && p->sample_cb) p->sample_cb(p->ctx, ch, t, c->sample * c->vol);
}
/* a word reaches AUDxDAT at time t (by DMA or written by the CPU): the state machine's transitions */
static inline void arek_paula_dat(ArekPaula *p, ArekPaulaChan *c, int ch, double t, uint16_t w, int quiet) {
    c->dat = w; c->en_hi = c->en_lo = 1;
    if (c->on) {
        switch (c->st) {
        case AREK_PAULA_000: c->audlen = c->len; arek_paula_state(p, c, ch, t, AREK_PAULA_001, quiet); arek_paula_request(p, c, ch, t); break;
        case AREK_PAULA_001:                                  /* the first word: discarded, the pointer back, the request */
            c->first = w; c->ptr = c->lc; if (c->audlen != 1) c->audlen--;
            arek_paula_irq(p, c, ch, t, quiet); arek_paula_request(p, c, ch, t); arek_paula_state(p, c, ch, t, AREK_PAULA_101, quiet); break;
        case AREK_PAULA_101:                                  /* the second word starts the output */
            c->perfin = t + arek_paula_per(c); c->vol = c->vol_latch; c->out = c->dat; c->bcount = 0;
            arek_paula_request(p, c, ch, t); arek_paula_state(p, c, ch, t, AREK_PAULA_010, quiet); arek_paula_byte(p, c, ch, t, 1, quiet); break;
        case AREK_PAULA_010: case AREK_PAULA_011:
            if (c->audlen != 1) c->audlen--; else { c->audlen = c->len; c->ptr = c->lc; c->intreq2 = 1; }
            break;
        }
    } else if (c->st == AREK_PAULA_000 && !c->ip) {           /* the CPU's mode: the word plays, the request is raised */
        c->vol = c->vol_latch; c->perfin = t + arek_paula_per(c); c->out = c->dat; c->bcount = 0;
        arek_paula_irq(p, c, ch, t, quiet); arek_paula_state(p, c, ch, t, AREK_PAULA_010, quiet); arek_paula_byte(p, c, ch, t, 1, quiet);
    }
}
/* The channel's events up to absolute time t (inclusive): the DMA words in their slots, the period events. quiet = a
 * copy planning its slots (arek_paula_predict): no samples, no interrupts, no fetch count. */
static inline void arek_paula_step(ArekPaula *p, ArekPaulaChan *c, int ch, double t, int quiet) {
    for (;;) {
        double tf = AREK_PAULA_HAS(c->req) ? arek_paula_slot(p, ch, c->req) : 1e300;
        double tb = AREK_PAULA_HAS(c->perfin) ? c->perfin : 1e300;
        double nx = tf < tb ? tf : tb;
        if (nx > t) break;
        if (tf <= tb) {                                       /* the DMA word (AUDxDAT) */
            c->req = AREK_PAULA_NONE;
            if (quiet) { arek_paula_mark_at(p, ch, tf - p->bus->hpos); }
            uint16_t w = quiet ? c->dat : p->bus->rd16(p->bus->ctx, c->ptr & p->bus->chipmask);
            if (!quiet) p->fetches++;
            c->ptr += 2;
            arek_paula_dat(p, c, ch, tf, w, quiet);
        } else {                                              /* the period event */
            c->perfin = AREK_PAULA_NONE;
            if (c->st == AREK_PAULA_010) { c->perfin = tb + arek_paula_per(c); arek_paula_state(p, c, ch, tb, AREK_PAULA_011, quiet); arek_paula_byte(p, c, ch, tb, 0, quiet); }
            else if (c->st == AREK_PAULA_011) {
                if (c->on || !c->ip) {                        /* the next word (DMA) or the buffer again (the CPU's mode) */
                    c->perfin = tb + arek_paula_per(c); c->out = c->dat; c->vol = c->vol_latch;
                    if (c->on) { arek_paula_request(p, c, ch, tb); if (c->intreq2) { arek_paula_irq(p, c, ch, tb, quiet); c->intreq2 = 0; } }
                    else arek_paula_irq(p, c, ch, tb, quiet);
                    arek_paula_state(p, c, ch, tb, AREK_PAULA_010, quiet); arek_paula_byte(p, c, ch, tb, 1, quiet);
                } else { c->intreq2 = 0; arek_paula_state(p, c, ch, tb, AREK_PAULA_000, quiet); }   /* DMA off and the request pending: the channel stops */
            }
        }
    }
}
/* Plan the channel's slots up to the end of the frame from its state (unchanged until the next register write): mark them
 * ahead so a blit does not take them; the channel's old planned slots after `from` are freed first. */
static inline void arek_paula_predict(ArekPaula *p, int ch, double from) {
    ArekBus *b = p->bus; uint8_t code = (uint8_t)(AREK_BUS_AUDIO + ch);
    double fend = p->frame_base + (double)b->lines * b->hpos;
    long k0 = (long)(from - p->frame_base) + 1; if (k0 < 0) k0 = 0;
    for (long k = k0; k < (long)b->lines * b->hpos; k++) if (b->own[k] == code) b->own[k] = 0;
    ArekPaulaChan c = p->ch[ch];
    if (AREK_PAULA_HAS(c.req)) arek_paula_mark_at(p, ch, c.req);
    arek_paula_step(p, &c, ch, fend - 1e-9, 1);
}

static inline void arek_paula_init(ArekPaula *p, ArekBus *b, arek_paula_sample_fn cb, void *ctx) {
    for (int ch = 0; ch < 4; ch++) { ArekPaulaChan *c = &p->ch[ch]; c->on = c->st = c->ip = 0; c->req = c->perfin = AREK_PAULA_NONE; c->bcount = 0;
        c->lc = c->ptr = 0; c->len = c->audlen = c->per = c->vol = c->vol_latch = 0; c->dat = c->out = c->first = 0; c->sample = 0;
        c->en_hi = c->en_lo = 0; c->intreq2 = 0; }
    p->bus = b; p->frame_base = 0; p->fetches = 0; p->sample_cb = cb; p->ctx = ctx; p->irq_cb = 0; p->state_cb = 0; p->irqs = 0;
}

/* A new frame (after arek_bus_frame): base = absolute time of its slot 0; the planned slots of every channel go into the new map. */
static inline void arek_paula_frame(ArekPaula *p, double base) {
    p->frame_base = base;
    for (int ch = 0; ch < 4; ch++) arek_paula_predict(p, ch, base - 1);
}

static inline void arek_paula_run(ArekPaula *p, double t) {
    for (int ch = 0; ch < 4; ch++) arek_paula_step(p, &p->ch[ch], ch, t, 0);
}

/* A write at absolute time t: off = $A0-$DE (AUDxLCH/LCL/LEN/PER/VOL/DAT), $96 (DMACON, audio bits 0-3) or $9C (INTREQ). */
static inline void arek_paula_write(ArekPaula *p, double t, uint32_t off, uint16_t v) {
    arek_paula_run(p, t);
    if (off >= 0xa0 && off < 0xe0) {
        int ch = (int)((off - 0xa0) >> 4); ArekPaulaChan *c = &p->ch[ch];
        switch (off & 0xf) {
        case 0x0: c->lc = (c->lc & 0xffff) | ((uint32_t)(v & 0x7) << 16); break;
        case 0x2: c->lc = (c->lc & 0x70000) | (v & 0xfffe); break;
        case 0x4: c->len = v; break;
        case 0x6: c->per = v; arek_paula_predict(p, ch, t); break;
        case 0x8: c->vol_latch = (v & 0x7f) > 64 ? 64 : (v & 0x7f); break;   /* takes effect at the next high byte */
        case 0xa: arek_paula_dat(p, c, ch, t, v, 0); arek_paula_predict(p, ch, t); break;
        }
    } else if (off == 0x096) {
        for (int ch = 0; ch < 4; ch++) if (v & (1 << ch)) {
            ArekPaulaChan *c = &p->ch[ch];
            if (v & 0x8000) { if (!c->on) { c->on = 1; if (c->st == AREK_PAULA_000) { c->audlen = c->len; arek_paula_state(p, c, ch, t, AREK_PAULA_001, 0); arek_paula_request(p, c, ch, t); } } }
            else if (c->on) { c->on = 0; if (c->st == AREK_PAULA_001 || c->st == AREK_PAULA_101) arek_paula_state(p, c, ch, t, AREK_PAULA_000, 0); }
            arek_paula_predict(p, ch, t);
        }
    } else if (off == 0x09c) {
        for (int ch = 0; ch < 4; ch++) if (v & (0x80 << ch)) {
            p->ch[ch].ip = (v & 0x8000) ? 1 : 0;
            arek_paula_predict(p, ch, t);
        }
    }
}
#endif
