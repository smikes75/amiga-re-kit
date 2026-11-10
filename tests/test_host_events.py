"""1.0.40 (the audit of 2026-11-10): events of the host that only happened when the game looked.
Synthetic games through the native engine; nothing here needs the emulator."""
import os
import struct
import subprocess

import pytest

from arek import bus, host
from arek.m68k import recomp

MAIN, L3, L6 = 0x1000, 0x1100, 0x1200


def run(tmp_path, prog, frames, auto, defines=()):
    if not bus.compiler():
        pytest.skip('no C compiler')
    img = bytearray(0x2000)
    for at, hx in prog.items():
        img[at:at + len(hx) // 2] = bytes.fromhex(hx)
    src, _, _ = recomp.generate(bytes(img), 0, auto=list(auto), timing=True, bus_table=True)
    (tmp_path / 'game.c').write_text(src)
    st = tmp_path / 'state'
    st.mkdir()
    ram = bytearray(0x80000)
    ram[:len(img)] = img
    (st / 'chip.bin').write_bytes(ram)
    creg = bytearray(512)
    creg[0x96:0x98] = struct.pack('>H', 0x0200)
    (st / 'creg.bin').write_bytes(creg)
    (st / 'state.txt').write_text('0 0 0 0 0 0 0 0\n0 0 0 0 0 0 0 7f000\n2000 0 0 1000\nfe 0 0 0 0 5500\n100\n')
    host.pack(str(st), str(tmp_path / 'state.bin'))
    host.engine_build(str(tmp_path / 'n'), str(tmp_path / 'game.c'), 'f_%06x' % L3, 'f_%06x' % MAIN, native=True, defines=list(defines))
    r = subprocess.run([str(tmp_path / 'n' / 'arek_host_engine'), str(tmp_path / 'state.bin'), str(frames), '--dump', str(tmp_path / 'out.bin')],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    mem = (tmp_path / 'out.bin').read_bytes()
    return lambda at: struct.unpack('>H', mem[at:at + 2])[0]


WAIT_VBL = ('30384002'              # loop: move.w $4002,d0
            'b0784002'              # w:    cmp.w $4002,d0
            '67fa'                  #       beq.s w
            '52784000'              #       addq.w #1,$4000
            '60f0')                 #       bra.s loop
L3_H = '52784002' '33fc002000dff09c' '4e73'          # addq.w #1,$4002; move.w #$20,$dff09c; rte


def test_a_cia_timer_interrupt_comes_when_the_timer_runs_out(tmp_path):
    """CIA-B timer A, continuous, latch 100 (101 E ticks = 505 colour clocks), its ICR mask bit and INTENA EXTER set; the
    game never reads the CIA outside the level-6 handler. Ten frames hold about 1400 underflows. Before, the timers were
    only run when the game touched a CIA register: 0 interrupts."""
    prog = {MAIN: '4df900dff000'
                  '3d7ce020009a'          # move.w #$e020,$9a(a6)     INTENA: master, EXTER, VERTB
                  '13fc008100bfdd00'      # move.b #$81,$bfdd00       ICR mask: timer A
                  '13fc006400bfd400'      # move.b #100,$bfd400       TALO
                  '13fc000000bfd500'      # move.b #0,$bfd500         TAHI
                  '13fc001100bfde00'      # move.b #$11,$bfde00       CRA: START, FORCE LOAD, continuous
                  + WAIT_VBL,
            L3: L3_H,
            L6: '52784006'                # addq.w #1,$4006
                '4a3900bfdd00'            # tst.b $bfdd00             reading the ICR clears it
                '33fc200000dff09c'        # move.w #$2000,$dff09c     clear EXTER
                '4e73'}
    w = run(tmp_path, prog, 10, [MAIN, L3, L6], defines=['HOST_L6=f_%06x' % L6])
    frames = w(0x4002)
    want = frames * 313 * 227 / 505.0
    assert frames >= 9 and abs(w(0x4006) - want) < 0.03 * want + 150, (frames, w(0x4006), want)   # ~141 a frame, the first and last frame partly


def test_a_polled_cia_timer_raises_no_interrupt(tmp_path):
    """The same timer without the ICR mask bit: the game may poll it, no interrupt is requested."""
    prog = {MAIN: '4df900dff000' '3d7ce020009a' '13fc006400bfd400' '13fc000000bfd500' '13fc001100bfde00' + WAIT_VBL,
            L3: L3_H, L6: '52784006' '4a3900bfdd00' '33fc200000dff09c' '4e73'}
    w = run(tmp_path, prog, 6, [MAIN, L3, L6], defines=['HOST_L6=f_%06x' % L6])
    assert w(0x4002) >= 5 and w(0x4006) == 0


def test_the_line_counter_wraps_inside_an_instruction_that_crosses_the_frame_end(tmp_path):
    """A game counting how often VHPOSR's high byte is $39 (line 57) must see it once a frame. The frame rolls at an
    instruction boundary, and a read made past the frame's end inside the instruction reported line 313 = $139, whose
    low byte is $39 too: twice a frame."""
    prog = {MAIN: '4df900dff000'
                  '3d7cc020009a'
                  '0c39003900dff006'      # a: cmpi.b #$39,$dff006
                  '66f6'                  #    bne.s a
                  '52784000'              #    addq.w #1,$4000
                  '0c39003900dff006'      # b: cmpi.b #$39,$dff006
                  '67f6'                  #    beq.s b
                  '60e6',                 #    bra.s a
            L3: L3_H}
    w = run(tmp_path, prog, 60, [MAIN, L3])
    frames = w(0x4002)
    assert frames >= 59 and abs(w(0x4000) - frames) <= 1, (frames, w(0x4000))
