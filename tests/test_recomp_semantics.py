"""Runtime semantics of the generated C, one instruction at a time.

Each case is a tiny program (one instruction + rts) run on a zeroed RAM; the
expected registers and flags are worked out by hand from the 68000 manual.
"""
import os
import shutil
import subprocess

import pytest

from arek.m68k import recomp
from arek.m68k.decoder import Flow, JumpTable, jtab_targets

BASE = 0x1000
FLAGS = 'xnzvc'


def run(tmp_path, hexcode, regs, flags='00000', auto=(BASE,), extra_c='', logs=None, pre_c='',
        ram_init=None, env=None, **gen):
    """Run ``hexcode`` + rts at BASE (also placed in RAM); return (d, a, flags, RAM).
    ``gen`` goes to recomp.generate (flow=...), ``extra_c`` is appended to the source and
    ``pre_c`` put before it (host macros), ``ram_init`` = {address: bytes} written to RAM first,
    the driver's log text is appended to ``logs``."""
    cc = shutil.which('cc') or shutil.which('gcc') or shutil.which('clang')
    if not cc:
        pytest.skip('no C compiler')
    prog = bytes.fromhex(hexcode + '4e75')
    src, _, _ = recomp.generate(prog, BASE, auto=list(auto), with_main=True, **gen)
    c, exe = tmp_path / 'r.c', tmp_path / 'r'
    c.write_text(pre_c + src + extra_c)
    subprocess.run([cc, '-O1', '-o', str(exe), str(c)], check=True)
    memsz = 0x80000
    ram = bytearray(memsz)
    for at, b in (ram_init or {}).items():
        ram[at:at + len(b)] = b
    ram[BASE:BASE + len(prog)] = prog
    (tmp_path / 'ram.bin').write_bytes(ram)
    r = dict(regs)
    r.setdefault('a7', memsz - 0x100)
    line = ' '.join('%x' % r.get(n, 0) for n in ['d%d' % i for i in range(8)] + ['a%d' % i for i in range(8)])
    (tmp_path / 'regs.txt').write_text(line + '\n%s\nf_%06x\n' % (' '.join(flags), BASE))
    out, log = tmp_path / 'out.bin', tmp_path / 'log.txt'
    subprocess.run([str(exe), str(tmp_path / 'ram.bin'), str(tmp_path / 'regs.txt'), str(out), str(log)], check=True,
                   env={**os.environ, **(env or {})})
    rows = log.read_text().split('\n')
    if logs is not None:
        logs.append(log.read_text())
    d = [int(x, 16) for x in rows[:8]]
    a = [int(x, 16) for x in rows[8:16]]
    f = dict(zip(FLAGS, map(int, rows[16].split())))
    return d, a, f, out.read_bytes()


def flags_of(f):
    return ''.join(k.upper() if f[k] else '.' for k in FLAGS)


