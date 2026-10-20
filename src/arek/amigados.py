"""AmigaDOS filesystem (OFS / FFS) reader for ADF images, plus a builder of
synthetic images for tests.

Most games here boot their own trackloader and never touch the filesystem,
but some (Team17's, for one) keep their packed files as ordinary AmigaDOS
files. A raw scan of such an image then finds the packer header 24 bytes
into a sector and the stream cut into 488-byte pieces: OFS data blocks.
This module reads the structure so the file can be reassembled first.

What is read: boot block DOS type, root block, directories (hash table +
hash chains), file header blocks, extension blocks, data blocks (OFS: 24 B
header + 488 B data; FFS: 512 B raw). Every structure block carries a
checksum (the longword sum must be zero); the reader verifies it and raises
instead of guessing. ``strict=False`` turns checksum errors and data blocks
without an OFS header (raw sectors a game wrote itself) into warnings and
takes the bytes as they are.
Floppy geometry only: 880 KB DD (root block 880) and 1760 KB HD (root 1760).
Nothing is written to the image.
"""
import struct

BSIZE = 512
T_HEADER, T_DATA, T_LIST = 2, 8, 16
ST_ROOT, ST_USERDIR, ST_FILE = 1, 2, -3
HT_SIZE = BSIZE // 4 - 56          # 72 hash-table / data-pointer slots
OFS_DATA = BSIZE - 24              # 488 data bytes per OFS data block


class DOSError(ValueError):
    pass


# ----------------------------------------------------------------- blocks
def block(data, n):
    if n < 0 or (n + 1) * BSIZE > len(data):
        raise DOSError('block %d outside the image' % n)
    return data[n * BSIZE:(n + 1) * BSIZE]


def _long(blk, i):
    return struct.unpack_from('>i', blk, i * 4)[0]


def _ulong(blk, i):
    return struct.unpack_from('>I', blk, i * 4)[0]


