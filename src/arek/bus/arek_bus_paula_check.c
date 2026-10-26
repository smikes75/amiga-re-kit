/* arek_bus_paula_check.c - the Paula model (arek_bus_paula.h) against a recorded run (arek selftest audio): the register
 * writes of VAHL_REGLOG are replayed into the model, its audio slots are compared with the audio owners of the bus log
 * (ABBL) frame by frame, and its output bytes with the samples of VAHL_AUDLOG.
 *   arek_bus_paula_check LOG.abbl WRITES.txt [SAMPLES.txt | -] [FROM_FRAME] [RAM.bin]
 * WRITES.txt: lines `t off value` (t = CCK relative to the log's first frame start, may be negative; off = $96 or $A0-$DE),
 * sorted by t. SAMPLES.txt: lines `t ch value` (the log's output samples, byte * volume). FROM_FRAME: first frame of the
 * log to compare (default 0). RAM.bin: the chip RAM the samples are fetched from (zeros without it). Output: per channel
 * the slots that agree / only in the log / only in the model, the samples
 * that agree exactly and within 1 CCK; exit 0 when no slot disagrees in the compared frames. No game data. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "arek_bus.h"
#include "arek_bus_paula.h"

static uint8_t RAM[0x80000];
static uint16_t rd16(void *c, uint32_t a) { (void)c; a &= 0x7fffe; return (uint16_t)((RAM[a] << 8) | RAM[a + 1]); }

typedef struct { double t; int ch, v; } Sample;
static Sample *SM; static long SN = 0, SCAP = 0;
static FILE *DIFF = 0;             /* $AREK_PAULA_DIFF: every sample that differs (only-log / only-model / value), for the analysis */
static void on_sample(void *ctx, int ch, double t, int value) {
    (void)ctx;
    if (SN == SCAP) { SCAP = SCAP ? 2 * SCAP : 65536; SM = realloc(SM, (size_t)SCAP * sizeof *SM); }
    SM[SN].t = t; SM[SN].ch = ch; SM[SN].v = value; SN++;
}
static int cmp_sample(const void *a, const void *b) {
    const Sample *x = a, *y = b;
    if (x->ch != y->ch) return x->ch - y->ch;
    return x->t < y->t ? -1 : x->t > y->t ? 1 : x->v - y->v;
}

