"""arek.bus: the bus model per DMA slot (synthetic frames, no game), the bus table of a translation
and the glue that puts the model behind a translation's hooks."""
import json
import os
import shutil
import struct
import subprocess

import pytest

from arek import bus, cli
from arek.m68k import decoder, recomp, timing

HERE = os.path.dirname(os.path.abspath(bus.__file__))
H, NL = 227, 312


def dec(code):
    return decoder.decode(bytes.fromhex(code + '0000'), 0x1000, 0x1000)


def test_table_entries_follow_the_translation():
    T = timing
    assert T.bus_table_entry(dec('4e75')) == (1, 3, 0)                              # rts: a7 += 4, no reads
    assert T.bus_table_entry(dec('4e73')) == (1, 3, 0)                              # rte: only the SR is read
    assert T.bus_table_entry(dec('6100 0010'.replace(' ', ''))) == (2, 0, T.TAB_PRE_ALL | T.TAB_PUSH2)   # bsr.w
    assert T.bus_table_entry(dec('6110')) == (1, 1, T.TAB_PRE_ALL | T.TAB_PUSH2)    # bsr.s: one more prefetch
    assert T.bus_table_entry(dec('4ed0')) == (1, 1, T.TAB_PRE_ALL)                  # jmp (a0)
    assert T.bus_table_entry(dec('4ef0 0000'.replace(' ', ''))) == (2, 1, T.TAB_PRE_ALL | T.TAB_PRE_2)   # jmp 0(a0,d0.w)
    assert T.bus_table_entry(dec('4e90')) == (1, 1, T.TAB_PRE_ALL | T.TAB_PUSH2)    # jsr (a0)
    assert T.bus_table_entry(dec('4250')) == (1, 1, 0)                              # clr.w (a0): the 68000 reads first
    assert T.bus_table_entry(dec('4cd8 00ff'.replace(' ', ''))) == (2, 1, 0)        # movem.l (a0)+,d0-d7: one read more
    assert T.bus_table_entry(dec('48a0 00ff'.replace(' ', ''))) == (2, 0, T.TAB_PRE_2)   # movem.w d0-d7,-(a0)
    assert T.bus_table_entry(dec('6602')) == (1, 0, T.TAB_PRE_ALL | T.TAB_BCC_S)    # bne.s
    assert T.bus_table_entry(dec('51c8 fffe'.replace(' ', ''))) == (2, 0, T.TAB_PRE_ALL | T.TAB_DBCC)   # dbf
    assert T.bus_table_entry(dec('2020')) == (1, 0, T.TAB_PRE_2)                    # move.l -(a0),d0
    assert T.bus_table_entry(dec('2080')) == (1, 0, 0)                              # move.l d0,(a0): both writes performed
    assert T.bus_table_entry(dec('3000')) == (1, 0, 0)
    assert T.bus_table_entry(dec('50d0')) == (1, 1, 0)                              # st (a0): the ea read is not performed
    for code in ('4e75', '2080', '4850', '4e50 0000', '4e58', 'b148', 'd148', 'c108', 'c0d0', '0650 0001'):
        w, extra, _ = T.bus_table_entry(dec(code.replace(' ', '')))
        r, wr = T.bus(dec(code.replace(' ', '')))
        assert w + extra + T.performed(dec(code.replace(' ', ''))) == r + wr, code


