"""Long parity: where a rebuild first leaves the original, record by record.

Both sides are traces in the layout of ``arek.headless.trace`` - the original from
``arek trace run`` (VTR1/VTR2, optionally ``--inputs`` so both get the same input), the
rebuild from its own engine writing the same records (``trace.encode``; the layout is in
docs/HEADLESS.md). Record k of one side is compared with record k + shift of the other:
the captured RAM word by word (and hashed ranges by hash), optionally the CPU registers.

    a, b = list(trace.records('orig.vtr')), list(trace.records('native.vtr'))
    r = compare(a, b, ignore=[(0xc00100, 0x40)])   # r['first']: the first record that differs
    best_shift(a, b, range(-3, 4))                  # a rebuild one or two ticks out of phase

Three game projects did this on their own (Alien Breed ``origtrace``/``tracecmp``, Turrican II
``origtrace``, Superfrog Sonnet ``verify_rec``); this is the common part.
"""
from .headless import trace


def _spans(rec):
    return [(s, s + len(d), d) for s, d in rec['ranges'].items()]


def _cut(lo, hi, ignore):
    """[lo, hi) minus the ``ignore`` spans, as a list of spans."""
    parts = [(lo, hi)]
    for s, n in ignore:
        out = []
        for a, b in parts:
            if s + n <= a or s >= b:
                out.append((a, b))
                continue
            if a < s:
                out.append((a, s))
            if s + n < b:
                out.append((s + n, b))
        parts = out
    return parts


def diff_records(ra, rb, ranges=None, ignore=(), regs=False):
    """Differences between two records: ``[(addr or name, a, b), ...]`` - 16-bit words of the
    RAM both captured (within ``ranges`` [(start, length)] when given, minus ``ignore``),
    hashed ranges by their hash (``('hash', start)``), and with ``regs`` D0-D7/A0-A7/SR."""
    out = []
    for sa, ea, da in _spans(ra):
        for sb, eb, db in _spans(rb):
            lo, hi = max(sa, sb), min(ea, eb)
            if lo >= hi:
                continue
            windows = [(lo, hi)] if not ranges else \
                [(max(lo, s), min(hi, s + n)) for s, n in ranges if max(lo, s) < min(hi, s + n)]
            for wlo, whi in windows:
                for plo, phi in _cut(wlo, whi, ignore):
                    plo += plo & 1
                    xa, xb = da[plo - sa:phi - sa], db[plo - sb:phi - sb]
                    if xa == xb:
                        continue
                    for off in range(0, len(xa) - 1, 2):
                        if xa[off:off + 2] != xb[off:off + 2]:
                            out.append((plo + off, int.from_bytes(xa[off:off + 2], 'big'),
                                        int.from_bytes(xb[off:off + 2], 'big')))
    for start, (ln, ha) in ra.get('hashes', {}).items():
        hb = rb.get('hashes', {}).get(start)
        if hb is None and start in rb['ranges'] and len(rb['ranges'][start]) == ln:
            hb = (ln, trace.fnv1a64(rb['ranges'][start]))
        if hb is not None and hb[1] != ha:
            out.append((('hash', start), ha, hb[1]))
    if regs:
        for name, i in [('d%d' % i, i) for i in range(8)]:
            if ra['d'][i] != rb['d'][i]:
                out.append((name, ra['d'][i], rb['d'][i]))
        for name, i in [('a%d' % i, i) for i in range(8)]:
            if ra['a'][i] != rb['a'][i]:
                out.append((name, ra['a'][i], rb['a'][i]))
        if ra['sr'] != rb['sr']:
            out.append(('sr', ra['sr'], rb['sr']))
    return out


def compare(a, b, ranges=None, ignore=(), shift=0, regs=False, limit=20):
    """Record k of ``a`` against record k + ``shift`` of ``b``. Returns ``pairs``, ``equal``,
    ``first`` (index, hit/frame of both sides, the first ``limit`` differences), ``differing``
    [(k, number of differences)] and ``addresses`` [(addr, records where it differs)] by count."""
    pairs = [(k, k + shift) for k in range(len(a)) if 0 <= k + shift < len(b)]
    first, differing, counts = None, [], {}
    for k, j in pairs:
        d = diff_records(a[k], b[j], ranges, ignore, regs)
        if not d:
            continue
        differing.append((k, len(d)))
        for addr, _, _ in d:
            counts[addr] = counts.get(addr, 0) + 1
        if first is None:
            first = {'index': k, 'a': {'hit': a[k]['hit'], 'frame': a[k]['frame']},
                     'b': {'hit': b[j]['hit'], 'frame': b[j]['frame']}, 'diffs': d[:limit], 'count': len(d)}
    top = sorted(counts.items(), key=lambda kv: (-kv[1], str(kv[0])))[:limit]
    return {'pairs': len(pairs), 'equal': len(pairs) - len(differing), 'shift': shift, 'first': first,
            'differing': differing, 'addresses': top}


def best_shift(a, b, shifts=range(-3, 4), ranges=None, ignore=()):
    """Which phase fits: ``[(shift, equal pairs, pairs), ...]``, best first."""
    out = []
    for s in shifts:
        r = compare(a, b, ranges, ignore, s)
        out.append((s, r['equal'], r['pairs']))
    return sorted(out, key=lambda t: (-(t[1] / t[2] if t[2] else 0), abs(t[0])))


def _addr(x):
    return '%s %x' % x if isinstance(x, tuple) else ('%06x' % x if isinstance(x, int) else x)


def format_compare(r):
    L = ['%d of %d record pairs equal (shift %d)' % (r['equal'], r['pairs'], r['shift'])]
    f = r['first']
    if f:
        L.append('first difference: record %d (original hit %d frame %d, rebuild hit %d frame %d), %d differences'
                 % (f['index'], f['a']['hit'], f['a']['frame'], f['b']['hit'], f['b']['frame'], f['count']))
        for addr, va, vb in f['diffs']:
            L.append('  %-10s original %-8x rebuild %x' % (_addr(addr), va, vb))
        L.append('most often different: ' + ', '.join('%s (%d)' % (_addr(x), n) for x, n in r['addresses'][:10]))
    return '\n'.join(L)
