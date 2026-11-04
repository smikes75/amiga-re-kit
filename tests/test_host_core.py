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


PROG3 = {
    MAIN: '4df900dff000'          # lea $dff000,a6
          '3d7cc020009a'          # move.w #$c020,$9a(a6)    INTENA: master + VERTB
          '103900bfec01'          # move.b $bfec01,d0        SDR: the key the keyboard shifted in
          '13c000004010'          # move.b d0,$4010
          '13fc00ff00bfec01'      # move.b #$ff,$bfec01      the handshake: SDR loaded with $FF
          '123900bfec01'          # move.b $bfec01,d1        reads back $FF on the hardware (G53)
          '13c100004011'          # move.b d1,$4011
          '103900bfed01'          # move.b $bfed01,d0        ICR: SP pending
          '13c000004012'          # move.b d0,$4012
          '103900bfed01'          # move.b $bfed01,d0        the read cleared it
          '13c000004013'          # move.b d0,$4013
          '30384002'              # loop: move.w $4002,d0
          'b0784002'              # w2:   cmp.w $4002,d0
          '67fa'                  #       beq.s w2
          '60f4',                 #       bra.s loop
    L3: '52784002'                # addq.w #1,$4002
        '33fc002000dff09c'        # move.w #$20,$dff09c       clear VERTB
        '4e73',                   # rte
    COPLIST: 'fffffffe',
}


