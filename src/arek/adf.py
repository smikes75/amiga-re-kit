"""ADF disk images: geometry, boot block, entropy map, inventory.

An ADF is a raw dump of a double-density 3.5" disk: 80 cylinders x 2 heads x
11 sectors x 512 bytes = 901 120 bytes. Nothing else is assumed - most games
here do not use the AmigaDOS filesystem at all (they boot their own trackloader
from the boot block), so this module never tries to "mount" the image; for
the games that do keep AmigaDOS files, ``arek.amigados`` reads OFS/FFS. What
this module can do without any guess:

* check the size and the boot block (DOS type, checksum, whether it is bootable)
* slice by track / sector (what a trackloader reads with ``trackdisk`` style
  ``cylinder, head, sector, count`` arguments)
* an entropy map per sector - the first measurement of any disk: where the
  code is (low entropy, repetitive 68k words), where packed data is (~8 bits),
  where empty sectors are (0), where graphics are (medium, structured)
* an inventory record (sha256, size, boot type) for the method's "measured
  description of the original"
"""
import hashlib
import math
import struct

SECTOR = 512
SECTORS_PER_TRACK = 11
TRACKS = 160                     # 80 cylinders x 2 heads
SIZE = SECTOR * SECTORS_PER_TRACK * TRACKS      # 901 120
TRACK_BYTES = SECTOR * SECTORS_PER_TRACK        # 5 632


class ADFError(ValueError):
    pass


def check_size(data):
    if len(data) != SIZE:
        raise ADFError('not a DD ADF: %d bytes (expected %d)' % (len(data), SIZE))


def track(data, n):
    """Bytes of track ``n`` (0..159; track = cylinder*2 + head)."""
    if not 0 <= n < TRACKS:
        raise ADFError('track out of range: %d' % n)
    return data[n * TRACK_BYTES:(n + 1) * TRACK_BYTES]


def sector(data, n):
    """Bytes of absolute sector ``n`` (0..1759)."""
    if not 0 <= n < TRACKS * SECTORS_PER_TRACK:
        raise ADFError('sector out of range: %d' % n)
    return data[n * SECTOR:(n + 1) * SECTOR]


def chs(sector_no):
    """Absolute sector -> (cylinder, head, sector)."""
    t, s = divmod(sector_no, SECTORS_PER_TRACK)
    c, h = divmod(t, 2)
    return c, h, s


def offset(cyl, head, sec=0):
    return ((cyl * 2 + head) * SECTORS_PER_TRACK + sec) * SECTOR


def bootblock_checksum(bb):
    """AmigaDOS boot block checksum (ones' complement sum of 256 longs with
    the checksum field treated as 0). Valid iff the result equals the stored
    long at offset 4."""
    s = 0
    for i in range(0, 1024, 4):
        if i == 4:
            continue
        s += struct.unpack_from('>I', bb, i)[0]
        if s > 0xffffffff:
            s = (s + 1) & 0xffffffff
    return (~s) & 0xffffffff


def bootblock(data):
    bb = data[:1024]
    dostype = bb[:4]
    stored = struct.unpack_from('>I', bb, 4)[0]
    calc = bootblock_checksum(bb)
    kind = 'unknown'
    if dostype[:3] == b'DOS':
        kind = 'DOS%d' % dostype[3]
    elif dostype == b'KICK':
        kind = 'KICK'
    return {'dostype': dostype.hex(), 'dostype_text': kind,
            'rootblock': struct.unpack_from('>I', bb, 8)[0],
            'checksum_stored': stored, 'checksum_calc': calc,
            'bootable': stored == calc and dostype[:3] == b'DOS',
            'code_words': bb[12:12 + 32].hex()}


def entropy(block):
    """Shannon entropy in bits per byte (0..8)."""
    if not block:
        return 0.0
    counts = [0] * 256
    for b in block:
        counts[b] += 1
    n = len(block)
    return -sum((c / n) * math.log2(c / n) for c in counts if c)


def entropy_map(data, unit=SECTOR):
    """List of (offset, entropy) per ``unit`` bytes."""
    return [(i, entropy(data[i:i + unit])) for i in range(0, len(data), unit)]


def classify(e, block=None):
    """Rough class for an entropy value measured over a 512-byte window.
    (Thresholds are for that window size: 512 uniformly random bytes only
    reach ~7.6 bits, so "packed" starts at 7.4, not at 8.)"""
    if block is not None and not any(block):
        return 'empty'
    if e < 0.5:
        return 'empty'
    if e < 5.0:
        return 'sparse'          # tables, text, bitplanes with lots of 0
    if e < 6.8:
        return 'code/data'       # 68k code typically sits 5.5-6.8
    if e < 7.4:
        return 'dense'           # graphics, samples
    return 'packed'              # compressed or random


def regions(data, unit=SECTOR, min_run=2):
    """Merge consecutive sectors with the same class into regions."""
    out = []
    for off, e in entropy_map(data, unit):
        c = classify(e, data[off:off + unit])
        if out and out[-1]['class'] == c:
            out[-1]['end'] = off + unit
            out[-1]['n'] += 1
            out[-1]['esum'] += e
        else:
            out.append({'start': off, 'end': off + unit, 'class': c, 'n': 1, 'esum': e})
    for r in out:
        r['entropy'] = r.pop('esum') / r['n']
        r['track_start'] = r['start'] // TRACK_BYTES
        r['track_end'] = (r['end'] - 1) // TRACK_BYTES
    return out


def inventory(data, name=''):
    check_size(data)
    bb = bootblock(data)
    return {'name': name, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'tracks': TRACKS, 'sectors': TRACKS * SECTORS_PER_TRACK,
            'bootblock': bb, 'entropy_mean': sum(e for _, e in entropy_map(data)) / (TRACKS * SECTORS_PER_TRACK),
            'empty_sectors': sum(1 for i in range(0, SIZE, SECTOR) if not any(data[i:i + SECTOR]))}


def ascii_map(data, cols=22):
    """One character per sector, 22 sectors (2 tracks) per line: a picture of
    the disk you can read in a terminal. ``.`` empty, ``-`` sparse, ``c``
    code/data, ``d`` dense, ``#`` packed."""
    sym = {'empty': '.', 'sparse': '-', 'code/data': 'c', 'dense': 'd', 'packed': '#'}
    chars = [sym[classify(e, data[o:o + SECTOR])] for o, e in entropy_map(data)]
    lines = []
    for i in range(0, len(chars), cols):
        t = (i // SECTORS_PER_TRACK)
        lines.append('trk %3d  %s' % (t, ''.join(chars[i:i + cols])))
    return '\n'.join(lines)
