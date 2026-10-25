"""Instruction times of the MC68000 in clock cycles (no wait states).

From the tables of the MC68000 User's Manual (section 8), checked instruction by
instruction against Moira (Dirk W. Hoffmann, MIT), the CPU core of vAmiga. A
memory access is 4 clocks; on an Amiga the CPU can be delayed further by DMA,
which is outside this module.

    cycles(insn, taken=True, src=None, dst=None, count=None, dbcc='loop')

``insn`` is a decoder.Insn. Some times depend on data; pass what is known:

    taken   Bcc: branch taken; Scc: condition true
    dbcc    'loop' (branch back, 10), 'expired' (counter ran out, 14), 'cc' (condition true, 12)
    src     MULU/MULS/DIVU/DIVS: the 16-bit source operand
    dst     DIVU/DIVS: the 32-bit dividend
    count   shifts with the count in a register: the count; bit operations on Dn: the bit number

Without the data the worst case is returned: MUL 70, DIVU 140, DIVS 158, a register shift
by 63, bit operations on bits 16-31. ``exact(insn)`` tells whether the time is fixed.
"""
from .decoder import SZ_L, Unsupported

# effective address calculation: (byte/word, long)
_EA = {'dn': (0, 0), 'an': (0, 0), 'ind': (4, 8), 'post': (4, 8), 'pre': (6, 10),
       'd16': (8, 12), 'd8x': (10, 14), 'absw': (8, 12), 'absl': (12, 16),
       'pcd16': (8, 12), 'pcd8x': (10, 14), 'imm': (4, 8)}
# MOVE destination
_DST = {'dn': (0, 0), 'an': (0, 0), 'ind': (4, 8), 'post': (4, 8), 'pre': (4, 8),
        'd16': (8, 12), 'd8x': (10, 14), 'absw': (8, 12), 'absl': (12, 16)}
# control addressing: (An), d16(An), d8(An,Xn), abs.W, abs.L, d16(PC), d8(PC,Xn)
_CTL = {'jmp': (8, 10, 14, 10, 12, 10, 14), 'jsr': (16, 18, 22, 18, 20, 18, 22),
        'lea': (4, 8, 12, 8, 12, 8, 12), 'pea': (12, 16, 20, 16, 20, 16, 20)}
_CTL_IX = {'ind': 0, 'd16': 1, 'd8x': 2, 'absw': 3, 'absl': 4, 'pcd16': 5, 'pcd8x': 6}
# MOVEM base by addressing class: memory to registers / registers to memory
_MOVEM_M2R = {'ind': 12, 'post': 12, 'd16': 16, 'd8x': 18, 'absw': 16, 'absl': 20, 'pcd16': 16, 'pcd8x': 18}
_MOVEM_R2M = {'ind': 8, 'pre': 8, 'd16': 12, 'd8x': 14, 'absw': 12, 'absl': 16}
_FIXED = {'nop': 4, 'rts': 16, 'rte': 20, 'link': 16, 'unlk': 12, 'exg': 6, 'ext': 4,
          'swap': 4, 'moveq': 4, 'bra': 10, 'bsr': 18}


def ea_class(e):
    """The addressing class of a decoder EA."""
    if e.kind == 'd':
        return 'dn'
    if e.kind == 'a':
        return 'an'
    if e.kind == 'imm':
        return 'imm'
    m = getattr(e, 'mode', None)
    named = {2: 'ind', 5: 'd16', 6: 'd8x', 70: 'absw', 71: 'absl', 72: 'pcd16', 73: 'pcd8x'}
    if m in named:
        return named[m]
    if e.text.startswith('-('):
        return 'pre'
    if e.text.endswith(')+'):
        return 'post'
    raise Unsupported('timing: unknown operand %s' % e.text)


def ea_time(e, long=False):
    return _EA[ea_class(e)][1 if long else 0]


def _mulu(src):
    return 38 + 2 * bin(src & 0xffff).count('1')


def _muls(src):
    v = (src & 0xffff) << 1
    return 38 + 2 * sum(1 for i in range(16) if ((v >> i) & 1) != ((v >> (i + 1)) & 1))


