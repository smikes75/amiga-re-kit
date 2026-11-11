"""The bus pattern of every 68000 instruction: its clocks without the bus and its bus cycles in the order the
processor makes them, and the place where it samples the interrupt level - measured on Moira (vAmiga's 68000) by
``moira_diff`` and kept in ``buspat.json`` (``arek difftest --bus-patterns`` writes it again).

Why: a host's bus model made an instruction's prefetches first, then its data accesses, then its idle clocks. On a
free bus that is the right length; beside DMA (bitplanes, the disk, the Copper) each access waits for ITS slot, so the
order decides where the instruction ends, and the interrupt level is sampled in one particular cycle. SWIV's
decompressor beside five bitplanes gained 21 colour clocks a frame.

A pattern is a list of items: an int = clocks without the bus, ``'p'`` = a read of the program stream (prefetch, an
extension word, a PC-relative operand), ``'d'`` = a data access, ``'V'`` = the clocks that depend on the data (a shift's
count, a multiply's bits, a bit number): the instruction's clock count minus everything else. A bus cycle is 4 clocks.
``poll`` = (j, delta): the level is sampled ``delta`` clocks after the start of bus cycle ``j`` (2 = inside it, before
its access; 0 = right before it; 4 and more = after it) - j = -1: ``delta`` clocks after the instruction's start.

An instruction whose pattern depends on the outcome (a branch taken or not, dbcc, scc) has one pattern per clock count.
The key of an instruction is its text with registers and numbers made anonymous plus its length in words; the patterns
of movem are stored as prefix / per-register unit / suffix."""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
_TABLE = None


