"""The host of a translation (path B): the C files a rebuild includes around the output of
``arek recomp`` so the translated game runs with the kit's models - time from the bus model
per DMA slot, the beam, interrupts, the CIAs, Paula's audio DMA and output, the OCS picture
line by line - and the drivers that run it against the original's captures. Extracted from the
Alien Breed II project (docs/HOST.md).

    arek host copy DIR                  # arek_host.h, arek_display.h, arek_audio.h, the drivers (plus `arek bus copy`)
    arek host state CAPTURE OUT         # a bpstate capture -> the state folder the trace driver starts from

``render(ram, cop1lc, regs)`` runs the C renderer (``arek_display_render.c``) on a chip RAM image
and returns the frame's pixels, the way ``arek.display.render`` does in Python: the tests hold the
two against each other and ``arek selftest display --c`` holds the C one against the emulator.
"""
import json
import os
import shutil
import struct
import subprocess
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = ('arek_host_pre.h', 'arek_host.h', 'arek_display.h', 'arek_audio.h', 'arek_host_trace.c', 'arek_display_render.c')


def copy(dest):
    """Copy the host's sources into ``dest`` (a project's lib folder, next to ``arek bus copy``). Returns the paths."""
    os.makedirs(dest, exist_ok=True)
    out = []
    for name in FILES:
        shutil.copy(os.path.join(HERE, name), os.path.join(dest, name))
        out.append(os.path.join(dest, name))
    return out


def compiler():
    return shutil.which('cc') or shutil.which('gcc') or shutil.which('clang')


def compile_render(out=None, cc=None):
    """Build ``arek_display_render`` (one frame from a RAM image with the C renderer). Returns the executable."""
    cc = cc or compiler()
    if not cc:
        raise RuntimeError('no C compiler (cc, gcc or clang) for the renderer')
    out = out or os.path.join(tempfile.mkdtemp(prefix='arek-host'), 'arek_display_render')
    subprocess.run([cc, '-O2', '-I', HERE, '-o', out, os.path.join(HERE, 'arek_display_render.c'), '-lm'], check=True)
    return out


def render(ram, cop1lc, regs=None, exe=None, lines=312):
    """The C renderer on ``ram`` (bytes): ``(pixels, rgb)`` - ``pixels[v][h]`` 12-bit colours (bit 12 = EHB half
    bright) for ``lines`` lines, ``rgb`` the 716 x 285 RGB24 screenshot. ``regs``: {offset: value} at the frame start."""
    exe = exe or compile_render()
    d = tempfile.mkdtemp(prefix='arek-render')
    rp, raw, pix = os.path.join(d, 'ram.bin'), os.path.join(d, 'out.raw'), os.path.join(d, 'out.pix')
    with open(rp, 'wb') as f:
        f.write(bytes(ram))
    args = [exe, rp, '%x' % cop1lc, raw, pix]
    if regs:
        words = [0] * 0x100
        for off, v in regs.items():
            words[off >> 1] = v & 0xffff
        rg = os.path.join(d, 'regs.txt')
        with open(rg, 'w') as f:
            f.write(' '.join('%x' % w for w in words) + '\n')
        args.append(rg)
    subprocess.run(args, check=True)
    with open(pix, 'rb') as f:
        data = f.read()
    width = 456
    pixels = [list(struct.unpack('<%dH' % width, data[v * width * 2:(v + 1) * width * 2])) for v in range(min(lines, 312))]
    with open(raw, 'rb') as f:
        rgb = f.read()
    shutil.rmtree(d, ignore_errors=True)
    return pixels, rgb


def state(capture, out, trace=None):
    """The state folder a host driver starts from (``arek_host_trace.c``), from an ``arek bpstate`` capture folder:
    ``chip.bin`` (chip RAM from 0), ``slow.bin`` (the first extra region, zeros without one), ``creg.bin`` (the custom
    registers, ``bpstate.chip_regs``), ``state.txt`` (D0-D7, A0-A7; SR, beam time in CCK, INTREQ, PC; CIA-A PRA SDR ICR,
    JOY0DAT JOY1DAT POTGOR; frame). SR comes from cpu.json ``sr`` or from record 0 of ``trace`` (a trace armed at the
    same stop); the CIA and joystick values from cpu.json ``chips`` (``ciaa``) when the build prints them, else
    defaults (PRA $FE, POTGOR $5500). Returns the metadata dict."""
    from ..headless import bpstate
    capture = os.path.abspath(capture)
    with open(os.path.join(capture, 'cpu.json')) as f:
        meta = json.load(f)
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(capture, meta['ram_file']), 'rb') as f:
        chip = f.read()
    with open(os.path.join(out, 'chip.bin'), 'wb') as f:
        f.write(chip[:0x80000].ljust(0x80000, b'\0'))
    slow = b''
    if meta.get('regions'):
        with open(os.path.join(capture, meta['regions'][0]['file']), 'rb') as f:
            slow = f.read()
    with open(os.path.join(out, 'slow.bin'), 'wb') as f:
        f.write(slow[:0x80000].ljust(0x80000, b'\0'))
    with open(os.path.join(out, 'creg.bin'), 'wb') as f:
        f.write(bpstate.chip_regs(meta.get('chips', {})))
    sr = meta.get('sr')
    if sr is None and trace:
        from ..headless import trace as tr
        r0 = next(iter(tr.records(trace)))
        if r0['pc'] != meta['pc']:
            raise ValueError('trace record 0 (pc %x) is not the capture stop (pc %x)' % (r0['pc'], meta['pc']))
        sr = r0['sr']
    if sr is None:
        ccr = meta.get('ccr') or {}
        sr = 0x2000 | (ccr.get('x', 0) << 4) | (ccr.get('n', 0) << 3) | (ccr.get('z', 0) << 2) | (ccr.get('v', 0) << 1) | ccr.get('c', 0)
    chips = meta.get('chips', {})
    cia = chips.get('ciaa', {})
    pa = chips.get('paula', {})
    v, h = meta['beam']['position']
    with open(os.path.join(out, 'state.txt'), 'w') as f:
        f.write(' '.join('%x' % x for x in meta['d']) + '\n' + ' '.join('%x' % x for x in meta['a']) + '\n')
        f.write('%x %d %x %x\n' % (sr, v * 227 + h, pa.get('INTREQ', 0) if isinstance(pa.get('INTREQ', 0), int) else 0, meta['pc']))
        f.write('%x %x %x %x %x %x\n' % (cia.get('PRA', 0xfe) if isinstance(cia.get('PRA', 0xfe), int) else 0xfe,
                                         cia.get('SDR', 0) if isinstance(cia.get('SDR', 0), int) else 0,
                                         cia.get('ICR', 0) if isinstance(cia.get('ICR', 0), int) else 0,
                                         0, 0, 0x5500))
        f.write('%d\n' % meta['beam']['frame'])
    return {'sr': sr, 'frame': meta['beam']['frame'], 'time': v * 227 + h, 'pc': meta['pc'], 'dir': os.path.abspath(out)}
