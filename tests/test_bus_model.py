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
    assert T.bus_table_entry(dec('48a0 00ff'.replace(' ', ''))) == (2, 0, 0)         # movem.w d0-d7,-(a0): a write, no wait (Alien Breed II)
    assert T.bus_table_entry(dec('2100')) == (1, 0, 0)                              # move.l d0,-(a0): a write, no wait
    assert T.bus_table_entry(dec('d160')) == (1, 0, T.TAB_PRE_2)                    # add.w d0,-(a0): read first
    assert T.bus_table_entry(dec('3020')) == (1, 0, T.TAB_PRE_2)                    # move.w -(a0),d0
    assert T.bus_table_entry(dec('21b0 0000'.replace(' ', '')))[2] & T.TAB_PRE_2     # move.l (a0),0(a0,d0.w): the index adds its cycles
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
    } else if (!strcmp(mode, "spr")) {                        /* sprites 0-7 all at one POS/CTL ($50..$70), DDFSTRT from argv[4] */
        regs[0x092 >> 1] = (uint16_t)strtoul(argv[4], 0, 16);
        RAM[0x2000] = 0x50; RAM[0x2001] = 0x80; RAM[0x2002] = 0x70; RAM[0x2003] = 0x00;
        for (int n = 0; n < 8; n++) { regs[(0x120 >> 1) + 2 * n] = 0; regs[(0x122 >> 1) + 2 * n] = 0x2000; }
        arek_bus_frame(&B, 312);
        int v = atoi(argv[3]); uint8_t *L = own + v * 227;
        printf("line %d:", v); for (int h = 0; h < 227; h++) printf(" %d", L[h]); printf("\n");
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


def test_sprite_slots_yield_to_bitplanes(harness):
    def line(ddf, v):
        return [int(x) for x in harness('83e0', 'spr', v, ddf).split(':')[1].split()]     # + SPREN
    full = line('38', 0x60)                           # DDFSTRT $38: every sprite gets both slots on a data line
    assert all(full[0x15 + 4 * n] == 16 + n and full[0x17 + 4 * n] == 16 + n for n in range(8))
    cut = line('24', 0x60)                            # DDFSTRT $24: slots from $23 on belong to the bitplanes
    assert all(cut[0x15 + 4 * n] == 16 + n and cut[0x17 + 4 * n] == 16 + n for n in range(3))
    assert cut[0x21] == 19 and cut[0x23] != 19 and not any(cut[h] in range(20, 24) for h in range(227))
    above = line('24', 25)                            # line 25 (above DIWSTRT): no bitplanes, every POS/CTL fetch happens
    assert all(above[0x15 + 4 * n] == 16 + n and above[0x17 + 4 * n] == 16 + n for n in range(8))


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
    assert '#define BUS_LO 0x1000u' in src and '#define BUS_SPARSE 1' in src and 'bus_tab_row(uint32_t pc)' in src
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


def test_blit_words_are_not_cpu_accesses(tmp_path):
    cc = bus.compiler()
    if not cc:
        pytest.skip('no C compiler')
    # lea $dff000,a6 ; move.l #$10000,$50(a6) ; move.l #$20000,$54(a6) ; move.w #$09f0,$40(a6) ; clr.w $42(a6)
    # move.w #-1,$44(a6) ; move.w #-1,$46(a6) ; clr.w $64(a6) ; clr.w $66(a6) ; move.w #$0814,$58(a6) ; rts   (32 x 20 words A->D)
    prog = bytes.fromhex('4df900dff000 2d7c000100000050 2d7c000200000054 3d7c09f00040 426e0042 3d7cffff0044 3d7cffff0046 426e0064 426e0066 3d7c08140058 4e75'.replace(' ', ''))
    base = 0x1000
    src, _, _ = recomp.generate(prog, base, auto=[base], with_main=True, timing=True, bus_table=True)
    glue = '''
#include "arek_bus_glue.h"
static uint8_t OWN[313 * 227]; static uint16_t REGS[0x100];
static uint16_t rd(void *c, uint32_t a) { (void)c; return (uint16_t)((MEM[a & 0x7fffe] << 8) | MEM[(a & 0x7fffe) + 1]); }
__attribute__((constructor)) static void init(void) { arek_glue_init(227, 312, 313, OWN, REGS, rd, 0); REGS[0x096 >> 1] = 0x82c0; }
'''
    c, exe = tmp_path / 'r.c', tmp_path / 'r'
    c.write_text(src + glue)
    subprocess.run([cc, '-O1', '-DTICK_HOOK', '-DBUS_HOOK', '-I', HERE, '-o', str(exe), str(c),
                    os.path.join(HERE, 'arek_bus.c'), os.path.join(HERE, 'arek_bus_vamiga.c')], check=True)
    ram = bytearray(0x80000)
    ram[base:base + len(prog)] = prog
    (tmp_path / 'ram.bin').write_bytes(ram)
    (tmp_path / 'regs.txt').write_text(' '.join(['0'] * 15 + ['7ff00']) + '\n0 0 0 0 0\nf_001000\n')
    log = tmp_path / 'log.txt'
    subprocess.run([str(exe), str(tmp_path / 'ram.bin'), str(tmp_path / 'regs.txt'), str(tmp_path / 'out.bin'), str(log)], check=True)
    text = log.read_text()
    t = float([l for l in text.splitlines() if l.startswith('bus')][0].split()[1])
    assert 'blits 1' in text and t < 120, t          # 11 instructions, not 640 blitted words as CPU accesses


def test_operand_accesses_go_through_the_hooks():
    # movem.w (a6)+,d0-d1 ; movem.w d0-d1,-(a6) ; rte  - their operand reads and writes are CPU bus accesses (KIT-GAPS 29)
    src, _, _ = recomp.generate(bytes.fromhex('4c9e0003 48a6c000 4e73'.replace(' ', '')), 0x1000, funcs=[(0x1000, 0x100a, 0x1000)])
    body = src[src.index('L001000:'):]
    assert 'rd16(ma' in body and 'wr16(ma' in body and 'rd16(sp)' in body
    assert 'rd16_raw(ma' not in body and 'wr16_raw(ma' not in body and 'rd16_raw(sp)' not in body
    # the blitter's own traffic stays raw
    rt = src[:src.index('L001000:')]
    assert 'rd16_raw(apt)' in rt and 'wr16_raw(dpt, d)' in rt


def test_bus_table_is_sparse():
    """Code at the start and 1 MB later: two segments, not a table over the whole image (Alien Breed II: 55 MB of C)."""
    prog = bytes.fromhex('4e71 4e75'.replace(' ', ''))                  # nop; rts
    far = 0x100000
    img = bytearray(far + 4)
    img[0:4] = prog
    img[far:far + 4] = prog
    src, _, _ = recomp.generate(bytes(img), 0, auto=[0, far], bus_table=True)
    assert 'BUS_SEGS_N 2' in src and 'BUS_SEG_LO[BUS_SEGS_N] = {0x0u, 0x100000u}' in src and 'BUS_SEG_HI[BUS_SEGS_N] = {0x4u, 0x100004u}' in src
    assert src.count('{1,0,0},{1,3,0}') == 2 and len(src) < 200000                 # nop, rts in both; no 12 MB of zeros


PAULA_HARNESS = r"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "arek_bus.h"
#include "arek_bus_paula.h"
static uint8_t RAM[0x10000];
static uint16_t rd16(void *c, uint32_t a) { (void)c; a &= 0xfffe; return (uint16_t)((RAM[a] << 8) | RAM[a + 1]); }
static void sample(void *c, int ch, double t, int v) { (void)c; printf("s %d %.0f %d\n", ch, t, v); }
int main(void) {
    static uint8_t own[313 * 227]; static uint16_t regs[0x100];
    ArekBus B; arek_bus_init(&B, 227, 313, 313, own, regs, rd16, 0);
    ArekPaula P; arek_paula_init(&P, &B, sample, 0);
    const uint16_t W[4] = { 0x0102, 0x0304, 0x0506, 0x0708 };
    for (int i = 0; i < 4; i++) { RAM[0x1000 + 2 * i] = W[i] >> 8; RAM[0x1001 + 2 * i] = W[i] & 0xff; }
    arek_bus_frame(&B, 313); arek_paula_frame(&P, 0);
    arek_paula_write(&P, 0, 0xa0, 0); arek_paula_write(&P, 0, 0xa2, 0x1000); arek_paula_write(&P, 0, 0xa4, 4);
    arek_paula_write(&P, 0, 0xa6, 100); arek_paula_write(&P, 0, 0xa8, 64);
    arek_paula_write(&P, 2320, 0x96, 0x8001);                       /* DMA on at line 10, slot 50 */
    printf("planned %d %d\n", own[11 * 227 + 13], own[12 * 227 + 13]);   /* marked ahead, before anything ran */
    arek_paula_run(&P, 3300);
    arek_paula_write(&P, 3300, 0x96, 0x0001);                       /* off */
    arek_paula_run(&P, 20000);
    long n = 0; for (long k = 0; k < 313L * 227; k++) if (own[k] == 4) { printf("slot %ld\n", k); n++; }
    printf("fetches %ld slots %ld\n", P.fetches, n);
    return 0;
}
"""


def test_paula_model_rules(tmp_path):
    """arek_bus_paula.h: request -> slot $0D of the next line, the first word discarded, bytes every PER, a request
    on every even byte, one high and one low byte per word, slots planned ahead, nothing after DMA off (the rules
    Alien Breed II measured, plus vAmiga's output state machine; `arek selftest audio` has them exact)."""
    cc = bus.compiler()
    if not cc:
        pytest.skip('no C compiler')
    (tmp_path / 'p.c').write_text(PAULA_HARNESS)
    subprocess.run([cc, '-O1', '-I', HERE, '-o', str(tmp_path / 'p'), str(tmp_path / 'p.c'), os.path.join(HERE, 'arek_bus.c'),
                    os.path.join(HERE, 'arek_bus_vamiga.c'), '-lm'], check=True)
    out = subprocess.run([str(tmp_path / 'p')], capture_output=True, text=True, check=True).stdout.splitlines()
    assert 'planned 4 4' in out                                               # the slots of lines 11 and 12 are marked at the write
    samples = [tuple(map(int, l.split()[2:])) for l in out if l.startswith('s 0 ')]
    # 2937: the high byte's turn before the next word arrived (fetched at 2964) -> skipped, as vAmiga's state machine does;
    # off at 3300 after the low byte 3237: the next (high) byte is not output
    assert samples == [(2737, 64), (2837, 128), (3037, 128), (3137, 192), (3237, 256)]
    slots = [int(l.split()[1]) for l in out if l.startswith('slot ')]
    assert slots[:3] == [11 * 227 + 13, 12 * 227 + 13, 13 * 227 + 13] and all(k % 227 == 13 for k in slots)
    assert not [k for k in slots if k > 16 * 227]                               # the request pending at the off is served, no more
    assert out[-1].startswith('fetches ')


def test_selftest_audio_disk_and_conversions():
    from arek import adf
    from arek.headless import selftest
    d = selftest.audio_disk()
    assert len(d) == adf.SIZE and d[:4] == b'DOS\0' and adf.bootblock_checksum(d[:1024]) == struct.unpack('>I', d[4:8])[0]
    pay = selftest.AUDIO_PAYLOAD
    assert d[12 + 26:12 + 26 + len(pay)] == pay and pay[:6] == bytes.fromhex('4df900dff000')
    assert pay[selftest.AUDIO_SAMP - 0x40000:selftest.AUDIO_SAMP - 0x40000 + 4] == bytes([0, 16, 32, 48])
    assert pay[selftest.AUDIO_LOOP - 0x40000:selftest.AUDIO_LOOP - 0x40000 + 6] == bytes.fromhex('4bf90003c000')   # lea $3c000,a5 (the loop's head)
    recs = [{'frame': 331, 'v': 100, 'h': 40, 'reg': 0x096, 'value': 0x8001, 'agnus': False},
            {'frame': 330, 'v': 100, 'h': 30, 'reg': 0x0a6, 'value': 200, 'agnus': False},
            {'frame': 330, 'v': 100, 'h': 31, 'reg': 0x09a, 'value': 0xc020, 'agnus': False}]   # INTENA: not Paula's
    w = bus.paula_writes(recs, 330, 313)
    assert w == [(100 * 227 + 30, 0x0a6, 200), (313 * 227 + 100 * 227 + 40, 0x096, 0x8001)]
    assert bus.paula_samples([(330, 5, 6, -64, 2)], 330, 313) == [(5 * 227 + 6, 2, -64)]
    # the program's interrupt table: an entry per detection (bits, VPOSR, VHPOSR, frame counter); the counter maps to the
    # records' frames (d7 counts at line 100: an entry below line 100 belongs to the next frame)
    table = struct.pack('>4H', 0x0080, 0, 0x6410, 7) + struct.pack('>4H', 0x0300, 1, 0x0a20, 7) + struct.pack('>4H', 0x0080, 0, 0x3005, 8) + bytes(8)
    recs = [{'frame': 340, 'd': [0] * 7 + [7], 'ranges': {}}, {'frame': 341, 'd': [0] * 7 + [8], 'ranges': {selftest.AUDIO_TABLE: table}}]
    assert selftest.audio_table(recs) == [(0, 340, 100, 0x10), (1, 340, 0x10a, 0x20), (2, 340, 0x10a, 0x20), (0, 342, 0x30, 5)]
    model = [(0, 10 * 313 * 227 + 100 * 227 + 13), (1, 10 * 313 * 227 + 0x10a * 227 + 15), (2, 10 * 313 * 227 + 0x10a * 227 + 17),
             (0, 12 * 313 * 227 + 0x30 * 227 - 100), (3, 12 * 313 * 227)]
    q = selftest.audio_irqs(recs, model, 330, 313, 0)
    assert (q['detected'], q['model'], q['matched'], q['max_delay'], q['late'], q['missing']) == (4, 5, 4, 105, 0, 1)
    assert q['unmatched'] == [] and q['orphans'] == [(3, 12 * 313 * 227)]
    q = selftest.audio_irqs(recs, model, 330, 313, 0, window=80)
    assert q['unmatched'] == [(0, 12 * 313 * 227 + 0x30 * 227 + 5)] and q['orphans'] == [(3, 12 * 313 * 227), (0, 12 * 313 * 227 + 0x30 * 227 - 100)]   # in time order
    assert selftest.audio_irqs(recs, model, 330, 313, 0, to_t=11 * 313 * 227)['detected'] == 3   # the log's end bounds the detections


def test_paula_check_program(tmp_path):
    """arek_bus_paula_check on a synthetic log: the slots the model plans appear in the log -> agree; a log without them -> disagree."""
    cc = bus.compiler()
    if not cc:
        pytest.skip('no C compiler')
    exe = bus.compile_paula_check(str(tmp_path / 'chk'), cc)
    H, NL = 227, 313
    writes = [(0, 0xa0, 0), (0, 0xa2, 0x1000), (0, 0xa4, 4), (0, 0xa6, 100), (0, 0xa8, 64), (2320, 0x96, 0x8001)]
    empty = bytearray(H * NL)
    for k in (1, 3, 5, 226):
        for v in range(NL):
            empty[v * H + k] = 2
    (tmp_path / 'none.abbl').write_bytes(b'ABBL' + struct.pack('<5I', H, NL, 0, 1, 0) + bytes(empty))
    r = bus.paula_check(str(tmp_path / 'none.abbl'), writes, exe=exe)
    assert r['rc'] == 1 and r['agree'] == 0 and r['disagree'] > 10 and r['slots'][0]['only_model'] == r['disagree']
    full = bytearray(empty)
    for v in range(11, NL):
        full[v * H + 13] = 4                                                   # one fetch per line from line 11 on
    (tmp_path / 'full.abbl').write_bytes(b'ABBL' + struct.pack('<5I', H, NL, 0, 1, 0) + bytes(full))
    ram = bytearray(0x2000)
    ram[0x1000:0x1008] = bytes.fromhex('0102030405060708')
    r = bus.paula_check(str(tmp_path / 'full.abbl'), writes, samples=[(2737, 0, 64), (2837, 0, 128)], exe=exe, ram=bytes(ram), irqs=True)
    assert r['slots'][0]['only_model'] == 0 and r['samples'][0]['exact'] == 2 and r['samples'][0]['model'] > 2
    # the interrupt requests: the slot of the first (discarded) word after DMA on, then the slot of every block's last word
    # the interrupt requests, one CCK after: the slot of the first (discarded) word after DMA on; the block's last word
    # arrives at line 15 (4 words from line 12) and its request is raised at the next high byte (bytes every 100 CCK from 2737)
    assert r['irqs'][:2] == [(0, 11 * 227 + 13 + 1), (0, 3537 + 1)] and 'interrupt requests:' in r['text']


COPW_HARNESS = r'''
#include <stdio.h>
#include <string.h>
#include "arek_bus.h"
static uint8_t RAM[0x10000];
static uint16_t rd16(void *c, uint32_t a) { (void)c; a &= 0xfffe; return (uint16_t)((RAM[a] << 8) | RAM[a + 1]); }
static void cop(uint32_t *at, uint16_t a, uint16_t b) { RAM[*at] = a >> 8; RAM[*at + 1] = a; RAM[*at + 2] = b >> 8; RAM[*at + 3] = b; *at += 4; }
static long planes(const uint8_t *own) { long n = 0; for (long k = 0; k < 312L * 227; k++) n += own[k] >= 8 && own[k] < 16; return n; }
int main(int argc, char **argv) {
    static uint8_t own[313 * 227]; static uint16_t regs[0x100];
    ArekBus B; arek_bus_init(&B, 227, 312, 313, own, regs, rd16, 0);
    uint32_t at = 0x1000;                                   /* list A: 4 hires planes, COP1LC to itself (an intro screen) */
    cop(&at, 0x0100, 0xc204); cop(&at, 0x0080, 0x0000); cop(&at, 0x0082, 0x1000); cop(&at, 0xffff, 0xfffe);
    at = 0x2000;                                            /* list B: no bitplanes (the level's own list) */
    cop(&at, 0x0100, 0x0200); cop(&at, 0xffff, 0xfffe);
    regs[0x096 >> 1] = 0x83c0; regs[0x092 >> 1] = 0x3c; regs[0x094 >> 1] = 0xd4; regs[0x08e >> 1] = 0x2c81; regs[0x090 >> 1] = 0xf4c1;
    regs[0x080 >> 1] = 0; regs[0x082 >> 1] = 0x1000;
    arek_bus_frame(&B, 312); long a = planes(own);
    regs[0x082 >> 1] = 0x2000; regs[0x100 >> 1] = 0x0200;  /* the CPU sets COP1LC to list B */
    if (argc > 1) { arek_bus_cpu_write(&B, 0x082); arek_bus_cpu_write(&B, 0x100); }
    arek_bus_frame(&B, 312); long b = planes(own);
    printf("%ld %ld\n", a, b);
    return 0;
}
'''


def test_cpu_write_beats_the_coppers_earlier_write(tmp_path):
    """G50 (Alien Breed II): a list that writes COP1LC to itself, then the CPU sets COP1LC to another list: the next frame's
    map follows the CPU's list once the write is reported (arek_bus_cpu_write); without it the old list's planes stay."""
    cc = bus.compiler()
    if not cc:
        pytest.skip('no C compiler')
    (tmp_path / 'h.c').write_text(COPW_HARNESS)
    subprocess.run([cc, '-O1', '-I', HERE, '-o', str(tmp_path / 'h'), str(tmp_path / 'h.c'), os.path.join(HERE, 'arek_bus.c'),
                    os.path.join(HERE, 'arek_bus_vamiga.c')], check=True)
    old = [int(x) for x in subprocess.run([str(tmp_path / 'h')], capture_output=True, text=True, check=True).stdout.split()]
    new = [int(x) for x in subprocess.run([str(tmp_path / 'h'), 'cpu'], capture_output=True, text=True, check=True).stdout.split()]
    assert old[0] > 20000 and old[1] == old[0]                   # without the report the map keeps list A
    assert new[0] == old[0] and new[1] == 0                      # with it: list B, no bitplane slots
