import struct

import pytest

from arek import adf, copper, hunk


def test_hunk_build_load_relocates():
    code = b'\x4e\x75' * 4 + struct.pack('>I', 0x10)
    exe = hunk.build([('CODE', code), ('DATA', b'\x01\x02\x03\x04'), ('BSS', bytes(8))],
                     {0: {1: [8]}})
    assert hunk.is_hunk(exe)
    info = hunk.info(exe)
    assert [h['kind'] for h in info['hunks']] == ['CODE', 'DATA', 'BSS']
    hs = hunk.load(exe, 0x1000)
    assert [b for b, _ in hs] == [0x1000, 0x100c, 0x1010]
    assert struct.unpack('>I', hs[0][1][8:12])[0] == 0x10 + 0x100c
    assert hunk.single(hunk.build([('CODE', code)]), 0x40000)[:8] == code[:8]


def test_hunk_rejects_unknown_record():
    exe = bytearray(hunk.build([('CODE', b'\x4e\x75\x4e\x75')]))
    struct.pack_into('>I', exe, 24, 0x3f0)            # HUNK_OVERLAY instead of CODE
    with pytest.raises(hunk.FormatError):
        hunk.info(bytes(exe))


def test_hunk_split_streams():
    a = hunk.build([('CODE', b'\x4e\x75\x4e\x75'), ('DATA', b'\x00\x01\x02\x03'),
                    ('CODE', b'\x60\xfe\x4e\x71'), ('BSS', bytes(16))])
    # cut the stream after the second HUNK_END for the two-file layout
    reader = hunk.Reader(a)
    hunk.header(reader)
    hs = [bytearray(4) for _ in range(4)]
    hunk.records(reader, hs, [0] * 4, 0, 2)
    cut = reader.pos
    out = hunk.split(a[:cut], a[cut:], 0xc00000, 0x10000)
    assert [b for b, _ in out] == [0xc00000, 0xc00004, 0x10000, 0x10004]
    assert out[2][1] == b'\x60\xfe\x4e\x71'


def _disk():
    d = bytearray(adf.SIZE)
    d[0:4] = b'DOS\0'
    d[12:16] = b'\x43\xfa\x00\x18'
    struct.pack_into('>I', d, 4, adf.bootblock_checksum(d[:1024]))
    return d


def test_adf_bootblock_and_geometry():
    d = _disk()
    bb = adf.bootblock(bytes(d))
    assert bb['bootable'] and bb['dostype_text'] == 'DOS0'
    d[20] ^= 1
    assert not adf.bootblock(bytes(d))['bootable']
    assert adf.chs(adf.SECTORS_PER_TRACK * 3 + 5) == (1, 1, 5)
    assert adf.offset(1, 1, 5) == (adf.SECTORS_PER_TRACK * 3 + 5) * adf.SECTOR
    with pytest.raises(adf.ADFError):
        adf.check_size(bytes(100))


def test_adf_entropy_regions(rnd):
    d = _disk()
    d[0x4000:0x6000] = rnd(0x2000)
    regs = adf.regions(bytes(d))
    packed = [r for r in regs if r['class'] == 'packed']
    assert packed and packed[0]['start'] == 0x4000 and packed[0]['end'] == 0x6000
    m = adf.ascii_map(bytes(d))
    assert m.count('#') == 16
    inv = adf.inventory(bytes(d), 'x')
    assert inv['empty_sectors'] == adf.TRACKS * adf.SECTORS_PER_TRACK - 1 - 16


def test_copper_disassemble():
    cl = bytes.fromhex('0180000001001200') + bytes.fromhex('8101fffe') + bytes.fromhex('fffffffe')
    rows = copper.disassemble(cl, 0x20000)
    assert rows[0] == (0x20000, 'MOVE  COLOR00   <- $0000')
    assert 'BPLCON0' in rows[1][1]
    assert rows[2][1].startswith('WAIT  VP=129')
    assert rows[3][1].startswith('END')
    assert copper.regname(0x0e4) == 'BPL2PTH' and copper.regname(0x15a) == 'SPR3CTL'
