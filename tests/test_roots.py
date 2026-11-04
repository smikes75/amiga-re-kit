"""arek roots: static roots of a whole-game translation, and arek recomp --auto-soft / --auto-file."""
import json
import struct

import pytest

from arek import cli
from arek.m68k import recomp, roots
from arek.m68k.decoder import Unsupported


def image():
    img = bytearray(0x400)
    # $1000: lea table(pc),a0 ; jsr (a0,d0.w) ; rts        - the table base through lea
    img[0x000:0x004] = bytes.fromhex('41fa0012')                     # lea $1014(pc),a0   (pc = $1002 + $12)
    img[0x004:0x008] = bytes.fromhex('4eb00000')                     # jsr 0(a0,d0.w)
    img[0x008:0x00a] = bytes.fromhex('4e75')
    img[0x00a:0x014] = bytes.fromhex('217c0000112000044e75')         # move.l #$1120,4(a0) ; rts   - a handler stored into a structure
    # $1014: four bra.w slots
    for k in range(4):
        img[0x014 + 4 * k:0x018 + 4 * k] = bytes.fromhex('6000') + struct.pack('>h', 0x100 + 0x10 * k - (0x16 + 4 * k))
    # $1100.. four handlers: moveq ; rts
    for k in range(4):
        img[0x100 + 0x10 * k:0x104 + 0x10 * k] = bytes.fromhex('70%02x4e75' % (k + 1))
    img[0x120:0x124] = bytes.fromhex('70094e75')                     # the stored handler
    # $1200: a pointer table of three code addresses, then data
    img[0x200:0x20c] = struct.pack('>III', 0x1100, 0x1120, 0x1004)
    img[0x300:0x304] = bytes.fromhex('fdfdfdfd')                     # data a bad root points at
    return bytes(img)


def test_scan_finds_every_kind():
    r = roots.scan(image(), 0x1000)
    slots = {0x1014, 0x1018, 0x101c, 0x1020}
    assert all(r[a] >= {'slots', 'lea'} for a in slots)
    assert r[0x1100] >= {'ptr'} and r[0x1004] >= {'ptr'} and r[0x1120] >= {'ptr', 'imm'}
    assert 0x1300 not in r and 0x1200 not in r
    only = roots.scan(image(), 0x1000, kinds=('imm',))
    assert set(only) == {0x1120}
    assert roots.scan(image(), 0x1000, lo=0x1000, hi=0x1100, kinds=('ptr',)) == {}   # targets outside the range do not count
    assert '001120 imm,ptr' in roots.format_roots(r)


def test_cli_and_auto_soft(tmp_path, capsys):
    f = tmp_path / 'img.bin'
    f.write_bytes(image())
    assert cli.main(['roots', str(f), '--base', '0x1000', '--json', str(tmp_path / 'r.json'), '--kinds', 'slots', 'imm']) == 0
    j = json.load(open(tmp_path / 'r.json'))
    assert j['1014'] == ['slots'] and j['1120'] == ['imm'] and '1100' not in j
    with pytest.raises(Unsupported):
        recomp.generate(image(), 0x1000, auto=[0x1100, 0x1300])
    rep = {}
    src, _, entries = recomp.generate(image(), 0x1000, auto=[0x1100, 0x1300], auto_soft=True, report=rep)
    assert 0x1100 in entries and 0x1300 not in entries and rep['dropped'][0][0] == 0x1300 and 'void f_001100(' in src
    with pytest.raises(Unsupported):                                  # a frontier inside a reached routine still refuses
        recomp.generate(image(), 0x1000, auto=[0x1000], auto_soft=True)
    (tmp_path / 'roots.txt').write_text('1100\n# a comment\n1300\n')
    assert cli.main(['recomp', str(f), '--base', '0x1000', '--auto-file', str(tmp_path / 'roots.txt'), '--auto-soft',
                     '-o', str(tmp_path / 'g.c')]) == 0
    err = capsys.readouterr().err
    assert 'root 001300 dropped' in err and 'void f_001100(' in (tmp_path / 'g.c').read_text()


def test_auto_soft_drops_a_root_whose_call_tree_reaches_data():
    """1.0.11 (Turrican II KIT-GAPS 16): a root found by a static scan that calls (bsr) into bytes that are not code is
    dropped too - not only a root whose own first words are bad; the good root stays."""
    img = bytearray(0x400)
    img[0x000:0x004] = bytes.fromhex('70014e75')                 # $1000 good root: moveq #1,d0 ; rts
    img[0x100:0x104] = bytes.fromhex('61004e75'[:4]) + bytes.fromhex('00fe')   # $1100 bsr.w $1200 (offset $fe from $1102)
    img[0x104:0x106] = bytes.fromhex('4e75')
    img[0x200:0x204] = bytes.fromhex('fdfdfdfd')                 # $1200 data
    with pytest.raises(Unsupported):
        recomp.generate(bytes(img), 0x1000, auto=[0x1000, 0x1100])
    rep = {}
    src, _, entries = recomp.generate(bytes(img), 0x1000, auto=[0x1000, 0x1100], auto_soft=True, report=rep)
    assert 0x1000 in entries and 0x1100 not in entries and 'void f_001000(' in src
    assert rep['dropped'] and rep['dropped'][0][0] == 0x1100 and 'reaches $1200' in rep['dropped'][0][1], rep


def test_scan_finds_pointers_and_lea_targets_the_linear_sweep_misses():
    """1.0.12 (Turrican II KIT-GAPS 17): a module header's long pointing at a routine the linear decode is out of step
    with (data before it), and a lea of that routine, are roots."""
    img = bytearray(0x200)
    img[0x000:0x004] = struct.pack('>I', 0x1106)                  # $1000 header: a pointer to the routine
    img[0x004:0x008] = bytes.fromhex('47fa0100')                  # $1004 lea $1106(pc),a3
    img[0x008:0x00a] = bytes.fromhex('4e75')
    img[0x100:0x106] = bytes.fromhex('203c0000')  + b'\x70'      # $1100 data: move.l #$0000_70.. swallows $1106 in the sweep
    img[0x106:0x10a] = bytes.fromhex('70054e75')                  # $1106 moveq #5,d0 ; rts
    r = roots.scan(bytes(img), 0x1000)
    assert 0x1106 in r and r[0x1106] >= {'ptr', 'lea'}, r.get(0x1106)


def test_walk_marks_a_flow_leaving_the_image():
    """1.0.12 (KIT-GAPS 18): a root whose flow runs off the end of the image (data decoded as code) has a frontier,
    so --auto-soft drops it instead of the generator emitting a jump to a label that does not exist."""
    img = bytes.fromhex('8080808080808080')                        # or.l d0,d0 x4, then the end of the image
    with pytest.raises(Unsupported):
        recomp.generate(img, 0x1000, auto=[0x1000])
    rep = {}
    recomp.generate(img + b'', 0x1000, auto=[0x1000], auto_soft=True, report=rep)
    assert rep['dropped'] and 'past the end' in rep['dropped'][0][1]
