/* arek_bus_vamiga.c - cast modelu sbernice odvozena z vAmiga (https://github.com/dirkwhoffmann/vAmiga, verze 899da5d):
 * poradi slotu bitplanu (Agnus SequencerBpl), stavovy automat copperu (Copper/CopperEvents: cteni jen v sudem volnem taktu, WAIT
 * s komparatorem h + 2, blokovany takt 0xE0) a mikroprogramy blitru SlowBlitter (Blitter/SlowBlitter.cpp).
 *
 * Odvozeno z vAmiga, Copyright (C) Dirk W. Hoffmann. Licence: Mozilla Public License 2.0 (MPL-2.0), https://mozilla.org/MPL/2.0/.
 * Tento soubor je pod MPL-2.0; zbytek modelu (arek_bus.c, arek_bus.h) ne. Kalibrace a overeni: README.md.
 */
#include <string.h>
#include "arek_bus.h"

/* plan 1-6 ve skupine 8 taktu lores (vAmiga SequencerBpl) */
static const uint8_t LORES_SLOT8[6] = { 7, 3, 5, 1, 6, 2 };
typedef struct { uint32_t ptr; int vs, ve, st; } BSpr;   /* st: 0 ceka na POS/CTL (radek 25), 1 ceka na vstart, 2 data, 3 konec */

/* Pevne DMA snimku: obnova, sprity, bitplany, copper. Copper: kazdy krok ceka na volnou sbernici, FETCH/REQ jen v sudem taktu,
 * dalsi krok za 2 takty (vAmiga CopperEvents). Registry, ktere copper zapsal minuly snimek, plati na zacatku dalsiho (copr/copw). */
