"""Continuous trace of the original: every breakpoint (or watchpoint) hit
writes one record and the emulation keeps running.

Needs a VAHeadless built with one of the trace patches:

``vamiga-trace.patch`` (c59425d)
    ``VAHL_TRACE=<file>``: per breakpoint hit a ``VTR1`` record =
    header + chip RAM (``VAHL_TRACE_LEN`` bytes, default 512 KB).
``vamiga-trace-ranges-899da5d.patch`` (899da5d, on top of the headless patch)
    as above, plus ``VAHL_TRACE_RANGES=start:len,...`` (hex) -> ``VTR2``
    records holding only those ranges (chip, slow RAM, even custom
    registers or CIA through ``spypeek``), and watchpoints -> ``VTW2``
    records that also carry the PC of the instruction that touched the
    address.

Record layout (little endian, as the host writes it)::

    24 x u32: magic, address, hit counter, Agnus frame, v, h, SR,
              D0..D7, A0..A7, n   (n = RAM length for VTR1, range count otherwise)
    VTW2 only: u32 PC of the accessing instruction
    VTR1: n bytes of RAM from address 0
    VTR2/VTW2: n x (u32 start, u32 length, length bytes)

The patch only reads (``spypeek``); a trace never changes the run it records.
"""
import os
import struct

VTR1, VTR2, VTW2 = 0x31525456, 0x32525456, 0x32575456
KINDS = {VTR1: 'VTR1', VTR2: 'VTR2', VTW2: 'VTW2'}
HEAD = struct.Struct('<24I')


class TraceError(ValueError):
    pass


def records(src):
    """Yield one dict per record from a trace file path or bytes:
    ``kind, addr, hit, frame, v, h, sr, d[8], a[8], pc, ranges{start: bytes}``.
    ``pc`` is the accessing instruction for watchpoint records (VTW2), the
    breakpoint address otherwise."""
    data = src if isinstance(src, (bytes, bytearray, memoryview)) else open(src, 'rb').read()
    data = memoryview(data)
    pos, n = 0, len(data)

    def take(k, what):
        nonlocal pos
        if pos + k > n:
            raise TraceError('truncated %s at offset %d (need %d bytes, %d left)' % (what, pos, k, n - pos))
        out = data[pos:pos + k]
        pos += k
        return out

    while pos < n:
        h = HEAD.unpack(take(HEAD.size, 'header'))
        if h[0] not in KINDS:
            raise TraceError('unknown record magic %08x at offset %d' % (h[0], pos - HEAD.size))
        rec = {'kind': KINDS[h[0]], 'addr': h[1], 'hit': h[2], 'frame': h[3], 'v': h[4], 'h': h[5],
               'sr': h[6], 'd': list(h[7:15]), 'a': list(h[15:23]), 'pc': h[1], 'ranges': {}}
        if h[0] == VTW2:
            rec['pc'] = struct.unpack('<I', take(4, 'watchpoint pc'))[0]
        if h[0] == VTR1:
            rec['ranges'][0] = bytes(take(h[23], 'RAM'))
        else:
            for _ in range(h[23]):
                start, ln = struct.unpack('<II', take(8, 'range header'))
                rec['ranges'][start] = bytes(take(ln, 'range data'))
        yield rec


def read(rec, addr, fmt='H'):
    """Big-endian value at ``addr`` from the record's RAM ranges (``struct``
    format letter, e.g. 'B', 'h', 'H', 'I'), or None when not captured."""
    k = struct.calcsize('>' + fmt)
    for start, data in rec['ranges'].items():
        if start <= addr and addr + k <= start + len(data):
            return struct.unpack_from('>' + fmt, data, addr - start)[0]
    return None


def ranges_arg(ranges):
    """[(start, length), ...] -> the ``VAHL_TRACE_RANGES`` string."""
    return ','.join('%x:%x' % (s, n) for s, n in ranges)


def env(path, ranges=None, length=None):
    """Environment for a traced run of the patched VAHeadless."""
    e = {'VAHL_TRACE': str(path)}
    if ranges:
        e['VAHL_TRACE_RANGES'] = ranges_arg(ranges)
    if length:
        e['VAHL_TRACE_LEN'] = str(length)
    return e


def arm_events(t, breaks=(), watches=()):
    """RetroShell events that arm the trace at second ``t``: breakpoints and
    watchpoints with ignore count 0 (the patch records instead of stopping)."""
    ev = [(t, 'debugger')]
    ev += [(t, 'break at $%x 0' % b) for b in breaks]
    ev += [(t, 'watch at $%x 0' % w) for w in watches]
    ev.append((t, 'commander'))
    return ev


def capture(conf, out, events, t_arm, t_end, breaks=(), watches=(), ranges=None, adf=None,
            timeout=1200, setup=()):
    """Run the original with ``events`` (``[(second, retroshell command)]``),
    arm the trace at ``t_arm`` and stop at ``t_end``. Writes ``out`` (the
    trace), ``out + '.retrosh'`` (the script) and ``out + '.log'``; returns
    the number of records."""
    from . import config, shot
    if not breaks and not watches:
        raise TraceError('nothing to trace: give breakpoints and/or watchpoints')
    adf = adf or config.require(conf, 'ADF1')['ADF1']
    if os.path.exists(out):
        os.unlink(out)
    script = shot.build_script(conf, adf, list(events) + arm_events(t_arm, breaks, watches),
                               t_end, out + '.png', setup)
    with open(out + '.retrosh', 'w') as f:
        f.write(script)
    log = shot.run_script(conf, script, capture=True, env=env(out, ranges), timeout=timeout)
    with open(out + '.log', 'w') as f:
        f.write(log)
    if not os.path.exists(out):
        raise TraceError('no trace written - is VAHL a build with a trace patch? (see %s.log)' % out)
    return sum(1 for _ in records(out))


def summary(src, fields=None):
    """One row per record: hit, frame, beam, kind, pc, and ``fields``
    (``{name: (addr, fmt)}``) read from the captured ranges."""
    rows = []
    for r in records(src):
        row = {'hit': r['hit'], 'frame': r['frame'], 'v': r['v'], 'h': r['h'], 'kind': r['kind'],
               'addr': r['addr'], 'pc': r['pc'], 'sr': r['sr'], 'd': r['d'], 'a': r['a'],
               'ranges': {('%x' % s): len(b) for s, b in r['ranges'].items()}}
        for name, (addr, fmt) in (fields or {}).items():
            row[name] = read(r, addr, fmt)
        rows.append(row)
    return rows


def format_summary(rows, fields=()):
    L = ['%d records' % len(rows)]
    for r in rows:
        extra = ' '.join('%s=%s' % (k, r[k]) for k in fields)
        L.append('%5d  frame %6d  beam %3d,%3d  %s  %06x  pc %06x  %s' % (
            r['hit'], r['frame'], r['v'], r['h'], r['kind'], r['addr'], r['pc'], extra))
    return '\n'.join(L)
