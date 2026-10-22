"""Bounded AmigaDOS HUNK executable reader (from the Superfrog project).

Supports the subset game loaders actually use: HUNK_HEADER without resident
names, CODE/DATA/BSS records, RELOC32, HUNK_END. Anything else raises
``FormatError`` explicitly - this is not a general executable loader and it
never guesses.

``load(data, bases)`` relocates every hunk to the address you supply (one base
per hunk, or a single base from which hunks are laid out contiguously) and
returns ``[(base, bytes), ...]``. ``split(main, chip, ...)`` follows the
two-stream layout the Superfrog stage-2 loader uses (first hunks in slow RAM,
the rest in chip RAM, records split across two files).
"""
import struct

HUNK_HEADER, HUNK_CODE, HUNK_DATA, HUNK_BSS = 0x3f3, 0x3e9, 0x3ea, 0x3eb
HUNK_RELOC32, HUNK_END = 0x3ec, 0x3f2
NAMES = {0x3e9: 'CODE', 0x3ea: 'DATA', 0x3eb: 'BSS'}


class FormatError(ValueError):
    pass


class Reader:
    def __init__(self, data):
        self.data, self.pos = data, 0

    def take(self, count):
        if count < 0 or self.pos + count > len(self.data):
            raise FormatError('Truncated HUNK stream')
        result = self.data[self.pos:self.pos + count]
        self.pos += count
        return result

    def word(self):
        return struct.unpack('>I', self.take(4))[0]


def is_hunk(data):
    return len(data) >= 8 and data[:4] == b'\x00\x00\x03\xf3'


def header(reader):
    """Parse HUNK_HEADER; returns the allocation sizes in bytes."""
    if reader.word() != HUNK_HEADER or reader.word() != 0:
        raise FormatError('Expected HUNK_HEADER without resident names')
    count, first, last = reader.word(), reader.word(), reader.word()
    if not 1 <= count <= 64 or first != 0 or last != count - 1:
        raise FormatError('Unsupported HUNK table')
    sizes = [(reader.word() & 0x3fffffff) * 4 for _ in range(count)]
    if any(size > 16 * 1024 * 1024 for size in sizes):
        raise FormatError('Oversized HUNK allocation')
    return sizes


def records(reader, hunks, bases, first, count, kinds=None):
    """Read ``count`` hunk bodies starting at hunk ``first`` and relocate."""
    for index in range(first, first + count):
        kind = reader.word() & 0x3fffffff
        if kind not in NAMES:
            raise FormatError('Unsupported HUNK record %#x' % kind)
        if kinds is not None:
            kinds.append(NAMES[kind])
        size = reader.word() * 4
        if size > len(hunks[index]):
            raise FormatError('HUNK record exceeds allocation')
        if kind != HUNK_BSS:
            hunks[index][:size] = reader.take(size)
        while True:
            kind = reader.word() & 0x3fffffff
            if kind == HUNK_END:
                break
            if kind != HUNK_RELOC32:
                raise FormatError('Unsupported HUNK record %#x' % kind)
            while True:
                reloc_count = reader.word()
                if reloc_count == 0:
                    break
                target = reader.word()
                if target >= len(bases):
                    raise FormatError('HUNK relocation target out of range')
                for _ in range(reloc_count):
                    offset = reader.word()
                    if offset % 2 or offset + 4 > len(hunks[index]):
                        raise FormatError('HUNK relocation offset out of range')
                    value = struct.unpack_from('>I', hunks[index], offset)[0]
                    struct.pack_into('>I', hunks[index], offset,
                                     (value + bases[target]) & 0xffffffff)


