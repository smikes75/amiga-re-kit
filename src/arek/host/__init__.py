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
import re
import shutil
import struct
import subprocess
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = tuple(sorted(f for f in os.listdir(HERE) if f.endswith(('.h', '.c', '.js'))))   # every source of the host (G55: a list forgot a header)
STATE_MAGIC = b'AREKSTATE1\0'
ENGINE_API = ('engine_alloc', 'engine_init', 'engine_set_disk', 'engine_run', 'engine_waiting', 'engine_ended', 'engine_error',
              'engine_done', 'engine_allow', 'engine_keys', 'engine_keys2', 'engine_key', 'engine_fr_frame', 'engine_fr_aud0',
              'engine_fr_naud', 'engine_fr_led', 'engine_aud_ring', 'engine_aud_size', 'engine_rgb', 'engine_rgb_w', 'engine_rgb_h',
              'engine_pix', 'engine_pix_w', 'engine_pix_h', 'engine_led', 'engine_frame_no', 'engine_peek8', 'engine_poke8',
              'engine_disk_reads', 'engine_disk_fails', 'engine_hash_hex', 'engine_stop', 'engine_parked', 'engine_threaded',
              'engine_aud_written', 'engine_aud_read', 'engine_aud_low', 'engine_hash_on', 'engine_cpu_speed')


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
    JOY0DAT JOY1DAT POTGOR; frame; 1.0.49, when the capture has the CIAs: for CIA-A then CIA-B the latch, counter and
    control register of timer A and of timer B, the interrupt mask and the ICR - a state taken in the middle of a game
    keeps its running timers and their interrupts). SR comes from cpu.json ``sr`` or from record 0 of ``trace`` (a trace armed at the
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
        cias = [bpstate.cia_regs(chips.get(n), clock=meta['beam'].get('clock')) for n in ('ciaa', 'ciab')]
        if all(cias):                                    # 1.0.49: the timers, masks and pending bits of both CIAs
            f.write(' '.join('%x %x %x %x %x %x %x %x' % (c['LA'], c['TA'], c['CRA'], c['LB'], c['TB'], c['CRB'], c['IMR'], c['ICR'])
                             for c in cias) + '\n')
        dr = meta.get('drive') or {}
        if 'cylinder' in dr and 'offset' in dr:          # 1.0.53: the drive for a host with HOST_FLOPPY - cylinder, byte under the head, colour clocks to the next byte, motor, PRB
            f.write('@drive %d %d %d %d %x\n' % (dr['cylinder'], dr['offset'] // 8, dr.get('dsk_due', 55), 1 if dr.get('motor') else 0, dr.get('prb', 0xff)))
        for line in audio_lines(meta):                   # 1.0.60: Paula's four channels where the original's stood
            f.write(line + '\n')
    playing = audio_playing(meta)
    if playing and not meta.get('audio'):
        import sys
        print('arek host state: channel %s is playing at the capture and the capture has no audio state - the host starts '
              'with silent channels and without their DMA slots (capture with a build that has vamiga-audstate-899da5d.patch)'
              % ', '.join(str(c) for c in playing), file=sys.stderr)
    return {'sr': sr, 'frame': meta['beam']['frame'], 'time': v * 227 + h, 'pc': meta['pc'], 'dir': os.path.abspath(out)}


def audio_playing(meta):
    """The channels with a period event pending at the capture (``? agnus events``: CH0-CH3)."""
    text = ((meta.get('drive') or {}).get('text') or {}).get('agnus events', '')
    return [int(m.group(1)) for m in re.finditer(r'^CH([0-3])\s+CHX_', text, re.M)]


def audio_lines(meta):
    """state.txt's ``@audio`` lines from a capture's ``audio`` (bpstate.parse_audio; a build with
    vamiga-audstate-899da5d.patch): per channel ``@audio CH ON ST IP REQ PERFIN LC PTR LEN AUDLEN PER VOL VOLLATCH DAT OUT
    ENHI ENLO INTREQ2 REQ2`` - REQ, REQ2 and PERFIN in absolute colour clocks (-1 = none; frame x 71 051 + line x 227 +
    slot), the numbers from LC on in hex. REQ is the model's request time: the slot that serves a pending request, one
    line back (the emulator serves it in the channel's next slot $0D + 2 x CH). None without the audio state in the
    capture.

    1.0.64: the emulator holds a request in two places - ``audDR`` in Paula from the moment it is raised to the end of
    that line, then ``audxDR`` in Agnus until the slot. A capture between the two saw no ``audxDR`` and the request was
    lost (the build did not print ``audDR``): the channel played one word twice and its next slot was missing. With
    ``audDR`` alone REQ is the start of the capture's line (served in the next one); with both, REQ is Agnus's and
    REQ2 Paula's (a period below 114, a word shorter than a line)."""
    audio = meta.get('audio') or []
    if len(audio) != 4:
        return []
    ag = (meta.get('chips') or {}).get('agnus', {})
    frame, (v, h) = meta['beam']['frame'], meta['beam']['position']
    out = []
    for a in sorted(audio, key=lambda x: x['channel']):
        ch = a['channel']
        req = req2 = -1
        if a.get('audxDR'):
            slot = 0x0d + 2 * ch
            req = frame * 71051 + (v if h < slot else v + 1) * 227 + slot - 227
        if a.get('audDR'):
            now_line = frame * 71051 + v * 227
            if req < 0:
                req = now_line
            else:
                req2 = now_line
        perfin = -1 if a.get('perfin') is None else a['perfin'] // 8
        num = lambda key: ag.get(key, 0) if isinstance(ag.get(key, 0), int) else 0
        out.append('@audio %d %d %d %d %d %d %x %x %x %x %x %x %x %x %x %d %d %d %d' % (
            ch, 1 if a.get('AUDxON') else 0, a.get('State', 0), 1 if a.get('AUDxIP') else 0, req, perfin,
            num('AUD%dLC' % ch), num('AUD%dPT' % ch), a.get('audlenLatch', 0), a.get('audlen', 0), a.get('audperLatch', 0),
            a.get('audvol', 0), a.get('audvolLatch', 0), a.get('auddat', 0), a.get('buffer', 0),
            1 if a.get('enablePenhi') else 0, 1 if a.get('enablePenlo') else 0, 1 if a.get('intreq2') else 0, req2))
    return out


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


WASM_FUNCTION_LIMIT = 7654321           # V8 refuses a larger function body


def wasm_largest_function(path):
    """The size in bytes of the largest function body of a wasm file (0 without a code section)."""
    with open(path, 'rb') as f:
        b = f.read()

    def leb(p):
        v = sh = 0
        while True:
            c = b[p]
            p += 1
            v |= (c & 0x7f) << sh
            sh += 7
            if not c & 0x80:
                return v, p
    pos = 8
    while pos < len(b):
        sid = b[pos]
        size, pos = leb(pos + 1)
        if sid == 10:
            n, p = leb(pos)
            big = 0
            for _ in range(n):
                sz, p = leb(p)
                big = max(big, sz)
                p += sz
                if p >= len(b):
                    break
            return big
        pos += size
    return 0


def engine_build(out_dir, *args, **kw):
    """Run ``engine_command``; returns the command. Raises CalledProcessError when the compiler fails. A big translation
    can get hundreds of routines inlined into one wasm function above V8's limit (Xenon 2, 17 MB of C: 8.2 MB in one
    function, ``CompileError`` at instantiation): such a build is made again with ``-fno-inline-functions``."""
    os.makedirs(out_dir, exist_ok=True)
    cmd = engine_command(out_dir, *args, **kw)
    subprocess.run(cmd, check=True)
    if cmd[0] == 'emcc' and '-fno-inline-functions' not in cmd:
        wasm = os.path.splitext(cmd[cmd.index('-o') + 1])[0] + '.wasm'
        big = wasm_largest_function(wasm) if os.path.exists(wasm) else 0
        if big > WASM_FUNCTION_LIMIT:
            print('a wasm function of %d bytes is above the browsers\' limit of %d: building again with -fno-inline-functions'
                  % (big, WASM_FUNCTION_LIMIT))
            cmd = cmd + ['-fno-inline-functions']
            subprocess.run(cmd, check=True)
    return cmd
