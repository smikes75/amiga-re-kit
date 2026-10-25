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

``suite`` runs many scenarios at once (``arek parity SUITE.json``): per scenario the state (the
traces above), the picture (screenshots of both sides, ``--shots`` on the original) and the
sound (the writes to Paula, ``--reglog`` on the original, the same binary layout from the
rebuild), each as "how many ticks agree and where the first difference is" - the table the
Superfrog project kept by hand (``tools/shoda.py``).
"""
import json
import os
import subprocess

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


# --- a suite of scenarios -------------------------------------------------------------------

AUDIO_REGS = {0x096} | {0x0a0 + 16 * c + o for c in range(4) for o in (0, 2, 4, 6, 8)}     # DMACON, AUDxLC/LEN/PER/VOL


def _audio_frames(path, regs=AUDIO_REGS):
    """Per frame the writes to the audio registers (and DMACON) as a tuple of (reg, value)."""
    out = {}
    for r in trace.read_reglog(path):
        if r['reg'] in regs and not r['agnus']:
            out.setdefault(r['frame'], []).append((r['reg'], r['value']))
    return {f: tuple(v) for f, v in out.items()}


def compare_audio(orig, rebuild, shifts=range(-60, 61)):
    """Frames whose audio writes agree, with the one shift (rebuild frame = original + shift)
    that fits the whole scenario best: ``{'frames', 'equal', 'shift', 'first'}``. ``frames`` is
    the union of the frames either side wrote in (before the shift), so a frame the rebuild
    writes at ``f + shift`` counts once under ``f``; a frame only one side wrote in counts as
    unequal. The rebuild's side comes from ``trace.encode_reglog``."""
    a, b = _audio_frames(orig), _audio_frames(rebuild)
    frames = sorted(set(a) | set(b))
    if not frames:
        return {'frames': 0, 'equal': 0, 'shift': 0, 'first': None}
    best = None
    for s in shifts:
        eq = sum(1 for f in frames if a.get(f, ()) == b.get(f + s, ()))
        if best is None or eq > best[1] or (eq == best[1] and abs(s) < abs(best[0])):
            best = (s, eq)
    s, eq = best
    first = next((f for f in frames if a.get(f, ()) != b.get(f + s, ())), None)
    return {'frames': len(frames), 'equal': eq, 'shift': s, 'first': first}


def compare_shots(orig_prefix, rebuild_prefix, tolerance=0, shift=0):
    """Pictures of both sides (``trace.shot_files``: PREFIX_<frame>.raw, RGB24), paired by frame
    (rebuild frame = original + shift): ``{'pairs', 'equal', 'pixels', 'differing', 'worst'}``,
    a pixel equal when every channel is within ``tolerance``."""
    a, b = dict(trace.shot_files(orig_prefix)), dict(trace.shot_files(rebuild_prefix))
    pairs, equal, px, total, worst = 0, 0, 0, 0, None
    for f in sorted(a):
        if f + shift not in b:
            continue
        da, db = open(a[f], 'rb').read(), open(b[f + shift], 'rb').read()
        if len(da) != len(db):
            raise ValueError('shots %s and %s differ in size' % (a[f], b[f + shift]))
        n = 0
        for i in range(0, len(da), 3):
            if abs(da[i] - db[i]) > tolerance or abs(da[i + 1] - db[i + 1]) > tolerance or abs(da[i + 2] - db[i + 2]) > tolerance:
                n += 1
        pairs += 1
        equal += n == 0
        px += n
        total += len(da) // 3
        if worst is None or n > worst[1]:
            worst = (f, n)
    return {'pairs': pairs, 'equal': equal, 'pixels': total, 'differing': px, 'worst': worst}


