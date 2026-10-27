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

MAIN, LOOP, L3 = 0x1000, 0x100c, 0x1100
PROG = {
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
    (st / 'creg.bin').write_bytes(creg)
    (st / 'state.txt').write_text('0 0 0 0 0 0 0 0\n0 0 0 0 0 0 0 7f000\n2000 0 0 1000\nfe 0 0 0 0 5500\n100\n')
    out = tmp_path / 'run.vtr'
    r = subprocess.run([str(exe), str(st), str(out), '5', '--full'], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    recs = list(trace.records(str(out)))
    ticks = [x for x in recs if x['pc'] == LOOP]
    irqs = [x for x in recs if x['pc'] == L3]
    assert [x['frame'] for x in irqs] == [101, 102, 103, 104]                          # VERTB at the start of every frame after the first
    assert all(x['v'] == 0 and 10 <= x['h'] < 60 for x in irqs)                           # accepted right after the latency
    assert len(ticks) >= 5
    counters = [struct.unpack('>H', x['ranges'][0][0x4000:0x4002])[0] for x in ticks]
    frames = [struct.unpack('>H', x['ranges'][0][0x4002:0x4004])[0] for x in ticks]
    assert counters == list(range(len(ticks))) and frames == [k for k in range(len(ticks))]   # one tick per frame
    assert 'irqs 4' in r.stderr and 'io_unknown 0' in r.stderr
    lof = [struct.unpack('>H', x['ranges'][0][0x4004:0x4006])[0] >> 15 for x in irqs]
    assert lof[1:] == [1, 1, 1]                                                             # (record 0 precedes the first write) no LACE: every field long
    creg[0x100:0x102] = struct.pack('>H', 0x0004)                                            # BPLCON0 LACE
    (st / 'creg.bin').write_bytes(creg)
    r = subprocess.run([str(exe), str(st), str(out), '5', '--full'], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    irqs = [x for x in trace.records(str(out)) if x['pc'] == L3]
    assert [struct.unpack('>H', x['ranges'][0][0x4004:0x4006])[0] >> 15 for x in irqs][1:] == [0, 1, 0]   # the fields alternate


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
