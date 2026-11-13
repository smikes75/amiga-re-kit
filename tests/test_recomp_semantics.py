"""Runtime semantics of the generated C, one instruction at a time.

Each case is a tiny program (one instruction + rts) run on a zeroed RAM; the
expected registers and flags are worked out by hand from the 68000 manual.
"""
import os
import shutil
import subprocess

import pytest

from arek import cli
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
    # divs.w d1,d0: overflow leaves d0, sets V, and N as the 68000 does (1.0.26, Moira)
    ('81c1', {'d0': 0x10000000, 'd1': 1}, '00000', 0x10000000, '.N.V.'),
    # divu.w d1,d0: overflow leaves d0, sets V and N, clears Z and C
    ('80c1', {'d0': 0x10000000, 'd1': 1}, '00101', 0x10000000, '.N.V.'),
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
    assert 'unknown_call(0x1012u)' not in src
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



def test_jump_table_slots_count_their_own_clocks(tmp_path):
    """1.0.71 (Turrican II KIT-GAP 37): a jump into a table of bra slots runs the slot's bra (10 clocks, two prefetches)
    or rts (16) before the target. A translation with timing went from the jump straight to the target: the music
    player's command dispatch lost 10 clocks a command, its interrupt handler ended 4-38 colour clocks early."""
    entry = '4eb00000' '33c100004000' '4e75'
    prog = code_at(entry) + '00' * (0x100 - 0x36)
    prog += '6000ff1e' '4e750000' '6000ff26'
    data = bytes.fromhex(prog + '4e75')
    targets = jtab_targets(data, BASE, 0x1100, 3, 4, 'bra')
    cyc = {}
    for slots in (False, True):
        flow = Flow(jtabs={0x1000: JumpTable(targets, 4, 0x1100, slots=slots)})
        for d0 in (0, 4, 8):
            logs = []
            *_, mem = run(tmp_path, prog, {'a0': 0x1100, 'd0': d0, 'd1': 0x7777}, flow=flow, timing=True, logs=logs)
            cyc[slots, d0] = int(logs[0].split('cycles ')[1].split()[0])
    assert [cyc[True, d0] - cyc[False, d0] for d0 in (0, 4, 8)] == [10, 16, 10], cyc
    from arek.m68k.recomp import flow_from_specs
    flow = flow_from_specs(data, BASE, jtab=['1000:1100:3:4:bra'])          # the command line's spelling: a bra table has slots
    assert flow.jtabs[0x1000].slots
    src, _, _ = recomp.generate(data, BASE, auto=[BASE], flow=flow, timing=True, bus_table=True)
    assert 'case 0: TICK(0x1100u, 10); ' in src and 'case 1: TICK(0x1104u, 16); ' in src and 'case 2: TICK(0x1108u, 10); ' in src
    plain, _, _ = recomp.generate(data, BASE, auto=[BASE], flow=flow)
    assert 'TICK(0x1100u' not in plain
    # the slot has its row in the bus table (2 words: the bra.w with its two prefetches)
    hook = '\nvoid tick_hook(M68 *m, uint32_t pc, uint32_t clocks) { (void)m; (void)clocks; if (pc == 0x1100u) { const uint8_t *r = bus_tab_row(pc); MEM[0x4010] = r[0]; MEM[0x4011] = 0x5a; } }\n'
    *_, mem = run(tmp_path, prog, {'a0': 0x1100, 'd0': 0, 'd1': 0x7777}, flow=flow, timing=True, bus_table=True, pre_c='#define TICK_HOOK 1\n', extra_c=hook)
    assert tuple(mem[0x4010:0x4012]) == (2, 0x5a)
    assert not JumpTable(jtab_targets(data, BASE, 0x1100, 3, 4, 'bra'), 4, 0x1100).slots   # the class's default: as before


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


# 1.0.66 (SWIV: the crack's trainer rewrites instructions of the game by the options chosen): --smc / Flow.smc
#   1000 tst.w d0 ; 1002 beq.s 100a ; 1004 move.w d0,$1012.l (the program writes the opcode word it was given)
#   100a move.w #5,$4000.l ; 1012 addq.w #1,$4000.l ; 1018 addq.w #1,$4002.l ; 101e addq.w #1,$4004.l ; 1024 rts
SMC_PROG = '4a40' '6706' '33c000001012' '33fc000500004000' '527900004000' '527900004002' '527900004004'


def test_a_rewritten_instruction_runs_as_what_ram_holds(tmp_path):
    """One translation holds the instruction of the image and the ones the program may write there; the words in RAM
    choose when the place runs. Before, the image's instruction ran whatever the program wrote."""
    flow = Flow(smc={0x1012: [bytes.fromhex('4a79'), bytes.fromhex('600a')]})   # tst.w $4000.l / bra.s $101e
    got = []
    for d0 in (0, 0x4a79, 0x600a):
        *_, mem = run(tmp_path, SMC_PROG, {'d0': d0}, flow=flow)
        got.append(mem[0x4000:0x4006].hex())
    assert got == ['000600010001',                           # as the image: 5 + 1, both others counted
                   '000500010001',                           # tst.w: nothing added (its extension words are the image's)
                   '000500000001']                           # bra.s over the first two
    *_, mem = run(tmp_path, SMC_PROG, {'d0': 0x4a79})
    assert mem[0x4000:0x4002].hex() == '0006'               # without the option the translation does not notice


