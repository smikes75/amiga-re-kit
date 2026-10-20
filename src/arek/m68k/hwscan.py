"""Where in the game code the hardware boundary lies (from ``scan68k.py``).

Question answered: how many routines get by without touching the custom chips
($dff000), the CIAs ($bfxxxx) or ROM - i.e. how much of the code the static
recompiler can translate *without a chip model*.

Method: from the given roots the flow graph is walked (branches both ways,
``rts`` ends a path) so routine boundaries come from control flow, **not from
linear reading** - data stored between routines is never decoded as code.
For every instruction the addresses are classified: absolute ones by range,
``(An)`` / ``(d,An)`` by what the routine loaded into An (``lea abs``,
``movea.l #imm``), by a global convention (``abase``, e.g. ``{6: 0xdff000}``),
by pointers looked up in a real chip-RAM dump, or by measured entry
registers. Ambiguous = unknown base, reported as such.

Everything game-specific (code range, roots, per-frame routines) is a
parameter; the Turrican II values live in that project's wrapper.
"""
import collections

from . import decoder


CHIP_MAX = 0x200000                    # largest chip RAM an OCS/ECS Agnus addresses


def classify_addr(a, chip=CHIP_MAX):
    """``chip`` = chip RAM size of the machine; an address between it and
    2 MB is not RAM on that machine and counts as 'other'."""
    a &= 0xffffff
    if a < chip:
        return 'ram'                       # chip RAM
    if a < CHIP_MAX:
        return 'other'                     # chip address space, no RAM there
    if 0xc00000 <= a < 0xd80000:
        return 'ram'                       # slow RAM
    if 0xdf0000 <= a <= 0xdfffff:
        return 'custom'                    # Agnus/Denise/Paula
    if 0xbf0000 <= a <= 0xbfffff:
        return 'cia'
    if a >= 0xf00000:
        return 'rom'
    return 'other'


def eas(ins):
    for name in ('ea', 'src', 'dst'):
        e = getattr(ins, name, None)
        if e is not None and getattr(e, 'mode', None) is not None:
            yield e


class Routine:
    def __init__(self, start):
        self.start = start
        self.ins = {}
        self.calls = set()
        self.indirect = []       # (adresa, druh)
        self.bad = []            # nedekodovatelna slova
        self.abs_hw = collections.Counter()
        self.areg_hw = collections.Counter()
        self.unknown_base = collections.Counter()

    def local_ok(self):
        return not (self.abs_hw or self.areg_hw or self.indirect or self.bad)

    def summary(self):
        return {
            'start': self.start, 'instructions': len(self.ins),
            'calls': sorted(self.calls), 'indirect': self.indirect, 'bad': self.bad,
            'abs_hw': dict(self.abs_hw), 'areg_hw': dict(self.areg_hw),
            'unknown_base': dict(self.unknown_base), 'local_ok': self.local_ok(),
        }


def body(data, base, start, lo, hi):
    """Instructions reachable from ``start`` (branches both ways, rts ends a path)."""
    out, seen, work = [], set(), [start]
    while work:
        a = work.pop()
        if a in seen or not (lo <= a < hi):
            continue
        seen.add(a)
        try:
            i = decoder.decode(data, base, a)
        except decoder.Unsupported:
            continue
        out.append(i)
        work.extend(decoder.successors(i))
    return out