int main(int argc, char **argv) {
    if (argc < 3) { fprintf(stderr, "arek_bus_paula_check LOG.abbl WRITES.txt [SAMPLES.txt | -] [FROM_FRAME] [RAM.bin]\n"); return 2; }
    FILE *f = fopen(argv[1], "rb"); if (!f) { perror(argv[1]); return 2; }
    char magic[4]; uint32_t hd[5];
    if (fread(magic, 1, 4, f) != 4 || memcmp(magic, "ABBL", 4) || fread(hd, 4, 5, f) != 5) { fprintf(stderr, "not ABBL\n"); return 2; }
    uint32_t H = hd[0], NL = hd[1], NF = hd[3], FS = H * NL;
    uint8_t *maps = malloc((size_t)NF * FS);
    if (fread(maps, 1, (size_t)NF * FS, f) != (size_t)NF * FS) { fprintf(stderr, "short file\n"); return 2; }
    fclose(f);
    /* the writes */
    long WN = 0, WCAP = 1024; double *WT = malloc(WCAP * sizeof *WT); unsigned *WO = malloc(WCAP * sizeof *WO), *WV = malloc(WCAP * sizeof *WV);
    f = fopen(argv[2], "r"); if (!f) { perror(argv[2]); return 2; }
    { double t; unsigned o, v;
      while (fscanf(f, "%lf %x %x", &t, &o, &v) == 3) {
          if (WN == WCAP) { WCAP *= 2; WT = realloc(WT, WCAP * sizeof *WT); WO = realloc(WO, WCAP * sizeof *WO); WV = realloc(WV, WCAP * sizeof *WV); }
          WT[WN] = t; WO[WN] = o; WV[WN] = v; WN++; } }
    fclose(f);
    uint32_t from = argc > 4 ? (uint32_t)atoi(argv[4]) : 0;
    if (getenv("AREK_PAULA_DIFF")) DIFF = fopen(getenv("AREK_PAULA_DIFF"), "w");
    if (argc > 5) { f = fopen(argv[5], "rb"); if (!f) { perror(argv[5]); return 2; } if (fread(RAM, 1, sizeof RAM, f) == 0) { fprintf(stderr, "RAM?\n"); return 2; } fclose(f); }
    uint8_t *own = malloc(FS);
    static uint16_t regs[0x100];
    ArekBus B; arek_bus_init(&B, (int)H, (int)NL, (int)NL, own, regs, rd16, 0);
    ArekPaula P; arek_paula_init(&P, &B, on_sample, 0);
    long first_fr = 0;
    if (WN && WT[0] < 0) first_fr = (long)floor(WT[0] / FS);
    long ok[4] = { 0 }, only_log[4] = { 0 }, only_model[4] = { 0 }, logn[4] = { 0 }, modn[4] = { 0 };
    long w = 0;
    for (long fr = first_fr; fr < (long)NF; fr++) {
        arek_bus_frame(&B, (int)NL);                                   /* an empty map (no display DMA): refresh only */
        double base = (double)fr * FS;
        arek_paula_frame(&P, base);
        while (w < WN && WT[w] < base + FS) { arek_paula_write(&P, WT[w], WO[w], (uint16_t)WV[w]); w++; }
        arek_paula_run(&P, base + FS - 1e-9);
        if (fr < (long)from) continue;
        const uint8_t *m = maps + (size_t)fr * FS;
        for (uint32_t k = 0; k < FS; k++) {
            if (m[(k / H) * H] == 0xff) continue;                      /* a line the log did not record */
            int lc = (m[k] >= 4 && m[k] < 8) ? m[k] - 4 : -1, mc = (own[k] >= 4 && own[k] < 8) ? own[k] - 4 : -1;
            if (lc >= 0) logn[lc]++;
            if (mc >= 0) modn[mc]++;
            if (lc >= 0 && lc == mc) ok[lc]++;
            else { if (lc >= 0) only_log[lc]++; if (mc >= 0) only_model[mc]++; }
        }
    }
    long bad = 0;
    for (int ch = 0; ch < 4; ch++) {
        printf("slots ch%d: log %ld model %ld agree %ld only-log %ld only-model %ld\n", ch, logn[ch], modn[ch], ok[ch], only_log[ch], only_model[ch]);
        bad += only_log[ch] + only_model[ch];
    }
    printf("audio slots: agree %ld, disagree %ld (frames %u-%u)\n", ok[0] + ok[1] + ok[2] + ok[3], bad, from, NF ? NF - 1 : 0);
    if (argc > 3 && strcmp(argv[3], "-")) {                             /* the samples */
        long LN = 0, LCAP = 65536; Sample *LS = malloc(LCAP * sizeof *LS);
        f = fopen(argv[3], "r"); if (!f) { perror(argv[3]); return 2; }
        { double t; int ch, v;
          while (fscanf(f, "%lf %d %d", &t, &ch, &v) == 3) {
              if (t < (double)from * FS || t >= (double)NF * FS) continue;   /* only the frames the bus log covers */
              if (LN == LCAP) { LCAP *= 2; LS = realloc(LS, LCAP * sizeof *LS); }
              LS[LN].t = t; LS[LN].ch = ch; LS[LN].v = v; LN++; } }
        fclose(f);
        long MN = 0; for (long i = 0; i < SN; i++) if (SM[i].t >= (double)from * FS) SM[MN++] = SM[i];
        qsort(LS, LN, sizeof *LS, cmp_sample); qsort(SM, MN, sizeof *SM, cmp_sample);
        for (int ch = 0; ch < 4; ch++) {
            long ln = 0, mn = 0, exact = 0, near = 0, i = 0, j = 0;
            for (long k = 0; k < LN; k++) if (LS[k].ch == ch) ln++;
            for (long k = 0; k < MN; k++) if (SM[k].ch == ch) mn++;
            while (i < LN && LS[i].ch != ch) i++;
            while (j < MN && SM[j].ch != ch) j++;
            while (i < LN && j < MN && LS[i].ch == ch && SM[j].ch == ch) {   /* merge by time: exact / within 1 CCK and the same value */
                double d = SM[j].t - LS[i].t;
                if (d > 1.5) { if (DIFF) fprintf(DIFF, "only-log %d %.0f %d\n", ch, LS[i].t, LS[i].v); i++; }
                else if (d < -1.5) { if (DIFF) fprintf(DIFF, "only-model %d %.0f %d\n", ch, SM[j].t, SM[j].v); j++; }
                else { if (LS[i].v == SM[j].v) { if (fabs(d) < 0.5) exact++; else near++; } else if (DIFF) fprintf(DIFF, "value %d %.0f %d %d\n", ch, LS[i].t, LS[i].v, SM[j].v); i++; j++; }
            }
            printf("samples ch%d: log %ld model %ld exact %ld near %ld", ch, ln, mn, exact, near);
            for (long k = 0; k < LN; k++) if (LS[k].ch == ch) { printf("  first log %.0f %d", LS[k].t, LS[k].v); break; }
            for (long k = 0; k < MN; k++) if (SM[k].ch == ch) { printf("  model %.0f %d", SM[k].t, SM[k].v); break; }
            printf("\n");
        }
    }
    return bad ? 1 : 0;
}