def test_a_rewritten_instruction_with_words_nobody_named_stops(tmp_path):
    flow = Flow(smc={0x1012: [bytes.fromhex('4a79')]})
    with pytest.raises(subprocess.CalledProcessError) as e:
        run(tmp_path, SMC_PROG, {'d0': 0x4e71}, flow=flow)   # a nop there: not the image's, not a named one
    assert e.value.returncode == 4


def test_rewritten_two_nops_over_a_call_and_an_rts(tmp_path):
    """The other content may be several instructions (two nop over a bsr.w) or end the routine (rts)."""
    # 1000 tst.w d0 ; 1002 beq.s 100a ; 1004 move.l d0,$100a.l ; 100a bsr.w $1016 ; 100e addq.w #1,$4002.l ; 1014 rts
    # 1016 addq.w #1,$4000.l ; 101c rts
    prog = '4a40' '6706' '23c00000100a' '6100000a' '527900004002' '4e75' '527900004000'
    flow = Flow(smc={0x100a: [bytes.fromhex('4e714e71'), bytes.fromhex('4e75')]})
    got = []
    for d0 in (0, 0x4e714e71, 0x4e75000a):
        *_, mem = run(tmp_path, prog, {'d0': d0}, flow=flow)
        got.append(mem[0x4000:0x4004].hex())
    assert got == ['00010001', '00000001', '00000000']


def test_rewritten_instruction_clocks_and_bus_rows(tmp_path):
    """With --timing every content counts its own clocks, and the bus table gives its own row while it is in RAM
    (bit 7 of the image row's flags sends the lookup to bus_smc_row)."""
    flow = Flow(smc={0x1012: [bytes.fromhex('4a79'), bytes.fromhex('600a')]})
    cyc = []
    for d0 in (0, 0x4a79, 0x600a):
        logs = []
        run(tmp_path, SMC_PROG, {'d0': d0}, flow=flow, timing=True, logs=logs)
        cyc.append(int(logs[0].split('cycles ')[1].split()[0]))
    # tst.w d0 4, beq 10 taken / 8 not + move.w d0,abs.l 16, move.w #,abs.l 20, addq.w #1,abs.l 20 each, rts 16
    assert cyc == [4 + 10 + 20 + 60 + 16, 4 + 8 + 16 + 20 + 16 + 40 + 16, 4 + 8 + 16 + 20 + 10 + 20 + 16], cyc
    src, _, _ = recomp.generate(bytes.fromhex(SMC_PROG + '4e75'), BASE, auto=[BASE], flow=flow, timing=True, bus_table=True)
    assert 'static const uint8_t BUS_SMC[2][6]' in src and '(r[2] & 0x80) ? bus_smc_row(pc, r) : r' in src
    assert 'if (pc == 0x1012u && (rd16_raw(0x1012u) == 0x4a79u)) return BUS_SMC[0];' in src
    # the row a host's tick_hook gets at the place: the image's, the tst's, the bra's
    from arek.m68k.decoder import decode
    from arek.m68k.timing import bus_table_entry
    hook = '\nvoid tick_hook(M68 *m, uint32_t pc, uint32_t clocks) { (void)m; (void)clocks; if (pc == 0x1012u) { const uint8_t *r = bus_tab_row(pc); MEM[0x4010] = r[0]; MEM[0x4011] = r[1]; MEM[0x4012] = r[2]; } }\n'
    prog, rows = bytes.fromhex(SMC_PROG + '4e75'), []
    for d0 in (0, 0x4a79, 0x600a):
        *_, mem = run(tmp_path, SMC_PROG, {'d0': d0}, flow=flow, timing=True, bus_table=True, pre_c='#define TICK_HOOK 1\n', extra_c=hook)
        rows.append(tuple(mem[0x4010:0x4013]))
    want = [bus_table_entry(decode(prog[:0x12] + alt + prog[0x12 + len(alt):], BASE, 0x1012)) for alt in (b'', b'\x4a\x79', b'\x60\x0a')]
    assert rows == [want[0][:2] + (want[0][2] | 0x80,), want[1], want[2]] and want[0][0] == 3 and want[2][0] == 1, (rows, want)
    plain, _, _ = recomp.generate(bytes.fromhex(SMC_PROG + '4e75'), BASE, auto=[BASE], timing=True, bus_table=True)
    assert 'BUS_SMC' not in plain and 'bus_smc_row' not in plain and 'unknown_call(0x1012u)' not in plain


def test_smc_refusals_and_the_command_line(tmp_path, capsys):
    from arek.m68k.decoder import Unsupported
    prog = bytes.fromhex(SMC_PROG + '4e75')
    for alt, why in (('4eb9', 'a call or a jump'), ('5279', 'what the image holds'), ('4a', 'whole words')):
        with pytest.raises(Unsupported, match=why):
            recomp.generate(prog, BASE, auto=[BASE], flow=Flow(smc={0x1012: [bytes.fromhex(alt)]}))
    f = tmp_path / 'p.bin'
    f.write_bytes(prog)
    assert cli.main(['recomp', str(f), '--base', '0x1000', '--auto', '0x1000', '--smc', '1012=4a79,600a', '-o', str(tmp_path / 'p.c')]) == 0
    src = (tmp_path / 'p.c').read_text()
    assert 'if ((rd16_raw(0x1012u) == 0x4a79u)) {   /* --smc: ' in src and '} else if ((rd16_raw(0x1012u) == 0x600au)) {' in src
    assert '} else if ((rd16_raw(0x1012u) == 0x5279u)) {' in src and 'unknown_call(0x1012u); return; }' in src


