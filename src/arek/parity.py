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


def expected(ra, ranges=None, ignore=()):
    """What a comparison of the original's record ``ra`` covers: ``(bytes, hashes)`` - its captured bytes within
    ``ranges`` minus ``ignore``, and its hashed ranges. (0, 0) means the record gives nothing to compare."""
    n = 0
    for sa, ea, _ in _spans(ra):
        for wlo, whi in ([(sa, ea)] if not ranges else [(max(sa, s), min(ea, s + k)) for s, k in ranges if max(sa, s) < min(ea, s + k)]):
            n += sum(hi - lo for lo, hi in _cut(wlo, whi, ignore))
    return n, len(ra.get('hashes', {}))


def diff_records(ra, rb, ranges=None, ignore=(), regs=False):
    """Differences between two records, the original ``ra`` being the reference: ``[(addr or name, a, b), ...]``.

    Every byte the original captured (within ``ranges`` [(start, length)] when given, minus ``ignore``) is expected
    on the rebuild's side: bytes that differ are reported as 16-bit words at even addresses (a single byte where the
    piece starts or ends on an odd address), bytes the rebuild did not capture as ``(('missing', start), length, 0)``
    (1.0.39: before, only the bytes both sides happened to carry were looked at, so a rebuild with other ranges, or
    none, compared equal). Hashed ranges go by their hash (``('hash', start)``; a hash the rebuild lacks, or one over
    another length, is a difference). A part of ``ranges`` the original itself did not capture (nor hash) is
    ``(('uncaptured', start), length, 0)``: asked for, never checked. With ``regs`` also D0-D7/A0-A7/SR."""
    out = []
    spans_b = _spans(rb)
    have = [(s, e - s) for s, e, _ in _spans(ra)] + [(s, ln) for s, (ln, _) in ra.get('hashes', {}).items()]
    for s, n in ranges or ():
        for plo, phi in _cut(s, s + n, ignore):
            for mlo, mhi in _cut(plo, phi, have):
                if mhi > mlo:
                    out.append((('uncaptured', mlo), mhi - mlo, 0))
    for sa, ea, da in _spans(ra):
        windows = [(sa, ea)] if not ranges else \
            [(max(sa, s), min(ea, s + n)) for s, n in ranges if max(sa, s) < min(ea, s + n)]
        for wlo, whi in windows:
            for plo, phi in _cut(wlo, whi, ignore):
                covered = []
                for sb, eb, db in spans_b:
                    lo, hi = max(plo, sb), min(phi, eb)
                    if lo >= hi:
                        continue
                    covered.append((lo, hi - lo))
                    xa, xb = da[lo - sa:hi - sa], db[lo - sb:hi - sb]
                    if xa == xb:
                        continue
                    at = lo
                    while at < hi:
                        end = min(hi, (at | 1) + 1)                   # up to the end of the word ``at`` lies in
                        wa, wb = da[at - sa:end - sa], db[at - sb:end - sb]
                        if wa != wb:
                            out.append((at, int.from_bytes(wa, 'big'), int.from_bytes(wb, 'big')))
                        at = end
                for mlo, mhi in _cut(plo, phi, covered):
                    if mhi > mlo:
                        out.append((('missing', mlo), mhi - mlo, 0))
    for start, (ln, ha) in ra.get('hashes', {}).items():
        hb = rb.get('hashes', {}).get(start)
        if hb is None and start in rb['ranges'] and len(rb['ranges'][start]) == ln:
            hb = (ln, trace.fnv1a64(rb['ranges'][start]))
        if hb is None:
            out.append((('missing hash', start), ln, 0))
        elif hb[0] != ln or hb[1] != ha:
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
    """Record k of ``a`` (the original) against record k + ``shift`` of ``b`` (the rebuild). Returns ``pairs``,
    ``equal``, ``first`` (index, hit/frame of both sides, the first ``limit`` differences), ``differing``
    [(k, number of differences)] and ``addresses`` [(addr, records where it differs)] by count; 1.0.39 also
    ``original`` and ``rebuild`` (records on each side), ``short`` (original records past the rebuild's end - the
    rebuild stopped early, or is empty), ``extra`` (rebuild records past the original's end), ``bytes`` / ``hashes``
    (how much of the original the pairs put to the test; ``empty`` when that is nothing) and ``complete``: every
    original record had a partner, the pairs carried something to compare and all are equal - the only pass."""
    pairs = [(k, k + shift) for k in range(len(a)) if 0 <= k + shift < len(b)]
    short = sum(1 for k in range(len(a)) if k + shift >= len(b))
    extra = max(0, len(b) - max(0, len(a) + shift))
    first, differing, counts, nbytes, nhash = None, [], {}, 0, 0
    for k, j in pairs:
        eb, eh = expected(a[k], ranges, ignore)
        nbytes, nhash = nbytes + eb, nhash + eh
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
    empty = bool(pairs) and not (nbytes or nhash or regs)            # paired, but the records carry nothing to compare
    return {'pairs': len(pairs), 'equal': len(pairs) - len(differing), 'shift': shift, 'first': first,
            'differing': differing, 'addresses': top, 'original': len(a), 'rebuild': len(b), 'short': short,
            'extra': extra, 'bytes': nbytes, 'hashes': nhash, 'empty': empty,
            'complete': bool(pairs) and not differing and not short and not empty}


