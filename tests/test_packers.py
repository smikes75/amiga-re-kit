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