HARNESS = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "arek_bus.h"
static uint8_t RAM[0x10000];
static uint16_t rd16(void *c, uint32_t a) { (void)c; a &= 0xfffe; return (uint16_t)((RAM[a] << 8) | RAM[a + 1]); }
static void cop(uint32_t *at, uint16_t a, uint16_t b) { RAM[*at] = a >> 8; RAM[*at + 1] = a; RAM[*at + 2] = b >> 8; RAM[*at + 3] = b; *at += 4; }
int main(int argc, char **argv) {
    static uint8_t own[313 * 227]; static uint16_t regs[0x100];
    ArekBus B; arek_bus_init(&B, 227, 312, 313, own, regs, rd16, 0);
    uint32_t at = 0x1000;
    cop(&at, 0x0100, 0x5200); cop(&at, 0x0180, 0x0123); cop(&at, 0x6c07, 0xfffe); cop(&at, 0x0182, 0x0456); cop(&at, 0xffff, 0xfffe);
    regs[0x096 >> 1] = (uint16_t)strtoul(argv[1], 0, 16);      /* DMACON */
    regs[0x100 >> 1] = 0x5200; regs[0x092 >> 1] = 0x38; regs[0x094 >> 1] = 0xd0; regs[0x08e >> 1] = 0x2c81; regs[0x090 >> 1] = 0xf4c1;
    regs[0x080 >> 1] = 0; regs[0x082 >> 1] = 0x1000;
    arek_bus_frame(&B, 312);
    const char *mode = argv[2];
    if (!strcmp(mode, "map")) {
        long cnt[32] = { 0 };
        for (long k = 0; k < 312L * 227; k++) cnt[own[k]]++;
        for (int i = 0; i < 32; i++) if (cnt[i]) printf("owner %d %ld\n", i, cnt[i]);
        int v = atoi(argv[3]); uint8_t *L = own + v * 227;
        printf("line %d:", v); for (int h = 0; h < 227; h++) printf(" %d", L[h]); printf("\n");
        printf("cop_int %.1f\n", B.cop_int);
    } else if (!strcmp(mode, "cpu")) {
        double t = atof(argv[3]);
        double t2 = arek_bus_insn(&B, t, 12, 1, 0);           /* move.l d0,(a0): 1 prefetch */
        t2 = arek_bus_data(&B, t2); t2 = arek_bus_data(&B, t2);
        t2 = arek_bus_insn_end(&B, t2);
        printf("t %.1f cpu %u wait %u\n", t2, B.cpu_n, B.wait_n);
    } else if (!strcmp(mode, "blit")) {
        double t = atof(argv[3]); uint16_t size = (uint16_t)strtoul(argv[4], 0, 16);
        t = arek_bus_blit(&B, t, 0x09f0, 0, size);
        int busy0 = arek_bus_bbusy(&B, t + 1);
        double e = t + 1; while (e < 312.0 * 227) { arek_bus_blt_advance(&B, (uint32_t)e); if (!B.bl.on) break; e += 1; }   /* the end as the bus log records it: the last write done */
        long n = 0, first = -1, last = -1;
        for (long k = 0; k < 312L * 227; k++) if (own[k] == AREK_BUS_BLITTER) { n++; if (first < 0) first = k; last = k; }
        printf("busy0 %d end %.0f slots %ld first %ld last %ld\n", busy0, e, n, first, last);
        for (long k = 0; k < 312L * 227; k++) if (own[k] == AREK_BUS_BLITTER) printf("%ld\n", k);
    } else if (!strcmp(mode, "pri")) {
        double t = 1000;
        t = arek_bus_blit(&B, t, 0x09f0, 0, 0x0814);
        unsigned w0 = B.wait_n; double t2 = t;
        for (int k = 0; k < 20; k++) t2 = arek_bus_data(&B, t2);
        printf("waits %u dt %.0f\n", B.wait_n - w0, t2 - t);
    }
    return 0;
}
'''


@pytest.fixture(scope='module')
def harness(tmp_path_factory):
    cc = bus.compiler()
    if not cc:
        pytest.skip('no C compiler')
    d = tmp_path_factory.mktemp('bus')
    (d / 'h.c').write_text(HARNESS)
    exe = d / 'h'
    subprocess.run([cc, '-O1', '-I', HERE, '-o', str(exe), str(d / 'h.c'), os.path.join(HERE, 'arek_bus.c'),
                    os.path.join(HERE, 'arek_bus_vamiga.c')], check=True)

    def run(*args):
        return subprocess.run([str(exe)] + [str(a) for a in args], capture_output=True, text=True, check=True).stdout
    return run


def test_frame_map_fixed_dma(harness):
    out = harness('83c0', 'map', 100)              # DMAEN BPLEN COPEN BLTEN, 5 planes lores
    owners = {int(a): int(b) for a, b in (l.split()[1:] for l in out.splitlines() if l.startswith('owner'))}
    assert owners[2] == 312 * 4                     # refresh 1/3/5/226 on every line
    line = [int(x) for x in next(l for l in out.splitlines() if l.startswith('line 100')).split(':')[1].split()]
    assert line[1] == line[3] == line[5] == line[226] == 2
    groups = list(range(0x38, 0xd0 + 8, 8))
    for g in groups:                                 # 5 planes: slots 7/3/5/1/6 of each group, slot 2 (plane 6) free
        for q, plane in zip((7, 3, 5, 1, 6), range(5)):
            assert line[g + q] == 8 + plane, (g, q)
        assert line[g + 2] not in range(8, 16)
    assert sum(1 for x in line if 8 <= x < 16) == 5 * len(groups)
    out10 = harness('83c0', 'map', 10)              # above the display window: no bitplanes
    line10 = [int(x) for x in next(l for l in out10.splitlines() if l.startswith('line 10:')).split(':')[1].split()]
    assert not any(8 <= x < 16 for x in line10)
    assert owners[24] >= 5 and owners[24] < 40      # the copper: a few reads (MOVE, WAIT, MOVE, END), even slots only
    line0 = [int(x) for x in next(l for l in harness('83c0', 'map', 0).splitlines() if l.startswith('line 0:')).split(':')[1].split()]
    assert all(h % 2 == 0 for h, x in enumerate(line0) if x == 24)
    off = harness('0000', 'map', 100)               # DMA off: only refresh
    assert {int(a): int(b) for a, b in (l.split()[1:] for l in off.splitlines() if l.startswith('owner')) if int(a)} == {2: 312 * 4}


def test_cpu_waits_for_dma_slots(harness):
    free = harness('83c0', 'cpu', 10 * 227 + 20)    # a free line: 3 accesses, no wait, 12 clocks = 6 CCK
    busy = harness('83c0', 'cpu', 100 * 227 + 0x38)  # inside a bitplane group: the CPU waits
    f = dict(zip(('t', 'cpu', 'wait'), free.split()[1::2]))
    b = dict(zip(('t', 'cpu', 'wait'), busy.split()[1::2]))
    assert f['cpu'] == '3' and f['wait'] == '0' and abs(float(f['t']) - (10 * 227 + 20 + 6)) <= 1
    assert b['cpu'] == '3' and int(b['wait']) > 0 and float(b['t']) > 100 * 227 + 0x38 + 6


def test_blit_takes_its_slots(harness):
    out = harness('82c0', 'blit', 1000, '0814')     # no bitplanes; A->D, 32 x 20 words
    head = out.splitlines()[0].split()
    r = dict(zip(head[0::2], head[1::2]))
    slots = [int(x) for x in out.splitlines()[1:]]
    assert r['busy0'] == '1' and len(slots) == 2 * 640 and int(r['slots']) == 1280   # A read + D write per word
    assert slots[0] >= 1000 and float(r['end']) - 1000 >= 1280 and float(r['end']) - 1000 < 1280 * 1.5
    assert all(k % 227 not in (1, 3, 5, 226) for k in slots)                       # never over refresh


def test_blitter_priority(harness):
    pri = harness('86c0', 'pri')                      # BLTPRI: the CPU waits for the blitter
    no = harness('82c0', 'pri')                       # without it the blitter yields after 2 waits
    wp, dp = (int(float(x)) for x in pri.split()[1::2])
    wn, dn = (int(float(x)) for x in no.split()[1::2])
    assert wp > wn and dp > dn                       # the CPU gets through sooner without BLTPRI


def test_bus_table_and_glue_run(tmp_path):
    cc = bus.compiler()
    if not cc:
        pytest.skip('no C compiler')
    # moveq #1,d0 ; move.l d0,(a0) ; bsr.s sub ; rts ; (a nop never reached) ; sub: rts
    prog = bytes.fromhex('7001 2080 6104 4e75 4e71 4e75'.replace(' ', ''))
    base = 0x1000
    src, _, _ = recomp.generate(prog, base, auto=[base], with_main=True, timing=True, bus_table=True)
    assert '#define BUS_LO 0x1000u' in src and 'static const uint8_t BUS_TAB[BUS_N][3]' in src
    glue = '''