def test_an_immediate_the_program_rewrites_is_read_from_ram(tmp_path):
    """1.0.67 (SWIV: the crack's trainer writes the number of missiles and the rate of fire into the immediate operands
    of a hook it calls every frame): --live ADDR / Flow.live - the operand of the instruction at ADDR is what RAM
    holds when it runs, byte, word or long; the clocks and the bus row are the instruction's own. Without the option
    the image's operand is used."""
    # 1000 move.w d0,$1014.l ; 1006 move.b d1,$101d.l ; 100c move.l d2,$1024.l      (the program writes the operands)
    # 1012 move.w #$1111,$4000.l ; 101a move.b #$f4,$4002.l ; 1022 move.l #$11112222,$4004.l ; 102c rts
    prog = '33c000001014' '13c10000101d' '23c200001024' '33fc111100004000' '13fc00f400004002' '23fc1111222200004004'
    regs = {'d0': 0xabcd, 'd1': 0x77, 'd2': 0xdeadbeef}
    flow = Flow(live={0x1012, 0x101a, 0x1022})
    logs = []
    d, a, f, mem = run(tmp_path, prog, regs, flow=flow, timing=True, logs=logs)
    assert mem[0x4000:0x4008].hex() == 'abcd7700deadbeef' and flags_of(f)[1] == 'N'      # the long's sign
    plain = []
    *_, mem = run(tmp_path, prog, regs, timing=True, logs=plain)
    assert mem[0x4000:0x4008].hex() == '1111f40011112222'
    assert logs[0].split('cycles ')[1].split()[0] == plain[0].split('cycles ')[1].split()[0]
    src, _, _ = recomp.generate(bytes.fromhex(prog + '4e75'), BASE, auto=[BASE], flow=flow, timing=True, bus_table=True)
    ref, _, _ = recomp.generate(bytes.fromhex(prog + '4e75'), BASE, auto=[BASE], timing=True, bus_table=True)
    assert 'rd16_raw(0x1014u)' in src and '(rd16_raw(0x101cu) & 0xffu)' in src and '((rd16_raw(0x1024u) << 16) | rd16_raw(0x1026u))' in src
    tab = lambda t: t[t.index('static const uint8_t BUS_PAT'):t.index('static inline const uint8_t *bus_tab_row')]
    assert tab(src) == tab(ref)                                                  # the same bus table
    from arek.m68k.decoder import Unsupported
    with pytest.raises(Unsupported, match='no immediate operand in an extension word'):
        recomp.generate(bytes.fromhex(prog + '4e75'), BASE, auto=[BASE], flow=Flow(live={0x1000}))
    f_ = tmp_path / 'p.bin'
    f_.write_bytes(bytes.fromhex(prog + '4e75'))
    assert cli.main(['recomp', str(f_), '--base', '0x1000', '--auto', '0x1000', '--live', '1012', '101a', '-o', str(tmp_path / 'p.c')]) == 0
    assert 'rd16_raw(0x1014u)' in (tmp_path / 'p.c').read_text() and 'rd16_raw(0x1024u)' not in (tmp_path / 'p.c').read_text()


def test_external_routine_and_exit_point(tmp_path):
    entry = '4eb900001020' '33c100004000' '4eb900001030' '33fc999900004002' '4e75'
    ext = '\nvoid ext_load(M68 *m) { m->d[1] = 0x5555; m->a[7] += 4; }\n'   # behaves like the routine incl. rts
    logs = []
    *_, mem = run(tmp_path, code_at(entry), {}, flow=Flow(externs={0x1020: 'ext_load'}, exits={0x1030}),
                  extra_c=ext, logs=logs)
    assert mem[0x4000:0x4002].hex() == '5555'
    assert mem[0x4002:0x4004].hex() == '0000'             # the exit point ended the run before
    assert 'exit 1030' in logs[0]


def test_fall_through_and_branch_into_an_external_routine(tmp_path):
    """G54 (Alien Breed II): a routine that falls through into an --extern routine, and one that branches to it, got a
    goto to a label the translation no longer has. Both become the host call with the caller's return."""
    # A: moveq #1,d0 (falls into B)   B: moveq #2,d1 ; rts   C: moveq #3,d2 ; bra.s B
    prog = '7001' '7202' '4e75' '7403' '60f8'
    a, b, c = BASE, BASE + 2, BASE + 6
    src, _, _ = recomp.generate(bytes.fromhex(prog + '4e75'), BASE, auto=[a, b, c], flow=Flow(externs={b: 'ext_b'}))
    assert 'goto L%06x' % b not in src and src.count('ext_b(m); return;') == 2
    ext = '\nvoid ext_b(M68 *m) { m->d[1] = 0x5555; m->a[7] += 4; }\n'           # behaves like B incl. its rts
    d, *_ = run(tmp_path, prog, {}, auto=[a, b, c], flow=Flow(externs={b: 'ext_b'}), extra_c=ext)
    assert d[0] == 1 and d[1] == 0x5555                                          # A ran, fell into the host's B, returned to the driver
    p = cli.build_parser().parse_args(['recomp', 'x.bin', '--base', '0', '-o', 'x.c', '--extern', '1=a', '--extern', '2=b', '3=c'])
    assert p.extern == ['1=a', '2=b', '3=c']                                     # repeated --extern accumulates


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
    assert src.count('cia_read_hook') >= 2 and '#ifdef CIA_HOOK' in src
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


