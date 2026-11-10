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


@pytest.mark.parametrize('n', [1, 2, 3, 4, 7, 8, 9, 31, 32, 33, 100, 264, 265, 300, 1000, 4097])
def test_bytekiller_bk_roundtrip(rnd, n):
    d = rnd(n)
    p = bytekiller.pack_bk_literal(d)
    assert int.from_bytes(p[4:8], 'big') == n and int.from_bytes(p[:4], 'big') == len(p) - 12
    out, ok = bytekiller.unpack_bk(p)
    assert ok and out == d
    assert bytekiller.detect(p) == 'bk'


def test_bytekiller_detect_tells_b_from_bk(rnd):
    d = rnd(500)
    assert bytekiller.detect(bytekiller.pack_b_literal(d)) == 'b'
    assert bytekiller.detect(bytekiller.pack_bk_literal(d)) == 'bk'
    assert bytekiller.detect(rnd(64)) is None


def test_bytekiller_bk_checksum_detects_corruption(rnd):
    p = bytearray(bytekiller.pack_bk_literal(rnd(200)))
    p[16] ^= 0x40                                   # flip a bit inside the stream
    out, ok = bytekiller.unpack_bk(bytes(p))
    assert not ok


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
    bkk = bytekiller.pack_bk_literal(d)
    img[6000:6000 + len(bkk)] = bkk
    pp = pp20.pack_literal(d)
    img[9000:9000 + len(pp)] = pp
    img[12000:12004] = b'RNC\x01'
    rep = scan.scan(bytes(img))
    assert [h['offset'] for h in rep['bytekiller_b']] == [4000]
    assert [h['offset'] for h in rep['bytekiller_bk']] == [6000] and rep['bytekiller_bk'][0]['unpacked'] == 300
    magics = {(h['offset'], h['magic']) for h in rep['signatures']}
    assert (9000, 'PP20') in magics and (12000, 'RNC\x01') in magics
    assert 'bytekiller' in scan.format_report(rep) and 'BK blocks' in scan.format_report(rep)


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


# ----------------------------------------------------------------- RNC method 1 (1.0.21, Xenon 2 KIT-GAP 1)
from arek.packers import rnc  # noqa: E402


def _rnc_samples(rnd):
    return [b'', b'A', b'ab' * 1000, rnd(5000), bytes(70000), (b'hello world ' * 300 + rnd(777)) * 3,
            bytes((i * 7) & 0xff for i in range(40000)) + rnd(100) * 20]


def test_rnc_round_trip_and_header(rnd):
    """Every kind of data packs to a valid method-1 block and unpacks to itself; the header fields and the CRC-16
    (polynomial 0xA001, as the loader computes it) are what the decoder checks."""
    assert rnc.crc16(b'') == 0 and rnc.crc16(b'123456789') == 0xbb3d           # CRC-16/ARC check value
    for data in _rnc_samples(rnd):
        p = rnc.pack(data)
        assert p[:4] == rnc.MAGIC1 and rnc.is_rnc(p)
        h = rnc.info(p)
        assert h['method'] == 1 and h['unpacked'] == len(data) and h['packed'] == len(p) - rnc.HEADER and h['crc_out'] == rnc.crc16(data)
        assert h['crc_in'] == rnc.crc16(p[rnc.HEADER:]) and h['chunks'] == (1 if data else 0)
        assert rnc.unpack(p) == data
    assert len(rnc.pack(b'ab' * 1000)) < 60 and len(rnc.pack(bytes(70000))) < 60   # matches do compress


def test_rnc_block_inside_an_image_and_many_chunks(rnd):
    """A block at an offset inside a bigger file; the chunk count byte and a stream of more than one chunk
    (65 535 segments per chunk) decode as the original decoder would."""
    data = rnd(300)
    img = rnd(1000) + rnc.pack(data) + b'tail'
    assert rnc.unpack(img, 1000) == data
    # force many segments: alternate a repeated run and a random byte so that the greedy packer emits 70 000 / 4 segments
    noise = rnd(90000)
    tricky = b''.join(b'xyzxyz' + noise[i:i + 1] for i in range(90000))   # ~80 000 segments: two chunks
    p = rnc.pack(tricky)
    assert rnc.info(p)['chunks'] >= 2 and rnc.unpack(p) == tricky


