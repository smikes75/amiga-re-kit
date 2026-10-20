import pytest

from arek.packers import bytekiller, pp20, scan


@pytest.mark.parametrize('n', [1, 2, 3, 4, 7, 8, 9, 31, 32, 33, 100, 264, 265, 300, 1000, 4097])
def test_pp20_roundtrip(rnd, n):
    d = rnd(n)
    p = pp20.pack_literal(d)
    assert pp20.is_pp20(p)
    assert pp20.unpacked_length(p) == n
    assert pp20.unpack(p) == d


def test_pp20_rejects_garbage():
    with pytest.raises(ValueError):
        pp20.unpack(b'XXXX' + bytes(16))


@pytest.mark.parametrize('n', [1, 2, 3, 4, 7, 8, 9, 31, 32, 33, 100, 264, 265, 300, 1000, 4097])
def test_bytekiller_b_roundtrip(rnd, n):
    d = rnd(n)
    p = bytekiller.pack_b_literal(d)
    out, ok = bytekiller.unpack_b(p)
    assert ok and out == d


def test_bytekiller_checksum_detects_corruption(rnd):
    p = bytearray(bytekiller.pack_b_literal(rnd(200)))
    p[12] ^= 0x40                                   # flip a bit inside the stream
    out, ok = bytekiller.unpack_b(bytes(p))
    assert not ok


def test_scan_finds_blocks_and_signatures(rnd):
    img = bytearray(rnd(16000))
    d = rnd(300)
    bk = bytekiller.pack_b_literal(d)
    img[4000:4000 + len(bk)] = bk
    pp = pp20.pack_literal(d)
    img[9000:9000 + len(pp)] = pp
    img[12000:12004] = b'RNC\x01'
    rep = scan.scan(bytes(img))
    assert [h['offset'] for h in rep['bytekiller_b']] == [4000]
    magics = {(h['offset'], h['magic']) for h in rep['signatures']}
    assert (9000, 'PP20') in magics and (12000, 'RNC\x01') in magics
    assert 'bytekiller' in scan.format_report(rep)


def test_scan_pp20_file_verified(rnd):
    d = rnd(123)
    rep = scan.scan(pp20.pack_literal(d))
    assert rep['pp20'][0]['unpacked'] == 123 and rep['pp20'][0]['verified']


# ----------------------------------------------------------------- Atomik
from arek.packers import atomik  # noqa: E402


def _atomik_cases(rnd):
    return {
        'random': rnd(1500),
        'zeros': bytes(3000),
        'period3': b'abc' * 500,
        'text': b'the quick brown fox jumps over the lazy dog ' * 40,
        'mixed': b''.join(rnd(50) + b'REPEAT' * (1 + i % 30) for i in range(40)),
        'far': rnd(300) + bytes(9000) + rnd(10),     # distances beyond the 8480 window
        'min': bytes(range(12)),
    }


@pytest.mark.parametrize('n', [12, 13, 100, 264, 1000, 4097])
@pytest.mark.parametrize('skip_last', [False, True])
def test_atomik_literal_roundtrip(rnd, n, skip_last):
    d = rnd(n)
    p = atomik.pack_literal(d, skip_last=skip_last)
    assert atomik.is_atomik(p)
    assert atomik.header(p) == {'unpacked': n, 'packed': n + skip_last, 'length': len(p)}
    assert atomik.unpack(p) == d
    assert atomik.unpack(p + b'trailing image bytes') == d


@pytest.mark.parametrize('prime', [0, 3, 7])
def test_atomik_lz_roundtrip(rnd, prime):
    for name, d in _atomik_cases(rnd).items():
        p = atomik.pack(d, prime=prime)
        assert atomik.unpack(p) == d, name
        assert atomik.header(p)['length'] == len(p), name
    # back references are really used: repetitive data packs far below 1:1
    assert len(atomik.pack(bytes(3000))) < 100
    assert len(atomik.pack(b'abc' * 500)) < 100


def test_atomik_length_and_literal_paths(rnd):
    """Lengths 2..5 (unary), 6..13 (3 bits), 14..255 (byte), 256 (byte 0);
    literal runs in every category band, incl. runs too long for a category."""
    pieces = []
    for ln in (2, 3, 4, 5, 6, 13, 14, 200, 255, 256):
        pieces.append(rnd(ln) * 2)                  # a match of exactly ln
        pieces.append(rnd(25))                       # 25 literals > cat-0 max (21)
    for lits in (0, 1, 2, 5, 6, 21, 22, 41, 137, 138, 2000):
        pieces.append(b'ZZZZZZ' + rnd(lits))
    d = b''.join(pieces)
    for prime in (0, 5):
        assert atomik.unpack(atomik.pack(d, prime=prime)) == d


def test_atomik_rejects_bad_streams(rnd):
    d = rnd(100)
    p = atomik.pack(d)
    with pytest.raises(ValueError):
        atomik.unpack(b'XTN!' + p[4:])                       # magic
    with pytest.raises(ValueError):
        atomik.unpack(p[:-1])                                # truncated trailer
    bad = bytearray(p)
    bad[4:8] = (0).to_bytes(4, 'big')                        # output size 0
    with pytest.raises(ValueError):
        atomik.unpack(bytes(bad))
    bad = bytearray(p)
    bad[4:8] = (len(d) + 7).to_bytes(4, 'big')               # size lies -> pointer check
    with pytest.raises(ValueError):
        atomik.unpack(bytes(bad))
    with pytest.raises(ValueError):
        atomik.pack_literal(b'short')
    with pytest.raises(ValueError):
        atomik.pack(b'')


def test_scan_finds_and_verifies_atomik(rnd):
    img = bytearray(rnd(20000))
    d = rnd(40) + b'pattern' * 30 + rnd(40)
    blk = atomik.pack(d)
    img[6000:6000 + len(blk)] = blk
    img[15000:15004] = b'ATN!'                               # signature without a block
    rep = scan.scan(bytes(img))
    hits = {h['offset']: h for h in rep['atomik']}
    assert hits[6000]['verified'] and hits[6000]['unpacked'] == len(d)
    assert hits[6000]['end'] == 6000 + len(blk)
    assert not hits[15000]['verified'] and 'error' in hits[15000]
    txt = scan.format_report(rep)
    assert 'atomik (ATN!) blocks: 2, verified 1' in txt
