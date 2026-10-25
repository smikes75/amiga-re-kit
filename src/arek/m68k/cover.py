"""Coverage of a translation run (``recomp --cover``): which translated instructions ran.

The runtime keeps one bit per instruction word and ``cov_dump`` writes the addresses that ran
as ranges (``H <lo> <n>`` then ``first-last`` per line, hex); ``recomp --cover`` also writes
``OUT.cover.json`` with the translated instructions per routine. Together they say how much of
each routine a run exercised and which routines never ran - the places a random-input run
(``arek fuzz``) has not reached and a bug may hide.
"""
import json


def read(src):
    """The addresses that ran, as a set of instruction addresses."""
    text = src if isinstance(src, str) and '\n' in src else open(src).read()
    ran = set()
    for line in text.splitlines():
        f = line.split()
        if not f or f[0] == 'H':
            continue
        a, _, b = f[0].partition('-')
        lo, hi = int(a, 16), int(b or a, 16)
        ran.update(range(lo, hi + 1, 2))
    return ran


def report(ran, sidecar, top=20):
    """``{'instructions', 'executed', 'routines': [{'addr', 'instructions', 'executed', 'share'}, ...]
    (least covered first), 'never': [addr, ...]}`` from the executed set and the sidecar
    (``recomp --cover``: path or dict)."""
    side = sidecar if isinstance(sidecar, dict) else json.loads(open(sidecar).read())
    routines, total, hit = [], 0, 0
    for entry, ranges in side['routines'].items():
        pcs = [a for lo, hi in ranges for a in range(lo, hi + 1, 2)]
        n = len(pcs)
        e = sum(1 for a in pcs if a in ran)
        total += n
        hit += e
        routines.append({'addr': int(entry, 16), 'instructions': n, 'executed': e, 'share': e / n if n else 0.0})
    routines.sort(key=lambda r: (r['share'], -r['instructions'], r['addr']))
    return {'instructions': total, 'executed': hit, 'share': hit / total if total else 0.0,
            'routines': routines[:top] if top else routines,
            'never': [r['addr'] for r in routines if r['executed'] == 0]}


def format_report(r):
    L = ['%d of %d translated instructions ran (%.1f %%), %d routines never ran'
         % (r['executed'], r['instructions'], 100 * r['share'], len(r['never']))]
    L.append('%-8s %12s %9s %7s' % ('routine', 'instructions', 'executed', 'share'))
    for x in r['routines']:
        L.append('%06x   %12d %9d %6.1f%%' % (x['addr'], x['instructions'], x['executed'], 100 * x['share']))
    return '\n'.join(L)
