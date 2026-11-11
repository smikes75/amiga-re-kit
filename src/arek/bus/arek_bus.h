/* arek_bus.h - model sbernice Amigy (OCS/ECS, PAL i NTSC) po DMA slotech pro rekompilovane hry (cesta B kitu amiga-re-kit).
 *
 * Mapa vlastniku slotu snimku (obnova, zvuk, bitplany, sprity, copper, blitter, procesor), blitter po taktech, procesor podle pristupu
 * instrukci na sbernici. Bez hernich dat: vse, co patri hre (tabulky instrukci, kdy se vola preruseni, model Pauly), dela volajici.
 * Kody vlastniku jako bus log kitu (VAHL_BUSLOG): 0 volno, 1 procesor, 2 obnova, 4-7 zvuk, 8-15 bitplan, 16-23 sprite, 24 copper,
 * 25 blitter, 26 blokovano (copper v taktu 0xE0).
 *
 * Cas = takty CCK od zacatku snimku (radek * hpos + takt), double: procesor pocita interni cykly po polovinach taktu.
 * Funkce, ktere posouvaji cas procesoru, dostanou jeho dosavadni cas a vrati novy (volajici drzi svuj cas sam).
 *
 * Geometrie (zmereno proti VAHL_BUSLOG vAmiga 899da5d, docs/BUS.md kitu): PAL radek 227 taktu (vAmiga hCnt bez LOL; pole bus logu ma
 * 228 polozek, polozka 227 je v PAL vzdy 0), snimek 312 (kratky, LOF 0) nebo 313 radku (dlouhy, LOF 1). NTSC (radky 227/228 stridave
 * podle LOL, 262/263 radku) model zatim nedela: hpos je pevny po celou dobu behu.
 *
 * Soubory: arek_bus.c (procesor, instrukce, API), arek_bus_vamiga.c (mapa DMA snimku vcetne automatu copperu a mikroprogramy blitru,
 * odvozeno z vAmiga, Dirk W. Hoffmann, MPL-2.0). Lze prelozit samostatne nebo vlozit do jednoho prekladu (#include "arek_bus.c").
 */
#ifndef AREK_BUS_H
#define AREK_BUS_H
#include <stdint.h>

#define AREK_BUS_FREE 0
#define AREK_BUS_CPU 1
#define AREK_BUS_REFRESH 2
#define AREK_BUS_AUDIO 4       /* + kanal 0-3 */
#define AREK_BUS_BITPLANE 8    /* + plan 0-5 */
#define AREK_BUS_SPRITE 16     /* + sprite 0-7 */
#define AREK_BUS_COPPER 24
#define AREK_BUS_BLITTER 25
#define AREK_BUS_BLOCKED 26

typedef uint16_t (*arek_bus_rd16_fn)(void *ctx, uint32_t addr);   /* cteni chip RAM bez sbernice (copper list, POS/CTL spritu) */

