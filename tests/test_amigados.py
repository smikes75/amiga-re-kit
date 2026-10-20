import struct

import pytest

from arek import adf, amigados as ad, cli
from arek.packers import atomik, scan


def _files(rnd):
    return {'small.bin': b'hello', 'exact488.bin': rnd(488), 'big.bin': rnd(40000),
            'data/levels/l1.bin': b'L' * 1000, 'empty.bin': b''}


@pytest.mark.parametrize('ffs', [False, True])
def test_build_walk_read(rnd, ffs):
    files = _files(rnd)
    img = ad.build_image(files, name='SYN', ffs=ffs)
    assert len(img) == adf.SIZE and adf.bootblock(img)['bootable']
    assert ad.dostype(img)['fs'] == ('FFS' if ffs else 'OFS')
    r = ad.root(img)
    assert r['name'] == 'SYN' and r['checksum_ok'] and r['bitmap_valid']
    rows = {e['path']: e for e in ad.walk(img)}
    assert set(rows) == set(files) | {'data', 'data/levels'}
    assert rows['data']['type'] == 'dir' and rows['data/levels']['parent'] == rows['data']['block']
    for p, c in files.items():
        assert rows[p]['size'] == len(c)
        assert ad.read_file(img, rows[p]) == c
        assert ad.read_file(img, rows[p]['block']) == c
    # 40000 B needs more than the 72 pointers of the header -> extension block
    assert len(ad.data_blocks(img, rows['big.bin']['block'])) == (79 if ffs else 82)
    assert rows['big.bin']['extension'] != 0
    assert ad.find(img, 'SYN:Data/Levels/L1.BIN')['block'] == rows['data/levels/l1.bin']['block']
    assert ad.find(img, 'nope') is None
    txt = ad.format_listing(img, ad.listing(img))
    assert 'volume "SYN"' in txt and 'data/levels/l1.bin' in txt


def test_not_dos_and_loops(rnd):
    assert ad.dostype(rnd(2000)) is None
    with pytest.raises(ad.DOSError):
        ad.walk(bytes(adf.SIZE))
    img = bytearray(ad.build_image({'a': b'x' * 20, 'b': b'y' * 20}))
    e = ad.find(bytes(img), 'a')
    # hash chain pointing at itself -> loop detected, not an endless walk
    struct.pack_into('>i', img, e['block'] * ad.BSIZE + ad.BSIZE - 16, e['block'])
    ad._put_checksum(memoryview(img)[e['block'] * ad.BSIZE:(e['block'] + 1) * ad.BSIZE])
    with pytest.raises(ad.DOSError):
        ad.walk(bytes(img))


def test_corruption_strict_and_lenient(rnd):
    img = bytearray(ad.build_image({'f.bin': rnd(3000)}))
    e = ad.find(bytes(img), 'f.bin')
    blocks = ad.data_blocks(bytes(img), e['block'])
    # flip a byte inside the second data block: checksum breaks
    img[blocks[1] * ad.BSIZE + 100] ^= 0x55
    with pytest.raises(ad.DOSError):
        ad.read_file(bytes(img), e)
    warn = []
    out = ad.read_file(bytes(img), e, strict=False, warnings=warn)
    assert len(out) == 3000 and warn == ['block %d bad checksum' % blocks[1]]
    # overwrite the third data block with raw bytes (no OFS header at all)
    raw = rnd(ad.BSIZE)
    img[blocks[2] * ad.BSIZE:(blocks[2] + 1) * ad.BSIZE] = raw
    with pytest.raises(ad.DOSError):
        ad.read_file(bytes(img), e)
    warn = []
    out = ad.read_file(bytes(img), e, strict=False, warnings=warn)
    assert out[2 * ad.OFS_DATA:2 * ad.OFS_DATA + ad.BSIZE] == raw
    assert any('no OFS data header' in w for w in warn)
    # a broken header block is reported by walk
    img[e['block'] * ad.BSIZE + 200] ^= 1
    with pytest.raises(ad.DOSError):
        ad.walk(bytes(img))
    rows = ad.walk(bytes(img), strict=False)
    assert rows[0]['checksum_ok'] is False


def test_ofs_file_holding_an_atomik_block(rnd):
    payload = rnd(300) + b'level data ' * 200 + rnd(300)
    blk = atomik.pack(payload)
    img = ad.build_image({'levels/l1.atn': blk, 'readme': b'plain'})
    rep = scan.scan(img)
    hits = rep['atomik']
    assert len(hits) == 1 and hits[0]['offset'] % ad.BSIZE == 24
    assert not hits[0]['verified'] and 'OFS data block' in hits[0]['hint']
    assert 'OFS data block' in scan.format_report(rep)
    body = ad.read_file(img, ad.find(img, 'levels/l1.atn'))
    assert body == blk and atomik.unpack(body) == payload


def test_cli_ls_cat_extract(tmp_path, capsys, rnd):
    files = {'a.bin': rnd(700), 'd/b.bin': b'bbb'}
    disk = tmp_path / 'd.adf'
    disk.write_bytes(ad.build_image(files, name='VOL'))
    assert cli.main(['adf', 'ls', str(disk)]) == 0
    out = capsys.readouterr().out
    assert 'volume "VOL"' in out and 'd/b.bin' in out
    assert cli.main(['adf', 'cat', str(disk), '-p', 'D/B.BIN', '-o', str(tmp_path / 'b')]) == 0
    assert (tmp_path / 'b').read_bytes() == b'bbb'
    assert cli.main(['adf', 'extract', str(disk), '-o', str(tmp_path / 'x')]) == 0
    assert (tmp_path / 'x' / 'a.bin').read_bytes() == files['a.bin']
    assert (tmp_path / 'x' / 'd' / 'b.bin').read_bytes() == b'bbb'
    with pytest.raises(SystemExit):
        cli.main(['adf', 'cat', str(disk), '-p', 'missing', '-o', str(tmp_path / 'm')])


def test_mcp_adf_tools(tmp_path, rnd):
    pytest.importorskip('mcp')
    import asyncio
    from arek import mcp_server
    disk = tmp_path / 'd.adf'
    disk.write_bytes(ad.build_image({'x/y.bin': rnd(1000)}, name='MCP'))

    async def go():
        r = await mcp_server.mcp.call_tool('adf_ls', {'path': str(disk)})
        txt = r.content[0].text if hasattr(r, 'content') else str(r)
        assert 'MCP' in txt and 'x/y.bin' in txt
        r = await mcp_server.mcp.call_tool('adf_file', {'path': str(disk), 'name': 'X/Y.BIN', 'out': str(tmp_path / 'y')})
        assert (tmp_path / 'y').stat().st_size == 1000
    asyncio.run(go())


def test_cli_extract_confines_names_to_output_dir(tmp_path, capsys, rnd):
    img = bytearray(ad.build_image({'ok.bin': b'fine', 'evil.bin': b'bad'}))
    e = ad.find(bytes(img), 'evil.bin')
    blk = memoryview(img)[e['block'] * ad.BSIZE:(e['block'] + 1) * ad.BSIZE]
    ad._put_bstr(blk, ad.BSIZE - 80, '../../escaped', 30)     # a hostile name in the image
    ad._put_checksum(blk)
    disk = tmp_path / 'd.adf'
    disk.write_bytes(bytes(img))
    out = tmp_path / 'out'
    assert cli.main(['adf', 'extract', str(disk), '-o', str(out)]) == 0
    assert (out / 'ok.bin').read_bytes() == b'fine'
    assert not (tmp_path / 'escaped').exists() and not (out / 'escaped').exists()
    assert 'unsafe name' in capsys.readouterr().err