def suite(cfg, base='.', run=True):
    """Run every scenario of ``cfg`` (a dict or a JSON path) and return its rows. A scenario::

        {"name": "l1-idle",
         "original": {"trace": "build/l1.vtr", "shots": "build/l1_shot", "reglog": "build/l1.reg",
                      "make": "arek trace run ... --out build/l1.vtr"},
         "rebuild":  {"trace": "build/l1_native.vtr", "shots": "build/l1_native_shot", "reglog": "build/l1_native.reg"},
         "ranges": ["c01776:300"], "ignore": ["c01978:4"], "shifts": 4, "tolerance": 8, "audio_shifts": 60}

    Paths are relative to ``base``. ``make`` is run (shell) when the original's trace is
    missing and ``run`` is true - the emulator side is cached by its file. Shots and reglog are
    optional; a row has ``state``, ``picture`` and ``sound`` with None where a side is missing."""
    if not isinstance(cfg, dict):
        cfg = json.loads(open(cfg).read())
    rows = []
    for sc in cfg['scenarios']:
        o, r = sc['original'], sc['rebuild']

        def path(k, side):
            return os.path.join(base, side[k]) if side.get(k) else None
        row = {'name': sc['name'], 'state': None, 'picture': None, 'sound': None}
        if path('trace', o) and not os.path.exists(path('trace', o)) and o.get('make') and run:
            subprocess.run(o['make'], shell=True, check=True, cwd=base)
        if path('trace', o) and path('trace', r) and os.path.exists(path('trace', o)) and os.path.exists(path('trace', r)):
            ta, tb = list(trace.records(path('trace', o))), list(trace.records(path('trace', r)))
            rng = [trace.parse_range(x)[:2] for x in sc.get('ranges', [])] or None
            ign = [trace.parse_range(x)[:2] for x in sc.get('ignore', [])]
            n = sc.get('shifts', 4)
            shifts = best_shift(ta, tb, range(-n, n + 1), rng, ign)
            c0 = compare(ta, tb, rng, ign, 0)
            f = c0['first']
            row['state'] = {'pairs': c0['pairs'], 'equal': c0['equal'],
                            'first': f['index'] if f else None,                 # record index (0-based)
                            'first_frame': f['a']['frame'] if f else None,      # the original's frame and hit there
                            'first_hit': f['a']['hit'] if f else None,
                            'best_shift': shifts[0][0], 'equal_shifted': shifts[0][1]}
        if path('shots', o) and path('shots', r):
            row['picture'] = compare_shots(path('shots', o), path('shots', r), sc.get('tolerance', 0), sc.get('shot_shift', 0))
        if path('reglog', o) and path('reglog', r) and os.path.exists(path('reglog', o)) and os.path.exists(path('reglog', r)):
            n = sc.get('audio_shifts', 60)
            row['sound'] = compare_audio(path('reglog', o), path('reglog', r), range(-n, n + 1))
        rows.append(row)
    return rows


def format_suite(rows):
    L = ['%-14s %18s %11s %10s %16s %20s' % ('scenario', 'state equal', 'first/frame', 'shift:eq', 'picture equal', 'sound equal')]
    for r in rows:
        st, pic, snd = r['state'], r['picture'], r['sound']
        s1 = '%d/%d (%.1f%%)' % (st['equal'], st['pairs'], 100 * st['equal'] / st['pairs']) if st and st['pairs'] else '-'
        s2 = ('%d/f%d' % (st['first'], st['first_frame'])) if st and st['first'] is not None else '-'
        s3 = '%d:%d' % (st['best_shift'], st['equal_shifted']) if st else '-'
        s4 = '%d/%d' % (pic['equal'], pic['pairs']) if pic else '-'
        if pic and pic['pixels']:
            s4 += ' (%.2f%%)' % (100 * (1 - pic['differing'] / pic['pixels']))
        s5 = '%d/%d (%.1f%%) s%+d' % (snd['equal'], snd['frames'], 100 * snd['equal'] / snd['frames'], snd['shift']) if snd and snd['frames'] else '-'
        L.append('%-14s %18s %11s %10s %16s %20s' % (r['name'][:14], s1, s2, s3, s4, s5))
    return '\n'.join(L)