/* Stav modelu. Volajici ho drzi (staticky nebo v halde); pole oznacena "cte volajici" smi cist, ostatni jsou vnitrni. */
typedef struct ArekBus {
    int hpos;                  /* takty na radek (PAL 227) */
    int lines;                 /* radku snimku (PAL 312 / 313) */
    int maxlines;              /* kapacita mapy v radcich (>= lines; radky za koncem snimku drzi pristupy, ktere pretekly) */
    uint8_t *own;              /* cte volajici: own[radek * hpos + takt], maxlines * hpos bajtu; volajici do nej smi znacit sloty
                                  vlastnich modelu DMA (zvuk: arek_bus_mark) */
    uint16_t *regs;            /* registry volajiciho ($DFF000 + 2 i): model cte DMACON, BPLCON0, DDF, DIW, sprity, COP1LC, BLTxxx
                                  a zapisy copperu do DMACON propisuje i sem (jeden registr pro blitter i DMACONR) */
    arek_bus_rd16_fn rd16; void *ctx;
    uint32_t chipmask;         /* maska adres DMA (512 KB chip RAM: 0x7fffe) */
    int cdang;                 /* 1.0.47: COPCON bit 1 as the CPU last wrote it; -1 = not written in this run (a capture does not carry it) */
    uint32_t cop_default;      /* copper list, dokud COP1LC neni zapsany (start ze stavu, kdy registry nejsou v RAM); 0 = zadny */
    int slotoff;               /* slot procesoru: takty po zacatku sbernicoveho cyklu (Moira SYNC: 1) */
    double cop_lat;            /* latence preruseni copperu v taktech (pricte se k casu zapisu INTREQ) */
    double cop_int;            /* cte volajici: cas prvniho zapisu INTREQ SET|COPER copperem v tomto snimku (+ cop_lat), -1 = zadny */
    /* 1.0.6 (Turrican II KIT-GAPS 7): KAZDY zapis copperu MOVE INTREQ,SET|bity v tomto snimku - cas (+ cop_lat) a bity & 0x7fff
     * (uvod Turricanu II zveda RBF $0800 = uroven 5 copperem); cop_int = cas prvniho s bitem COPER (jako dosud) */
#define AREK_BUS_COPIRQ 8
    struct { double t; uint16_t bits; } cop_irq[AREK_BUS_COPIRQ]; int cop_irq_n;
    uint32_t cpu_n, wait_n;    /* cte volajici: pristupy procesoru a takty cekani v tomto snimku */
    /* vnitrni: registry, ktere copper psal minuly snimek (plati na zacatku dalsiho), blitter, rozpracovana instrukce */
    uint16_t copr[0x100]; uint8_t copw[0x100];
    double last_t0, prev_t0; long last_slot, prev_slot;      /* 1.0.51: the last CPU access - when it was asked for and the slot it took (arek_bus_undo_last), and the one before */
    /* 1.0.52 (SWIV KIT-GAPS 9): the CPU's writes to the registers that steer DMA, with their slots, and the registers the
     * frame's map started from - arek_bus_cpu_reg works the rest of the frame out again (journal_on: the host's switch) */
    uint16_t regs0[0x100]; int jn, journal_on, remap; uint32_t jt[32]; uint16_t jreg[32], jval[32];
    double acc_t[4]; uint32_t poll_back;  /* 1.0.53: when the last four CPU accesses were asked for (0 = the last); the instruction samples its interrupt level poll_back cycles before its last (timing.bus_poll) */
    /* 1.0.55: the instruction's bus pattern (arek.m68k.buspat: Moira's order of idle clocks and bus cycles, and where the
     * interrupt level is sampled) - arek_bus_pat_begin; the accesses of the translation take its data cycles in order */
    void (*ahead)(struct ArekBus *b, uint32_t slot); uint32_t ahead_to;   /* 1.0.56: the host marks its DMA slots up to past `slot` and sets ahead_to (the slot from which it wants to be asked again) */
    int unserved; long carry_rel;                        /* 1.0.56: accesses that found no slot before the cap past the frame's end (arek_bus_frame_carry) */
    int pat_off;                         /* the host's switch: 1 = do not use the patterns (HOST_BUS_PAT=0) */
    const uint8_t *pat; int pat_on, pat_n, pat_i, pat_pj, pat_pd, pat_acc, pat_v, poll_valid; double pat_poll;
    int order2;                          /* 1.0.53: honour the bus table's fourth byte (the host's timing model) */
    uint32_t in_defer;                   /* 1.0.53: the instruction's last prefetch is still to come - 1 at its end, 2 / 3 before the data access after one / two (timing.bus_order) */
    int cpu_fast;                        /* 1.0.51: a faster CPU (the host moves its time back): a slot the CPU itself took is free for it */
    int last_wait;                       /* 1.0.50: colour clocks the last CPU access waited for a free slot (the host's IPL sample point) */
    struct { int on, busy, phase, pc, lockD; uint32_t left, bt; const uint8_t *prog; } bl;
    int bls;
    uint32_t in_n, in_l, in_da, in_pre, in_tail;   /* in_tail (1.0.47): accesses the instruction makes at its END, after its remaining internal clocks */
} ArekBus;

/* Zalozeni: own = pole maxlines * hpos bajtu volajiciho, regs = registry volajiciho (0x100 slov), rd16 + ctx = cteni chip RAM. */
void arek_bus_init(ArekBus *b, int hpos, int lines, int maxlines, uint8_t *own, uint16_t *regs, arek_bus_rd16_fn rd16, void *ctx);

/* Zacatek snimku (paprsek na radku 0, takt 0): blitter dobehne do konce predchoziho snimku a jeho zbytek se prenese, pak pevna mapa
 * DMA noveho snimku (obnova 1/3/5/226, sprity, bitplany, copper po taktech z copper listu COP1LC). lines = radku noveho snimku.
 * Sloty zvuku si volajici dopise sam (arek_bus_mark), protoze zavisi na jeho modelu Pauly. Vynuluje cpu_n, wait_n, cop_int. */
