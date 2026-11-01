/* arek_host_datadisk.h - a data disk the game writes, kept by the page (localStorage, wb-datadisk.js) or by a file
 * natively. Team17's games save the high-score table by hand (OPTIONS -> HISCORE SAVE / LOAD -> "insert your custom
 * datadisk") to sector 0 of a disk in DF0 through their own disk routine; a rebuild without a drive answers DISK ERROR.
 * This header is the disk: AHDD_SECTORS sectors of 512 bytes in the host, read and written through the game's disk
 * routine replaced with `arek recomp --extern ADDR=name`, handed to the page before the game runs and taken back after
 * every write. Extracted from the Alien Breed II project (docs/HOST.md). Header-only, MIT. No game data: which registers
 * carry the unit, the sector, the count, the mode and the buffer, what the game expects back and when the data disk is
 * "in the drive" are the project's, in the extern routine:
 *
 *   AHDD_EXTERN(game_dsk_io, m->d[0] & 3, (uint16_t)m->d[1], (uint16_t)m->d[2], m->d[3] & 1, m->a[0])
 *   // = void game_dsk_io(M68 *m) { D0 = 0 when the sectors moved, AHDD_FAIL (30, TDERR_SeekError) otherwise; rts }
 *
 * A game whose one routine serves its own disks too (Superfrog) decides in its own extern: the data disk is in the drive
 * (ahdd_in(); the project calls ahdd_insert(1 / 0) around the game's "insert datadisk" prompt, or leaves it in for
 * good - the default) and unit 0 -> ahdd_io(), otherwise ahd_read() of arek_host_disk.h.
 * The page: ahdd_buf() / ahdd_size() are the sectors (the page writes them before the game runs and reads them back
 * when ahdd_gen() changed - every write by the game bumps it); ahdd_set(ok) says whether they hold a disk. An empty
 * drive (no disk saved yet) reads as zeros and still takes a write - what a blank disk does; the game decides what a
 * sector without its marker means. Natively ahdd_sync(path) once per frame keeps the file at path equal to the disk.
 * Needs before it: the translation (rd8_raw, wr8_raw, M68). */
#ifndef AREK_HOST_DATADISK_H
#define AREK_HOST_DATADISK_H
#include <stdint.h>
#include <stdio.h>
#ifdef __EMSCRIPTEN__
#include <emscripten.h>
#define AHDD_API EMSCRIPTEN_KEEPALIVE
#else
#define AHDD_API
#endif
#ifndef AHDD_SECTORS
#define AHDD_SECTORS 1
#endif
#ifndef AHDD_FAIL
#define AHDD_FAIL 30u                                       /* trackdisk's TDERR_SeekError: the disk cannot be accessed */
#endif
#define AHDD_SECTOR 512
static uint8_t AHDD[AHDD_SECTORS * AHDD_SECTOR];
static volatile int AHDD_OK = 0, AHDD_GEN = 0, AHDD_IN = 1;
static long AHDD_READS = 0, AHDD_WRITES = 0, AHDD_MISS = 0;    /* for the page's diagnostics */
/* count sectors from `sector` between the disk and the translation's memory at addr; 1 = done, 0 = outside the disk */
static int ahdd_io(long sector, int count, int write, uint32_t addr) {
    if (sector < 0 || count < 0 || sector + count > AHDD_SECTORS) { AHDD_MISS++; return 0; }
    uint8_t *p = AHDD + sector * AHDD_SECTOR; long n = (long)count * AHDD_SECTOR;
    if (write) { for (long i = 0; i < n; i++) p[i] = (uint8_t)rd8_raw(addr + (uint32_t)i); if (n) { AHDD_OK = 1; AHDD_GEN++; } AHDD_WRITES++; }
    else { for (long i = 0; i < n; i++) wr8_raw(addr + (uint32_t)i, AHDD_OK ? p[i] : 0); AHDD_READS++; }
    return 1;
}
AHDD_API uint8_t *ahdd_buf(void) { return AHDD; }
AHDD_API int ahdd_size(void) { return AHDD_SECTORS * AHDD_SECTOR; }
AHDD_API void ahdd_set(int ok) { AHDD_OK = ok != 0; }      /* the page put a disk into the buffer (1) or took it out (0) */
AHDD_API int ahdd_has(void) { return AHDD_OK; }
AHDD_API int ahdd_gen(void) { return AHDD_GEN; }
AHDD_API void ahdd_insert(int in) { AHDD_IN = in != 0; }   /* the data disk is in the drive (1) or the game's disk is (0) */
AHDD_API int ahdd_in(void) { return AHDD_IN; }
/* the extern routine for a `jsr` the game makes: the caller pushed the return address, so it ends with an rts */
static inline void ahdd_rts(M68 *m) { m->a[7] += 4; }
#define AHDD_EXTERN(name, UNIT, SECTOR, COUNT, WRITE, ADDR) \
    void name(M68 *m) { int ok = AHDD_IN && (int)(UNIT) == 0 && ahdd_io((long)(SECTOR), (int)(COUNT), (int)(WRITE), (uint32_t)(ADDR)); \
                        m->d[0] = ok ? 0u : (uint32_t)(AHDD_FAIL); ahdd_rts(m); }
#ifndef __EMSCRIPTEN__
/* natively, once per frame: the file at path is the disk - read on the first call (none or short = an empty drive),
 * written after every change by the game; 1 = written now, 0 = nothing to do, -1 = the file cannot be written */
static int ahdd_sync(const char *path) {
    static int gen = -1;
    if (!path) return 0;
    if (gen < 0) {
        FILE *f = fopen(path, "rb"); AHDD_OK = f && fread(AHDD, 1, sizeof AHDD, f) == sizeof AHDD; if (f) fclose(f);
        gen = AHDD_GEN; return 0;
    }
    if (gen == AHDD_GEN) return 0;
    gen = AHDD_GEN;
    FILE *f = fopen(path, "wb"); if (!f) return -1;
    fwrite(AHDD, 1, sizeof AHDD, f); fclose(f); return 1;
}
#endif
#endif