# DIVU/DIVS follow Jorge Cwik's analysis of the 68000 division microcode, in the form of
# Moira's cyclesDiv (MIT): mcycles count the microcode loop, one bus cycle = 2 clocks.
def _divu(dividend, divisor):
    dividend &= 0xffffffff
    divisor &= 0xffff
    if divisor == 0:
        raise ValueError('division by zero is a trap, not an instruction time')
    if (dividend >> 16) >= divisor:                  # quotient does not fit 16 bits
        return 10
    mcycles, hdivisor = 38, divisor << 16
    for _ in range(15):
        if dividend & 0x80000000:
            dividend = ((dividend << 1) - hdivisor) & 0xffffffff
        else:
            dividend = (dividend << 1) & 0xffffffff
            if dividend >= hdivisor:
                dividend -= hdivisor
                mcycles += 1
            else:
                mcycles += 2
    return 2 * mcycles


def _divs(dividend, divisor):
    dividend = dividend - (1 << 32) if dividend & 0x80000000 else dividend
    divisor = (divisor & 0xffff) - 0x10000 if divisor & 0x8000 else divisor & 0xffff
    if divisor == 0:
        raise ValueError('division by zero is a trap, not an instruction time')
    mcycles = 7 if dividend < 0 else 6
    if (abs(dividend) >> 16) >= abs(divisor):        # quotient does not fit 16 bits
        return (mcycles + 2) * 2
    mcycles += 55
    if divisor >= 0:
        mcycles += 1 if dividend < 0 else -1
    aquot = abs(dividend) // abs(divisor)
    for _ in range(15):
        if not aquot & 0x8000:
            mcycles += 1
        aquot = (aquot << 1) & 0xffff
    return 2 * mcycles


def exact(i):
    """True when the time of ``i`` does not depend on data or on a branch outcome."""
    k = i.kind
    if k in ('bcc', 'dbcc', 'scc', 'mulu', 'muls', 'divu', 'divs'):
        return False
    if k == 'shift' and not getattr(i, 'mem', False) and not i.cnt.isdigit():
        return False
    if k == 'bit' and i.bitop and ea_class(i.ea) == 'dn':
        return False
    return True


def cycles(i, taken=True, src=None, dst=None, count=None, dbcc='loop'):
    k = i.kind
    L = getattr(i, 'sz', None) == SZ_L
    if k in _FIXED:
        return _FIXED[k]
    if k == 'move':
        return 4 + ea_time(i.src, L) + _DST[ea_class(i.dst)][L]
    if k == 'alu':
        c = ea_class(i.ea)
        if i.name == 'cmp':
            return (6 if L else 4) + ea_time(i.ea, L)
        if i.to_ea:
            return (12 if L else 8) + ea_time(i.ea, L)
        if L:
            return (8 if c in ('dn', 'an', 'imm') else 6) + ea_time(i.ea, L)
        return 4 + ea_time(i.ea, L)
    if k == 'eor':
        if ea_class(i.ea) == 'dn':
            return 8 if L else 4
        return (12 if L else 8) + ea_time(i.ea, L)
    if k in ('adda', 'suba'):
        c = ea_class(i.ea)
        if L:
            return (8 if c in ('dn', 'an', 'imm') else 6) + ea_time(i.ea, L)
        return 8 + ea_time(i.ea, L)
    if k == 'cmpa':
        return 6 + ea_time(i.ea, L)
    if k == 'alui':
        c = ea_class(i.ea)
        if c == 'imm':                               # to CCR / SR
            return 20
        cmp = i.name == 'cmpi'
        if c == 'dn':
            return (14 if cmp else 16) if L else 8
        return ((12 if cmp else 20) if L else (8 if cmp else 12)) + ea_time(i.ea, L)
    if k == 'addq':
        c = ea_class(i.ea)
        if c == 'dn':
            return 8 if L else 4
        if c == 'an':
            return 8
        return (12 if L else 8) + ea_time(i.ea, L)
    if k in ('clr', 'neg', 'negx', 'not'):
        if ea_class(i.ea) == 'dn':
            return 6 if L else 4
        return (12 if L else 8) + ea_time(i.ea, L)
    if k == 'tst':
        return 4 + ea_time(i.ea, L)
    if k == 'scc':
        if ea_class(i.ea) == 'dn':
            return 6 if taken else 4
        return 8 + ea_time(i.ea)
    if k == 'bit':
        dyn = i.src.startswith('m->d[')
        if ea_class(i.ea) == 'dn':
            if i.bitop == 0:
                return 6 if dyn else 10
            high = count is None or (count & 31) >= 16
            base = (8 if i.bitop == 2 else 6) if dyn else (12 if i.bitop == 2 else 10)
            return base + (2 if high else 0)
        return (4 if dyn else 8) + (0 if i.bitop == 0 else 4) + ea_time(i.ea)
    if k == 'shift':
        if getattr(i, 'mem', False):
            return 8 + ea_time(i.ea)
        n = int(i.cnt) if i.cnt.isdigit() else (63 if count is None else count & 63)
        return (8 if L else 6) + 2 * n
    if k == 'bcc':
        if taken:
            return 10
        return 8 if i.end - i.addr == 2 else 12
    if k == 'dbcc':
        return {'loop': 10, 'expired': 14, 'cc': 12}[dbcc]
    if k in _CTL:
        return _CTL[k][_CTL_IX[ea_class(i.ea)]]
    if k == 'movem':
        c = ea_class(i.ea)
        n = bin(i.mask).count('1')
        base = (_MOVEM_R2M if i.to_mem else _MOVEM_M2R)[c]
        return base + (8 if L else 4) * n
    if k == 'sr':
        if i.which == 'from_sr':
            return 6 if ea_class(i.ea) == 'dn' else 8 + ea_time(i.ea)
        return 12 + ea_time(i.ea)
    if k == 'mulu':
        return (70 if src is None else _mulu(src)) + ea_time(i.ea)
    if k == 'muls':
        return (70 if src is None else _muls(src)) + ea_time(i.ea)
    if k == 'divu':
        return (140 if src is None or dst is None else _divu(dst, src)) + ea_time(i.ea)
    if k == 'divs':
        return (158 if src is None or dst is None else _divs(dst, src)) + ea_time(i.ea)
    if k == 'bcd':
        return 18 if i.mem else 6
    if k == 'addx':
        if i.mem:
            return 30 if L else 18
        return 8 if L else 4
    if k == 'cmpm':
        return 20 if L else 12
    raise Unsupported('timing: %s' % k)