CASES = [
    # roxl.w #1,d0 with X=1: the top bit goes to X and C, X comes in at the bottom
    ('e350', {'d0': 0x8000}, '10000', 0x0001, 'X...C'),
    # roxr.l #2,d1 with X=0: 3 -> 1 (X=1) -> $80000000 (X=1)
    ('e491', {'d1': 3}, '00000', 0x80000000, 'XN..C'),
    # asl.b #1,d0: $40 -> $80, the sign changed -> V
    ('e300', {'d0': 0x40}, '00000', 0x80, '.N.V.'),
    # asl.b #2,d0: $20 -> $40 -> $80, the sign changed at the second step -> V
    ('e500', {'d0': 0x20}, '00000', 0x80, '.N.V.'),
    # asl.b #1,d0: $c0 -> $80, the sign stayed -> no V, C and X from the bit shifted out
    ('e300', {'d0': 0xc0}, '00000', 0x80, 'XN..C'),
    # addx.b d1,d0, X=1: $ff + $01 + 1 = $101 -> 1, carry from the first half must survive in X
    ('d101', {'d0': 0xff, 'd1': 0x01}, '10100', 0x01, 'X...C'),
    # addx.b d1,d0, X=1: -128 + -1 + 1 = -128: no overflow although the partial sums overflow
    ('d101', {'d0': 0x80, 'd1': 0xff}, '10000', 0x80, 'XN..C'),
    # subx.b d1,d0, X=1, Z=1: 0 - 0 - 1 = $ff, borrow; Z cleared
    ('9101', {'d0': 0, 'd1': 0}, '10100', 0xff, 'XN..C'),
    # addx.b d1,d0, X=0, Z=1: 0 + 0 = 0 keeps Z (only cleared, never set)
    ('d101', {'d0': 0, 'd1': 0}, '00100', 0x00, '..Z..'),
    # muls.w d1,d0: -2 * 3 = -6
    ('c1c1', {'d0': 0xfffe, 'd1': 3}, '00000', 0xfffffffa, '.N...'),
    # divs.w d1,d0: -7 / 2 = -3 remainder -1
    ('81c1', {'d0': 0xfffffff9, 'd1': 2}, '00000', 0xfffffffd, '.N...'),
    # divs.w d1,d0: overflow leaves d0, sets V
    ('81c1', {'d0': 0x10000000, 'd1': 1}, '00000', 0x10000000, '...V.'),
    # divu.w d1,d0: overflow leaves d0, sets V, clears C
    ('80c1', {'d0': 0x10000000, 'd1': 1}, '00001', 0x10000000, '...V.'),
]


@pytest.mark.parametrize('hexcode, regs, flags, d0, expect', CASES)
def test_instruction_semantics(tmp_path, hexcode, regs, flags, d0, expect):
    d, _, f, _ = run(tmp_path, hexcode, regs, flags)
    reg = 1 if hexcode == 'e491' else 0
    assert (d[reg], flags_of(f)) == (d0, expect)


def test_return_to_the_callers_caller(tmp_path):
    # main: bsr sub ; move.l #1,$4000 ; rts
    # sub:  bsr inner ; move.l #2,$4004 ; rts      <- skipped: inner drops sub's frame
    # inner: addq.l #4,a7 ; rts                     -> returns straight into main
    prog = ('6100000e' '23fc0000000100004000' '4e75'
            '6100000e' '23fc0000000200004004' '4e75'
            '588f')
    d, a, f, mem = run(tmp_path, prog, {'a7': 0x7ff00})
    assert mem[0x4000:0x4004] == b'\0\0\0\1'
    assert mem[0x4004:0x4008] == b'\0\0\0\0'
    assert a[7] == 0x7ff04                         # main's own rts popped one long more


def mw(reg, v):
    """move.w #v,$dff000+reg"""
    return '33fc%04x00dff%03x' % (v & 0xffff, reg)


def ml(reg, v):
    """move.l #v,$dff000+reg (a blitter pointer pair)"""
    return '23fc%08x00dff%03x' % (v, reg)


def test_intena_set_clear_and_intenar(tmp_path):
    prog = (mw(0x09a, 0xc020) + '33f900dff01c00004000'      # move.w $dff01c,$4000
            + mw(0x09a, 0x0020) + '33f900dff01c00004002')
    *_, mem = run(tmp_path, prog, {})
    assert mem[0x4000:0x4004] == bytes.fromhex('40204000')


def test_byte_write_to_custom_lands_on_both_halves(tmp_path):
    # move.b #$83,$dff096: DMACON gets $8383 -> set $0383; DMACONR shows it (+ blitter done bit)
    prog = '13fc008300dff096' + '33f900dff00200004000'
    *_, mem = run(tmp_path, prog, {})
    assert mem[0x4000:0x4002] == bytes.fromhex('2383')


