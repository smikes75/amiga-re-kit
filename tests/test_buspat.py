"""1.0.55: the bus pattern of every instruction (arek.m68k.buspat), measured on Moira and kept in buspat.json. The
corpus (tests/data/buspat_corpus.json: one program per shape with Moira's events) replays without Moira."""
import json
import os
import subprocess

import pytest

from arek import bus
from arek.m68k import buspat, decode, recomp

HERE = os.path.dirname(os.path.abspath(__file__))
BUS = os.path.dirname(bus.__file__)


def _expand(v, cyc):
    fixed, out = buspat._fixed(v['items']), []
    for x in v['items']:
        x = cyc - fixed if x == 'V' else x
        if isinstance(x, int):
            if x and out and isinstance(out[-1], int):
                out[-1] += x
            elif x:
                out.append(x)
        else:
            out.append(x)
    return out


def test_the_table_gives_moiras_pattern_for_every_shape():
    corpus = json.load(open(os.path.join(HERE, 'data', 'buspat_corpus.json')))
    progs = [(k, p) for k, p in corpus['shapes'].items()] + [(k, p) for k, ps in corpus['more'].items() for p in ps]
    assert len(corpus['shapes']) > 1300
    n = 0
    for k, p in progs:
        ins = decode(bytes.fromhex(p['code']) + bytes(16), 0x8000, 0x8000)
        assert buspat.key(ins) == k
        vs = buspat.variants(ins)
        assert vs, k
        for busev, poll, cyc in p['runs']:
            items, starts = buspat.canon(busev)
            v = next((x for x in vs if x['clocks'] == cyc), None) or next((x for x in vs if x['clocks'] == 0), None)
            assert v is not None and _expand(v, cyc) == items and tuple(v['poll']) == buspat.poll_of(busev, poll, starts), (k, cyc, v, items)
            n += 1
    assert n > 1700


def test_patterns_of_known_instructions():
    v = lambda hx: buspat.variants(decode(bytes.fromhex(hx) + bytes(8), 0, 0))
    assert v('2b4f000e') == [{'clocks': 0, 'items': ['p', 'd', 'd', 'p'], 'poll': [2, 2]}]     # move.l a7,14(a5): sampled between the two write words
    assert v('2a55') == [{'clocks': 0, 'items': ['d', 'd', 'p'], 'poll': [2, 2]}]             # movea.l (a5),a5
    assert v('52680004') == [{'clocks': 0, 'items': ['p', 'd', 'p', 'd'], 'poll': [2, 2]}]    # addq.w #1,4(a0): read, prefetch (sample), write
    assert v('61000010') == [{'clocks': 0, 'items': [2, 'd', 'd', 'p', 'p'], 'poll': [3, 2]}]  # bsr.w: 2 idle, the return address, two prefetches
    assert v('e348')[0]['items'] == ['p', 'V'] and v('c0c1')[0]['items'] == ['p', 'V']       # lsl.w #n,d0; mulu: the prefetch, then the clocks the data asks for
    # the whole gap is the data's: random operands never gave mulu fewer than two 1 bits, and a floor of 38 clocks made
    # SWIV's mulu by $20 (36) one colour clock too long
    assert v('c0e9000a')[0]['items'] == ['p', 'd', 'p', 'V'] and v('80fc0003')[0]['items'] == ['p', 'V', 'p']   # mulu 10(a1),d0; divu #3,d0: divides before its prefetch
    assert {x['clocks'] for x in v('6602')} == {8, 10} and v('6b04') == v('6602') and {x['clocks'] for x in v('51c8fffe')} == {10, 12, 14}   # bne.s = bmi.s (one shape for every condition); dbcc
    assert [x for x in v('51c8fffe') if x['clocks'] == 14][0]['items'] == [2, 'p', 'p', 'p']
    m = v('4cdf7ffe')[0]                                                                       # movem.l (a7)+,d1-a6: 14 registers
    assert m['items'] == ['p'] + ['d', 'd'] * 14 + ['d', 'p'] and m['poll'] == [30, 2]
    assert buspat.encode({'clocks': 0, 'items': [2, 'p', 'V', 'd'], 'poll': [-1, 0]}) == bytes([4, 255, 0, 2, 0x80, 0xfe, 0x81])


