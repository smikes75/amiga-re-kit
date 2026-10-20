"""Brute-force scan of an image or file for packed blocks and known signatures.

Three kinds of evidence, reported separately so nothing is over-claimed:

* **signatures** - magic words of packers the Amiga scene used (PP20, RNC,
  ATN!, IMP!, XPKF, CrM!, S404, TPWM, PX20), plus HUNK headers and DOS boot
  blocks. A signature is a *hint*; the kit can unpack only PP20 and the
  Bytekiller family itself.
* **bytekiller_b** - the format has no magic, but it has an 8-byte header and
  an XOR checksum over the whole stream that must come out 0; a header that
  passes the checksum and then unpacks without error is a very strong hit.
* **bytekiller_a** (``deep=True``) - the SWIV word-stream variant has no
  checksum; a block is a hit only if a full unpack succeeds and consumes the
  stream exactly. It is tried only at offsets whose header is plausible.
"""
import struct

from . import bytekiller, pp20

SIGNATURES = {
    b'PP20': 'PowerPacker 2.0 (unpack: arek pp20)',
    b'PX20': 'PowerPacker 2.0, encrypted (no unpacker here)',
    b'RNC\x01': 'Rob Northen Compression method 1 (no unpacker here)',
    b'RNC\x02': 'Rob Northen Compression method 2 (no unpacker here)',
    b'ATN!': 'Atomik packer (no unpacker here)',
    b'IMP!': 'Imploder (no unpacker here)',
    b'XPKF': 'XPK container (no unpacker here)',
    b'CrM!': 'Crunch Mania (no unpacker here)',
    b'CrM2': 'Crunch Mania 2 (no unpacker here)',
    b'S404': 'StoneCracker 4.04 (no unpacker here)',
    b'TPWM': 'Turbo Packer (no unpacker here)',
    b'\x00\x00\x03\xf3': 'HUNK executable header (arek hunk)',
    b'DOS\x00': 'AmigaDOS OFS boot block / DOS type',
    b'DOS\x01': 'AmigaDOS FFS DOS type',
}

MAX_UNPACKED = 1 << 20


def signatures(data, align=2):
    hits = []
    for magic, desc in SIGNATURES.items():
        start = 0
        while True:
            i = data.find(magic, start)
            if i < 0:
                break
            if i % align == 0:
                hits.append({'offset': i, 'magic': magic.decode('latin-1'), 'what': desc})
            start = i + 1
    if any(h['magic'] == 'PP20' for h in hits):
        for h in hits:
            if h['magic'] == 'PP20':
                h['eff'] = list(data[h['offset'] + 4:h['offset'] + 8])
    return sorted(hits, key=lambda h: h['offset'])


def _plausible_header(data, off):
    if off + 8 > len(data):
        return None
    size, packed = struct.unpack_from('>II', data, off)
    if not 16 <= size <= MAX_UNPACKED:
        return None
    if packed < 8 or packed % 4 or packed > size + 64:
        return None
    if off + 8 + packed > len(data):
        return None
    return size, packed


def bytekiller_b(data, align=2, verify=True):
    """Offsets where an 8-byte Bytekiller header is followed by a stream whose
    longword XOR is 0. With ``verify`` the block is also unpacked."""
    hits = []
    n = len(data)
    off = 0
    while off + 16 <= n:
        hp = _plausible_header(data, off)
        if hp:
            size, packed = hp
            s = off + 8
            x = 0
            for i in range(s, s + packed, 4):
                x ^= struct.unpack_from('>I', data, i)[0]
            if x == 0:
                hit = {'offset': off, 'unpacked': size, 'packed': packed, 'checksum': 'ok'}
                if verify:
                    try:
                        out, ok = bytekiller.unpack_b(data, off)
                        hit['verified'] = ok and len(out) == size
                    except Exception as e:           # corrupt / false positive
                        hit['verified'] = False
                        hit['error'] = str(e)
                if not verify or hit['verified']:
                    hits.append(hit)
        off += align
    return hits


def bytekiller_a(data, align=2, max_tries=20000):
    """Costly: tries a full format-A unpack at every plausible header."""
    hits, tries = [], 0
    n = len(data)
    off = 0
    while off + 16 <= n and tries < max_tries:
        hp = _plausible_header(data, off)
        if hp:
            size, packed = hp
            tries += 1
            try:
                out, _ = bytekiller.unpack_a(data, off)
                # the reader must have consumed (almost) the whole stream
                if len(out) == size:
                    hits.append({'offset': off, 'unpacked': size, 'packed': packed,
                                 'verified': True})
            except Exception:
                pass
        off += align
    return hits


def pp20_blocks(data):
    """PP20 headers with what can be read from them. The end of a PP20 block
    is not stored in its header (the length sits in the LAST long), so for an
    image the block boundary has to come from the loader code; for a single
    file the whole file is the block and ``unpacked`` is reported."""
    out = []
    for h in signatures(data):
        if h['magic'] != 'PP20':
            continue
        rec = {'offset': h['offset'], 'eff': h['eff']}
        if h['offset'] == 0 and len(data) > 12:
            rec['unpacked'] = pp20.unpacked_length(data)
            try:
                rec['verified'] = len(pp20.unpack(data)) == rec['unpacked']
            except Exception as e:
                rec['verified'] = False
                rec['error'] = str(e)
        out.append(rec)
    return out


def scan(data, deep=False, align=2):
    rep = {'size': len(data),
           'signatures': signatures(data, align),
           'pp20': pp20_blocks(data),
           'bytekiller_b': bytekiller_b(data, align)}
    if deep:
        rep['bytekiller_a'] = bytekiller_a(data, align)
    return rep


def format_report(rep):
    L = ['size: %d bytes' % rep['size']]
    L.append('signatures: %d' % len(rep['signatures']))
    for h in rep['signatures']:
        extra = '  eff=%s' % h['eff'] if 'eff' in h else ''
        L.append('  %08x  %-6s %s%s' % (h['offset'], h['magic'], h['what'], extra))
    L.append('bytekiller B blocks (checksum ok + unpack ok): %d' % len(rep['bytekiller_b']))
    for h in rep['bytekiller_b']:
        L.append('  %08x  packed %6d -> unpacked %6d' % (h['offset'], h['packed'], h['unpacked']))
    if 'bytekiller_a' in rep:
        L.append('bytekiller A blocks (full unpack ok): %d' % len(rep['bytekiller_a']))
        for h in rep['bytekiller_a']:
            L.append('  %08x  packed %6d -> unpacked %6d' % (h['offset'], h['packed'], h['unpacked']))
    for h in rep['pp20']:
        if 'unpacked' in h:
            L.append('pp20 file: unpacked %d, verified=%s' % (h['unpacked'], h.get('verified')))
    return '\n'.join(L)
