"""Rob Northen Compression, method 1 (``RNC\\x01``, ProPack): the decruncher and a naive packer for the tests
(kit 1.0.21, Xenon 2's KIT-GAP 1: ``arek scan`` knew the signature, the kit had no unpacker).

Header (18 bytes, big-endian)::

  'RNC' | method (1) | unpacked length (4) | packed length (4) | CRC-16 of the unpacked data (2)
  | CRC-16 of the packed data (2) | leeway (1) | number of chunks (1) | packed data

CRC-16: polynomial 0xA001 (reflected 0x8005), initial value 0, no final xor - the CRC of the loader routine.

Method 1 is a bit stream of 16-bit little-endian words read from the lowest bit up, with the raw bytes of a
segment stored in the byte stream itself: a chunk starts with three Huffman tables (the raw lengths, the
distances, the lengths - each as ``num`` (5 bits) code lengths of 4 bits, canonical codes by length then symbol,
the code bits mirrored) and a 16-bit count of segments; a segment is a raw run (its length from the first table,
the bytes copied straight from the stream, the bit reader then re-primed) and, but for the last one, a match
(distance - 1 and length - 2 from the other two tables). A table symbol v >= 2 stands for the numbers
2^(v-1) .. 2^v - 1 and is followed by v - 1 extra bits. The decoder keeps the exact reading discipline of the
original (a word prefetched past the one being consumed; the raw bytes take the prefetched word's place), so a
stream packed by any ProPack unpacks here; both CRCs are verified. Method 2 (``RNC\\x02``) is recognised and
refused.

``pack`` is a deliberately naive packer (greedy matches, uniform code lengths) that exists so the decoder is
round-trip tested without any game data; its streams unpack with the original decoder's rules.
"""
import struct

MAGIC1 = b'RNC\x01'
MAGIC2 = b'RNC\x02'
HEADER = 18
_CRC = []
for _i in range(256):
    _v = _i
    for _ in range(8):
        _v = (_v >> 1) ^ 0xA001 if _v & 1 else _v >> 1
    _CRC.append(_v)


def crc16(data):
    v = 0
    for b in data:
        v ^= b
        v = (v >> 8) ^ _CRC[v & 0xff]
    return v


def is_rnc(data, offset=0):
    return data[offset:offset + 3] == b'RNC' and data[offset + 3:offset + 4] in (b'\x01', b'\x02')


def info(data, offset=0):
    """The header fields at ``offset`` (``method``, ``unpacked``, ``packed``, ``crc_out``, ``crc_in``, ``leeway``,
    ``chunks``, ``start`` of the packed data)."""
    h = data[offset:offset + HEADER]
    if len(h) < HEADER or h[:3] != b'RNC':
        raise ValueError('missing RNC header at offset 0x%x' % offset)
    unpacked, packed, crc_out, crc_in = struct.unpack('>IIHH', h[4:16])
    return {'method': h[3], 'unpacked': unpacked, 'packed': packed, 'crc_out': crc_out, 'crc_in': crc_in,
            'leeway': h[16], 'chunks': h[17], 'start': offset + HEADER}


def _mirror(x, n):
    r = 0
    for _ in range(n):
        r = (r << 1) | (x & 1)
        x >>= 1
    return r


class _Bits:
    """The original's bit reader: ``p`` is the word last loaded (the prefetch), the low ``n - 16`` bits of ``buf``
    are what remains of the word before it; raw bytes start at ``p`` and re-prime the buffer."""

    def __init__(self, data, pos):
        self.data = data
        self.p = pos
        self.buf = self._word(pos)
        self.n = 16

    def _word(self, p):
        d = self.data
        return (d[p] if p < len(d) else 0) | ((d[p + 1] if p + 1 < len(d) else 0) << 8)

    def peek(self, mask):
        return self.buf & mask

    def advance(self, k):
        self.buf >>= k
        self.n -= k
        if self.n < 16:
            self.p += 2
            self.buf |= self._word(self.p) << self.n
            self.n += 16

    def read(self, k):
        v = self.buf & ((1 << k) - 1)
        self.advance(k)
        return v

    def raw(self, count):
        if self.p + count > len(self.data):
            raise ValueError('RNC stream exhausted (corrupt data?)')
        out = self.data[self.p:self.p + count]
        self.p += count
        self.n -= 16
        self.buf &= (1 << self.n) - 1
        self.buf |= self._word(self.p) << self.n
        self.n += 16
        return out


