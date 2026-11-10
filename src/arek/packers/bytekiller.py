"""Bytekiller-family decrunchers (from the S.W.I.V. project's ``depack.py``).

The SWIV disk used no known packer; it carried two of its own and their
unpack routines. Both read the stream BACKWARDS from the end and write
backwards from the end of the target block, and both share an 8-byte header::

    +0  long  unpacked length
    +4  long  packed stream length (from +8)

Format B is the classic *Bytekiller* (longword stream, bits from the low end,
values MSB first, an XOR checksum over all longs that must end at 0 - a free
integrity check). Format A reads WORDS, numbers taken from the low end of a
register (LSB first), no checksum but a richer code: match lengths of
1/2/4/8 bits with bases 1/3/7/23, offsets 5/9/14 bits with bases 0/32/544;
length 23 is stolen as the escape for long literal runs.

Format BK (kit 1.0.4, Turrican II's cracktro layer at $40024, reported by the
Turrican-recomp project) is the same classic Bytekiller code with the ORIGINAL
12-byte header::

    +0  long  packed stream length (from +12)
    +4  long  unpacked length
    +8  long  checksum: the decruncher starts d5 there and XORs every long it
              reads; d5 must end at 0

so there is no checksum long inside the stream and no extra long read at the
end. ``unpack_bk(data, off)`` -> (bytes, checksum_ok); ``detect(data, off)``
tells which of B / BK verifies at an offset.

``unpack_b(data, off)`` -> (bytes, checksum_ok); ``unpack_a(data, off)`` -> (bytes, True).
``pack_b_literal`` / ``pack_bk_literal`` are literal-only encoders for round-trip tests.
"""


import bisect
import struct


class BitReader:
    """Cte bity pozpatku, presne jako getbit na 0x82.

        lsr.l #1,d0      ; C = X = spodni bit, d0 >>= 1
        bne.s  hotovo    ; longword jeste neni vycerpany
        move.l -(a0),d0  ; dobrat dalsi (pozpatku), X zustava
        eor.l  d0,d5     ; kontrolni soucet
        roxr.l #1,d0     ; X -> bit31, novy spodni bit -> C
    """

    def __init__(self, data, end, checksum=0, start=0):
        if end > len(data) or end < start + 4:
            raise ValueError("the packed stream (%d-%d) is not inside the data (%d bytes)" % (start, end, len(data)))
        self.data = data
        self.start = start      # 1.0.39: the stream's first byte - reading below it is an error, not the bytes before the block
        self.pos = end          # a0, ukazuje ZA konec proudu
        self.checksum = checksum  # d5 (format BK starts it at the header's checksum)
        self.buf = self._long()  # d0

    def _long(self):
        self.pos -= 4
        if self.pos < self.start:
            raise ValueError("the packed stream ran out - damaged data or a wrong offset")
        v = int.from_bytes(self.data[self.pos:self.pos + 4], "big")
        self.checksum ^= v
        return v

    def bit(self):
        c = self.buf & 1
        self.buf >>= 1
        if self.buf:
            return c
        # longword vycerpany: c je zarazka, ne data
        new = self._long()
        self.buf = (c << 31) | (new >> 1)
        return new & 1

    def bits(self, n):
        """n bitu, nejvyssi napred (addx.l d2,d2 ve smycce na 0x76)."""
        v = 0
        for _ in range(n):
            v = (v << 1) | self.bit()
        return v


def _decode_b(br, size):
    """The classic Bytekiller code (formats B and BK share it): writes backwards into ``size`` bytes."""
    out = bytearray(size)
    p = size                                    # a1, zapis pozpatku

    def literals(n):
        nonlocal p
        if p - n < 0:                           # 1.0.43: a negative index wrote over the END of the output without a word
            raise ValueError("a literal run passes the start of the output - damaged data or a wrong offset")
        for _ in range(n):
            p -= 1
            out[p] = br.bits(8)

    def match(length, offset):
        nonlocal p
        s = p + offset
        if p - length < 0 or s > size:
            raise ValueError("a match passes the output - damaged data or a wrong offset")
        for _ in range(length):
            s -= 1
            p -= 1
            out[p] = out[s]

    while p > 0:
        if br.bit() == 0:
            if br.bit() == 0:
                literals(br.bits(3) + 1)        # 1..8 literalu
            else:
                match(2, br.bits(8))            # delka 2, offset 8 bitu
        else:
            sel = br.bits(2)
            if sel == 0:
                match(3, br.bits(9))            # delka 3, offset 9 bitu
            elif sel == 1:
                match(4, br.bits(10))           # delka 4, offset 10 bitu
            elif sel == 2:
                n = br.bits(8) + 1              # delka 1..256
                match(n, br.bits(12))           # offset 12 bitu
            else:
                literals(br.bits(8) + 9)        # 9..264 literalu

    return out