#include "arek_bus_glue.h"
static uint8_t OWN[313 * 227]; static uint16_t REGS[0x100];
static uint16_t rd(void *c, uint32_t a) { (void)c; return (uint16_t)((MEM[a & 0x7fffe] << 8) | MEM[(a & 0x7fffe) + 1]); }
__attribute__((constructor)) static void init(void) { arek_glue_init(227, 312, 313, OWN, REGS, rd, 0); }
'''
    c, exe = tmp_path / 'r.c', tmp_path / 'r'
    c.write_text(src + glue)
    subprocess.run([cc, '-O1', '-DTICK_HOOK', '-DBUS_HOOK', '-I', HERE, '-o', str(exe), str(c),
                    os.path.join(HERE, 'arek_bus.c'), os.path.join(HERE, 'arek_bus_vamiga.c')], check=True)
    ram = bytearray(0x80000)
    ram[base:base + len(prog)] = prog
    (tmp_path / 'ram.bin').write_bytes(ram)
    (tmp_path / 'regs.txt').write_text(' '.join(['0'] * 8 + ['2000'] + ['0'] * 6 + ['7ff00']) + '\n0 0 0 0 0\nf_001000\n')
    log = tmp_path / 'log.txt'
    subprocess.run([str(exe), str(tmp_path / 'ram.bin'), str(tmp_path / 'regs.txt'), str(tmp_path / 'out.bin'), str(log)], check=True)
    text = log.read_text()
    cycles = int([l for l in text.splitlines() if l.startswith('cycles')][0].split()[1])
    t = float([l for l in text.splitlines() if l.startswith('bus')][0].split()[1])
    clocks = 4 + 12 + 18 + 16 + 16                                        # moveq, move.l, bsr, rts, rts
    assert cycles == 0                                                    # with TICK_HOOK the host counts, not CYCLES
    assert clocks / 2 <= t <= clocks / 2 + 8, t                           # CCK: half the clocks, plus a few refresh waits
    assert (tmp_path / 'out.bin').read_bytes()[0x2000:0x2004] == b'\0\0\0\1'


def test_copy_and_replay(tmp_path, capsys):
    assert cli.main(['bus', 'copy', str(tmp_path / 'lib')]) == 0
    assert all((tmp_path / 'lib' / f).exists() for f in bus.FILES)
    assert 'MPL-2.0' in (tmp_path / 'lib' / 'arek_bus_vamiga.c').read_text()[:600]
    cc = bus.compiler()
    if not cc:
        pytest.skip('no C compiler')
    # a synthetic bus log: one frame, bitplane-free, one blit the model itself places; the replay must agree with it
    exe = bus.compile_replay(str(tmp_path / 'replay'), cc)
    harness = tmp_path / 'h.c'
    harness.write_text(HARNESS)
    hexe = tmp_path / 'h'
    subprocess.run([cc, '-O1', '-I', HERE, '-o', str(hexe), str(harness), os.path.join(HERE, 'arek_bus.c'),
                    os.path.join(HERE, 'arek_bus_vamiga.c')], check=True)
    out = subprocess.run([str(hexe), '82c0', 'blit', '1000', '0814'], capture_output=True, text=True, check=True).stdout
    head = dict(zip(out.splitlines()[0].split()[0::2], out.splitlines()[0].split()[1::2]))
    slots = [int(x) for x in out.splitlines()[1:]]
    rows = {}
    for v in range(NL):
        row = bytearray(H + 1)
        for h in (1, 3, 5, 226):
            row[h] = 2
        rows[(7, v)] = row
    for k in slots:
        rows[(7, k // H)][k % H] = 25
    end = int(float(head['end']))
    log = {'lines': rows, 'waits': [], 'blits': [{'frame': 7, 'v': 1000 // H, 'h': 1000 % H, 'bltcon0': 0x09f0, 'bltcon1': 0,
                                                 'width': 20, 'height': 32, 'end': (7, end // H, end % H)}]}
    info = bus.buslog_to_bin(log, str(tmp_path / 'f.abbl'))
    assert info == {'frame0': 7, 'frames': 1, 'blits': 1, 'lines': NL, 'hpos': H}
    r = bus.replay(str(tmp_path / 'f.abbl'), exe)
    assert r['blits'] == 1 and r['exact'] == 1 and r['slots_ok'] == 1280 and r['slots_bad'] == 0 and r['ok'], r['text']


def test_selftest_bus_disk_and_registers():
    from arek import adf
    from arek.headless import selftest
    d = selftest.bus_disk()
    assert len(d) == adf.SIZE and d[:4] == b'DOS\0' and adf.bootblock_checksum(d[:1024]) == struct.unpack('>I', d[4:8])[0]
    pay = selftest.BUS_PAYLOAD
    assert d[12 + 26:12 + 26 + len(pay)] == pay and len(pay) % 2 == 0
    assert pay[:6] == bytes.fromhex('4df900dff000')                         # lea $dff000,a6
    cop = pay[selftest.BUS_COPLIST - 0x40000:selftest.BUS_COPLIST - 0x40000 + 4]
    assert cop == bytes.fromhex('01005200')                                 # BPLCON0 = 5 planes lores, the copper's first move
    assert selftest.BUS_REGS[0x096] & 0x0400 and selftest.BUS_REGS[0x122] == selftest.BUS_SPR0 & 0xffff
    assert pay[selftest.BUS_SPR0 - 0x40000:selftest.BUS_SPR0 - 0x40000 + 4] == bytes.fromhex('50807000')
