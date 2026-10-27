"""The Amiga bus per DMA slot, for recompiled games (``arek_bus.h``, ``arek_bus.c``,
``arek_bus_vamiga.c``): who owns each slot of each line (refresh, audio, bitplanes, sprites,
copper, blitter, CPU), the blitter cycle by cycle, the CPU by the bus accesses of its
instructions. It decides what a frame boundary cannot: on which instruction an interrupt lands,
when a blit ends, whether the original overran the frame. Extracted from the Alien Breed project
(docs/BUS.md: API, calibration, geometry, limits); ``arek_bus_vamiga.c`` is derived from vAmiga
(Dirk W. Hoffmann, MPL-2.0), the rest is MIT like the kit.

    arek bus copy DIR          # the C files into a project (a translation includes arek_bus_glue.h)
    arek selftest bus          # the model against VAHeadless's bus log on a synthetic program
    arek selftest audio        # the Paula model (arek_bus_paula.h: audio DMA slots, output bytes) against the logs
    arek recomp --bus-table    # per translated instruction: words, extra accesses, internal cycles before

The host side: ``arek_bus_glue.h`` turns the runtime's hooks (``-DTICK_HOOK -DBUS_HOOK``) into
model calls; ``replay`` runs the blitter of the model against a recorded bus log (no game data
needed: the log of any run, or the self-test's).
"""
import collections
import os
import shutil
import struct
import subprocess
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = ('arek_bus.h', 'arek_bus.c', 'arek_bus_vamiga.c', 'arek_bus_glue.h', 'arek_bus_replay.c', 'arek_bus_check.c',
         'arek_bus_paula.h', 'arek_bus_paula_check.c')


def copy(dest):
    """Copy the model's sources into ``dest`` (a project's lib folder). Returns the paths."""
    os.makedirs(dest, exist_ok=True)
    out = []
    for name in FILES:
        shutil.copy(os.path.join(HERE, name), os.path.join(dest, name))
        out.append(os.path.join(dest, name))
    return out


def compiler():
    return shutil.which('cc') or shutil.which('gcc') or shutil.which('clang')


def compile_replay(out=None, cc=None):
    """Build ``arek_bus_replay`` (the blitter of the model against a bus log). Returns the executable."""
    cc = cc or compiler()
    if not cc:
        raise RuntimeError('no C compiler (cc, gcc or clang) for the bus model')
    out = out or os.path.join(tempfile.mkdtemp(prefix='arek-bus'), 'arek_bus_replay')
    subprocess.run([cc, '-O2', '-I', HERE, '-o', out, os.path.join(HERE, 'arek_bus_replay.c'),
                    os.path.join(HERE, 'arek_bus.c'), os.path.join(HERE, 'arek_bus_vamiga.c')], check=True)
    return out


def compile_check(out=None, cc=None):
    """Build ``arek_bus_check`` (the model's fixed DMA map against a bus log). Returns the executable."""
    cc = cc or compiler()
    if not cc:
        raise RuntimeError('no C compiler (cc, gcc or clang) for the bus model')
    out = out or os.path.join(tempfile.mkdtemp(prefix='arek-bus'), 'arek_bus_check')
    subprocess.run([cc, '-O2', '-I', HERE, '-o', out, os.path.join(HERE, 'arek_bus_check.c'),
                    os.path.join(HERE, 'arek_bus.c'), os.path.join(HERE, 'arek_bus_vamiga.c')], check=True)
    return out


def buslog_to_bin(log, out, hpos=227, lines=None):
    """A bus log (``trace.read_buslog`` result or path) as the replay's binary (ABBL): frame maps
    ``nframes x lines x hpos`` (owner per slot, 0xFF = line missing) and the blits. ``lines`` as
    in the log when not given. Returns ``{'frame0', 'frames', 'blits', 'lines', 'hpos'}``."""
    from ..headless import trace
    if not isinstance(log, dict):
        log = trace.read_buslog(log)
    rows = log['lines']
    frames = sorted({f for f, v in rows})
    if not frames:
        raise ValueError('the bus log has no lines')
    if lines is None:
        lines = max(v for f, v in rows) + 1
    f0, nf = frames[0], frames[-1] - frames[0] + 1
    with open(out, 'wb') as o:
        o.write(b'ABBL' + struct.pack('<5I', hpos, lines, f0, nf, len(log['blits'])))
        for f in range(f0, f0 + nf):
            for v in range(lines):
                row = rows.get((f, v))
                if row is None:
                    o.write(b'\xff' * hpos)
                else:
                    o.write(bytes(row[:hpos]) + bytes(max(0, hpos - len(row))))
        for b in log['blits']:
            e = b['end']
            o.write(struct.pack('<I6HI2H8x', b['frame'], b['v'], b['h'], b['bltcon0'], b['bltcon1'], b['width'], b['height'],
                                e[0] if e else 0xffffffff, e[1] if e else 0, e[2] if e else 0))
    return {'frame0': f0, 'frames': nf, 'blits': len(log['blits']), 'lines': lines, 'hpos': hpos}


