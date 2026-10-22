"""Self-tests of a VAHeadless build on synthetic boot disks (no game involved).

``display(conf)``: does ``arek.display`` render what this emulator shows? The disk
(``selftest_display.s``: 6 planes of a pattern, dual playfield with scroll and changing
priorities, EHB, sprites with an attached pair and control words reloaded at VSTOP) is run
to its idle loop, RAM and the screenshot are captured and compared pixel by pixel.

``inputs(conf)``: are inputs applied frame by frame? It runs its disk with ``VAHL_INPUTS``
and checks that every frame saw exactly the keys of its line.
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


def display(conf, timeout=300, keep=None):
    """Render the self-test frame with ``arek.display`` and compare it with the emulator's
    screenshot: ``{'pixels': differing, 'total': n, 'box': ..., 'dir': folder}``."""
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
