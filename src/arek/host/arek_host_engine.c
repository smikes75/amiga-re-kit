/* arek_host_engine.c - the engine of a rebuild for a web page: the translated game on the kit's host (arek_host.h),
 * driven frame by frame by the page, which reads every frame's picture (vAmiga's screenshot layout) and sound (48 kHz
 * stereo) and gives the inputs and the disk images (arek_host_disk.h). Built with Emscripten ASYNCIFY (arek host engine):
 * the game runs as a coroutine in the page's thread - when it has finished more frames than the page allowed, its next
 * wait loop (WAIT_LOOP of the translation, the beam or a counter an interrupt bumps) sleeps in js_wait() until
 * engine_allow(n) and Module.__engineResume(); meanwhile the page draws. ASYNCIFY instruments only js_wait's callers,
 * so the game sleeps in wait loops only (as the Superfrog and Alien Breed II rebuilds). Built natively (cc), the same
 * file runs the game for N frames and prints a line the Node check compares (arek_host_engine_check.js):
 *
 *   arek host engine OUT --game game.c --l3 f_c13e1c --entry f_c01c72 [--dynamic] [--ovl overlays.c] [--src externs.c]
 *   arek_host_engine STATE.bin FRAMES [--disk N FILE]... [--keys alt|none] [--shot OUT.raw] [--dump CHIP.bin]  (native)
 *   node arek_host_engine_check.js OUT STATE.bin FRAMES [DISK.adf ...]                       (the same line from wasm)
 *
 * STATE.bin: `arek host pack` of a state folder (arek host state): "AREKSTATE1", chip RAM, slow RAM, the custom
 * registers, state.txt. ENGINE_DYNAMIC: when HOST_ENTRY returns, the run goes on at the return address its rts popped
 * (call_addr; a level loop that returns to a dispatcher). ENGINE_SRC: the project's file with its extern routines
 * (AHD_EXTERN) and hooks, included after the host. No game data: the state and the disks come from the page. */
#include <setjmp.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "arek_host_pre.h"
#define UNKNOWN_HOOK 1
#define OVERLAY_HOOK 1
struct M68; void host_wait_loop(uint32_t pc, uint32_t addr);
#define WAIT_LOOP(m, pc, addr) host_wait_loop(pc, addr)
#ifndef GAME_SRC
#error "define GAME_SRC (the translation, e.g. \"game.c\")"
#endif
#include GAME_SRC
#undef main
#ifdef OVL_SRC
#include OVL_SRC
#endif
#include "arek_bus_glue.h"
#ifndef HOST_L3
#error "define HOST_L3 (the translated level-3 handler)"
#endif
#include "arek_host.h"
#include "arek_host_disk.h"
#ifndef HOST_ENTRY
#error "define HOST_ENTRY (the translated routine the run starts in, e.g. f_c01c72)"
#endif
void HOST_ENTRY(M68 *m);
#ifdef ENGINE_SRC
#include ENGINE_SRC
#endif
#ifdef __EMSCRIPTEN__
#include <emscripten.h>
#define API EMSCRIPTEN_KEEPALIVE
#else
#define API
#endif

/* the page's view of a frame */
#define G_NFR 32
#define G_AUDN (48000 * 8)                                 /* the sound ring: 8 s of stereo frames */
typedef struct { long frame; int aud0, naud, led; } GFr;
static GFr G_FR[G_NFR];
static int16_t G_AUD[G_AUDN * 2]; static int G_AW = 0;
static int G_DONE = 0, G_ALLOW = 0, G_END = 0, G_WAIT = 0; static uint32_t G_ERR = 0;
static M68 E_M; static uint32_t E_ENTRY = 0;
static int E_KEYS = 0, E_KEYS2 = -1, E_KEYMODE = 0; static volatile int E_KEY_CODE = -1, E_KEY_DOWN = 0;

/* the translation's run-time targets it does not know: the page sees the address (engine_error), the game sleeps */
void unknown_hook(uint32_t a) { if (!G_ERR) G_ERR = a; }
void overlay_unknown_hook(M68 *m, uint32_t base, uint32_t entry, uint64_t fp) { (void)m; (void)base; (void)fp; if (!G_ERR) G_ERR = entry; }