def blit_line(x0, y0, x1, y1, plane=0x5000, row=4):
    """Register setup for a solid line, as the Hardware Reference Manual prescribes."""
    dx, dy = abs(x1 - x0), abs(y1 - y0)
    xmajor = dx >= dy
    dmax, dmin = (dx, dy) if xmajor else (dy, dx)
    err = 4 * dmin - 2 * dmax
    con1 = 1 | (0x40 if err < 0 else 0)
    if xmajor:
        con1 |= 0x10 | (0x04 if x1 < x0 else 0) | (0x08 if y1 < y0 else 0)
    else:
        con1 |= (0x04 if y1 < y0 else 0) | (0x08 if x1 < x0 else 0)
    start = plane + y0 * row + (x0 >> 4) * 2
    return (mw(0x040, ((x0 & 15) << 12) | 0x0bca) + mw(0x042, con1)
            + mw(0x044, 0xffff) + mw(0x046, 0xffff) + mw(0x074, 0x8000) + mw(0x072, 0xffff)
            + mw(0x052, err) + mw(0x064, 4 * (dmin - dmax)) + mw(0x062, 4 * dmin)
            + mw(0x060, row) + mw(0x066, row) + ml(0x048, start) + ml(0x054, start)
            + mw(0x058, ((dmax + 1) << 6) | 2))


@pytest.mark.parametrize('line, rows', [
    ((0, 0, 7, 0), ['ff000000'] + ['00000000'] * 7),                       # horizontal
    ((0, 0, 0, 7), ['80000000'] * 8),                                      # vertical
    ((0, 0, 7, 7), ['%02x000000' % (0x80 >> y) for y in range(8)]),        # diagonal
    ((7, 7, 0, 0), ['%02x000000' % (0x80 >> y) for y in range(8)]),        # the same, drawn backwards
    ((12, 1, 19, 1), ['00000000', '000ff000'] + ['00000000'] * 6),         # across a word boundary
])
def test_blitter_line_mode(tmp_path, line, rows):
    *_, mem = run(tmp_path, blit_line(*line), {})
    assert [mem[0x5000 + 4 * y:0x5004 + 4 * y].hex() for y in range(8)] == rows


@pytest.mark.parametrize('con1, src, out', [
    (0x000a, 0x0810, 0x0ff0),     # inclusive fill: both edges kept
    (0x0012, 0x0810, 0x07f0),     # exclusive fill: the left edge (higher bit) dropped
    (0x000e, 0x0010, 0x001f),     # inclusive with FCI: the carry starts set
])
def test_blitter_fill_mode(tmp_path, con1, src, out):
    prog = ('33fc%04x00006000' % src
            + mw(0x040, 0x09f0) + mw(0x042, con1) + mw(0x044, 0xffff) + mw(0x046, 0xffff)
            + ml(0x050, 0x6000) + ml(0x054, 0x6002) + mw(0x058, (1 << 6) | 1))
    *_, mem = run(tmp_path, prog, {})
    assert mem[0x6002:0x6004].hex() == '%04x' % out


def test_jsr_absolute_and_jmp_pc_relative_reach_translated_code(tmp_path):
    # $1000: jsr $1014.l   $1006: jmp $1012(pc)   $100a: move.w #$dead,$4002 (skipped)
    # $1012: rts           $1014: move.w #$beef,$4000 ; rts
    prog = ('4eb900001014' '4efa000a' '33fcdead00004002' '4e75'
            '33fcbeef00004000')
    src, stats, entries = recomp.generate(bytes.fromhex(prog + '4e75'), BASE, auto=[BASE], with_main=True)
    assert 'unknown_call(0x1014u)' not in src
    *_, mem = run(tmp_path, prog, {})
    assert mem[0x4000:0x4004] == bytes.fromhex('beef0000')


# r0 at $1020 sets d1 = $1111, r2 at $1030 sets d1 = $2222 (both: move.w #imm,d1 ; rts)
ROUTINES = ('00' * 16 + '323c11114e75' + '00' * 10 + '323c22224e75')


