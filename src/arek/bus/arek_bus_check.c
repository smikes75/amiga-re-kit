/* arek_bus_check.c - the model's frame map against a recorded bus log (arek selftest bus): for every frame of an ABBL file
 * the map is built from the registers and chip RAM the self-test program sets (regs: 0x100 words as hex text; RAM: a chip RAM
 * image) and the fixed DMA owners (refresh, bitplanes, sprites, copper) are compared slot by slot with the log; CPU, blitter
 * and free slots are left out (they depend on the program's timing). Then the blits are replayed as arek_bus_replay does.
 *   arek_bus_check LOG.abbl REGS.txt RAM.bin [LINES_FROM LINES_TO]
 * Output: per owner the slots that agree and disagree; exit 0 when nothing disagrees. No game data: the log of any run. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "arek_bus.h"

static uint8_t *RAM; static uint32_t RAMSZ;
static uint16_t rd16(void *c, uint32_t a) { (void)c; a &= 0xffffe; if (a + 1 >= RAMSZ) return 0; return (uint16_t)((RAM[a] << 8) | RAM[a + 1]); }

int main(int argc, char **argv) {
    if (argc < 4) { fprintf(stderr, "arek_bus_check LOG.abbl REGS.txt RAM.bin [FROM TO]\n"); return 2; }
    FILE *f = fopen(argv[1], "rb"); if (!f) { perror(argv[1]); return 2; }
    char magic[4]; uint32_t hd[5];
    if (fread(magic, 1, 4, f) != 4 || memcmp(magic, "ABBL", 4) || fread(hd, 4, 5, f) != 5) { fprintf(stderr, "not ABBL\n"); return 2; }
    uint32_t H = hd[0], NL = hd[1], NF = hd[3], FS = H * NL;
    uint8_t *maps = malloc((size_t)NF * FS);
    if (fread(maps, 1, (size_t)NF * FS, f) != (size_t)NF * FS) { fprintf(stderr, "short file\n"); return 2; }
    fclose(f);
    static uint16_t regs[0x100];
    f = fopen(argv[2], "r"); if (!f) { perror(argv[2]); return 2; }
    for (int i = 0; i < 0x100; i++) { unsigned v = 0; if (fscanf(f, "%x", &v) != 1) break; regs[i] = (uint16_t)v; }
    fclose(f);
    f = fopen(argv[3], "rb"); if (!f) { perror(argv[3]); return 2; }
    fseek(f, 0, SEEK_END); RAMSZ = (uint32_t)ftell(f); fseek(f, 0, SEEK_SET);
    RAM = malloc(RAMSZ); if (fread(RAM, 1, RAMSZ, f) != RAMSZ) { fprintf(stderr, "RAM?\n"); return 2; } fclose(f);
    uint32_t v0 = argc > 5 ? (uint32_t)atoi(argv[4]) : 0, v1 = argc > 5 ? (uint32_t)atoi(argv[5]) : NL;
    uint8_t *own = malloc(FS);
    ArekBus B; arek_bus_init(&B, (int)H, (int)NL, (int)NL, own, regs, rd16, 0);
    long ok[32] = { 0 }, bad[32] = { 0 }, missing = 0;
    for (uint32_t fr = 0; fr < NF; fr++) {
        arek_bus_frame(&B, (int)NL);
        const uint8_t *m = maps + (size_t)fr * FS;
        for (uint32_t v = v0; v < v1 && v < NL; v++) {
            if (m[v * H] == 0xff) { missing++; continue; }
            for (uint32_t h = 0; h < H; h++) {
                uint8_t want = m[v * H + h], got = own[v * H + h];
                int fixed_w = want == 2 || (want >= 8 && want < 24), fixed_g = got == 2 || (got >= 8 && got < 24);
                if (!fixed_w && !fixed_g) continue;
                if (want == got) ok[want]++;
                else { bad[fixed_w ? want : got]++; if (bad[fixed_w ? want : got] <= 3) printf("frame %u line %u slot %u: log %u model %u\n", fr, v, h, want, got); }
            }
        }
    }
    long tbad = 0, tok = 0;
    for (int o = 0; o < 32; o++) if (ok[o] || bad[o]) { printf("owner %d: agree %ld disagree %ld\n", o, ok[o], bad[o]); tbad += bad[o]; tok += ok[o]; }
    printf("fixed DMA slots: agree %ld, disagree %ld, lines missing in the log %ld\n", tok, tbad, missing);
    return tbad ? 1 : 0;
}
