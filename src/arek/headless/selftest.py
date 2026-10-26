"""Self-tests of a VAHeadless build on synthetic boot disks (no game involved).

``display(conf)``: does ``arek.display`` render what this emulator shows? The disk
(``selftest_display.s``: 6 planes of a pattern, dual playfield with scroll and changing
priorities, EHB, sprites with an attached pair and control words reloaded at VSTOP) is run
to its idle loop, RAM and the screenshot are captured and compared pixel by pixel.

``inputs(conf)``: are inputs applied frame by frame? It runs its disk with ``VAHL_INPUTS``
and checks that every frame saw exactly the keys of its line.

``audio(conf)``: does the Paula model (``arek_bus_paula.h``) agree with this emulator? Its disk
(``selftest_audio.s``: four channels with different periods, lengths and volumes switched on and
off by a script, a period change while playing) runs with ``VAHL_BUSLOG``, ``VAHL_REGLOG`` and
``VAHL_AUDLOG``; the register writes are replayed into the model and its audio DMA slots and
output bytes are compared with the logs.

``bus(conf)``: does the bus model (``arek.bus``) agree with this emulator's bus log? Its disk
(``selftest_bus.s``: 5 lores planes, a sprite, a copper list with waits, three blits in a loop
with stack traffic between them) runs with ``VAHL_BUSLOG``; the model's fixed DMA slots are
compared with the log slot by slot and every blit is replayed over the recorded map.
The disk only needs the Kickstart ROM from ``local.conf``. Its boot block copies a
payload to $40000 and jumps there; the payload installs a level-3 handler at
$40028 that stores JOY1DAT and CIA-A PRA of each frame at $50000 + 4·n (n at
$4FFF0) and returns. Source (GNU as, -m68000)::

    boot:   lea pay(%pc),%a0 ; lea 0x40000,%a1 ; move.w #(payend-pay)/2-1,%d0
    1:      move.w (%a0)+,(%a1)+ ; dbf %d0,1b ; jmp 0x40000
    pay:    lea 0xdff000,%a6 ; move.w #0x7fff,0x9a(%a6) ; move.w #0x7fff,0x9c(%a6)
            move.l #handler,0x6c ; clr.w 0x4fff0 ; move.w #0xc020,0x9a(%a6)
    loop:   bra.s loop
    handler: movem.l %d1/%a0,-(%sp) ; move.w 0x4fff0,%d1 ; lea 0x50000,%a0 ; adda.w %d1,%a0
            move.w 0xdff00c,(%a0)+ ; move.b 0xbfe001,(%a0) ; addq.w #4,0x4fff0
            move.w #0x20,0xdff09c ; move.w #0x20,0xdff09c ; movem.l (%sp)+,%d1/%a0 ; rte
"""
import os
import random
import struct
import tempfile

from .. import adf
from . import trace

HANDLER = 0x40028
BOOT = bytes.fromhex(
    '41fa001843f900040000303c003032d851c8fffc4ef9000400004df900dff0003d7c7fff009a3d7c7fff009c'
    '21fc00040028006c42790004fff03d7cc020009a60fe48e7408032390004fff041f900050000d0c130f900df'
    'f00c10b900bfe00158790004fff033fc002000dff09c33fc002000dff09c4cdf01024e73')
KEYS = ('', 'R', 'L', 'U', 'D', 'F', 'RF', 'UL', 'DR')


def _boot_disk(code):
    d = bytearray(adf.SIZE)
    d[0:4] = b'DOS\0'
    struct.pack_into('>I', d, 8, 880)
    d[12:12 + len(code)] = code
    struct.pack_into('>I', d, 4, adf.bootblock_checksum(d[:1024]))
    return bytes(d)


def disk():
    """The input self-test ADF image."""
    return _boot_disk(BOOT)


