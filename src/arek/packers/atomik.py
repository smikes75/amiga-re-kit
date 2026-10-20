"""Atomik (``ATN!``) decruncher (from the Superfrog project, where the loader
was read instruction by instruction and the decoder checked against the
emulator's RAM after unpacking).

Layout of a packed block (big endian)::

  'ATN!' | unpacked length | packed length P      12 B; in the file they
                                                  overwrite stream[0:12]
  stream[12:P]
  trailer, 46 B: the 12 overwritten stream bytes as three longs in reverse
                 order (stream[8:12], stream[4:8], stream[0:4])
                 | first literal count (4 B) | initial bit buffer (2 B)
                 | 8 signed shorts: distance bases | 12 B: distance bit widths

A block is therefore exactly P + 46 bytes long, which is what makes a hit
inside a disk image verifiable (``scan`` uses it). The stream is consumed
from its END. Literal bytes are popped raw; control bits come from a byte
buffer with a sentinel bit (68000 ``add.b d0,d0 / bne / move.b -(an),d0 /
addx.b``), eight data bits per byte, MSB first. Output is written from the
end. Each round: ``n`` literals, stop when the output is full, then one back
reference: length (unary 2..5, or escape: 3 bits -> 6..13, or a raw byte ->
1..255 with 0 meaning 256), the literal count of the NEXT round
(category-dependent widths and bases) and the distance (widths and bases
from the trailer tables).

``pack`` is a greedy test encoder (literals + back references) and
``pack_literal`` the single-run variant. They exist so the decoder can be
round-trip tested on synthetic data; the tables they write are their own
choice, the decoder is table driven. Real streams come from the games.
"""
import bisect
import struct

MAGIC = b'ATN!'
TRAILER = 46
LITERAL_BITS = (1, 1, 1, 1, 2, 3, 3, 4, 4, 5, 7, 14)
LITERAL_BASE_HI = (6, 10, 10, 18)
LITERAL_BASE_MID = 2


class FormatError(ValueError):
    pass


def is_atomik(data):
    return data[:4] == MAGIC


def header(data):
    """``{'unpacked', 'packed', 'length'}`` of the block starting at 0, or None.
    ``length`` is the whole block including the trailer."""
    if len(data) < 12 or data[:4] != MAGIC:
        return None
    unpacked, packed = struct.unpack_from('>II', data, 4)
    return {'unpacked': unpacked, 'packed': packed, 'length': packed + TRAILER}


def unpack(data, max_output=16 * 1024 * 1024):
    """Decode the ATN! block at the start of ``data`` (trailing bytes are
    ignored, so a slice of a disk image works). Raises FormatError on any
    inconsistency: bounds, final source pointer, sizes."""
    if len(data) < 12 + TRAILER or data[:4] != MAGIC:
        raise FormatError('missing ATN! header')
    output_size, packed_size = struct.unpack_from('>II', data, 4)
    if packed_size < 12 or packed_size + TRAILER > len(data):
        raise FormatError('truncated ATN! stream/trailer')
    if not 0 < output_size <= max_output:
        raise FormatError('invalid ATN! output size')
    source = bytearray(data[:packed_size])
    # Three MOVE.L (a2)+,-(a0) restore the overwritten stream header.
    for i in range(3):
        source[8 - 4 * i:12 - 4 * i] = data[packed_size + 4 * i:packed_size + 4 * i + 4]
    literal_count, initial_bits = struct.unpack_from('>IH', data, packed_size + 12)
    table = data[packed_size + 18:packed_size + TRAILER]
    offset_bases = struct.unpack_from('>8h', table)
    offset_bits = table[16:28]
    cursor = packed_size - (0 if initial_bits & 0x8000 else 1)
    bit_buffer = initial_bits & 255
    result = bytearray(output_size)
    dest = output_size

    def pop():
        nonlocal cursor
        cursor -= 1
        if cursor < 0:
            raise FormatError('ATN! source underrun')
        return source[cursor]

    def bit():
        nonlocal bit_buffer
        carry = bit_buffer >> 7
        bit_buffer = (bit_buffer << 1) & 255
        if bit_buffer == 0:
            value = pop()
            bit_buffer = ((value << 1) | carry) & 255
            carry = value >> 7
        return carry

    def bits(count):
        if not 1 <= count <= 32:
            raise FormatError('invalid ATN! bit count')
        value = 0
        for _ in range(count):
            value = (value << 1) | bit()
        return value

    while True:
        if literal_count > dest:
            raise FormatError('ATN! literal run exceeds output')
        for _ in range(literal_count):
            dest -= 1
            result[dest] = pop()
        if dest == 0:
            break
        length, category = 2, 0
        while category < 4 and bit():
            length += 1
            category += 1
        if category == 4:
            # Four leading ones: a fifth one selects a byte length.
            length = pop() if bit() else bits(3) + 6
            category = 3
        literal_index = category
        literal_base = 0
        if bit():
            if bit():
                literal_base = LITERAL_BASE_HI[category]
                literal_index += 8
            else:
                literal_base = LITERAL_BASE_MID
                literal_index += 4
        literal_count = (bits(LITERAL_BITS[literal_index]) + literal_base) & 65535
        offset_index = category
        offset_base = 0
        if bit():
            if bit():
                offset_base = offset_bases[4 + category]
                offset_index += 8
            else:
                offset_base = offset_bases[category]
                offset_index += 4
        distance = offset_base + 1 + bits(offset_bits[offset_index])
        # SUBQ.B loops 256 times for an initial zero length.
        length = length or 256
        if length > dest or distance < 1 or dest + distance > output_size:
            raise FormatError('invalid ATN! back reference')
        for _ in range(length):
            dest -= 1
            result[dest] = result[dest + distance]
    if cursor != 0:
        raise FormatError('ATN! final source pointer %d, expected 0' % cursor)
    return bytes(result)


