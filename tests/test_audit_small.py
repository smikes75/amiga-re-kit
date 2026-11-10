"""1.0.43: the small confirmed findings of the audit of 2026-11-10 - each case went wrong without a word before."""
import os
import struct
import subprocess

import pytest

from arek import bus, host
from arek.headless import shot, trace
from arek.m68k import recomp
from arek.m68k.decoder import Flow, JumpTable, jtab_targets
from test_recomp_semantics import BASE, code_at, run

BUS = os.path.dirname(os.path.abspath(bus.__file__))
HOST = os.path.dirname(os.path.abspath(host.__file__))
HOOK = dict(pre_c='#define UNKNOWN_HOOK 1\n', extra_c='\nvoid unknown_hook(uint32_t a) { (void)a; }\n')


# ------------------------------------------------------------------ the translation
def test_a_jump_table_offset_outside_the_table_runs_no_slot(tmp_path):
    """jmp 0(a0,d0.w) into a table of three bra slots with d0 = 10 (not a multiple of 4): the 68000 would jump into the
    middle of a slot. With a hook that returns (the browser build) the translation reported the unknown offset and then
    ran slot 10 / 4 = 2 as if nothing had happened."""
    prog = code_at('4ef00000') + '00' * (0x100 - 0x36) + '6000ff1e' '4e750000' '6000ff26'
    data = bytes.fromhex(prog + '4e75')
    flow = Flow(jtabs={0x1000: JumpTable(jtab_targets(data, BASE, 0x1100, 3, 4, 'bra'), 4, 0x1100)})
    d, *_ = run(tmp_path, prog, {'a0': 0x1100, 'd0': 8}, flow=flow, **HOOK)
    assert d[1] == 0x2222                                                   # a real slot still runs (its routine sets d1)
    d, *_ = run(tmp_path, prog, {'a0': 0x1100, 'd0': 10}, flow=flow, **HOOK)
    assert d[1] == 0                                                        # was $2222
    d, *_ = run(tmp_path, prog, {'a0': 0x1100, 'd0': 400}, flow=flow, **HOOK)
    assert d[1] == 0                                                        # past the table: the default arm


def test_unknown_jumps_end_the_routine_in_the_generated_text():
    prog = bytes.fromhex(code_at('4ef00000') + '00' * (0x100 - 0x36) + '6000ff1e' '4e750000' '6000ff26' + '4e75')
    flow = Flow(jtabs={0x1000: JumpTable(jtab_targets(prog, BASE, 0x1100, 3, 4, 'bra'), 4, 0x1100)})
    src, _, _ = recomp.generate(prog, BASE, auto=[BASE], flow=flow)
    body = src[src.index('void f_001000(M68 *m) {'):]
    assert '{ unknown_call((uint32_t)off); return; } else switch' in body and 'default: unknown_call((uint32_t)off); return; }' in body


# ------------------------------------------------------------------ the bus model
def test_a_blit_across_the_frame_end_is_still_busy_in_the_first_colour_clock(tmp_path):
    """arek_bus_bbusy(b, t) with t below 2 - slotoff computed slot -1 as an unsigned number: the blitter ran to its end
    at once - BBUSY clear and the BLIT interrupt a frame early, whenever an instruction boundary fell in the first
    colour clock of a frame."""
    cc = bus.compiler()
    if not cc:
        pytest.skip('no C compiler')
    c = tmp_path / 'b.c'
    c.write_text(r'''
#include <stdio.h>
#include "arek_bus.h"
static uint16_t rd(void *c, uint32_t a) { (void)c; (void)a; return 0; }
static uint8_t own[400 * 227]; static uint16_t regs[0x100];
int main(void) {
    for (int k = 0; k < 2; k++) {
        ArekBus b; arek_bus_init(&b, 227, 313, 400, own, regs, rd, 0);
        regs[0x096 >> 1] = 0x0240; arek_bus_frame(&b, 313);
        arek_bus_blit(&b, 312 * 227 + 100, 0x09f0, 0, (uint16_t)((400 << 6) | 50));    /* 20 000 words near the frame end */
        arek_bus_frame(&b, 313);
        printf("%d %u\n", arek_bus_bbusy(&b, k ? 2.0 : 0.5), b.bl.left);
    }
    return 0;
}''')
    exe = tmp_path / 'b'
    subprocess.run([cc, '-O1', '-I', BUS, '-o', str(exe), str(c), os.path.join(BUS, 'arek_bus.c'), os.path.join(BUS, 'arek_bus_vamiga.c'), '-lm'], check=True)
    rows = [x.split() for x in subprocess.run([str(exe)], capture_output=True, text=True, check=True).stdout.splitlines()]
    assert rows[0][0] == '1' and rows[1][0] == '1' and int(rows[0][1]) > 19000, rows     # was: busy 0, 0 words left at t = 0.5


