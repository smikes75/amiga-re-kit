/* arek_bus_paula.h - Paula audio DMA for the bus model (amiga-re-kit): when each channel uses its DMA slot ($0D + 2n) and
 * which byte is on its output, so a host marks the audio slots of the frame map (arek_bus_mark) and mixes the sound.
 *
 * Rules measured by the Alien Breed II project against VAHL_BUSLOG / VAHL_AUDLOG of vAmiga 899da5d (docs/BUS.md
 * "Audio DMA"), checked by `arek selftest audio`:
 *   DMA on -> a request. A request raised in line v is served in the channel's slot of line v + 1, even if DMA was
 *   switched off meanwhile. The first word after switching on is discarded and the pointer goes back to AUDxLC; the
 *   second word starts the output (byte 0 = its high byte) and requests the next word; then a byte every AUDxPER CCK,
 *   and every even byte (a new word reaches the output) requests the next word. Output = byte * min(volume, 64).
 *   The length counter wraps the pointer to AUDxLC after AUDxLEN words. Audio has priority on the bus: the slots a
 *   channel will use up to the end of the frame are marked ahead (arek_paula_predict), so a blit scheduled by BLTSIZE
 *   does not take them; a register write re-plans them.
 *   The output (vAmiga's state machine, checked by the self-test's samples): each DMA word enables one high and one
 *   low byte; a byte whose turn comes before a new word arrived is skipped (the period still runs), so a word fetched
 *   early loses the previous word's low byte. The volume written to AUDxVOL takes effect at the next high byte.
 *   After DMA off a pending low byte is still output, then the channel stops (a game that clears the audio
 *   INTREQ bits and switches DMA off and on without a gap keeps vAmiga's state machine looping; not modelled).
 *
 * Time is absolute CCK (frames * lines * hpos + line * hpos + slot), double, the frame base from arek_paula_frame().
 * Header-only, MIT like the kit (no vAmiga code). Include it after arek_bus.h. A host:
 *   arek_paula_init(&P, &bus, sample_cb, ctx);
 *   after every arek_bus_frame(&bus, lines): arek_paula_frame(&P, absolute time of the frame start);
 *   arek_paula_write(&P, t, off, v) for every write to $DFF0A0-$DFF0DE and to DMACON (audio bits);
 *   arek_paula_run(&P, t) before anything that depends on the output (instruction boundaries, the end of the frame).
 * Words are read with the bus's rd16 (chip RAM without the bus; the slot itself is in the map). */
#ifndef AREK_BUS_PAULA_H
#define AREK_BUS_PAULA_H
#include <math.h>
#include <stdint.h>
#include "arek_bus.h"

typedef struct {
    int on, st;                    /* st: 0 idle, 1 waiting for the 1st word, 2 waiting for the 2nd, 3 output running */
    double req;                    /* time of the pending DMA request, < 0 = none */
    double nbyte;                  /* time of the next output byte, < 0 = none */
    long bcount;                   /* bytes output since the 2nd word (even = a new word on the output) */
    uint32_t lc, ptr;
    uint16_t len, lenctr, per, vol, vol_latch;
    uint16_t hold, out, first;     /* the last word fetched (AUDxDAT), the word on the output, the discarded 1st word */
    int8_t sample;                 /* the byte on the output */
    int en_hi, en_lo;              /* a new word enables one high and one low byte (vAmiga enablePenhi/Penlo) */
    int drain;                     /* DMA off while the low byte of the word is still due: output it, then stop */
} ArekPaulaChan;

typedef void (*arek_paula_sample_fn)(void *ctx, int ch, double t, int value);   /* byte * volume at absolute time t */

typedef struct {
    ArekPaulaChan ch[4];
    ArekBus *bus;
    double frame_base;             /* absolute time of the current frame's slot 0 */
    long fetches;                  /* words fetched (statistics) */
    arek_paula_sample_fn sample_cb; void *ctx;
} ArekPaula;

static inline double arek_paula_slot(const ArekPaula *p, int ch, double req) {   /* the slot that serves a request raised at req */
    return (floor(req / p->bus->hpos) + 1) * p->bus->hpos + 0x0d + 2 * ch;
}

static inline void arek_paula_mark(ArekPaula *p, int ch) {           /* the pending request's slot into the map, if in this frame */
    ArekPaulaChan *c = &p->ch[ch];
    if (c->req < 0) return;
    double rel = arek_paula_slot(p, ch, c->req) - p->frame_base;
    if (rel >= 0 && rel < (double)p->bus->lines * p->bus->hpos) arek_bus_mark(p->bus, (uint32_t)rel, (uint8_t)(AREK_BUS_AUDIO + ch));
}

static inline void arek_paula_request(ArekPaula *p, int ch, double t) { p->ch[ch].req = t; arek_paula_mark(p, ch); }

/* Plan the channel's slots up to the end of the frame from its state (unchanged until the next register write): mark them
 * ahead so a blit does not take them; the channel's old planned slots after `from` are freed first. */