def info(data):
    """Sizes and record kinds without relocating (for ``arek hunk info``).

    A file that ends cleanly after fewer records than the header declares is reported,
    not refused: ``missing`` lists the hunks whose records are not in it (a game loader
    may keep them in a second stream - ``split``)."""
    reader = Reader(data)
    sizes = header(reader)
    hunks = [bytearray(s) for s in sizes]
    kinds = []
    for index in range(len(sizes)):
        if reader.pos == len(data):
            break
        records(reader, hunks, [0] * len(sizes), index, 1, kinds)
    out = {'hunks': [{'index': i, 'kind': kinds[i] if i < len(kinds) else None, 'size': s}
                     for i, s in enumerate(sizes)],
           'trailing_bytes': len(data) - reader.pos}
    if len(kinds) < len(sizes):
        out['missing'] = list(range(len(kinds), len(sizes)))
        out['note'] = ('records of hunks %d-%d are not in this file; a second stream? '
                       '(arek hunk split)' % (len(kinds), len(sizes) - 1))
    return out


def load(data, bases):
    """Relocate all hunks. ``bases``: int (contiguous from there) or list."""
    reader = Reader(data)
    sizes = header(reader)
    if isinstance(bases, int):
        b, lst = bases, []
        for s in sizes:
            lst.append(b)
            b += (s + 3) & ~3
        bases = lst
    if len(bases) != len(sizes):
        raise FormatError('Expected %d bases, got %d' % (len(sizes), len(bases)))
    hunks = [bytearray(s) for s in sizes]
    records(reader, hunks, list(bases), 0, len(sizes))
    if reader.pos != len(data):
        raise FormatError('Trailing HUNK bytes')
    return [(b, bytes(h)) for b, h in zip(bases, hunks)]


def single(data, base):
    """One-hunk executable -> relocated bytes."""
    out = load(data, [base])
    if len(out) != 1:
        raise FormatError('Expected one HUNK')
    return out[0][1]


def split(program, chip, slow_base, chip_base, n_slow=2):
    """Two-stream layout: the first ``n_slow`` hunks' records are in
    ``program`` (placed from ``slow_base``), the remaining ones in ``chip``
    (placed from ``chip_base``). Returns ``[(base, bytes), ...]``."""
    reader = Reader(program)
    sizes = header(reader)
    if len(sizes) <= n_slow:
        raise FormatError('Expected more than %d hunks' % n_slow)
    bases, b = [], slow_base
    for s in sizes[:n_slow]:
        bases.append(b)
        b += (s + 3) & ~3
    b = chip_base
    for s in sizes[n_slow:]:
        bases.append(b)
        b += (s + 3) & ~3
    hunks = [bytearray(size) for size in sizes]
    records(reader, hunks, bases, 0, n_slow)
    if reader.pos != len(program):
        raise FormatError('Trailing main stream bytes')
    reader = Reader(chip)
    records(reader, hunks, bases, n_slow, len(sizes) - n_slow)
    if reader.pos != len(chip):
        raise FormatError('Trailing chip stream bytes')
    return [(base, bytes(data)) for base, data in zip(bases, hunks)]


def build(hunks, relocs=None):
    """Assemble a HUNK executable from ``[(kind, bytes), ...]`` with optional
    ``relocs = {hunk_index: {target_index: [offsets]}}``. Used by the tests;
    also handy for writing small probes that run on a real Amiga."""
    relocs = relocs or {}
    out = [struct.pack('>IIIII', HUNK_HEADER, 0, len(hunks), 0, len(hunks) - 1)]
    for kind, body in hunks:
        out.append(struct.pack('>I', (len(body) + 3) // 4))
    for i, (kind, body) in enumerate(hunks):
        code = {v: k for k, v in NAMES.items()}[kind]
        words = (len(body) + 3) // 4
        out.append(struct.pack('>II', code, words))
        if kind != 'BSS':
            out.append(bytes(body) + b'\0' * (words * 4 - len(body)))
        if relocs.get(i):
            out.append(struct.pack('>I', HUNK_RELOC32))
            for target, offs in relocs[i].items():
                out.append(struct.pack('>II', len(offs), target))
                out += [struct.pack('>I', o) for o in offs]
            out.append(struct.pack('>I', 0))
        out.append(struct.pack('>I', HUNK_END))
    return b''.join(out)