# ------------------------------------------------------------------ the host
def test_an_audio_request_raised_inside_the_instruction_is_cleared_by_its_intreq_write(tmp_path):
    """A channel in the CPU's mode asks for its next word at 1500; an instruction that starts at 1495 writes INTREQ at 1503
    to acknowledge. Paula was run to 1503 only AFTER the bit was cleared, so the request of 1500 came back: one interrupt
    too many, and the host's INTREQ and the model's AUDxIP disagreed."""
    cc = bus.compiler()
    if not cc:
        pytest.skip('no C compiler')
    img = bytearray(0x2000)
    img[0x1100:0x1102] = bytes.fromhex('4e73')
    src, _, _ = recomp.generate(bytes(img), 0, auto=[0x1100], timing=True, bus_table=True)
    (tmp_path / 'game.c').write_text(src)
    (tmp_path / 't.c').write_text(r'''
#include "arek_host_pre.h"
#include "game.c"
#undef main
#include "arek_bus_glue.h"
#define HOST_L3 f_001100
#include "arek_host.h"
void exit_point(M68 *m, uint32_t at) { (void)m; (void)at; }
int main(void) {
    CREG[0x096 >> 1] = 0x0200;
    host_init(1000); host_display_init();
    wr16_raw(0xdff0a6, 200); wr16_raw(0xdff0a8, 64);
    arek_glue_set_time(1100); wr16_raw(0xdff0aa, 0x1234);      /* AUD0DAT with DMA off: the CPU's mode, a request at once */
    arek_glue_set_time(1150); wr16_raw(0xdff09c, 0x0080);
    arek_glue_set_time(1495); arek_paula_run(&H_PAULA, h_abs());
    arek_glue_set_time(1503); wr16_raw(0xdff09c, 0x0080);      /* the request of 1500 is older than this write */
    printf("%d %d\n", !!(H_INTREQ & 0x80), H_PAULA.ch[0].ip);
    return 0; }''')
    exe = tmp_path / 't'
    subprocess.run([cc, '-O1', '-w', '-I', BUS, '-I', HOST, '-I', str(tmp_path), '-o', str(exe), str(tmp_path / 't.c'),
                    os.path.join(BUS, 'arek_bus.c'), os.path.join(BUS, 'arek_bus_vamiga.c'), '-lm'], check=True)
    assert subprocess.run([str(exe)], capture_output=True, text=True, check=True).stdout.split() == ['0', '0']   # was 1 0


# ------------------------------------------------------------------ the measuring side
def test_a_time_with_a_fraction_is_refused():
    conf = {'ROM': '/rom', 'MACHINE': 'A500_OCS_1MB'}
    assert 'wait 3' in shot.build_script(conf, '/d.adf', [(3, 'joystick2 press 1')], 5, '/o.png')
    assert 'wait 3' in shot.build_script(conf, '/d.adf', [(3.0, 'joystick2 press 1')], 5.0, '/o.png')
    for events, end in (([(2.5, 'joystick2 press 1')], 10), ([], 9.5)):
        with pytest.raises(shot.HeadlessError):                              # was 'wait 2' / 'wait 9': a shorter run, silently
            shot.build_script(conf, '/d.adf', events, end, '/o.png')


def test_inputs_need_a_breakpoint(tmp_path):
    adf, rom, inp = tmp_path / 'g.adf', tmp_path / 'k.rom', tmp_path / 'in.txt'
    adf.write_bytes(bytes(901120))
    rom.write_bytes(b'x')
    inp.write_text('R\nF\n')
    conf = {'ROM': str(rom), 'ADF1': str(adf), 'VAHL': '/nonexistent/VAHeadless'}
    with pytest.raises(trace.TraceError) as e:                               # ran, and the game was idle
        trace.capture(conf, str(tmp_path / 'r.vtr'), [], 1, 2, inputs=str(inp), shots=str(tmp_path / 'p'), shot_frames=(100, 101))
    assert 'breakpoint' in str(e.value)
