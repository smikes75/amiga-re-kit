"""1.0.48 (SWIV KIT-GAPS 3): a switch whose values span more than a WebAssembly br_table holds comes out of emcc wrong.
The dispatchers of a translation are therefore emitted by 4 KB blocks (Gen.emit_switch)."""
import random
import shutil
import subprocess

import pytest

from arek.m68k import recomp


class _Out:
    SWITCH_SPAN = recomp.Gen.SWITCH_SPAN

    def __init__(self):
        self.lines = []

    def emit(self, s=''):
        self.lines.append(s)


def _addresses():
    """Every instruction of two code areas, as a --resume dispatcher has them (no game's addresses: random steps)."""
    rnd = random.Random(1)
    out = []
    for lo, hi in ((0x8, 0x7fa8), (0xefc0, 0x12000)):
        a = lo
        while a < hi:
            out.append(a)
            a += rnd.choice((2, 2, 4, 4, 4, 6, 6, 8))
    return out


def _program(addrs, blocks):
    o = _Out()
    o.emit('#include <stdio.h>\n#include <stdint.h>\nstatic uint32_t GOT; static int BAD;')
    for a in addrs:
        o.emit('__attribute__((noinline)) static void f_%x(void) { GOT = 0x%xu; }' % (a, a))
    o.emit('__attribute__((noinline)) void call_addr(uint32_t a) {')
    cases = [(a, 'f_%x(); return;' % a) for a in addrs]
    if blocks:
        recomp.Gen.emit_switch(o, 'a', cases, '    ')
    else:
        o.emit('    switch (a) {')
        for v, st in cases:
            o.emit('    case 0x%xu: %s' % (v, st))
        o.emit('    }')
    o.emit('    BAD++;\n}')
    o.emit('static const uint32_t A[] = {%s};' % ','.join('0x%xu' % a for a in addrs))
    o.emit('int main(void) { volatile uint32_t v; int n = (int)(sizeof A / sizeof *A);')
    o.emit('    for (int i = 0; i < n; i++) { v = A[i]; GOT = 0; call_addr(v); if (GOT != A[i]) BAD++; v = A[i] + 1; call_addr(v); }')
    o.emit('    printf("bad %d of %d\\n", BAD - n, n); return 0; }')          # the odd addresses have no case: n defaults
    return '\n'.join(o.lines)


def test_a_wide_switch_is_emitted_by_blocks():
    o = _Out()
    recomp.Gen.emit_switch(o, 'a', [(0x1000, 'x();'), (0x1ffe, 'y();')], '  ')
    assert o.lines == ['  switch (a) {', '  case 0x1000u: x();', '  case 0x1ffeu: y();', '  }']        # narrow: as before
    o = _Out()
    recomp.Gen.emit_switch(o, 'a', [(0x1000, 'x();'), (0x1ffe, 'y();'), (0x7ff00, 'z();')], '  ')
    assert o.lines == ['  switch (a >> 12) {', '  case 0x1u: switch (a) {', '      case 0x1000u: x();', '      case 0x1ffeu: y();',
                       '      } break;', '  case 0x7fu: switch (a) {', '      case 0x7ff00u: z();', '      } break;', '  }']
    o = _Out()
    recomp.Gen.emit_switch(o, 'a', [], '')
    assert o.lines == ['switch (a) {', '}']


def test_a_resume_dispatcher_over_two_far_areas_uses_blocks():
    img = bytearray(0x12000)
    for at in (0x1000, 0x11000):
        img[at:at + 6] = bytes.fromhex('52404e714e75')                    # addq.w #1,d0; nop; rts
    src, _, _ = recomp.generate(bytes(img), 0, auto=[0x1000, 0x11000], resume=True)
    body = src[src.index('void call_addr(M68 *m, uint32_t a) {'):]
    body = body[:body.index('\n}')]
    assert 'switch (a >> 12) {' in body and 'case 0x11u: switch (a) {' in body
    assert 'case 0x11002u: RESUME_PC = 0x11002u; f_011000(m); return;' in body and 'case 0x1000u: f_001000(m); return;' in body


def test_a_wide_switch_in_wasm(tmp_path):
    """Measured with emcc 6.0.12: one switch over these addresses misses most of its cases in wasm (natively it is
    right); by blocks every address reaches its routine. The plain form is checked only to say when the compiler no
    longer needs this."""
    if not (shutil.which('emcc') and shutil.which('node')):
        pytest.skip('no emcc / node')
    addrs = _addresses()

    def run(blocks):
        c = tmp_path / ('b%d.c' % blocks)
        c.write_text(_program(addrs, blocks))
        js = tmp_path / ('b%d.js' % blocks)
        r = subprocess.run(['emcc', '-O2', '-w', str(c), '-o', str(js)], capture_output=True, text=True)
        if r.returncode:
            return 'build failed'
        return subprocess.run(['node', str(js)], capture_output=True, text=True).stdout.strip()
    assert run(1) == 'bad 0 of %d' % len(addrs)
    plain = run(0)
    if plain == 'bad 0 of %d' % len(addrs):
        pytest.skip('this emcc compiles the plain switch right')
