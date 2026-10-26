/* arek_display_render.c - one frame from a chip RAM image with arek_display.h (the C renderer), for `arek selftest display`
 * and the tests that hold it against arek.display (Python):
 *   arek_display_render RAM.bin COP1LC_HEX OUT.raw OUT.pix [REGS.txt]
 * OUT.raw: 716 x 285 RGB24 like a VAHeadless screenshot; OUT.pix: 312 lines x 456 lowres pixels, 16-bit little-endian
 * colours (bit 12 = EHB half bright); REGS.txt: 0x100 hex words, the registers at the start of the frame (DMACON for the
 * sprite slot rule, BPLCON0 ... when the Copper does not set them). No game data. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
static uint8_t *MEM; static uint32_t MEMSZ;
static uint16_t CREG[0x100];
#include "arek_display.h"

int main(int argc, char **argv) {
    if (argc < 5) { fprintf(stderr, "arek_display_render RAM.bin COP1LC_HEX OUT.raw OUT.pix [REGS.txt]\n"); return 2; }
    FILE *f = fopen(argv[1], "rb"); if (!f) { perror(argv[1]); return 2; }
    fseek(f, 0, SEEK_END); MEMSZ = (uint32_t)ftell(f); fseek(f, 0, SEEK_SET);
    if (MEMSZ > 0x200000) MEMSZ = 0x200000;
    MEM = malloc(MEMSZ); if (fread(MEM, 1, MEMSZ, f) != MEMSZ) { fprintf(stderr, "RAM?\n"); return 2; } fclose(f);
    if (argc > 5) {
        f = fopen(argv[5], "r"); if (!f) { perror(argv[5]); return 2; }
        for (int i = 0; i < 0x100; i++) { unsigned v = 0; if (fscanf(f, "%x", &v) != 1) break; CREG[i] = (uint16_t)v; }
        fclose(f);
        for (int i = 0; i < 0x100; i++) if (CREG[i]) ard_write(2u * i, CREG[i]);
    }
    uint32_t cop = (uint32_t)strtoul(argv[2], 0, 16);
    ard_write(0x080, (uint16_t)(cop >> 16)); ard_write(0x082, (uint16_t)cop);
    ard_frame_start();
    ard_until(312);
    ard_to_rgb();
    f = fopen(argv[3], "wb"); if (!f) { perror(argv[3]); return 2; }
    fwrite(ARD_RGB, 1, sizeof ARD_RGB, f); fclose(f);
    f = fopen(argv[4], "wb"); if (!f) { perror(argv[4]); return 2; }
    for (int v = 0; v < 312; v++) for (int h = 0; h < ARD_WIDTH; h++) { uint8_t b[2] = { (uint8_t)ARD_PIX[v][h], (uint8_t)(ARD_PIX[v][h] >> 8) }; fwrite(b, 1, 2, f); }
    fclose(f);
    return 0;
}