def test_cia_sdr_write_is_stored(tmp_path):
    """G53 (Alien Breed II): a game's keyboard routine reads SDR, acknowledges by writing $FF into it and reads it
    again; the hardware returns $FF, the host returned the old key, so a held key repeated (AAA in the hall of
    fame). ICR reads SP once and is clear afterwards."""
    cc = bus.compiler()
    if not cc:
        pytest.skip('no C compiler')
    img = bytearray(0x2000)
    for at, hx in PROG3.items():
        img[at:at + len(hx) // 2] = bytes.fromhex(hx)
    src, _, _ = recomp.generate(bytes(img), 0, auto=[MAIN, L3], timing=True, bus_table=True)
    (tmp_path / 'game.c').write_text(src)
    exe = tmp_path / 'host_trace'
    subprocess.run([cc, '-O1', '-I', BUS, '-I', HOST, '-I', str(tmp_path), '-DGAME_SRC="game.c"', '-DTICK_PC=0x1044u',
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
    (st / 'state.txt').write_text('0 0 0 0 0 0 0 0\n0 0 0 0 0 0 0 7f000\n2000 0 0 1000\nfe bf 8 0 0 5500\n100\n')   # SDR = ~($20 << 1): space held, SP in ICR
    out = tmp_path / 'run.vtr'
    r = subprocess.run([str(exe), str(st), str(out), '2', '--full'], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    last = list(trace.records(str(out)))[-1]['ranges'][0]
    assert list(last[0x4010:0x4014]) == [0xbf, 0xff, 0x08, 0x00]
    assert 'io_unknown 0' in r.stderr


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


MAIN_IRQ, LOOP_IRQ, L3_IRQ, COPLIST_IRQ = 0x1000, 0x1046, 0x1100, 0x1800
PROG_IRQ = {
    COPLIST_IRQ: '6401fffe'          # WAIT line 100
              '009c8010'          # MOVE INTREQ, SET|COPER
              'fffffffe',
    MAIN_IRQ: '4df900dff000'         # lea $dff000,a6
           '3d7cc050009a'         # move.w #$c050,$9a(a6)   INTENA: master + COPER + BLIT
           '3d7c09f00040'         # BLTCON0: A -> D, minterm $f0
           '3d7c00000042'         # BLTCON1
           '3d7cffff0044'         # BLTAFWM
           '3d7cffff0046'         # BLTALWM
           '2d7c000050000050'     # BLTAPT = $5000
           '2d7c000060000054'     # BLTDPT = $6000
           '3d7c00000064'         # BLTAMOD
           '3d7c00000066'         # BLTDMOD
           '3d7c00410058'         # BLTSIZE: 1 line x 1 word
           '52784000'             # loop: addq.w #1,$4000
           '60fa',                #       bra.s loop
    L3_IRQ: '303900dff01e'           # move.w $dff01e,d0          INTREQR as the handler sees it
         '31c04002'               # move.w d0,$4002
         '52784004'               # addq.w #1,$4004
         '33fc005000dff09c'       # move.w #$50,$dff09c        clear COPER + BLIT
         '4e73',                  # rte
}


def test_mid_frame_start_keeps_the_coppers_irq_and_a_blit_raises_blit(tmp_path):
    """1.0.5 (Turrican II KIT-GAPS 2, 3): a trace that starts after the line where the Copper wrote INTREQ must not
    raise that frame's COPER again (the state already carries it); a blit the CPU starts sets INTREQ BLIT when it ends."""
    cc = bus.compiler()
    if not cc:
        pytest.skip('no C compiler')
    img = bytearray(0x2000)
    for at, hx in PROG_IRQ.items():
        img[at:at + len(hx) // 2] = bytes.fromhex(hx)
    src, _, _ = recomp.generate(bytes(img), 0, auto=[MAIN_IRQ, L3_IRQ], timing=True, bus_table=True)
    (tmp_path / 'game.c').write_text(src)
    exe = tmp_path / 'host_trace'
    subprocess.run([cc, '-O1', '-I', BUS, '-I', HOST, '-I', str(tmp_path), '-DGAME_SRC="game.c"', '-DTICK_PC=0x1046u',
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
    creg[0x96:0x98] = struct.pack('>H', 0x02c0)                     # DMAEN + COPEN + BLTEN
    creg[0x82:0x84] = struct.pack('>H', COPLIST_IRQ)
    (st / 'creg.bin').write_bytes(creg)
    t0 = 150 * 227                                                  # the start: line 150, after the Copper's INTREQ at line 100
    (st / 'state.txt').write_text('0 0 0 0 0 0 0 0\n0 0 0 0 0 0 0 7f000\n2000 %d 0 1000\nfe 0 0 0 0 5500\n100\n' % t0)
    out = tmp_path / 'run.vtr'
    r = subprocess.run([str(exe), str(st), str(out), '4', '--full'], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    irqs = [x for x in trace.records(str(out)) if x['pc'] == L3_IRQ]
    seen = [struct.unpack('>H', x['ranges'][0][0x4002:0x4004])[0] for x in irqs]   # record k holds what handler k-1 read
    assert len(irqs) >= 3, (len(irqs), [(x['frame'], x['v'], hex(v)) for x, v in zip(irqs, seen)], r.stderr)
    # frame 100: exactly one entry - the blit's, right after the start (no COPER: its write at line 100 lies before t0)
    first = [x for x in irqs if x['frame'] == 100]
    assert len(first) == 1 and 150 <= first[0]['v'] <= 156, [(x['frame'], x['v']) for x in irqs]
    assert seen[1] & 0x0040 and not seen[1] & 0x0010, hex(seen[1])
    # the frames after: COPER at the Copper's line, no BLIT (the blit ran once)
    later = [x for x in irqs if x['frame'] > 100]
    assert later and all(100 <= x['v'] <= 103 for x in later), [(x['frame'], x['v']) for x in later]
    assert all(v & 0x0010 and not v & 0x0040 for v in seen[2:]), [hex(v) for v in seen]


MAIN_L5, L5_HANDLER, COPLIST_L5 = 0x1000, 0x1200, 0x1800
PROG_L5 = {
    COPLIST_L5: '6401fffe'         # WAIT line 100
                '009c8800'         # MOVE INTREQ, SET|RBF (bit 11: level 5) - an intro's timing interrupt by the Copper
                'fffffffe',
    MAIN_L5: '4df900dff000'        # lea $dff000,a6
             '3d7cc800009a'        # move.w #$c800,$9a(a6)   INTENA: master + RBF
             '52784000'            # loop: addq.w #1,$4000
             '60fa',               #       bra.s loop
    L5_HANDLER: '52784004'         # addq.w #1,$4004
                '303900dff01e'     # move.w $dff01e,d0
                '31c04002'         # move.w d0,$4002
                '33fc080000dff09c' # move.w #$800,$dff09c   clear RBF
                '4e73',            # rte
    0x1300: '4e73',               # a level-3 handler that never runs (INTENA has no level-3 source)
}


def test_copper_raises_any_intreq_bit_through_the_games_vector(tmp_path):
    """1.0.6 (Turrican II KIT-GAPS 7): a Copper MOVE INTREQ,SET|RBF raises level 5 at the Copper's line; the host's
    HOST_VECTOR_HANDLER jumps through the game's vector $74 in RAM (a game that changes its vectors at run time)."""
    cc = bus.compiler()
    if not cc:
        pytest.skip('no C compiler')
    img = bytearray(0x2000)
    for at, hx in PROG_L5.items():
        img[at:at + len(hx) // 2] = bytes.fromhex(hx)
    img[0x74:0x78] = struct.pack('>I', L5_HANDLER)                  # the game's level-5 vector
    img[0x6c:0x70] = struct.pack('>I', 0x1300)                      # the level-3 vector (never taken here)
    src, _, _ = recomp.generate(bytes(img), 0, auto=[MAIN_L5, L5_HANDLER, 0x1300], timing=True, bus_table=True)
    (tmp_path / 'game.c').write_text(src)
    exe = tmp_path / 'host_trace'
    subprocess.run([cc, '-O1', '-I', BUS, '-I', HOST, '-I', str(tmp_path), '-DGAME_SRC="game.c"', '-DTICK_PC=0x100cu',
                    '-DHOST_ENTRY=f_001000', '-DHOST_L3=host_vec_l3', '-DHOST_L5=host_vec_l5',
                    os.path.join(HOST, 'arek_host_trace.c'), os.path.join(BUS, 'arek_bus.c'), os.path.join(BUS, 'arek_bus_vamiga.c'),
                    '-lm', '-o', str(exe)], check=True)
    st = tmp_path / 'state'
    st.mkdir()
    ram = bytearray(0x80000)
    ram[:len(img)] = img
    (st / 'chip.bin').write_bytes(ram)
    (st / 'slow.bin').write_bytes(bytes(0x80000))
    creg = bytearray(512)
    creg[0x96:0x98] = struct.pack('>H', 0x0280)                     # DMAEN + COPEN
    creg[0x82:0x84] = struct.pack('>H', COPLIST_L5)
    (st / 'creg.bin').write_bytes(creg)
    (st / 'state.txt').write_text('0 0 0 0 0 0 0 0\n0 0 0 0 0 0 0 7f000\n2000 0 0 1000\nfe 0 0 0 0 5500\n100\n')
    out = tmp_path / 'run.vtr'
    r = subprocess.run([str(exe), str(st), str(out), '4', '--full'], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert 'irqs 4' in r.stderr, r.stderr                                                   # one level 5 per frame
    ticks = list(trace.records(str(out)))                                                  # the spinning loop: a record per pass
    counts = [struct.unpack('>H', x['ranges'][0][0x4004:0x4006])[0] for x in ticks]
    firsts = [ticks[i] for i in range(1, len(ticks)) if counts[i] != counts[i - 1]]      # the pass right after each handler
    assert len(firsts) >= 3 and all(100 <= x['v'] <= 104 for x in firsts), [(x['frame'], x['v']) for x in firsts]   # at the Copper's line
    seen = [struct.unpack('>H', x['ranges'][0][0x4002:0x4004])[0] for x in firsts]
    assert all(v & 0x0800 and not v & 0x0010 for v in seen), [hex(v) for v in seen]        # RBF pending, no COPER


MAIN_BX, TICK_BX = 0x1000, 0x104e
PROG_BX = {
    MAIN_BX: '4df900dff000'        # lea $dff000,a6
             '3d7c84400096'        # move.w #$8440,$96(a6)   DMACON SET|BLTPRI|BLTEN
             '3d7c09f00040'        # BLTCON0 A -> D
             '3d7c00000042'        # BLTCON1
             '3d7cffff0044'        # BLTAFWM
             '3d7cffff0046'        # BLTALWM
             '2d7c000100000050'    # BLTAPT = $10000
             '2d7c000200000054'    # BLTDPT = $20000
             '3d7c00000064'        # BLTAMOD
             '3d7c00000066'        # BLTDMOD
             '3d7c74140058'        # BLTSIZE $7414: 464 lines x 20 words = 9 280 words (Turrican II's intro)
             '082e000e0002'        # w: btst #14,$2(a6)      DMACONR BBUSY
             '66f8'                #    bne.s w
             '31ee00044000'        # tick: move.w $4(a6),$4000   VPOSR when BBUSY cleared
             '31ee00064002'        #       move.w $6(a6),$4002   VHPOSR
             '60fe',               # loop: bra.s loop
    0x1300: '4e73',                # a level-3 handler that never runs
}


def test_blit_crossing_the_frame_end_goes_on_in_the_next_frame(tmp_path):
    """1.0.7 (Turrican II KIT-GAPS 10): a 9 280-word blit started at line 262 (BLTPRI on) runs past the frame end; the
    blitter must keep its slots in the next frame and BBUSY must clear ~32 lines in, as in the original - not 200 lines later."""
    cc = bus.compiler()
    if not cc:
        pytest.skip('no C compiler')
    img = bytearray(0x2000)
    for at, hx in PROG_BX.items():
        img[at:at + len(hx) // 2] = bytes.fromhex(hx)
    img[0x6c:0x70] = struct.pack('>I', 0x1300)
    src, _, _ = recomp.generate(bytes(img), 0, auto=[MAIN_BX, 0x1300], timing=True, bus_table=True)
    (tmp_path / 'game.c').write_text(src)
    exe = tmp_path / 'host_trace'
    subprocess.run([cc, '-O1', '-I', BUS, '-I', HOST, '-I', str(tmp_path), '-DGAME_SRC="game.c"', '-DTICK_PC=0x104eu',
                    '-DHOST_ENTRY=f_001000', '-DHOST_L3=host_vec_l3',
                    os.path.join(HOST, 'arek_host_trace.c'), os.path.join(BUS, 'arek_bus.c'), os.path.join(BUS, 'arek_bus_vamiga.c'),
                    '-lm', '-o', str(exe)], check=True)
    st = tmp_path / 'state'
    st.mkdir()
    ram = bytearray(0x80000)
    ram[:len(img)] = img
    (st / 'chip.bin').write_bytes(ram)
    (st / 'slow.bin').write_bytes(bytes(0x80000))
    creg = bytearray(512)
    creg[0x96:0x98] = struct.pack('>H', 0x0200)                     # DMAEN; the program adds BLTEN + BLTPRI
    creg[0x82:0x84] = struct.pack('>H', 0x1800)                     # COP1LC: an empty list
    ram[0x1800:0x1804] = bytes.fromhex('fffffffe')
    (st / 'chip.bin').write_bytes(ram)
    (st / 'creg.bin').write_bytes(creg)
    t0 = 262 * 227                                                  # the start: line 262 of frame 100, BLTSIZE right away
    (st / 'state.txt').write_text('0 0 0 0 0 0 0 0\n0 0 0 0 0 0 0 7f000\n2000 %d 0 1000\nfe 0 0 0 0 5500\n100\n' % t0)
    out = tmp_path / 'run.vtr'
    r = subprocess.run([str(exe), str(st), str(out), '3', '--full', '--own', str(tmp_path / 'own.bin')], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    ticks = [x for x in trace.records(str(out)) if x['pc'] == TICK_BX]
    assert ticks, r.stderr
    done = ticks[0]                                                 # the first pass after BBUSY cleared
    # 9 280 words x 2 slots = 18 560 slots; ~50 lines of frame 100 take ~11 200, the rest ends ~line 32-45 of frame 101
    assert done['frame'] == 101 and done['v'] < 80, (done['frame'], done['v'], done['h'])
    own = (tmp_path / 'own.bin').read_bytes()
    rec = 8 + 313 * 227                                             # H_FRAME (long) + the frame's own map (313 lines)
    frames = {}
    for i in range(0, len(own) - rec + 1, rec):
        frames[struct.unpack('<q', own[i:i + 8])[0]] = own[i + 8:i + rec]
    assert 1 in frames, sorted(frames)                              # H_FRAME 1 = the second frame of the run (frame 101)
    second = frames[1]
    bl = second.count(25)
    assert 6000 < bl < 9000, bl                                     # the rest of the blit: ~7 300 slots in the next frame
    assert second[:32 * 227].count(25) > 6000 and second[40 * 227:].count(25) == 0   # in lines 0-32, nothing after


def test_host_trace_reglog_regs_selects_the_registers(tmp_path):
    """1.0.8 (Turrican II KIT-GAPS 11): host_trace --reglog-regs 040-058 records the blitter registers; the default set does not."""
    cc = bus.compiler()
    if not cc:
        pytest.skip('no C compiler')
    img = bytearray(0x2000)
    for at, hx in PROG_BX.items():
        img[at:at + len(hx) // 2] = bytes.fromhex(hx)
    img[0x6c:0x70] = struct.pack('>I', 0x1300)
    src, _, _ = recomp.generate(bytes(img), 0, auto=[MAIN_BX, 0x1300], timing=True, bus_table=True)
    (tmp_path / 'game.c').write_text(src)
    exe = tmp_path / 'host_trace'
    subprocess.run([cc, '-O1', '-I', BUS, '-I', HOST, '-I', str(tmp_path), '-DGAME_SRC="game.c"', '-DTICK_PC=0x104eu',
                    '-DHOST_ENTRY=f_001000', '-DHOST_L3=host_vec_l3',
                    os.path.join(HOST, 'arek_host_trace.c'), os.path.join(BUS, 'arek_bus.c'), os.path.join(BUS, 'arek_bus_vamiga.c'),
                    '-lm', '-o', str(exe)], check=True)
    st = tmp_path / 'state'
    st.mkdir()
    ram = bytearray(0x80000)
    ram[:len(img)] = img
    ram[0x1800:0x1804] = bytes.fromhex('fffffffe')
    (st / 'chip.bin').write_bytes(ram)
    (st / 'slow.bin').write_bytes(bytes(0x80000))
    creg = bytearray(512)
    creg[0x96:0x98] = struct.pack('>H', 0x0200)
    creg[0x82:0x84] = struct.pack('>H', 0x1800)
    (st / 'creg.bin').write_bytes(creg)
    (st / 'state.txt').write_text('0 0 0 0 0 0 0 0\n0 0 0 0 0 0 0 7f000\n2000 0 0 1000\nfe 0 0 0 0 5500\n100\n')
    out = tmp_path / 'run.vtr'
    r = subprocess.run([str(exe), str(st), str(out), '2', '--reglog', str(tmp_path / 'r1.bin'), '--reglog-regs', '040-058,096'], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    rows = trace.read_reglog(str(tmp_path / 'r1.bin'))
    regs = [(x['reg'], x['value']) for x in rows]
    assert (0x058, 0x7414) in regs and (0x040, 0x09f0) in regs and (0x096, 0x8440) in regs, regs[:12]
    assert all(0x040 <= x['reg'] <= 0x058 or x['reg'] == 0x096 for x in rows)
    r = subprocess.run([str(exe), str(st), str(out), '2', '--reglog', str(tmp_path / 'r2.bin')], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    regs2 = [x['reg'] for x in trace.read_reglog(str(tmp_path / 'r2.bin'))]
    assert 0x096 in regs2 and 0x058 not in regs2                      # the default set: DMACON yes, BLTSIZE no
    r = subprocess.run([str(exe), str(st), str(out), '2', '--reglog', str(tmp_path / 'r3.bin'), '--reglog-regs', 'xyz'], capture_output=True, text=True)
    assert r.returncode != 0 and 'reglog-regs' in r.stderr


MAIN_SP, L3_SP, EXT_SP, TICK_SP = 0x1000, 0x1100, 0x1400, 0x1012
PROG_SP = {
    MAIN_SP: '4df900dff000'         # lea $dff000,a6
             '3d7cc020009a'         # move.w #$c020,$9a(a6)   INTENA: master + VERTB
             '4eb900001400'         # jsr $1400               the --extern (a loader replaced in C): spends two frames
             '52784000'             # tick: addq.w #1,$4000
             '60fa',                #       bra.s tick
    L3_SP: '52784002'               # addq.w #1,$4002         VERTB count
           '33fc002000dff09c'       # move.w #$20,$dff09c     clear VERTB
           '4e73',                  # rte
}
EXTERN_SP = r"""
void f_spend(M68 *m) { host_spend(m, 2.0 * 313 * 227 + 10, 0); m->a[7] += 4; }   /* the rts of the replaced routine */
"""


def test_extern_spends_the_originals_time_with_interrupts_served(tmp_path):
    """1.0.8 (Turrican II KIT-GAPS 12): an --extern that calls host_spend() moves the host's time on; the VERTB
    interrupts of the frames it covers are taken inside it, and the game resumes two frames later."""
    cc = bus.compiler()
    if not cc:
        pytest.skip('no C compiler')
    img = bytearray(0x2000)
    for at, hx in PROG_SP.items():
        img[at:at + len(hx) // 2] = bytes.fromhex(hx)
    fl = recomp.flow_from_specs(bytes(img), 0, extern=['1400=f_spend'])
    src, _, _ = recomp.generate(bytes(img), 0, auto=[MAIN_SP, L3_SP], flow=fl, timing=True, bus_table=True)
    assert 'f_spend(m)' in src
    (tmp_path / 'game.c').write_text(src + EXTERN_SP)
    exe = tmp_path / 'host_trace'
    subprocess.run([cc, '-O1', '-I', BUS, '-I', HOST, '-I', str(tmp_path), '-DGAME_SRC="game.c"', '-DTICK_PC=0x1012u',
                    '-DHOST_ENTRY=f_001000', '-DHOST_L3=f_001100', '-DHOST_L3_PC=0x1100u',
                    os.path.join(HOST, 'arek_host_trace.c'), os.path.join(BUS, 'arek_bus.c'), os.path.join(BUS, 'arek_bus_vamiga.c'),
                    '-lm', '-o', str(exe)], check=True)
    st = tmp_path / 'state'
    st.mkdir()
    ram = bytearray(0x80000)
    ram[:len(img)] = img
    ram[0x1800:0x1804] = bytes.fromhex('fffffffe')
    (st / 'chip.bin').write_bytes(ram)
    (st / 'slow.bin').write_bytes(bytes(0x80000))
    creg = bytearray(512)
    creg[0x96:0x98] = struct.pack('>H', 0x0200)
    creg[0x82:0x84] = struct.pack('>H', 0x1800)
    (st / 'creg.bin').write_bytes(creg)
    (st / 'state.txt').write_text('0 0 0 0 0 0 0 0\n0 0 0 0 0 0 0 7f000\n2000 0 0 1000\nfe 0 0 0 0 5500\n100\n')
    out = tmp_path / 'run.vtr'
    r = subprocess.run([str(exe), str(st), str(out), '4', '--full'], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    recs = list(trace.records(str(out)))
    irqs = [x for x in recs if x['pc'] == L3_SP]
    ticks = [x for x in recs if x['pc'] == TICK_SP]
    assert ticks and ticks[0]['frame'] == 102 and ticks[0]['v'] <= 1, (ticks[0]['frame'], ticks[0]['v'])   # the game resumes two frames later
    assert [x['frame'] for x in irqs[:2]] == [101, 102], [(x['frame'], x['v']) for x in irqs]            # VERTB taken inside the spend
    assert struct.unpack('>H', ticks[0]['ranges'][0][0x4002:0x4004])[0] >= 2                            # the handler ran twice before the first tick
