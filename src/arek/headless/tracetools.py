"""Tools over trace records, from the Alien Breed II project (docs/HOST.md): the targets of the
original's indirect jumps, per-instruction timing of a host against the original's breakpoints,
records picked by pc, and the full-RAM difference of two traces paired by (frame, pc, order).

    arek trace targets TRACE IMAGE --base B          # -> arek recomp --indirect SITE=T1,T2 ...
    arek trace pcs ORIG.vtr HOST_PC.txt --tick PC    # exact passes, the first drift, where it changes
    arek trace filter IN.vtr OUT.vtr --pc PC...      # only these pcs (the tick boundary) for arek trace compare
    arek trace pairdiff ORIG.vtr HOST.vtr            # records paired by (frame, pc, order), bytes that differ
"""
import collections
import struct

from . import trace


def indirect_target(image, base, pc, d, a):
    """The target of the indirect jsr/jmp at ``pc`` from the registers of a record: (An), (d8,An,Xn),
    (d8,PC,Xn); ``image`` holds the code at ``base``."""
    op = struct.unpack('>H', image[pc - base:pc - base + 2])[0]
    mode, reg = (op >> 3) & 7, op & 7
    if mode == 2:                                   # (An)
        return a[reg] & 0xffffff
    ext = struct.unpack('>H', image[pc - base + 2:pc - base + 4])[0]
    xr = (ext >> 12) & 7
    x = (a if ext & 0x8000 else d)[xr]
    if not ext & 0x0800:                            # .W index
        x &= 0xffff
        x = x - 0x10000 if x & 0x8000 else x
    d8 = ext & 0xff
    d8 = d8 - 0x100 if d8 & 0x80 else d8
    if mode == 6:                                   # (d8,An,Xn)
        return (a[reg] + d8 + x) & 0xffffff
    if mode == 7 and reg == 3:                      # (d8,PC,Xn): PC = the extension word's address
        return (pc + 2 + d8 + x) & 0xffffff
    raise ValueError('site $%x: mode %d reg %d is not an indirect jump' % (pc, mode, reg))


def indirect_targets(records, image, base=0, only=None):
    """``{site: Counter(target: hits)}`` for the records at indirect jump sites (breakpoints on the
    jsr/jmp); ``only``: sites to take (default every record's pc)."""
    seen = collections.defaultdict(collections.Counter)
    for r in records:
        if only is not None and r['pc'] not in only:
            continue
        seen[r['pc']][indirect_target(image, base, r['pc'], r['d'], r['a'])] += 1
    return dict(seen)


def format_targets(targets):
    L = []
    for s, c in sorted(targets.items()):
        L.append('site $%06x: %d hits, %d targets: %s' % (s, sum(c.values()), len(c),
                 ' '.join('$%x(%d)' % (t, n) for t, n in sorted(c.items()))))
    if targets:
        L.append('arek recomp ... ' + ' '.join('--indirect %x=%s' % (s, ','.join('%x' % t for t in sorted(c)))
                                               for s, c in sorted(targets.items())))
    return '\n'.join(L)


def read_pclog(path):
    """Rows of a host's ``--pclog`` file (``frame pc v h`` per line) as ``(frame, pc, v, h)``."""
    out = []
    with open(path) as f:
        for line in f:
            x = line.split()
            if len(x) >= 4:
                out.append((int(x[0]), int(x[1], 16), int(x[2]), int(x[3])))
    return out


def pc_compare(orig, host, tick=None, from_frame=0, lines=313, hpos=227, drift_limit=25):
    """Per-instruction timing: the original's records (breakpoints on every pc) against a host's
    ``--pclog`` rows, from the first pass of ``tick`` at or after ``from_frame``. Returns ``seq`` (passes
    with the same pc sequence), ``exact`` (of those with the same beam position), ``first_time_diff``
    (index), ``seq_diff`` (index and both pcs where the sequence parts), ``drift`` [(index, host - original
    in CCK, change, pc, frame, v, h, previous pc)] where the difference changes."""
    O = [(r['frame'], r['pc'], r['v'], r['h']) for r in orig if r['frame'] >= from_frame]
    H = [h for h in host if h[0] >= from_frame] if from_frame else list(host)
    if tick is not None:
        O = O[next((i for i, o in enumerate(O) if o[1] == tick), len(O)):]
        H = H[next((i for i, h in enumerate(H) if h[1] == tick), len(H)):]
    T = lambda r: (r[0] * lines + r[2]) * hpos + r[3]
    seq = exact = 0
    first_time = None
    seq_diff = None
    drift, prev = [], 0
    for k, (o, h) in enumerate(zip(O, H)):
        if o[1] != h[1]:
            seq_diff = (k, o[1], h[1], O[k - 1][1] if k else None)
            break
        seq += 1
        if o == h:
            exact += 1
        elif first_time is None:
            first_time = k
        d = T(h) - T(o)
        if d != prev and len(drift) < drift_limit:
            drift.append((k, d, d - prev, o[1], o[0], o[2], o[3], O[k - 1][1] if k else None))
        prev = d
    return {'seq': seq, 'exact': exact, 'first_time_diff': first_time, 'seq_diff': seq_diff, 'drift': drift,
            'original': len(O), 'host': len(H)}