def best_shift(a, b, shifts=range(-3, 4), ranges=None, ignore=()):
    """Which phase fits: ``[(shift, equal pairs, pairs), ...]``, best first."""
    out = []
    for s in shifts:
        r = compare(a, b, ranges, ignore, s)
        out.append((s, r['equal'], r['pairs']))
    return sorted(out, key=lambda t: (-(t[1] / t[2] if t[2] else 0), abs(t[0])))


def _addr(x):
    return '%s %x' % x if isinstance(x, tuple) else ('%06x' % x if isinstance(x, int) else x)


def _diff_line(addr, va, vb):
    if isinstance(addr, tuple) and addr[0] == 'uncaptured':
        return '  %-10s %d bytes of the asked range are not in the original\'s record (never checked)' % ('%06x' % addr[1], va)
    if isinstance(addr, tuple) and addr[0].startswith('missing'):
        return '  %-10s %d bytes the rebuild did not capture%s' % ('%06x' % addr[1], va, ' (a hashed range)' if addr[0] == 'missing hash' else '')
    return '  %-10s original %-8x rebuild %x' % (_addr(addr), va, vb)


def format_compare(r):
    L = ['%d of %d record pairs equal (shift %d); original %d records, rebuild %d; %d bytes and %d hashes compared'
         % (r['equal'], r['pairs'], r['shift'], r.get('original', r['pairs']), r.get('rebuild', r['pairs']),
            r.get('bytes', 0), r.get('hashes', 0))]
    if not r['pairs']:
        L.append('NOTHING COMPARED: no record of the original has a partner in the rebuild')
    elif r.get('empty'):
        L.append('NOTHING COMPARED: the paired records carry no bytes or hashes in the given ranges (and no --regs)')
    elif r.get('short'):
        L.append('NOT COMPLETE: the last %d records of the original have no partner - the rebuild ends early' % r['short'])
    if r.get('extra'):
        L.append('the rebuild goes on for %d records past the original (not compared)' % r['extra'])
    f = r['first']
    if f:
        L.append('first difference: record %d (original hit %d frame %d, rebuild hit %d frame %d), %d differences'
                 % (f['index'], f['a']['hit'], f['a']['frame'], f['b']['hit'], f['b']['frame'], f['count']))
        for addr, va, vb in f['diffs']:
            L.append(_diff_line(addr, va, vb))
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
    """Frames whose audio writes agree, with the one shift (rebuild frame = original + shift) that fits the whole
    scenario best: ``{'frames', 'equal', 'shift', 'first', 'original', 'rebuild'}``. ``frames`` counts the frames in
    which either side wrote, the rebuild's moved back by the shift - so a frame only one side wrote in is unequal
    whatever the shift (1.0.39: before, a shift could move the rebuild's writes onto frames nobody looked at, and
    frames in which neither side wrote at ``f + shift`` counted as equal). ``original`` / ``rebuild``: frames with
    writes on each side. The rebuild's side comes from ``trace.encode_reglog``."""
    a, b = _audio_frames(orig), _audio_frames(rebuild)
    if not a and not b:
        return {'frames': 0, 'equal': 0, 'shift': 0, 'first': None, 'original': 0, 'rebuild': 0}
    best = None
    for s in shifts:
        frames = set(a) | {g - s for g in b}
        eq = sum(1 for f in frames if a.get(f, ()) == b.get(f + s, ()))
        score = (eq, -len(frames), -abs(s))
        if best is None or score > best[0]:
            best = (score, s, eq, frames)
    _, s, eq, frames = best
    first = next((f for f in sorted(frames) if a.get(f, ()) != b.get(f + s, ())), None)
    return {'frames': len(frames), 'equal': eq, 'shift': s, 'first': first, 'original': len(a), 'rebuild': len(b)}


