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
``vamiga-inputs-reglog-899da5d.patch`` (on top of trace-ranges)
    ``VAHL_INPUTS=<file>``: input per frame - line k holds the keys of frame k
    (``R L U D F S`` = right, left, up, down, fire on joystick 2, space), applied
    at the first breakpoint hit of each frame with v < 100 (put the breakpoint in
    the VBL handler). Frame exact; RetroShell ``wait 1 frames`` waits 1.4 frames
    on average. ``VAHL_REGLOG``: every write to DMACON, INTENA, INTREQ, ADKCON and
    AUD0-3 (``read_reglog``). ``VAHL_AUDLOG``: every sample Paula outputs (``read_audlog``).
    ``VAHL_TRACE_SKIP=N`` / ``VAHL_TRACE_FROM_FRAME=F``: no records for the
    first N hits / before frame F. A range ``start:lenh`` records an FNV-1a 64 hash
    instead of the bytes (``rec['hashes']``).

Record layout (little endian, as the host writes it)::

    24 x u32: magic, address, hit counter, Agnus frame, v, h, SR,
              D0..D7, A0..A7, n   (n = RAM length for VTR1, range count otherwise)
    VTW2 only: u32 PC of the accessing instruction
    VTR1: n bytes of RAM from address 0
    VTR2/VTW2: n x (u32 start, u32 length, length bytes); length with bit 31 set:
               8 bytes FNV-1a 64 of the range instead of the bytes

