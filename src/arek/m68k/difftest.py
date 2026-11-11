"""The translation against the 68000, instruction by instruction: every opcode the decoder accepts runs on Moira (vAmiga's
CPU, Dirk W. Hoffmann, MIT) and through ``recomp.generate`` from the same registers and RAM; registers, SR, memory, the
place it ended and the clock count must agree. (1.0.26; a game finds such a slip after days, this finds it in minutes.)

``sweep`` needs the vAmiga source and a C++ compiler (``arek difftest --moira DIR``). ``record`` keeps a sample of the
cases with Moira's results as a text file, and ``check_corpus`` replays such a file through the translation with a C
compiler alone: that is what the kit's tests do. No game data: the RAM is a computed pattern, the code is generated.

Not compared, by design of the translation: cases where Moira raised an exception other than TRAP (address error, division by
zero, privilege, trace; the translation has no exceptions but TRAP), accessed something above the mirrored chip RAM
(custom chips, CIAs), or wrote into the instruction itself; and a7 after SR lost the S bit (one a7, no USP/SSP).
"""
import gzip
import json
import os
import random
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import recomp
from .decoder import Flow, Unsupported, decode

MEMSZ = 0x40000
CODE_LO, CODE_HI = 0x8000, 0x28000       # programs; below is reachable by abs.w, above is the data window
STUB = 0x7f00                            # a routine for jsr/jmp abs.w
STACK = 0x30000
NOP = 0x4e71
CONTROL = {'bcc', 'bra', 'dbcc', 'bsr', 'jsr', 'jmp', 'rts', 'rte', 'trap'}      # templates, not the plain sweep
FLAG_NAMES = {1: 'exception', 2: 'outside RAM', 4: 'self-modifying', 8: 'no stop reached'}
HERE = Path(__file__).resolve().parent


def pattern():
    """The RAM before any program: the same bytes on both sides, nothing of any game."""
    v = 0x2545f491
    out = bytearray(MEMSZ)
    for i in range(MEMSZ):
        v = (v ^ (v << 13)) & 0xffffffff
        v ^= v >> 17
        v = (v ^ (v << 5)) & 0xffffffff
        out[i] = v & 0xff
    # jsr/jmp abs.w: nop, then an exit
    out[STUB:STUB + 4] = bytes.fromhex('4e714e71')
    return out


class Program:
    """One instruction with what it needs around it. ``build(P)`` gives the bytes and the absolute addresses at P."""

    def __init__(self, kind, build, states, text=None):
        self.kind, self.build, self.states, self.text = kind, build, states, text


def be16(v):
    return (v & 0xffff).to_bytes(2, 'big')


def be32(v):
    return (v & 0xffffffff).to_bytes(4, 'big')


INTERESTING = (0, 1, 2, 3, 0x7f, 0x80, 0xff, 0x100, 0x7fff, 0x8000, 0xffff, 0x10000, 0x7fffffff, 0x80000000, 0xffffffff,
               0xfffffffe, 0x12345678, 0x99, 0x9, 0x10, 0x1f, 0x20, 0x21, 0x3f, 0x40)


def state(rng, small=False, **over):
    """{'sr', 'd': [8], 'a': [8], 'pokes': {}} in supervisor mode, T clear, the a registers inside the data window."""
    def dreg():
        if small:
            return rng.randrange(0, 0x40) * 2
        r = rng.random()
        return rng.choice(INTERESTING) if r < .6 else rng.getrandbits(32)

    def areg():
        v = rng.randrange(0x2c000, 0x38000)
        return v & ~1 if small or rng.random() < .9 else v | 1
    s = {'sr': 0x2000 | (rng.randrange(8) << 8) | rng.getrandbits(5), 'd': [dreg() for _ in range(8)],
         'a': [areg() for _ in range(7)] + [(rng.randrange(0x2e000, 0x34000) & ~1)], 'pokes': {}}
    s.update(over)
    return s


def ext_word(rng):
    r = rng.random()
    if r < .4:
        return rng.randrange(0, 4)
    if r < .7:
        return rng.randrange(0, 0x1000) & ~1
    if r < .85:
        return rng.randrange(0x400, 0x7ffe) & ~1
    return rng.getrandbits(16)


def plain_program(code, rng, nstates=8):
    ins = decode(code + bytes(16), 0x8000, 0x8000)

    def build(P):
        return {'code': code + be16(NOP), 'entry': P, 'roots': [P], 'exits': [P + len(code)], 'dyn': [], 'self': P + len(code)}
    return Program(ins.kind, build, lambda: [state(rng, small=(k % 2 == 1)) for k in range(nstates)], ins.text)


def opcode_programs(rng, op, tries):
    """Up to ``tries`` instruction encodings of ``op``: its extension words are drawn again, and the ones the decoder refuses
    (a byte immediate with a high byte, say) do not count."""
    seen, out = set(), []
    for k in range(tries * 3):
        words = bytes(b for w in [op] + [ext_word(rng) if k % 3 else rng.randrange(0, 4) if rng.random() < .5 else rng.getrandbits(8)
                                         for _ in range(5)] for b in be16(w))
        try:
            ins = decode(words, 0x8000, 0x8000)
        except (Unsupported, IndexError, ValueError):
            continue
        code = words[:ins.end - ins.addr]
        if ins.kind in CONTROL:
            return []
        if code not in seen:
            seen.add(code)
            out.append(code)
        if len(out) >= tries:
            break
    return out


