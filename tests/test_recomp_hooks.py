"""Wait-loop hooks, rte as the end of a path, bit-operation texts, the timing helpers of an
overlay module (--lib --timing) and address spellings on the command line."""
import argparse
import shutil
import subprocess

import pytest

from arek import cli
from arek.m68k import decoder, recomp
from arek.m68k.decoder import Flow

from test_recomp_semantics import BASE, run


def prog(text):
    return bytes.fromhex(text.replace(' ', ''))


def test_rte_ends_a_path():
    # rte ; dc.w $b008 (not a 68000 instruction) ; rts
    p = prog('4e73 b008 4e75')
    ins, _, bad, _ = decoder.walk(p, BASE, BASE, BASE, BASE + len(p))
    assert list(ins) == [BASE] and not bad


@pytest.mark.parametrize('code, text', [
    ('0839 0007 00bfe001', 'btst #7,$bfe001.l'),
    ('0110', 'btst d0,(a0)'),
    ('08f9 0003 0000 1000', 'bset #3,$1000.l'),
    ('01b9 00dff002', 'bclr d0,$dff002.l'),
    ('0841 001f', 'bchg #31,d1'),
])
def test_bit_operations_show_their_operands(code, text):
    assert decoder.decode(prog(code) + b'\0' * 4, BASE, BASE).text == text


WAITS = [
    # tst.w $2000.l ; bne.s back
    ('4a79 0000 2000 66f8', '0x2000u'),
    # btst #7,$bfe001.l ; bne.s back
    ('0839 0007 00bf e001 66f6', '0xbfe001u'),
    # cmpi.b #55,$c21208.l ; beq.s back
    ('0c39 0037 00c2 1208 67f6', '0xc21208u'),
    # cmp.w (4,a0),d0 ; bne.s back
    ('b068 0004 66fa', '(uint32_t)(m->a[0] + (4))'),
    # cmpa.l $3000.l,a1 ; bne.s back
    ('b3f9 0000 3000 66f8', '0x3000u'),
]


@pytest.mark.parametrize('code, addr', WAITS)
def test_wait_loop_gets_a_hook(code, addr):
    src, _, _ = recomp.generate(prog(code + ' 4e75'), BASE, auto=[BASE])
    assert 'WAIT_LOOP(m, 0x1000u, %s); goto L001000;' % addr in src
    assert '#define WAIT_LOOP(m, pc, addr) ((void)0)' in src


@pytest.mark.parametrize('code', [
    '4a40 66fc',                   # tst.w d0 ; bne: a register, nothing to wait for
    '4a58 66fc',                   # tst.w (a0)+ ; bne: walks memory, not a poll
    '4a79 0000 2000 4e71 66f6',    # tst.w $2000.l ; nop ; bne: not the instruction right before
    '51c8 fffe',                   # dbf d0,* : a counting loop
])
def test_other_loops_get_no_hook(code):
    src, _, _ = recomp.generate(prog(code + ' 4e75'), BASE, auto=[BASE])
    assert 'WAIT_LOOP(m, 0x' not in src


def test_the_host_hook_lets_a_wait_loop_end(tmp_path):
    # tst.w $2000.l ; bne.s back ; moveq #1,d0 ; rts - RAM $2000 = $0101, the hook clears it
    hook = '#define WAIT_LOOP(m, pc, addr) (MEM[(addr)] = MEM[(addr) + 1] = 0, WAITS++)\nstatic int WAITS;\n'
    d, *_ = run(tmp_path, '4a79 0000 2000 66f8 7001'.replace(' ', ''), {}, pre_c=hook,
                ram_init={0x2000: b'\x01\x01'})
    assert d[0] == 1


def test_lib_with_timing_carries_its_helpers_and_shares_them(tmp_path):
    cc = shutil.which('cc') or shutil.which('gcc') or shutil.which('clang')
    if not cc:
        pytest.skip('no C compiler')
    # module at $2000: mulu.w d1,d0 ; rts
    msrc, _, _ = recomp.generate(prog('c0c1 4e75'), 0x2000, auto=[0x2000], timing=True,
                                 flow=Flow(prefix=('m1_', 0x2000, 0x3000), lib=True))
    assert 'static uint32_t mulu_t' in msrc and '#ifndef AREK_TIMING' in msrc
    assert '#define MEMSZ' not in msrc
    main, _, _ = recomp.generate(prog('7001 4e75'), BASE, auto=[BASE], timing=True)
    c = tmp_path / 'both.c'
    c.write_text(main + '\n' + msrc)                     # module after the main translation
    subprocess.run([cc, '-c', '-Werror', '-Wno-unused-function', '-o', str(tmp_path / 'both.o'), str(c)],
                   check=True)
    # a host that defines its own TICK first keeps it: the module only defines TICK when missing
    assert msrc.index('#ifndef TICK') < msrc.index('#define TICK(pc, n) (COV_TICK(pc), PROF_TICK(n), CYCLES += (n))')


def test_address_spellings(capsys):
    assert cli.A('$1000') == cli.A('0x1000') == 0x1000 and cli.A('4096') == 4096
    with pytest.raises(argparse.ArgumentTypeError, match='0xc00000'):
        cli.A('c00000')
    assert cli.AH('100000') == 100000
    assert 'read as decimal (0x186a0)' in capsys.readouterr().err
    cli.AH('0x100000')
    assert capsys.readouterr().err == ''
    assert recomp.parse_func_spec('$1000:0x1010') == (0x1000, 0x1010, 0x1000)