def unpack_b(data, off=0):
    """Rozbali blok na offsetu off. Vraci (data, ok_checksum)."""
    size = int.from_bytes(data[off:off + 4], "big")
    packed = int.from_bytes(data[off + 4:off + 8], "big")
    if size == 0 or size > 8 << 20:
        raise ValueError("implausible unpacked length: %d" % size)
    if packed < 4 or off + 8 + packed > len(data):     # 1.0.39: a length past the data read as zeros and "verified" (checksum 0)
        raise ValueError("implausible packed length: %d" % packed)

    br = BitReader(data, off + 8 + packed, start=off + 8)
    out = _decode_b(br, size)
    br._long()                                  # zaverecny longword (0x9c)
    return bytes(out), br.checksum == 0

def unpack_bk(data, off=0):
    """Format BK: the classic 12-byte header (packed length, unpacked length, checksum). Returns (data, ok_checksum)."""
    packed = int.from_bytes(data[off:off + 4], "big")
    size = int.from_bytes(data[off + 4:off + 8], "big")
    chk = int.from_bytes(data[off + 8:off + 12], "big")
    if size == 0 or size > 8 << 20:
        raise ValueError("implausible unpacked length: %d" % size)
    if packed < 4 or off + 12 + packed > len(data):
        raise ValueError("implausible packed length: %d" % packed)
    br = BitReader(data, off + 12 + packed, chk, start=off + 12)
    out = _decode_b(br, size)
    return bytes(out), br.checksum == 0


def _decode_c(br, size):
    """The second code table met behind a TAIL block (1.0.44, Xenon 2 KIT-GAP 17, written from that session's
    disassembly of the decruncher): every step is a COUNT of literals (possibly 0) followed by one match, backwards
    into ``size`` bytes; the bit reader is the classic one."""
    out = bytearray(size)
    p = size
    while True:
        n = br.bits(3)
        if n == 7:
            if br.bit() == 0:
                n = br.bits(4) + 7
            else:
                n = br.bits(10)
                if n == 0:
                    n = br.bits(18)
        if p - n < 0:
            raise ValueError("a literal run passes the start of the output - damaged data or a wrong offset")
        for _ in range(n):
            p -= 1
            out[p] = br.bits(8)
        if p == 0:
            break
        c = br.bits(2)
        if c == 0:
            length, width = 2, 8
        elif c == 1:
            length, width = 3, (8 if br.bit() else 14)
        else:
            if c == 2:
                length = 4
            else:
                e = br.bits(2)
                length = br.bits(8) if e == 3 else br.bits(2) + 7 if e == 2 else e + 5
            width = 16 if br.bit() == 0 else 8 if br.bit() else 12
        ofs = br.bits(width)
        if p - length < 0 or ofs == 0 or p - 1 + ofs >= size:
            raise ValueError("a match passes the output - damaged data or a wrong offset")
        for _ in range(length):
            p -= 1
            out[p] = out[p + ofs]
        if p == 0:
            break
    return out


TAIL_CODES = {'b': _decode_b, 'c': _decode_c}


