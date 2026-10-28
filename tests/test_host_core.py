"""arek_host.h + arek_host_trace.c on a synthetic game: a loop that waits for the frame counter a level-3 handler
bumps on VERTB. The host must deliver the interrupt every frame, advance the beam a frame at a time and write
records the kit's trace reader takes."""
import os
import shutil
import struct
import subprocess

import pytest

from arek import bus, host
from arek.headless import trace
from arek.m68k import recomp

BUS = os.path.dirname(os.path.abspath(bus.__file__))
HOST = os.path.dirname(os.path.abspath(host.__file__))

MAIN, LOOP, L3, COPLIST = 0x1000, 0x100c, 0x1100, 0x1800
PROG = {
    COPLIST: 'fffffffe',          # an empty Copper list (the renderer's Copper runs from COP1LC)
    MAIN: '4df900dff000'          # lea $dff000,a6
          '3d7cc020009a'          # move.w #$c020,$9a(a6)    INTENA: master + VERTB
          '30384002'              # loop: move.w $4002,d0     the handler's frame counter
          'b0784002'              # w:    cmp.w $4002,d0
          '67fa'                  #       beq.s w
          '52784000'              #       addq.w #1,$4000     ticks
          '60f0',                 #       bra.s loop
    L3: '52784002'                # addq.w #1,$4002
        '33f900dff00400004004'    # move.w $dff004,$4004      VPOSR: LOF in bit 15
        '33fc002000dff09c'        # move.w #$20,$dff09c       clear VERTB
        '0c7800024002'            # cmpi.w #2,$4002           frame 2 of the run: LACE on
        '6608'                    # bne.s +8
        '33fc000400dff100'        # move.w #4,$dff100
        '0c7800054002'            # cmpi.w #5,$4002           frame 5: LACE off again
        '6608'                    # bne.s +8
        '33fc000000dff100'        # move.w #0,$dff100
        '4e73',                   # rte
}