# ----------------------------------------------------------------- test encoder
# Distance tables the test encoder writes into the trailer: widths 5 / 8 / 13
# bits with bases 0 / 32 / 288 -> distances 1..32, 33..288, 289..8480.
TEST_OFFSET_BITS = bytes((5, 5, 5, 5, 8, 8, 8, 8, 13, 13, 13, 13))
TEST_OFFSET_BASES = (32, 32, 32, 32, 288, 288, 288, 288)
MAX_DISTANCE = 288 + (1 << 13)
MAX_LENGTH = 256


def literal_max(category):
    """Largest literal count encodable after a match of this category."""
    return LITERAL_BASE_HI[category] + (1 << LITERAL_BITS[category + 8]) - 1


def _category(length):
    return length - 2 if length <= 5 else 3


class _Writer:
    """Builds the stream in DECODER READ ORDER. A control byte is allocated
    at the moment the decoder would pop it (its first bit), raw bytes
    (literals, byte lengths) go where they are popped. ``prime`` control bits
    are kept in the trailer's initial buffer instead of the stream."""

    def __init__(self, prime=0):
        if not 0 <= prime <= 7:
            raise ValueError('prime must be 0..7')
        self.out = bytearray()
        self.prime = prime
        self.initial = 0x80                  # sentinel only
        self.idx = None
        self.acc = 0
        self.n = 0
        self.cap = 8
        self.first = True

    def bit(self, b):
        if self.n == 0:
            if self.first and self.prime:
                self.cap, self.idx = self.prime, None
            else:
                self.cap, self.idx = 8, len(self.out)
                self.out.append(0)
            self.first = False
        self.acc = (self.acc << 1) | b
        self.n += 1
        if self.n == self.cap:
            self._flush()

    def _flush(self):
        if self.idx is None:
            self.initial = ((self.acc << (8 - self.n)) | (1 << (7 - self.n))) & 255
        else:
            self.out[self.idx] = (self.acc << (8 - self.n)) & 255
        self.acc = self.n = 0

    def bits(self, value, count):
        for i in range(count - 1, -1, -1):
            self.bit((value >> i) & 1)

    def byte(self, v):
        self.out.append(v & 255)

    def finish(self):
        if self.n:
            self._flush()
        return bytes(reversed(self.out))


def _put_length(w, length):
    if length <= 5:
        for _ in range(length - 2):
            w.bit(1)
        w.bit(0)
        return length - 2
    w.bits(0b1111, 4)
    if length <= 13:
        w.bit(0)
        w.bits(length - 6, 3)
    else:
        w.bit(1)
        w.byte(length & 255)              # 256 -> 0
    return 3


def _put_literal_count(w, category, n):
    if n <= 1:
        w.bit(0)
        w.bits(n, 1)
    elif n < LITERAL_BASE_HI[category]:
        w.bit(1)
        w.bit(0)
        w.bits(n - LITERAL_BASE_MID, LITERAL_BITS[category + 4])
    else:
        if n > literal_max(category):
            raise ValueError('literal run too long for category %d' % category)
        w.bit(1)
        w.bit(1)
        w.bits(n - LITERAL_BASE_HI[category], LITERAL_BITS[category + 8])