def _table(bs):
    num = bs.read(5)
    if not num:
        return []
    lens = [bs.read(4) for _ in range(num)]
    entries, codeb = [], 0
    for i in range(1, max(lens) + 1):
        for j in range(num):
            if lens[j] == i:
                entries.append((_mirror(codeb, i), i, j))
                codeb += 1
        codeb <<= 1
    return entries


def _huf(bs, table):
    for code, ln, val in table:
        if bs.peek((1 << ln) - 1) == code:
            bs.advance(ln)
            break
    else:
        raise ValueError('RNC Huffman code not in the table (corrupt data?)')
    if val >= 2:
        val = (1 << (val - 1)) | bs.read(val - 1)
    return val


def unpack(data, offset=0):
    """The unpacked bytes of the RNC method 1 block at ``offset``; both CRCs verified, a mismatch raises."""
    h = info(data, offset)
    if h['method'] != 1:
        raise ValueError('RNC method %d: only method 1 is unpacked here' % h['method'])
    body = bytes(data[h['start']:h['start'] + h['packed']])
    if len(body) < h['packed']:
        raise ValueError('RNC block truncated: %d of %d packed bytes' % (len(body), h['packed']))
    if crc16(body) != h['crc_in']:
        raise ValueError('RNC packed CRC mismatch: %04x, header %04x' % (crc16(body), h['crc_in']))
    bs = _Bits(body, 0)
    bs.advance(2)
    out = bytearray()
    want = h['unpacked']
    while len(out) < want:
        before = len(out)
        raw_t, dist_t, len_t = _table(bs), _table(bs), _table(bs)
        count = bs.read(16)
        while True:
            n = _huf(bs, raw_t)
            if n:
                out += bs.raw(n)
            count -= 1
            if count <= 0:
                break
            posn = _huf(bs, dist_t) + 1
            ln = _huf(bs, len_t) + 2
            if posn > len(out):
                raise ValueError('RNC match before the start of the output (corrupt data?)')
            if posn >= ln:
                out += out[-posn:len(out) - posn + ln]
            else:
                for _ in range(ln):
                    out.append(out[-posn])
            if len(out) > want:
                raise ValueError('RNC output longer than the header says (corrupt data?)')
        if len(out) == before:
            raise ValueError('RNC chunk produced nothing (corrupt data?)')
    if crc16(out) != h['crc_out']:
        raise ValueError('RNC unpacked CRC mismatch: %04x, header %04x' % (crc16(out), h['crc_out']))
    return bytes(out)


# ----------------------------------------------------------------- the naive packer (tests only)
class _Writer:
    """The inverse of _Bits: a word being filled stays where it was opened, raw bytes go after it, the next bits still
    fill it - the layout the reader's prefetch expects."""

    def __init__(self):
        self.out = bytearray()
        self.wpos = None
        self.nbits = 0
        self.word = 0

    def bits(self, value, n):
        for i in range(n):
            if self.wpos is None:
                self.wpos = len(self.out)
                self.out += b'\0\0'
                self.nbits = self.word = 0
            self.word |= ((value >> i) & 1) << self.nbits
            self.nbits += 1
            if self.nbits == 16:
                self.out[self.wpos] = self.word & 0xff
                self.out[self.wpos + 1] = self.word >> 8
                self.wpos = None

    def raw(self, b):
        self.out += b

    def finish(self):
        if self.wpos is not None:
            self.out[self.wpos] = self.word & 0xff
            self.out[self.wpos + 1] = self.word >> 8
            self.wpos = None
        return bytes(self.out)