The patch only reads (``spypeek``); a trace never changes the run it records.
"""
import os
import struct
import zlib

VTR1, VTR2, VTW2 = 0x31525456, 0x32525456, 0x32575456
KINDS = {VTR1: 'VTR1', VTR2: 'VTR2', VTW2: 'VTW2'}
MAGIC = {name: magic for magic, name in KINDS.items()}
PACKED = b'VTP1'                        # pack(): u32 count, then zlib of records XORed with the previous one
HEAD = struct.Struct('<24I')


class TraceError(ValueError):
    pass


def records(src):
    """Yield one dict per record from a trace file path or bytes:
    ``kind, addr, hit, frame, v, h, sr, d[8], a[8], pc, ranges{start: bytes}``,
    ``hashes{start: (length, fnv1a64)}`` for hashed ranges.
    ``pc`` is the accessing instruction for watchpoint records (VTW2), the
    breakpoint address otherwise. A packed file (``pack``) is read the same way."""
    data = src if isinstance(src, (bytes, bytearray, memoryview)) else open(src, 'rb').read()
    packed = bytes(data[:4]) == PACKED
    if packed:
        data = zlib.decompress(bytes(data[8:]))
    data = memoryview(data)
    pos, n = 0, len(data)
    prev = {}

    def bytes_of(start, ln, what):
        raw = bytes(take(ln, what))
        if packed and (start, ln) in prev:
            raw = _xor(raw, prev[(start, ln)])
        prev[(start, ln)] = raw
        return raw

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
               'sr': h[6], 'd': list(h[7:15]), 'a': list(h[15:23]), 'pc': h[1], 'ranges': {},
               'hashes': {}}
        if h[0] == VTW2:
            rec['pc'] = struct.unpack('<I', take(4, 'watchpoint pc'))[0]
        if h[0] == VTR1:
            rec['ranges'][0] = bytes_of(0, h[23], 'RAM')
        else:
            for _ in range(h[23]):
                start, ln = struct.unpack('<II', take(8, 'range header'))
                if ln & 0x80000000:
                    rec['hashes'][start] = (ln & 0x7fffffff, struct.unpack('<Q', take(8, 'range hash'))[0])
                else:
                    rec['ranges'][start] = bytes_of(start, ln, 'range data')
        yield rec


def _xor(a, b):
    return (int.from_bytes(a, 'big') ^ int.from_bytes(b, 'big')).to_bytes(len(a), 'big')


def encode(rec, prev=None):
    """One record (a dict as ``records`` yields) as bytes. A native engine that writes the same
    layout (docs/HEADLESS.md) can be compared with the original by ``arek trace compare``.
    ``prev``: {(start, length): bytes} of the previous record - XOR against it (``pack``)."""
    kind = rec.get('kind', 'VTR2')
    ranges, hashes = rec.get('ranges', {}), rec.get('hashes', {})
    n = len(ranges[0]) if kind == 'VTR1' else len(ranges) + len(hashes)
    d, a = list(rec.get('d', [0] * 8)), list(rec.get('a', [0] * 8))
    out = [HEAD.pack(MAGIC[kind], rec.get('addr', 0), rec.get('hit', 0), rec.get('frame', 0), rec.get('v', 0),
                     rec.get('h', 0), rec.get('sr', 0), *d, *a, n)]
    if kind == 'VTW2':
        out.append(struct.pack('<I', rec.get('pc', 0)))

    def body(start, data):
        if prev is not None:
            key = (start, len(data))
            old, prev[key] = prev.get(key), data
            return _xor(data, old) if old is not None else data
        return data
    if kind == 'VTR1':
        out.append(body(0, ranges[0]))
        return b''.join(out)
    for start, data in ranges.items():
        out.append(struct.pack('<II', start, len(data)) + body(start, data))
    for start, (ln, hv) in hashes.items():
        out.append(struct.pack('<IIQ', start, ln | 0x80000000, hv))
    return b''.join(out)


def pack(src, out):
    """Write the trace ``src`` packed: every range XORed with the same range of the previous
    record, the whole zlib-compressed (most RAM does not change between hits). ``records``
    reads it back unchanged. Returns (records, bytes before, bytes after)."""
    prev, parts, n = {}, [], 0
    for rec in records(src):
        parts.append(encode(rec, prev))
        n += 1
    raw = b''.join(parts)
    blob = PACKED + struct.pack('<I', n) + zlib.compress(raw, 6)
    with open(out, 'wb') as f:
        f.write(blob)
    before = os.path.getsize(src) if not isinstance(src, (bytes, bytearray, memoryview)) else len(src)
    return n, before, len(blob)


def read(rec, addr, fmt='H'):
    """Big-endian value at ``addr`` from the record's RAM ranges (``struct``
    format letter, e.g. 'B', 'h', 'H', 'I'), or None when not captured."""
    k = struct.calcsize('>' + fmt)
    for start, data in rec['ranges'].items():
        if start <= addr and addr + k <= start + len(data):
            return struct.unpack_from('>' + fmt, data, addr - start)[0]
    return None


def fnv1a64(data):
    """The hash a ``start:lenh`` range records."""
    h = 0xcbf29ce484222325
    for b in data:
        h = ((h ^ b) * 0x100000001b3) & 0xffffffffffffffff
    return h


def parse_range(spec):
    """'start:len' or 'start:lenh' (hex) -> (start, length, hashed)."""
    start, _, ln = spec.partition(':')
    hashed = ln.endswith('h')
    return int(start, 16), int(ln.rstrip('h'), 16), hashed


def ranges_arg(ranges):
    """[(start, length[, hashed]), ...] -> the ``VAHL_TRACE_RANGES`` string."""
    return ','.join('%x:%x%s' % (r[0], r[1], 'h' if len(r) > 2 and r[2] else '') for r in ranges)


INPUT_KEYS = set('RLUDFS')


def check_inputs(path):
    """An input file: one line per frame, only the letters R L U D F S (any order,
    empty = nothing held). Returns the number of frames."""
    n = 0
    with open(path) as f:
        for n, line in enumerate(f, 1):
            bad = set(line.strip()) - INPUT_KEYS
            if bad:
                raise TraceError('%s line %d: %r - only R L U D F S (one line per frame)'
                                 % (path, n, ''.join(sorted(bad))))
    return n


def env(path, ranges=None, length=None, inputs=None, reglog=None, audlog=None, skip=None,
        from_frame=None):
    """Environment for a traced run of the patched VAHeadless."""
    e = {'VAHL_TRACE': str(path)}
    if ranges:
        e['VAHL_TRACE_RANGES'] = ranges_arg(ranges)
    if length:
        e['VAHL_TRACE_LEN'] = str(length)
    if inputs:
        check_inputs(inputs)
        e['VAHL_INPUTS'] = os.path.abspath(inputs)
    if reglog:
        e['VAHL_REGLOG'] = os.path.abspath(reglog)
    if audlog:
        e['VAHL_AUDLOG'] = os.path.abspath(audlog)
    if skip:
        e['VAHL_TRACE_SKIP'] = str(skip)
    if from_frame is not None:
        e['VAHL_TRACE_FROM_FRAME'] = str(from_frame)
    return e


REG_NAMES = {0x096: 'DMACON', 0x09a: 'INTENA', 0x09c: 'INTREQ', 0x09e: 'ADKCON'}
for _ch in range(4):
    for _off, _n in ((0, 'LCH'), (2, 'LCL'), (4, 'LEN'), (6, 'PER'), (8, 'VOL'), (10, 'DAT')):
        REG_NAMES[0x0a0 + 16 * _ch + _off] = 'AUD%d%s' % (_ch, _n)


def read_reglog(src):
    """Records of a ``VAHL_REGLOG`` file (16 bytes each): ``frame, v, h, reg, name, value,
    pc, agnus`` (agnus = written by DMA, not by the CPU)."""
    data = src if isinstance(src, (bytes, bytearray)) else open(src, 'rb').read()
    if len(data) % 16:
        raise TraceError('reglog length %d is not a multiple of 16' % len(data))
    out = []
    for frame, beam, rv, pc in struct.iter_unpack('<4I', data):
        reg = rv >> 16
        out.append({'frame': frame, 'v': beam >> 16, 'h': beam & 0xffff, 'reg': reg,
                    'name': REG_NAMES.get(reg, '%03x' % reg), 'value': rv & 0xffff,
                    'pc': pc & 0xffffff, 'agnus': bool(pc >> 24)})
    return out


def read_audlog(src):
    """Samples of a ``VAHL_AUDLOG`` file (12 bytes each): ``(frame, v, h, sample*volume, channel)``."""
    data = src if isinstance(src, (bytes, bytearray)) else open(src, 'rb').read()
    if len(data) % 12:
        raise TraceError('audlog length %d is not a multiple of 12' % len(data))
    return [(frame, beam >> 16, beam & 0xffff, struct.unpack('<h', struct.pack('<H', sc >> 16))[0], sc & 0xffff)
            for frame, beam, sc in struct.iter_unpack('<3I', data)]


def arm_events(t, breaks=(), watches=()):
    """RetroShell events that arm the trace at second ``t``: breakpoints and
    watchpoints with ignore count 0 (the patch records instead of stopping)."""
    ev = [(t, 'debugger')]
    ev += [(t, 'break at $%x 0' % b) for b in breaks]
    ev += [(t, 'watch at $%x 0' % w) for w in watches]
    ev.append((t, 'commander'))
    return ev


PATCH_OF = {'VAHL_TRACE': 'vamiga-trace*.patch', 'VAHL_TRACE_RANGES': 'vamiga-trace-ranges-899da5d.patch',
            'VAHL_INPUTS': 'vamiga-inputs-reglog-899da5d.patch', 'VAHL_REGLOG': 'vamiga-inputs-reglog-899da5d.patch',
            'VAHL_AUDLOG': 'vamiga-inputs-reglog-899da5d.patch', 'VAHL_TRACE_SKIP': 'vamiga-inputs-reglog-899da5d.patch',
            'VAHL_TRACE_FROM_FRAME': 'vamiga-inputs-reglog-899da5d.patch'}


def require_patch(vahl, variables):
    """The binary must know every environment variable the run relies on; a build
    without the patch ignores it silently (or stops at the first breakpoint and hangs)."""
    with open(vahl, 'rb') as f:
        blob = f.read()
    missing = [v for v in variables if v.encode() not in blob]
    if missing:
        raise TraceError('%s was not built with %s (it does not know %s) - see docs/HEADLESS.md'
                         % (vahl, ', '.join(sorted({PATCH_OF[v] for v in missing})), ', '.join(missing)))


def capture(conf, out, events, t_arm, t_end, breaks=(), watches=(), ranges=None, adf=None,
            timeout=1200, setup=(), inputs=None, reglog=None, audlog=None, skip=None, from_frame=None):
    """Run the original with ``events`` (``[(second, retroshell command)]``),
    arm the trace at ``t_arm`` and stop at ``t_end``. Writes ``out`` (the
    trace), ``out + '.retrosh'`` (the script) and ``out + '.log'``; returns
    the number of records."""
    from . import shot
    if not breaks and not watches:
        raise TraceError('nothing to trace: give breakpoints and/or watchpoints')
    adf = shot.check_disk(conf, adf or conf.get('ADF1'))
    e = env(out, ranges, inputs=inputs, reglog=reglog, audlog=audlog, skip=skip, from_frame=from_frame)
    needed = [k for k in e if k != 'VAHL_TRACE_LEN']
    if any(len(r) > 2 and r[2] for r in ranges or ()):
        needed.append('VAHL_TRACE_SKIP')            # hashed ranges came with the inputs/reglog patch
    if conf.get('VAHL') and os.path.isfile(conf['VAHL']):
        require_patch(conf['VAHL'], needed)
    if os.path.exists(out):
        os.unlink(out)
    script = shot.build_script(conf, adf, list(events) + arm_events(t_arm, breaks, watches),
                               t_end, out + '.png', setup)
    with open(out + '.retrosh', 'w') as f:
        f.write(script)
    log = shot.run_script(conf, script, capture=True, timeout=timeout, env=e)
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
               'ranges': {('%x' % s): len(b) for s, b in r['ranges'].items()},
               'hashes': {('%x' % s): '%016x' % hv for s, (_, hv) in r['hashes'].items()}}
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
