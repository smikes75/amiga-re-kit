"""Verification contracts: compare captured machine states, byte for byte.

A *capture* is a folder written by ``arek bpstate`` (``cpu.json`` + RAM
dumps). A *contract* says which registers and memory ranges a routine may
change, and the check reports every difference outside that - the honest
measurement that replaces "looks the same in the emulator".

Typical use::

    before = load('build/cap/draw_before')      # breakpoint at routine entry
    after  = load('build/cap/draw_after')       # breakpoint at its RTS
    mine   = run_recompiled(before['ram'])      # C from arek recomp
    report = compare(after['ram'], mine, ranges=[(0x60000, 0x70000)])

``compare`` returns a list of differing runs ``(start, end, expected, got)``
truncated to ``max_runs``; an empty list is the only pass.
"""
import json
from pathlib import Path


def load(folder):
    folder = Path(folder)
    meta = json.loads((folder / 'cpu.json').read_text())
    meta['ram'] = (folder / ('ram_%x_%d.bin' % (meta['breakpoint'], meta['skip']))).read_bytes()
    for r in meta.get('regions', []):
        r['data'] = (folder / r['file']).read_bytes()
    return meta


def diff_runs(a, b, base=0, max_runs=64, max_show=16):
    """Runs of differing bytes between two equal-length buffers."""
    if len(a) != len(b):
        raise ValueError('length mismatch: %d vs %d' % (len(a), len(b)))
    runs, i, n = [], 0, len(a)
    while i < n and len(runs) < max_runs:
        if a[i] == b[i]:
            i += 1
            continue
        j = i
        while j < n and a[j] != b[j]:
            j += 1
        runs.append((base + i, base + j, a[i:min(j, i + max_show)].hex(), b[i:min(j, i + max_show)].hex()))
        i = j
    return runs


def compare(expected, got, ranges=None, base=0, **kw):
    """Compare ``got`` with ``expected`` inside ``ranges`` (absolute
    addresses; whole buffer when None)."""
    if ranges is None:
        return diff_runs(expected, got, base, **kw)
    out = []
    for lo, hi in ranges:
        a = expected[lo - base:hi - base]
        b = got[lo - base:hi - base]
        out += diff_runs(a, b, lo, **kw)
    return out


def diff_regs(before, after, allow=()):
    """Registers that changed between two captures, minus the allowed ones."""
    changed = {}
    for i in range(8):
        for k in 'da':
            name = '%s%d' % (k, i)
            if before[k][i] != after[k][i] and name not in allow:
                changed[name] = (before[k][i], after[k][i])
    return changed


def untouched(before, after, ranges, base=0):
    """Assert the routine did NOT write inside ``ranges`` (returns violations)."""
    return compare(before, after, ranges, base)


def format_runs(runs):
    if not runs:
        return 'OK - no differences'
    L = ['%d differing run(s):' % len(runs)]
    for s, e, x, g in runs:
        L.append('  %06x-%06x (%d B)  expected %s  got %s' % (s, e, e - s, x, g))
    return '\n'.join(L)