def code_at(entry_hex):
    """``entry_hex`` from BASE, padded to $1020, then the two routines (ends at $1036)."""
    pad = 0x20 - len(entry_hex) // 2
    assert pad >= 0
    return entry_hex + '00' * pad + ROUTINES[32:]


def test_jump_table_of_bra_slots(tmp_path):
    # $1000: jsr 0(a0,d0.w) ; move.w d1,$4000 ; rts      table at $1100: bra r0 / rts / bra r2
    entry = '4eb00000' '33c100004000' '4e75'
    prog = code_at(entry) + '00' * (0x100 - 0x36)
    prog += '6000ff1e' '4e750000' '6000ff26'
    data = bytes.fromhex(prog + '4e75')
    jt = JumpTable(jtab_targets(data, BASE, 0x1100, 3, 4, 'bra'), 4, 0x1100)
    assert jt.targets == [0x1020, None, 0x1030]
    flow = Flow(jtabs={0x1000: jt})
    for d0, want in ((0, '1111'), (4, '7777'), (8, '2222')):
        *_, mem = run(tmp_path, prog, {'a0': 0x1100, 'd0': d0, 'd1': 0x7777}, flow=flow)
        assert mem[0x4000:0x4002].hex() == want, d0


def test_indirect_jsr_through_a_register(tmp_path):
    entry = '4e91' '33c100004000' '4e75'                   # jsr (a1) ; move.w d1,$4000 ; rts
    flow = Flow(indirect={0x1000: [0x1020, 0x1030]})
    *_, mem = run(tmp_path, code_at(entry), {'a1': 0x1030}, flow=flow)
    assert mem[0x4000:0x4002].hex() == '2222'


def test_jmp_whose_operand_the_program_rewrites(tmp_path):
    # move.l #$1030,$100c ; $100a: jmp $1020.l (operand at $100c rewritten before it runs)
    entry = '23fc000010300000100c' '4ef900001020'
    flow = Flow(indirect={0x100a: [0x1020, 0x1030]})
    d, *_ = run(tmp_path, code_at(entry), {}, flow=flow)
    assert d[1] == 0x2222


def test_external_routine_and_exit_point(tmp_path):
    entry = '4eb900001020' '33c100004000' '4eb900001030' '33fc999900004002' '4e75'
    ext = '\nvoid ext_load(M68 *m) { m->d[1] = 0x5555; m->a[7] += 4; }\n'   # behaves like the routine incl. rts
    logs = []
    *_, mem = run(tmp_path, code_at(entry), {}, flow=Flow(externs={0x1020: 'ext_load'}, exits={0x1030}),
                  extra_c=ext, logs=logs)
    assert mem[0x4000:0x4002].hex() == '5555'
    assert mem[0x4002:0x4004].hex() == '0000'             # the exit point ended the run before
    assert 'exit 1030' in logs[0]


def test_stop_keeps_the_walk_out_of_data():
    prog = bytes.fromhex('6708' '4e75' + '00' * 6 + 'ffff')      # beq $100a -> undecodable word
    with pytest.raises(recomp.Unsupported):
        recomp.generate(prog, BASE, auto=[BASE])
    src, _, _ = recomp.generate(prog, BASE, auto=[BASE], flow=Flow(stops={0x100a}))
    assert 'unknown_call(0x100au)' in src


def test_overlay_module_with_prefix_shares_the_runtime(tmp_path):
    # main: jsr $2000.l (the module, linked as an external) ; move.w d1,$4000 ; rts
    # module at $2000 (prefix m1_): jsr $1020.l (a main routine) ; rts
    module = bytes.fromhex('4eb900001020' '4e75')
    msrc, _, ments = recomp.generate(module, 0x2000, auto=[0x2000],
                                     flow=Flow(prefix=('m1_', 0x2000, 0x3000), lib=True))
    assert 'void f_m1_002000(M68 *m) {' in msrc and 'void f_001020(M68 *m);' in msrc
    assert '#define MEMSZ' not in msrc                   # no second runtime
    entry = '4eb900002000' '33c100004000' '4e75'
    *_, mem = run(tmp_path, code_at(entry), {}, auto=(BASE, 0x1020),
                  flow=Flow(externs={0x2000: 'f_m1_002000'}), extra_c='\n' + msrc)
    assert mem[0x4000:0x4002].hex() == '1111'


