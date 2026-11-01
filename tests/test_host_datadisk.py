"""arek_host_datadisk.h on a synthetic translation: the game's disk routine (an AHDD_EXTERN) reads an empty drive as
zeros, writes a sector the page then sees (the generation bumps), reads it back, fails outside the disk, on another
unit and with the disk taken out of the drive; natively ahdd_sync() keeps a file equal to the disk across runs."""
import os
import subprocess

import pytest

from arek import bus, host

HOST = os.path.dirname(os.path.abspath(host.__file__))
PROG = r'''
#include <stdint.h>
#include <stdio.h>
#include <string.h>
static uint8_t MEM[0x10000];
static uint8_t rd8_raw(uint32_t a) { return MEM[a & 0xffff]; }
static void wr8_raw(uint32_t a, uint8_t v) { MEM[a & 0xffff] = v; }
typedef struct { uint32_t d[8], a[8]; } M68;
#define AHDD_SECTORS 2
#include "arek_host_datadisk.h"
AHDD_EXTERN(game_dsk_io, m->d[0] & 3, (uint16_t)m->d[1], (uint16_t)m->d[2], m->d[3] & 1, m->a[0])
static uint32_t io(M68 *m, int unit, int sec, int n, int wr, uint32_t a0) {
    m->d[0] = unit; m->d[1] = sec; m->d[2] = n; m->d[3] = wr ? 0x8001 : 0x8000; m->a[0] = a0; game_dsk_io(m); return m->d[0];
}
int main(int argc, char **argv) {
    M68 m; memset(&m, 0, sizeof m); m.a[7] = 0x7000;
    const char *path = argc > 1 ? argv[1] : 0;
    ahdd_sync(path);                                           /* the first call: the file is the disk */
    int had = ahdd_has();
    for (int i = 0; i < 512; i++) MEM[0x1000 + i] = (uint8_t)(i * 7 + 3);
    memset(MEM + 0x2000, 0xee, 1024);
    uint32_t r0 = io(&m, 0, 0, 1, 0, 0x2000);                  /* a read before any write */
    int zeros = 1; for (int i = 0; i < 512; i++) zeros &= MEM[0x2000 + i] == (had ? (uint8_t)(i * 7 + 3) : 0);
    int g0 = ahdd_gen();
    uint32_t r1 = io(&m, 0, 0, 1, 1, 0x1000);                  /* the game writes sector 0 */
    uint32_t r2 = io(&m, 0, 0, 1, 0, 0x2200);
    int same = !memcmp(MEM + 0x2200, MEM + 0x1000, 512);
    uint32_t r3 = io(&m, 0, 1, 2, 0, 0x3000);                  /* sectors 1-2: outside a 2-sector disk */
    uint32_t r4 = io(&m, 1, 0, 1, 0, 0x3000);                  /* unit 1: not the data disk */
    ahdd_insert(0); uint32_t r5 = io(&m, 0, 0, 1, 0, 0x3000); ahdd_insert(1);   /* the game's disk is in the drive */
    uint32_t r6 = io(&m, 0, 1, 1, 0, 0x3000);                  /* sector 1 of an empty-but-written disk: zeros of the buffer */
    int wrote = ahdd_sync(path);
    printf("had %d r0 %u zeros %d gen %d->%d r1 %u r2 %u same %d r3 %u r4 %u r5 %u r6 %u sp %x reads %ld writes %ld miss %ld sync %d\n",
           had, r0, zeros, g0, ahdd_gen(), r1, r2, same, r3, r4, r5, r6, m.a[7], AHDD_READS, AHDD_WRITES, AHDD_MISS, wrote);
    return 0;
}
'''


def test_data_disk_in_the_host(tmp_path):
    cc = bus.compiler()
    if not cc:
        pytest.skip('no C compiler')
    (tmp_path / 'dd.c').write_text(PROG)
    subprocess.run([cc, '-O1', '-Wall', '-Werror', '-I', HOST, '-o', str(tmp_path / 'dd'), str(tmp_path / 'dd.c')], check=True, timeout=120)
    disk = tmp_path / 'datadisk.bin'
    r = subprocess.run([str(tmp_path / 'dd'), str(disk)], capture_output=True, text=True, check=True, timeout=30).stdout.split()
    # an empty drive: the read gives zeros and D0 = 0; the write bumps the generation; the read matches; the misses fail with 30
    assert r == ['had', '0', 'r0', '0', 'zeros', '1', 'gen', '0->1', 'r1', '0', 'r2', '0', 'same', '1', 'r3', '30', 'r4', '30', 'r5', '30', 'r6', '0',
                 'sp', '701c', 'reads', '3', 'writes', '1', 'miss', '1', 'sync', '1'], r
    assert disk.stat().st_size == 1024 and disk.read_bytes()[:512] == bytes((i * 7 + 3) & 0xff for i in range(512)) and disk.read_bytes()[512:] == bytes(512)
    # the next run starts with the file as the disk: the first read already gives the saved sector
    r2 = subprocess.run([str(tmp_path / 'dd'), str(disk)], capture_output=True, text=True, check=True, timeout=30).stdout.split()
    assert r2[:6] == ['had', '1', 'r0', '0', 'zeros', '1'] and r2[7] == '0->1'
    # no file: the sync is a no-op, the disk still works in memory
    r3 = subprocess.run([str(tmp_path / 'dd')], capture_output=True, text=True, check=True, timeout=30).stdout.split()
    assert r3[:2] == ['had', '0'] and r3[-1] == '0' and r3[13] == '1'