def resolve_bases(ins, abase, ram):
    """What can be in the address registers. Besides ``lea abs`` and
    ``movea.l #imm``, pointers loaded from memory are looked up **in a real
    chip-RAM dump** from a game run (measured, not guessed); ambiguous = unknown."""
    consts = dict(abase)
    bad = set()

    def rd32(a):
        return int.from_bytes(ram[a:a + 4], 'big') & 0xffffff if ram and a + 4 <= len(ram) else None

    for _ in range(3):                            # fixpoint pres poradi zapisu
        for i in ins:
            tgt, val = None, None
            if i.kind == 'lea':
                tgt = i.an
                if i.ea.mode in (70, 71):
                    val = i.ea.absval
                elif i.ea.mode == 5 and consts.get(i.ea.areg) is not None:
                    val = (consts[i.ea.areg] + i.ea.disp) & 0xffffff
            elif i.kind == 'move' and getattr(i, 'movea', False) and i.sz == 2:
                tgt = i.dst.reg
                if i.src.kind == 'imm':
                    val = i.src.imm & 0xffffff
                elif i.src.kind == 'a':
                    val = consts.get(i.src.reg)
                elif i.src.mode in (70, 71) and i.src.absval < 0x200000:
                    val = rd32(i.src.absval)
                elif i.src.mode in (2, 5) and consts.get(i.src.areg) is not None:
                    p = (consts[i.src.areg] + (i.src.disp or 0)) & 0xffffff
                    val = rd32(p) if p < 0x200000 else None
            elif i.kind in ('adda', 'suba') and getattr(i, 'an', None) is not None:
                tgt, val = i.an, None
            elif i.kind == 'addq' and i.ea.kind == 'a':
                tgt, val = i.ea.reg, None
            elif i.kind == 'movem' and not i.to_mem:
                for bit in range(8, 16):
                    if (i.mask >> bit) & 1:
                        bad.add(bit - 8)
            if tgt is None:
                continue
            if val is None:
                bad.add(tgt)
            elif consts.get(tgt) not in (None, val):
                bad.add(tgt)                      # dve ruzne baze -> neznama
            else:
                consts[tgt] = val
    for b in bad:
        consts.pop(b, None)
    return consts


def scan_routine(data, base, start, lo, hi, abase, ram=None, chip=CHIP_MAX):
    """``abase`` = global convention for address registers, e.g. ``{6: 0xdff000}``."""
    r = Routine(start)
    consts = resolve_bases(body(data, base, start, lo, hi), abase, ram)
    seen, work = set(), [start]
    while work:
        a = work.pop()
        if a in seen:
            continue
        if not (lo <= a < hi):
            r.indirect.append((a, 'outside code range'))
            continue
        seen.add(a)
        try:
            i = decoder.decode(data, base, a)
        except decoder.Unsupported as e:
            r.bad.append((a, str(e).split(' @')[0]))
            continue
        r.ins[a] = i
        for e in eas(i):
            if e.mode in (70, 71):
                k = classify_addr(e.absval, chip)
                if k != 'ram':
                    r.abs_hw[k] += 1
            elif e.mode in (2, 5, 6):
                v = consts.get(e.areg)
                if v is None:
                    r.unknown_base[e.areg] += 1
                else:
                    k = classify_addr(v + (e.disp or 0), chip)
                    if k != 'ram':
                        r.areg_hw[k] += 1
        if i.kind == 'bsr':
            r.calls.add(i.target)
        elif i.kind == 'jsr':
            if i.ea.mode in (70, 71):
                r.calls.add(i.ea.absval)
            else:
                r.indirect.append((a, 'jsr ' + i.ea.text))
        elif i.kind == 'jmp' and i.ea.mode not in (70, 71):
            r.indirect.append((a, 'jmp ' + i.ea.text))
        work.extend(decoder.successors(i))
    return r


def measured_bases(entry, addr, abase):
    """Measured address-register values at routine entry (``entryregs`` JSON:
    ``{"hex addr": {pass: {"a": [...]}}}``). Only registers that had the same
    value in every measured pass are trusted."""
    rec = (entry or {}).get('%x' % addr)
    if not rec:
        return dict(abase)
    out = dict(abase)
    vals = list(rec.values())
    for i in range(8):
        v = {p['a'][i] for p in vals}
        if len(v) == 1:
            out.setdefault(i, v.pop() & 0xffffff)
    return out


def scan(data, base, roots, lo, hi, abase=None, ram=None, entry=None, chip=CHIP_MAX):
    """Return {start: Routine} for everything reachable from ``roots``."""
    abase = abase or {}
    routines, work = {}, list(roots)
    while work:
        s = work.pop()
        if s in routines or not (lo <= s < hi):
            continue
        r = scan_routine(data, base, s, lo, hi, measured_bases(entry, s, abase), ram, chip)
        routines[s] = r
        work.extend(r.calls)
    return routines


def closure(routines):
    """A routine is 'translatable' only if neither it nor anything it calls
    touches hardware, jumps indirectly or contains an undecodable word."""
    ok = {a: r.local_ok() for a, r in routines.items()}
    changed = True
    while changed:
        changed = False
        for a, r in routines.items():
            if not ok[a]:
                continue
            for c in r.calls:
                if c not in routines or not ok[c]:
                    ok[a] = False
                    changed = True
                    break
    return ok


