"""The host of a translation (path B): the C files a rebuild includes around the output of
``arek recomp`` so the translated game runs with the kit's models - time from the bus model
per DMA slot, the beam, interrupts, the CIAs, Paula's audio DMA and output, the OCS picture
line by line - and the drivers that run it against the original's captures. Extracted from the
Alien Breed II project (docs/HOST.md).

    arek host copy DIR                  # arek_host.h, arek_display.h, arek_audio.h, arek_host_disk.h, the drivers, the engine (plus `arek bus copy`)
    arek host state CAPTURE OUT         # a bpstate capture -> the state folder the trace driver starts from
    arek host pack STATE OUT.bin        # the state folder as one file for the engine (engine_init)
    arek host engine OUT --game game.c --l3 f_x --entry f_y [--native] [--run]   # the emcc (or cc) command for arek_host_engine.c

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
FILES = ('arek_host_pre.h', 'arek_host.h', 'arek_display.h', 'arek_audio.h', 'arek_host_disk.h', 'arek_host_trace.c',
         'arek_display_render.c', 'arek_host_engine.c', 'arek_host_engine_check.js')
STATE_MAGIC = b'AREKSTATE1\0'
ENGINE_API = ('engine_alloc', 'engine_init', 'engine_set_disk', 'engine_run', 'engine_waiting', 'engine_ended', 'engine_error',
              'engine_done', 'engine_allow', 'engine_keys', 'engine_keys2', 'engine_key', 'engine_fr_frame', 'engine_fr_aud0',
              'engine_fr_naud', 'engine_fr_led', 'engine_aud_ring', 'engine_aud_size', 'engine_rgb', 'engine_rgb_w', 'engine_rgb_h',
              'engine_pix', 'engine_pix_w', 'engine_pix_h', 'engine_led', 'engine_frame_no', 'engine_peek8', 'engine_poke8',
              'engine_disk_reads', 'engine_disk_fails', 'engine_hash_hex', 'engine_stop', 'engine_parked', 'engine_threaded',
              'engine_aud_written', 'engine_aud_read', 'engine_aud_low', 'engine_hash_on')


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
    bright) for ``lines`` lines, ``rgb`` the 716 x 285 RGB24 screenshot. ``regs``: {offset: value} at the frame start.
    ``render.hires`` afterwards holds {v: [912 pixels]} of the lines drawn in hires (as ``Frame.hires``)."""
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
    pos = 312 * width * 2
    flags = data[pos:pos + 312]
    pos += 312
    hires = {}
    for v in range(312):
        if flags[v]:
            hires[v] = list(struct.unpack('<%dH' % (2 * width), data[pos:pos + 4 * width]))
            pos += 4 * width
    with open(raw, 'rb') as f:
        rgb = f.read()
    shutil.rmtree(d, ignore_errors=True)
    render.hires = hires
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


def pack(state_dir, out):
    """The state folder (``state``) as one file the engine loads (``engine_init``): ``AREKSTATE1`` + NUL, chip RAM
    (0x80000), slow RAM (0x80000, zeros without slow.bin), the custom registers (0x200), state.txt + NUL. Returns the size."""
    def part(name, size):
        path = os.path.join(state_dir, name)
        data = open(path, 'rb').read() if os.path.exists(path) else b''
        return data[:size].ljust(size, b'\0')
    with open(os.path.join(state_dir, 'state.txt'), 'rb') as f:
        txt = f.read()
    blob = STATE_MAGIC + part('chip.bin', 0x80000) + part('slow.bin', 0x80000) + part('creg.bin', 0x200) + txt + b'\0'
    with open(out, 'wb') as f:
        f.write(blob)
    return len(blob)


