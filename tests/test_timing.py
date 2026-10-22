"""arek.m68k.timing against clock counts measured on Moira (tests/data/moira68000_cycles.tsv).

The table holds one representative per instruction kind x size x addressing class (915) and the
data-dependent cases (MULU/MULS/DIVU/DIVS operands, register shift counts, bit numbers). The full
sweep - every opcode the decoder accepts, 42 247 of them - matched Moira when the table was made."""
import json
from pathlib import Path

import pytest

from arek.m68k import decoder, timing

ROWS = [l.rstrip('\n').split('\t') for l in (Path(__file__).parent / 'data' / 'moira68000_cycles.tsv').open()
        if l.strip() and not l.startswith('#')]


@pytest.mark.parametrize('code, kw, cycles, text', ROWS, ids=[r[3] for r in ROWS])
def test_cycles_match_moira(code, kw, cycles, text):
    i = decoder.decode(bytes.fromhex(code + '0000'), 0x1000, 0x1000)
    # the table predates bit operands and dbcc targets in the text
    assert i.text == text or (i.kind == 'bit' and i.text.split()[0] == text) or \
        (i.kind == 'dbcc' and i.text.split(',')[0] == text)
    assert timing.cycles(i, **json.loads(kw)) == int(cycles)


def test_table_covers_every_kind():
    kinds = {decoder.decode(bytes.fromhex(r[0] + '0000'), 0x1000, 0x1000).kind for r in ROWS}
    assert kinds >= {'move', 'moveq', 'alu', 'alui', 'addq', 'adda', 'suba', 'cmpa', 'eor', 'clr', 'neg',
                     'negx', 'not', 'tst', 'scc', 'bit', 'shift', 'bcc', 'bra', 'bsr', 'dbcc', 'jmp',
                     'jsr', 'lea', 'pea', 'movem', 'sr', 'mulu', 'muls', 'divu', 'divs', 'bcd', 'addx',
                     'cmpm', 'exg', 'ext', 'swap', 'link', 'unlk', 'nop', 'rts', 'rte'}


def test_worst_case_without_data_and_exactness():
    mulu = decoder.decode(bytes.fromhex('c0c1'), 0, 0)
    assert timing.cycles(mulu) == 70 and not timing.exact(mulu)
    nop = decoder.decode(bytes.fromhex('4e71'), 0, 0)
    assert timing.exact(nop)
    bne = decoder.decode(bytes.fromhex('6602'), 0, 0)
    assert (timing.cycles(bne), timing.cycles(bne, taken=False)) == (10, 8)


def test_listing_with_cycles(tmp_path, capsys):
    from arek import cli
    f = tmp_path / 'p.bin'
    f.write_bytes(bytes.fromhex('2010' '6602' 'c0c1' '4e75'))
    cli.main(['dis', str(f), '--base', '0x1000', '--cycles'])
    out = capsys.readouterr().out
    assert '; 12 clk' in out and '; 10 taken, 8 not clk' in out and '; 38-70 clk' in out and '; 16 clk' in out