def directed_codes():
    """Encodings the random draw of extension words almost never makes (1.0.40; the audit of 2026-11-10: of the recorded
    corpus 809 of 907 first extension words were below $100, no movem had its base register in the list, no index was an
    address register). movem with the base register in and out of the list, every form of the index word, displacements
    with the sign bit, bit numbers past the operand's size."""
    out = []

    def W(*words):
        out.append(b''.join(be16(w & 0xffff) for w in words))
    for reg in (0, 1, 6):
        for op in (0x4c98, 0x4cd8):                          # movem.w / .l (An)+,list: bit n = Dn, 8 + n = An
            for mask in (0x0001 | 0x0100 << reg, 0x0100 << reg, 0xffff, 0x8001, 0x00ff, 0x7f00 & ~(0x0100 << reg) | 0x0003):
                W(op | reg, mask)
        for op in (0x48a0, 0x48e0):                          # movem.w / .l list,-(An): the mask is mirrored (bit 15 = D0, 7 - n = An)
            for mask in (0x8000 | 0x0080 >> reg, 0x0080 >> reg, 0xffff, 0x8001, 0xff00, 0x00ff & ~(0x0080 >> reg) | 0xc000):
                W(op | reg, mask)
        for op in (0x4890, 0x48d0, 0x4c90, 0x4cd0):          # list,(An) and (An),list
            for mask in (0x0101 << reg, 0xffff, 0x8001):
                W(op | reg, mask)
        for op in (0x48a8, 0x48e8, 0x4ca8, 0x4ce8):          # (d16,An)
            for d16 in (0x0010, 0xfff0, 0x7ffe, 0x8000):
                W(op | reg, 0x0303, d16)
        for op in (0x48b0, 0x48f0, 0x4cb0, 0x4cf0):          # (d8,An,Xn)
            for ext in (0x0004, 0x0804, 0x90fc, 0x98fc, 0x1080):
                W(op | reg, 0x0303, ext)
    for mask in (0x0303, 0xffff, 0x8001):
        W(0x4cba, mask, 0x0010)                              # movem.w (d16,pc),list
        W(0x4cfb, mask, 0x0810)                              # movem.l (d8,pc,Xn),list
    index = [(a << 15) | (xr << 12) | (lng << 11) | d8 for a in (0, 1) for xr in (0, 7) for lng in (0, 1) for d8 in (0x02, 0x7e, 0x80, 0xfe)]
    for reg in (0, 5):
        for ext in index:
            W(0x3030 | reg, ext)                             # move.w (d8,An,Xn),d0
            W(0x2030 | reg, ext)                             # move.l
            W(0x1030 | reg, ext)                             # move.b
            W(0x3180 | reg << 9, ext)                        # move.w d0,(d8,An,Xn)
            W(0x43f0 | reg, ext)                             # lea (d8,An,Xn),a1
            W(0x5270 | reg, ext)                             # addq.w #1,(d8,An,Xn)
        for d16 in (0x0002, 0x7ffe, 0x8000, 0xfffe, 0xff00):
            W(0x3028 | reg, d16)                             # move.w (d16,An),d0
            W(0x2140 | reg << 9, d16)                        # move.l d0,(d16,An)
            W(0x41e8 | reg, d16)                             # lea (d16,An),a0
            W(0x4a68 | reg, d16)                             # tst.w (d16,An)
    for ext in index:
        W(0x303b, ext)                                       # move.w (d8,pc,Xn),d0
        W(0x41fb, ext)                                       # lea (d8,pc,Xn),a0
    for d16 in (0x0002, 0x7ffe, 0x8000, 0xfffe):
        W(0x303a, d16)                                       # move.w (d16,pc),d0
    for op in (0x0800, 0x0840, 0x0880, 0x08c0):              # btst / bchg / bclr / bset #n
        for n in (0, 7, 8, 15, 16, 31, 32, 33, 63, 255):
            W(op, n)                                         # ,d0: the number modulo 32
            W(op | 0x10, n)                                  # ,(a0): modulo 8
            W(op | 0x28 | 1, n, 0xfffe)                      # ,(d16,a1)
    for op in (0x0100, 0x0140, 0x0180, 0x01c0):              # the same with the number in d1
        W(op | 1 << 9)
        W(op | 1 << 9 | 0x10)
    return out


def directed_programs(rng, nstates=12):
    """``directed_codes`` as programs; the encodings the decoder refuses are left out."""
    out = []
    for code in directed_codes():
        try:
            ins = decode(code + bytes(16), 0x8000, 0x8000)
        except (Unsupported, IndexError, ValueError):
            continue
        if ins.kind in CONTROL or ins.end - ins.addr != len(code):
            continue
        out.append(plain_program(code, rng, nstates))
    return out