# bus cycles of an effective address: (extension words + operand reads) for a word / a long operand
_EA_R = {'dn': (0, 0), 'an': (0, 0), 'ind': (1, 2), 'post': (1, 2), 'pre': (1, 2), 'd16': (2, 3), 'd8x': (2, 3),
         'absw': (2, 3), 'absl': (3, 4), 'pcd16': (2, 3), 'pcd8x': (2, 3), 'imm': (1, 2)}
_DST_X = {'dn': 0, 'an': 0, 'ind': 0, 'post': 0, 'pre': 0, 'd16': 1, 'd8x': 1, 'absw': 1, 'absl': 2}
# control addressing, (reads, writes): (An), d16(An), d8(An,Xn), abs.W, abs.L, d16(PC), d8(PC,Xn)
_CTL_RW = {'jmp': ((2, 0), (2, 0), (3, 0), (2, 0), (3, 0), (2, 0), (3, 0)),
           'jsr': ((2, 2), (2, 2), (2, 2), (2, 2), (3, 2), (2, 2), (2, 2)),
           'lea': ((1, 0), (2, 0), (2, 0), (2, 0), (3, 0), (2, 0), (2, 0)),
           'pea': ((1, 2), (2, 2), (2, 2), (2, 2), (3, 2), (2, 2), (2, 2))}
_MOVEM_R_M2R = {'ind': 3, 'post': 3, 'd16': 4, 'd8x': 4, 'absw': 4, 'absl': 5, 'pcd16': 4, 'pcd8x': 4}
_MOVEM_R_R2M = {'ind': 2, 'pre': 2, 'd16': 3, 'd8x': 3, 'absw': 3, 'absl': 4}
_FIXED_RW = {'nop': (1, 0), 'rts': (4, 0), 'rte': (5, 0), 'link': (2, 2), 'unlk': (3, 0), 'exg': (1, 0),
             'ext': (1, 0), 'swap': (1, 0), 'moveq': (1, 0), 'bra': (2, 0), 'bsr': (2, 2)}


