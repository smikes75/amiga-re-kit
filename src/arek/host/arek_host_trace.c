/* arek_host_trace.c - the translated game from a state of the original (arek host state) with inputs per frame; writes
 * records in the kit's trace format (VTR2) so `arek trace compare` and `arek parity` hold it against the original.
 *
 *   cc -O2 -I lib -DGAME_SRC='"game.c"' -DTICK_PC=0xc01c72u -DHOST_ENTRY=f_c01c72 -DHOST_L3=f_c13e1c \
 *      arek_host_trace.c arek_bus.c arek_bus_vamiga.c -lm -o host_trace
 *   host_trace STATE_DIR OUT.vtr FRAMES [INPUTS.txt] [--full] [--skip-stack N] [--own FILE] [--pclog FILE PCS.txt]
 *              [--reglog FILE] [--audlog FILE] [--shots PREFIX FIRST:LAST]
 * A record at every pass of TICK_PC outside an interrupt (the game's tick) and, with HOST_L3_PC, at every entry of the
 * level-3 handler; ranges 0:MEMSZ and SLOWBASE:SLOWSZ as FNV-1a 64 hashes (like --range ...h), with --full the bytes.
 * INPUTS: line k = the keys of frame k (R L U D F S, as arek fuzz writes them); line 0 applies from the start.
 * --skip-stack N: the slow RAM hash starts N bytes in (the stack below is not compared). --own: the slot map of every
 * frame (bus_compare). --pclog: the time of every pass of the listed pcs (per-instruction timing against the original's
 * breakpoints). --reglog / --audlog: the host's register writes and samples in the VAHL_REGLOG / VAHL_AUDLOG layouts
 * (arek parity). --shots: the picture of frames FIRST..LAST as PREFIX_frame.raw (716 x 285 RGB24). No game data. */
#include <setjmp.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "arek_host_pre.h"
#ifndef GAME_SRC
#error "define GAME_SRC (the translation, e.g. \"game.c\")"
#endif
#include GAME_SRC
#undef main
#include "arek_bus_glue.h"
#ifndef HOST_L3
#error "define HOST_L3 (the translated level-3 handler)"
#endif
#include "arek_host.h"
#ifndef TICK_PC
#error "define TICK_PC (the pc of the game's tick, e.g. 0xc01c72u)"
#endif
#ifndef HOST_ENTRY
#error "define HOST_ENTRY (the translated routine the run starts in, e.g. f_c01c72)"
#endif
void HOST_ENTRY(M68 *m);

static jmp_buf DONE;
static FILE *OUTF;
static long MAXFRAMES, HITS = 0;
static int FULL = 0;
static uint32_t H_SLOW_SKIP = 0;
static char **INP = 0; static long NINP = 0;