def control_programs(rng):
    """The instructions that leave the straight line, each with a place to go: a stop of its own for both ways."""
    out = []

    def add(kind, build, states, text):
        out.append(Program(kind, build, states, text))

    def flags_states(n=8):
        return lambda: [state(rng, small=k % 2 == 1) for k in range(n)]
    for cond in range(16):
        if cond == 1:
            continue
        kind = 'bra' if cond == 0 else 'bcc'
        for wide in (0, 1):
            def build(P, cond=cond, wide=wide):
                head = be16(0x6000 | (cond << 8) | (0 if wide else 4)) + (be16(4) if wide else b'')
                return {'code': head + be16(NOP) * 3, 'entry': P, 'roots': [P], 'exits': [P + len(head), P + 6], 'dyn': [],
                        'self': P + len(head)}
            add(kind, build, lambda: [state(rng, sr=0x2000 | k) for k in range(32)], 'b%02x%s' % (cond, '.w' if wide else '.s'))
    for cond in range(16):
        for reg in range(8):
            def build(P, cond=cond, reg=reg):
                head = be16(0x50c8 | (cond << 8) | reg) + be16(4)
                return {'code': head + be16(NOP) * 3, 'entry': P, 'roots': [P], 'exits': [P + 4, P + 6], 'dyn': [], 'self': P + 4}

            def st(reg=reg):
                ss = []
                for v in (0, 1, 0xffff, 0x10000, 0x1ffff):
                    for f in (0, 4, 1, 8):
                        s = state(rng, sr=0x2000 | f)
                        s['d'][reg] = v
                        ss.append(s)
                return ss
            add('dbcc', build, st, 'db%x d%d' % (cond, reg))
    for wide in (0, 1):
        def build(P, wide=wide):
            head = be16(0x6100 | (0 if wide else 4)) + (be16(4) if wide else b'')
            t = P + 6
            return {'code': head + be16(NOP) * 4, 'entry': P, 'roots': [P], 'exits': [t + 2], 'dyn': [], 'self': P + len(head)}
        add('bsr', build, flags_states(), 'bsr' + ('.w' if wide else '.s'))
    # jsr / jmp through every control mode; the target T is a nop and an exit
    for base, kind in ((0x4e80, 'jsr'), (0x4ec0, 'jmp')):
        for reg in range(7):
            for mode, nm in ((2, '(a%d)'), (5, 'd16(a%d)'), (6, 'd8(a%d,xn)')):
                def build(P, base=base, mode=mode, reg=reg):
                    ext = b'' if mode == 2 else (be16(0x20) if mode == 5 else be16(0x1020))     # d16 = $20 ; d8 = $20, d1.w
                    head = be16(base | (mode << 3) | reg) + ext
                    t = P + len(head) + 2
                    return {'code': head + be16(NOP) * 3, 'entry': P, 'roots': [P, t], 'exits': [t + 2, P + len(head)], 'dyn': [P],
                            'self': P + len(head), 'T': t}

                def st(mode=mode, reg=reg):
                    return lambda t: [_target_state(rng, mode, reg, t) for _ in range(6)]
                add(kind, build, st(), kind + ' ' + nm % reg)
        for sub, nm in ((0, 'abs.w'), (1, 'abs.l'), (2, 'd16(pc)'), (3, 'd8(pc,xn)')):
            def build(P, base=base, sub=sub):
                dyn = []
                if sub == 0:
                    t = STUB
                    head = be16(base | 0x38) + be16(t)
                elif sub == 1:
                    t = P + 8
                    head = be16(base | 0x39) + be32(t)
                elif sub == 2:
                    t = P + 6
                    head = be16(base | 0x3a) + be16(4)
                else:
                    t = P + 6
                    head = be16(base | 0x3b) + be16(0x1004)                             # d8 = 4, d1.w
                    dyn = [P]
                return {'code': head + be16(NOP) * 4, 'entry': P, 'roots': [P, t], 'exits': [t + 2, P + len(head)], 'dyn': dyn,
                        'self': P + len(head), 'T': t}

            def st(t):
                ss = [state(rng) for _ in range(6)]
                for s in ss:
                    s['d'][1] = 0                                                # the index of d8(pc,d1.w)
                return ss
            add(kind, build, st, kind + ' ' + nm)

    def rts(P):
        return {'code': be16(0x4e75) + be16(NOP), 'entry': P, 'roots': [P], 'exits': [P + 2], 'dyn': [], 'self': P + 2, 'kind_ret': P + 2}
    add('rts', rts, lambda stop: [_stacked(state(rng), be32(stop | (0xff000000 if k % 2 else 0))) for k in range(6)], 'rts')

    def rte(P):
        return {'code': be16(0x4e73) + be16(NOP), 'entry': P, 'roots': [P], 'exits': [P + 2], 'dyn': [], 'self': P + 2, 'kind_ret': P + 2}
    add('rte', rte, lambda stop: [_stacked(state(rng), be16(0x2000 | (k << 8) | (k * 5 & 31)) + be32(stop)) for k in range(8)], 'rte')
    for n in range(16):
        def trap(P, n=n):
            h = P + 4
            return {'code': be16(0x4e40 | n) + be16(NOP) + be16(0x40c7) + be16(0x4e73), 'entry': P, 'roots': [P, h], 'exits': [P + 2], 'dyn': [],
                    'self': P + 2, 'vector': (0x80 + 4 * n, h)}
        add('trap', trap, lambda v: [_poked(state(rng), v) for _ in range(4)], 'trap #%d' % n)
    return out


def _target_state(rng, mode, reg, t):
    s = state(rng)
    s['a'][reg] = t if mode == 2 else (t - 0x20) & 0xffffffff
    if rng.random() < .5:
        s['a'][reg] |= rng.choice((0xff, 0x80, 0x01)) << 24      # a flag in the top byte: 24 address lines (1.0.27)
    s['d'][1] = 0
    return s