#ifdef ENGINE_ASYNC
EM_ASYNC_JS(void, js_wait, (void), { await new Promise((res) => { Module.__engineResume = res; }); Module.__engineResume = null; });
#else
static jmp_buf G_STOPJ;
static void js_wait(void) { longjmp(G_STOPJ, 1); }        /* natively the run ends where the page would wait */
#endif
/* WAIT_LOOP of the translation: the game waits for the beam / a counter; here it sleeps when it is ahead of the page */
void host_wait_loop(uint32_t pc, uint32_t addr) {
    (void)pc; (void)addr;
    while (G_DONE >= G_ALLOW || G_ERR || G_END) { G_WAIT = 1; js_wait(); }
    G_WAIT = 0;
}
/* inputs at the start of a frame: keys bits 1 R 2 L 4 U 8 D 16 F on port 1 (JOY1DAT, fire = CIA-A PRA bit 7), keys2 on
 * port 0 (-1 = none); a raw key as the keyboard sends it (~((code << 1) | released) into SDR, SP in ICR) */
static void e_apply_keys(void) {
    if (E_KEYMODE == 1) E_KEYS = ((G_DONE - 1) / 40) % 2 ? 4 : 1;   /* the check's pattern (arek_host_engine_check.js) */
    int k = E_KEYS, r = k & 1, l = (k >> 1) & 1, u = (k >> 2) & 1, d = (k >> 3) & 1, f = (k >> 4) & 1;
    H_JOY1 = (uint16_t)((r << 1) | (r ^ d) | (l << 9) | ((l ^ u) << 8));
    H_CIAA_PRA = (uint8_t)((H_CIAA_PRA & 0x7f) | (f ? 0 : 0x80));
    if (E_KEYS2 >= 0) {
        k = E_KEYS2; r = k & 1; l = (k >> 1) & 1; u = (k >> 2) & 1; d = (k >> 3) & 1; f = (k >> 4) & 1;
        H_JOY0 = (uint16_t)((r << 1) | (r ^ d) | (l << 9) | ((l ^ u) << 8));
        H_CIAA_PRA = (uint8_t)((H_CIAA_PRA & 0xbf) | (f ? 0 : 0x40));
    }
    int c = E_KEY_CODE;
    if (c >= 0) { H_CIAA_SDR = (uint8_t)~((c << 1) | (E_KEY_DOWN ? 0 : 1)); H_CIAA_ICR |= 0x08; E_KEY_CODE = -1; }
}
static void e_frame_start(void) { e_apply_keys(); }
/* the frame is drawn (ARD_PIX): its screenshot, its samples into the ring, its record; the page may now read them */
static void e_frame_done(void) {
    int n = G_DONE; GFr *f = &G_FR[n % G_NFR];
    ard_to_rgb();
    ara_until(H_PAULA.frame_base + (double)H_LINES * HOST_HPOS);
    f->frame = H_FRAME0 + H_FRAME; f->led = H_LED_OFF < 0 ? -1 : !H_LED_OFF; f->aud0 = G_AW; f->naud = ARA_N;
    for (int i = 0; i < ARA_N; i++) { int w = (G_AW + i) % G_AUDN; G_AUD[2 * w] = ARA_BUF[2 * i]; G_AUD[2 * w + 1] = ARA_BUF[2 * i + 1]; }
    G_AW = (G_AW + ARA_N) % G_AUDN; ARA_N = 0;
    G_DONE = n + 1;                                       /* the game sleeps at its next wait loop */
}