void arek_bus_frame(ArekBus *b, int lines);
double arek_bus_frame_carry(ArekBus *b, double t);   /* 1.0.56: after arek_bus_frame - the accesses that found no slot before the frame rolled */

/* Procesor. arek_bus_insn: zacatek instrukce (dokonci predchozi), pre = internich polotaktu pred pristupy, accesses = pristupy, ktere
 * instrukce udela hned (prefetch); cycles = celkove cykly 68000 (zbytek po pristupech se pricte jako interni cykly pri dokonceni).
 * arek_bus_data: datovy pristup do chip sbernice (ceka na volny slot). arek_bus_slow: pristup mimo chip sbernici (CIA, E takt):
 * zapocita se do pristupu instrukce, trva cck taktu bez slotu. arek_bus_insn_end: dokonceni instrukce (pred prerusenim, mimo tabulku). */
double arek_bus_insn(ArekBus *b, double t, uint32_t cycles, uint32_t accesses, uint32_t pre);
double arek_bus_data(ArekBus *b, double t);
double arek_bus_slow(ArekBus *b, double t, double cck);
double arek_bus_insn_end(ArekBus *b, double t);
double arek_bus_access(ArekBus *b, double t);   /* jeden pristup procesoru (pouzivaji predchozi; vrati cas po pristupu) */

/* Blitter: zapis BLTSIZE procesorem (pristup uz zapocitany, t = cas procesoru po nem). Vraci cas procesoru (rezim car zatim jen
 * odhadem h * 8 taktu procesoru, blitter se nespusti). arek_bus_bbusy: BBUSY v taktu cteni DMACONR procesorem. */
/* 1.0.51: take the last CPU access back (its slot is free again) and return the time it was asked for - for an access the
 * 68000 makes AFTER something the model has not done yet (the prefetch behind a CIA access); the caller makes it again. Two calls take the last two back. */
double arek_bus_undo_last(ArekBus *b);
/* 1.0.55: an instruction by its pattern p = { n items, poll cycle (255: before the first), poll delta, items } with
 * items 1-127 = clocks without the bus, 0x80 = a read of the program stream, 0x81 = a data access, 0xfe = the clocks
 * that depend on the data (clocks - everything else). Runs up to the first data access; arek_bus_data / arek_bus_slow
 * take the data cycles in order, arek_bus_insn_end runs what is left. After the end b->pat_poll is the time the
 * instruction sampled the interrupt level (b->poll_valid). */
double arek_bus_pat_begin(ArekBus *b, double t, const uint8_t *p, uint32_t clocks);
double arek_bus_blit(ArekBus *b, double t, uint16_t con0, uint16_t con1, uint16_t size);
int arek_bus_bbusy(ArekBus *b, double t);

/* Slot DMA jineho modelu (zvuk): obsadi takt k, je-li volny. */
/* a CPU write to a custom register (G50, Alien Breed II): it is later than the Copper's write of the same register, so the
 * next frame's map starts from the CPU's value (regs), not the Copper's (copr) - e.g. COP1LC set by the CPU after a list
 * that wrote COP1LC to itself */
static inline void arek_bus_cpu_write(ArekBus *b, uint32_t off) { b->copw[(off & 0x1fe) >> 1] = 0; }
/* 1.0.52: a CPU write of v to custom register off at slot now (the frame's colour clock): DMACON, DIWSTRT/STOP,
 * DDFSTRT/STOP, BPLCON0, COPJMP1/2 take effect in THIS frame's map from that slot on (the Copper switched on in the
 * middle of a frame runs from where its pointer stood, bitplane DMA starts on the next line...). Returns 1 when the
 * map was worked out again. Needs journal_on. */
int arek_bus_cpu_reg(ArekBus *b, uint32_t off, uint16_t v, uint32_t now);
static inline void arek_bus_mark(ArekBus *b, uint32_t k, uint8_t who) { if (k < (uint32_t)(b->maxlines * b->hpos) && !b->own[k]) b->own[k] = who; }

/* vnitrni (arek_bus_vamiga.c) */
void arek_bus_frame_map(ArekBus *b);
void arek_bus_blt_advance(ArekBus *b, uint32_t t);
void arek_bus_blt_start(ArekBus *b, uint32_t t0, uint16_t con0, uint32_t words);
#endif
