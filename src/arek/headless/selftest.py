"""Self-test of a VAHeadless build: are inputs applied frame by frame?

``inputs(conf)`` builds a synthetic bootable ADF (no game involved), runs it with
``VAHL_INPUTS`` and checks that every frame saw exactly the keys of its line.
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


def disk():
    """The self-test ADF image."""
    d = bytearray(adf.SIZE)
    d[0:4] = b'DOS\0'
    struct.pack_into('>I', d, 8, 880)
    d[12:12 + len(BOOT)] = BOOT
    struct.pack_into('>I', d, 4, adf.bootblock_checksum(d[:1024]))
    return bytes(d)


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