def _stacked(s, frame):
    s['pokes'][s['a'][7]] = frame
    return s


def _poked(s, vector):
    s['pokes'][vector[0]] = be32(vector[1])
    return s


def states_of(p, m):
    """The states of program ``p`` built as ``m``."""
    if 'T' in m:
        return p.states(m['T'])
    if 'kind_ret' in m:
        return p.states(m['kind_ret'])
    if 'vector' in m:
        return p.states(m['vector'])
    return p.states()


def case_line(m, s):
    pk = ','.join('%x=%s' % (a, b.hex()) for a, b in sorted(s['pokes'].items())) or '-'
    stops = list(m['exits']) + [0xffffffff]
    return '%x %x %x %x %x %x %s %s %s' % (m['entry'], s['a'][7], s['sr'], stops[0], stops[1], m['self'],
                                          ' '.join('%x' % v for v in s['d']), ' '.join('%x' % v for v in s['a'][:7]), pk)


DRIVER = r'''
/* --- arek difftest: one line of the cases file, one line of results, the RAM back from a copy ------------------- */
#include <setjmp.h>
static jmp_buf CASE_JB;
static uint32_t EXIT_AT;
static uint8_t INIT[MEMSZ];
void exit_point(M68 *m, uint32_t at) { (void)m; EXIT_AT = at; longjmp(CASE_JB, 1); }
void unknown_hook(uint32_t a) { EXIT_AT = a; longjmp(CASE_JB, 2); }
int main(int argc, char **argv) {
    FILE *f = fopen(argv[1], "rb");
    if (!f || fread(MEM, 1, MEMSZ, f) != MEMSZ) { fprintf(stderr, "image?\n"); return 1; }
    fclose(f);
    memcpy(INIT, MEM, MEMSZ);
    FILE *in = fopen(argv[2], "r"), *out = fopen(argv[3], "w");
    static char line[8192], pk[4096];
    while (fgets(line, sizeof line, in)) {
        uint32_t pc, sp, sr, s1, s2, se, d[8], a[7];
        int used = 0;
        if (sscanf(line, "%x %x %x %x %x %x%n", &pc, &sp, &sr, &s1, &s2, &se, &used) != 6) continue;
        const char *p = line + used;
        for (int i = 0; i < 8; i++) { sscanf(p, "%x%n", &d[i], &used); p += used; }
        for (int i = 0; i < 7; i++) { sscanf(p, "%x%n", &a[i], &used); p += used; }
        sscanf(p, "%4095s", pk);
        if (pk[0] != '-') {
            const char *s = pk;
            while (*s) {
                char *e;
                uint32_t at = (uint32_t)strtoul(s, &e, 16);
                s = e + 1;
                for (; s[0] && s[0] != ','; s += 2, at++) { char h[3] = { s[0], s[1], 0 }; MEM[at % MEMSZ] = (uint8_t)strtoul(h, NULL, 16); }
                if (*s == ',') s++;
            }
        }
        M68 m; memset(&m, 0, sizeof m);
        for (int i = 0; i < 8; i++) m.d[i] = d[i];
        for (int i = 0; i < 7; i++) m.a[i] = a[i];
        m.a[7] = sp;
        sr_set(&m, sr, 1);
        CYCLES = 0; EXIT_AT = 0;
        int how = setjmp(CASE_JB);
        if (!how) call_addr(&m, pc);
        fprintf(out, "%x %llx %x %x", how == 2 ? 16 : 0, (unsigned long long)CYCLES, EXIT_AT, sr_get(&m));
        for (int i = 0; i < 8; i++) fprintf(out, " %x", m.d[i]);
        for (int i = 0; i < 8; i++) fprintf(out, " %x", m.a[i]);
        if (memcmp(MEM, INIT, MEMSZ)) {
            int first = 1;
            for (uint32_t i = 0; i < MEMSZ; i++)
                if (MEM[i] != INIT[i]) { fprintf(out, "%s%x=%02x", first ? " " : ",", i, MEM[i]); first = 0; }
            fprintf(out, "\n");
            memcpy(MEM, INIT, MEMSZ);
        } else
            fprintf(out, " -\n");
        fflush(out);
    }
    fclose(out);
    return 0;
}
'''


def parse_result(line):
    t = line.split()
    return {'flags': int(t[0], 16), 'cycles': int(t[1], 16), 'pc': int(t[2], 16), 'sr': int(t[3], 16),
            'd': [int(x, 16) for x in t[4:12]], 'a': [int(x, 16) for x in t[12:20]], 'mem': t[20] if len(t) > 20 else '-',
            'bus': t[21] if len(t) > 22 else None, 'poll': int(t[22]) if len(t) > 22 else None}    # 1.0.55: Moira's bus pattern of the first instruction


def differences(ref, got):
    """The fields in which the translation differs from Moira, [] when it does not."""
    out = []
    if got['flags']:
        return ['unknown target $%x' % got['pc']]
    if got['pc'] and got['pc'] != ref['pc']:
        out.append('pc')
    if got['sr'] & 0x1f != ref['sr'] & 0x1f:
        out.append('ccr')
    if got['sr'] & 0xff00 != ref['sr'] & 0xff00:
        out.append('sr')
    out += ['d%d' % i for i in range(8) if got['d'][i] != ref['d'][i]]
    n = 8 if ref['sr'] & 0x2000 else 7                  # S lost: Moira's a7 is the USP, the translation has one a7
    out += ['a%d' % i for i in range(n) if got['a'][i] != ref['a'][i]]
    if got['mem'] != ref['mem']:
        out.append('memory')
    if got['cycles'] != ref['cycles']:
        out.append('cycles')
    return out