def _put_distance(w, category, distance):
    v = distance - 1
    if v < (1 << TEST_OFFSET_BITS[category]):
        w.bit(0)
        w.bits(v, TEST_OFFSET_BITS[category])
    elif v - TEST_OFFSET_BASES[category] < (1 << TEST_OFFSET_BITS[category + 4]):
        w.bit(1)
        w.bit(0)
        w.bits(v - TEST_OFFSET_BASES[category], TEST_OFFSET_BITS[category + 4])
    else:
        if v - TEST_OFFSET_BASES[4 + category] >= (1 << TEST_OFFSET_BITS[category + 8]):
            raise ValueError('distance %d out of range' % distance)
        w.bit(1)
        w.bit(1)
        w.bits(v - TEST_OFFSET_BASES[4 + category], TEST_OFFSET_BITS[category + 8])


def _tokenize(data, window):
    """Greedy, from the end (decoder order): ``first`` literals, then
    ``[length, distance, literals_after]`` per back reference."""
    n = len(data)
    ends = {}
    for i in range(n - 1):
        ends.setdefault(bytes(data[i:i + 2]), []).append(i + 2)
    first, matches, lit, dest = None, [], 0, n
    while dest > 0:
        best = None
        if dest >= 2:
            cands = ends.get(bytes(data[dest - 2:dest]), ())
            for e in cands[bisect.bisect_right(cands, dest):][:32]:
                d = e - dest
                if d > window:
                    break
                max_len = min(MAX_LENGTH, dest)
                ln = 2
                while ln < max_len and data[dest - 1 - ln] == data[dest - 1 - ln + d]:
                    ln += 1
                if best is None or ln > best[0]:
                    best = (ln, d)
        if best:
            if first is None:
                first = lit
            else:
                matches[-1][2] = lit
            lit = 0
            matches.append([best[0], best[1], 0])
            dest -= best[0]
        else:
            lit += 1
            dest -= 1
    if first is None:
        first = lit
    else:
        matches[-1][2] = lit
    return first, matches


def _fit_literal_runs(first, matches):
    """A literal run after a match is bounded by the match's category; a run
    that does not fit swallows its match (the match becomes literals)."""
    while True:
        bad = next((k for k, m in enumerate(matches) if m[2] > literal_max(_category(m[0]))), None)
        if bad is None:
            return first, matches
        ln, _, lit = matches.pop(bad)
        if bad == 0:
            first += ln + lit
        else:
            matches[bad - 1][2] += ln + lit


def _assemble(out_len, stream, first_literals, initial_bits, bases=TEST_OFFSET_BASES,
              widths=TEST_OFFSET_BITS):
    packed = len(stream)
    if packed < 12:
        raise ValueError('stream shorter than 12 bytes cannot carry the header')
    return (MAGIC + struct.pack('>II', out_len, packed) + stream[12:]
            + stream[8:12] + stream[4:8] + stream[0:4]
            + struct.pack('>IH', first_literals, initial_bits)
            + struct.pack('>8h', *bases) + bytes(widths))


def pack_literal(data, skip_last=False):
    """One literal run, no control bits (valid, inefficient). ``skip_last``
    exercises the loader state where the trailer's initial-buffer word has
    bit 15 clear and the last stream byte is not consumed."""
    if len(data) < 12:
        raise ValueError('ATN! needs at least 12 stream bytes')
    stream = bytes(data) + (b'\0' if skip_last else b'')
    return _assemble(len(data), stream, len(data), 0x80 | (0 if skip_last else 0x8000))


def pack(data, prime=0, window=MAX_DISTANCE):
    """Greedy LZ test encoder: literals and back references, ``prime`` control
    bits (0..7) stored in the trailer's initial buffer."""
    n = len(data)
    if n == 0:
        raise ValueError('empty input')
    data = bytes(data)
    first, matches = _fit_literal_runs(*_tokenize(data, min(window, MAX_DISTANCE)))
    w = _Writer(prime)
    dest = n
    for _ in range(first):
        dest -= 1
        w.byte(data[dest])
    for ln, d, lit in matches:
        cat = _put_length(w, ln)
        _put_literal_count(w, cat, lit)
        _put_distance(w, cat, d)
        dest -= ln
        for _ in range(lit):
            dest -= 1
            w.byte(data[dest])
    assert dest == 0
    stream = w.finish()
    if len(stream) < 12:
        return pack_literal(data)
    return _assemble(n, stream, first, 0x8000 | w.initial)