def test_stub_notes_are_generated_on_request(tmp_path):
    from arek.m68k import decoder
    decoder.STUBS[(6, -30)] = 'lvo_open'
    try:
        prog = bytes.fromhex('4eaeffe2' '4e75')                    # jsr -30(a6)
        src, _, _ = recomp.generate(prog, BASE, auto=[BASE], stub_impl='notes')
        assert 'static void lvo_open(M68 *m) { (void)m; hw_note("stub lvo_open"); }' in src
        src, _, _ = recomp.generate(prog, BASE, auto=[BASE])
        assert 'static void lvo_open' not in src             # default: defined by the user
    finally:
        decoder.STUBS.pop((6, -30), None)


def test_flow_from_cli_spellings():
    entry = '4eb00000' + '00' * (0x100 - 4)
    data = bytes.fromhex(entry + '6000ff1e' '4e750000' '6000ff26')
    fl = recomp.flow_from_specs(data, BASE, jtab=['1000,1010:1100:3:4:bra'], indirect=['1004=1020,$1030'],
                                stop=['100a'], exitat=['1040'], extern=['1050=load'], ret=['1060'],
                                prefix='ov:2000:3000', lib=True)
    assert fl.jtabs[0x1010].targets == [0x1020, None, 0x1030] and fl.jtabs[0x1000] is fl.jtabs[0x1010]
    assert fl.indirect == {0x1004: [0x1020, 0x1030]}
    assert (fl.stops, fl.exits, fl.rets, fl.externs) == ({0x100a}, {0x1040}, {0x1060}, {0x1050: 'load'})
    assert fl.fname(0x2004) == 'f_ov002004' and fl.fname(0x1000) == 'f_001000' and fl.lib


def test_recomp_cli_flow_options(tmp_path, capsys):
    from arek import cli
    prog = tmp_path / 'p.bin'
    prog.write_bytes(bytes.fromhex(code_at('4e91' '33c100004000' '4e75') + '4e75'))
    out = tmp_path / 'p.c'
    rc = cli.main(['recomp', str(prog), '--base', '0x1000', '--auto', '0x1000',
                   '--indirect', '1000=1020,1030', '-o', str(out)])
    assert rc in (None, 0)
    src = out.read_text()
    assert 'case 0x1020u:' in src and 'case 0x1030u:' in src


def test_timing_counts_the_path_actually_run(tmp_path):
    prog = ('7003'          # moveq #3,d0                4
            'd441'          # add.w d1,d2               4 x 4
            '51c8fffc'      # dbf d0,$1002              10 x 3, then 14
            'c8c3'          # mulu d3,d4  (d3 = $00ff)  38 + 2*8
            'eb6e'          # lsl.w d5,d6 (d5 = 5)      6 + 2*5
            '6702'          # beq $1010   (not taken)   8
            '4e71')         # nop                       4      + the rts 16
    logs = []
    run(tmp_path, prog, {'d3': 0xff, 'd5': 5, 'd6': 1}, timing=True, logs=logs)
    want = 4 + 4 * 4 + 3 * 10 + 14 + 54 + 16 + 8 + 4 + 16
    assert 'cycles %d' % want in logs[0]


def test_timing_is_off_by_default_and_has_a_host_hook():
    src, _, _ = recomp.generate(bytes.fromhex('4e714e75'), BASE, auto=[BASE])
    assert 'TICK(0x' not in src.split('#define TICK(pc, n) (COV_TICK(pc), PROF_TICK(n), CYCLES += (n))')[1]
    assert '#ifdef TICK_HOOK' in src
    src, _, _ = recomp.generate(bytes.fromhex('4e714e75'), BASE, auto=[BASE], timing=True)
    assert 'TICK(0x1000u, 4);' in src and 'TICK(0x1002u, 16);' in src


