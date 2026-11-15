"""arek host boot (kit 1.0.82): the start from the disks without a Kickstart, measured. -DAREK_FIRSTREAD logs the bytes
a run reads before it writes them (the CPU, the blitter, DMA); `arek host boot` finds them on the disk images (copy
rules with an FNV-1a of the bytes) or keeps them as the residue, and writes a state with zero RAM and arek_boot.h; a
vector still in the Kickstart ROM is acknowledged. Synthetic programs and disks only."""
import os
import random
import struct
import subprocess

import pytest

from arek import bus, host, hostboot
from arek.headless import trace
from arek.m68k import recomp

from test_recomp_semantics import run

BUS = os.path.dirname(os.path.abspath(bus.__file__))
HOST = os.path.dirname(os.path.abspath(host.__file__))


def log_ranges(path):
    out = []
    for line in path.read_text().splitlines():
        if line.startswith('#'):
            continue
        lo, hi, k = line.split()
        out.append((int(lo, 16), int(hi, 16), k))
    return out


def covers(ranges, a):
    return next((k for lo, hi, k in ranges if lo <= a < hi), None)


def test_firstread_logs_what_the_run_read_before_it_wrote_it(tmp_path):
    """move.l $4,d0 reads $4-$7 first; $2000 is written, then read (not logged); $3001 read as a byte; a blit A -> D
    reads $4000-$4001 as the blitter and writes $5000 (a later CPU read of it is not logged)."""
    prog = ('20380004'                  # move.l $4.w,d0
            '31fc12342000'              # move.w #$1234,$2000.w
            '32382000'                  # move.w $2000.w,d1
            '14383001'                  # move.b $3001.w,d2
            '33fc09f000dff040'          # BLTCON0 A -> D
            '33fc000000dff042'          # BLTCON1
            '33fcffff00dff044'          # BLTAFWM
            '33fcffff00dff046'          # BLTALWM
            '23fc0000400000dff050'      # BLTAPT $4000
            '23fc0000500000dff054'      # BLTDPT $5000
            '33fc004100dff058'          # BLTSIZE 1 line x 1 word
            '36385000')                 # move.w $5000.w,d3
    log = tmp_path / 'fr.txt'
    d, _, _, ram = run(tmp_path, prog, {}, pre_c='#define AREK_FIRSTREAD 1\n', env={'AREK_FIRSTREAD': str(log)},
                       ram_init={0x4: b'\0\0\x12\x34', 0x3000: b'\x55\x66', 0x4000: b'\xab\xcd'})
    assert d[0] == 0x1234 and d[1] == 0x1234 and d[2] == 0x66 and d[3] == 0xabcd
    r = log_ranges(log)
    assert all(covers(r, a) == 'c' for a in range(4, 8)) and covers(r, 0x3001) == 'c'
    assert covers(r, 0x3000) is None and covers(r, 0x2000) is None and covers(r, 0x2001) is None
    assert covers(r, 0x4000) == 'b' and covers(r, 0x4001) == 'b' and covers(r, 0x5000) is None
    _, _, _, _ = run(tmp_path, prog, {}, env={'AREK_FIRSTREAD': str(tmp_path / 'none.txt')})   # without the define: nothing
    assert not (tmp_path / 'none.txt').exists()


def disk_and_state(seed=5):
    rnd = random.Random(seed)
    disk = bytearray(rnd.randrange(1, 256) for _ in range(0x4000))
    chip = bytearray(0x80000)
    chip[0x400:0xc00] = disk[0x1000:0x1800]
    chip[0x500:0x504] = b'\xde\xad\xbe\xef'          # the crack's fix over the loaded bytes
    chip[0x4:0x8] = b'\0\0\x12\x34'                  # an ExecBase-like long: only its non-zero bytes are needed
    chip[0x9000:0x9010] = disk[0x2000:0x2010]        # on the disk too, but nobody reads it
    return bytes(disk), chip


def test_the_plan_takes_the_disk_and_keeps_the_rest(tmp_path):
    disk, chip = disk_and_state()
    sp = hostboot.Space(chip, b'')
    log = tmp_path / 'fr.txt'
    log.write_text('# arek firstread 1\n000004 000008 c\n000400 000c00 c\n001800 001804 d\n')
    p = hostboot.plan(sp, hostboot.read_logs([log], sp), [disk])
    got = {c['to']: (c['off'], c['len']) for c in p['copies']}
    assert got[0x400][0] == 0x1000 and 0x400 + got[0x400][1] <= 0x500
    tail = max(c for c in got if c > 0x400)
    assert tail <= 0x504 and got[tail][0] == 0x1000 + (tail - 0x400) and tail + got[tail][1] == 0xc00
    res = {r['to']: r['bytes'] for r in p['residue']}
    assert res[0x6] == b'\x12\x34'                                          # the zero half of the long is not needed
    assert any(a <= 0x500 and a + len(b) >= 0x504 for a, b in res.items())  # the fix stays in the build
    assert all(not (0x9000 <= a < 0x9010) for a in res) and all(c['to'] != 0x9000 for c in p['copies'])
    assert p['needed'] == 2 + 0x800 and p['from_disk'] + p['residue_bytes'] >= p['needed']
    for c in p['copies']:
        assert c['fnv'] == hostboot.fnv(disk[c['off']:c['off'] + c['len']])