def test_rnc_detects_corruption_and_refuses_method_2(rnd):
    data = rnd(2000) + b'abcabcabc' * 50
    p = bytearray(rnc.pack(data))
    bad = p[:]; bad[rnc.HEADER + 10] ^= 1                                        # a packed byte: the packed CRC catches it
    with pytest.raises(ValueError, match='packed CRC'):
        rnc.unpack(bytes(bad))
    bad = p[:]; bad[12] ^= 1                                                     # the unpacked CRC in the header
    with pytest.raises(ValueError, match='unpacked CRC'):
        rnc.unpack(bytes(bad))
    bad = p[:]; bad[3] = 2
    with pytest.raises(ValueError, match='method 2'):
        rnc.unpack(bytes(bad))
    with pytest.raises(ValueError, match='truncated'):
        rnc.unpack(bytes(p[:-5]))
    with pytest.raises(ValueError, match='missing RNC header'):
        rnc.unpack(b'not a block')


def test_rnc_cli_scan_and_mcp(tmp_path, rnd):
    from arek import cli
    from arek.packers import scan as scan_mod
    data = b'code' * 500 + rnd(200)
    img = bytes(100) + rnc.pack(data)
    (tmp_path / 'img.bin').write_bytes(img)
    assert cli.main(['rnc', str(tmp_path / 'img.bin'), '-o', str(tmp_path / 'out.bin'), '--offset', '100']) in (0, None)
    assert (tmp_path / 'out.bin').read_bytes() == data
    hits = scan_mod.signatures(img)
    assert any(h['magic'] == 'RNC\x01' and h['offset'] == 100 and 'arek rnc' in h['what'] for h in hits)
    from arek import mcp_server
    r = mcp_server.unpack(str(tmp_path / 'img.bin'), str(tmp_path / 'out2.bin'), 'auto', '0x64')
    assert r['kind'] == 'rnc' and r['bytes'] == len(data) and (tmp_path / 'out2.bin').read_bytes() == data


def test_bytekiller_tail_has_its_parameters_at_the_end(rnd, tmp_path):
    """1.0.43 (Xenon 2 KIT-GAP 17): a crunched executable's block - the unpacked length is its last long, the first bit
    word the one before; the block sits somewhere inside a file. The start-header formats refused it."""
    from arek import cli
    d = rnd(700)
    block = bytekiller.pack_tail_literal(d)
    assert int.from_bytes(block[-4:], 'big') == 700 and len(block) % 4 == 0
    assert bytekiller.unpack_tail(block) == (d, True)
    image = rnd(0x15a) + block + rnd(40)
    assert bytekiller.unpack_tail(image, 0x15a, 0x15a + len(block)) == (d, True)
    out, exact = bytekiller.unpack_tail(image, 0x15a - 4, 0x15a + len(block))       # a start 4 bytes early: decoded, not used up exactly
    assert out == d and exact is False
    with pytest.raises(ValueError):
        bytekiller.unpack_tail(image, 0x15a, 0x15a + len(block) - 2)                 # not whole longs
    with pytest.raises(ValueError):
        bytekiller.unpack_tail(block[:-4] + b'\xff\xff\xff\xff')                     # an implausible length
    src, dst = tmp_path / 'f.bin', tmp_path / 'o.bin'
    src.write_bytes(image)
    assert cli.main(['bytekiller', str(src), '-o', str(dst), '--format', 'tail', '--offset', '0x15a', '--end', hex(0x15a + len(block))]) == 0
    assert dst.read_bytes() == d


def test_bytekiller_refuses_a_stream_that_leaves_the_output(rnd):
    """1.0.43: a run or a match that passes the start of the output used negative indices - it wrote over the END of
    the output and the block came back "unpacked"."""
    good = bytekiller.pack_tail_literal(rnd(300))
    short = good[:-4] + (200).to_bytes(4, 'big')                                     # the same stream, a shorter output
    with pytest.raises(ValueError):
        bytekiller.unpack_tail(short)


def test_length_fields_do_not_drive_the_allocation(rnd):
    """1.0.43: an RNC header may announce 4 GB, a Turrican II run count 2^32 - both were taken at their word."""
    from arek.packers import rnc, turrican2
    packed = rnc.pack(rnd(500)) if hasattr(rnc, 'pack') else None
    if packed:
        assert rnc.unpack(packed) and rnc.unpack(packed, max_output=500)
        with pytest.raises(ValueError):
            rnc.unpack(packed, max_output=499)
    out = turrican2.rle_forward(bytes([1, 2, 3, 3, 5, 2, 0x08, 0, 0, 0]), 10)        # a run of $08000000 into 10 bytes
    assert len(out) == 10
    for bad in (b'', bytes(3), bytes(12), b'\xff' * 64, rnd(2000)):
        with pytest.raises(ValueError):                                              # was IndexError / struct.error / a huge buffer
            turrican2.unpack_t2(bad)