def test_hw_hook_answers_unmodelled_reads_and_sees_writes(tmp_path):
    """-DHW_HOOK: a custom register the runtime does not model is answered by the host; every write is observed."""
    host = """
int hw_read_hook(uint32_t off, uint32_t *v) { if (off == 0x006) { *v = 0x1234; return 1; } return 0; }
void hw_write_hook(uint32_t off, uint32_t v) { MEM[0x4000] = (uint8_t)(off >> 8); MEM[0x4001] = (uint8_t)off; MEM[0x4002] = (uint8_t)(v >> 8); MEM[0x4003] = (uint8_t)v; }
"""
    prog = '303900dff006' + '33fc567800dff180'                   # move.w $dff006,d0 (VHPOSR); move.w #$5678,$dff180
    d, _, _, mem = run(tmp_path, prog, {}, pre_c='#define HW_HOOK 1\n', extra_c=host)
    assert d[0] == 0x1234 and mem[0x4000:0x4004] == bytes.fromhex('01805678')
    d, _, _, mem = run(tmp_path, prog, {})                        # without the hook: unmodelled read = the shadow (0), no observer
    assert d[0] == 0 and mem[0x4000:0x4004] == bytes(4)


def test_driver_loads_the_custom_registers_of_a_capture(tmp_path):
    """$AREK_CREG (bpstate creg.bin): INTENAR reads back what the capture had in INTENA."""
    creg = bytearray(512); creg[0x9a:0x9c] = bytes.fromhex('c020')
    (tmp_path / 'creg.bin').write_bytes(creg)
    d, *_ = run(tmp_path, '303900dff01c', {}, env={'AREK_CREG': str(tmp_path / 'creg.bin')})   # move.w $dff01c,d0
    assert d[0] == 0x4020


def test_overlay_fingerprint_is_not_a_cpu_access():
    """1.0.7 (Turrican II KIT-GAPS 9): overlay_fp hashes the module's bytes with raw reads - a bus-counted rd8 made every
    overlay_call cost emulated time (256 accesses per registered module: lines of the game's frame)."""
    from arek.m68k import recomp as R
    body = R.RUNTIME[R.RUNTIME.index('static uint64_t overlay_fp'):]
    body = body[:body.index('return h;')]
    assert 'rd8_raw(base + i)' in body and 'h ^= rd8(' not in body


def test_blitter_modulo_ignores_bit_0(tmp_path):
    """1.0.9 (Turrican II KIT-GAPS 13): a modulo is a word quantity - the hardware ignores its bit 0 (DMOD $21 acts as $20;
    with $21 kept, the intro logo's rows landed a byte off)."""
    prog = ('33fcaaaa00006000' + '33fcbbbb00006002'                       # two source words, rows of one word
            + mw(0x040, 0x09f0) + mw(0x042, 0) + mw(0x044, 0xffff) + mw(0x046, 0xffff)
            + ml(0x050, 0x6000) + ml(0x054, 0x6100) + mw(0x064, 0) + mw(0x066, 3)   # DMOD 3: acts as 2
            + mw(0x058, (2 << 6) | 1))
    *_, mem = run(tmp_path, prog, {})
    assert mem[0x6100:0x6106].hex() == 'aaaa0000bbbb'                  # row 1 at +4 (2 + 2), not at an odd +5


def test_blitter_shifters_carry_into_the_next_row(tmp_path):
    """1.0.57 (SWIV in the game, frame 4236): the bits a barrel shifter moves out of a row's last word come in at the
    next row's first word - the shifters are cleared at a blit's start, not at a row's. A = $FFFF shifted by 8: $00FF
    only in the very first word (the model had it at the start of every row and the game's state left the original's
    one frame later). The same for B."""
    fill = ''.join('33fcffff0000%04x' % a for a in (0x6000, 0x6002, 0x6004, 0x6006))
    prog = (fill + mw(0x040, 0x89f0) + mw(0x042, 0) + mw(0x044, 0xffff) + mw(0x046, 0xffff)      # ASH 8, A -> D
            + ml(0x050, 0x6000) + ml(0x054, 0x6100) + mw(0x064, 0) + mw(0x066, 0) + mw(0x058, (2 << 6) | 2)
            + mw(0x040, 0x05cc) + mw(0x042, 0x4000)                                                # BSH 4, B -> D
            + ml(0x04c, 0x6000) + ml(0x054, 0x6200) + mw(0x062, 0) + mw(0x066, 0) + mw(0x058, (2 << 6) | 2))
    *_, mem = run(tmp_path, prog, {})
    assert mem[0x6100:0x6108].hex() == '00ffffff' 'ffffffff'
    assert mem[0x6200:0x6208].hex() == '0fffffff' 'ffffffff'