def format_pc_compare(r, image=None, base=0):
    def insn(pc):
        if image is None or pc is None:
            return ''
        from ..m68k import disasm
        try:
            rows = disasm.listing(image, base, pc, pc + 10, limit=1)
            return '  after: ' + disasm.format_listing(rows).strip().splitlines()[0]
        except Exception:
            return ''
    L = ['%d passes with the same pc sequence (original %d, host %d), %d of them exact in time' % (r['seq'], r['original'], r['host'], r['exact'])]
    if r['first_time_diff'] is not None:
        L.append('first time difference at pass %d' % r['first_time_diff'])
    if r['seq_diff']:
        k, o, h, p = r['seq_diff']
        L.append('pc sequence parts at pass %d: original %06x, host %06x%s' % (k, o, h, insn(p)))
    for k, d, dd, pc, frame, v, h, p in r['drift']:
        L.append('%7d %+5d (%+d) at %06x frame %d (%d,%d)%s' % (k, d, dd, pc, frame, v, h, insn(p)))
    return '\n'.join(L)


def filter_pcs(src, out, pcs, skip=0):
    """Only the records at ``pcs`` (e.g. the tick boundary) into ``out``, the first ``skip`` of them dropped."""
    n = 0
    with open(out, 'wb') as f:
        for k, r in enumerate(r for r in trace.records(src) if r['pc'] in pcs):
            if k < skip:
                continue
            f.write(trace.encode(r))
            n += 1
    return n


def pair_diff(a, b, from_frame=0, ignore=(), limit=40):
    """Records of two traces paired by (frame, pc, order within the frame); every byte that differs
    in the ranges both carry (``ignore``: [(start, length)] left out). Returns rows
    ``{'key': (frame, pc, n), 'only': 'orig'|'host'|None, 'a_beam', 'b_beam', 'diffs': [(addr, va, vb)]}``."""
    def key(recs):
        c, out = collections.Counter(), {}
        for r in recs:
            k = (r['frame'], r['pc'])
            out[(k[0], k[1], c[k])] = r
            c[k] += 1
        return out
    A, B = key(a), key(b)
    rows = []
    for k in sorted(set(A) | set(B)):
        if k[0] < from_frame:
            continue
        ra, rb = A.get(k), B.get(k)
        if not ra or not rb:
            rows.append({'key': k, 'only': 'orig' if ra else 'host', 'a_beam': (ra or rb)['v'], 'b_beam': None, 'diffs': []})
        else:
            diffs = []
            for base, p in ra['ranges'].items():
                q = rb['ranges'].get(base)
                if q is None:
                    continue
                for i in range(min(len(p), len(q))):
                    ad = base + i
                    if any(s <= ad < s + l for s, l in ignore):
                        continue
                    if p[i] != q[i]:
                        diffs.append((ad, p[i], q[i]))
            rows.append({'key': k, 'only': None, 'a_beam': (ra['v'], ra['h']), 'b_beam': (rb['v'], rb['h']), 'diffs': diffs})
        if len(rows) >= limit:
            break
    return rows


def format_pair_diff(rows):
    L = []
    for r in rows:
        f, pc, n = r['key']
        if r['only']:
            L.append('%5d %06x #%d only in %s' % (f, pc, n, r['only']))
        else:
            d = r['diffs']
            L.append('%5d %06x #%d beam o%s h%s %s' % (f, pc, n, r['a_beam'], r['b_beam'],
                     'EQUAL' if not d else '%d B: %s' % (len(d), ' '.join('$%x:%02x/%02x' % x for x in d[:10]))))
    return '\n'.join(L)
