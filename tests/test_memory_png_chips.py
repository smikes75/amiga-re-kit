"""Chip + slow RAM in the generated C, PNG output without Pillow, custom chip registers
in a bpstate capture."""
import struct
import subprocess
import zlib

import pytest

from arek import cli
from arek.headless import bpstate, shot
from arek.m68k import recomp
from arek.m68k.decoder import Flow

from test_recomp_semantics import BASE, run

# move.l #$12345678,$c00010.l ; move.l $c00010.l,d0
SLOW_RW = '23fc 1234 5678 00c0 0010 2039 00c0 0010'.replace(' ', '')


def test_slow_ram_is_modelled_and_logged(tmp_path):
    logs = []
    d, *_ = run(tmp_path, SLOW_RW, {}, logs=logs, slow=(0xc00000, 0x80000))
    assert d[0] == 0x12345678
    assert 'w c00010' in logs[0] and 'w c00013' in logs[0]


def test_without_slow_ram_the_access_stops_the_run(tmp_path):
    with pytest.raises(subprocess.CalledProcessError) as e:
        run(tmp_path, SLOW_RW, {})
    assert e.value.returncode == 3


def test_memsz_and_slow_defines():
    src, _, _ = recomp.generate(bytes.fromhex('4e75'), BASE, auto=[BASE], memsz=0x100000,
                                slow=(0xc00000, 0x40000))
    head = src[:src.index('#include')]
    assert '#define MEMSZ 0x100000u' in head and '#define SLOWSZ 0x40000u' in head
    with pytest.raises(ValueError):
        recomp.generate(bytes.fromhex('4e75'), BASE, auto=[BASE], slow=(0xc00000, 0x40000),
                        flow=Flow(lib=True))


def test_recomp_cli_slow(tmp_path, capsys):
    f = tmp_path / 'p.bin'
    f.write_bytes(bytes.fromhex(SLOW_RW + '4e75'))
    assert cli.main(['recomp', str(f), '--base', '0x1000', '--auto', '0x1000', '--slow', 'c00000:80000',
                     '--memsz', '0x80000', '-o', str(tmp_path / 'p.c')]) == 0
    assert '#define SLOWBASE 0xc00000u' in (tmp_path / 'p.c').read_text()


def _png_pixels(path):
    b = path.read_bytes()
    assert b[:8] == b'\x89PNG\r\n\x1a\n'
    pos, idat, ihdr = 8, b'', None
    while pos < len(b):
        n, kind = struct.unpack('>I4s', b[pos:pos + 8])
        body = b[pos + 8:pos + 8 + n]
        assert struct.unpack('>I', b[pos + 8 + n:pos + 12 + n])[0] == zlib.crc32(kind + body)
        if kind == b'IHDR':
            ihdr = struct.unpack('>IIBBBBB', body)
        elif kind == b'IDAT':
            idat += body
        pos += 12 + n
    w, h = ihdr[:2]
    raw = zlib.decompress(idat)
    return ihdr, [raw[y * (w * 3 + 1) + 1:(y + 1) * (w * 3 + 1)] for y in range(h)]


def test_png_without_pillow(tmp_path):
    rgb = bytes([255, 0, 0, 0, 255, 0, 0, 0, 255, 9, 9, 9])
    p = shot.write_png(tmp_path / 'x.png', 2, 2, rgb)
    ihdr, rows = _png_pixels(p)
    assert ihdr == (2, 2, 8, 2, 0, 0, 0) and rows == [rgb[:6], rgb[6:]]


def test_raw_frame_to_png(tmp_path):
    raw = tmp_path / 'f.raw'
    raw.write_bytes(bytes(range(256)) * (shot.RAW_W * shot.RAW_H * 3 // 256) + bytes(shot.RAW_W * shot.RAW_H * 3 % 256))
    ihdr, rows = _png_pixels(shot.raw_to_png(raw, tmp_path / 'f.png'))
    assert ihdr[:2] == (shot.RAW_W, shot.RAW_H) and b''.join(rows) == raw.read_bytes()


# what vAmiga 5.0b2 prints (shortened), with the CPU part around it
CHIPS_OUT = '''
r cpu
              PC : 0x00c01a46
try r agnus

Registers:

                  DMACON : 0x03f0
                 BPLCON0 : 0x5200
                  BPL0PT : 0x0002dbae  BPL1PT : 0x0002f5ae
                  BPL6PT : 0x00000000  BPL6PT : 0x00000000
try r copper

Registers:

                   COPPC : 0x00006fd4 ( +4 )
                  COP1LC : 0x00006fd0
                  COP1LC : 0x00007800
                   CDANG : no
try r denise

Registers:

                 SPRxPOS : 0x05cd 0x0000 0x0000 0x0000 0x0000 0x0000 0x0000 0x0000
try r blitter

Registers:

                 BLTAMOD : -2
                    USEA : yes
commander
mem save bin /x 0 524288
'''


def test_parse_chips():
    c = bpstate.parse_chips(CHIPS_OUT)
    assert c['agnus']['DMACON'] == 0x3f0 and c['agnus']['BPL1PT'] == 0x2f5ae
    assert 'BPL6PT#2' in c['agnus']
    assert c['copper']['COP1LC'] == 0x6fd0 and c['copper']['COP1LC#2'] == 0x7800
    assert c['copper']['COPPC'] == 0x6fd4 and c['copper']['CDANG'] is False
    assert c['denise']['SPRxPOS'][0] == 0x5cd and len(c['denise']['SPRxPOS']) == 8
    assert c['blitter'] == {'BLTAMOD': -2, 'USEA': True}
    assert 'cpu' not in c


def test_cpu_pc_is_not_taken_from_copper():
    assert bpstate.parse_regs('COPPC : 0x00006fd4\n  PC : 0x00c01a46\n')['pc'] == 0xc01a46
