"""arek.m68k.timing.bus: bus cycles n(r/w) of every instruction, as the MC68000 User's Manual lists them."""
import json
from pathlib import Path

import pytest

from arek.m68k import decoder, timing

ROWS = [l.rstrip('\n').split('\t') for l in (Path(__file__).parent / 'data' / 'moira68000_cycles.tsv').open()
        if l.strip() and not l.startswith('#')]


def dec(code):
    return decoder.decode(bytes.fromhex(code + '0000'), 0x1000, 0x1000)


# hex, (reads, writes), clocks - table 8 of the manual
MANUAL = [
    ('3000', (1, 0), 4),            # move.w d0,d0
    ('2080', (1, 2), 12),           # move.l d0,(a0)
    ('2050', (3, 0), 12),           # movea.l (a0),a0
    ('2278 1000', (4, 0), 16),      # movea.l $1000.w,a1
    ('3150 0010', (3, 1), 16),      # move.w (a0),16(a0)
    ('d050', (2, 0), 8),            # add.w (a0),d0
    ('d1a8 0004', (4, 2), 24),      # add.l d0,4(a0)
    ('b040', (1, 0), 4),            # cmp.w d0,d0
    ('4250', (2, 1), 12),           # clr.w (a0)
    ('4280', (1, 0), 6),            # clr.l d0
    ('4e90', (2, 2), 16),           # jsr (a0)
    ('4eb9 0000 1000', (3, 2), 20),  # jsr $1000.l
    ('4ed0', (2, 0), 8),            # jmp (a0)
    ('4ef9 0000 1000', (3, 0), 12),  # jmp $1000.l
    ('4e75', (4, 0), 16),           # rts
    ('4e73', (5, 0), 20),           # rte
    ('4e71', (1, 0), 4),            # nop
    ('4cd8 00ff', (19, 0), 76),     # movem.l (a0)+,d0-d7
    ('48a0 00ff', (2, 8), 40),      # movem.w d0-d7,-(a0)
    ('41e8 0010', (2, 0), 8),       # lea 16(a0),a0
    ('4850', (1, 2), 12),           # pea (a0)
    ('4e50 0000', (2, 2), 16),      # link a0,#0
    ('4e58', (3, 0), 12),           # unlk a0
    ('4a50', (2, 0), 8),            # tst.w (a0)
    ('5250', (2, 1), 12),           # addq.w #1,(a0)
    ('5240', (1, 0), 4),            # addq.w #1,d0
    ('0640 0001', (2, 0), 8),       # addi.w #1,d0
    ('0650 0001', (3, 1), 16),      # addi.w #1,(a0)
    ('0c90 0000 0001', (5, 0), 20),  # cmpi.l #1,(a0)
    ('0810 0003', (3, 0), 12),      # btst #3,(a0)
    ('0150', (2, 1), 12),           # bchg d0,(a0)
    ('0100', (1, 0), 6),            # btst d0,d0
    ('e1d0', (2, 1), 12),           # asl.w (a0)
    ('e348', (1, 0), 8),            # lsl.w #1,d0
    ('b148', (3, 0), 12),           # cmpm.w (a0)+,(a0)+
    ('d148', (3, 1), 18),           # addx.w -(a0),-(a0)
    ('d188', (5, 2), 30),           # addx.l -(a0),-(a0)
    ('c108', (3, 1), 18),           # abcd -(a0),-(a0)
    ('40c0', (1, 0), 6),            # move sr,d0
    ('40d0', (2, 1), 12),           # move sr,(a0)
    ('46d0', (2, 0), 16),           # move (a0),sr
    ('6100 0010', (2, 2), 18),      # bsr.w
    ('6000 0010', (2, 0), 10),      # bra.w
    ('50c0', (1, 0), 6),            # st d0
    ('50d0', (2, 1), 12),           # st (a0)
    ('b150', (2, 1), 12),           # eor.w d0,(a0)
    ('c0d0', (2, 0), 74),           # mulu (a0),d0 (worst case)
    ('7001', (1, 0), 4),            # moveq #1,d0
    ('4840', (1, 0), 4),            # swap d0
    ('c141', (1, 0), 6),            # exg d0,d1
]


@pytest.mark.parametrize('code, rw, clocks', MANUAL, ids=[m[0] for m in MANUAL])
def test_manual_rows(code, rw, clocks):
    i = dec(code.replace(' ', ''))
    assert timing.bus(i) == rw
    p = timing.bus_pattern(i)
    assert p['cycles'] == clocks and p['reads'] == rw[0] and p['writes'] == rw[1]
    assert p['internal'] == clocks - 4 * sum(rw) and p['internal'] >= 0
    assert p['words'] == len(code.replace(' ', '')) // 4


def test_to_ccr():
    i = dec('023c0001')                                                   # andi #1,ccr
    assert timing.bus(i) == (3, 0) and timing.cycles(i) == 20


def test_branches_and_loops():
    bne = dec('6602')
    assert timing.bus(bne) == (2, 0) and timing.bus(bne, taken=False) == (1, 0)
    assert timing.bus(dec('66000010'), taken=False) == (2, 0)
    dbf = dec('51c8fffe')
    assert [timing.bus(dbf, dbcc=x) for x in ('loop', 'expired', 'cc')] == [(2, 0), (3, 0), (2, 0)]
    assert timing.bus_pattern(dbf, dbcc='expired') == {'words': 2, 'reads': 3, 'writes': 0, 'cycles': 14, 'internal': 2}


@pytest.mark.parametrize('code, kw, cycles, text', ROWS, ids=[r[3] for r in ROWS])
def test_every_kind_fits_its_clocks(code, kw, cycles, text):
    # the bus cycles never exceed the clocks and what is left is whole internal cycles (even)
    i = dec(code)
    kw = json.loads(kw)
    r, w = timing.bus(i, taken=kw.get('taken', True), dbcc=kw.get('dbcc', 'loop'))
    internal = int(cycles) - 4 * (r + w)
    assert internal >= 0 and internal % 2 == 0, (text, r, w, cycles)
    assert r >= 1                                                        # the opcode word at least