DISPLAY_LOOP, DISPLAY_COPPER = 0x4004c, 0x4004e
DISPLAY_BOOT = bytes.fromhex(
    '41fa001843f900040000303c01d032d851c8fffc4ef9000400004df900dff0003d7c7fff009a3d7c7fff009641f90001'
    '00007e053c3c00c77a133006e748bb40c0fc02b5ef7830c051cdfff051ceffea51cfffe22d7c0004004e00803d400088'
    '3d7c83a0009660fe010046000102003101040024008e2c810090f4c100920038009400d001080000010a000000e00001'
    '00e2000000e4000100e61f4000e8000100ea3e8000ec000100ee5dc000f0000100f27d0000f4000100f69c4001200004'
    '0122018e012400040126039e01280004012a022a012c0004012e029201300004013202fa013400040136039e01380004'
    '013a039e013c0004013e039e0180000001820f00018400f00186000f01880ff0018a0f0f018c00ff018e0fff01900800'
    '01920080019400080196088001980808019a0088019c0888019e044401a00a5001a205a001a4050a01a60a0501a80c30'
    '01aa03c001ac030c01ae0c0301b00e7101b2017e01b407e101b60e1701b80d4201ba024d01bc042d01be0d246c07fffe'
    '010400098c07fffe01040052a007fffe010062000102000001040012c007fffe01005200fffffffe40805400f00f0ff0'
    'f00f0ff0f00f0ff0f00f0ff0f00f0ff0f00f0ff0f00f0ff0f00f0ff0f00f0ff0f00f0ff0f00f0ff0f00f0ff0f00f0ff0'
    'f00f0ff0f00f0ff0f00f0ff0f00f0ff0f00f0ff0f00f0ff0f00f0ff060907000aaaa5555aaaa5555aaaa5555aaaa5555'
    'aaaa5555aaaa5555aaaa5555aaaa5555aaaa5555aaaa5555aaaa5555aaaa5555aaaa5555aaaa5555aaaa5555aaaa5555'
    '0000000050a068003c3c00ff3c3c00ff3c3c00ff3c3c00ff3c3c00ff3c3c00ff3c3c00ff3c3c00ff3c3c00ff3c3c00ff'
    '3c3c00ff3c3c00ff3c3c00ff3c3c00ff3c3c00ff3c3c00ff3c3c00ff3c3c00ff3c3c00ff3c3c00ff3c3c00ff3c3c00ff'
    '3c3c00ff3c3c00ff0000000050a068800f0fff000f0fff000f0fff000f0fff000f0fff000f0fff000f0fff000f0fff00'
    '0f0fff000f0fff000f0fff000f0fff000f0fff000f0fff000f0fff000f0fff000f0fff000f0fff000f0fff000f0fff00'
    '0f0fff000f0fff000f0fff000f0fff000000000070b89800ffffffffffffffffffffffffffffffffffffffffffffffff'
    'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'
    'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'
    'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff00000000')


def display_disk():
    """The display self-test ADF image (boot code copies ``selftest_display.s`` to $40000)."""
    return _boot_disk(DISPLAY_BOOT)


def display(conf, timeout=300, keep=None, c=False):
    """Render the self-test frame with ``arek.display`` (``c=True``: with the C renderer of
    ``arek.host``) and compare it with the emulator's screenshot: ``{'pixels': differing, 'total': n,
    'box': ..., 'dir': folder}``."""
    from .. import display as dsp
    from . import bpstate
    tmp = keep or tempfile.mkdtemp(prefix='arek-selftest')
    path = os.path.join(tmp, 'display.adf')
    with open(path, 'wb') as f:
        f.write(display_disk())
    meta = bpstate.capture(conf, os.path.join(tmp, 'cap'), DISPLAY_LOOP, 0, 12, t_set=6, adf=path,
                           timeout=timeout, screenshot=True)
    cap = os.path.join(tmp, 'cap')
    with open(os.path.join(cap, meta['ram_file']), 'rb') as f:
        ram = f.read()
    with open(os.path.join(cap, 'stable.raw'), 'rb') as f:
        ref = f.read()
    if c:
        from .. import host
        _, rgb = host.render(ram, DISPLAY_COPPER, regs={0x096: meta['chips'].get('agnus', {}).get('DMACON', 0)} if meta.get('chips') else None)
        d = dsp.diff(rgb, ref)
    else:
        d = dsp.diff(dsp.to_screenshot(dsp.render(ram, DISPLAY_COPPER)), ref)
    d['dir'] = tmp
    return d