API uint8_t *engine_alloc(int n) { return (uint8_t *)malloc((size_t)(n > 0 ? n : 1)); }
/* the packed state (arek host pack): 0 = ready for engine_run */
API int engine_init(const uint8_t *p, int n) {
    static const char magic[] = "AREKSTATE1";
    if (n < 11 + 2 * 0x80000 + 0x200 + 2 || memcmp(p, magic, 10)) return -1;
    const uint8_t *end = p + n; p += 11;
    memcpy(MEM, p, MEMSZ < 0x80000 ? MEMSZ : 0x80000); p += 0x80000;
#if SLOWSZ
    memcpy(SLOW, p, SLOWSZ < 0x80000 ? SLOWSZ : 0x80000);
#endif
    p += 0x80000;
    for (int i = 0; i < 0x100; i++) CREG[i] = (uint16_t)((p[2 * i] << 8) | p[2 * i + 1]);
    p += 0x200;
    if (!memchr(p, 0, (size_t)(end - p))) return -2;
    const char *st = (const char *)p; int k = 0, used;
    memset(&E_M, 0, sizeof E_M);
    unsigned sr, intreq, entry, pra = 0xfe, sdr = 0, icr = 0, j0 = 0, j1 = 0, pot = 0x5500; double t0; long fr0 = 0;
    for (int i = 0; i < 8; i++) { if (sscanf(st + k, "%x%n", &E_M.d[i], &used) != 1) return -3; k += used; }
    for (int i = 0; i < 8; i++) { if (sscanf(st + k, "%x%n", &E_M.a[i], &used) != 1) return -3; k += used; }
    if (sscanf(st + k, "%x %lf %x %x%n", &sr, &t0, &intreq, &entry, &used) != 4) return -3;
    k += used;
    if (sscanf(st + k, "%x %x %x %x %x %x%n", &pra, &sdr, &icr, &j0, &j1, &pot, &used) == 6) {
        k += used; H_CIAA_PRA = (uint8_t)pra; H_CIAA_SDR = (uint8_t)sdr; H_CIAA_ICR = (uint8_t)icr;
        H_JOY0 = (uint16_t)j0; H_JOY1 = (uint16_t)j1; H_POTGOR = (uint16_t)pot;
        if (sscanf(st + k, "%ld", &fr0) == 1) H_FRAME0 = fr0;
    }
    sr_set(&E_M, sr, 1); H_INTREQ = (uint16_t)intreq; H_LED_OFF = (pra >> 1) & 1;
    E_ENTRY = entry;
    host_init(t0);
    host_display_init();
    h_frame_cb = e_frame_start; h_frame_done_cb = e_frame_done;
    G_DONE = 0; G_END = 0; G_WAIT = 0; G_ERR = 0; G_AW = 0;
    return 0;
}
API int engine_set_disk(int n, const uint8_t *p, int len) { return ahd_set(n, p, len); }
/* after engine_init (and the disks): the game from its entry; async it returns only when the game ends, natively when
 * it would wait for the page */
API int engine_run(void) {
    HOST_ENTRY(&E_M);
#ifdef ENGINE_DYNAMIC
    for (;;) { uint32_t next = ((uint32_t)rd16_raw(E_M.a[7] - 4) << 16) | rd16_raw(E_M.a[7] - 2); call_addr(&E_M, next); }
#endif
    G_END = 1;
    for (;;) { G_WAIT = 1; js_wait(); }
    return 0;
}
API int engine_waiting(void) { return G_WAIT; }
API int engine_ended(void) { return G_END; }
API uint32_t engine_error(void) { return G_ERR; }
API int engine_done(void) { return G_DONE; }
API void engine_allow(int n) { G_ALLOW = n; }
API void engine_keys(int k) { E_KEYS = k; }
API void engine_keys2(int k) { E_KEYS2 = k; }
API void engine_key(int code, int down) { E_KEY_DOWN = down; E_KEY_CODE = code & 0x7f; }
API double engine_fr_frame(int n) { return n < 0 ? -1 : (double)G_FR[n % G_NFR].frame; }
API int engine_fr_aud0(int n) { return G_FR[n % G_NFR].aud0; }
API int engine_fr_naud(int n) { return G_FR[n % G_NFR].naud; }
API int engine_fr_led(int n) { return G_FR[n % G_NFR].led; }
API int16_t *engine_aud_ring(void) { return G_AUD; }
API int engine_aud_size(void) { return G_AUDN; }
API uint8_t *engine_rgb(void) { return ARD_RGB; }           /* the last frame: 716 x 285 RGB24 */
API int engine_rgb_w(void) { return ARD_SHOT_W; }
API int engine_rgb_h(void) { return ARD_SHOT_H; }
API uint16_t *engine_pix(void) { return &ARD_PIX[0][0]; }   /* 12-bit colours, ARD_LINES x ARD_WIDTH */
API int engine_pix_w(void) { return ARD_WIDTH; }
API int engine_pix_h(void) { return ARD_LINES; }
API int engine_led(void) { return H_LED_OFF < 0 ? -1 : !H_LED_OFF; }
API double engine_frame_no(void) { return (double)(H_FRAME0 + H_FRAME); }
API int engine_peek8(uint32_t a) { if (a < MEMSZ) return MEM[a];
#if SLOWSZ
    if (a - SLOWBASE < SLOWSZ) return SLOW[a - SLOWBASE];
#endif
    return -1; }