def align_shot(a, b, width=716, max_shift=8, sample=4, step=1):
    """The shift (dx, dy) of picture b against a (RGB24 rows of ``width``) with the fewest differing pixels on a grid
    of every ``sample``-th pixel, |dx|, |dy| <= max_shift (dx in steps of ``step``; 2 for lowres pixels in a vAmiga
    screenshot): a screen shake moves the rebuild's window against the original's."""
    h = len(a) // (3 * width)
    best = None
    for dy in range(-max_shift, max_shift + 1):
        for dx in range(-max_shift, max_shift + 1, step):
            bad = 0
            for y in range(max_shift, h - max_shift, sample):
                ra, rb = (y * width) * 3, ((y + dy) * width) * 3
                for x in range(max_shift, width - max_shift, sample):
                    pa, pb = ra + 3 * x, rb + 3 * (x + dx)
                    bad += a[pa:pa + 3] != b[pb:pb + 3]
            if best is None or bad < best[0]:
                best = (bad, dx, dy)
    return best[1], best[2]


def diff_shots(da, db, tolerance=0, dx=0, dy=0, width=716):
    """Differing pixels of two RGB24 pictures, b shifted by (dx, dy) against a (the pixels a shift moves out are
    left out): ``(n, box)``, box = (x0, y0, x1, y1) or None. A buffer that is not ``width`` wide counts as one row."""
    if len(da) % (3 * width):
        width = len(da) // 3
    h = len(da) // (3 * width)
    n, x0, y0, x1, y1 = 0, None, None, None, None
    for y in range(h):
        yb = y + dy
        if not 0 <= yb < h:
            continue
        ra, rb = y * width * 3, yb * width * 3
        for x in range(width):
            xb = x + dx
            if not 0 <= xb < width:
                continue
            i, j = ra + 3 * x, rb + 3 * xb
            if abs(da[i] - db[j]) > tolerance or abs(da[i + 1] - db[j + 1]) > tolerance or abs(da[i + 2] - db[j + 2]) > tolerance:
                n += 1
                x0, y0 = x if x0 is None else min(x0, x), y if y0 is None else min(y0, y)
                x1, y1 = x if x1 is None else max(x1, x), y if y1 is None else max(y1, y)
    return n, (x0, y0, x1, y1) if n else None


