"""1.0.40 (the audit of 2026-11-10): events of the host that only happened when the game looked.
Synthetic games through the native engine; nothing here needs the emulator."""
import os
import struct
import subprocess

import pytest

from arek import bus, host
from arek.m68k import recomp

MAIN, L3, L6 = 0x1000, 0x1100, 0x1200


def run(tmp_path, prog, frames, auto, defines=(), args=(), cia='', intreq=0, t0=0):
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
    (st / 'state.txt').write_text('0 0 0 0 0 0 0 0\n0 0 0 0 0 0 0 7f000\n2000 %d %x 1000\nfe 0 0 0 0 5500\n100\n' % (t0, intreq) + cia)
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


@pytest.mark.parametrize('h,want', [(60, 0x6446), (216, 0x64e2), (217, 0x6400), (218, 0x6401), (219, 0x6502)])
def test_the_beam_position_is_read_as_agnus_reports_it(tmp_path, h, want):
    """1.0.55, -DHOST_IPL_MODEL=1 (vAmiga's peekVHPOSR): VHPOSR is the position of the access's own slot plus five colour
    clocks, and in the first two clocks of a line still with the old line number. move.w $dff006,d0 started at h: two
    prefetches, the read in slot h + 5, the value h + 10. SWIV's level 6 handler adds VHPOSR to its random seed - the
    host entered it at the original's colour clock, read 4 less and took another branch nine frames later."""
    prog = {MAIN: '303900dff006'          # move.w $dff006,d0
                  '31c04004'              # move.w d0,$4004
                  '4df900dff000' '3d7cc020009a' + WAIT_VBL,
            L3: L3_H}
    w = run(tmp_path, prog, 2, [MAIN, L3], defines=['HOST_IPL_MODEL=1'], t0=100 * 227 + h)
    assert w(0x4004) == want, hex(w(0x4004))