def test_blitter_descending_subtracts_the_modulo(tmp_path):
    """1.0.9: in descending mode the pointers run down a row and the modulo is subtracted at its end (HRM)."""
    prog = ('33fccccc00005ffe' + '33fcaaaa00006000' + '33fcbbbb00006002'
            + mw(0x040, 0x09f0) + mw(0x042, 0x0002) + mw(0x044, 0xffff) + mw(0x046, 0xffff)   # DESC
            + ml(0x050, 0x6002) + ml(0x054, 0x6102) + mw(0x064, 2) + mw(0x066, 2)           # modulo 2: skip a word between rows
            + mw(0x058, (2 << 6) | 1))
    *_, mem = run(tmp_path, prog, {})
    assert mem[0x6102:0x6104].hex() == 'bbbb' and mem[0x60fe:0x6100].hex() == 'cccc'   # row 1 from $5ffe to $60fe
    assert mem[0x6100:0x6102].hex() == '0000'                                             # the skipped word untouched


@pytest.mark.parametrize('hx, length, text', [
    ('003c0005', 4, 'ori.b #5,ccr'), ('023c00fa', 4, 'andi.b #250,ccr'), ('0a3c0001', 4, 'eori.b #1,ccr'),
    ('007c0700', 4, 'ori.w #1792,sr'), ('027cf8ff', 4, 'andi.w #63743,sr'),
])
def test_immediate_to_ccr_sr_is_four_bytes(hx, length, text):
    """1.0.10 (Turrican II KIT-GAPS 14): ori/andi/eori #imm,CCR|SR is 4 bytes - the decoder read another word as an
    immediate destination (6 bytes, 'ori.b #5,#250'), the walk went on misaligned and the generator refused."""
    from arek.m68k import decoder
    i = decoder.decode_at(bytes.fromhex(hx + '4e75'), 0x1000, 0x1000) if hasattr(decoder, 'decode_at') else None
    if i is None:
        tree = decoder.call_tree(bytes.fromhex(hx + '4e75'), 0x1000, [0x1000], 0x1000, 0x1006)
        ins = tree[0x1000][0]
        i = ins[0x1000]
        assert 0x1000 + length in ins and ins[0x1000 + length].text == 'rts'
    assert i.text == text


def test_immediate_to_ccr_sets_the_flags(tmp_path):
    """1.0.10: ori #$1f,ccr sets X N Z V C, andi #$fe,ccr clears C, eori #4,ccr flips Z (move sr,abs keeps the flags)."""
    prog = ('44fc0000' '003c001f'
            '40f900004000'          # move sr,$4000
            '023c00fe'              # andi #$fe,ccr      C off
            '40f900004002'
            '0a3c0004'              # eori #4,ccr        Z off
            '40f900004004')
    *_, mem = run(tmp_path, prog, {})
    v = [int.from_bytes(mem[0x4000 + 2 * k:0x4002 + 2 * k], 'big') & 0x1f for k in range(3)]
    assert v == [0x1f, 0x1e, 0x1a], [hex(x) for x in v]


SAME_AN = [
    # (hex, regs, ram_init, check address, expected bytes there, register, its value after) - 1.0.23, Xenon 2 KIT-GAP 3:
    # the 68000 reads the source BEFORE it forms the destination's address (Moira: readOp, then writeOp)
    ('22e90004', {'a1': 0x2000}, {0x2004: bytes.fromhex('11223344'), 0x2008: bytes.fromhex('55667788')},
     0x2000, '11223344', 'a1', 0x2004),                         # move.l (4,a1),(a1)+ reads a1+4, not a1+8
    ('2329fff6', {'a1': 0x2010}, {0x2006: bytes.fromhex('aabbccdd'), 0x2002: bytes.fromhex('99999999')},
     0x200c, 'aabbccdd', 'a1', 0x200c),                         # move.l (-10,a1),-(a1) reads a1-10, not a1-14
    ('2311', {'a1': 0x2004}, {0x2004: bytes.fromhex('cafebabe')},
     0x2000, 'cafebabe', 'a1', 0x2000),                         # move.l (a1),-(a1)
    ('2309', {'a1': 0x2004}, {},
     0x2000, '00002004', 'a1', 0x2000),                         # move.l a1,-(a1) stores the old a1
    ('30f00002', {'a0': 0x2000, 'd0': 4}, {0x2006: bytes.fromhex('beef'), 0x2008: bytes.fromhex('1111')},
     0x2000, 'beef', 'a0', 0x2002),                             # move.w (2,a0,d0.w),(a0)+
    ('d188', {'a0': 0x2008}, {0x2004: bytes.fromhex('00000005'), 0x2000: bytes.fromhex('00000010')},
     0x2000, '00000015', 'a0', 0x2000),                         # addx.l -(a0),-(a0): source a0-4, destination a0-8
    ('9349', {'a1': 0x2004}, {0x2002: bytes.fromhex('0003'), 0x2000: bytes.fromhex('0010')},
     0x2000, '000d', 'a1', 0x2000),                             # subx.w -(a1),-(a1)
    ('c309', {'a1': 0x2002}, {0x2001: bytes.fromhex('15'), 0x2000: bytes.fromhex('27')},
     0x2000, '42', 'a1', 0x2000),                               # abcd -(a1),-(a1): 27 + 15 = 42 (BCD)
    ('8309', {'a1': 0x2002}, {0x2001: bytes.fromhex('15'), 0x2000: bytes.fromhex('42')},
     0x2000, '27', 'a1', 0x2000),                               # sbcd -(a1),-(a1): 42 - 15 = 27 (BCD)
]