def report(routines, ok, per_frame=()):
    """Plain-dict report (JSON friendly)."""
    hw = [x for x, r in routines.items() if r.abs_hw or r.areg_hw]
    ind = [x for x, r in routines.items() if r.indirect]
    bad = [x for x, r in routines.items() if r.bad]
    unk = [x for x, r in routines.items() if r.unknown_base]
    total_ins = sum(len(r.ins) for r in routines.values())
    ins_ok = sum(len(routines[x].ins) for x, v in ok.items() if v)
    kinds = collections.Counter()
    for r in routines.values():
        kinds.update(r.abs_hw)
        kinds.update(r.areg_hw)
    hw_ins = sum(len(routines[x].ins) for x in hw)
    pf = []
    for t in per_frame:
        r = routines.get(t)
        if not r:
            pf.append({'addr': t, 'found': False})
            continue
        cust = r.abs_hw['custom'] + r.areg_hw['custom'] + r.abs_hw['cia'] + r.areg_hw['cia']
        tag = 'RAM' if ok[t] else ('hardware' if cust else ('indirect' if r.indirect else 'calls hw'))
        pf.append({'addr': t, 'found': True, 'instructions': len(r.ins), 'tag': tag,
                   'calls': len(r.calls), 'hw_accesses': cust,
                   'unknown_base': bool(r.unknown_base)})
    return {
        'routines': len(routines), 'instructions': total_ins,
        'pure_ram_local': sum(1 for r in routines.values() if r.local_ok()),
        'pure_ram_certain': sum(1 for r in routines.values() if r.local_ok() and not r.unknown_base),
        'touch_hw': len(hw), 'touch_hw_abs': sum(1 for x in hw if routines[x].abs_hw),
        'touch_hw_areg': sum(1 for x in hw if routines[x].areg_hw),
        'indirect': len(ind), 'undecodable': len(bad), 'unknown_base': len(unk),
        'translatable_transitive': sum(1 for v in ok.values() if v),
        'translatable_instructions': ins_ok,
        'translatable_pct': round(100.0 * ins_ok / max(total_ins, 1), 1),
        'non_ram_access_kinds': dict(kinds),
        'hw_routines_instructions': hw_ins,
        'largest_hw_routines': [{'addr': x, 'instructions': len(routines[x].ins)}
                                for x in sorted(hw, key=lambda x: -len(routines[x].ins))[:8]],
        'per_frame': pf,
    }


def format_report(rep):
    L = ['routines found: %d (%d instructions)' % (rep['routines'], rep['instructions']),
         '  pure RAM by themselves:         %d' % rep['pure_ram_local'],
         '  touch hardware:                 %d  (absolute %d, via address register %d)'
         % (rep['touch_hw'], rep['touch_hw_abs'], rep['touch_hw_areg']),
         '  indirect jump/call:             %d' % rep['indirect'],
         '  undecodable word:               %d' % rep['undecodable'],
         '  access via unknown base An:     %d' % rep['unknown_base'],
         '  pure RAM *for certain* (no unknown base): %d' % rep['pure_ram_certain'],
         '  instructions in transitively translatable routines: %d of %d (%.0f %%)'
         % (rep['translatable_instructions'], rep['instructions'], rep['translatable_pct']),
         '  translatable including callees (transitive): %d' % rep['translatable_transitive'],
         '  non-RAM accesses by kind: %s' % rep['non_ram_access_kinds'],
         '', 'hardware boundary:',
         '  routines touching hardware directly: %d (%d instructions, %.0f %% of code)'
         % (rep['touch_hw'], rep['hw_routines_instructions'],
            100.0 * rep['hw_routines_instructions'] / max(rep['instructions'], 1)),
         '  largest of them: ' + ', '.join('0x%05x (%d)' % (x['addr'], x['instructions'])
                                           for x in rep['largest_hw_routines'])]
    if rep['per_frame']:
        L.append('')
        L.append('per-frame routines:')
        for p in rep['per_frame']:
            if not p['found']:
                L.append('  0x%05x  not found' % p['addr'])
            else:
                L.append('  0x%05x  %4d instructions  %-9s calls %2d routines  %s%s'
                         % (p['addr'], p['instructions'], p['tag'], p['calls'],
                            'hw accesses %d  ' % p['hw_accesses'] if p['hw_accesses'] else '',
                            'unknown base An' if p['unknown_base'] else ''))
    return '\n'.join(L)