MAIN, LOOP, L3, COPLIST = 0x1000, 0x1026, 0x1100, 0x1800
PROG = {
    COPLIST: 'fffffffe',
    MAIN: '4df900dff000'          # lea $dff000,a6
          '3d7cc020009a'          # INTENA: master + VERTB
          '41f80400'              # lea $400.w,a0
          '343c03ff'              # move.w #$3ff,d2
          '7200'                  # moveq #0,d1
          'd258'                  # s: add.w (a0)+,d1         the loaded bytes
          '51cafffc'              # dbf d2,s
          '31c14006'              # move.w d1,$4006.w
          '31f800064008'          # move.w $6.w,$4008.w       the ExecBase-like word
          '30384002'              # loop: move.w $4002,d0
          'b0784002'              # w: cmp.w $4002,d0
          '67fa'                  # beq.s w
          '52784000'              # addq.w #1,$4000
          '60f0',                 # bra.s loop
    L3: '52784002'                # addq.w #1,$4002
        '33fc002000dff09c'        # clear VERTB
        '4e73',                   # rte
}


def build(tmp_path, name, game_c, entry, defs=()):
    cc = bus.compiler()
    exe = tmp_path / name
    subprocess.run([cc, '-O1', '-I', BUS, '-I', HOST, '-I', str(tmp_path), '-DGAME_SRC="%s"' % game_c, '-DTICK_PC=0x%xu' % LOOP,
                    '-DHOST_ENTRY=%s' % entry, '-DHOST_L3=host_vec_l3', *defs,
                    os.path.join(HOST, 'arek_host_trace.c'), os.path.join(BUS, 'arek_bus.c'), os.path.join(BUS, 'arek_bus_vamiga.c'),
                    '-lm', '-o', str(exe)], check=True)
    return exe


def words(vtr):
    return [struct.unpack('>5H', x['ranges'][0][0x4000:0x400a]) for x in trace.records(str(vtr)) if x['pc'] == LOOP]


