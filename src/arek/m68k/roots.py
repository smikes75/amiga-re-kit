"""Static roots for a whole-game translation: entry points the walker cannot see because the
program reaches them through tables and stored addresses (from the Alien Breed II project,
which needed 1 929 of them for 17 levels):

- ``slots``: tables of ``bra.w`` slots (a jump table of 4-byte branches, ``jsr (table,pc,d0)``);
- ``ptr``: longwords in the image that point at the start of an instruction of the code range
  (pointer tables, object records with handler addresses);
- ``lea``: the target of ``lea``/``pea`` when a slot table starts there (the table's base);
- ``imm``: ``move.l #addr,...`` with a code address (a handler stored into a structure at run time,
  which the walker never sees - KIT-GAPS G30 of Alien Breed II).

A root that leads into data is harmless with ``arek recomp --auto-soft`` (it is dropped with a
warning), so the scan can be generous.

    arek roots image.bin --base 0 --lo 0xc00fa0 --hi 0xc58a8c [--min-slots 4] [--json out.json]
"""
import struct

from . import decoder


def instructions(data, base, lo, hi):
    """Linear decode of [lo, hi): ``{addr: Insn}`` for every decodable instruction start (undecodable
    words are skipped two bytes at a time, as ``arek dis`` does)."""
    out, addr, end = {}, lo, min(hi, base + len(data))
    while addr < end:
        try:
            i = decoder.decode(data, base, addr)
        except Exception:
            addr += 2
            continue
        out[addr] = i
        addr = i.end
    return out


def _word(data, base, a):
    o = a - base
    return struct.unpack('>H', data[o:o + 2])[0] if 0 <= o and o + 2 <= len(data) else None


def _slot_run(data, base, a, hi):
    """Length of the run of ``bra.w`` slots (opcode $6000, 4 bytes each) starting at a."""
    n = 0
    while a + 4 <= hi and _word(data, base, a) == 0x6000:
        n += 1
        a += 4
    return n


def scan(data, base, lo=None, hi=None, min_slots=4, min_run=1, kinds=('slots', 'ptr', 'lea', 'imm')):
    """``{address: set(kinds)}`` of the static roots in [lo, hi) (default: the whole image)."""
    lo = base if lo is None else lo
    hi = base + len(data) if hi is None else min(hi, base + len(data))
    ins = instructions(data, base, lo, hi)
    starts = set(ins)
    roots = {}

    def add(a, kind):
        roots.setdefault(a, set()).add(kind)

    if 'slots' in kinds:
        a = lo
        while a + 4 <= hi:
            n = _slot_run(data, base, a, hi)
            if n >= min_slots:
                for k in range(n):
                    add(a + 4 * k, 'slots')
                a += 4 * n
            else:
                a += 2
    if 'ptr' in kinds:
        p = lo
        while p + 4 <= hi:
            run = []
            q = p
            while q + 4 <= hi:
                v = struct.unpack('>I', data[q - base:q - base + 4])[0] & 0xffffff
                if v not in starts or not lo <= v < hi:
                    break
                run.append(v)
                q += 4
            if len(run) >= min_run:
                for v in run:
                    add(v, 'ptr')
                p = q
            else:
                p += 2
    for a, i in ins.items():
        if 'lea' in kinds and i.kind in ('lea', 'pea'):
            t = getattr(i.ea, 'absval', None)
            if t is not None and lo <= t < hi and _slot_run(data, base, t, hi) >= min_slots:
                for k in range(_slot_run(data, base, t, hi)):
                    add(t + 4 * k, 'lea')
        if 'imm' in kinds and i.kind == 'move' and getattr(i, 'sz', None) == decoder.SZ_L:
            src = getattr(i, 'src', None)
            if src is not None and src.kind == 'imm':
                v = src.imm & 0xffffff
                if v in starts and lo <= v < hi and v != i.addr:
                    add(v, 'imm')
    return roots


def format_roots(roots):
    return '\n'.join('%06x %s' % (a, ','.join(sorted(k))) for a, k in sorted(roots.items()))