def key(i):
    """The shape of instruction ``i``: what its bus pattern depends on."""
    t = i.text
    if i.kind in ('bcc', 'dbcc', 'scc'):                  # one shape for every condition: which way it went shows in the clock count
        t = i.kind + t[len(t.split()[0]):]
    t = re.sub(r'\b[dD][0-7]\b', 'dN', t)
    t = re.sub(r'\b[aA][0-7]\b', 'aN', t)
    t = re.sub(r'\$-?[0-9a-fA-F]+', '$#', t)
    t = t.replace(',aN)', ',dN)')                    # an index register: data or address, the same cycles
    t = re.sub(r'#?-?\b\d+\b', '#', t)
    if i.kind == 'movem':
        t += ' >' if i.to_mem else ' <'                # registers to memory / memory to registers
    return '%s|%d' % (t, (i.end - i.addr) // 2)


def canon(bus):
    """Moira's events ("2,f,2,2,r,4,r,2": sync clocks, f / r / w accesses) as items: idle clocks, 'p', 'd'. A bus cycle
    takes 2 clocks before and 2 after its access out of the syncs around it. Returns (items, cycle start clocks)."""
    items, starts, pend, t = [], [], 0, 0
    for e in ([] if bus in (None, '-', '') else bus.split(',')):
        if e in ('r', 'w', 'f'):
            pend -= 2
            if pend < 0:
                raise ValueError('an access without its 2 clocks: %s' % bus)
            if pend:
                items.append(pend)
                t += pend
            starts.append(t)
            items.append('p' if e == 'f' else 'd')
            t += 4
            pend = -2
        else:
            pend += int(e)
    if pend < 0:
        raise ValueError('a bus cycle without its end: %s' % bus)
    if pend:
        items.append(pend)
    return items, starts


def poll_of(bus, poll, starts):
    """Moira's poll index (the number of events before POLL_IPL) as (j, delta)."""
    ev = [] if bus in (None, '-', '') else bus.split(',')
    t = sum(int(e) for e in ev[:poll] if e not in ('r', 'w', 'f'))      # the syncs before the poll
    j = -1
    for k, s in enumerate(starts):
        if s <= t:
            j = k
    return (j, t - starts[j]) if j >= 0 else (-1, t)


def _fixed(items):
    return sum(x for x in items if isinstance(x, int)) + 4 * sum(1 for x in items if x in ('p', 'd'))


def merge(runs):
    """The runs of one key ([(items, poll, cycles)]) as variants [{'clocks', 'items', 'poll'}]: one pattern with a 'V'
    when the runs differ in one idle amount only, else one per clock count. None when they do not fit either."""
    uniq = sorted({(tuple(it), tuple(p)) for it, p, _ in runs}, key=repr)
    if len(uniq) == 1:
        return [{'clocks': 0, 'items': list(uniq[0][0]), 'poll': list(uniq[0][1])}]
    acc = {tuple(x for x in it if not isinstance(x, int)) for it, _ in uniq}
    polls = {p for _, p in uniq}
    if len(acc) == 1 and len(polls) == 1:
        # one access sequence: where do the idle clocks differ? gaps = idle before each access and at the end
        def gaps(it):
            g, cur = [], 0
            for x in it:
                if isinstance(x, int):
                    cur += x
                else:
                    g.append(cur)
                    cur = 0
            return g + [cur]
        gs = [gaps(it) for it, _ in uniq]
        diff = [k for k in range(len(gs[0])) if len({g[k] for g in gs}) > 1]
        if len(diff) == 1:
            # the whole gap is 'V' (the instruction's clocks minus everything else), not the smallest one seen plus a
            # rest: random operands never gave mulu a source with fewer than two 1 bits, and SWIV's music routine
            # multiplies by $20 - one colour clock too long with a floor of 38
            k, items, n = diff[0], [], 0
            for x in list(acc)[0] + (None,):
                if n == k:
                    items.append('V')
                elif gs[0][n]:
                    items.append(gs[0][n])
                if x is not None:
                    items.append(x)
                n += 1
            return [{'clocks': 0, 'items': items, 'poll': list(polls.pop())}]
    by = {}
    for it, p, c in runs:
        by.setdefault(c, set()).add((tuple(it), tuple(p)))
    if all(len(v) == 1 for v in by.values()):
        return [{'clocks': c, 'items': list(next(iter(v))[0]), 'poll': list(next(iter(v))[1])} for c, v in sorted(by.items())]
    return None


def movem_parts(items, n, unit):
    """items = prefix + n x unit + suffix -> (prefix, suffix) or None."""
    u = list(unit) * n
    for p in range(len(items) - len(u) + 1):
        if items[p:p + len(u)] == u:
            return items[:p], items[p + len(u):]
    return None


def table():
    global _TABLE
    if _TABLE is None:
        with open(os.path.join(HERE, 'buspat.json')) as f:
            _TABLE = json.load(f)
    return _TABLE


def variants(i):
    """The patterns of instruction ``i``: [{'clocks' (0 = any), 'items', 'poll': [j, delta]}], or None when the table
    does not know its shape."""
    t = table()
    k = key(i)
    if i.kind == 'movem':
        e = t['movem'].get(k)
        if e is None:
            return None
        n = bin(i.mask).count('1') if hasattr(i, 'mask') else None
        if n is None:
            return None
        items = e['prefix'] + e['unit'] * n + e['suffix']
        j = sum(1 for x in items if x in ('p', 'd')) - e['poll_from_end']
        return [{'clocks': 0, 'items': items, 'poll': [j, e['poll_delta']]}]
    return t['shapes'].get(k)


def encode(v):
    """A variant as bytes for the host: n items, poll j (255 = before the first cycle), poll delta, the items (1-127 idle
    clocks, 0x80 program read, 0x81 data access, 0xfe the data-dependent clocks)."""
    out = []
    for x in v['items']:
        if x == 'p':
            out.append(0x80)
        elif x == 'd':
            out.append(0x81)
        elif x == 'V':
            out.append(0xfe)
        else:
            while x > 127:
                out.append(127)
                x -= 127
            if x:
                out.append(x)
    j, d = v['poll']
    return bytes([len(out), 255 if j < 0 else j, min(d, 255)] + out)


def build(collected, decode):
    """``buspat.json``'s content from the collection {op: [{'code', 'kind', 'text', 'runs': [(bus, poll, cycles)]}]}
    (``difftest.collect_patterns``). Returns (table, problems)."""
    by_key, movem, problems = {}, {}, []
    for progs in collected.values():
        for p in progs:
            code = bytes.fromhex(p['code'])
            try:
                ins = decode(code + bytes(16), 0x8000, 0x8000)
            except Exception as e:                       # noqa: BLE001 - a template the decoder reads differently
                problems.append(('decode', p['code'], str(e)))
                continue
            k = key(ins)
            runs = []
            for bus, poll, cyc in p['runs']:
                items, starts = canon(bus)
                runs.append((items, poll_of(bus, poll, starts), cyc))
            if ins.kind == 'movem':
                n = bin(ins.mask).count('1')
                long_ = ins.sz == 2
                for items, pl, cyc in runs:
                    acc = 'p' if '(pc' in ins.text else 'd'      # a PC-relative source is read from the program space
                    unit = [acc, acc] if long_ else [acc]
                    if n < 1:
                        continue
                    if acc == 'p':                               # the unit looks like the words around it: the list starts behind the extension words
                        skip = (ins.end - ins.addr) // 2 - 1
                        seen = [k for k, x in enumerate(items) if x == 'p']
                        at = seen[skip] if len(seen) > skip else None
                        parts = (items[:at], items[at + len(unit) * n:]) if at is not None and items[at:at + len(unit) * n] == unit * n else None
                    else:
                        parts = movem_parts(items, n, unit)
                    if not parts:
                        problems.append(('movem', p['code'], items))
                        continue
                    total = sum(1 for x in items if x in ('p', 'd'))
                    e = {'prefix': parts[0], 'unit': unit, 'suffix': parts[1], 'poll_from_end': total - pl[0], 'poll_delta': pl[1]}
                    if movem.setdefault(k, e) != e:
                        problems.append(('movem differs', k, e, movem[k]))
                continue
            by_key.setdefault(k, []).extend(runs)
    shapes = {}
    for k, runs in sorted(by_key.items()):
        v = merge(runs)
        if v is None:
            problems.append(('no rule', k, sorted({(tuple(it), tuple(pl), c) for it, pl, c in runs}, key=repr)[:6]))
            continue
        shapes[k] = v
    return {'shapes': shapes, 'movem': movem}, problems