def bus(i, taken=True, dbcc='loop'):
    """Bus cycles of ``i`` as ``(reads, writes)`` - the n(r/w) of the MC68000 User's Manual, the
    opcode and extension words included (each a read), 4 clocks each; the rest of
    ``cycles(i)`` is internal. What a model of the Amiga bus needs per instruction: how many
    slots the CPU takes, not only how long it runs."""
    k = i.kind
    L = getattr(i, 'sz', None) == SZ_L
    W = 2 if L else 1                                   # operand accesses of the size
    if k in _FIXED_RW:
        return _FIXED_RW[k]
    if k == 'move':
        d = ea_class(i.dst)
        return 1 + _EA_R[ea_class(i.src)][L] + _DST_X[d], 0 if d in ('dn', 'an') else W
    if k == 'alu':
        r = 1 + _EA_R[ea_class(i.ea)][L]
        return r, (W if i.to_ea and i.name != 'cmp' else 0)
    if k == 'eor':
        c = ea_class(i.ea)
        return (1, 0) if c == 'dn' else (1 + _EA_R[c][L], W)
    if k in ('adda', 'suba', 'cmpa', 'tst', 'mulu', 'muls', 'divu', 'divs'):
        return 1 + _EA_R[ea_class(i.ea)][L if k in ('adda', 'suba', 'cmpa', 'tst') else False], 0
    if k == 'alui':
        c = ea_class(i.ea)
        if c == 'imm':                                  # to CCR / SR
            return 3, 0
        imm = 2 if L else 1
        if c == 'dn':
            return 1 + imm, 0
        return 1 + imm + _EA_R[c][L], (0 if i.name == 'cmpi' else W)
    if k in ('addq', 'clr', 'neg', 'negx', 'not'):
        c = ea_class(i.ea)
        if c in ('dn', 'an'):
            return 1, 0
        return 1 + _EA_R[c][L], W
    if k == 'scc':
        c = ea_class(i.ea)
        return (1, 0) if c == 'dn' else (1 + _EA_R[c][0], 1)
    if k == 'bit':
        st = 0 if i.src.startswith('m->d[') else 1      # a static bit number is an extension word
        c = ea_class(i.ea)
        if c == 'dn':
            return 1 + st, 0
        return 1 + st + _EA_R[c][0], (0 if i.bitop == 0 else 1)
    if k == 'shift':
        if getattr(i, 'mem', False):
            return 1 + _EA_R[ea_class(i.ea)][0], 1
        return 1, 0
    if k == 'bcc':
        if taken:
            return 2, 0
        return (1, 0) if i.end - i.addr == 2 else (2, 0)
    if k == 'dbcc':
        return {'loop': (2, 0), 'expired': (3, 0), 'cc': (2, 0)}[dbcc]
    if k in _CTL_RW:
        return _CTL_RW[k][_CTL_IX[ea_class(i.ea)]]
    if k == 'movem':
        c = ea_class(i.ea)
        n = bin(i.mask).count('1') * W
        if i.to_mem:
            return _MOVEM_R_R2M[c], n
        return _MOVEM_R_M2R[c] + n, 0
    if k == 'sr':
        c = ea_class(i.ea)
        if i.which == 'from_sr':
            return (1, 0) if c == 'dn' else (1 + _EA_R[c][0], 1)
        return 1 + _EA_R[c][0], 0
    if k == 'bcd':
        return (3, 1) if i.mem else (1, 0)
    if k == 'addx':
        if i.mem:
            return (5, 2) if L else (3, 1)
        return 1, 0
    if k == 'cmpm':
        return (5, 0) if L else (3, 0)
    raise Unsupported('bus: %s' % k)


def _mem(e):
    return e is not None and not isinstance(e, str) and ea_class(e) not in ('dn', 'an', 'imm')