def moira_dir(path):
    p = Path(path)
    for c in (p, p / 'Core' / 'Components' / 'CPU' / 'Moira', p / 'Components' / 'CPU' / 'Moira'):
        if (c / 'Moira.cpp').exists():
            return c
    raise FileNotFoundError('no Moira.cpp in %s (give the vAmiga source or its Moira folder)' % path)


def build_harness(moira, out):
    """moira_diff, compiled with Moira's own sources; kept in ``out`` while the sources do not change."""
    cxx = shutil.which('c++') or shutil.which('g++') or shutil.which('clang++')
    if not cxx:
        raise RuntimeError('difftest needs a C++ compiler')
    m = moira_dir(moira)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    exe = out / 'moira_diff'
    src = [m / 'Moira.cpp', m / 'MoiraDebugger.cpp', m / 'MoiraCore68000.cpp', m / 'MoiraCore68010.cpp', m / 'MoiraCore68020.cpp']
    own = HERE / 'moira_diff.cpp'
    newest = max(x.stat().st_mtime for x in src + [own])
    if exe.exists() and exe.stat().st_mtime >= newest:
        return exe
    flags = ['-std=c++20', '-O1', '-w', '-I', str(HERE / 'moira_shim'), '-I', str(m)]

    def one(s):
        o = out / (Path(s).stem + '.o')
        subprocess.run([cxx] + flags + ['-c', str(s), '-o', str(o)], check=True)
        return str(o)
    with ThreadPoolExecutor(max_workers=os.cpu_count() or 2) as ex:
        objs = list(ex.map(one, src + [own]))
    subprocess.run([cxx] + objs + ['-o', str(exe)], check=True)
    return exe


def assign(programs):
    """Addresses for the programs, batch by batch: [(image, [(program, built)])] with no batch beyond the code area."""
    batches, cur, P, img = [], [], CODE_LO, pattern()
    base = bytes(img)
    for p in programs:
        m = p.build(P)
        if P + len(m['code']) + 2 > CODE_HI:
            batches.append((bytes(img), cur))
            cur, P, img = [], CODE_LO, bytearray(base)
            m = p.build(P)
        img[P:P + len(m['code'])] = m['code']
        cur.append((p, m))
        P += len(m['code']) + 2
    if cur:
        batches.append((bytes(img), cur))
    return batches