def replay(abbl, exe=None):
    """Run the blitter replay on an ABBL file: ``{'blits', 'exact', 'slots_ok', 'slots_bad', 'ok', 'text'}``."""
    exe = exe or compile_replay()
    r = subprocess.run([exe, abbl], capture_output=True, text=True)
    text = r.stdout + r.stderr
    out = {'ok': r.returncode == 0, 'text': text.strip(), 'blits': 0, 'exact': 0, 'slots_ok': 0, 'slots_bad': 0}
    import re
    m = re.search(r'blitu (\d+) .*?konec v tomtez taktu (\d+)', text)
    if m:
        out['blits'], out['exact'] = int(m.group(1)), int(m.group(2))
    m = re.search(r'shodne s logem (\d+), neshodne (\d+)', text)
    if m:
        out['slots_ok'], out['slots_bad'] = int(m.group(1)), int(m.group(2))
    return out


def compile_paula_check(out=None, cc=None):
    """Build ``arek_bus_paula_check`` (the Paula model against a bus log, a register log and an audio log). Returns the executable."""
    cc = cc or compiler()
    if not cc:
        raise RuntimeError('no C compiler (cc, gcc or clang) for the bus model')
    out = out or os.path.join(tempfile.mkdtemp(prefix='arek-bus'), 'arek_bus_paula_check')
    subprocess.run([cc, '-O2', '-I', HERE, '-o', out, os.path.join(HERE, 'arek_bus_paula_check.c'),
                    os.path.join(HERE, 'arek_bus.c'), os.path.join(HERE, 'arek_bus_vamiga.c')], check=True)
    return out


def paula_writes(records, frame0, lines, hpos=227):
    """``(t, off, value)`` of the writes to DMACON, INTREQ and the AUDx registers in ``trace.read_reglog`` records
    (CPU and Copper alike), ``t`` in CCK relative to slot 0 of frame ``frame0`` (negative before it), sorted."""
    out = []
    for r in records:
        if r['reg'] in (0x096, 0x09c) or 0x0a0 <= r['reg'] < 0x0e0:
            out.append(((r['frame'] - frame0) * lines * hpos + r['v'] * hpos + r['h'], r['reg'], r['value']))
    out.sort(key=lambda x: x[0])
    return out


def paula_samples(samples, frame0, lines, hpos=227):
    """``(t, channel, value)`` of ``trace.read_audlog`` samples, ``t`` as in ``paula_writes``."""
    return sorted(((frame - frame0) * lines * hpos + v * hpos + h, ch, value) for frame, v, h, value, ch in samples)