void arek_bus_frame_map(ArekBus *b) {
    const uint32_t H = (uint32_t)b->hpos, NL = (uint32_t)(b->lines < b->maxlines ? b->lines : b->maxlines);
    memset(b->own, 0, (size_t)b->maxlines * H); b->cop_int = -1;   /* cela mapa: radky za koncem snimku drzi pristupy, ktere pretekly (jinak by zustaly obsazene) */
    uint16_t R[0x100]; memcpy(R, b->regs, sizeof R);
    for (int i = 0; i < 0x100; i++) if (b->copw[i]) R[i] = b->copr[i];   /* registry, ktere copper psal minuly snimek: hodnota copperu (DIW, BPLCON, DDF, sprity) */
    memset(b->copw, 0, sizeof b->copw);
    uint32_t cp = ((uint32_t)R[0x080 >> 1] << 16 | R[0x082 >> 1]) & b->chipmask; if (!cp) cp = b->cop_default;   /* COP1LC jeste nezapsany (start ze stavu) */
    int cst = 1, cnext = 0; uint16_t c1 = 0, c2 = 0; uint32_t cwait = 0, cmask = 0;   /* copper: 1 FETCH, 2 MOVE, 3 WAIT_OR_SKIP, 4 WAIT1, 5 WAIT2, 6 cekani, 7 SKIP1, 8 SKIP2, 0 stop */
    int vflop = 0; BSpr S[8]; for (int n = 0; n < 8; n++) { S[n].ptr = ((uint32_t)R[(0x120 >> 1) + 2 * n] << 16 | R[(0x122 >> 1) + 2 * n]) & b->chipmask; S[n].st = 0; S[n].vs = S[n].ve = -1; }
    for (uint32_t v = 0; v < NL; v++) {
        uint8_t *L = b->own + v * H;
        L[1] = L[3] = L[5] = L[H - 1] = 2;   /* obnova: PAL 1/3/5/226 */
        { int s = R[0x08e >> 1] >> 8, e = (R[0x090 >> 1] >> 8) | ((R[0x090 >> 1] & 0x8000) ? 0 : 0x100); if ((int)v == e) vflop = 0; if ((int)v == s) vflop = 1; }
        uint16_t dma = R[0x096 >> 1]; int den = dma & 0x200;
        /* sprity: radek 25 nacte POS/CTL, data od vstart do vstop - 1, na vstop dalsi POS/CTL */
        if (den && (dma & 0x20) && v >= 25 && v < NL - 1) for (int n = 0; n < 8; n++) {
            BSpr *p = &S[n]; int fetch = 0;
            if (p->st == 0 && v == 25) fetch = 1;
            else if (p->st == 2 && (int)v == p->ve) fetch = 1;
            else if ((p->st == 1 || p->st == 2) && (int)v >= p->vs && (int)v < p->ve) { p->st = 2; L[0x15 + 4 * n] = L[0x17 + 4 * n] = 16 + n; p->ptr += 4; continue; }
            if (fetch) {
                uint32_t pos = b->rd16(b->ctx, p->ptr), ctl = b->rd16(b->ctx, p->ptr + 2); p->ptr += 4; L[0x15 + 4 * n] = L[0x17 + 4 * n] = 16 + n;
                p->vs = (pos >> 8) | ((ctl & 4) << 6); p->ve = (ctl >> 8) | ((ctl & 2) << 7); p->st = (pos | ctl) ? 1 : 3;
                if (p->st == 1 && p->vs <= (int)v) p->st = 3;
            }
        }
        int bdone = 0;
        for (int h = 0; h < (int)H; h++) {
            /* bitplany radku podle registru na zacatku nacitani (DDFSTRT) */
            int ddfs = R[0x092 >> 1] & 0xfc;
            if (v || h) {                    /* rychlost: preskocit takty, kdy se nic nedeje (bitplany jeste ne, copper ceka nebo stoji) */
                int nh = (int)H; if (!bdone && ddfs >= h && ddfs < nh) nh = ddfs;
                if (cst != 0 && den && (dma & 0x80)) { int c = cnext - (int)(v * H); if (c < h) c = h; if (c < nh) nh = c; }
                if (nh > h) { h = nh - 1; continue; }
            }
            if (!bdone && h == ddfs) {
                bdone = 1; uint16_t c0 = R[0x100 >> 1]; int np = (c0 >> 12) & 7, hires = c0 & 0x8000;
                if (den && (dma & 0x100) && vflop && np) {
                    int ddfe = R[0x094 >> 1] & 0xfc, groups = ((ddfe - ddfs) >> 3) + 1;
                    for (int k = 0; k < groups; k++) for (int q = 0; q < 8; q++) {
                        int hh = ddfs + 8 * k + q, p = -1;
                        if (hires) { static const int8_t HP[8] = { 3, 1, 2, 0, 3, 1, 2, 0 }; if (HP[q] < np) p = HP[q]; }
                        else for (int i = 0; i < np && i < 6; i++) if (LORES_SLOT8[i] == q) p = i;
                        if (p >= 0 && hh < (int)H) L[hh] = 8 + p;
                    }
                }
            }
            /* copper (vAmiga CopperEvents): kazdy krok ceka na volnou sbernici, FETCH/REQ jen v sudem taktu, dalsi krok za 2 takty */
            if (v == 0 && h == 0 && den && (dma & 0x80)) { L[0] = 24; cst = 1; cnext = 2; continue; }   /* COP_VBLANK: copper list 1 */
            if (!(den && (dma & 0x80)) || cst == 0 || (int)(v * H + h) < cnext) continue;
            int freeb = (L[h] == 0);
            if (h == 0xe0 && freeb && cst != 6) { L[h] = 26; freeb = 0; }
            switch (cst) {
            case 1:   /* FETCH */
                if (!freeb) { cnext = v * H + h + 1; break; }
                L[h] = 24; c1 = b->rd16(b->ctx, cp); cp += 2; cst = (c1 & 1) ? 3 : 2; cnext = v * H + h + 2; break;
            case 2:   /* MOVE */
                if (!freeb) { cnext = v * H + h + 1; break; }
                L[h] = 24; c2 = b->rd16(b->ctx, cp); cp += 2; cst = 1; cnext = v * H + h + 2;
                { uint32_t reg = c1 & 0x1fe;
                  if (reg == 0x088) { cp = ((uint32_t)R[0x080 >> 1] << 16 | R[0x082 >> 1]) & b->chipmask; }
                  else if (reg == 0x09c) { if ((c2 & 0x8010) == 0x8010 && b->cop_int < 0) b->cop_int = v * H + h + b->cop_lat;   /* INTREQ SET|COPER; zda preruseni dojde, rozhodne volajici */ }
                  else if (reg == 0x096) { if (c2 & 0x8000) R[0x096 >> 1] |= c2 & 0x7fff; else R[0x096 >> 1] &= ~c2; dma = R[0x096 >> 1]; den = dma & 0x200;
                      if (c2 & 0x8000) b->regs[0x096 >> 1] |= c2 & 0x7fff; else b->regs[0x096 >> 1] &= ~c2; }   /* DMACON je jeden registr: zapis copperu plati i pro blitter a cteni DMACONR */
                  else if (reg >= 0x120 && reg < 0x140) { R[reg >> 1] = c2; int n = (reg - 0x120) >> 2; S[n].ptr = ((uint32_t)R[(0x120 >> 1) + 2 * n] << 16 | R[(0x122 >> 1) + 2 * n]) & b->chipmask; }
                  else if (reg >= 0x140 && reg < 0x180 && !(reg & 4)) {   /* SPRxPOS/SPRxCTL: Agnus z nich bere okno DMA spritu */
                      R[reg >> 1] = c2; int n = (reg - 0x140) >> 3; uint32_t pos = R[(0x140 >> 1) + 4 * n], ctl = R[(0x142 >> 1) + 4 * n];
                      S[n].vs = (pos >> 8) | ((ctl & 4) << 6); S[n].ve = (ctl >> 8) | ((ctl & 2) << 7); S[n].st = 1; }
                  else R[reg >> 1] = c2;
                  if (reg < 0x200) { b->copr[reg >> 1] = R[reg >> 1]; b->copw[reg >> 1] = 1; } }
                break;
            case 3:   /* WAIT_OR_SKIP: druhe slovo */
                if (!freeb) { cnext = v * H + h + 1; break; }
                L[h] = 24; c2 = b->rd16(b->ctx, cp); cp += 2; cst = (c2 & 1) ? 7 : 4; cnext = v * H + h + 2; break;
            case 4: if (!freeb) { cnext = v * H + h + 1; break; } cst = 5; cnext = v * H + h + 2; break;
            case 7: if (!freeb) { cnext = v * H + h + 1; break; } cst = 8; cnext = v * H + h + 2; break;
            case 8: if (!freeb) { cnext = v * H + h + 1; break; } cst = 1; cnext = v * H + h + 2; break;   /* SKIP: bez preskoceni (hra ho v levelu nepouziva) */
            case 5:   /* WAIT2: najdi takt, kdy komparator projde (h + 2 v masce); 0xFFFF/FFFE = konec */
                if (!freeb) { cnext = v * H + h + 1; break; }
                { cwait = ((c1 >> 8) << 8) | (c1 & 0xfe); cmask = 0x8000 | ((c2 & 0x7f00)) | (c2 & 0xfe);
                  int found = -1;
                  for (uint32_t t = v * H + h; t < NL * H && found < 0; t++) {
                      uint32_t vv = t / H, hh = t % H, vb = vv & 0xff;
                      uint32_t vm = (cmask >> 8) & 0xff, vp = (cwait >> 8) & 0xff;
                      if ((vb & vm) < (vp & vm)) { t = vv * H + H - 1; continue; }   /* radek nevyhovuje: dalsi radek */
                      if ((vb & vm) > (vp & vm)) { found = (int)t; break; }
                      uint32_t hc = hh < 0xe0 ? hh + 2 : hh - 0xe0;
                      if ((hc & cmask & 0xff) >= (cwait & 0xff & cmask)) found = (int)t;
                  }
                  if (found < 0) { cst = 0; break; }
                  if (found == (int)(v * H + h)) { cst = 1; cnext = found + 2; } else { cst = 6; cnext = found; } }
                break;
            case 6:   /* WAKEUP: volna sbernice a sudy takt, pak FETCH */
                if (!freeb || (h & 1)) { cnext = v * H + h + 1; break; }
                cst = 1; cnext = v * H + h + 2; break;   /* vAmiga: COP_WAKEUP -> schedule(COP_FETCH), +2 */
            }
        }
    }
}
/* ---- blitter po taktech (mikroprogramy SlowBlitter vAmigy, Blitter/SlowBlitter.cpp: 16 kombinaci kanalu, bez rezimu car a fill) ---- */
#define B_BUS 1
#define B_IDLE 2
#define B_WD 4
#define B_REP 8
#define B_DONE 16
static const uint8_t BPROG[16][6] = {
    { B_IDLE, B_IDLE | B_REP, 0, B_DONE, B_DONE, B_DONE },
    { B_IDLE, B_WD | B_REP, 0, B_WD | B_DONE, B_DONE, B_DONE },
    { B_IDLE, B_BUS | B_REP, 0, B_DONE, B_DONE, B_DONE },
    { B_IDLE, B_BUS, B_WD | B_REP, 0, B_WD | B_DONE, B_DONE },
    { B_IDLE, B_BUS, B_IDLE | B_REP, 0, B_DONE, B_DONE },
    { B_IDLE, B_BUS, B_WD | B_REP, 0, B_WD | B_DONE, B_DONE },
    { B_IDLE, B_BUS, B_BUS | B_REP, 0, B_DONE, B_DONE },
    { B_IDLE, B_BUS, B_BUS, B_WD | B_REP, 0, B_WD | B_DONE },
    { B_BUS, B_IDLE | B_REP, 0, B_DONE, B_DONE, B_DONE },
    { B_BUS, B_WD | B_REP, 0, B_WD | B_DONE, B_DONE, B_DONE },
    { B_BUS, B_BUS | B_REP, 0, B_DONE, B_DONE, B_DONE },
    { B_BUS, B_BUS, B_WD | B_REP, 0, B_WD | B_DONE, B_DONE },
    { B_BUS, B_BUS, B_IDLE | B_REP, 0, B_DONE, B_DONE },
    { B_BUS, B_BUS, B_WD | B_REP, 0, B_WD | B_DONE, B_DONE },
    { B_BUS, B_BUS, B_BUS | B_REP, 0, B_DONE, B_DONE },
    { B_BUS, B_BUS, B_BUS, B_WD | B_REP, 0, B_WD | B_DONE },
};
/* stav blitru (ArekBus.bl): busy = BBUSY (maze se pri poslednim REPEAT, pred zapisem D), phase 1 STRT1, 2 STRT2, 3 bezi;
 * bls: procesor ceka 2 takty -> blitter bez BLTPRI ustoupi */
