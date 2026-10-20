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

``unpack_b(data, off)`` -> (bytes, checksum_ok); ``unpack_a(data, off)`` -> (bytes, True).
``pack_b_literal`` is a literal-only encoder for round-trip tests.
"""


import struct


class BitReader:
    """Cte bity pozpatku, presne jako getbit na 0x82.

        lsr.l #1,d0      ; C = X = spodni bit, d0 >>= 1
        bne.s  hotovo    ; longword jeste neni vycerpany
        move.l -(a0),d0  ; dobrat dalsi (pozpatku), X zustava
        eor.l  d0,d5     ; kontrolni soucet
        roxr.l #1,d0     ; X -> bit31, novy spodni bit -> C
    """

    def __init__(self, data, end):
        self.data = data
        self.pos = end          # a0, ukazuje ZA konec proudu
        self.checksum = 0       # d5
        self.buf = self._long()  # d0

    def _long(self):
        self.pos -= 4
        if self.pos < 0:
            raise ValueError("proud dosel - poskozena data nebo spatny offset")
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


def unpack_b(data, off=0):
    """Rozbali blok na offsetu off. Vraci (data, ok_checksum)."""
    size = int.from_bytes(data[off:off + 4], "big")
    packed = int.from_bytes(data[off + 4:off + 8], "big")
    if size == 0 or size > 8 << 20:
        raise ValueError("nesmyslna delka rozbalenych dat: %d" % size)

    out = bytearray(size)
    br = BitReader(data, off + 8 + packed)
    p = size                                    # a1, zapis pozpatku

    def literals(n):
        nonlocal p
        for _ in range(n):
            p -= 1
            out[p] = br.bits(8)

    def match(length, offset):
        nonlocal p
        s = p + offset
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

    br._long()                                  # zaverecny longword (0x9c)
    return bytes(out), br.checksum == 0


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
        raise ValueError("nesmyslna delka rozbalenych dat: %d" % size)

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