def paula_check(abbl, writes, samples=None, from_frame=0, exe=None, ram=None, irqs=False):
    """Run ``arek_bus_paula_check`` (``ram``: the chip RAM image the samples are fetched from, path or bytes):
    ``{'agree', 'disagree', 'slots': {ch: {'log', 'model', 'agree', 'only_log', 'only_model'}},
    'samples': {ch: {'log', 'model', 'exact', 'near'}}, 'text', 'rc'}``; ``irqs``: also ``'irqs'`` = the model's
    interrupt requests ``[(ch, t)]`` (t in CCK from the log's first frame)."""
    import re
    exe = exe or compile_paula_check()
    d = os.path.dirname(os.path.abspath(abbl))
    env = dict(os.environ)
    if irqs:
        env['AREK_PAULA_IRQ'] = os.path.join(d, 'paula_irqs.txt')
    wpath, spath = os.path.join(d, 'paula_writes.txt'), os.path.join(d, 'paula_samples.txt')
    with open(wpath, 'w') as f:
        for t, off, v in writes:
            f.write('%.1f %x %x\n' % (t, off, v))
    args = [exe, abbl, wpath, '-', str(from_frame)]
    if samples is not None:
        with open(spath, 'w') as f:
            for t, ch, v in samples:
                f.write('%.1f %d %d\n' % (t, ch, v))
        args[3] = spath
    if ram is not None:
        if not isinstance(ram, str):
            rpath = os.path.join(d, 'paula_ram.bin')
            with open(rpath, 'wb') as f:
                f.write(ram)
            ram = rpath
        args.append(ram)
    r = subprocess.run(args, capture_output=True, text=True, env=env)
    out = {'slots': {}, 'samples': {}, 'text': r.stdout + r.stderr, 'rc': r.returncode, 'agree': 0, 'disagree': -1}
    if irqs:
        with open(env['AREK_PAULA_IRQ']) as f:
            out['irqs'] = [(int(a), float(b)) for a, b in (ln.split() for ln in f if ln.strip())]
    for m in re.finditer(r'slots ch(\d): log (\d+) model (\d+) agree (\d+) only-log (\d+) only-model (\d+)', r.stdout):
        out['slots'][int(m.group(1))] = dict(zip(('log', 'model', 'agree', 'only_log', 'only_model'), map(int, m.groups()[1:])))
    for m in re.finditer(r'samples ch(\d): log (\d+) model (\d+) exact (\d+) near (\d+)', r.stdout):
        out['samples'][int(m.group(1))] = dict(zip(('log', 'model', 'exact', 'near'), map(int, m.groups()[1:])))
    m = re.search(r'audio slots: agree (\d+), disagree (\d+)', r.stdout)
    if m:
        out['agree'], out['disagree'] = int(m.group(1)), int(m.group(2))
    return out


OWNER_LETTERS = '.CRDAAAA12345678SSSSSSSScbx'


def own_frames(data, frame0, hpos=227, lines=313):
    """The slot maps a host wrote with ``--own`` (int64 frame index + lines * hpos owners per frame): ``{frame: bytes}``."""
    data = data if isinstance(data, (bytes, bytearray)) else open(data, 'rb').read()
    frames, p, n = {}, 0, lines * hpos
    while p + 8 + n <= len(data):
        f = struct.unpack('<q', data[p:p + 8])[0]
        frames[frame0 + f] = bytes(data[p + 8:p + 8 + n])
        p += 8 + n
    return frames


def own_compare(log, frames, hpos=227, lines=313):
    """A host's slot maps against a bus log (``trace.read_buslog``), frame by frame: owner counts of both sides,
    the lines whose blitter or CPU slots differ, and the first DMA difference (CPU-vs-free differences are a
    consequence of shifted time; the DMA ones are the model's). Returns rows ``{'frame', 'counts': {owner: (log,
    host)}, 'lines', 'first_dma', 'dma': {(log owner, host owner): n}}``."""
    rows = []
    for fr in sorted(frames):
        if not any((fr, v) in log['lines'] for v in range(lines)):
            continue
        co, ch, dl, kinds, first = collections.Counter(), collections.Counter(), [], collections.Counter(), None
        for v in range(lines):
            o = log['lines'].get((fr, v))
            if o is None:
                continue
            h = frames[fr][v * hpos:(v + 1) * hpos]
            o = bytes(o[:hpos])
            co.update(o); ch.update(h)
            if o.count(25) != h.count(25) or abs(o.count(1) - h.count(1)) > 6:
                dl.append(v)
            for k in range(min(len(o), len(h))):
                if o[k] != h[k]:
                    key = (o[k], h[k])
                    kinds[key] += 1
                    if first is None and key not in ((1, 0), (0, 1)):
                        first = (v, k, key)
        rows.append({'frame': fr, 'counts': {k: (co[k], ch[k]) for k in sorted(set(co) | set(ch)) if co[k] != ch[k]},
                     'lines': dl, 'first_dma': first, 'dma': {k: n for k, n in kinds.items() if k not in ((1, 0), (0, 1))}})
    return rows


def format_own_compare(rows):
    L = []
    for r in rows:
        name = lambda k: OWNER_LETTERS[k] if k < len(OWNER_LETTERS) else '?'
        L.append('%d  %s  lines %s  first DMA diff %s  %s' % (
            r['frame'], ' '.join('%s:%d/%d' % (name(k), a, b) for k, (a, b) in r['counts'].items()), r['lines'][:12],
            r['first_dma'], dict(sorted(r['dma'].items(), key=lambda x: -x[1])[:6])))
    return '\n'.join(L)
