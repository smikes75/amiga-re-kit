"""1.0.40 (the audit of 2026-11-10): events of the host that only happened when the game looked.
Synthetic games through the native engine; nothing here needs the emulator."""
import os
import struct
import subprocess

import pytest

from arek import bus, host
from arek.m68k import recomp

MAIN, L3, L6 = 0x1000, 0x1100, 0x1200


def run(tmp_path, prog, frames, auto, defines=(), args=(), cia='', intreq=0):
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
    (st / 'state.txt').write_text('0 0 0 0 0 0 0 0\n0 0 0 0 0 0 0 7f000\n2000 0 %x 1000\nfe 0 0 0 0 5500\n100\n' % intreq + cia)
    host.pack(str(st), str(tmp_path / 'state.bin'))
    host.engine_build(str(tmp_path / 'n'), str(tmp_path / 'game.c'), 'f_%06x' % L3, 'f_%06x' % MAIN, native=True, defines=list(defines))
    r = subprocess.run([str(tmp_path / 'n' / 'arek_host_engine'), str(tmp_path / 'state.bin'), str(frames), '--dump', str(tmp_path / 'out.bin')] + list(args),
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    mem = (tmp_path / 'out.bin').read_bytes()
    w = lambda at: struct.unpack('>H', mem[at:at + 2])[0]
    w.lines = r.stdout.splitlines()
    return w


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


@pytest.mark.parametrize('cia', ['', 'ffff ffff 0 ffff ffff 0 0 0  64 30 1 ffff ffff 0 1 0\n'])
def test_a_captured_state_keeps_its_running_cia_timer(tmp_path, cia):
    """1.0.49 (SWIV): a state taken in the middle of a game - the game set CIA-B timer A up long before and never
    touches it again. state.txt's CIA line (latch 100, counter 48, running, mask bit set) keeps the level-6 interrupts
    coming, ~141 a frame; without the line the host's CIAs are at reset and there are none."""
    prog = {MAIN: '4df900dff000' '3d7ce020009a' + WAIT_VBL,       # INTENA: master, EXTER, VERTB
            L3: L3_H,
            L6: '52784006' '4a3900bfdd00' '33fc200000dff09c' '4e73'}
    w = run(tmp_path, prog, 10, [MAIN, L3, L6], defines=['HOST_L6=f_%06x' % L6], cia=cia)
    frames = w(0x4002)
    want = frames * 313 * 227 / 505.0 if cia else 0
    assert frames >= 9 and abs(w(0x4006) - want) < 0.03 * want + (150 if cia else 1), (frames, w(0x4006), want)


@pytest.mark.parametrize('model', [0, 1])
def test_the_instruction_an_interrupt_is_taken_after(tmp_path, model):
    """1.0.50 (SWIV KIT-GAPS 7), opt-in -DHOST_IPL_MODEL=1: VERTB is pending and the game enables it with a write to
    INTENA. The original (vAmiga, SWIV's boot) runs ONE more instruction before the interrupt - the level is on the
    68000's pins only after the write's instruction has sampled them. Without the model the host takes it right after
    the write (the stacked PC is the lea), with it after the lea (the moveq)."""
    prog = {MAIN: '4df900dff000'          # 1000: lea $dff000,a6
                  '33fcc02000dff09a'      # 1006: move.w #$c020,$dff09a   INTENA: master + VERTB
                  '41fa0100'              # 100e: lea $100(pc),a0
                  '7064'                  # 1012: moveq #100,d0
                  + WAIT_VBL,             # 1014: the frame loop
            L3: '4a78400c' '6610'         # tst.w $400c; bne.s skip       the first interrupt only
                '31ef00024008'            # move.w 2(a7),$4008            the stacked PC, high word
                '31ef0004400a'            # move.w 4(a7),$400a            low word
                '5278400c'                # addq.w #1,$400c
                + L3_H}                   # skip: addq.w #1,$4002; move.w #$20,$dff09c; rte
    w = run(tmp_path, prog, 2, [MAIN, L3], defines=['HOST_IPL_MODEL=1'] if model else [], intreq=0x20)
    assert w(0x4008) == 0 and w(0x400a) == (0x1012 if model else 0x100e), hex(w(0x400a))


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


def test_every_key_event_reaches_the_game_one_per_frame(tmp_path):
    """1.0.43: a press, its release and another press sent before the game's next frame. The engine kept one event: the
    game saw only the last (a quick tap was lost; a lost release is a key held for good). The level-3 handler here
    notes every new value of CIA-A SDR ($BFEC01 = ~((code << 1) | released))."""
    prog = {MAIN: '4df900dff000' '3d7cc020009a' + WAIT_VBL,
            L3: '103900bfec01'          # move.b $bfec01,d0
                'b0384010'              # cmp.b $4010,d0
                '6714'                  # beq.s skip
                '11c04010'              # move.b d0,$4010
                '32384012'              # move.w $4012,d1
                '41f84020'              # lea $4020,a0
                '11801000'              # move.b d0,(a0,d1.w)
                '52784012'              # addq.w #1,$4012
                + L3_H}                 # skip: the frame counter, the acknowledge, rte
    w = run(tmp_path, prog, 8, [MAIN, L3], args=['--keys', 'none', '--key', '20:1', '--key', '20:0', '--key', '21:1'])
    assert w(0x4012) == 3 and (w(0x4020), w(0x4022) >> 8) == (0xbfbe, 0xbd), (w(0x4012), hex(w(0x4020)), hex(w(0x4022)))


def test_a_restart_is_the_first_run_again(tmp_path):
    """1.0.43: engine_init a second time in the same process (the page's restart). The game notes CIA-B timer A's low
    byte before it starts the timer, and counts frames; the host kept the timer running from the first run, went on
    counting frames, and the two runs differed."""
    prog = {MAIN: '4df900dff000'
                  '13f900bfd40000004010'  # move.b $bfd400,$4010      the timer as the game finds it
                  '3d7cc020009a'
                  '13fc006400bfd400' '13fc000000bfd500' '13fc001100bfde00'   # latch 100, START + FORCE LOAD, continuous
                  + WAIT_VBL,
            L3: L3_H}
    w = run(tmp_path, prog, 6, [MAIN, L3], args=['--keys', 'none', '--twice'])
    assert len(w.lines) == 2 and w.lines[0] == w.lines[1], w.lines
    assert w(0x4010) >> 8 == 0xff                                            # a stopped timer at its first value


def test_cia_accesses_wait_for_the_e_clock_as_the_original(tmp_path):
    """1.0.51 (SWIV KIT-GAPS 7), -DHOST_IPL_MODEL=1: a CIA access waits for E clock position 2 and for the next cycle's
    when that is less than 6 clocks away (vAmiga Agnus::syncWithEClock) - 6 to 15 clocks, worked out 2 clocks into the
    bus cycle, at the place the 68000 makes the access (before the instruction's last prefetch; the write of bclr after
    it). Measured on SWIV's VBL handler against vAmiga: 56 of 56 times equal over two frames (before: -3 and -2 colour
    clocks at the first two CIA instructions). Here the same rule in Python against the host's pc log."""
    import os
    from arek import bus as busmod
    cc = busmod.compiler()
    if not cc:
        pytest.skip('no C compiler')
    HOST = os.path.dirname(host.__file__)
    BUS = os.path.dirname(busmod.__file__)
    code = ('41f900bfe001'      # 1000 lea $bfe001,a0
            '4a10'              # 1006 tst.b (a0)
            '08100006'          # 1008 btst #6,(a0)
            '10280d00'          # 100c move.b $d00(a0),d0
            '08a800060e00'      # 1010 bclr #6,$e00(a0)
            '11400e00'          # 1016 move.b d0,$e00(a0)
            '4e71'              # 101a nop
            '52b84000' '60fa')  # 101c addq.l #1,$4000; bra.s 101c
    img = bytearray(0x2000)
    img[0x1000:0x1000 + len(code) // 2] = bytes.fromhex(code)
    img[0x1100:0x1102] = bytes.fromhex('4e73')
    src, _, _ = recomp.generate(bytes(img), 0, auto=[0x1000, 0x1100], timing=True, bus_table=True)
    (tmp_path / 'game.c').write_text(src)
    exe = tmp_path / 'host_trace'
    subprocess.run([cc, '-O1', '-I', BUS, '-I', HOST, '-I', str(tmp_path), '-DGAME_SRC="game.c"', '-DTICK_PC=0x101cu', '-DHOST_IPL_MODEL=1',
                    '-DHOST_ENTRY=f_001000', '-DHOST_L3=f_001100', os.path.join(HOST, 'arek_host_trace.c'), os.path.join(BUS, 'arek_bus.c'),
                    os.path.join(BUS, 'arek_bus_vamiga.c'), '-lm', '-o', str(exe)], check=True)
    pcs = [0x1006, 0x1008, 0x100c, 0x1010, 0x1016, 0x101a]
    (tmp_path / 'pcs.txt').write_text(''.join('%x\n' % p for p in pcs))
    for frame in (100, 101, 103):                       # the E clock's position at a frame's start: (2 * frame) mod 10
        for t0 in (100 * 227 + 60, 100 * 227 + 61, 100 * 227 + 63):
            st = tmp_path / ('state_%d_%d' % (frame, t0))
            st.mkdir()
            ram = bytearray(0x80000)
            ram[:len(img)] = img
            (st / 'chip.bin').write_bytes(ram)
            (st / 'slow.bin').write_bytes(bytes(0x80000))
            (st / 'creg.bin').write_bytes(bytes(512))
            (st / 'state.txt').write_text('0 0 0 0 0 0 0 0\n0 0 0 0 0 0 0 7f000\n2700 %d 0 1000\nfe 0 0 0 0 5500\n%d\n' % (t0, frame))
            log = tmp_path / 'pc.txt'
            r = subprocess.run([str(exe), str(st), str(tmp_path / 'o.vtr'), '1', '--pclog', str(log), str(tmp_path / 'pcs.txt')],
                               capture_output=True, text=True, timeout=60)
            assert r.returncode == 0, r.stderr
            got = {}
            for line in log.read_text().splitlines():
                f, pc, v, h = line.split()
                got.setdefault(int(pc, 16), int(v) * 227 + int(h))

            def wait(clk):                               # clk: CPU clocks into the frame at the start of the bus cycle
                e = (2 * frame + clk + 2) % 10
                d = (2 - e) % 10
                return d + 10 if d < 6 else d
            t = 2 * got[0x1006]
            want = {0x1006: t}
            t += 8 + wait(t)                             # tst.b (a0): the read, then the prefetch
            want[0x1008] = t
            t += 12 + wait(t + 4)                        # btst #6,(a0): the bit number, the read, the prefetch
            want[0x100c] = t
            t += 12 + wait(t + 4)                        # move.b d16(a0),d0
            want[0x1010] = t
            d1 = wait(t + 8)                             # bclr #6,d16(a0): two words, the read, the prefetch, the write
            t += 20 + d1 + wait(t + 8 + d1 + 4 + 4)
            want[0x1016] = t
            t += 12 + wait(t + 4)                        # move.b d0,d16(a0): the displacement, the write, the prefetch
            want[0x101a] = t
            assert {p: 2 * got[p] for p in pcs} == want, (frame, t0, got, want)


def test_a_faster_cpu_runs_more_instructions_a_frame(tmp_path):
    """1.0.51 (Turrican II KIT-GAPS 34): HOST_CPU_SPEED / engine_cpu_speed(n) - n sixteenths of the 68000's time per
    instruction. The frames stay frames (one VERTB each); the loop gets through twice the passes at 8, and 16 is the
    host as it was, to the byte."""
    import os
    from arek import bus as busmod
    from arek.headless import trace
    cc = busmod.compiler()
    if not cc:
        pytest.skip('no C compiler')
    HOST = os.path.dirname(host.__file__)
    BUS = os.path.dirname(busmod.__file__)
    img = bytearray(0x2000)
    code = '4df900dff000' '3d7cc020009a' '52b84010' '60fa'      # INTENA: master + VERTB; 100c: addq.l #1,$4010; bra.s 100c
    img[0x1000:0x1000 + len(code) // 2] = bytes.fromhex(code)
    img[0x1100:0x1100 + len(L3_H) // 2] = bytes.fromhex(L3_H)
    src, _, _ = recomp.generate(bytes(img), 0, auto=[0x1000, 0x1100], timing=True, bus_table=True)
    (tmp_path / 'game.c').write_text(src)
    exe = tmp_path / 'host_trace'
    subprocess.run([cc, '-O1', '-I', BUS, '-I', HOST, '-I', str(tmp_path), '-DGAME_SRC="game.c"', '-DTICK_PC=0x100cu',
                    '-DHOST_ENTRY=f_001000', '-DHOST_L3=f_001100', os.path.join(HOST, 'arek_host_trace.c'), os.path.join(BUS, 'arek_bus.c'),
                    os.path.join(BUS, 'arek_bus_vamiga.c'), '-lm', '-o', str(exe)], check=True)
    st = tmp_path / 'state'
    st.mkdir()
    ram = bytearray(0x80000)
    ram[:len(img)] = img
    (st / 'chip.bin').write_bytes(ram)
    (st / 'slow.bin').write_bytes(bytes(0x80000))
    (st / 'creg.bin').write_bytes(bytes(512))
    (st / 'state.txt').write_text('0 0 0 0 0 0 0 0\n0 0 0 0 0 0 0 7f000\n2000 0 0 1000\nfe 0 0 0 0 5500\n100\n')

    def go(speed):
        env = {k: v for k, v in os.environ.items() if k != 'HOST_CPU_SPEED'}
        if speed is not None:
            env['HOST_CPU_SPEED'] = str(speed)
        out = tmp_path / ('o%s.vtr' % speed)
        r = subprocess.run([str(exe), str(st), str(out), '3'], capture_output=True, text=True, timeout=60, env=env)
        assert r.returncode == 0, r.stderr
        recs = list(trace.records(str(out)))
        return len(recs), len({x['frame'] for x in recs}), out.read_bytes(), r.stderr
    n0, f0, b0, e0 = go(None)
    n16, f16, b16, _ = go(16)
    n8, f8, b8, e8 = go(8)
    assert b16 == b0 and n0 > 1000
    assert f8 == f0 and abs(n8 - 2 * n0) < 0.02 * n0, (n0, f0, n8, f8)
    assert e8.split('irqs')[1].split()[0] == e0.split('irqs')[1].split()[0]        # as many interrupts: one VERTB a frame