API void engine_poke8(uint32_t a, int v) { if (a < MEMSZ) MEM[a] = (uint8_t)v;
#if SLOWSZ
    else if (a - SLOWBASE < SLOWSZ) SLOW[a - SLOWBASE] = (uint8_t)v;
#endif
}
API double engine_disk_reads(void) { return (double)AHD_READS; }
API double engine_disk_fails(void) { return (double)AHD_FAIL; }
/* FNV-1a 64 of the last frame's picture and the chip RAM: the native and the wasm build must agree */
static char G_HASH[17];
API const char *engine_hash_hex(void) {
    uint64_t h = 0xcbf29ce484222325ull;
    for (size_t i = 0; i < sizeof ARD_RGB; i++) { h ^= ARD_RGB[i]; h *= 0x100000001b3ull; }
    for (size_t i = 0; i < MEMSZ; i++) { h ^= MEM[i]; h *= 0x100000001b3ull; }
    snprintf(G_HASH, sizeof G_HASH, "%016llx", (unsigned long long)h); return G_HASH;
}

#ifndef ENGINE_ASYNC
static uint8_t *rdall(const char *path, long *len) {
    FILE *f = fopen(path, "rb"); if (!f) { perror(path); exit(2); }
    fseek(f, 0, SEEK_END); *len = ftell(f); fseek(f, 0, SEEK_SET);
    uint8_t *b = (uint8_t *)malloc((size_t)(*len > 0 ? *len : 1));
    if (*len > 0 && (long)fread(b, 1, (size_t)*len, f) != *len) { fprintf(stderr, "read %s\n", path); exit(2); }
    fclose(f); return b;
}
int main(int argc, char **argv) {
    if (argc < 3) { fprintf(stderr, "arek_host_engine STATE.bin FRAMES [--disk N FILE]... [--keys alt|none] [--shot OUT.raw] [--dump CHIP.bin]\n"); return 2; }
    long len; uint8_t *st = rdall(argv[1], &len);
    int r = engine_init(st, (int)len);
    if (r) { fprintf(stderr, "engine_init %d\n", r); return 2; }
    G_ALLOW = atoi(argv[2]); E_KEYMODE = 1; const char *shot = 0, *dump = 0;
    for (int i = 3; i < argc; i++) {
        if (!strcmp(argv[i], "--disk") && i + 2 < argc) { int n = atoi(argv[i + 1]); if (ahd_set_file(n, argv[i + 2])) { fprintf(stderr, "disk %s\n", argv[i + 2]); return 2; } i += 2; }
        else if (!strcmp(argv[i], "--keys") && i + 1 < argc) { E_KEYMODE = strcmp(argv[++i], "none") ? 1 : 0; }
        else if (!strcmp(argv[i], "--shot") && i + 1 < argc) shot = argv[++i];
        else if (!strcmp(argv[i], "--dump") && i + 1 < argc) dump = argv[++i];
    }
    if (!setjmp(G_STOPJ)) engine_run();
    if (G_ERR) fprintf(stderr, "unknown routine %06x\n", G_ERR);
    printf("frames %d frame %ld hash %s\n", G_DONE, G_DONE ? G_FR[(G_DONE - 1) % G_NFR].frame : -1L, engine_hash_hex());
    if (shot) { FILE *f = fopen(shot, "wb"); if (f) { fwrite(ARD_RGB, 1, sizeof ARD_RGB, f); fclose(f); } }
    if (dump) { FILE *f = fopen(dump, "wb"); if (f) { fwrite(MEM, 1, MEMSZ, f); fclose(f); } }
    return G_ERR ? 3 : 0;
}
#endif