HARNESS = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "arek_bus.h"
static uint16_t rd16(void *c, uint32_t a) { (void)c; (void)a; return 0xffff; }
int main(int argc, char **argv) {
    static uint8_t own[313 * 227]; static uint16_t regs[0x100];
    ArekBus B; arek_bus_init(&B, 227, 312, 313, own, regs, rd16, 0);
    arek_bus_frame(&B, 312);
    uint8_t pat[64]; int n = 0; for (int i = 1; i < argc - 2; i++) pat[n++] = (uint8_t)strtoul(argv[i], 0, 0);
    uint32_t clocks = (uint32_t)atoi(argv[argc - 2]); int datas = atoi(argv[argc - 1]);
    for (int busy = 0; busy < 2; busy++) {
        memset(own, 0, sizeof own); if (busy) for (int k = 1005; k < 1011; k++) own[k] = 8;      /* DMA in six slots */
        double t = 1000, t0 = t;
        t = arek_bus_pat_begin(&B, t, pat, clocks);
        for (int k = 0; k < datas; k++) t = arek_bus_data(&B, t);
        t = arek_bus_insn_end(&B, t);
        printf("dt %.1f poll %.1f slots", t - t0, B.pat_poll - t0);
        for (long k = 1000; k < 1060; k++) if (own[k] == AREK_BUS_CPU) printf(" %ld", k - 1000);
        printf("\n");
    }
    return 0;
}
'''


def test_the_bus_model_runs_a_pattern(tmp_path):
    """The model's executor: idle clocks and bus cycles in the pattern's order, the translation's accesses taking its
    data cycles (too few: the model makes the rest at the end; too many: ignored), the sample time by the pattern."""
    cc = bus.compiler()
    if not cc:
        pytest.skip('no C compiler')
    (tmp_path / 'h.c').write_text(HARNESS)
    exe = tmp_path / 'h'
    subprocess.run([cc, '-O1', '-I', BUS, str(tmp_path / 'h.c'), os.path.join(BUS, 'arek_bus.c'), os.path.join(BUS, 'arek_bus_vamiga.c'), '-lm', '-o', str(exe)], check=True)

    def run(v, clocks, datas):
        r = subprocess.run([str(exe)] + [str(b) for b in buspat.encode(v)] + [str(clocks), str(datas)], capture_output=True, text=True, check=True)
        return [line.split() for line in r.stdout.splitlines()]
    addq = {'clocks': 0, 'items': ['p', 'd', 'p', 'd'], 'poll': [2, 2]}                 # addq.w #1,4(a0)
    free, busy = run(addq, 16, 2)
    assert free[:4] == ['dt', '8.0', 'poll', '5.0'] and free[5:] == ['1', '3', '5', '7']        # four cycles, sampled 1 colour clock into the third
    assert busy[:2] == ['dt', '14.0'] and busy[3] == '5.0' and busy[5:] == ['1', '3', '11', '13']   # slots 5-10 are DMA's: the third cycle waits, sampled before its wait
    assert run(addq, 16, 0)[0] == free and run(addq, 16, 5)[0] == free                    # the translation's accesses do not change the count
    shift = {'clocks': 0, 'items': ['p', 'V'], 'poll': [0, 2]}                           # lsl.w #3,d0: 12 clocks
    assert run(shift, 12, 0)[0][:4] == ['dt', '6.0', 'poll', '1.0']
    bsr = {'clocks': 0, 'items': [2, 'd', 'd', 'p', 'p'], 'poll': [3, 2]}
    assert run(bsr, 18, 2)[0][:6] == ['dt', '9.0', 'poll', '8.0', 'slots', '2']


def test_a_translation_carries_the_patterns():
    img = bytearray(0x2000)
    img[0x1000:0x100a] = bytes.fromhex('52680004' '51c8fffa' '4e75')                    # addq.w #1,4(a0); dbf d0; rts
    src, _, _ = recomp.generate(bytes(img), 0, auto=[0x1000], timing=True, bus_table=True)
    assert '#define BUS_ROW6 1' in src and 'static const uint8_t BUS_PAT[' in src and 'static const uint16_t BUS_VAR[' in src