def test_a_start_from_the_disk_runs_as_the_state_at_the_entry(tmp_path):
    """The state at the entry (the loaded bytes, the fix, the vector, the Copper list in RAM) against a state with zero
    RAM + arek_boot.h made from the first run's log and the disk: the same records; another disk is refused."""
    if not bus.compiler():
        pytest.skip('no C compiler')
    disk, chip = disk_and_state()
    img = bytearray(0x2000)
    for at, hx in PROG.items():
        img[at:at + len(hx) // 2] = bytes.fromhex(hx)
    chip[0x1000:0x2000] = img[0x1000:0x2000]
    chip[0x1800:0x1804] = bytes.fromhex(PROG[COPLIST])
    chip[0x6c:0x70] = struct.pack('>I', L3)
    src, _, _ = recomp.generate(bytes(img), 0, auto=[MAIN, L3], timing=True, bus_table=True)
    (tmp_path / 'game.c').write_text(src)
    (tmp_path / 'boot_game.c').write_text('#include "game.c"\n#include "arek_host_disk.h"\n#include "arek_boot.h"\n')
    full = tmp_path / 'full'
    full.mkdir()
    (full / 'chip.bin').write_bytes(chip)
    (full / 'slow.bin').write_bytes(bytes(0x80000))
    creg = bytearray(512)
    creg[0x96:0x98] = struct.pack('>H', 0x0280)                     # DMAEN + COPEN: the Copper reads its list
    creg[0x82:0x84] = struct.pack('>H', COPLIST)
    (full / 'creg.bin').write_bytes(creg)
    (full / 'state.txt').write_text('0 0 0 0 0 0 0 0\n0 0 0 0 0 0 0 7f000\n2000 0 0 1000\nfe 0 0 0 0 5500\n100\n')
    exe = build(tmp_path, 'host_fr', 'game.c', 'f_001000', ['-DAREK_FIRSTREAD=1'])
    log = tmp_path / 'fr.txt'
    r = subprocess.run([str(exe), str(full), str(tmp_path / 'a.vtr'), '6', '--full'], capture_output=True, text=True,
                       env={**os.environ, 'AREK_FIRSTREAD': str(log)})
    assert r.returncode == 0, r.stderr
    lr = log_ranges(log)
    assert covers(lr, 0x6e) == 'c' and covers(lr, 0x1800) == 'd' and covers(lr, 0x400) == 'c'
    (tmp_path / 'disk.adf').write_bytes(disk)
    out = tmp_path / 'boot'
    p = hostboot.boot(full, out, [log], [tmp_path / 'disk.adf'])
    assert p['copies'] and p['residue_bytes'] < 64, hostboot.format_report(p)
    assert (out / 'state' / 'chip.bin').read_bytes() == bytes(0x80000)
    (tmp_path / 'arek_boot.h').write_text((out / 'arek_boot.h').read_text())
    exe2 = build(tmp_path, 'host_boot', 'boot_game.c', 'arek_boot', ['-DAREK_BOOT_GO=f_001000'])
    r2 = subprocess.run([str(exe2), str(out / 'state'), str(tmp_path / 'b.vtr'), '6', '--full'], capture_output=True, text=True,
                        env={**os.environ, 'AREK_DF0': str(tmp_path / 'disk.adf')})
    assert r2.returncode == 0, r2.stderr
    a, b = words(tmp_path / 'a.vtr'), words(tmp_path / 'b.vtr')
    assert len(a) >= 4 and a == b, (a, b)
    assert a[0][3] == sum(struct.unpack('>1024H', bytes(chip[0x400:0xc00]))) & 0xffff and a[0][4] == 0x1234
    other = bytearray(disk)
    other[0x1200] ^= 1
    (tmp_path / 'other.adf').write_bytes(other)
    r3 = subprocess.run([str(exe2), str(out / 'state'), str(tmp_path / 'c.vtr'), '2'], capture_output=True, text=True,
                        env={**os.environ, 'AREK_DF0': str(tmp_path / 'other.adf')})
    assert r3.returncode == 3 and 'not the measured bytes' in r3.stderr


def test_a_vector_into_the_kickstart_is_acknowledged(tmp_path):
    """VERTB enabled while $6c still points into the ROM (a start at the loader's entry): the host acknowledges it and
    returns - one interrupt a frame, the handler in RAM never runs, no unknown routine."""
    if not bus.compiler():
        pytest.skip('no C compiler')
    img = bytearray(0x2000)
    for at, hx in PROG.items():
        img[at:at + len(hx) // 2] = bytes.fromhex(hx)
    img[0x6c:0x70] = struct.pack('>I', 0xfc0c9a)
    src, _, _ = recomp.generate(bytes(img), 0, auto=[MAIN, L3], timing=True, bus_table=True)
    (tmp_path / 'game.c').write_text(src)
    exe = build(tmp_path, 'host_rom', 'game.c', 'f_001000')
    st = tmp_path / 'st'
    st.mkdir()
    ram = bytearray(0x80000)
    ram[:len(img)] = img
    (st / 'chip.bin').write_bytes(ram)
    (st / 'slow.bin').write_bytes(bytes(0x80000))
    creg = bytearray(512)
    creg[0x96:0x98] = struct.pack('>H', 0x0200)
    creg[0x82:0x84] = struct.pack('>H', COPLIST)
    (st / 'creg.bin').write_bytes(creg)
    (st / 'state.txt').write_text('0 0 0 0 0 0 0 0\n0 0 0 0 0 0 0 7f000\n2000 0 0 1000\nfe 0 0 0 0 5500\n100\n')
    r = subprocess.run([str(exe), str(st), str(tmp_path / 'r.vtr'), '4', '--full'], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert 'irqs 3' in r.stderr and 'unknown' not in r.stderr.replace('io_unknown', ''), r.stderr   # VERTB from the 2nd frame on
    assert [w[1] for w in words(tmp_path / 'r.vtr')] == [0]                  # the handler in RAM never ran: the loop waits


def test_cli_host_boot(tmp_path, capsys):
    from arek import cli
    disk, chip = disk_and_state()
    st = tmp_path / 'st'
    st.mkdir()
    (st / 'chip.bin').write_bytes(chip)
    (st / 'slow.bin').write_bytes(bytes(0x80000))
    (st / 'creg.bin').write_bytes(bytes(512))
    (st / 'state.txt').write_text('0 0 0 0 0 0 0 0\n0 0 0 0 0 0 0 7f000\n2000 0 0 1000\nfe 0 0 0 0 5500\n100\n')
    (tmp_path / 'fr.txt').write_text('000004 000008 c\n000400 000c00 c\n')
    (tmp_path / 'd.adf').write_bytes(disk)
    cli.main(['host', 'boot', str(st), str(tmp_path / 'out'), '--reads', str(tmp_path / 'fr.txt'), '--disk', str(tmp_path / 'd.adf')])
    o = capsys.readouterr().out
    assert 'from the disks:' in o and 'in the build:' in o and (tmp_path / 'out' / 'arek_boot.h').exists()