static uint64_t fnv(const uint8_t *p, size_t n) {
    uint64_t h = 0xcbf29ce484222325ull;
    for (size_t i = 0; i < n; i++) { h ^= p[i]; h *= 0x100000001b3ull; }
    return h;
}
static void put32(uint32_t v) { fwrite(&v, 4, 1, OUTF); }       /* little endian host */
static void record(M68 *m, uint32_t addr) {
    long tt = (long)h_now();
    uint32_t head[24] = { 0x32525456u, addr, (uint32_t)HITS++, (uint32_t)(H_FRAME0 + H_FRAME), (uint32_t)(tt / HOST_HPOS),
                          (uint32_t)(tt % HOST_HPOS), sr_get(m) };
    for (int i = 0; i < 8; i++) { head[7 + i] = m->d[i]; head[15 + i] = m->a[i]; }
#if SLOWSZ
    head[23] = 2;
#else
    head[23] = 1;
#endif
    fwrite(head, 4, 24, OUTF);
    if (FULL) {
        put32(0); put32(MEMSZ); fwrite(MEM, 1, MEMSZ, OUTF);
#if SLOWSZ
        put32(SLOWBASE); put32(SLOWSZ); fwrite(SLOW, 1, SLOWSZ, OUTF);
#endif
    } else {
        uint64_t h;
        put32(0); put32(MEMSZ | 0x80000000u); h = fnv(MEM, MEMSZ); fwrite(&h, 8, 1, OUTF);
#if SLOWSZ
        put32(SLOWBASE + H_SLOW_SKIP); put32((SLOWSZ - H_SLOW_SKIP) | 0x80000000u); h = fnv(SLOW + H_SLOW_SKIP, SLOWSZ - H_SLOW_SKIP); fwrite(&h, 8, 1, OUTF);
#endif
    }
}
static FILE *R_PCLOG = 0; static uint8_t *R_PCSET = 0;
static int pc_listed(uint32_t pc) {
    if (pc < MEMSZ) return R_PCSET[pc >> 1];
#if SLOWSZ
    if (pc - SLOWBASE < SLOWSZ) return R_PCSET[(MEMSZ >> 1) + ((pc - SLOWBASE) >> 1)];
#endif
    return 0;
}
static void on_pc(M68 *m, uint32_t pc) {
    if (R_PCLOG && pc_listed(pc)) { long tt = (long)h_now(); fprintf(R_PCLOG, "%ld %06x %ld %ld\n", H_FRAME0 + H_FRAME, pc, tt / HOST_HPOS, tt % HOST_HPOS); }
#ifdef HOST_L3_PC
    if (pc == HOST_L3_PC) { record(m, pc); return; }
#endif
    if (pc == TICK_PC && !H_IRQ_DEPTH) record(m, pc);
}
static FILE *R_AUD = 0;
static void r_aud(int ch, double t, int value) {
    double rel = t - H_PAULA.frame_base; long fr = H_FRAME0 + H_FRAME; if (rel < 0) { rel += (double)H_LINES * HOST_HPOS; fr--; }
    long tt = (long)rel; uint32_t rec[3] = { (uint32_t)fr, (uint32_t)(((tt / HOST_HPOS) << 16) | (tt % HOST_HPOS)), ((uint32_t)(uint16_t)value << 16) | (uint32_t)ch };
    fwrite(rec, 4, 3, R_AUD);
}
static FILE *R_REG = 0;
static void r_reg(uint32_t off, uint32_t v) {
    if (!(off == 0x096 || off == 0x09a || off == 0x09c || off == 0x09e || (off >= 0x0a0 && off < 0x0e0))) return;
    long tt = (long)h_now();
    uint32_t rec[4] = { (uint32_t)(H_FRAME0 + H_FRAME), (uint32_t)(((tt / HOST_HPOS) << 16) | (tt % HOST_HPOS)), (off << 16) | (v & 0xffff), H_PC & 0xffffff };
    fwrite(rec, 4, 4, R_REG);
}
static void apply_input(long k) {
    const char *s = (k < NINP) ? INP[k] : "";
    int r = !!strchr(s, 'R'), l = !!strchr(s, 'L'), u = !!strchr(s, 'U'), d = !!strchr(s, 'D'), f = !!strchr(s, 'F');
    H_JOY1 = (uint16_t)((r << 1) | (r ^ d) | (l << 9) | ((l ^ u) << 8));
    H_CIAA_PRA = (uint8_t)((H_CIAA_PRA & 0x7f) | (f ? 0 : 0x80));
}
static void on_frame(void) {
    if (H_FRAME >= MAXFRAMES) longjmp(DONE, 1);
    apply_input(H_FRAME);
}
static void rdfile(const char *dir, const char *n, void *buf, size_t len) {
    char p[512]; snprintf(p, sizeof p, "%s/%s", dir, n);
    FILE *f = fopen(p, "rb"); if (!f || fread(buf, 1, len, f) != len) { fprintf(stderr, "read %s\n", p); exit(1); } fclose(f);
}
int main(int argc, char **argv) {
    if (argc < 4) { fprintf(stderr, "host_trace STATE_DIR OUT.vtr FRAMES [INPUTS.txt] [--full] [--skip-stack N] [--own F] [--pclog F PCS] [--reglog F] [--audlog F] [--shots P A:B]\n"); return 1; }
    MAXFRAMES = atol(argv[3]);
    for (int i = 4; i < argc; i++) {
        if (!strcmp(argv[i], "--full")) { FULL = 1; continue; }
        if (!strcmp(argv[i], "--skip-stack") && i + 1 < argc) { H_SLOW_SKIP = (uint32_t)strtoul(argv[++i], 0, 0); continue; }
        if (!strcmp(argv[i], "--own") && i + 1 < argc) { H_OWN_DUMP = fopen(argv[++i], "wb"); continue; }
        if (!strcmp(argv[i], "--pclog") && i + 2 < argc) {
            R_PCLOG = fopen(argv[++i], "w"); R_PCSET = calloc((MEMSZ >> 1) + (SLOWSZ >> 1) + 1, 1);
            FILE *pf = fopen(argv[++i], "r"); unsigned x;
            while (pf && fscanf(pf, "%x", &x) == 1) { if (x < MEMSZ) R_PCSET[x >> 1] = 1;
#if SLOWSZ
                else if (x - SLOWBASE < SLOWSZ) R_PCSET[(MEMSZ >> 1) + ((x - SLOWBASE) >> 1)] = 1;
#endif
            }
            if (pf) fclose(pf); continue; }
        if (!strcmp(argv[i], "--reglog") && i + 1 < argc) { R_REG = fopen(argv[++i], "wb"); h_wr_cb = r_reg; continue; }
        if (!strcmp(argv[i], "--audlog") && i + 1 < argc) { R_AUD = fopen(argv[++i], "wb"); h_sample_cb = r_aud; continue; }
        if (!strcmp(argv[i], "--shots") && i + 2 < argc) { H_SHOT_PREFIX = argv[++i]; sscanf(argv[++i], "%ld:%ld", &H_SHOT_FIRST, &H_SHOT_LAST); continue; }
        FILE *f = fopen(argv[i], "r"); if (!f) { perror(argv[i]); return 1; }
        static char line[64]; long cap = 0;
        while (fgets(line, sizeof line, f)) {
            if (NINP == cap) { cap = cap ? cap * 2 : 4096; INP = realloc(INP, cap * sizeof *INP); }
            line[strcspn(line, "\r\n")] = 0; INP[NINP++] = strdup(line);
        }
        fclose(f);
    }
    rdfile(argv[1], "chip.bin", MEM, MEMSZ);
#if SLOWSZ
    rdfile(argv[1], "slow.bin", SLOW, SLOWSZ);
#endif
    uint8_t cr[0x200]; rdfile(argv[1], "creg.bin", cr, sizeof cr);
    for (int i = 0; i < 0x100; i++) CREG[i] = (uint16_t)((cr[2 * i] << 8) | cr[2 * i + 1]);
    M68 m; memset(&m, 0, sizeof m);
    char p[512]; snprintf(p, sizeof p, "%s/state.txt", argv[1]);
    FILE *f = fopen(p, "r"); if (!f) { perror(p); return 1; }
    unsigned sr, intreq, entry, pra = 0xfe, sdr = 0, icr = 0, j0 = 0, j1 = 0, pot = 0x5500; double t0;
    for (int i = 0; i < 8; i++) if (fscanf(f, "%x", &m.d[i]) != 1) return 1;
    for (int i = 0; i < 8; i++) if (fscanf(f, "%x", &m.a[i]) != 1) return 1;
    if (fscanf(f, "%x %lf %x %x", &sr, &t0, &intreq, &entry) != 4) return 1;
    if (fscanf(f, "%x %x %x %x %x %x", &pra, &sdr, &icr, &j0, &j1, &pot) == 6) {
        H_CIAA_PRA = (uint8_t)pra; H_CIAA_SDR = (uint8_t)sdr; H_CIAA_ICR = (uint8_t)icr; H_JOY0 = (uint16_t)j0; H_JOY1 = (uint16_t)j1; H_POTGOR = (uint16_t)pot;
    }
    { long fr0 = 0; if (fscanf(f, "%ld", &fr0) == 1) H_FRAME0 = fr0; }
    fclose(f);
    sr_set(&m, sr, 1); H_INTREQ = (uint16_t)intreq;
    H_LED_OFF = (pra >> 1) & 1;
    OUTF = fopen(argv[2], "wb"); if (!OUTF) { perror(argv[2]); return 1; }
    host_init(t0);
    host_display_init();
    h_pc_cb = on_pc; h_frame_cb = on_frame;
    if (NINP) apply_input(0);
    if (!setjmp(DONE)) {
        if (entry != TICK_PC) fprintf(stderr, "note: the state's pc %x is not TICK_PC %x; the run starts in HOST_ENTRY\n", entry, (unsigned)TICK_PC);
        HOST_ENTRY(&m);
        fprintf(stderr, "the entry routine returned (the level ended?)\n");
    }
    fclose(OUTF);
    if (R_PCLOG) fclose(R_PCLOG);
    if (R_REG) fclose(R_REG);
    if (R_AUD) fclose(R_AUD);
    if (H_OWN_DUMP) fclose(H_OWN_DUMP);
#ifdef PROF_N
    if (getenv("AREK_PROFILE")) { FILE *pf = fopen(getenv("AREK_PROFILE"), "w"); if (pf) { prof_dump(pf, -1); fclose(pf); } }
#endif
#ifdef COV_N
    if (getenv("AREK_COVER")) { FILE *cf = fopen(getenv("AREK_COVER"), "w"); if (cf) { cov_dump(cf); fclose(cf); } }
#endif
    fprintf(stderr, "records %ld frames %ld irqs %ld io_unknown %ld (last %06x) oob %ld\n", HITS, H_FRAME, H_IRQS, H_IO_UNKNOWN, H_IO_LAST, OOB_COUNT);
    return 0;
}