def keys_of(joy, cia):
    """JOY1DAT and CIA-A PRA -> the keys held (R L U D F)."""
    r, l = bool(joy & 2), bool(joy & 0x200)
    u, dn = bool(((joy >> 8) ^ (joy >> 9)) & 1), bool((joy ^ (joy >> 1)) & 1)
    return ''.join(k for k, on in zip('RLUDF', (r, l, u, dn, not cia & 0x80)) if on)


def inputs(conf, frames=240, seed=7, timeout=300, keep=None):
    """Run the self-test; returns ``{'frames': n, 'match': n, 'mismatch': [(k, want, got)]}``."""
    tmp = keep or tempfile.mkdtemp(prefix='arek-selftest')
    path = os.path.join(tmp, 'selftest.adf')
    with open(path, 'wb') as f:
        f.write(disk())
    rnd = random.Random(seed)
    lines = [KEYS[(k // 3) % len(KEYS)] if k % 17 else rnd.choice(KEYS) for k in range(frames + 60)]
    inp = os.path.join(tmp, 'inputs.txt')
    with open(inp, 'w') as f:
        f.write('\n'.join(lines) + '\n')
    out = os.path.join(tmp, 'selftest.vtr')
    seconds = 6 + frames / 50.0
    trace.capture(conf, out, [], 6, int(seconds) + 1, breaks=[HANDLER],
                  ranges=[(0x4fff0, 4), (0x50000, 4 * (frames + 400))], adf=path, timeout=timeout, inputs=inp)
    recs = list(trace.records(out))
    if len(recs) < 2:
        raise trace.TraceError('the handler at $%x was not hit - see %s.log' % (HANDLER, out))
    buf = recs[-1]['ranges'][0x50000]
    bad, n = [], 0
    for k, rec in enumerate(recs[:-1]):
        c = struct.unpack('>H', rec['ranges'][0x4fff0][:2])[0]
        if c + 3 > len(buf):
            break
        want = ''.join(ch for ch in 'RLUDF' if ch in lines[k])
        got = keys_of(struct.unpack('>H', buf[c:c + 2])[0], buf[c + 2])
        n += 1
        if got != want:
            bad.append((k, want, got))
    return {'frames': n, 'match': n - len(bad), 'mismatch': bad[:20], 'dir': tmp}


BUS_LOOP, BUS_COPLIST, BUS_SPR0, BUS_NUL = 0x40042, 0x400de, 0x40196, 0x4021e
BUS_PAYLOAD = bytes.fromhex('4df900dff0003d7c7fff009a3d7c7fff00962d7c000400de00803d4000883d7c87e000963d7cffff00443d7cffff0046426e0060426e0062426e0064426e00667e002d7c0001000000502d7c0002000000543d7c09f00040426e00423d7c08140058082e0006000266f82d7c0001000000502d7c00012000004c2d7c0001400000482d7c0002200000543d7c0fca00403d7c100000423d7c040a0058082e0006000266f82d7c0002400000543d7c01000040426e00423d7c10280058082e0006000266f841f90003000048e0ff7c4cd83eff524733c70003fffe6000ff6601005200008e2c810090f4c100920038009400d001080000010a000000e0000500e2000000e4000500e6200000e8000500ea400000ec000500ee600000f0000500f280000120000401220196012400040126021e01280004012a021e012c0004012e021e013000040132021e013400040136021e01380004013a021e013c0004013e021e0180000001820f00018400f00186000f6c07fffe018000058c07fffe01800050a007fffe01800500c007fffe01800055fffffffe50807000f00f0ff0f00f0ff0f00f0ff0f00f0ff0f00f0ff0f00f0ff0f00f0ff0f00f0ff0f00f0ff0f00f0ff0f00f0ff0f00f0ff0f00f0ff0f00f0ff0f00f0ff0f00f0ff0f00f0ff0f00f0ff0f00f0ff0f00f0ff0f00f0ff0f00f0ff0f00f0ff0f00f0ff0f00f0ff0f00f0ff0f00f0ff0f00f0ff0f00f0ff0f00f0ff0f00f0ff0f00f0ff00000000000000000')


def bus_disk():
    """The bus self-test ADF image (boot code copies ``selftest_bus.s``, linked at $40000, there)."""
    n = len(BUS_PAYLOAD) // 2 - 1
    stub = bytes.fromhex('41fa001843f900040000303c') + struct.pack('>H', n) + bytes.fromhex('32d851c8fffc4ef900040000')
    return _boot_disk(stub + BUS_PAYLOAD)


BUS_REGS = {0x096: 0x87e0, 0x100: 0x5200, 0x092: 0x38, 0x094: 0xd0, 0x08e: 0x2c81, 0x090: 0xf4c1,
            0x080: BUS_COPLIST >> 16, 0x082: BUS_COPLIST & 0xffff, 0x120: BUS_SPR0 >> 16, 0x122: BUS_SPR0 & 0xffff}
for _n in range(1, 8):
    BUS_REGS[0x120 + 4 * _n], BUS_REGS[0x122 + 4 * _n] = BUS_NUL >> 16, BUS_NUL & 0xffff


AUDIO_LOOP, AUDIO_SAMP = 0x4001a, 0x40118
AUDIO_PAYLOAD = bytes.fromhex('4df900dff0003d7c7fff009a3d7c7fff00963d7c820000967e00706461000084524733c70003fffe32070241000f66046100007cd241323b104a67043d41009632070241000f0c410009660c3d7c009600a63d7c003000a8303c00c86100004432070241000f0c41000566063d7c000200960c41000b66a23d7c800f00966000ff9a000000008001000080020000800c00000002000080030000000f000000000000322e0006e049b20066f64e752d7c0004011800a03d7c001000a43d7c00c800a63d7c004000a82d7c0004011800b03d7c000800b43d7c007c00b63d7c002000b82d7c0004011800c03d7c002000c43d7c012c00c63d7c004000c82d7c0004011800d03d7c000400d43d7c008300d63d7c002800d84e7500102030405060707f7060504030201000f0e0d0c0b0a0908090a0b0c0d0e0f003070b0f13171b1f23272b2f33373b3ffdf9f5f1ede9e5e1ddd9d5d1cdc9c5c1')


def audio_disk():
    """The Paula self-test ADF image (boot code copies ``selftest_audio.s``, linked at $40000, there)."""
    n = len(AUDIO_PAYLOAD) // 2 - 1
    stub = bytes.fromhex('41fa001843f900040000303c') + struct.pack('>H', n) + bytes.fromhex('32d851c8fffc4ef900040000')
    return _boot_disk(stub + AUDIO_PAYLOAD)


def audio(conf, frames=60, first=330, timeout=300, keep=None):
    """Run the Paula self-test, record ``frames`` frames from ``first`` (bus log, register log, audio
    log) and check ``arek_bus_paula.h``: ``{'frames', 'from', 'agree', 'disagree', 'slots', 'samples',
    'dir', 'text'}`` (``slots`` / ``samples`` per channel as ``arek.bus.paula_check`` returns them).
    The comparison starts one frame after the first full setup of the channels inside the window
    (the program rewrites it every 16 frames), so the model and the log start from the same state."""
    from .. import bus as busmod
    tmp = keep or tempfile.mkdtemp(prefix='arek-selftest')
    os.makedirs(tmp, exist_ok=True)
    path = os.path.join(tmp, 'audio.adf')
    with open(path, 'wb') as f:
        f.write(audio_disk())
    out, log = os.path.join(tmp, 'audio.vtr'), os.path.join(tmp, 'audio.bus')
    reglog, audlog = os.path.join(tmp, 'audio.reglog'), os.path.join(tmp, 'audio.audlog')
    seconds = (first + frames) / 50.0 + 1
    trace.capture(conf, out, [], 6, int(seconds) + 1, breaks=[AUDIO_LOOP], ranges=[(0x3fffe, 2)], adf=path,
                  timeout=timeout, buslog=log, bus_frames=(first, first + frames - 1), reglog=reglog, audlog=audlog)
    recs = list(trace.records(out))
    if len(recs) < 2:
        raise trace.TraceError('the loop at $%x was not hit - see %s.log' % (AUDIO_LOOP, out))
    blog = trace.read_buslog(log)
    abbl = os.path.join(tmp, 'audio.abbl')
    info = busmod.buslog_to_bin(blog, abbl, hpos=227)
    writes = trace.read_reglog(reglog)
    setups = sorted({r['frame'] for r in writes if r['reg'] == 0x0a0 and not r['agnus']})
    logged = min(r['frame'] for r in writes) if writes else 0
    start = next((f for f in setups if f > logged and f >= info['frame0']), None)
    if start is None or start - info['frame0'] + 2 >= info['frames']:
        raise trace.TraceError('no full channel setup inside the logged window (files in %s)' % tmp)
    ram = bytearray(0x80000)
    ram[0x40000:0x40000 + len(AUDIO_PAYLOAD)] = AUDIO_PAYLOAD
    r = busmod.paula_check(abbl, busmod.paula_writes(writes, info['frame0'], info['lines']),
                           busmod.paula_samples(trace.read_audlog(audlog), info['frame0'], info['lines']),
                           from_frame=start - info['frame0'] + 1, exe=busmod.compile_paula_check(os.path.join(tmp, 'arek_bus_paula_check')),
                           ram=bytes(ram))
    r.update(frames=info['frames'], lines=info['lines'], dir=tmp, setup_frame=start, **{'from': start - info['frame0'] + 1})
    return r


def bus(conf, frames=40, first=330, timeout=300, keep=None):
    """Run the self-test, record the bus log of ``frames`` frames from ``first`` (after boot) and
    check the model: ``{'frames', 'fixed_ok', 'fixed_bad', 'blits', 'exact', 'slots_ok', 'slots_bad', 'dir', 'text'}``."""
    import re
    import subprocess
    from .. import bus as busmod
    tmp = keep or tempfile.mkdtemp(prefix='arek-selftest')
    path = os.path.join(tmp, 'bus.adf')
    with open(path, 'wb') as f:
        f.write(bus_disk())
    out, log = os.path.join(tmp, 'bus.vtr'), os.path.join(tmp, 'bus.log')
    seconds = (first + frames) / 50.0 + 1
    trace.capture(conf, out, [], 6, int(seconds) + 1, breaks=[BUS_LOOP], ranges=[(0x3fffe, 2)], adf=path,
                  timeout=timeout, buslog=log, bus_frames=(first, first + frames - 1))
    recs = list(trace.records(out))
    if len(recs) < 2:
        raise trace.TraceError('the loop at $%x was not hit - see %s.log' % (BUS_LOOP, out))
    blog = trace.read_buslog(log)
    abbl = os.path.join(tmp, 'bus.abbl')
    info = busmod.buslog_to_bin(blog, abbl, hpos=227)
    with open(os.path.join(tmp, 'regs.txt'), 'w') as f:
        f.write(' '.join('%x' % BUS_REGS.get(i * 2, 0) for i in range(0x100)) + '\n')
    ram = bytearray(0x80000)
    ram[0x40000:0x40000 + len(BUS_PAYLOAD)] = BUS_PAYLOAD
    with open(os.path.join(tmp, 'ram.bin'), 'wb') as f:
        f.write(ram)
    cc = busmod.compiler()
    if not cc:
        raise RuntimeError('no C compiler for the bus model')
    check = busmod.compile_check(os.path.join(tmp, 'arek_bus_check'), cc)
    r = subprocess.run([check, abbl, os.path.join(tmp, 'regs.txt'), os.path.join(tmp, 'ram.bin')], capture_output=True, text=True)
    m = re.search(r'fixed DMA slots: agree (\d+), disagree (\d+)', r.stdout)
    rep = busmod.replay(abbl, busmod.compile_replay(os.path.join(tmp, 'arek_bus_replay'), cc))
    return {'frames': info['frames'], 'lines': info['lines'], 'fixed_ok': int(m.group(1)) if m else 0,
            'fixed_bad': int(m.group(2)) if m else -1, 'blits': rep['blits'], 'exact': rep['exact'],
            'slots_ok': rep['slots_ok'], 'slots_bad': rep['slots_bad'], 'dir': tmp, 'text': r.stdout + rep['text']}