def unpack_tail(data, off=0, end=None, code='b'):
    """Format TAIL (1.0.43, Xenon 2 KIT-GAP 17): a crunched block whose parameters are at its END - the decruncher of
    a packed executable points a0 behind the block and takes ``move.l -(a0),a2`` (the unpacked length) and
    ``move.l -(a0),d0`` (the first bit word); the code follows downwards to the block's start ``off``. ``end``: the
    offset behind the block (default: the end of the data). ``code``: 'b' the classic Bytekiller table, 'c' the table
    of counted literal runs (1.0.44) - the layout does not say which, so the caller names it (``unpack_tail_any``
    tries both). There is no checksum in this layout: the second value says whether the bit stream was used up
    exactly at ``off`` - the only evidence the format offers. Returns (data, consumed_exactly)."""
    if code not in TAIL_CODES:
        raise ValueError("code is 'b' or 'c', not %r" % (code,))
    end = len(data) if end is None else end
    if end - off < 8 or end > len(data) or (end - off) % 4:           # 1.0.44: one bit word and the length is the smallest block
        raise ValueError("a TAIL block is whole longs between its start and its end (%d bytes)" % (end - off))
    size = int.from_bytes(data[end - 4:end], "big")
    if size == 0 or size > 8 << 20:
        raise ValueError("implausible unpacked length: %d (the last long of the block)" % size)
    br = BitReader(data, end - 4, start=off)
    out = TAIL_CODES[code](br, size)
    return bytes(out), br.pos == off


def unpack_tail_any(data, off=0, end=None):
    """Try both code tables on a TAIL block. Returns (data, code) of the ONE table that decodes it and uses the bit
    stream up exactly; raises when none or both do (an answer picked from two equal candidates would be a guess)."""
    hits, errors = [], []
    for code in sorted(TAIL_CODES):
        try:
            out, exact = unpack_tail(data, off, end, code)
        except ValueError as e:
            errors.append('%s: %s' % (code, e))
            continue
        if exact:
            hits.append((out, code))
        else:
            errors.append('%s: decoded, but the bit stream was not used up exactly' % code)
    if len(hits) != 1:
        raise ValueError('TAIL block: %s' % ('both code tables decode it exactly - name the code' if hits else '; '.join(errors)))
    return hits[0]


def _bit_stream(bits):
    """Bits in decoder read order -> the backwards longword stream (the sentinel rule of ``BitReader.bit``: the long
    read FIRST holds k <= 31 payload bits under a 1 bit, every later long 32)."""
    longs = []
    k = len(bits) % 32
    v = 1 << k
    for i, b in enumerate(bits[:k]):
        v |= b << i
    longs.append(v)
    for j in range(k, len(bits), 32):
        v = 0
        for i, b in enumerate(bits[j:j + 32]):
            v |= b << i
        longs.append(v)
    longs.reverse()
    return b''.join(struct.pack('>I', v) for v in longs)


def pack_tail_literal(data):
    """A TAIL block of literal runs only (for tests): the backwards longword stream, then the unpacked length."""
    b = pack_b_literal(data)
    return b[8 + 4:] + struct.pack('>I', len(data))