void arek_bus_blt_advance(ArekBus *b, uint32_t t) {     /* udalosti blitru v taktech bl.bt..t (vcetne) */
    const uint32_t cap = (uint32_t)(b->maxlines * b->hpos); uint16_t *CREG = b->regs;
    while (b->bl.on && b->bl.bt <= t) {
        uint32_t c = b->bl.bt++; uint8_t o = c < cap ? b->own[c] : 0; int fr = (o == 0) && !(b->bls && !(CREG[0x096 >> 1] & 0x400));
        if (!(CREG[0x096 >> 1] & 0x200) || !(CREG[0x096 >> 1] & 0x40)) fr = 0;
        if (b->bl.phase == 1) { if (fr) b->bl.phase = 2; continue; }
        if (b->bl.phase == 2) { if (fr) b->bl.phase = 3; continue; }
        uint8_t in = b->bl.prog[b->bl.pc]; int bus = 0, idle = 0;
        if (in & B_WD) { bus = !b->bl.lockD; idle = b->bl.lockD; } else { bus = in & B_BUS; idle = in & B_IDLE; }
        if ((bus || idle) && !fr) continue;
        if (bus && c < cap) b->own[c] = 25;
        b->bl.pc++;
        if (in & B_REP) { b->bl.lockD = 0; if (--b->bl.left) b->bl.pc = 0; else b->bl.busy = 0; }
        if (in & B_DONE) { b->bl.on = 0; break; }
    }
}
void arek_bus_blt_start(ArekBus *b, uint32_t t0, uint16_t con0, uint32_t words) {   /* t0 = takt zapisu BLTSIZE; registr plati o takt pozdeji */
    b->bl.on = 1; b->bl.busy = 1; b->bl.phase = 1; b->bl.pc = 0; b->bl.lockD = 1; b->bl.left = words; b->bl.prog = BPROG[(con0 >> 8) & 15]; b->bl.bt = t0 + 2;
}