def test_a_cia_timer_started_by_a_load_counts_one_e_cycle_later(tmp_path):
    """1.0.55, -DHOST_IPL_MODEL=1 (vAmiga's CIA pipeline): a one-shot timer started by writing its high byte is loaded and
    started by the same write, and the load holds the first count back by one E cycle (5 colour clocks) against a timer
    started by its control register. SWIV starts its music timer the first way and restarts it the second in the
    handler: the first level 6 entry came 8 colour clocks early. Both programs make the starting write at the same
    time; the handler is entered from a 5-clock loop, so exactly 5 colour clocks apart."""
    cc = bus.compiler()
    if not cc:
        pytest.skip('no C compiler')
    HOST, BUS = os.path.dirname(host.__file__), os.path.dirname(bus.__file__)
    head = ('4df900dff000'            # 1000 lea $dff000,a6
            '3d7ce000009a'            # 1006 move.w #$e000,$9a(a6)    INTENA: master, EXTER
            '41f900bfd000'            # 100c lea $bfd000,a0
            '117c00810d00')           # 1012 move.b #$81,$d00(a0)     ICR mask: timer A
    by_cra = ('117c00640400'          # 1018 move.b #100,$400(a0)     TALO
              '117c00000500'          # 101e move.b #0,$500(a0)       TAHI: a stopped timer is loaded
              '117c00090e00')         # 1024 move.b #$09,$e00(a0)     CRA: one-shot, START
    by_load = ('117c00080e00'         # 1018 move.b #$08,$e00(a0)     CRA: one-shot, stopped
               '117c00640400'         # 101e move.b #100,$400(a0)     TALO
               '117c00000500')        # 1024 move.b #0,$500(a0)       TAHI: loads and starts
    tail = '4e71' '60fe'              # 102a nop; 102c bra.s 102c
    got = {}
    for name, body in (('cra', by_cra), ('load', by_load)):
        d = tmp_path / name
        d.mkdir()
        img = bytearray(0x2000)
        code = bytes.fromhex(head + body + tail)
        img[0x1000:0x1000 + len(code)] = code
        img[0x1100:0x1102] = bytes.fromhex('4e73')
        l6 = bytes.fromhex('4a3900bfdd00' '33fc200000dff09c' '4e73')      # tst.b $bfdd00; move.w #$2000,$dff09c; rte
        img[0x1200:0x1200 + len(l6)] = l6
        src, _, _ = recomp.generate(bytes(img), 0, auto=[0x1000, 0x1100, 0x1200], timing=True, bus_table=True)
        (d / 'game.c').write_text(src)
        exe = d / 'host_trace'
        subprocess.run([cc, '-O1', '-I', BUS, '-I', HOST, '-I', str(d), '-DGAME_SRC="game.c"', '-DTICK_PC=0x1100u', '-DHOST_IPL_MODEL=1',
                        '-DHOST_ENTRY=f_001000', '-DHOST_L3=f_001100', '-DHOST_L6=f_001200', os.path.join(HOST, 'arek_host_trace.c'),
                        os.path.join(BUS, 'arek_bus.c'), os.path.join(BUS, 'arek_bus_vamiga.c'), '-lm', '-o', str(exe)], check=True)
        st = d / 'state'
        st.mkdir()
        ram = bytearray(0x80000)
        ram[:len(img)] = img
        (st / 'chip.bin').write_bytes(ram)
        (st / 'slow.bin').write_bytes(bytes(0x80000))
        (st / 'creg.bin').write_bytes(bytes(512))
        (st / 'state.txt').write_text('0 0 0 0 0 0 0 0\n0 0 0 0 0 0 0 7f000\n2000 %d 0 1000\nfe 0 0 0 0 5500\n100\n' % (100 * 227 + 60))
        (d / 'pcs.txt').write_text('102a\n1200\n')
        r = subprocess.run([str(exe), str(st), str(d / 'o.vtr'), '1', '--pclog', str(d / 'pc.txt'), str(d / 'pcs.txt')],
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        t = {}
        for line in (d / 'pc.txt').read_text().splitlines():
            f, pc, v, hh = line.split()
            t.setdefault(int(pc, 16), int(v) * 227 + int(hh))
        got[name] = t
    assert got['cra'][0x102a] == got['load'][0x102a], got
    # the interrupt is requested in the E cycle the counter reaches 0: 100 counts, the first one in the third (fourth)
    # E cycle after the write - about 102 E cycles after the instruction behind the write
    assert 500 < got['cra'][0x1200] - got['cra'][0x102a] < 540, got
    assert got['load'][0x1200] - got['cra'][0x1200] == 5, got


def test_vertb_reaches_the_pins_three_colour_clocks_into_the_frame(tmp_path):
    """1.0.55, -DHOST_IPL_MODEL=1 (vAmiga: VERTB is requested at colour clock 0, iplPipe takes 3): the interrupt is taken
    after the first instruction that samples the pins (one colour clock into its bus cycle) at clock 3 or later -
    1.0.50 had 4, and SWIV's boot met an instruction that started at clock 2 of frame 2146. A sled of exg (6 clocks) through
    the frame's end from eight start times; the instruction the handler returns to is the one behind the first that
    started at clock 2 or later."""
    cc = bus.compiler()
    if not cc:
        pytest.skip('no C compiler')
    HOST, BUS = os.path.dirname(host.__file__), os.path.dirname(bus.__file__)
    img = bytearray(0x2000)
    code = bytes.fromhex('c141' * 60 + '60fe')            # exg d0,d1: 6 clocks, so the starts fall on odd and even colour clocks
    img[0x1000:0x1000 + len(code)] = code
    l3 = bytes.fromhex('33fc002000dff09c' '4e73')
    img[0x1100:0x1100 + len(l3)] = l3
    src, _, _ = recomp.generate(bytes(img), 0, auto=[0x1000, 0x1100], timing=True, bus_table=True)
    (tmp_path / 'game.c').write_text(src)
    exe = tmp_path / 'host_trace'
    subprocess.run([cc, '-O1', '-I', BUS, '-I', HOST, '-I', str(tmp_path), '-DGAME_SRC="game.c"', '-DTICK_PC=0x1100u', '-DHOST_L3_PC=0x1100u', '-DHOST_IPL_MODEL=1',
                    '-DHOST_ENTRY=f_001000', '-DHOST_L3=f_001100', os.path.join(HOST, 'arek_host_trace.c'), os.path.join(BUS, 'arek_bus.c'),
                    os.path.join(BUS, 'arek_bus_vamiga.c'), '-lm', '-o', str(exe)], check=True)
    (tmp_path / 'pcs.txt').write_text(''.join('%x\n' % a for a in list(range(0x1000, 0x107a, 2)) + [0x1100]))
    creg = bytearray(512)
    creg[0x9a:0x9c] = struct.pack('>H', 0x4020)
    at_two = 0
    for d in range(8):
        st = tmp_path / ('state%d' % d)
        st.mkdir()
        ram = bytearray(0x80000)
        ram[:len(img)] = img
        (st / 'chip.bin').write_bytes(ram)
        (st / 'slow.bin').write_bytes(bytes(0x80000))
        (st / 'creg.bin').write_bytes(creg)
        (st / 'state.txt').write_text('0 0 0 0 0 0 0 0\n0 0 0 0 0 0 0 7f000\n2000 %d 0 1000\nfe 0 0 0 0 5500\n100\n' % (312 * 227 + 190 + d))
        r = subprocess.run([str(exe), str(st), str(tmp_path / 'o.vtr'), '2', '--pclog', str(tmp_path / 'pc.txt'), str(tmp_path / 'pcs.txt')],
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        rows = []
        for line in (tmp_path / 'pc.txt').read_text().splitlines():
            f, pc, v, h = line.split()
            rows.append((int(pc, 16), (int(f) - 101) * 313 * 227 + int(v) * 227 + int(h)))
        k = next(i for i, (pc, _) in enumerate(rows) if pc == 0x1100)
        starts = [t for _, t in rows[:k]]                  # the last one is the instruction the handler returns to
        first = next(i for i, t in enumerate(starts) if t >= 2)
        at_two += starts[first] == 2
        assert k - 1 == first + 1, (d, rows[max(0, k - 6):k + 1])
    assert at_two, 'no start time put an instruction on colour clock 2: the case 3 and 4 differ in'


def test_the_register_log_has_the_slot_of_the_write(tmp_path):
    """1.0.56 (SWIV), -DHOST_IPL_MODEL=1: host_trace --reglog stamps a CPU write with the write's own slot, as the
    emulator's VAHL_REGLOG does - not with the model's time behind the cycle (every write of SWIV's boot was one colour
    clock late against the original's log while the instruction times were equal). move.w #$40,$dff0a6 started at
    h = 60: three prefetches, the write's cycle from 66, its slot 67."""
    cc = bus.compiler()
    if not cc:
        pytest.skip('no C compiler')
    HOST, BUS = os.path.dirname(host.__file__), os.path.dirname(bus.__file__)
    img = bytearray(0x2000)
    code = bytes.fromhex('33fc004000dff0a6' '60fe')      # move.w #$40,$dff0a6; bra.s self
    img[0x1000:0x1000 + len(code)] = code
    img[0x1100:0x1102] = bytes.fromhex('4e73')
    src, _, _ = recomp.generate(bytes(img), 0, auto=[0x1000, 0x1100], timing=True, bus_table=True)
    (tmp_path / 'game.c').write_text(src)
    exe = tmp_path / 'host_trace'
    subprocess.run([cc, '-O1', '-I', BUS, '-I', HOST, '-I', str(tmp_path), '-DGAME_SRC="game.c"', '-DTICK_PC=0x1100u', '-DHOST_IPL_MODEL=1',
                    '-DHOST_ENTRY=f_001000', '-DHOST_L3=f_001100', os.path.join(HOST, 'arek_host_trace.c'), os.path.join(BUS, 'arek_bus.c'),
                    os.path.join(BUS, 'arek_bus_vamiga.c'), '-lm', '-o', str(exe)], check=True)
    st = tmp_path / 'state'
    st.mkdir()
    ram = bytearray(0x80000)
    ram[:len(img)] = img
    (st / 'chip.bin').write_bytes(ram)
    (st / 'slow.bin').write_bytes(bytes(0x80000))
    (st / 'creg.bin').write_bytes(bytes(512))
    (st / 'state.txt').write_text('0 0 0 0 0 0 0 0\n0 0 0 0 0 0 0 7f000\n2000 %d 0 1000\nfe 0 0 0 0 5500\n100\n' % (100 * 227 + 60))
    r = subprocess.run([str(exe), str(st), str(tmp_path / 'o.vtr'), '1', '--reglog', str(tmp_path / 'reg.bin')], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    recs = [struct.unpack('<4I', (tmp_path / 'reg.bin').read_bytes()[k:k + 16]) for k in range(0, (tmp_path / 'reg.bin').stat().st_size, 16)]
    assert recs == [(100, (100 << 16) | 67, (0x0a6 << 16) | 0x40, 0x1000)], recs


def test_a_copper_list_set_behind_the_frames_end_runs_a_frame_later(tmp_path):
    """1.0.63 (SWIV, landscape 4), -DHOST_IPL_MODEL=1: `move.l #$2000,$dff080` begins 7 colour clocks before the frame's
    end, its two writes land in the first clocks of the next frame - after the Copper has taken COP1LC (clock 0). The
    original runs the old list for that whole frame; the host stored the value before it rolled the frame, so its bus
    model and its picture ran the new list a frame early (SWIV: 70 836 pixels of frame 6721, other sprite slots, the
    level 6 interrupt 4 colour clocks late). List A: COLOR00 red; list B: five more moves, COLOR00 green."""
    cc = bus.compiler()
    if not cc:
        pytest.skip('no C compiler')
    HOST, BUS = os.path.dirname(host.__file__), os.path.dirname(bus.__file__)
    img = bytearray(0x2000)
    code = bytes.fromhex('23fc0000200000dff080' '60fe')      # move.l #$2000,$dff080; bra.s self
    img[0x1000:0x1000 + len(code)] = code
    img[0x1100:0x1102] = bytes.fromhex('4e73')
    src, _, _ = recomp.generate(bytes(img), 0, auto=[0x1000, 0x1100], timing=True, bus_table=True)
    (tmp_path / 'game.c').write_text(src)
    exe = tmp_path / 'host_trace'
    subprocess.run([cc, '-O1', '-I', BUS, '-I', HOST, '-I', str(tmp_path), '-DGAME_SRC="game.c"', '-DTICK_PC=0x1100u', '-DHOST_IPL_MODEL=1',
                    '-DHOST_ENTRY=f_001000', '-DHOST_L3=f_001100', os.path.join(HOST, 'arek_host_trace.c'), os.path.join(BUS, 'arek_bus.c'),
                    os.path.join(BUS, 'arek_bus_vamiga.c'), '-lm', '-o', str(exe)], check=True)
    st = tmp_path / 'state'
    st.mkdir()
    ram = bytearray(0x80000)
    ram[:len(img)] = img
    ram[0x3000:0x3008] = bytes.fromhex('01800f00' 'fffffffe')                                   # list A
    ram[0x2000:0x201c] = bytes.fromhex('01820111' * 5 + '018000f0' 'fffffffe')                  # list B
    (st / 'chip.bin').write_bytes(ram)
    (st / 'slow.bin').write_bytes(bytes(0x80000))
    creg = bytearray(512)
    creg[0x96:0x98] = struct.pack('>H', 0x0280)                                                 # DMAEN | COPEN
    creg[0x80:0x84] = struct.pack('>HH', 0, 0x3000)
    (st / 'creg.bin').write_bytes(creg)
    (st / 'state.txt').write_text('0 0 0 0 0 0 0 0\n0 0 0 0 0 0 0 7f000\n2000 %d 0 1000\nfe 0 0 0 0 5500\n100\n' % (312 * 227 + 220))
    r = subprocess.run([str(exe), str(st), str(tmp_path / 'o.vtr'), '3', '--own', str(tmp_path / 'own.bin'), '--shots', str(tmp_path / 'p'), '100:103',
                        '--reglog', str(tmp_path / 'reg.bin'), '--reglog-regs', '080-082'], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    recs = [struct.unpack('<4I', (tmp_path / 'reg.bin').read_bytes()[k:k + 16]) for k in range(0, (tmp_path / 'reg.bin').stat().st_size, 16)]
    assert [(f, vh >> 16) for f, vh, _, _ in recs] == [(101, 0), (101, 0)] and all((vh & 0xffff) > 2 for _, vh, _, _ in recs), recs   # in the new frame, after the Copper's first fetch
    frames = bus.own_frames((tmp_path / 'own.bin').read_bytes(), 100)
    cop = {f: sum(1 for o in frames[f][:313 * 227] if o == 24) for f in (101, 102)}       # 24: the Copper (AREK_BUS_COPPER)
    assert 0 < cop[101] < cop[102] and cop[102] - cop[101] == 10, cop                              # the bus: list A in frame 101, B (five moves more) in 102
    px = lambda f: (lambda d: tuple(d[(150 * 716 + 358) * 3:(150 * 716 + 358) * 3 + 3]))((tmp_path / ('p_%06d.raw' % f)).read_bytes())
    assert px(101)[0] > 200 and px(101)[1] < 40, px(101)                                          # the picture: red in frame 101
    assert px(102)[1] > 200 and px(102)[0] < 40, px(102)                                          # green in 102


def test_a_captured_running_timer_underflows_in_the_emulators_e_cycle(tmp_path):
    """1.0.56 (SWIV, a capture in the game), -DHOST_IPL_MODEL=1: the emulator's counter c of a running timer reaches 0
    c E cycles after the capture and requests its interrupt in that cycle; three colour clocks later the level is on the
    pins. The model's own counter runs two cycles behind the 8520's and took a captured value as its own: two cycles
    late. Here: CIA-B timer A one-shot, counter 48, a 5-colour-clock loop - the loop pass that samples the level ends
    1 to 5 colour clocks after it arrived."""
    cc = bus.compiler()
    if not cc:
        pytest.skip('no C compiler')
    HOST, BUS = os.path.dirname(host.__file__), os.path.dirname(bus.__file__)
    img = bytearray(0x2000)
    img[0x1000:0x1002] = bytes.fromhex('60fe')                              # bra.s self
    img[0x1100:0x1102] = bytes.fromhex('4e73')
    l6 = bytes.fromhex('4a3900bfdd00' '33fc200000dff09c' '4e73')
    img[0x1200:0x1200 + len(l6)] = l6
    src, _, _ = recomp.generate(bytes(img), 0, auto=[0x1000, 0x1100, 0x1200], timing=True, bus_table=True)
    (tmp_path / 'game.c').write_text(src)
    exe = tmp_path / 'host_trace'
    subprocess.run([cc, '-O1', '-I', BUS, '-I', HOST, '-I', str(tmp_path), '-DGAME_SRC="game.c"', '-DTICK_PC=0x1100u', '-DHOST_IPL_MODEL=1',
                    '-DHOST_ENTRY=f_001000', '-DHOST_L3=f_001100', '-DHOST_L6=f_001200', os.path.join(HOST, 'arek_host_trace.c'),
                    os.path.join(BUS, 'arek_bus.c'), os.path.join(BUS, 'arek_bus_vamiga.c'), '-lm', '-o', str(exe)], check=True)
    creg = bytearray(512)
    creg[0x9a:0x9c] = struct.pack('>H', 0x6000)                             # INTENA: master, EXTER
    (tmp_path / 'pcs.txt').write_text('1200\n')
    for h0 in (60, 61, 62, 63, 64):
        t0 = 100 * 227 + h0
        st = tmp_path / ('state%d' % h0)
        st.mkdir()
        ram = bytearray(0x80000)
        ram[:len(img)] = img
        (st / 'chip.bin').write_bytes(ram)
        (st / 'slow.bin').write_bytes(bytes(0x80000))
        (st / 'creg.bin').write_bytes(creg)
        (st / 'state.txt').write_text('0 0 0 0 0 0 0 0\n0 0 0 0 0 0 0 7f000\n2000 %d 0 1000\nfe 0 0 0 0 5500\n100\n'
                                      'ffff ffff 0 ffff ffff 0 0 0  64 30 9 ffff ffff 0 1 0\n' % t0)
        r = subprocess.run([str(exe), str(st), str(tmp_path / 'o.vtr'), '1', '--pclog', str(tmp_path / 'pc.txt'), str(tmp_path / 'pcs.txt')],
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        f, pc, v, h = (tmp_path / 'pc.txt').read_text().splitlines()[0].split()
        entered = 100 * 313 * 227 + int(v) * 227 + int(h)                   # the handler's first instruction: 44 clocks after the loop's pass
        pins = ((100 * 313 * 227 + t0) // 5 + 0x30) * 5 + 3
        assert 1 <= entered - 22 - pins <= 5, (h0, entered - 22 - pins)


def _own_slots(path, owner, lines=313):
    """(line, slot) of the slots `owner` has in a host's --own dump, frame by frame (int64 frame index + the map)."""
    data, out, n = open(path, 'rb').read(), [], lines * 227
    for k in range(0, len(data) - 8 - n + 1, 8 + n):
        m = data[k + 8:k + 8 + n]
        out.append([(i // 227, i % 227) for i in range(n) if m[i] == owner])
    return out


def _audio_host(tmp_path, code, t0, audio, dmacon, chip=None):
    cc = bus.compiler()
    if not cc:
        pytest.skip('no C compiler')
    HOST, BUS = os.path.dirname(host.__file__), os.path.dirname(bus.__file__)
    d = tmp_path / ('h%d' % t0)
    d.mkdir()
    img = bytearray(0x2000)
    prog = bytes.fromhex(code)
    img[0x1000:0x1000 + len(prog)] = prog
    img[0x1100:0x1102] = bytes.fromhex('4e73')
    src, _, _ = recomp.generate(bytes(img), 0, auto=[0x1000, 0x1100], timing=True, bus_table=True)
    (d / 'game.c').write_text(src)
    exe = d / 'host_trace'
    subprocess.run([cc, '-O1', '-I', BUS, '-I', HOST, '-I', str(d), '-DGAME_SRC="game.c"', '-DTICK_PC=0x1100u', '-DHOST_IPL_MODEL=1',
                    '-DHOST_ENTRY=f_001000', '-DHOST_L3=f_001100', os.path.join(HOST, 'arek_host_trace.c'), os.path.join(BUS, 'arek_bus.c'),
                    os.path.join(BUS, 'arek_bus_vamiga.c'), '-lm', '-o', str(exe)], check=True)
    st = d / 'state'
    st.mkdir()
    ram = bytearray(0x80000)
    ram[:len(img)] = img
    (st / 'chip.bin').write_bytes(ram)
    (st / 'slow.bin').write_bytes(bytes(0x80000))
    creg = bytearray(512)
    creg[0x96:0x98] = struct.pack('>H', dmacon)
    (st / 'creg.bin').write_bytes(creg)
    (st / 'state.txt').write_text('0 0 0 0 0 0 0 0\n0 0 0 0 0 0 0 7f000\n2000 %d 0 1000\nfe 0 0 0 0 5500\n100\n' % t0 + audio)
    for at, hx in (chip or {}).items():
        ram[at:at + len(hx) // 2] = bytes.fromhex(hx)
    (st / 'chip.bin').write_bytes(ram)
    r = subprocess.run([str(exe), str(st), str(d / 'o.vtr'), '1', '--own', str(d / 'own.bin'), '--audlog', str(d / 'aud.bin')], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    if chip is not None:                                             # channel 1's output: (line, slot, byte * volume)
        from arek.headless import trace
        return [(v, h, val) for f, v, h, val, ch in trace.read_audlog(str(d / 'aud.bin')) if ch == 1]
    return _own_slots(str(d / 'own.bin'), 5)[0]                      # channel 1's slots (owner 4 + channel) in the first frame


def test_a_captured_playing_channel_goes_on_fetching(tmp_path):
    """1.0.60 (SWIV, a capture in the game): state.txt's @audio lines (arek host state, from a capture made with a build
    that has vamiga-audstate-899da5d.patch) put Paula's channels where the original's stood. Channel 1 in the middle
    of a sample (state 011, period 400, the next period event 100 colour clocks after the start): the low byte ends,
    the next word is requested and fetched in the channel's slot ($0F) of the next line, then every 800 colour clocks.
    Without the lines the host's Paula is idle and the original's 34 audio slots a frame were none."""
    t0 = 60 * 227 + 30
    base = 100 * 313 * 227
    audio = ''.join('@audio %d 0 0 1 -1 -1 0 0 3 2 7ef8 8 0 0 0 1 0 0\n' % c for c in (0, 2, 3))
    audio += '@audio 1 1 3 1 -1 %d 0 2000 1 3e 190 40 40 6fd 80a 1 0 0\n' % (base + t0 + 100)
    slots = _audio_host(tmp_path, '60fe', t0, audio, 0x8202)
    first = (t0 + 100) // 227 + 1                                      # the line after the period event's
    assert slots and slots[0] == (first, 15), slots[:3]
    lines = [v for v, s in slots]
    assert all(s == 15 for v, s in slots) and 3 <= lines[1] - lines[0] <= 4 and len(slots) > 60, slots[:5]   # a word every 800 colour clocks (3.5 lines)
    assert _audio_host(tmp_path, '60fe', t0 + 1, '', 0x8202) == []      # no lines: no audio DMA


def test_raw_keys_of_the_input_lines_reach_the_game_through_the_keyboards_serial_port(tmp_path):
    """1.0.65 (SWIV, the second player's keys): host_trace's input lines take K<hh> / k<hh> (a raw key pressed / released,
    two lower-case hex digits) and S (space held), as the emulator's lines do with vamiga-keys-899da5d.patch, and send
    them through the host's keyboard: the code rotated and inverted in CIA-A's SDR 1610 colour clocks after the event
    (eight bits of 210) plus the CIA's cycles, ICR's SP bit, and the next code only after the game's handshake (CRA bit 6
    set and cleared). The game here polls ICR, stores SDR and the beam, and shakes hands. Line 1: left shift down; line
    2: shift up and cursor up down - the second waits for the handshake of the first; lines 5-6: space."""
    cc = bus.compiler()
    if not cc:
        pytest.skip('no C compiler')
    from arek.headless import trace
    HOST, BUS = os.path.dirname(host.__file__), os.path.dirname(bus.__file__)
    img = bytearray(0x2000)
    code = bytes.fromhex('43f900003000'            # 1000 lea $3000,a1
                         '103900bfed01'            # 1006 move.b $bfed01,d0     ICR
                         '08000003'                # 100c btst #3,d0
                         '67f4'                    # 1010 beq.s $1006
                         '7200'                    # 1012 moveq #0,d1
                         '123900bfec01'            # 1014 move.b $bfec01,d1     SDR
                         '32c1'                    # 101a move.w d1,(a1)+
                         '32f900dff004'            # 101c move.w $dff004,(a1)+  VPOSR
                         '32f900dff006'            # 1022 move.w $dff006,(a1)+  VHPOSR
                         '08f9000600bfee01'        # 1028 bset #6,$bfee01       the handshake: SP low
                         '08b9000600bfee01'        # 1030 bclr #6,$bfee01       ... and high again
                         '4e71'                    # 1038 nop                   (the record)
                         '60ca')                   # 103a bra.s $1006
    img[0x1000:0x1000 + len(code)] = code
    img[0x1100:0x1102] = bytes.fromhex('4e73')
    src, _, _ = recomp.generate(bytes(img), 0, auto=[0x1000, 0x1100], timing=True, bus_table=True)
    (tmp_path / 'game.c').write_text(src)
    exe = tmp_path / 'host_trace'
    subprocess.run([cc, '-O1', '-I', BUS, '-I', HOST, '-I', str(tmp_path), '-DGAME_SRC="game.c"', '-DTICK_PC=0x1038u', '-DHOST_IPL_MODEL=1',
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
    (tmp_path / 'in.txt').write_text('\nK60\nk60K4c\n\n\nS\n\n\n\n')
    assert trace.check_inputs(str(tmp_path / 'in.txt')) == 9 and trace.inputs_use_keys(str(tmp_path / 'in.txt'))
    r = subprocess.run([str(exe), str(st), str(tmp_path / 'o.vtr'), '9', str(tmp_path / 'in.txt'), '--full'], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    recs = list(trace.records(str(tmp_path / 'o.vtr')))
    last = recs[-1]
    got = [(trace.read(last, 0x3000 + 6 * k), trace.read(last, 0x3002 + 6 * k) & 1, trace.read(last, 0x3004 + 6 * k) >> 8) for k in range(len(recs))]
    inv = lambda c: (~((c << 1) | (c >> 7))) & 0xff
    assert [g[0] for g in got] == [inv(0x60), inv(0xe0), inv(0x4c), inv(0x40), inv(0xc0)], got       # $3f $3e $67 $7f $7e
    assert [r_['frame'] for r_ in recs] == [101, 102, 102, 105, 106]
    assert [g[2] for g in got] == [7, 7, 15, 7, 7], got          # 1610 colour clocks and the CIA's cycles: line 7; the queued code as long again after the handshake
    # without the handshake the keyboard waits (143 ms, then it resyncs bit by bit): no second code in these frames
    img[0x1028:0x1038] = bytes.fromhex('4e71' * 8)
    src, _, _ = recomp.generate(bytes(img), 0, auto=[0x1000, 0x1100], timing=True, bus_table=True)
    (tmp_path / 'game.c').write_text(src)
    subprocess.run([cc, '-O1', '-I', BUS, '-I', HOST, '-I', str(tmp_path), '-DGAME_SRC="game.c"', '-DTICK_PC=0x1038u', '-DHOST_IPL_MODEL=1',
                    '-DHOST_ENTRY=f_001000', '-DHOST_L3=f_001100', os.path.join(HOST, 'arek_host_trace.c'), os.path.join(BUS, 'arek_bus.c'),
                    os.path.join(BUS, 'arek_bus_vamiga.c'), '-lm', '-o', str(exe)], check=True)
    ram[:len(img)] = img
    (st / 'chip.bin').write_bytes(ram)
    r = subprocess.run([str(exe), str(st), str(tmp_path / 'o2.vtr'), '9', str(tmp_path / 'in.txt'), '--full'], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    recs = list(trace.records(str(tmp_path / 'o2.vtr')))
    assert [r_['frame'] for r_ in recs] == [101] and trace.read(recs[0], 0x3000) == inv(0x60)


def test_paula_fetches_before_a_later_store_of_the_same_instruction(tmp_path):
    """1.0.64 (SWIV: a wave table the game rewrites while a channel loops over one word of it): the host ran Paula at
    instruction boundaries, so a word whose slot lies inside an instruction was read after all of that instruction's
    stores - also one that comes in a later slot. `move.w #$7f7f,$2000.w` begins at slot 13 of line 60; channel 1
    fetches the word at $2000 in slot 15, the store follows. The original plays the old word ($1122) once more, the
    host played $7f7f a period early (SWIV: two samples wrong at some 60 places in 4.4 million)."""
    t0 = 60 * 227 + 13
    base = 100 * 313 * 227
    audio = ''.join('@audio %d 0 0 1 -1 -1 0 0 3 2 7ef8 8 0 0 0 1 0 0\n' % c for c in (0, 2, 3))
    audio += '@audio 1 1 2 1 %d %d 2000 2000 1 1 190 40 40 3344 3344 1 1 0 -1\n' % (base + 59 * 227 + 15, base + t0 + 300)
    out = _audio_host(tmp_path, '31fc7f7f2000' '60fe', t0, audio, 0x8202, chip={0x2000: '1122'})
    vals = [val for v, h, val in out][:6]
    assert vals[:5] == [0x44 * 64, 0x11 * 64, 0x22 * 64, 0x7f * 64, 0x7f * 64], out[:8]   # the low byte of the word that played, the old word, then the new one


def test_a_captured_request_waits_in_paula_or_in_agnus(tmp_path):
    """1.0.64: the emulator holds an audio DMA request in Paula (audDR) from the moment it is raised to the end of that
    line, then in Agnus (audxDR) until the channel's slot. The capture carried Agnus's flag only: a state taken between
    the request and the line's end lost it, the channel played a word twice and its next slot was missing (SWIV's VBL
    routine is entered at slot 110 of line 0: a channel that asked earlier in that line). REQ in the capture's line
    (Paula's) is served in the next line; REQ one line back (Agnus's) in this line; with both (the 19th field, a
    period below 114) in this line and the next. Channel 1 at line 60, slot 5; period 400, the next period event far."""
    t0 = 60 * 227 + 5
    base = 100 * 313 * 227
    other = ''.join('@audio %d 0 0 1 -1 -1 0 0 3 2 7ef8 8 0 0 0 1 0 0\n' % c for c in (0, 2, 3))
    one = lambda req, req2: other + '@audio 1 1 2 1 %d %d 0 2000 1 3e 190 40 40 6fd 80a 1 0 0%s\n' % (
        req, base + t0 + 3000, '' if req2 is None else ' %d' % req2)
    paula, agnus = base + 60 * 227, base + 59 * 227 + 15
    first = lambda audio, k: [v for v, s in _audio_host(tmp_path, '60fe', t0 + k, audio, 0x8202) if v < 70]
    assert first(one(paula, -1), 0) == [61]                             # Paula's: the next line
    assert first(one(agnus, None), 1) == [60]                           # Agnus's (a state.txt of 1.0.60-1.0.63: 18 fields): this line
    assert first(one(agnus, paula), 2) == [60, 61]                      # both
    assert first(one(-1, -1), 3) == []


@pytest.mark.parametrize('h0, line', [(216, 61), (218, 62)])
def test_paula_takes_dmacon_two_colour_clocks_after_the_write(tmp_path, h0, line):
    """1.0.60 (SWIV, frame 15193): the chips take DMACON two colour clocks after the CPU's write (vAmiga
    recordRegisterChange). move.w #$8202,$dff096 started at h0 of line 60 writes in slot h0 + 7: from slot 223 the channel is
    on in line 60 and its first word comes in line 61; from slot 225 it is on in line 61 and the word comes in line 62 - the host started the channel a line early and the blit beside it ended two slots late."""
    audio = ''.join('@audio %d 0 0 1 -1 -1 0 0 3 2 7ef8 8 0 0 0 1 0 0\n' % c for c in (0, 2, 3))
    audio += '@audio 1 0 0 1 -1 -1 2000 2000 10 10 190 40 40 0 0 1 0 0\n'
    slots = _audio_host(tmp_path, '33fc820200dff096' '60fe', 60 * 227 + h0, audio, 0x8200)
    assert slots and slots[0] == (line, 15), slots[:3]


@pytest.mark.parametrize('by_tick', [False, True])
def test_input_lines_by_the_ticks_hits_as_the_emulator_takes_them(tmp_path, by_tick):
    """1.0.61 (SWIV, frame 16337): the emulator takes the next input line at the first breakpoint hit of a frame on lines
    0-99. A frame whose VBL handler starts lower takes none, and the original is one line behind from then on - the host,
    which went by the frame number, was not. host_trace --inputs-v LO:HI follows the emulator's rule. Here the game
    masks interrupts over a frame's start once: the handler of frame 104 runs at line 150 and reads the joystick."""
    cc = bus.compiler()
    if not cc:
        pytest.skip('no C compiler')
    HOST, BUS = os.path.dirname(host.__file__), os.path.dirname(bus.__file__)
    main = ('4df900dff000' '3d7cc020009a'                 # lea $dff000,a6; move.w #$c020,$9a(a6)
            '0c7800034000' '66f8'                         # loop: cmpi.w #3,$4000; bne.s loop        three frames
            '46fc2700'                                    # move.w #$2700,sr
            '0c39009600dff006' '66f6'                     # w1: cmpi.b #150,$dff006; bne.s w1          line 150 of frame 103
            '0c39000a00dff006' '66f6'                     # w2: cmpi.b #10,$dff006; bne.s w2           line 10 of frame 104
            '0c39009600dff006' '66f6'                     # w3: line 150 of frame 104
            '46fc2000' '60fe')                            # move.w #$2000,sr; bra.s self
    l3 = '33f900dff00c00dff180' '52784000' '33fc002000dff09c' '4e73'   # move.w JOY1DAT,COLOR00; addq.w #1,$4000; ack; rte
    img = bytearray(0x2000)
    for at, hx in ((0x1000, main), (0x1100, l3)):
        b = bytes.fromhex(hx)
        img[at:at + len(b)] = b
    src, _, _ = recomp.generate(bytes(img), 0, auto=[0x1000, 0x1100], timing=True, bus_table=True)
    (tmp_path / 'game.c').write_text(src)
    exe = tmp_path / 'host_trace'
    subprocess.run([cc, '-O1', '-I', BUS, '-I', HOST, '-I', str(tmp_path), '-DGAME_SRC="game.c"', '-DTICK_PC=0x1100u', '-DHOST_L3_PC=0x1100u',
                    '-DHOST_IPL_MODEL=1', '-DHOST_ENTRY=f_001000', '-DHOST_L3=f_001100', os.path.join(HOST, 'arek_host_trace.c'),
                    os.path.join(BUS, 'arek_bus.c'), os.path.join(BUS, 'arek_bus_vamiga.c'), '-lm', '-o', str(exe)], check=True)
    st = tmp_path / 'state'
    st.mkdir()
    ram = bytearray(0x80000)
    ram[:len(img)] = img
    (st / 'chip.bin').write_bytes(ram)
    (st / 'slow.bin').write_bytes(bytes(0x80000))
    (st / 'creg.bin').write_bytes(bytes(512))
    (st / 'state.txt').write_text('0 0 0 0 0 0 0 0\n0 0 0 0 0 0 0 7f000\n2000 300 0 1000\nfe 0 0 0 0 5500\n100\n')
    (tmp_path / 'inp.txt').write_text('\nR\nL\nU\nD\nRU\nLD\nR\nL\nU\n')
    r = subprocess.run([str(exe), str(st), str(tmp_path / 'o.vtr'), '8', str(tmp_path / 'inp.txt'), '--inputs-first', '101',
                        '--reglog', str(tmp_path / 'reg.bin'), '--reglog-regs', '180'] + (['--inputs-v', '0:99'] if by_tick else []),
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    data = (tmp_path / 'reg.bin').read_bytes()
    seen = [(f, bv >> 16, rv & 0xffff) for f, bv, rv, pc in struct.iter_unpack('<4I', data)]
    assert [f for f, v, x in seen][:6] == [101, 102, 103, 104, 105, 106] and seen[3][1] >= 150 and all(v < 5 for f, v, x in seen[:3] + seen[4:6]), seen
    joy = {'': 0, 'R': 3, 'L': 0x300, 'U': 0x100, 'D': 1, 'RU': 0x103}
    want = ['', 'R', 'L', 'L', 'U', 'D'] if by_tick else ['', 'R', 'L', 'U', 'D', 'RU']      # frame 104 takes no line by the tick's rule
    assert [x for f, v, x in seen][:6] == [joy[k] for k in want], seen


def _blit_freeze_prog():
    """A blit of 512 x 48 words with BLTPRI started on line 228 every frame, the CPU waiting on BBUSY behind it; the Copper
    raises COPER on line 236 - while the CPU stands."""
    head = ('4df900dff000'              # lea $dff000,a6
            '2d7c000018000080'          # move.l #$1800,$80(a6)       COP1LC
            '3d400088'                  # move.w d0,$88(a6)           COPJMP1
            '3d7c86c00096'              # move.w #$86c0,$96(a6)       DMACON: DMAEN BLTPRI COPEN BLTEN
            '3d7cc010009a')             # move.w #$c010,$9a(a6)       INTENA: master, COPER
    w1 = ('302e0006'                    # w1: move.w $6(a6),d0        VHPOSR
          'e048'                        #     lsr.w #8,d0
          'b07c00e4'                    #     cmp.w #$e4,d0           line 228
          '66f4')                       #     bne.s w1
    blit = ('3d7c09f00040'              # move.w #$09f0,$40(a6)       BLTCON0: A -> D (both cycles of a word: nothing left for the CPU)
            '3d7c00000042'              # move.w #0,$42(a6)
            '3d7cffff0044'              # move.w #$ffff,$44(a6)       BLTAFWM
            '3d7cffff0046'              # move.w #$ffff,$46(a6)       BLTALWM
            '2d7c000300000050'          # move.l #$30000,$50(a6)      BLTAPT
            '3d7c00000064'              # move.w #0,$64(a6)           BLTAMOD
            '2d7c000200000054'          # move.l #$20000,$54(a6)      BLTDPT
            '3d7c00000066'              # move.w #0,$66(a6)           BLTDMOD
            '3d7c80300058'              # move.w #$8030,$58(a6)       BLTSIZE: 512 x 48 words
            '082e00060002'              # w2: btst #6,$2(a6)          BBUSY
            '66f8'                      #     bne.s w2
            '52784000')                 # addq.w #1,$4000
    back = len(w1 + blit) // 2 + 2
    return {MAIN: head + w1 + blit + '60%02x' % ((-back) & 0xff),
            L3: '52784002' '33fc001000dff09c' '4e73',                 # addq.w #1,$4002; move.w #$10,$dff09c; rte
            0x1800: 'ec01fffe' '009c8010' 'fffffffe'}                 # WAIT line 236; INTREQ <- SET COPER; end


def test_a_copper_interrupt_raised_while_the_cpu_stands_behind_a_blit_is_served(tmp_path):
    """1.0.69 (Turrican II KIT-GAP 35): a restart of a level runs three blits of 512 x 48 words and waits for each with
    btst / bne; the CPU stands behind the blit from line 235 into the next frame, the Copper's INTREQ write of line 236
    falls into it and no instruction boundary comes before the frame's end. The frame's roll forgot the request: of six
    interrupts the original served the host served four, and the music was two frames late from then on. Here every
    frame's request falls into such a blit: all of them must be served."""
    w = run(tmp_path, _blit_freeze_prog(), 12, [MAIN, L3])
    blits, irqs = w(0x4000), w(0x4002)
    assert blits >= 10 and irqs >= blits, (blits, irqs)


def test_ports_and_exter_follow_the_cias_interrupt_lines(tmp_path):
    """1.0.69 (Turrican II KIT-GAP 38): Paula's PORTS and EXTER are the CIAs' interrupt lines. CIA-B's one-shot timer
    runs out with its mask bit set: EXTER is requested. Cleared in INTREQ while the CIA still asks (its ICR not read) the
    bit is there again at once - the original's handler wrote $2070 back where the host had $0070; after the ICR is read
    the request stays until it is cleared, and then it is gone."""
    prog = {MAIN: '4df900dff000'
                  '13fc008100bfdd00'      # move.b #$81,$bfdd00       ICR mask: timer A
                  '13fc001000bfd400'      # move.b #16,$bfd400        TALO
                  '13fc000000bfd500'      # move.b #0,$bfd500         TAHI
                  '13fc001900bfde00'      # move.b #$19,$bfde00       CRA: START, ONESHOT, FORCE LOAD
                  '323c07d0' '51c9fffe'   # move.w #2000,d1; dbf d1,*
                  '31ee001e4010'          # move.w $1e(a6),$4010      INTREQR: EXTER
                  '3d7c2000009c'          # move.w #$2000,$9c(a6)     clear EXTER - the CIA still asks
                  '31ee001e4012'          # move.w $1e(a6),$4012
                  '4a3900bfdd00'          # tst.b $bfdd00             the ICR read: the CIA lets go
                  '31ee001e4014'          # move.w $1e(a6),$4014      the request is still there
                  '3d7c2000009c'          # move.w #$2000,$9c(a6)
                  '31ee001e4016'          # move.w $1e(a6),$4016      gone
                  '3d7cc020009a'          # move.w #$c020,$9a(a6)     INTENA: master, VERTB (the frames go on)
                  + WAIT_VBL,
            L3: L3_H}
    w = run(tmp_path, prog, 3, [MAIN, L3])
    assert [w(a) & 0x2000 for a in (0x4010, 0x4012, 0x4014, 0x4016)] == [0x2000, 0x2000, 0x2000, 0]
