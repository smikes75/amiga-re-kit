"""Translated routines against the original, call by call (from the Alien Breed II project): a trace
with breakpoints on the call sites (``jsr abs.l``) and on the addresses after them gives pairs of
records (before the call, after the return). For every pair the RAM and registers of the first
record go into the recomp driver (``--main``), the routine runs, and its RAM and registers are
compared with the second record. Pairs an interrupt handler fell into are left out.

    arek verify calls TRACE.vtr DRIVER IMAGE.bin --base B [--vbl ADDR] [--max N] [--json OUT]
"""
import json
import os
import struct
import subprocess
import tempfile

from ..headless import trace


def call_pairs(records, image, base=0, vbl=None, max_per=3):
    """``[(target, record_before, record_after)]`` for consecutive records where the first sits on a
    ``jsr abs.l`` and the second on the instruction after it; at most ``max_per`` per target."""
    out, count = [], {}
    recs = list(records)
    for r, n in zip(recs, recs[1:]):
        pc = r['pc']
        if vbl is not None and (pc == vbl or n['pc'] == vbl):
            continue
        if image[pc - base:pc - base + 2] != b'\x4e\xb9':
            continue
        tgt = struct.unpack('>I', image[pc - base + 2:pc - base + 6])[0]
        if n['pc'] != pc + 6 or count.get(tgt, 0) >= max_per:
            continue
        count[tgt] = count.get(tgt, 0) + 1
        out.append((tgt, r, n))
    return out


def run_call(driver, tgt, before, after, chip_size=0x80000, timeout=5):
    """One pair through the driver. Returns ``{'frame', 'chip_diff', 'slow_diff', 'regs_equal', 'first', 'notes'}``
    or ``{'frame', 'error'}``."""
    tmp = tempfile.mkdtemp(prefix='arek-verify')
    chip = before['ranges'].get(0)
    if chip is None:
        return {'frame': before['frame'], 'error': 'the record carries no chip RAM range from 0'}
    slow_base = next((b for b in before['ranges'] if b >= chip_size), None)
    c_in, regs, c_out, log = (os.path.join(tmp, n) for n in ('c.bin', 'regs.txt', 'co.bin', 'log.txt'))
    with open(c_in, 'wb') as f:
        f.write(bytes(chip).ljust(chip_size, b'\0')[:chip_size])
    flags = before['sr']
    with open(regs, 'w') as f:
        f.write(' '.join('%x' % v for v in before['d']) + '\n' + ' '.join('%x' % v for v in before['a']) + '\n')
        f.write('%d %d %d %d %d\n' % ((flags >> 4) & 1, (flags >> 3) & 1, (flags >> 2) & 1, (flags >> 1) & 1, flags & 1))
        f.write('f_%06x %x\n' % (tgt, before['pc'] + 6))
    args = [driver, c_in, regs, c_out, log]
    if slow_base is not None:
        s_in, s_out = os.path.join(tmp, 's.bin'), os.path.join(tmp, 'so.bin')
        with open(s_in, 'wb') as f:
            f.write(bytes(before['ranges'][slow_base]))
        args += [s_in, s_out]
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {'frame': before['frame'], 'error': 'timeout %d s (waiting for hardware?)' % timeout}
    if p.returncode:
        return {'frame': before['frame'], 'error': p.stderr.strip()[:200] or 'rc %d' % p.returncode}
    with open(c_out, 'rb') as f:
        co = f.read()
    ec = after['ranges'].get(0, b'')
    dc = [i for i in range(min(len(co), len(ec))) if co[i] != ec[i]]
    ds = []
    if slow_base is not None and slow_base in after['ranges']:
        with open(s_out, 'rb') as f:
            so = f.read()
        es = after['ranges'][slow_base]
        ds = [slow_base + i for i in range(min(len(so), len(es))) if so[i] != es[i]]
    with open(log) as f:
        rows = f.read().split('\n')
    regs_ok = [int(x, 16) for x in rows[:16]] == list(after['d']) + list(after['a'])
    return {'frame': before['frame'], 'chip_diff': len(dc), 'slow_diff': len(ds), 'regs_equal': regs_ok,
            'first': ['$%x' % i for i in dc[:3]] + ['$%x' % i for i in ds[:3]],
            'notes': [l for l in rows if l.startswith(('note', 'hwreg', 'oob', 'exit'))][:6]}


def calls(records, driver, image, base=0, vbl=None, max_per=3, chip_size=0x80000):
    """Every call pair through the driver: ``{target: [results]}``."""
    out = {}
    for tgt, r, n in call_pairs(records, image, base, vbl, max_per):
        out.setdefault(tgt, []).append(run_call(driver, tgt, r, n, chip_size))
    return out


def format_calls(res):
    L = []
    for t, lst in sorted(res.items()):
        for x in lst:
            L.append('f_%06x fr %5d  %s' % (t, x['frame'], x.get('error') or 'chip %d slow %d regs %s %s %s' % (
                x['chip_diff'], x['slow_diff'], x['regs_equal'], x['first'], x['notes'])))
    ok = sum(1 for lst in res.values() for x in lst if not x.get('error') and not x['chip_diff'] and not x['slow_diff'] and x['regs_equal'])
    n = sum(len(lst) for lst in res.values())
    L.append('%d of %d calls equal (RAM and registers)' % (ok, n))
    return '\n'.join(L)


def write_json(res, path):
    with open(path, 'w') as f:
        json.dump({'%x' % t: v for t, v in res.items()}, f, indent=1)
