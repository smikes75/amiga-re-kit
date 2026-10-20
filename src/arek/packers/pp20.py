"""PowerPacker 2.0 (``PP20``) decruncher (from the Turrican II / Superfrog projects).

Format (verified against the loader routine and byte-for-byte against the
emulator's RAM after unpacking)::

  'PP20' | 4 B efficiency table (offset bit counts for match lengths 2,3,4,5+)
  | packed data | last 4 B: (unpacked length << 8) | number of unused bits
  in the final long word.

Bits are read from the end (lowest bit of the last long first), output is
written from the end. Bit 0 -> literals: count = 1 + sum of 2-bit groups
(3 = continue); then (or directly on bit 1) a match: 2 bits = length-2
(3 = more bits), offset width from the table (for length 5+ one bit selects
7 or the table width), length 5+ = 5 + sum of 3-bit groups (7 = continue).

``pack_literal`` is a deliberately naive encoder (literals only) that exists
so the decoder can be round-trip tested without any game data.
"""
import struct

MAGIC = b'PP20'


class _Bits:
    """Bits come from the end of the data: last long, from its lowest bit
    (68000: ``move.l -(a0),d1`` + ``lsr.l``); values assemble MSB first."""

    def __init__(self, data, skip):
        self.data = data
        self.pos = len(data)
        self.buf = 0
        self.n = 0
        self.get(skip)

    def get(self, count):
        v = 0
        for _ in range(count):
            if self.n == 0:
                self.pos -= 4
                if self.pos < 0:
                    raise ValueError('PP20 stream exhausted (corrupt data?)')
                self.buf = struct.unpack('>I', self.data[self.pos:self.pos + 4])[0]
                self.n = 32
            v = (v << 1) | (self.buf & 1)
            self.buf >>= 1
            self.n -= 1
        return v


def is_pp20(data):
    return data[:4] == MAGIC


def unpacked_length(data):
    return struct.unpack('>I', data[-4:])[0] >> 8


def unpack(src):
    if src[:4] != MAGIC:
        raise ValueError('missing PP20 header')
    eff = src[4:8]
    tail = struct.unpack('>I', src[-4:])[0]
    out_len = tail >> 8
    skip = tail & 0xff
    bits = _Bits(src[8:-4], skip)
    out = bytearray(out_len)
    o = out_len
    while o > 0:
        if bits.get(1) == 0:
            n = 1
            while True:
                x = bits.get(2)
                n += x
                if x != 3:
                    break
            for _ in range(n):
                o -= 1
                out[o] = bits.get(8)
            if o == 0:
                break
        ln = bits.get(2)
        nb = eff[ln]
        if ln == 3:
            if bits.get(1) == 0:
                nb = 7
            off = bits.get(nb)
            ln = 5
            while True:
                x = bits.get(3)
                ln += x
                if x != 7:
                    break
        else:
            off = bits.get(nb)
            ln += 2
        for _ in range(ln):
            o -= 1
            out[o] = out[o + off + 1]
    return bytes(out)


class _BitWriter:
    """Mirror of _Bits for the test encoder: values are emitted MSB first into a
    stream that the decoder reads from the end, lowest bit first."""

    def __init__(self):
        self.bits = []          # in decoder read order

    def put(self, value, count):
        for i in range(count - 1, -1, -1):
            self.bits.append((value >> i) & 1)

    def finish(self):
        # The decoder discards ``skip`` bits first, so padding goes at the
        # START of the read sequence. Read order: last long, bit 0 upwards.
        pad = (-len(self.bits)) % 32
        seq = [0] * pad + self.bits
        longs = []
        for i in range(0, len(seq), 32):
            v = 0
            for k, b in enumerate(seq[i:i + 32]):
                v |= b << k
            longs.append(v)
        longs.reverse()                      # chunk 0 must be the last long
        return b''.join(struct.pack('>I', w) for w in longs), pad


def pack_literal(data, eff=b'\x09\x0a\x0a\x0b'):
    """Encode ``data`` as PP20 using a single literal run (valid, inefficient).
    Exists for tests; real PowerPacker streams come from the games."""
    if not data:
        raise ValueError('empty input')
    w = _BitWriter()
    w.put(0, 1)                                   # literal run follows
    rem = len(data) - 1                           # count = 1 + sum of 2-bit groups
    while True:
        g = min(rem, 3)
        w.put(g, 2)
        rem -= g
        if g != 3:
            break
    for b in data[::-1]:                          # decoder writes from the end
        w.put(b, 8)
    stream, skip = w.finish()
    tail = struct.pack('>I', (len(data) << 8) | skip)
    return MAGIC + bytes(eff) + stream + tail