static inline void arek_paula_predict(ArekPaula *p, int ch, double from) {
    ArekBus *b = p->bus; uint8_t code = (uint8_t)(AREK_BUS_AUDIO + ch);
    double fend = p->frame_base + (double)b->lines * b->hpos;
    long k0 = (long)(from - p->frame_base) + 1; if (k0 < 0) k0 = 0;
    for (long k = k0; k < (long)b->lines * b->hpos; k++) if (b->own[k] == code) b->own[k] = 0;
    ArekPaulaChan c = p->ch[ch];
    for (int guard = 0; guard < 100000; guard++) {
        double tf = c.req >= 0 ? arek_paula_slot(p, ch, c.req) : 1e300;
        double tb = ((c.on || c.drain) && c.nbyte >= 0) ? c.nbyte : 1e300;
        if (tf >= fend && tb >= fend) break;
        if (tf <= tb) {
            double rel = tf - p->frame_base; if (rel >= 0) arek_bus_mark(b, (uint32_t)rel, code);
            c.req = -1; if (!c.on) continue;
            if (c.st == 1) { c.st = 2; c.req = tf; }
            else if (c.st == 2) { c.st = 3; c.bcount = 0; c.nbyte = tf + (c.per ? c.per : 0x10000); c.req = tf; }
        } else { c.bcount++; if (c.drain) { c.drain = 0; c.nbyte = -1; continue; } if (c.bcount % 2 == 0) c.req = tb; c.nbyte = tb + (c.per ? c.per : 0x10000); }
    }
}

static inline void arek_paula_init(ArekPaula *p, ArekBus *b, arek_paula_sample_fn cb, void *ctx) {
    for (int ch = 0; ch < 4; ch++) { ArekPaulaChan *c = &p->ch[ch]; c->on = c->st = 0; c->req = c->nbyte = -1; c->bcount = 0;
        c->lc = c->ptr = 0; c->len = c->lenctr = c->per = c->vol = c->vol_latch = 0; c->hold = c->out = c->first = 0; c->sample = 0;
        c->en_hi = c->en_lo = 0; c->drain = 0; }
    p->bus = b; p->frame_base = 0; p->fetches = 0; p->sample_cb = cb; p->ctx = ctx;
}

/* A new frame (after arek_bus_frame): base = absolute time of its slot 0; the planned slots of every channel go into the new map. */
static inline void arek_paula_frame(ArekPaula *p, double base) {
    p->frame_base = base;
    for (int ch = 0; ch < 4; ch++) arek_paula_predict(p, ch, base - 1);
}

static inline void arek_paula_byte(ArekPaula *p, int ch, double t) {   /* the byte whose turn it is; output only once per word */
    ArekPaulaChan *c = &p->ch[ch];
    int hi = c->bcount % 2 == 0;
    c->sample = (int8_t)(hi ? (c->out >> 8) : (c->out & 0xff));
    if (hi ? !c->en_hi : !c->en_lo) return;
    if (hi) c->en_hi = 0; else c->en_lo = 0;
    if (p->sample_cb) p->sample_cb(p->ctx, ch, t, c->sample * c->vol);
}

/* The channels' events up to absolute time t (inclusive): word fetches in their slots, output bytes. */
static inline void arek_paula_run(ArekPaula *p, double t) {
    for (int ch = 0; ch < 4; ch++) {
        ArekPaulaChan *c = &p->ch[ch];
        for (;;) {
            double tf = c->req >= 0 ? arek_paula_slot(p, ch, c->req) : 1e300;
            double tb = ((c->on || c->drain) && c->nbyte >= 0) ? c->nbyte : 1e300;
            double nx = tf < tb ? tf : tb;
            if (nx > t) break;
            if (tf <= tb) {                                   /* the DMA word (AUDxDAT): enables one high and one low byte */
                c->req = -1; p->fetches++;
                uint16_t w = p->bus->rd16(p->bus->ctx, c->ptr & p->bus->chipmask);
                c->ptr += 2; if (--c->lenctr == 0) { c->ptr = c->lc; c->lenctr = c->len; }
                c->hold = w; c->en_hi = c->en_lo = 1;
                if (!c->on) continue;                         /* served after DMA off: nothing more */
                if (c->st == 1) { c->st = 2; c->first = w; c->ptr = c->lc; c->lenctr = c->len; arek_paula_request(p, ch, tf); }
                else if (c->st == 2) { c->st = 3; c->out = w; c->bcount = 0; c->vol = c->vol_latch; arek_paula_byte(p, ch, tf); c->nbyte = tf + (c->per ? c->per : 0x10000); arek_paula_request(p, ch, tf); }
            } else {                                          /* the next output byte */
                c->bcount++;
                if (c->drain) {                               /* the low byte after DMA off, then the channel stops */
                    arek_paula_byte(p, ch, tb); c->drain = 0; c->nbyte = -1; continue;
                }
                if (c->bcount % 2 == 0) { c->out = c->hold; c->vol = c->vol_latch; arek_paula_request(p, ch, tb); }
                arek_paula_byte(p, ch, tb);
                c->nbyte = tb + (c->per ? c->per : 0x10000);
            }
        }
    }
}

/* A write to a Paula register at absolute time t: off = $A0-$DE (AUDxLCH/LCL/LEN/PER/VOL) or $96 (DMACON, audio bits 0-3). */
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
        }
    } else if (off == 0x096) {
        for (int ch = 0; ch < 4; ch++) if (v & (1 << ch)) {
            ArekPaulaChan *c = &p->ch[ch];
            if (v & 0x8000) { if (!c->on) { c->on = 1; c->st = 1; c->drain = 0; c->ptr = c->lc; c->lenctr = c->len; c->nbyte = -1; if (c->req < 0) arek_paula_request(p, ch, t); } }
            else if (c->on) { c->on = 0; c->drain = (c->st == 3 && c->nbyte >= 0 && c->bcount % 2 == 0); c->st = 0; if (!c->drain) c->nbyte = -1; }
            arek_paula_predict(p, ch, t);
        }
    }
}
#endif
