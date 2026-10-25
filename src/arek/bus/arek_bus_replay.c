/* bltreplay.c - blitter modelu arek_bus proti bus logu vAmigy (VAHL_BUSLOG -> buslog2bin.py): kazdy blit z logu se pusti v modelu
 * nad zaznamenanou mapou snimku (sloty jinych vlastniku obsazene; procesor a blitter volne, protoze procesor si slot bere az po
 * udalostech Agnusu v taktu) a porovna se konec blitu a sloty blitru s logem. Bez hernich dat a bez kodu hry.
 *   cc -O2 -I.. bltreplay.c ../arek_bus.c ../arek_bus_vamiga.c -o bltreplay && ./bltreplay LOG.abbl
 * Vystup: blitu shodnych (konec v tomtez taktu), sloty blitru shodne / neshodne, histogram rozdilu konce. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "arek_bus.h"

static uint16_t rd16_none(void *ctx, uint32_t a) { (void)ctx; (void)a; return 0; }   /* mapa se neskladá z copper listu */

typedef struct { uint32_t frame; uint16_t v, h, con0, con1, w, hgt; uint32_t ef; uint16_t ev, eh; uint8_t pad[8]; } Blit;

int main(int argc, char **argv) {
    if (argc < 2) { fprintf(stderr, "pouziti: bltreplay LOG.abbl\n"); return 2; }
    FILE *f = fopen(argv[1], "rb"); if (!f) { perror(argv[1]); return 2; }
    char magic[4]; uint32_t hd[5];
    if (fread(magic, 1, 4, f) != 4 || memcmp(magic, "ABBL", 4) || fread(hd, 4, 5, f) != 5) { fprintf(stderr, "neni ABBL\n"); return 2; }
    uint32_t H = hd[0], NL = hd[1], F0 = hd[2], NF = hd[3], NB = hd[4], FS = H * NL;
    uint8_t *maps = malloc((size_t)NF * FS); Blit *bl = malloc(sizeof(Blit) * (NB ? NB : 1));
    if (fread(maps, 1, (size_t)NF * FS, f) != (size_t)NF * FS || fread(bl, sizeof(Blit), NB, f) != NB) { fprintf(stderr, "kratky soubor\n"); return 2; }
    fclose(f);
    static uint16_t regs[0x100]; uint8_t *own = malloc(FS);
    ArekBus B; arek_bus_init(&B, (int)H, (int)NL, (int)NL, own, regs, rd16_none, 0);
    regs[0x096 >> 1] = 0x0240;   /* DMAEN | BLTEN */
    long blits = 0, exact = 0, skipped = 0, slotok = 0, slotbad = 0, hist[13] = { 0 }, far_lo = 0, far_hi = 0;
    for (uint32_t i = 0; i < NB; i++) {
        Blit *x = &bl[i];
        if (x->ef == 0xffffffffu || (x->con1 & 1) || x->frame < F0 || x->frame >= F0 + NF) { skipped++; continue; }
        uint32_t fr = x->frame - F0;
        /* mapa snimku: procesor (1) a blitter (25) volne, chybejici radek (0xFF) obsazeny */
        #define LOAD(k) do { const uint8_t *m = maps + (size_t)(k) * FS; for (uint32_t s = 0; s < FS; s++) { uint8_t o = m[s]; own[s] = (o == 1 || o == 25) ? 0 : (o == 0xff ? AREK_BUS_BLOCKED : o); } } while (0)
        LOAD(fr);
        uint32_t S = x->v * H + x->h, words = (uint32_t)(x->w ? x->w : 64) * (x->hgt ? x->hgt : 1024);
        arek_bus_blt_start(&B, S - 1, x->con0, words);   /* log: blit S; STRT1 nejdriv v S + 1 = t0 + 2 */
        uint32_t t = S, end_f = 0, end_t = 0; int done = 0;
        for (long guard = 0; guard < 4000000 && !done; guard++, t++) {
            if (t >= FS) {   /* konec snimku: blitter pokracuje v dalsim (jako arek_bus_frame), sloty tohoto snimku vyhodnotit */
                for (uint32_t s = 0; s < FS; s++) if (own[s] == AREK_BUS_BLITTER) { if (maps[(size_t)fr * FS + s] == 25) slotok++; else slotbad++; }
                if (++fr >= NF) break;
                t -= FS; B.bl.bt -= FS; LOAD(fr);
            }
            arek_bus_blt_advance(&B, t);
            if (!B.bl.on) { done = 1; end_f = fr; end_t = t; }
        }
        for (uint32_t s = 0; s < FS; s++) if (own[s] == AREK_BUS_BLITTER) { if (maps[(size_t)fr * FS + s] == 25) slotok++; else slotbad++; }
        blits++;
        if (!done) { far_hi++; continue; }
        long d = ((long)end_f - (long)(x->ef - F0)) * FS + (long)end_t - (long)(x->ev * H + x->eh);
        if (d == 0) exact++;
        if (d < -6) far_lo++; else if (d > 6) far_hi++; else hist[d + 6]++;
    }
    printf("%s: blitu %ld (preskoceno %ld: bez konce, rezim car, mimo log), konec v tomtez taktu %ld (%.2f %%)\n", argv[1], blits, skipped, exact, blits ? 100.0 * exact / blits : 0);
    printf("  sloty blitru shodne s logem %ld, neshodne %ld\n", slotok, slotbad);
    printf("  rozdil konce model - vAmiga [takty]: <-6 %ld", far_lo); for (int k = 0; k < 13; k++) if (hist[k]) printf(", %+d: %ld", k - 6, hist[k]); printf(", >6 %ld\n", far_hi);
    return (exact == blits && slotbad == 0) ? 0 : 1;
}
