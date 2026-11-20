"""Static roots for a whole-game translation: entry points the walker cannot see because the
program reaches them through tables and stored addresses (from the Alien Breed II project,
which needed 1 929 of them for 17 levels):

- ``slots``: tables of ``bra.w`` slots (a jump table of 4-byte branches, ``jsr (table,pc,d0)``);
- ``ptr``: longwords in the image that point at the start of an instruction of the code range
  (pointer tables, object records with handler addresses);
- ``lea``: the target of ``lea``/``pea`` when a slot table starts there (the table's base), or any decodable
  target (1.0.12: a routine whose address is passed in a register);
- ``imm``: ``move.l #addr,...`` with a code address (a handler stored into a structure at run time,
  which the walker never sees - KIT-GAPS G30 of Alien Breed II);
- ``ofs`` (1.0.86, SWIV): tables of 16-bit offsets that the code adds to a base, found from the code that reads
  them - ``lea BASE,An`` followed by ``adda.w Dx,An`` (once: offset * 1, twice: * 2; an ``add.w Dx,Dx`` / ``lsl.w #n,Dx``
  just before the ``lea`` doubles it) with a ``lea TABLE`` / ``pea TABLE`` up to 64 bytes before (entries of 2 or 4 bytes,
  the offset in either word: the longest run wins), or ``move.w (TABLE,pc,Dx),Dx`` + ``jmp`` / ``jsr (TABLE,pc,Dx)`` (a
  relative jump table: offsets from the table). A run ends at an offset 0 or at a target that is no instruction start
  of the linear decode; it counts from ``min_ofs`` (4) entries. SWIV's behaviour table ($16422, base $16564: 73
  coroutines, 12 of them reached only at the end of the game) is one.

- 1.0.99 (Turrican II, boss 3-2: ``unknown routine 265b0``): a root that is an entry of a run of ``bra.w`` slots shorter
  than ``min_slots`` brings the whole run (``min_table`` entries, default 3 - a pair of ``6000 xxxx`` also occurs in
  data). The boss's state machine jumps into a table of three ``bra.w`` at a computed address; ``lea`` found the table's
  first entry, the other two were missing and the game stopped in that fight. :func:`slot_table` gives the run of an
  address (a root known from a run - ``arek discover`` - needs only 2).

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


KINDS = ('slots', 'ptr', 'lea', 'imm', 'ofs')


def slot_table(data, base, a, lo=None, hi=None):
    """1.0.99: the run of ``bra.w`` slots that address ``a`` is an entry of - ``[start, start + 4, ...]``, [] when a holds
    no ``bra.w``. The run is followed back from a in steps of 4 and forward to its end."""
    lo = base if lo is None else lo
    hi = base + len(data) if hi is None else min(hi, base + len(data))
    if not lo <= a < hi or _word(data, base, a) != 0x6000:
        return []
    s = a
    while s - 4 >= lo and _word(data, base, s - 4) == 0x6000:
        s -= 4
    return [s + 4 * k for k in range(_slot_run(data, base, s, hi))]


def scan(data, base, lo=None, hi=None, min_slots=4, min_run=1, kinds=KINDS, min_ofs=4, min_table=3):
    """``{address: set(kinds)}`` of the static roots in [lo, hi) (default: the whole image)."""
    lo = base if lo is None else lo
    hi = base + len(data) if hi is None else min(hi, base + len(data))
    ins = instructions(data, base, lo, hi)
    starts = set(ins)
    roots = {}
    _code = {}

    def code_at(v):
        """1.0.12 (Turrican II KIT-GAPS 17): an instruction decodes at v - the linear sweep can be out of step there
        (data before a routine), so membership in its starts alone missed real routines (a module header's pointer)."""
        if v in starts:
            return True
        if v & 1 or not lo <= v < hi:
            return False
        if v not in _code:
            try:
                decoder.decode(data, base, v); _code[v] = True
            except Exception:
                _code[v] = False
        return _code[v]

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
        # every start position counts (1.0.14, Turrican II KIT-GAPS 22: a run read at a stride of 4 from the word before
        # a pointer jumped over the next aligned one); a position already read inside a run is not started again, so a
        # long block of equal values stays linear
        done = set()
        p = lo
        while p + 4 <= hi:
            if p in done:
                p += 2
                continue
            run = []
            q = p
            while q + 4 <= hi:
                v = struct.unpack('>I', data[q - base:q - base + 4])[0] & 0xffffff
                if not lo <= v < hi or not code_at(v):
                    break
                run.append(v)
                done.add(q)
                q += 4
            if len(run) >= min_run:
                for v in run:
                    add(v, 'ptr')
            p += 2
    for a, i in ins.items():
        if 'lea' in kinds and i.kind in ('lea', 'pea'):
            t = getattr(i.ea, 'absval', None)
            if t is not None and lo <= t < hi and _slot_run(data, base, t, hi) >= min_slots:
                for k in range(_slot_run(data, base, t, hi)):
                    add(t + 4 * k, 'lea')
            elif t is not None and code_at(t):
                add(t, 'lea')                    # 1.0.12: lea/pea of a routine (a handler passed in a register)
        if 'imm' in kinds and i.kind == 'move' and getattr(i, 'sz', None) == decoder.SZ_L:
            src = getattr(i, 'src', None)
            if src is not None and src.kind == 'imm':
                v = src.imm & 0xffffff
                if lo <= v < hi and v != i.addr and code_at(v):
                    add(v, 'imm')
    if 'ofs' in kinds:
        for t in offset_tables(data, base, lo, hi, ins, min_ofs):
            for v in t['targets']:
                add(v, 'ofs')
    if 'slots' in kinds and min_table:                   # 1.0.99: a root inside a short run of bra.w slots brings the run
        for a in list(roots):
            run = slot_table(data, base, a, lo, hi)
            if len(run) >= min_table:
                for t in run:
                    if t != a:
                        add(t, 'slots')
    return roots


def _sword(data, base, a):
    w = _word(data, base, a)
    return None if w is None else w - 0x10000 if w & 0x8000 else w


def _run(data, base, lo, hi, starts, table, at, stride, scale, field):
    """The targets of the offset table's entries in a row: base ``at`` + offset * scale, until an offset 0 or a target
    that is no instruction start."""
    out, p = [], table + field
    while p + 2 <= hi:
        o = _sword(data, base, p)
        if not o:
            break
        t = at + o * scale
        if t & 1 or not lo <= t < hi or t not in starts:
            break
        out.append(t)
        p += stride
    return out


def offset_tables(data, base, lo, hi, ins=None, min_ofs=4):
    """The offset tables the code reads (kind ``ofs`` of :func:`scan`): a list of ``{table, base, stride, field, scale,
    site, targets}``, ``site`` the instruction that adds the offset (the ``adda`` or the ``jmp`` / ``jsr``)."""
    ins = instructions(data, base, lo, hi) if ins is None else ins
    starts, order = set(ins), sorted(ins)
    pos = {a: k for k, a in enumerate(order)}
    out, seen = [], set()

    def target(i):
        return getattr(getattr(i, 'ea', None), 'absval', None)

    def best(table, at, scales, site, strides=(2, 4)):
        top = None
        for stride in strides:
            for field in range(0, stride, 2):
                for scale in scales:
                    r = _run(data, base, lo, hi, starts, table, at, stride, scale, field)
                    if len(r) >= min_ofs and (top is None or len(r) > len(top['targets'])):
                        top = {'table': table, 'base': at, 'stride': stride, 'field': field, 'scale': scale, 'site': site, 'targets': r}
        if top and (top['table'], top['base'], top['field']) not in seen:
            seen.add((top['table'], top['base'], top['field']))
            out.append(top)

    for k, a in enumerate(order):
        i = ins[a]
        if i.kind == 'lea' and target(i) is not None:            # lea BASE,An ; adda.w Dx,An [; adda.w Dx,An]
            at, an, n, dx, site = target(i), getattr(i, 'an', None), 0, None, None
            for b in order[k + 1:k + 4]:
                j = ins[b]
                if j.kind == 'adda' and getattr(j, 'sz', None) == decoder.SZ_W and getattr(j, 'an', None) == an and j.ea.kind == 'd' and dx in (None, j.ea.reg):
                    dx, n, site = j.ea.reg, n + 1, site or b
                elif n:
                    break
            if not n or not lo <= at < hi:
                continue
            mul = 1
            for b in order[max(0, k - 2):k]:                     # add.w Dx,Dx / lsl.w #s,Dx just before the lea
                j = ins[b]
                if j.kind == 'alu' and getattr(j, 'name', None) == 'add' and j.sz == decoder.SZ_W and j.reg == dx and j.ea.kind == 'd' and j.ea.reg == dx:
                    mul *= 2
                elif j.kind == 'shift' and getattr(j, 'name', None) in ('lsl', 'asl') and j.sz == decoder.SZ_W and j.reg == dx and str(j.cnt).isdigit():
                    mul <<= int(j.cnt)
            scales = sorted({n * mul, n})
            tables = []
            for b in order[max(0, k - 24):k]:                    # lea / pea TABLE up to 64 bytes before
                j = ins[b]
                if j.kind in ('lea', 'pea') and a - b <= 64 and target(j) is not None and target(j) != at and lo <= target(j) < hi:
                    tables.append(target(j))
            for table in tables:
                best(table, at, scales, site)
        elif i.kind in ('jmp', 'jsr') and getattr(i.ea, 'mode', None) == 73 and getattr(i.ea, 'pcbase', None) is not None:
            tb = i.ea.pcbase                                     # move.w (T,pc,Dx),Dx ; jmp (T,pc,Dx)
            for b in order[max(0, k - 3):k]:
                j = ins[b]
                src = getattr(j, 'src', None)
                if j.kind == 'move' and getattr(j, 'sz', None) == decoder.SZ_W and getattr(src, 'mode', None) == 73 and getattr(src, 'pcbase', None) == tb:
                    best(tb, tb, (1,), a, strides=(2,))
                    break
    return out


def format_roots(roots):
    return '\n'.join('%06x %s' % (a, ','.join(sorted(k))) for a, k in sorted(roots.items()))