def pack_tail_c(data, window=65535):
    """A TAIL block in code 'c' (for tests and round trips; a plain greedy search, slow on large data): counted literal
    runs and matches of 2..255 bytes."""
    if not data:
        raise ValueError('empty input')
    size = len(data)
    bits = []

    def put(v, n):
        for i in range(n - 1, -1, -1):
            bits.append((v >> i) & 1)

    # the positions of every byte pair, so a match is looked for only where its first two bytes are (1.0.45: every
    # offset of the window was tried at every position - 20 KB took minutes)
    pairs = {}
    for q in range(size - 1):
        pairs.setdefault(data[q:q + 2], []).append(q)

    def find(p):                                 # the longest match for the bytes below p: (length, ofs)
        best = (0, 0)
        if p < 2:
            return best
        lst = pairs.get(data[p - 2:p], ())
        for k in range(bisect.bisect_left(lst, p - 1), min(len(lst), bisect.bisect_left(lst, p - 1) + 64)):   # the nearest 64
            ofs = lst[k] + 2 - p                             # the pair ends at q + 2 = p + ofs
            if ofs > window:
                break
            n = 2
            while n < 255 and p - n - 1 >= 0 and data[p - n - 1] == data[p - n - 1 + ofs]:
                n += 1
            if n == 2 and ofs > 255 or n == 3 and ofs > 16383:
                n = 2 if n == 3 and ofs <= 255 else 0
            if n > best[0] or n == best[0] and n and ofs < best[1]:
                best = (n, ofs)
        return best if best[0] >= 2 else (0, 0)

    p = size
    while p > 0:
        lits = []
        m = (0, 0)
        while p > 0:
            m = find(p)
            if m[0]:
                break
            p -= 1
            lits.append(data[p])
        n = len(lits)
        if n >= 1 << 18:
            raise ValueError('a literal run of %d bytes does not fit the code' % n)
        if n < 7:
            put(n, 3)
        elif n <= 22:
            put(7, 3); put(0, 1); put(n - 7, 4)
        elif n < 1024:
            put(7, 3); put(1, 1); put(n, 10)
        else:
            put(7, 3); put(1, 1); put(0, 10); put(n, 18)
        for v in lits:
            put(v, 8)
        if p == 0:
            break
        length, ofs = m
        if length == 2:
            put(0, 2); put(ofs, 8)
        elif length == 3:
            put(1, 2)
            if ofs < 256:
                put(1, 1); put(ofs, 8)
            else:
                put(0, 1); put(ofs, 14)
        else:
            if length == 4:
                put(2, 2)
            elif length <= 6:
                put(3, 2); put(length - 5, 2)
            elif length <= 10:
                put(3, 2); put(2, 2); put(length - 7, 2)
            else:
                put(3, 2); put(3, 2); put(length, 8)
            if ofs < 256:
                put(1, 1); put(1, 1); put(ofs, 8)
            elif ofs < 4096:
                put(1, 1); put(0, 1); put(ofs, 12)
            else:
                put(0, 1); put(ofs, 16)
        p -= length
    return _bit_stream(bits) + struct.pack('>I', size)


def detect(data, off=0):
    """Which header layout verifies at ``off``: 'bk', 'b' or None (both decoded, both checksums checked)."""
    for fmt, fn in (('bk', unpack_bk), ('b', unpack_b)):
        try:
            _, ok = fn(data, off)
        except (ValueError, IndexError):
            ok = False
        if ok:
            return fmt
    return None



class BitReaderA:
    """Cte bity po wordech pozpatku, presne jako rutiny na 0xd2 a 0xea.

    Registr d6 je 32bitovy posuvnik plneny po hornich 16 bitech; d7 pocita,
    kolik bitu ve spodni polovine jeste zbyva.
    """

    M = 0xFFFFFFFF

    def __init__(self, data, end):
        self.data = data
        self.pos = end
        nbits = self._word()            # move.w -(a2),d0
        self.pos -= 4                   # move.l -(a2),d6
        buf = int.from_bytes(self.data[self.pos:self.pos + 4], "big")
        self.buf = buf >> (16 - nbits)  # lsr.l d7,d6  kde d7 = 16-nbits
        self.cnt = nbits                # d7

    def _word(self):
        self.pos -= 2
        if self.pos < 0:
            raise ValueError("proud dosel - poskozena data nebo spatny offset")
        return int.from_bytes(self.data[self.pos:self.pos + 2], "big")

    @staticmethod
    def _swap(v):
        return ((v << 16) | (v >> 16)) & BitReaderA.M

    def bit(self):
        self.cnt -= 1
        if self.cnt:
            c = self.buf & 1
            self.buf >>= 1
            return c
        # spodni pulka dosla: horni sjede dolu a nahoru prijde novy word
        self.cnt = 16
        low = self.buf & 0xFFFF
        self.buf = self._swap(self.buf >> 1)
        self.buf = (self.buf & 0xFFFF0000) | self._word()
        self.buf = self._swap(self.buf)
        return low & 1

    def bits(self, n):
        v = self.buf & ((1 << n) - 1)   # and.w maskou z tabulky na 0x102
        self.buf >>= n
        self.cnt -= n
        if self.cnt <= 0:               # bgt.s = doplnit az kdyz dojdou
            self.cnt += 16
            r = self.cnt
            self.buf = ((self.buf >> r) | (self.buf << (32 - r))) & self.M
            self.buf = (self.buf & 0xFFFF0000) | self._word()
            self.buf = ((self.buf << r) | (self.buf >> (32 - r))) & self.M
        return v