def compare_shots(orig_prefix, rebuild_prefix, tolerance=0, shift=0, align=0, width=716):
    """Pictures of both sides (``trace.shot_files``: PREFIX_<frame>.raw, RGB24), paired by frame
    (rebuild frame = original + shift): ``{'pairs', 'equal', 'pixels', 'differing', 'worst', 'frames'}``,
    a pixel equal when every channel is within ``tolerance``; ``align`` > 0: every pair is first aligned by the
    best shift up to that many pixels (a screen shake), ``frames`` lists (frame, differing, (dx, dy), box).
    1.0.39: ``missing`` = the original's frames the rebuild has no picture of (they are not equal), ``extra`` = the
    rebuild's pictures without an original, ``aligned`` = pairs that needed a shift, ``complete`` = every original
    picture has a partner and all pairs are equal; an empty picture is an error."""
    a, b = dict(trace.shot_files(orig_prefix)), dict(trace.shot_files(rebuild_prefix))
    pairs, equal, px, total, worst, frames, aligned = 0, 0, 0, 0, None, [], 0
    missing = [f for f in sorted(a) if f + shift not in b]
    extra = len([g for g in b if g - shift not in a])
    for f in sorted(a):
        if f + shift not in b:
            continue
        da, db = open(a[f], 'rb').read(), open(b[f + shift], 'rb').read()
        if not da or len(da) % 3:
            raise ValueError('shot %s is not an RGB24 picture (%d bytes)' % (a[f], len(da)))
        if len(da) != len(db):
            raise ValueError('shots %s and %s differ in size' % (a[f], b[f + shift]))
        dx, dy = align_shot(da, db, width, align) if align else (0, 0)
        n, box = diff_shots(da, db, tolerance, dx, dy, width)
        pairs += 1
        equal += n == 0
        aligned += (dx, dy) != (0, 0)
        px += n
        total += len(da) // 3
        frames.append((f, n, (dx, dy), box))
        if worst is None or n > worst[1]:
            worst = (f, n)
    return {'pairs': pairs, 'equal': equal, 'pixels': total, 'differing': px, 'worst': worst, 'frames': frames,
            'missing': missing, 'extra': extra, 'aligned': aligned, 'complete': bool(pairs) and equal == pairs and not missing}


def format_shots(r, all_frames=False):
    L = ['%d of %d pairs equal, %d of %d pixels differ%s' % (r['equal'], r['pairs'], r['differing'], r['pixels'],
                                                           ', worst frame %d (%d)' % r['worst'] if r['worst'] else '')]
    if not r['pairs']:
        L.append('NOTHING COMPARED: no picture of the original has a partner in the rebuild')
    if r.get('missing'):
        m = r['missing']
        L.append('NOT COMPLETE: the rebuild has no picture for %d frames of the original (%s%s)'
                 % (len(m), ', '.join(str(f) for f in m[:8]), ', ...' if len(m) > 8 else ''))
    if r.get('extra'):
        L.append('%d pictures of the rebuild have no original (not compared)' % r['extra'])
    if r.get('aligned'):
        L.append('%d pairs were shifted before comparing (align)' % r['aligned'])
    for f, n, (dx, dy), box in r['frames']:
        if n or all_frames or (dx, dy) != (0, 0):
            L.append('  frame %d: %d pixels, shift (%d, %d)%s' % (f, n, dx, dy, ', box %s' % (box,) if box else ''))
    return '\n'.join(L)


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
        row = {'name': sc['name'], 'state': None, 'picture': None, 'sound': None, 'problems': []}
        prob = row['problems']
        if path('trace', o) and not os.path.exists(path('trace', o)) and o.get('make') and run:
            subprocess.run(o['make'], shell=True, check=True, cwd=base)
        for what in ('trace', 'reglog'):                 # 1.0.39: a file the scenario names and one side lacks is a problem, not a '-'
            for side, name in ((o, 'original'), (r, 'rebuild')):
                other = r if side is o else o
                if path(what, side) and not os.path.exists(path(what, side)):
                    prob.append('%s %s missing: %s' % (name, what, side[what]))
                elif path(what, other) and not path(what, side):
                    prob.append('%s has no %s (the other side names one)' % (name, what))
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
                            'best_shift': shifts[0][0], 'equal_shifted': shifts[0][1],
                            'original': c0['original'], 'rebuild': c0['rebuild'], 'short': c0['short'],
                            'bytes': c0['bytes'], 'hashes': c0['hashes'], 'complete': c0['complete']}
            if not c0['pairs']:
                prob.append('state: nothing compared (original %d records, rebuild %d)' % (c0['original'], c0['rebuild']))
            elif c0['empty']:
                prob.append('state: the records carry nothing to compare in the given ranges')
            elif c0['short']:
                prob.append('state: the rebuild ends %d records before the original' % c0['short'])
        if path('shots', o) and path('shots', r):
            pic = row['picture'] = compare_shots(path('shots', o), path('shots', r), sc.get('tolerance', 0), sc.get('shot_shift', 0), sc.get('align', 0))
            if not pic['pairs']:
                prob.append('picture: nothing compared (%d pictures of the original without a partner)' % len(pic['missing']))
            elif pic['missing']:
                prob.append('picture: the rebuild has no picture for %d frames of the original' % len(pic['missing']))
            if pic['aligned']:
                prob.append('picture: %d pairs were shifted before comparing (align)' % pic['aligned'])
        elif path('shots', o) or path('shots', r):
            prob.append('%s has no shots (the other side names them)' % ('rebuild' if path('shots', o) else 'original'))
        if path('reglog', o) and path('reglog', r) and os.path.exists(path('reglog', o)) and os.path.exists(path('reglog', r)):
            n = sc.get('audio_shifts', 60)
            snd = row['sound'] = compare_audio(path('reglog', o), path('reglog', r), range(-n, n + 1))
            if not snd['frames']:
                prob.append('sound: neither side wrote to Paula (nothing compared)')
            elif not snd['original'] or not snd['rebuild']:
                prob.append('sound: the %s wrote nothing to Paula' % ('original' if not snd['original'] else 'rebuild'))
        if not any(x is not None for x in (row['state'], row['picture'], row['sound'])) and not prob:
            prob.append('the scenario compares nothing (no trace, shots or reglog on both sides)')
        row['complete'] = not prob and all(x is None or x.get('complete', x.get('equal') == x.get('frames')) for x in (row['state'], row['picture'], row['sound'])) \
            and any(x is not None for x in (row['state'], row['picture'], row['sound']))
        rows.append(row)
    return rows