def performed(i):
    """Word accesses the kit's translation of ``i`` makes itself through rd/wr (operand reads
    and writes, stack pushes and pops) - the model is told about them as they happen."""
    k = i.kind
    L = getattr(i, 'sz', None) == SZ_L
    W = 2 if L else 1
    if k == 'move':
        return (W if _mem(i.src) else 0) + (W if _mem(i.dst) else 0)
    if k == 'alu':
        return (W + (W if i.to_ea and i.name != 'cmp' else 0)) if _mem(i.ea) else 0
    if k in ('eor', 'addq', 'neg', 'negx', 'not'):
        return 2 * W if _mem(i.ea) else 0
    if k in ('adda', 'suba', 'cmpa', 'tst'):
        return W if _mem(i.ea) else 0
    if k in ('mulu', 'muls', 'divu', 'divs'):
        return 1 if _mem(i.ea) else 0
    if k == 'alui':
        return 0 if not _mem(i.ea) else W + (0 if i.name == 'cmpi' else W)
    if k == 'clr':
        return W if _mem(i.ea) else 0                  # the 68000 reads before it writes; the translation only writes
    if k == 'scc':
        return 1 if _mem(i.ea) else 0
    if k == 'bit':
        return (1 + (0 if i.bitop == 0 else 1)) if _mem(i.ea) else 0
    if k == 'shift':
        return 2 if getattr(i, 'mem', False) else 0
    if k in ('jsr', 'bsr', 'pea', 'link', 'unlk'):
        return 2
    if k == 'rte':
        return 1                                       # the SR; the return address is not read
    if k == 'movem':
        return bin(i.mask).count('1') * W
    if k == 'sr':
        return 1 if _mem(i.ea) else 0
    if k == 'bcd':
        return 3 if i.mem else 0
    if k == 'addx':
        return 3 * W if i.mem else 0
    if k == 'cmpm':
        return 2 * W
    return 0                                           # rts (a7 += 4), branches, jmp, nop, exg, ext, swap, moveq


TAB_BCC_S, TAB_DBCC, TAB_PRE_ALL, TAB_PRE_2, TAB_PUSH2 = 1, 2, 4, 8, 16


def bus_table_entry(i):
    """``(words, extra, flags)`` for the runtime's bus table (``recomp --bus-table``): the
    instruction's words (each a prefetch read), the bus accesses the 68000 makes that the
    translation does not (prefetch after a jump, the stack of rts, the read before clr,
    movem's extra read ...), and flags the host resolves at run time from the clock count:
    TAB_BCC_S (a taken short branch reads one more word), TAB_DBCC (an expired loop too),
    TAB_PRE_ALL (a jump spends its internal cycles before its accesses), TAB_PRE_2 (-(An) and
    d8(An,Xn) wait 2 cycles before the operand), TAB_PUSH2 (jsr/bsr push two words after)."""
    k = i.kind
    words = (i.end - i.addr) // 2
    if k == 'bcc':
        r, w = bus(i, taken=False)
    elif k == 'dbcc':
        r, w = bus(i, dbcc='loop')
    else:
        r, w = bus(i)
    extra = max(0, r + w - words - performed(i))
    flags = 0
    if k == 'bcc' and words == 1:
        flags |= TAB_BCC_S
    if k == 'dbcc':
        flags |= TAB_DBCC
    if k in ('bcc', 'bra', 'dbcc', 'jmp', 'jsr', 'bsr'):
        flags |= TAB_PRE_ALL
    if k in ('jsr', 'bsr'):
        flags |= TAB_PUSH2
    if any(_mem(e) and ea_class(e) in ('pre', 'd8x', 'pcd8x') for e in (getattr(i, a, None) for a in ('ea', 'src', 'dst'))):
        flags |= TAB_PRE_2
    return words, extra, flags


def bus_pattern(i, **kw):
    """``{'words', 'reads', 'writes', 'cycles', 'internal'}`` of ``i``: its length in words, its
    bus cycles, its clocks (``cycles(i, **kw)``) and the clocks spent without the bus."""
    r, w = bus(i, taken=kw.get('taken', True), dbcc=kw.get('dbcc', 'loop'))
    c = cycles(i, **kw)
    return {'words': (i.end - i.addr) // 2, 'reads': r, 'writes': w, 'cycles': c, 'internal': c - 4 * (r + w)}


def describe(i):
    """Clock count of ``i`` for a listing: a number, or the cases when it depends on data."""
    k = i.kind
    if exact(i):
        return '%d' % cycles(i)
    if k == 'bcc':
        return '%d taken, %d not' % (cycles(i), cycles(i, taken=False))
    if k == 'dbcc':
        return '10 loop, 14 expired, 12 cc'
    if k == 'scc':
        return '6 true, 4 false'
    if k == 'shift':
        return '%d+2n' % cycles(i, count=0)
    if k == 'bit':
        if not i.src.startswith('m->d['):
            return '%d' % cycles(i, count=int(i.src.rstrip('u'), 16))
        return '%d/%d' % (cycles(i, count=0), cycles(i, count=16))
    if k in ('mulu', 'muls'):
        return '%d-%d' % (38 + ea_time(i.ea), cycles(i))
    return 'max %d' % cycles(i)                      # divu/divs