def test_jump_table_with_the_base_register_known_only_at_run_time(tmp_path):
    # 1000 jsr (0,a0,d0.w) ; rts ; nops ; 1010: bra.w x3 (slots) ; 1020/1024/1028: moveq #1/2/3,d1 ; rts
    prog = ('4eb0 0000 4e75 4e71 4e71 4e71 4e71 4e71' '6000 000e 6000 000e 6000 000e 4e71 4e71'
            '7201 4e75 7202 4e75 7203').replace(' ', '')
    data = bytes.fromhex(prog + '4e75')
    targets = jtab_targets(data, BASE, 0x1010, 3, 4, 'bra')
    assert targets == [0x1020, 0x1024, 0x1028]
    regs = {'a0': 0x1014, 'd0': 4}                        # the program moved a0 one slot past the table
    d, *_ = run(tmp_path, prog, regs, flow=Flow(jtabs={BASE: JumpTable(targets, 4, 0x1010, base_reg=True)}))
    assert d[1] == 3                                      # slot (a0 - table + d0) / 4 = 2
    d, *_ = run(tmp_path, prog, regs, flow=Flow(jtabs={BASE: JumpTable(targets, 4, 0x1010)}))
    assert d[1] == 2                                      # a fixed origin = the table ignores a0
    fl = recomp.flow_from_specs(data, BASE, jtab=['1000:1010:3:4:bra:an'])
    assert fl.jtabs[BASE].base_reg and fl.jtabs[BASE].targets == targets


def test_cia_hook_gets_every_byte(tmp_path):
    """-DCIA_HOOK: $bfxxxx goes to the host byte by byte (Superfrog seeds its RNG from CIA-B TOD, move.l $bfd802,d0)."""
    host = """
uint8_t cia_read_hook(uint32_t a) { return (a & 1) ? 0xff : 0xab; }          /* CIA-B on the even bytes, nothing on the odd */
void cia_write_hook(uint32_t a, uint8_t v) { MEM[0x4000] = (uint8_t)(a >> 8); MEM[0x4001] = (uint8_t)a; MEM[0x4002] = v; }
"""
    prog = '203900bfd802' + '13fc001200bfe001'              # move.l $bfd802,d0; move.b #$12,$bfe001
    cc = shutil.which('cc') or shutil.which('gcc') or shutil.which('clang')
    if not cc:
        pytest.skip('no C compiler')
    src, _, _ = recomp.generate(bytes.fromhex(prog + '4e75'), BASE, auto=[BASE], with_main=True)
    assert src.count('cia_read_hook') == 2 and '#ifdef CIA_HOOK' in src
    c, exe = tmp_path / 'h.c', tmp_path / 'h'
    c.write_text(src + host)
    subprocess.run([cc, '-O1', '-DCIA_HOOK', '-o', str(exe), str(c)], check=True)
    ram = bytearray(0x80000)
    ram[BASE:BASE + len(prog) // 2 + 2] = bytes.fromhex(prog + '4e75')
    (tmp_path / 'ram.bin').write_bytes(ram)
    (tmp_path / 'regs.txt').write_text(' '.join(['0'] * 15 + ['7ff00']) + '\n0 0 0 0 0\nf_%06x\n' % BASE)
    subprocess.run([str(exe), str(tmp_path / 'ram.bin'), str(tmp_path / 'regs.txt'), str(tmp_path / 'out.bin'), str(tmp_path / 'log.txt')], check=True)
    d0 = int((tmp_path / 'log.txt').read_text().split('\n')[0], 16)
    assert d0 == 0xabffabff
    assert (tmp_path / 'out.bin').read_bytes()[0x4000:0x4003] == bytes.fromhex('e00112')