def unpack_a(data, off=0):
    """Rozbali blok formatu A. Vraci (data, True) - format nema soucet."""
    size = int.from_bytes(data[off:off + 4], "big")
    packed = int.from_bytes(data[off + 4:off + 8], "big")
    if size == 0 or size > 8 << 20:
        raise ValueError("implausible unpacked length: %d" % size)
    if packed < 2 or off + 8 + packed > len(data):       # 1.0.39
        raise ValueError("implausible packed length: %d" % packed)

    out = bytearray(size)
    br = BitReaderA(data, off + 8 + packed)
    p = size

    def literals(n):
        nonlocal p
        if p - n < 0:
            raise ValueError("beh literalu pretekl zacatek bloku")
        for _ in range(n):
            p -= 1
            out[p] = br.bits(8)

    def match(length, offset):
        nonlocal p
        if p - length < 0:
            raise ValueError("zapas pretekl zacatek bloku")
        s = p + offset
        for _ in range(length):
            s -= 1
            p -= 1
            out[p] = out[s]

    while p > 0:
        if br.bit():
            literals(1)
            continue

        # delka: unarni prefix vybira sirku pole a bazi
        if not br.bit():
            n = 1 + br.bits(1)
        elif not br.bit():
            n = 3 + br.bits(2)
        elif not br.bit():
            n = 7 + br.bits(4)
        else:
            n = 23 + br.bits(8)

        if n == 22:                     # ukradena hodnota = dlouhy beh literalu
            wide = 5 if br.bit() else 14
            literals(15 + br.bits(wide))
            continue
        if n > 22:
            n -= 1

        if not br.bit():
            offset = 32 + br.bits(9)
        elif not br.bit():
            offset = br.bits(5)
        else:
            offset = 544 + br.bits(14)
        match(n + 1, offset)

    return bytes(out), True


def pack_b_literal(data):
    """Bytekiller stream containing only literal runs (valid, inefficient).
    Produces the 8-byte header, the backwards longword stream and the final
    checksum long so that ``unpack_b`` returns ``ok == True``."""
    if not data:
        raise ValueError('empty input')
    bits = []                                   # in decoder read order

    def put(v, n):
        for i in range(n - 1, -1, -1):
            bits.append((v >> i) & 1)

    rev = data[::-1]
    i = 0
    while i < len(rev):
        n = min(len(rev) - i, 264)
        if n <= 8:
            put(0, 1); put(0, 1); put(n - 1, 3)          # 1..8 literals
        else:
            put(1, 1); put(3, 2); put(n - 9, 8)          # 9..264 literals
        for k in range(n):
            put(rev[i + k], 8)
        i += n
    # Sentinel rule (see BitReader.bit): the FIRST long read (= last in the
    # file) holds k <= 31 payload bits with a 1 bit just above them; once it
    # is exhausted that sentinel is rotated (roxr) into bit 31 of every later
    # long, so those carry a full 32 payload bits each.
    longs = []
    k = len(bits) % 32
    v = 1 << k
    for i, b in enumerate(bits[:k]):
        v |= b << i
    longs.append(v)
    for j in range(k, len(bits), 32):
        v = 0
        for i, b in enumerate(bits[j:j + 32]):
            v |= b << i
        longs.append(v)
    longs.reverse()                              # first read chunk = last long
    checksum = 0
    for v in longs:
        checksum ^= v
    stream = b''.join(struct.pack('>I', v) for v in longs)
    # the decoder reads ONE extra long after the last code (``br._long()``);
    # it is read last, so it sits FIRST in the file: make it the value that
    # zeroes the running XOR.
    stream = struct.pack('>I', checksum) + stream
    packed = len(stream)
    return struct.pack('>II', len(data), packed) + stream


def pack_bk_literal(data):
    """Format BK stream of literal runs only: the 12-byte header (packed, unpacked, checksum) and the backwards
    longword stream; the checksum is the XOR of the stream's longs so that the decruncher's d5 ends at 0."""
    b = pack_b_literal(data)
    stream = b[8 + 4:]                           # drop the 8-byte header and the extra first long of format B
    checksum = 0
    for i in range(0, len(stream), 4):
        checksum ^= int.from_bytes(stream[i:i + 4], 'big')
    return struct.pack('>III', len(stream), len(data), checksum) + stream
