"""The Amiga bus per DMA slot, for recompiled games (``arek_bus.h``, ``arek_bus.c``,
``arek_bus_vamiga.c``): who owns each slot of each line (refresh, audio, bitplanes, sprites,
copper, blitter, CPU), the blitter cycle by cycle, the CPU by the bus accesses of its
instructions. It decides what a frame boundary cannot: on which instruction an interrupt lands,
when a blit ends, whether the original overran the frame. Extracted from the Alien Breed project
(docs/BUS.md: API, calibration, geometry, limits); ``arek_bus_vamiga.c`` is derived from vAmiga
(Dirk W. Hoffmann, MPL-2.0), the rest is MIT like the kit.

    arek bus copy DIR          # the C files into a project (a translation includes arek_bus_glue.h)
    arek selftest bus          # the model against VAHeadless's bus log on a synthetic program
    arek recomp --bus-table    # per translated instruction: words, extra accesses, internal cycles before

The host side: ``arek_bus_glue.h`` turns the runtime's hooks (``-DTICK_HOOK -DBUS_HOOK``) into
model calls; ``replay`` runs the blitter of the model against a recorded bus log (no game data
needed: the log of any run, or the self-test's).
"""
import os
import shutil
import struct
import subprocess
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = ('arek_bus.h', 'arek_bus.c', 'arek_bus_vamiga.c', 'arek_bus_glue.h', 'arek_bus_replay.c', 'arek_bus_check.c')


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