def suite_ok(rows, strict=False):
    """The exit status of ``arek parity``: False when a scenario has a problem (a missing side, nothing compared, a
    rebuild that ends early); with ``strict`` also when anything differs."""
    return bool(rows) and all((r['complete'] if strict else not r['problems']) for r in rows)


def format_suite(rows):
    L = ['%-14s %18s %11s %10s %16s %20s' % ('scenario', 'state equal', 'first/frame', 'shift:eq', 'picture equal', 'sound equal')]
    for r in rows:
        st, pic, snd = r['state'], r['picture'], r['sound']
        n_st = st['pairs'] + st.get('short', 0) if st else 0             # 1.0.39: the original's records, not only the paired ones
        s1 = '%d/%d (%.1f%%)' % (st['equal'], n_st, 100 * st['equal'] / n_st) if st and n_st else '-'
        s2 = ('%d/f%d' % (st['first'], st['first_frame'])) if st and st['first'] is not None else '-'
        s3 = '%d:%d' % (st['best_shift'], st['equal_shifted']) if st else '-'
        n_pic = pic['pairs'] + len(pic.get('missing', ())) if pic else 0
        s4 = '%d/%d' % (pic['equal'], n_pic) if pic else '-'
        if pic and pic['pixels']:
            s4 += ' (%.2f%%)' % (100 * (1 - pic['differing'] / pic['pixels']))
        s5 = '%d/%d (%.1f%%) s%+d' % (snd['equal'], snd['frames'], 100 * snd['equal'] / snd['frames'], snd['shift']) if snd and snd['frames'] else '-'
        L.append('%-14s %18s %11s %10s %16s %20s' % (r['name'][:14], s1, s2, s3, s4, s5))
    for r in rows:
        for p in r.get('problems', ()):
            L.append('PROBLEM %s: %s' % (r['name'], p))
    return '\n'.join(L)