def engine_command(out_dir, game, l3, entry, cc=None, native=False, dynamic=False, ovl=None, src=None, includes=(),
                   defines=(), export='ArekEngine', extra=(), thread=False):
    """The command that builds ``arek_host_engine.c`` with the translation ``game`` (a path; its folder is an include
    path), the level-3 handler ``l3`` and the entry routine ``entry``: with Emscripten (ASYNCIFY, ``OUT/engine.js`` +
    ``engine.wasm``, the API exported) or ``native=True`` with the C compiler (``OUT/arek_host_engine``). ``ovl``: the
    overlay modules file (OVL_SRC), ``src``: the project's externs file (ENGINE_SRC), ``dynamic``: ENGINE_DYNAMIC;
    ``thread``: the engine in its own thread (ENGINE_THREAD: pthreads and shared memory, no ASYNCIFY; the page needs
    COOP / COEP, `arek web serve --isolated`) - the wasm build is ``engine_mt.js`` + ``engine_mt.wasm``."""
    from .. import bus
    game = os.path.abspath(game)
    bus_dir = os.path.dirname(os.path.abspath(bus.__file__))
    cmd = [cc] if cc else [compiler() or 'cc'] if native else ['emcc']
    cmd += ['-O2', '-I', HERE, '-I', bus_dir, '-I', os.path.dirname(game)]
    for inc in includes:
        cmd += ['-I', inc]
    cmd += ['-DGAME_SRC="%s"' % os.path.basename(game), '-DHOST_L3=%s' % l3, '-DHOST_ENTRY=%s' % entry]
    if dynamic:
        cmd.append('-DENGINE_DYNAMIC=1')
    if thread:
        cmd += ['-pthread', '-DENGINE_THREAD=1']
    if ovl:
        cmd += ['-I', os.path.dirname(os.path.abspath(ovl)), '-DOVL_SRC="%s"' % os.path.basename(ovl)]
    if src:
        cmd += ['-I', os.path.dirname(os.path.abspath(src)), '-DENGINE_SRC="%s"' % os.path.basename(src)]
    for d in defines:
        cmd.append('-D' + d)
    cmd += [os.path.join(HERE, 'arek_host_engine.c'), os.path.join(bus_dir, 'arek_bus.c'), os.path.join(bus_dir, 'arek_bus_vamiga.c')]
    if native:
        cmd += ['-lm', '-o', os.path.join(out_dir, 'arek_host_engine' + ('_mt' if thread else ''))]
    elif thread:
        cmd += ['-w', '-o', os.path.join(out_dir, 'engine_mt.js'),
                '-s', 'MODULARIZE=1', '-s', 'EXPORT_NAME=%s' % export, '-s', 'ENVIRONMENT=web,worker,node',
                '-s', 'PTHREAD_POOL_SIZE=1', '-s', 'INITIAL_MEMORY=268435456', '-s', 'STACK_SIZE=1048576',
                '-s', 'DEFAULT_PTHREAD_STACK_SIZE=8388608',
                '-s', 'EXPORTED_FUNCTIONS=[%s]' % ','.join('"_%s"' % f for f in ENGINE_API + ('malloc', 'free')),
                '-s', 'EXPORTED_RUNTIME_METHODS=["HEAPU8","HEAP16","HEAP32","ccall"]']
    else:
        cmd += ['-w', '-DENGINE_ASYNC=1', '-o', os.path.join(out_dir, 'engine.js'),
                '-s', 'MODULARIZE=1', '-s', 'EXPORT_NAME=%s' % export, '-s', 'ENVIRONMENT=web,worker,node',
                '-s', 'ASYNCIFY=1', '-s', "ASYNCIFY_IMPORTS=['js_wait']", '-s', 'ASYNCIFY_IGNORE_INDIRECT=1',
                '-s', 'ASYNCIFY_STACK_SIZE=1048576', '-s', 'ALLOW_MEMORY_GROWTH=1', '-s', 'INITIAL_MEMORY=67108864',
                '-s', 'STACK_SIZE=1048576',
                '-s', 'EXPORTED_FUNCTIONS=[%s]' % ','.join('"_%s"' % f for f in ENGINE_API + ('malloc',)),
                '-s', 'EXPORTED_RUNTIME_METHODS=["HEAPU8","HEAP16","ccall"]']
    cmd += list(extra)
    return cmd


def engine_build(out_dir, *args, **kw):
    """Run ``engine_command``; returns the command. Raises CalledProcessError when the compiler fails."""
    os.makedirs(out_dir, exist_ok=True)
    cmd = engine_command(out_dir, *args, **kw)
    subprocess.run(cmd, check=True)
    return cmd