def test_host_runs_a_synthetic_game(tmp_path):
    cc = bus.compiler()
    if not cc:
        pytest.skip('no C compiler')
    img = bytearray(0x2000)
    for at, hx in PROG.items():
        img[at:at + len(hx) // 2] = bytes.fromhex(hx)
    src, _, _ = recomp.generate(bytes(img), 0, auto=[MAIN, L3], timing=True, bus_table=True)
    assert 'void f_001000(' in src and 'void f_001100(' in src
    (tmp_path / 'game.c').write_text(src)
    exe = tmp_path / 'host_trace'
    subprocess.run([cc, '-O1', '-I', BUS, '-I', HOST, '-I', str(tmp_path), '-DGAME_SRC="game.c"', '-DTICK_PC=0x100cu',
                    '-DHOST_ENTRY=f_001000', '-DHOST_L3=f_001100', '-DHOST_L3_PC=0x1100u',
                    os.path.join(HOST, 'arek_host_trace.c'), os.path.join(BUS, 'arek_bus.c'), os.path.join(BUS, 'arek_bus_vamiga.c'),
                    '-lm', '-o', str(exe)], check=True)
    st = tmp_path / 'state'
    st.mkdir()
    ram = bytearray(0x80000)
    ram[:len(img)] = img
    (st / 'chip.bin').write_bytes(ram)
    (st / 'slow.bin').write_bytes(bytes(0x80000))
    creg = bytearray(512)
    creg[0x96:0x98] = struct.pack('>H', 0x0200)                     # DMAEN only: an empty frame map
    creg[0x82:0x84] = struct.pack('>H', COPLIST)                    # COP1LC
    (st / 'creg.bin').write_bytes(creg)
    (st / 'state.txt').write_text('0 0 0 0 0 0 0 0\n0 0 0 0 0 0 0 7f000\n2000 0 0 1000\nfe 0 0 0 0 5500\n100\n')
    out = tmp_path / 'run.vtr'
    r = subprocess.run([str(exe), str(st), str(out), '9', '--full'], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    recs = list(trace.records(str(out)))
    ticks = [x for x in recs if x['pc'] == LOOP]
    irqs = [x for x in recs if x['pc'] == L3]
    assert [x['frame'] for x in irqs] == list(range(101, 109))                         # VERTB at the start of every frame after the first
    assert all(x['v'] == 0 and 10 <= x['h'] < 60 for x in irqs)                           # accepted right after the latency
    assert len(ticks) >= 5
    counters = [struct.unpack('>H', x['ranges'][0][0x4000:0x4002])[0] for x in ticks]
    frames = [struct.unpack('>H', x['ranges'][0][0x4002:0x4004])[0] for x in ticks]
    assert counters == list(range(len(ticks))) and frames == [k for k in range(len(ticks))]   # one tick per frame
    assert 'irqs 8' in r.stderr and 'io_unknown 0' in r.stderr
    lof = [struct.unpack('>H', x['ranges'][0][0x4004:0x4006])[0] >> 15 for x in irqs]
    # a record at the handler's entry holds the previous handler's VPOSR: record k shows frame 100 + k. Long fields; the
    # handler sets LACE in frame 102, so the fields alternate from frame 103 on; it clears LACE in frame 105: every field
    # long again from frame 106 (not stuck short - Alien Breed II, G35)
    assert lof[1:] == [1, 1, 0, 1, 0, 1, 1]
    creg[0x100:0x102] = struct.pack('>H', 0x0004)                                            # BPLCON0 LACE
    (st / 'creg.bin').write_bytes(creg)
    r = subprocess.run([str(exe), str(st), str(out), '5', '--full'], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    irqs = [x for x in trace.records(str(out)) if x['pc'] == L3]
    assert [struct.unpack('>H', x['ranges'][0][0x4004:0x4006])[0] >> 15 for x in irqs][1:] == [0, 1, 0]   # the fields alternate
    # LACE set by the Copper every frame (the CPU's writes in frames 102 / 105 lose): the fields alternate throughout (G39)
    creg[0x100:0x102] = struct.pack('>H', 0)
    (st / 'creg.bin').write_bytes(creg)
    ram[COPLIST:COPLIST + 8] = bytes.fromhex('01000004fffffffe')
    (st / 'chip.bin').write_bytes(ram)
    r = subprocess.run([str(exe), str(st), str(out), '9', '--full'], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    irqs = [x for x in trace.records(str(out)) if x['pc'] == L3]
    assert [struct.unpack('>H', x['ranges'][0][0x4004:0x4006])[0] >> 15 for x in irqs][1:] == [0, 1, 0, 1, 0, 1, 0]


def test_state_from_a_capture(tmp_path):
    cap = tmp_path / 'cap'
    cap.mkdir()
    (cap / 'ram.bin').write_bytes(bytes(range(256)) * 16)
    (cap / 'extra.bin').write_bytes(b'\x11' * 1000)
    meta = {'d': list(range(8)), 'a': [0x10, 0x20, 0x30, 0x40, 0x50, 0x60, 0x70, 0x7f000], 'pc': 0x1000,
            'ccr': {'x': 1, 'n': 0, 'z': 1, 'v': 0, 'c': 0}, 'beam': {'clock': 1, 'frame': 1234, 'position': [100, 50]},
            'ram_file': 'ram.bin', 'regions': [{'base': 0xc00000, 'length': 1000, 'file': 'extra.bin'}],
            'chips': {'agnus': {'DMACON': 0x83e0}, 'paula': {'INTREQ': 0x20}, 'ciaa': {'PRA': 0x7e}}}
    import json
    (cap / 'cpu.json').write_text(json.dumps(meta))
    r = host.state(str(cap), str(tmp_path / 'st'))
    st = tmp_path / 'st'
    assert (st / 'chip.bin').stat().st_size == 0x80000 and (st / 'chip.bin').read_bytes()[:4] == bytes([0, 1, 2, 3])
    assert (st / 'slow.bin').read_bytes()[:3] == b'\x11\x11\x11' and (st / 'slow.bin').stat().st_size == 0x80000
    assert (st / 'creg.bin').read_bytes()[0x96:0x98] == bytes.fromhex('83e0')
    lines = (st / 'state.txt').read_text().splitlines()
    assert lines[0] == '0 1 2 3 4 5 6 7' and lines[1].endswith('7f000')
    assert lines[2] == '2014 %d 20 1000' % (100 * 227 + 50) and lines[3].startswith('7e ') and lines[4] == '1234'
    assert r['sr'] == 0x2014 and r['frame'] == 1234
    from arek import cli
    assert cli.main(['host', 'state', str(cap), str(tmp_path / 'st2')]) == 0 and (tmp_path / 'st2' / 'state.txt').exists()


# POTGO's output bits read back in POTGOR (G40) and CIA-B timer A counts E ticks (G38): the game writes POTGO three
# times and records POTGOR, then waits for a one-shot timer of 100 ticks and records VHPOSR before and after
PROG2 = {
    MAIN: '4df900dff000'          # lea $dff000,a6
          '3d7cc020009a'          # move.w #$c020,$9a(a6)    INTENA: master + VERTB
          '3d7caa010034'          # move.w #$aa01,$34(a6)    POTGO: every pin an output, driven low
          '31ee00164010'          # move.w $16(a6),$4010     POTGOR
          '3d7cff010034'          # move.w #$ff01,$34(a6)    driven high
          '31ee00164012'          # move.w $16(a6),$4012
          '3d7c00010034'          # move.w #$0001,$34(a6)    no outputs: the pins keep their state
          '31ee00164014'          # move.w $16(a6),$4014
          '13fc006400bfd400'      # move.b #100,$bfd400      CIA-B TALO
          '13fc000000bfd500'      # move.b #0,$bfd500        TAHI
          '31ee00064016'          # move.w $6(a6),$4016      VHPOSR before
          '13fc001900bfde00'      # move.b #$19,$bfde00      CRA: START, ONESHOT, FORCE LOAD
          '0839000000bfdd00'      # w: btst #0,$bfdd00       ICR: timer A underflow?
          '67f6'                  #    beq.s w
          '31ee00064018'          # move.w $6(a6),$4018      VHPOSR after
          '30384002'              # loop: move.w $4002,d0
          'b0784002'              # w2:   cmp.w $4002,d0
          '67fa'                  #       beq.s w2
          '60f4',                 #       bra.s loop
    L3: '52784002'                # addq.w #1,$4002
        '33fc002000dff09c'        # move.w #$20,$dff09c       clear VERTB
        '4e73',                   # rte
    COPLIST: 'fffffffe',
}


def test_potgo_readback_and_cia_timer(tmp_path):
    cc = bus.compiler()
    if not cc:
        pytest.skip('no C compiler')
    img = bytearray(0x2000)
    for at, hx in PROG2.items():
        img[at:at + len(hx) // 2] = bytes.fromhex(hx)
    src, _, _ = recomp.generate(bytes(img), 0, auto=[MAIN, L3], timing=True, bus_table=True)
    (tmp_path / 'game.c').write_text(src)
    exe = tmp_path / 'host_trace'
    subprocess.run([cc, '-O1', '-I', BUS, '-I', HOST, '-I', str(tmp_path), '-DGAME_SRC="game.c"', '-DTICK_PC=0x105eu',
                    '-DHOST_ENTRY=f_001000', '-DHOST_L3=f_001100', os.path.join(HOST, 'arek_host_trace.c'),
                    os.path.join(BUS, 'arek_bus.c'), os.path.join(BUS, 'arek_bus_vamiga.c'), '-lm', '-o', str(exe)], check=True)
    st = tmp_path / 'state'
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
    out = tmp_path / 'run.vtr'
    r = subprocess.run([str(exe), str(st), str(out), '3', '--full'], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    last = list(trace.records(str(out)))[-1]['ranges'][0]
    potgor = struct.unpack('>3H', last[0x4010:0x4016])
    assert potgor == (0x0000, 0x5500, 0x5500)                                               # outputs low, high, then inputs keep the state
    before, after = struct.unpack('>2H', last[0x4016:0x401a])
    t0, t1 = (before >> 8) * 227 + (before & 0xff), (after >> 8) * 227 + (after & 0xff)
    assert 100 * 5 <= t1 - t0 <= 100 * 5 + 60                                              # 100 E ticks of 5 CCK, then the poll and the stores
    assert 'io_unknown 0' in r.stderr
