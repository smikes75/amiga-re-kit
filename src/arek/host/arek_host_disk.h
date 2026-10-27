/* arek_host_disk.h - the game's disk reads served from disk images given at run time (a visitor's ADF in the browser
 * through engine_set_disk, a file on the command line natively), for a rebuild that ships no game data: the game's
 * read routine is replaced with `arek recomp --extern ADDR=name` by a few lines that call ahd_read(). Extracted from
 * the Alien Breed II project (docs/HOST.md). Header-only, MIT. No game data: which registers carry the disk, the first
 * sector, the count and the destination, the disk identities and any sector remapping are the project's, in the
 * extern routine:
 *
 *   AHD_EXTERN(game_read, m->d[4] == 0x123111u ? 0 : 1, (int16_t)m->d[1], (uint16_t)m->d[2], m->a[0])
 *   // = void game_read(M68 *m) { D0 = 0 when the sectors were read, -1 otherwise; then rts }
 *
 * ahd_set(n, bytes, len) keeps a copy of image n (0-based; AHD_DISKS of them); ahd_read(disk, sector, count, dest)
 * copies count sectors of 512 bytes to dest through the translation's memory (chip and slow RAM) and returns 1, or 0
 * (no image, outside it, a bad disk) counting the failure; AHD_READS / AHD_FAIL / AHD_LAST_* for the page's diagnostics.
 * Needs before it: the translation (MEM, wr8_raw, rd8_raw, M68). */
#ifndef AREK_HOST_DISK_H
#define AREK_HOST_DISK_H
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#ifndef AHD_DISKS
#define AHD_DISKS 4
#endif
#define AHD_SECTOR 512
static uint8_t *AHD_IMG[AHD_DISKS]; static long AHD_LEN[AHD_DISKS];
static long AHD_READS = 0, AHD_FAIL = 0; static int AHD_LAST_DISK = -1; static long AHD_LAST_SEC = 0; static int AHD_LAST_N = 0;
static int ahd_set(int n, const uint8_t *p, long len) {
    if (n < 0 || n >= AHD_DISKS || len < 0) return -1;
    free(AHD_IMG[n]); AHD_IMG[n] = 0; AHD_LEN[n] = 0;
    if (!p || !len) return 0;
    AHD_IMG[n] = (uint8_t *)malloc((size_t)len); if (!AHD_IMG[n]) return -2;
    memcpy(AHD_IMG[n], p, (size_t)len); AHD_LEN[n] = len; return 0;
}
static int ahd_set_file(int n, const char *path) {          /* natively: the image from a file */
    FILE *f = fopen(path, "rb"); if (!f) return -1;
    fseek(f, 0, SEEK_END); long len = ftell(f); fseek(f, 0, SEEK_SET);
    uint8_t *b = (uint8_t *)malloc((size_t)(len > 0 ? len : 1)); int r = -1;
    if (b && len > 0 && (long)fread(b, 1, (size_t)len, f) == len) r = ahd_set(n, b, len);
    free(b); fclose(f); return r;
}
static int ahd_read(int disk, long sector, int count, uint32_t dest) {
    AHD_READS++; AHD_LAST_DISK = disk; AHD_LAST_SEC = sector; AHD_LAST_N = count;
    int ok = disk >= 0 && disk < AHD_DISKS && AHD_IMG[disk] && sector >= 0 && count >= 0 && (sector + count) * AHD_SECTOR <= AHD_LEN[disk];
    if (ok) { const uint8_t *src = AHD_IMG[disk] + sector * AHD_SECTOR; for (long i = 0; i < (long)count * AHD_SECTOR; i++) wr8_raw(dest + (uint32_t)i, src[i]); }
    else AHD_FAIL++;
#ifndef __EMSCRIPTEN__
    if (getenv("AHD_LOG")) fprintf(stderr, "disk %d sector %ld count %d -> %06x %s\n", disk, sector, count, dest, ok ? "ok" : "FAILED");
#endif
    return ok;
}
static uint32_t ahd_rd32(uint32_t a) { return (rd8_raw(a) << 24) | (rd8_raw(a + 1) << 16) | (rd8_raw(a + 2) << 8) | rd8_raw(a + 3); }
/* the extern routine for a `jsr` the game makes: the caller pushed the return address, so it ends with an rts */
static inline void ahd_rts(M68 *m) { m->a[7] += 4; }
#define AHD_EXTERN(name, DISK, SECTOR, COUNT, DEST) \
    void name(M68 *m) { int ok = ahd_read((int)(DISK), (long)(SECTOR), (int)(COUNT), (uint32_t)(DEST)); m->d[0] = ok ? 0u : 0xffffffffu; ahd_rts(m); }
#endif