def checksum_ok(blk):
    return sum(struct.unpack('>%dI' % (BSIZE // 4), blk)) & 0xffffffff == 0


def _bstr(blk, off, maxlen):
    n = min(blk[off], maxlen)
    return blk[off + 1:off + 1 + n].decode('latin-1')


def dostype(data):
    """``{'fs': 'OFS'|'FFS', 'intl': bool, 'dircache': bool, 'flags': n}`` or
    None when the boot block does not start with ``DOS``."""
    if len(data) < 4 or data[:3] != b'DOS':
        return None
    f = data[3]
    return {'fs': 'FFS' if f & 1 else 'OFS', 'intl': bool(f & 6), 'dircache': bool(f & 4), 'flags': f}


def root_block_number(data):
    return len(data) // BSIZE // 2


# ----------------------------------------------------------------- directory tree
def _entry(data, n, parent_path, strict):
    blk = block(data, n)
    ok = checksum_ok(blk)
    if _long(blk, 0) != T_HEADER:
        raise DOSError('block %d: not a header block (type %d)' % (n, _long(blk, 0)))
    if not ok and strict:
        raise DOSError('block %d: bad checksum' % n)
    sec = _long(blk, BSIZE // 4 - 1)
    name = _bstr(blk, BSIZE - 80, 30)
    e = {'name': name, 'path': parent_path + name, 'block': n, 'checksum_ok': ok,
         'protect': _ulong(blk, BSIZE // 4 - 48), 'comment': _bstr(blk, BSIZE - 184, 79),
         'parent': _long(blk, BSIZE // 4 - 3), 'hash_chain': _long(blk, BSIZE // 4 - 4)}
    if sec == ST_FILE:
        e.update(type='file', size=_ulong(blk, BSIZE // 4 - 47), first_data=_long(blk, 4),
                 extension=_long(blk, BSIZE // 4 - 2))
    elif sec == ST_USERDIR:
        e.update(type='dir', size=0)
    else:
        raise DOSError('block %d: unexpected secondary type %d' % (n, sec))
    return e


def root(data, n=None, strict=True):
    n = root_block_number(data) if n is None else n
    blk = block(data, n)
    ok = checksum_ok(blk)
    if _long(blk, 0) != T_HEADER or _long(blk, BSIZE // 4 - 1) != ST_ROOT:
        raise DOSError('block %d is not a root block' % n)
    if not ok and strict:
        raise DOSError('root block %d: bad checksum' % n)
    return {'block': n, 'name': _bstr(blk, BSIZE - 80, 30), 'checksum_ok': ok,
            'ht_size': _long(blk, 3), 'bitmap_valid': _long(blk, BSIZE // 4 - 50) == -1}


def entries(data, dir_block, parent_path='', strict=True):
    """Direct entries of a directory (root or user dir) in hash-table order."""
    blk = block(data, dir_block)
    out, seen = [], set()
    for i in range(HT_SIZE):
        n = _long(blk, 6 + i)
        while n:
            if n in seen:
                raise DOSError('hash chain loop at block %d' % n)
            seen.add(n)
            e = _entry(data, n, parent_path, strict)
            out.append(e)
            n = e['hash_chain']
    return out


def walk(data, strict=True):
    """Every file and directory of the image, depth first, with ``path``
    (``dir/sub/file``). Raises DOSError when the image is not AmigaDOS."""
    if dostype(data) is None:
        raise DOSError('no DOS boot block')
    r = root(data, strict=strict)
    out, todo, seen = [], [(r['block'], '')], set()
    while todo:
        b, prefix = todo.pop()
        if b in seen:
            raise DOSError('directory loop at block %d' % b)
        seen.add(b)
        for e in entries(data, b, prefix, strict):
            out.append(e)
            if e['type'] == 'dir':
                todo.append((e['block'], e['path'] + '/'))
    return out


def find(data, path, strict=True):
    """Entry for ``path`` (case-insensitive, ``/`` separated, an optional
    ``VOLUME:`` prefix is ignored) or None."""
    want = path.split(':', 1)[-1].strip('/').lower()
    for e in walk(data, strict):
        if e['path'].lower() == want:
            return e
    return None


# ----------------------------------------------------------------- file data
def data_blocks(data, header_block, strict=True):
    """Data block numbers of a file in order (header pointers are stored
    backwards from the end of the table; extension blocks continue them)."""
    out, n, seen = [], header_block, set()
    while n:
        if n in seen:
            raise DOSError('extension loop at block %d' % n)
        seen.add(n)
        blk = block(data, n)
        t = _long(blk, 0)
        if t not in (T_HEADER, T_LIST):
            raise DOSError('block %d: not a file header/extension block' % n)
        if not checksum_ok(blk) and strict:
            raise DOSError('block %d: bad checksum' % n)
        count = _long(blk, 2)
        if not 0 <= count <= HT_SIZE:
            raise DOSError('block %d: %d data pointers' % (n, count))
        for i in range(count):
            out.append(_long(blk, 6 + HT_SIZE - 1 - i))
        n = _long(blk, BSIZE // 4 - 2)
    return out


def read_file(data, entry, strict=True, warnings=None):
    """Bytes of a file given its entry (from ``walk``/``find``) or header
    block number. OFS data blocks are checked (type, owner, sequence,
    checksum); FFS blocks are raw."""
    if isinstance(entry, int):
        entry = _entry(data, entry, '', strict)
    if entry['type'] != 'file':
        raise DOSError('%s is a directory' % entry['path'])
    ffs = dostype(data)['fs'] == 'FFS'
    size = entry['size']
    out = bytearray()
    for i, n in enumerate(data_blocks(data, entry['block'], strict)):
        blk = block(data, n)
        if ffs:
            out += blk
            continue
        if _long(blk, 0) != T_DATA or _long(blk, 1) != entry['block'] or _long(blk, 2) != i + 1:
            # Seen on game disks: the file's blocks were (re)written raw, by the
            # game itself or a mastering tool, so there is no OFS header to trust.
            if strict:
                raise DOSError('%s: block %d is not data block %d of this file' % (entry['path'], n, i + 1))
            if warnings is not None:
                warnings.append('block %d has no OFS data header, taken raw' % n)
            out += blk
            continue
        if not checksum_ok(blk):
            if strict:
                raise DOSError('%s: data block %d bad checksum' % (entry['path'], n))
            if warnings is not None:
                warnings.append('block %d bad checksum' % n)
        ds = _long(blk, 3)
        if not 0 <= ds <= OFS_DATA:
            raise DOSError('%s: block %d data size %d' % (entry['path'], n, ds))
        out += blk[24:24 + ds]
    if len(out) < size:
        raise DOSError('%s: %d bytes of data for a %d byte file' % (entry['path'], len(out), size))
    return bytes(out[:size])


def listing(data, strict=True):
    """Rows for ``arek adf ls``: path, type, size, block, checksum."""
    return [{'path': e['path'], 'type': e['type'], 'size': e['size'], 'block': e['block'],
             'checksum_ok': e['checksum_ok']} for e in walk(data, strict)]


def format_listing(data, rows):
    dt = dostype(data)
    r = root(data, strict=False)
    L = ['%s%s  volume "%s"  root block %d%s' % (
        dt['fs'], ' intl' if dt['intl'] else '', r['name'], r['block'],
        '' if r['checksum_ok'] else '  ROOT CHECKSUM BAD')]
    for e in rows:
        L.append('%8s  %5d  %s%s%s' % (
            '<dir>' if e['type'] == 'dir' else e['size'], e['block'], e['path'],
            '/' if e['type'] == 'dir' else '', '' if e['checksum_ok'] else '   CHECKSUM BAD'))
    return '\n'.join(L)


# ----------------------------------------------------------------- synthetic image builder
def _hash(name, ht_size=HT_SIZE):
    h = len(name)
    for c in name:
        h = (h * 13 + ord(c.upper())) & 0x7ff
    return h % ht_size


def _put_checksum(blk, at=5):
    struct.pack_into('>I', blk, at * 4, 0)
    s = sum(struct.unpack('>%dI' % (BSIZE // 4), blk)) & 0xffffffff
    struct.pack_into('>I', blk, at * 4, (-s) & 0xffffffff)


def _put_bstr(blk, off, s, maxlen):
    b = s.encode('latin-1')[:maxlen]
    blk[off] = len(b)
    blk[off + 1:off + 1 + len(b)] = b


def build_image(files, name='SYN', ffs=False, size=BSIZE * 1760, bootcode=b''):
    """A valid OFS/FFS image holding ``files`` (``{'dir/name': bytes}``;
    directories are created as needed). Blocks are allocated sequentially
    after the bitmap block, the bitmap is written, every checksum is correct,
    so the image mounts in an emulator. For tests and probes only."""
    nblocks = size // BSIZE
    img = bytearray(size)
    img[0:4] = b'DOS' + bytes([1 if ffs else 0])
    struct.pack_into('>I', img, 8, nblocks // 2)
    img[12:12 + len(bootcode)] = bootcode
    from . import adf
    struct.pack_into('>I', img, 4, adf.bootblock_checksum(bytes(img[:1024])))
    rootn = nblocks // 2
    bitmapn = rootn + 1
    nxt = [bitmapn + 1]
    used = {rootn, bitmapn}

    def alloc():
        n = nxt[0]
        if n >= nblocks:
            raise DOSError('image full')
        nxt[0] += 1
        used.add(n)
        return n

    def header(n, sec, nm, parent):
        blk = bytearray(BSIZE)
        struct.pack_into('>iii', blk, 0, T_HEADER, n, 0)
        _put_bstr(blk, BSIZE - 80, nm, 30)
        struct.pack_into('>i', blk, BSIZE - 12, parent)
        struct.pack_into('>i', blk, BSIZE - 4, sec)
        return blk

    def link(dir_blk, child_blk, child_n, nm):
        i = 6 + _hash(nm)
        struct.pack_into('>i', child_blk, BSIZE - 16, _long(dir_blk, i))
        struct.pack_into('>i', dir_blk, i * 4, child_n)

    dirs = {'': (rootn, header(rootn, ST_ROOT, name, 0))}
    struct.pack_into('>i', dirs[''][1], 3 * 4, HT_SIZE)

    def directory(path):
        if path in dirs:
            return dirs[path]
        parent, _, nm = path.rpartition('/')
        pn, pblk = directory(parent)
        n = alloc()
        blk = header(n, ST_USERDIR, nm, pn)
        link(pblk, blk, n, nm)
        dirs[path] = (n, blk)
        return dirs[path]

    pending = []
    for path, content in files.items():
        parent, _, nm = path.rpartition('/')
        pn, pblk = directory(parent)
        hn = alloc()
        hdr = header(hn, ST_FILE, nm, pn)
        struct.pack_into('>I', hdr, BSIZE - 188, len(content))
        chunk = BSIZE if ffs else OFS_DATA
        pieces = [content[i:i + chunk] for i in range(0, len(content), chunk)]
        dblocks = [alloc() for _ in pieces]
        for i, (dn, piece) in enumerate(zip(dblocks, pieces)):
            if ffs:
                img[dn * BSIZE:dn * BSIZE + len(piece)] = piece
            else:
                blk = bytearray(BSIZE)
                struct.pack_into('>iiiii', blk, 0, T_DATA, hn, i + 1, len(piece),
                                 dblocks[i + 1] if i + 1 < len(dblocks) else 0)
                blk[24:24 + len(piece)] = piece
                _put_checksum(blk)
                img[dn * BSIZE:(dn + 1) * BSIZE] = blk
        if dblocks:
            struct.pack_into('>i', hdr, 4 * 4, dblocks[0])
        table, rest = dblocks[:HT_SIZE], dblocks[HT_SIZE:]
        struct.pack_into('>i', hdr, 2 * 4, len(table))
        for i, dn in enumerate(table):
            struct.pack_into('>i', hdr, (6 + HT_SIZE - 1 - i) * 4, dn)
        link(pblk, hdr, hn, nm)
        prev, prev_n = hdr, hn
        while rest:
            en = alloc()
            ext = bytearray(BSIZE)
            table, rest = rest[:HT_SIZE], rest[HT_SIZE:]
            struct.pack_into('>iii', ext, 0, T_LIST, en, len(table))
            for i, dn in enumerate(table):
                struct.pack_into('>i', ext, (6 + HT_SIZE - 1 - i) * 4, dn)
            struct.pack_into('>i', ext, BSIZE - 12, hn)
            struct.pack_into('>i', ext, BSIZE - 4, ST_FILE)
            struct.pack_into('>i', prev, BSIZE - 8, en)
            pending.append((prev_n, prev))
            prev, prev_n = ext, en
        pending.append((prev_n, prev))
    # bitmap: one bit per block from block 2, 1 = free
    bm = bytearray(BSIZE)
    for n in range(2, nblocks):
        if n not in used:
            i = n - 2
            bm[4 + (i // 32) * 4 + 3 - (i % 32) // 8] |= 1 << (i % 8)
    _put_checksum(bm, 0)
    img[bitmapn * BSIZE:(bitmapn + 1) * BSIZE] = bm
    rblk = dirs[''][1]
    struct.pack_into('>i', rblk, BSIZE - 200, -1)
    struct.pack_into('>i', rblk, BSIZE - 196, bitmapn)
    for n, blk in pending + list(dirs.values()):
        _put_checksum(blk)
        img[n * BSIZE:(n + 1) * BSIZE] = blk
    return bytes(img)