def translate_batch(work, image, built):
    """The generated C and its driver for a batch, compiled; the path of the executable, and the roots it refused."""
    cc = shutil.which('cc') or shutil.which('gcc') or shutil.which('clang')
    if not cc:
        raise RuntimeError('difftest needs a C compiler')
    roots = sorted({r for _, m in built for r in m['roots']})
    exits = sorted({e for _, m in built for e in m['exits']})
    dyn = sorted({d for _, m in built for d in m['dyn']})
    report = {}
    src, _, _ = recomp.generate(image, 0, auto=roots, lo=0, hi=MEMSZ, flow=Flow(exits=exits, dynamic=dyn), timing=True, memsz=MEMSZ,
                                oob='zero', auto_soft=True, report=report)
    work = Path(work)
    c = work / 'game.c'
    c.write_text('#define UNKNOWN_HOOK 1\n' + src + DRIVER)
    exe = work / 'game'
    r = subprocess.run([cc, '-O0', '-w', '-o', str(exe), str(c)], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError('the translation does not compile: ' + r.stderr[:2000])
    return exe, report.get('dropped', [])


def run_exe(exe, image, cases, work):
    work = Path(work)
    (work / 'image.bin').write_bytes(image)
    (work / 'cases.txt').write_text('\n'.join(cases) + '\n')
    out = work / 'out.txt'
    r = subprocess.run([str(exe), str(work / 'image.bin'), str(work / 'cases.txt'), str(out)], capture_output=True, text=True)
    rows = [parse_result(x) for x in out.read_text().splitlines()] if out.exists() else []
    return rows, r.returncode, r.stderr


def sweep(moira, build_dir, seed=1, per_opcode=3, kinds=None, jobs=None, progress=None, work=None):
    """Every opcode against Moira. Returns {'cases', 'opcodes', 'skipped', 'mismatches': [...], 'by_kind': {...}, 'rows': [...]}."""
    exe = build_harness(moira, build_dir)
    rng = random.Random(seed)
    programs, no_state = control_programs(rng), {}
    candidates = {}
    for op in range(0x10000):
        codes = opcode_programs(rng, op, 6)
        if codes:
            candidates[op] = codes
    if progress:
        progress('%d opcodes decode' % len(candidates))
    # the plain ones: the first encoding of each opcode with enough valid states; Moira decides what is valid
    chosen = []
    pending = {op: list(c) for op, c in candidates.items()}
    while pending:
        round_ = [(op, plain_program(c.pop(0), rng)) for op, c in pending.items() if c]
        if not round_:
            break
        for op, ok, why in _validate(exe, round_, per_opcode, work):
            if ok:
                chosen.append(ok)
                pending.pop(op, None)
            else:
                no_state[op] = why
        pending = {op: c for op, c in pending.items() if c}
    for op in {c[0] for c in chosen}:
        no_state.pop(op, None)
    plain = [c[1] for c in chosen]
    directed = []                                            # 1.0.40: the encodings the draw above does not reach
    for _, ok, why in _validate(exe, [(('directed', k), p) for k, p in enumerate(directed_programs(rng))], per_opcode + 2, work):
        if ok:
            ok[1]['directed'] = True
            directed.append(ok[1])
    plain += directed
    ctl = [(None, p) for p in programs]
    control_rows = []
    for _, ok, why in _validate(exe, ctl, 99, work):
        if ok:
            control_rows.append(ok[1])
    selected = plain + control_rows
    if kinds:
        selected = [p for p in selected if p['kind'] in kinds]
    groups = _groups(selected)
    for g in groups:
        _reference(exe, g, work)
    res = _compare_groups(groups, jobs, progress, work)
    res.update(programs=len(selected), opcodes=len(candidates), no_valid_state=len(no_state), selected=selected, exe=str(exe),
               directed=len(directed),
               refused=refused_opcodes(exe))
    return res


def refused_opcodes(exe):
    """{mnemonic: count} of the opcodes Moira's 68000 executes and the decoder does not know, whatever the extension words."""
    out = {}
    rng = random.Random(3)
    for line in subprocess.run([str(exe), '--list'], capture_output=True, text=True, check=True).stdout.splitlines():
        op, _, text = line.partition(' ')
        for k in range(6):
            words = be16(int(op, 16)) + bytes(b for _ in range(5) for b in be16(ext_word(rng) if k % 2 else rng.getrandbits(8)))
            try:
                decode(words, 0x8000, 0x8000)
                break
            except (Unsupported, IndexError, ValueError):
                continue
        else:
            name = text.split()[0].split('.')[0] if text.split() else '?'
            if name[0] == 'b' and int(op, 16) >> 12 == 6 and int(op, 16) & 1:
                continue                                # a branch to an odd address: an address error, no instruction
            out[name] = out.get(name, 0) + 1
    return out


def _validate(exe, rows, keep, work):
    """Run the programs' states on Moira; yields (op, (op, {...}) or None, why) with the states that were valid."""
    results = []
    with tempfile.TemporaryDirectory(dir=work) as td:
        for image, built in assign([p for _, p in rows]):
            cases, owner = [], []
            for k, (p, m) in enumerate(built):
                for s in states_of(p, m):
                    cases.append(case_line(m, s))
                    owner.append(k)
            out, rc, err = run_exe(exe, image, cases, td)
            if rc or len(out) != len(cases):
                raise RuntimeError('moira_diff failed: %s' % err[:500])
            per = {}
            why = {}
            for line, k, r in zip(cases, owner, out):
                if r['flags']:
                    why.setdefault(k, set()).add(r['flags'])
                elif len(per.setdefault(k, [])) < keep:
                    per[k].append((line, r))
            for k, (p, m) in enumerate(built):
                results.append((p, m, per.get(k), why.get(k)))
    out = []
    for (op, _), (p, m, good, why) in zip(rows, results):
        if good:
            out.append((op, (op, {'kind': p.kind, 'text': p.text, 'm': {x: m[x] for x in ('code', 'roots', 'exits', 'dyn', 'entry', 'self')}, 'base': m['entry'],
                                  'cases': good}), None))
        else:
            out.append((op, None, sorted(why or [])))
    return out


def _rebase(sel):
    """The kept programs at their own addresses: batches that do not overlap, by the address each was validated at."""
    groups, cur, used = [], [], []
    for s in sel:
        lo, hi = s['base'], s['base'] + len(s['m']['code'])
        if any(lo < b and a < hi for a, b in used):
            groups.append(cur)
            cur, used = [], []
        cur.append(s)
        used.append((lo, hi))
    if cur:
        groups.append(cur)
    return groups


def _image_for(group):
    img = pattern()
    for s in group:
        m = s['m']
        img[s['base']:s['base'] + len(m['code'])] = m['code']
    return bytes(img)


def _run_group(group, work):
    """Translate one group and run its cases; a list of (program, case line, Moira's row, translation's row)."""
    with tempfile.TemporaryDirectory(dir=work) as td:
        image = _image_for(group)
        built = [(None, s['m']) for s in group]
        exe, dropped = translate_batch(td, image, built)
        cases = [c[0] for s in group for c in s['cases']]
        rows, rc, err = run_exe(exe, image, cases, td)
        out, k = [], 0
        for s in group:
            for line, ref in s['cases']:
                got = rows[k] if k < len(rows) else None
                out.append((s, line, ref, got))
                k += 1
        return out, rc, err, dropped


def _groups(selected, size=1500):
    out = []
    for g in _rebase(selected):
        out += [g[i:i + size] for i in range(0, len(g), size)]
    return out


def _reference(exe, group, work):
    """Moira's results for the group's cases in the group's own image (code around an instruction is data to a neighbour's
    pc-relative read, so a result only holds for the image it ran on); cases no longer valid there drop out."""
    with tempfile.TemporaryDirectory(dir=work) as td:
        lines = [c[0] for s in group for c in s['cases']]
        rows, rc, err = run_exe(exe, _image_for(group), lines, td)
        if rc or len(rows) != len(lines):
            raise RuntimeError('moira_diff failed: %s' % err[:500])
    k = 0
    for s in group:
        keep = []
        for line, _ in s['cases']:
            if not rows[k]['flags']:
                keep.append((line, rows[k]))
            k += 1
        s['cases'] = keep


def _compare_groups(groups, jobs, progress, work):
    mism, total, by_kind, crashed = [], 0, {}, []
    with ThreadPoolExecutor(max_workers=jobs or os.cpu_count() or 2) as ex:
        for n, (res, rc, err, dropped) in enumerate(ex.map(lambda g: _run_group(g, work), groups)):
            if rc:
                crashed.append(err[:300] or 'exit %d' % rc)
            for s, line, ref, got in res:
                total += 1
                b = by_kind.setdefault(s['kind'], {'cases': 0, 'bad': 0})
                b['cases'] += 1
                d = differences(ref, got) if got else ['no result']
                if d:
                    b['bad'] += 1
                    mism.append({'kind': s['kind'], 'text': s['text'], 'code': s['m']['code'].hex(), 'case': line, 'fields': d, 'ref': ref, 'got': got})
            if progress:
                progress('group %d of %d' % (n + 1, len(groups)))
    return {'cases': total, 'by_kind': by_kind, 'mismatches': mism, 'crashed': crashed}


def summary(res):
    """Lines of text: a table of what differs, per kind and field, with one example each."""
    out = ['%d cases, %d programs, %d opcodes decode, %d opcodes with no valid state on Moira, %d mismatches'
           % (res['cases'], res['programs'], res['opcodes'], res['no_valid_state'], len(res['mismatches']))]
    seen = {}
    for m in res['mismatches']:
        key = (m['kind'], ','.join(m['fields']))
        seen.setdefault(key, []).append(m)
    for (kind, fields), ms in sorted(seen.items(), key=lambda kv: -len(kv[1])):
        e = ms[0]
        out.append('  %-8s %-24s %6d  e.g. %s [%s]' % (kind, fields, len(ms), e['text'], e['code']))
    for c in res['crashed']:
        out.append('  a batch ended early: ' + c)
    if res.get('refused'):
        out.append('legal on a 68000, refused by the decoder: ' + ', '.join('%s %d' % kv for kv in sorted(res['refused'].items(), key=lambda kv: -kv[1])))
    return out


def record(res, path, limit=4000, seed=7, work=None):
    """A sample of the sweep with Moira's results, run again for the sample's own images: one program per signature of the
    instruction first. Written as text; a G line starts a group that shares an image."""
    rng = random.Random(seed)
    by_name, by_sig = {}, {}
    for s in res['selected']:
        name = s['kind'] + ':' + s['text'].split(' ')[0]
        by_name.setdefault(name, []).append(s)
        by_sig.setdefault(name + ':' + _modes(s['text']), []).append(s)
    sample = [rng.choice(by_name[n]) for n in sorted(by_name)]           # every mnemonic first, then every addressing form
    forms = [rng.choice(v) for _, v in sorted(by_sig.items())]
    rng.shuffle(forms)
    rest = list(res['selected'])
    rng.shuffle(rest)
    chosen, out = set(), []
    for s in [x for x in res['selected'] if x.get('directed')] + sample + forms + rest:      # 1.0.40: the directed ones always
        if id(s) not in chosen:
            chosen.add(id(s))
            out.append(s)
    sample = out[:limit]
    groups = _groups(sorted(sample, key=lambda s: s['base']))
    n = 0
    with (gzip.open(path, 'wt') if str(path).endswith('.gz') else open(path, 'w')) as f:
        f.write('# 68000 semantics measured with Moira (vAmiga 899da5d, Dirk W. Hoffmann, MIT): arek difftest --record.\n'
                '# G starts a group sharing one image (difftest.pattern + its programs). P base code roots exits dyn self kind text.\n'
                '# C the case line | flags cycles pc sr d0-7 a0-7 memory\n')
        for g in groups:
            _reference(res['exe'], g, work)
            f.write('G\n')
            for s in g:
                if not s['cases']:
                    continue
                n += 1
                m = s['m']
                f.write('P %x %s %s %s %s %x %s %s\n' % (s['base'], m['code'].hex(), ','.join('%x' % x for x in m['roots']),
                                                         ','.join('%x' % x for x in m['exits']), ','.join('%x' % x for x in m['dyn']) or '-', m['self'],
                                                         s['kind'], s['text']))
                for line, ref in s['cases']:
                    f.write('C %s | %s\n' % (line, _row(ref)))
    return n


def _modes(text):
    """The addressing modes in an instruction's text, with the registers and numbers out."""
    t = text.partition(' ')[2]
    out, num = [], False
    for ch in t:
        if ch.isdigit() or ch in 'abcdef$-':
            if not num:
                out.append('#')
                num = True
            continue
        num = False
        out.append(ch)
    return ''.join(out)


def _row(r):
    return '%x %x %x %x %s %s %s' % (r['flags'], r['cycles'], r['pc'], r['sr'], ' '.join('%x' % v for v in r['d']), ' '.join('%x' % v for v in r['a']), r['mem'])


def load_corpus(path):
    groups, cur = [], None
    for line in (gzip.open(path, 'rt') if str(path).endswith('.gz') else open(path)):
        if line.startswith('G'):
            groups.append([])
        elif line.startswith('P '):
            t = line.rstrip('\n').split(' ', 8)
            base, code = int(t[1], 16), bytes.fromhex(t[2])
            cur = {'kind': t[7], 'text': t[8], 'base': base, 'cases': [],
                   'm': {'code': code, 'entry': base, 'roots': [int(x, 16) for x in t[3].split(',')], 'exits': [int(x, 16) for x in t[4].split(',')],
                         'dyn': [] if t[5] == '-' else [int(x, 16) for x in t[5].split(',')], 'self': int(t[6], 16)}}
            groups[-1].append(cur)
        elif line.startswith('C '):
            c, _, r = line[2:].rstrip('\n').partition(' | ')
            cur['cases'].append((c, parse_result(r)))
    return groups


def check_corpus(path, work, jobs=None):
    """The recorded cases through the translation: no Moira needed. The same result dict as ``sweep``."""
    groups = load_corpus(path)
    res = _compare_groups(groups, jobs, None, work)
    res.update(programs=sum(len(g) for g in groups), opcodes=0, no_valid_state=0)
    return res


def collect_patterns(moira, build_dir, work, seed=3, progress=None):
    """Moira's bus pattern of every instruction the decoder reads (1.0.55, ``buspat.build`` makes the table of it):
    {key: [{'code', 'kind', 'text', 'runs': [(bus, poll, cycles)]}]}. Two passes: random extension words, then for the
    shapes still without a pattern fixed ones that keep every absolute address inside the RAM."""
    from . import buspat
    exe = build_harness(moira, build_dir)
    rng = random.Random(seed)
    res = {}

    def run(rows):
        for i in range(0, len(rows), 4000):
            for op, ok, why in _validate(exe, rows[i:i + 4000], 6, work):
                if ok:
                    info = ok[1]
                    res.setdefault(str(op), []).append({'code': info['m']['code'].hex(), 'kind': info['kind'], 'text': info['text'],
                                                        'runs': sorted({(r['bus'], r['poll'], r['cycles']) for _, r in info['cases']})})
            if progress:
                progress('%d programs' % min(i + 4000, len(rows)))
    rows = []
    for op in range(0x10000):
        for c in opcode_programs(rng, op, 2)[:2]:
            rows.append((op, plain_program(c, rng, nstates=6)))
    rows += [(('ctl', k), p) for k, p in enumerate(control_programs(rng))]
    run(rows)
    table, _ = buspat.build(res, decode)
    buspat._TABLE = table
    rows = []
    safe = be16(0x0001) + be16(0x2340) + be16(0x0001) + be16(0x2350) + be16(0x0001)
    even = be16(0x0002) + be16(0x2340) + be16(0x0002) + be16(0x2350) + be16(0x0002)
    low = be16(0x2340) + be16(0x2350) + be16(0x0002) + be16(0x2360) + be16(0x0002)
    for op in range(0x10000):
        # absolute long / absolute short and PC-relative / two short addresses / a movem list of two before an address
        # ... / a short address before a long one (move $2340.w,$2350.l)
        for ext in (safe, even, low, be16(0x0003) + be16(0x2340) + safe, be16(0x0003) + safe, be16(0x2340) + be16(0) + be16(0x2350) + even):
            try:
                ins = decode(be16(op) + ext, 0x8000, 0x8000)
            except (Unsupported, IndexError, ValueError):
                continue
            if ins.kind in CONTROL or buspat.variants(ins) is not None:
                continue
            rows.append((('safe', op), plain_program((be16(op) + ext)[:ins.end - ins.addr], rng, nstates=6)))
    run(rows)
    buspat._TABLE = None
    return res


def main(a):
    """arek difftest."""
    work = a.work or tempfile.mkdtemp(prefix='arek-difftest-')
    Path(work).mkdir(parents=True, exist_ok=True)
    if getattr(a, 'bus_patterns', None):
        from . import buspat
        if not a.moira:
            raise SystemExit('difftest --bus-patterns: --moira DIR (the vAmiga source or its Moira folder)')
        got = collect_patterns(a.moira, Path(work) / 'moira', work, progress=(lambda s: print(s, flush=True)) if a.verbose else None)
        table, problems = buspat.build(got, decode)
        Path(a.bus_patterns).write_text(json.dumps(table, separators=(',', ':'), sort_keys=True) + '\n')
        print('%d shapes, %d movem shapes in %s; %d without a pattern' % (len(table['shapes']), len(table['movem']), a.bus_patterns, len(problems)))
        for q in problems[:40] if a.verbose else ():
            print('  ', q[0], q[1])
        return 0
    if a.corpus:
        res = check_corpus(a.corpus, work, a.jobs)
    else:
        if not a.moira:
            raise SystemExit('difftest: --moira DIR (the vAmiga source or its Moira folder), or --corpus FILE')
        res = sweep(a.moira, Path(work) / 'moira', seed=a.seed, per_opcode=a.states, kinds=set(a.kind) if a.kind else None, jobs=a.jobs,
                    progress=(lambda s: print(s, flush=True)) if a.verbose else None, work=work)
        if a.record:
            print('recorded %d programs in %s' % (record(res, a.record, a.record_limit, work=work), a.record))
    print('\n'.join(summary(res)))
    if a.json:
        Path(a.json).write_text(json.dumps({k: v for k, v in res.items() if k not in ('selected', 'exe')}, indent=1) + '\n')
    return 1 if res['mismatches'] or res['crashed'] else 0