def _symbol(n):
    """The table symbol of the number n: 0, 1, or the bit length of n (>= 2); the extra bits follow."""
    return n if n < 2 else n.bit_length()


def _codes(symbols):
    """Code lengths and codes for the used symbols: one code of length 1 for a single symbol, else uniform lengths -
    the canonical construction of the decoder, so the table it reads back is this one."""
    used = sorted(set(symbols))
    if not used:
        return [], {}
    num = max(used) + 1
    ln = 1 if len(used) == 1 else max(1, (len(used) - 1).bit_length())
    lens = [ln if j in used else 0 for j in range(num)]
    codes, codeb = {}, 0
    for i in range(1, max(lens) + 1):
        for j in range(num):
            if lens[j] == i:
                codes[j] = (_mirror(codeb, i), i)
                codeb += 1
        codeb <<= 1
    return lens, codes


def _write_table(w, lens):
    w.bits(len(lens), 5)
    for ln in lens:
        w.bits(ln, 4)


def _put(w, codes, n):
    s = _symbol(n)
    code, ln = codes[s]
    w.bits(code, ln)
    if s >= 2:
        w.bits(n - (1 << (s - 1)), s - 1)


def _segments(data, window=0xffff, maxlen=0x7fff):
    """Greedy LZ: (raw bytes, distance, length) with the last segment's match None."""
    segs, raw, pos, n = [], bytearray(), 0, len(data)
    heads = {}
    while pos < n:
        best_len, best_dist = 0, 0
        key = data[pos:pos + 3]
        if len(key) == 3:
            for q in heads.get(key, ())[-48:][::-1]:
                if pos - q > window:
                    break
                ln = 3
                while ln < maxlen and pos + ln < n and data[q + ln] == data[pos + ln]:
                    ln += 1
                if ln > best_len:
                    best_len, best_dist = ln, pos - q
        if best_len >= 3:
            segs.append((bytes(raw), best_dist, best_len))
            raw = bytearray()
            for i in range(best_len):
                k = data[pos + i:pos + i + 3]
                if len(k) == 3:
                    heads.setdefault(k, []).append(pos + i)
            pos += best_len
        else:
            raw.append(data[pos])
            if len(key) == 3:
                heads.setdefault(key, []).append(pos)
            pos += 1
    segs.append((bytes(raw), None, None))
    return segs


def pack(data, leeway=0):
    """A valid RNC method 1 block of ``data`` (naive: greedy matches, uniform code lengths); for the tests."""
    data = bytes(data)
    segs = _segments(data) if data else []
    chunks = [segs[i:i + 0xfffe] for i in range(0, len(segs), 0xfffe)]      # room for the raw-only segment that closes a chunk
    for c in chunks[:-1]:                                  # every chunk but the last ends with a raw-only segment
        c[-1] = (c[-1][0], None, None) if c[-1][1] is None else c[-1]
    fixed = []
    for c in chunks:
        if c[-1][1] is not None:
            c = c + [(b'', None, None)]
        fixed.append(c)
    w = _Writer()
    w.bits(0, 2)
    for c in fixed:
        raw_lens, codes_r = _codes([_symbol(len(r)) for r, _, _ in c])
        dist_lens, codes_d = _codes([_symbol(d - 1) for _, d, _ in c if d is not None])
        len_lens, codes_l = _codes([_symbol(ln - 2) for _, _, ln in c if ln is not None])
        _write_table(w, raw_lens)
        _write_table(w, dist_lens)
        _write_table(w, len_lens)
        w.bits(len(c), 16)
        for k, (r, d, ln) in enumerate(c):
            _put(w, codes_r, len(r))
            if r:
                w.raw(r)
            if k == len(c) - 1:
                break
            _put(w, codes_d, d - 1)
            _put(w, codes_l, ln - 2)
    body = w.finish()
    return MAGIC1 + struct.pack('>IIHHBB', len(data), len(body), crc16(data), crc16(body), leeway, len(fixed)) + body