@pytest.mark.parametrize('hexcode, regs, ram_init, at, want, reg, after', SAME_AN)
def test_source_read_before_the_destination_moves_the_same_register(tmp_path, hexcode, regs, ram_init, at, want, reg, after):
    d, a, f, ram = run(tmp_path, hexcode, regs, ram_init=ram_init)
    assert ram[at:at + len(want) // 2].hex() == want
    assert (a if reg[0] == 'a' else d)[int(reg[1])] == after


def test_rts_after_a_push_is_a_jump(tmp_path):
    """1.0.24 (Xenon 2 KIT-GAP 4): `move.l #X,-(a7); rts` jumps to X on the 68000; the translation returned to its C
    caller and dropped X. Now rts compares the stack with the routine's entry and runs X through call_addr."""
    code = '2f3c00001010' '4e75' + '4e71' * 4 + '7007'            # $1000 push $1010; rts | $1010 moveq #7,d0 (+ rts)
    d, a, f, ram = run(tmp_path, code, {}, auto=(BASE, 0x1010))
    assert d[0] == 7


def test_rts_after_a_replaced_return_address(tmp_path):
    """A called routine drops its return address and pushes another (addq.l #4,a7; move.l #X,-(a7); rts): X runs and
    its rts leaves the caller too - the caller's continuation ($1004 moveq #1,d1) never runs, as on the 68000."""
    code = ('6100000e' '7201' '4e75' + '4e71' * 4 +                 # $1000 bsr $1010 | $1004 moveq #1,d1 | rts
            '588f' '2f3c00001020' '4e75' + '4e71' * 3 + '7009')     # $1010 addq.l #4,a7; push $1020; rts | $1020 moveq #9,d0
    d, a, f, ram = run(tmp_path, code, {}, auto=(BASE, 0x1020))
    assert d[0] == 9 and d[1] == 0


def test_rts_with_two_pushed_targets_runs_both(tmp_path):
    """push $1030; push $1020; rts: $1020 runs, its rts jumps to $1030, whose rts returns - the chain through the long
    each rts popped."""
    code = ('2f3c00001030' '2f3c00001020' '4e75' + '4e71' * 9 +     # $1000 .. $100c rts, nops to $1020
            '7005' '4e75' + '4e71' * 6 + '7206')                    # $1020 moveq #5,d0; rts | $1030 moveq #6,d1 (+ rts)
    d, a, f, ram = run(tmp_path, code, {}, auto=(BASE, 0x1020, 0x1030))
    assert d[0] == 5 and d[1] == 6


# ------------------------------------------------------------------ 1.0.26: TRAP, rte, --resume
def be32(v):
    return v.to_bytes(4, 'big')


def test_trap_runs_the_vector_and_comes_back_behind_it(tmp_path):
    # 1000 trap #3 ; 1002 move sr,d3 ; 1004 moveq #1,d1 ; 1006 rts
    # 1008 move sr,d2 ; 100a moveq #5,d0 ; 100c rte      <- the handler, found through the vector at run time
    code = '4e43 40c3 7201 4e75 40c2 7005 4e73'.replace(' ', '')
    d, a, _, ram = run(tmp_path, code, {}, '11111', auto=(BASE, 0x1008), ram_init={0x8c: be32(0x1008)})
    top = 0x80000 - 0x100
    assert (d[0], d[1]) == (5, 1)
    assert d[2] == 0x201f                                  # the handler runs supervisor, the flags are the caller's
    assert d[3] == 0x001f                                  # rte gave back SR with the flags the handler changed
    assert a[7] == top + 4
    assert ram[top - 6:top] == bytes.fromhex('001f') + be32(0x1002)   # the 68000's frame


def test_trap_handler_replacing_the_stacked_pc(tmp_path):
    # 1000 trap #0 ; 1002 moveq #1,d1 ; 1004 rts
    # 1006 move.l #$1010,2(a7) ; 100e rte                 <- the handler goes on elsewhere
    # 1010 moveq #7,d2 ; 1012 rts                          <- pops the return address of the routine at 1000
    code = '4e40 7201 4e75 2f7c00001010 0002 4e73 7407'.replace(' ', '')
    d, a, _, _ = run(tmp_path, code, {}, auto=(BASE, 0x1006, 0x1010), ram_init={0x80: be32(0x1006)})
    assert (d[1], d[2]) == (0, 7) and a[7] == 0x80000 - 0x100 + 4


def test_rte_goes_to_a_frame_the_routine_pushed(tmp_path):
    # 1000 move.l #$100a,-(a7) ; 1006 move sr,-(a7) ; 1008 rte ; 100a moveq #1,d0 ; 100c rts
    code = '2f3c0000100a 40e7 4e73 7001'.replace(' ', '')
    d, a, _, _ = run(tmp_path, code, {}, auto=(BASE, 0x100a))
    assert d[0] == 1 and a[7] == 0x80000 - 0x100 + 4


def test_rte_from_a_routine_called_by_the_handler_still_unwinds(tmp_path):
    # 1000 bsr 1008 ; 1004 moveq #1,d0 ; 1006 rts         <- the frame the routine at 1008 pops is the driver's caller's
    # 1008 addq.l #4,a7 ; 100a rte
    code = '6100 0006 7001 4e75 588f 4e73'.replace(' ', '')
    top = 0x80000 - 0x100
    d, a, _, _ = run(tmp_path, code, {'a7': top}, ram_init={top: bytes.fromhex('2000') + be32(0x2000)})
    assert d[0] == 0 and a[7] == top + 6


def task_ram(stack_b, rts_frame=False):
    """Two records in a ring as SWIV's (+0 next, +14 saved a7), task B not started yet: its stack holds a start frame."""
    frame = be32(0x1016) if rts_frame else bytes.fromhex('2000') + be32(0x1016)
    sp = stack_b - len(frame)
    return {0x3000: be32(0x3100), 0x3100: be32(0x3000), 0x3100 + 14: be32(sp), sp: frame}


def tasks(limit, yield_ends_in='4e73', push_sr='40e7'):
    """Two loops, each counting and yielding from one routine deeper; the first ends the run at `limit`:
    1000 addq.l #1,$2000.w ; 1004 cmpi.l #limit,$2000.w ; 100c bge.s 1014 ; 100e bsr 1020 ; 1012 bra.s 1000 ; 1014 nop (exit)
    1016 addq.l #1,$2004.w ; 101a bsr 1020 ; 101e bra.s 1016
    1020 bsr yield ; 1024 rts
    yield: [move sr,-(a7)] ; move.l a7,14(a5) ; movea.l (a5),a5 ; movea.l 14(a5),a7 ; rte or rts"""
    return ('52b82000 0cb8%08x2000 6c06 61000010 60ec 4e71 52b82004 61000004 60f6 61000004 4e75' % limit
            + push_sr + '2b4f000e 2a55 2e6d000e' + yield_ends_in).replace(' ', '')


@pytest.mark.parametrize('stack_b', [0x5000, 0x7ff80], ids=['below', 'above'])
def test_two_tasks_switching_through_rte(tmp_path, stack_b):
    n = 300000                                             # a C frame per switch would not fit the C stack
    d, a, _, ram = run(tmp_path, tasks(n), {'a5': 0x3000}, auto=(BASE, 0x1016), flow=Flow(exits=[0x1014]), resume=True,
                       ram_init=task_ram(stack_b))
    assert int.from_bytes(ram[0x2000:0x2004], 'big') == n
    assert int.from_bytes(ram[0x2004:0x2008], 'big') == n - 1


@pytest.mark.parametrize('stack_b', [0x5000, 0x7ff80], ids=['below', 'above'])
def test_two_tasks_switching_through_rts(tmp_path, stack_b):
    n = 300000
    _, _, _, ram = run(tmp_path, tasks(n, '4e75', ''), {'a5': 0x3000}, auto=(BASE, 0x1016), flow=Flow(exits=[0x1014]),
                       resume=True, ram_init=task_ram(stack_b, rts_frame=True))
    assert int.from_bytes(ram[0x2000:0x2004], 'big') == n
    assert int.from_bytes(ram[0x2004:0x2008], 'big') == n - 1


def test_a_task_switch_without_resume_names_the_address(tmp_path):
    with pytest.raises(subprocess.CalledProcessError) as e:
        run(tmp_path, tasks(100), {'a5': 0x3000}, auto=(BASE, 0x1016), flow=Flow(exits=[0x1014]), ram_init=task_ram(0x5000))
    assert e.value.returncode == 4                         # unknown routine 001024: the stacked PC is inside a routine


def test_resume_keeps_ordinary_returns(tmp_path):
    # the handler's plain rte under TASK_RUN: the run ends where it would without --resume
    code = '4e43 40c3 7201 4e75 40c2 7005 4e73'.replace(' ', '')
    d, a, _, _ = run(tmp_path, code, {}, '11111', auto=(BASE, 0x1008), ram_init={0x8c: be32(0x1008)}, resume=True)
    assert (d[0], d[1], d[2], d[3]) == (5, 1, 0x201f, 0x001f) and a[7] == 0x80000 - 0x100 + 4


def test_resume_pushed_target_and_profile_refused(tmp_path):
    # after a jump the run has no C caller to return to: it ends at an exit (or the host's stop)
    d, a, _, _ = run(tmp_path, '2f3c0000100a 40e7 4e73 7001 4e71'.replace(' ', ''), {}, auto=(BASE, 0x100a), resume=True,
                     flow=Flow(exits=[0x100c]))
    assert d[0] == 1 and a[7] == 0x80000 - 0x100
    with pytest.raises(ValueError, match='--resume'):
        recomp.generate(bytes.fromhex('4e75'), BASE, auto=[BASE], profile=True, resume=True)


def test_a_resumed_routine_that_ends_in_an_rts_to_a_pushed_target_goes_on_there(tmp_path):
    """1.0.62 (SWIV, landscapes 2-4: "unknown routine 640001"): after C frames were dropped (here an rts to a pushed
    target; in the game an interrupt), the run goes on from the 68000's stack - TASK_RUN calls the address the last rts
    popped. A routine resumed that way pushes a continuation (pea), jumps to a routine through a register and that one's
    rts pops the continuation: the stack is where it was, and the loop took that for "the target did nothing", skipped
    the continuation and called the next long on the stack.
    1000 bsr 1020 ; 1004 pea 1010(pc) ; 1008 lea 1014(pc),a1 ; 100c jmp (a1) ; 100e nop
    1010 moveq #7,d2 ; 1012 nop (exit) ; 1014 moveq #1,d1 ; 1016 rts
    1020 move.l #$1030,-(a7) ; 1026 rts (a jump: the C frames go) ; 1030 moveq #3,d3 ; 1032 rts (back to 1004, from the stack)"""
    code = ('6100001e' '487a000a' '43fa000a' '4ed1' '4e71' '7407' '4e71' '7201' '4e75' + '4e71' * 4
            + '2f3c00001030' '4e75' + '4e71' * 4 + '7603' '4e75')
    d, a, _, _ = run(tmp_path, code, {}, auto=(BASE, 0x1004, 0x1010, 0x1014, 0x1030), resume=True,
                     flow=Flow(exits=[0x1012], dynamic=[0x100c]))
    assert (d[1], d[2], d[3]) == (1, 7, 3) and a[7] == 0x80000 - 0x100


def test_resume_module_and_cli(tmp_path):
    src, _, _ = recomp.generate(bytes.fromhex('7001 4e71 4e75'.replace(' ', '')), 0x8000, auto=[0x8000], resume=True,
                                flow=Flow(lib=True, prefix=('m_', 0x8000, 0x8006), module=(0x8000, 6)))
    assert 'a --resume module needs' in src and 'case 0x8002u: RESUME_PC = 0x8002u; f_m_008000(m); return;' in src
    p = tmp_path / 'p.bin'
    p.write_bytes(bytes.fromhex('7001 4e71 4e75'.replace(' ', '')))
    out = tmp_path / 'o.c'
    assert cli.main(['recomp', str(p), '--base', '0x1000', '--auto', '0x1000', '--resume', '-o', str(out)]) == 0
    text = out.read_text()
    assert '#define AREK_RESUME 1' in text and 'case 0x1002u: RESUME_PC = 0x1002u; f_001000(m); return;' in text


@pytest.mark.parametrize('how', ['indirect', 'dynamic', 'pushed'])
def test_a_target_with_a_flag_in_its_top_byte(tmp_path, how):
    """1.0.27 (Xenon 2 KIT-GAP 6): the 68000 has 24 address lines; $ff00100c is $00100c.
    1000 movea.l #$ff00100c,a1 ; 1006 jsr (a1) ; 1008 rts ; 100a nop ; 100c moveq #1,d0 ; 100e rts
    pushed: 1000 move.l #$ff00100c,-(a7) ; 1006 rts ..."""
    if how == 'pushed':
        code, flow = '2f3cff00100c 4e75 4e75 4e71 7001'.replace(' ', ''), Flow()
    else:
        code = '227cff00100c 4e91 4e75 4e71 7001'.replace(' ', '')
        flow = Flow(indirect={0x1006: [0x100c]}) if how == 'indirect' else Flow(dynamic=[0x1006])
    d, a, _, _ = run(tmp_path, code, {}, auto=(BASE, 0x100c), flow=flow)
    assert d[0] == 1 and a[7] == 0x80000 - 0x100 + 4


# --- 1.0.40: the audit of 2026-11-10 -------------------------------------------------------------------------------
def test_a_callee_that_removes_its_own_argument_returns_to_its_caller(tmp_path):
    """main: move.w #5,-(a7); bsr f; move.l #1,$4000; rts   f: movea.l (a7)+,a0; addq.l #2,a7; move.l a0,-(a7); rts.
    Before, a7 above the caller's sp0 after the call was read as "returned to the caller's caller": main ended at the
    bsr and $4000 stayed 0, without a word."""
    main = '3f3c0005' '6100000e' '23fc0000000100004000' '4e75'
    f = '205f' '548f' '2f08'                                   # + the rts run() appends
    d, a, _, ram = run(tmp_path, main + f, {'a7': 0x7ff00})
    assert ram[0x4000:0x4004] == be32(1) and a[7] == 0x7ff04


def test_a_callee_that_pops_a_long_argument_twice_in_a_row(tmp_path):
    """main: move.l #7,-(a7); bsr f; move.l #9,-(a7); bsr f; move.l d0,$4000; rts
    f: movea.l (a7)+,a0; move.l (a7)+,d1; add.l d1,d0; move.l a0,-(a7); rts - the same callee from two sites, the stack
    after each call exactly at the caller's entry level."""
    main = '2f3c00000007' '61000014' '2f3c00000009' '6100000a' '23c000004000' '4e75'
    f = '205f' '221f' 'd081' '2f08'
    d, a, _, ram = run(tmp_path, main + f, {'a7': 0x7ff00})
    assert ram[0x4000:0x4004] == be32(16) and d[0] == 16 and a[7] == 0x7ff04


def test_movem_postincrement_with_the_base_register_in_the_list(tmp_path):
    """movem (An)+,list with An in the list: An ends as the address after the last word read, the value loaded for it
    is lost (Moira: writeA after the loop). The translation kept the loaded value."""
    ram = {0x4000: be32(0x11111111) + be32(0x22222222)}
    d, a, _, _ = run(tmp_path, '4cd80101', {'a0': 0x4000}, ram_init=ram)            # movem.l (a0)+,d0/a0
    assert d[0] == 0x11111111 and a[0] == 0x4008
    d, a, _, _ = run(tmp_path, '4c980101', {'a0': 0x4000}, ram_init={0x4000: bytes.fromhex('8001 7fff'.replace(' ', ''))})   # movem.w
    assert d[0] == 0xffff8001 and a[0] == 0x4004
    d, a, _, _ = run(tmp_path, '4cd80201', {'a0': 0x4000}, ram_init=ram)            # movem.l (a0)+,d0/a1: the base not in the list
    assert d[0] == 0x11111111 and a[1] == 0x22222222 and a[0] == 0x4008
