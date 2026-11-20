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


def test_auto_soft_drops_a_root_that_branches_nowhere():
    """1.0.14 (Turrican II KIT-GAPS 21): data decoded as a bra to a negative address (or out of a resident translation's
    range) is a frontier: --auto-soft drops the root instead of the generator refusing 'skok mimo funkci na $-25c8'."""
    img = bytearray(0x100)
    img[0x000:0x004] = bytes.fromhex('70014e75')                 # $1000 good root
    img[0x010:0x014] = bytes.fromhex('6000') + (0x10000 - 0x2000).to_bytes(2, 'big')   # $1010 bra.w $-ffe: below 0
    rep = {}
    src, _, entries = recomp.generate(bytes(img), 0x1000, auto=[0x1000, 0x1010], auto_soft=True, report=rep)
    assert 0x1000 in entries and 0x1010 not in entries
    assert rep['dropped'] and 'negative' in rep['dropped'][0][1], rep


def test_scan_finds_a_pointer_inside_word_long_pairs():
    """1.0.14 (Turrican II KIT-GAPS 22): in a table of (word, long) pairs the misaligned long read across a word and the
    next pointer's high word can itself land on code; a run that went on at a stride of 4 then jumped over the next
    aligned pointer (the final boss's handler of Turrican II 5-2)."""
    img = bytearray(0x20100)
    img[0x1000:0x1004] = bytes.fromhex('70014e75')                # code
    img[0x1180:0x1184] = bytes.fromhex('70024e75')                # code: the pointer that was missed
    img[0x20000:0x20004] = bytes.fromhex('70034e75')              # code where the misaligned read lands
    img[0x100:0x104] = struct.pack('>I', 0x1000)                  # L1
    img[0x104:0x106] = bytes.fromhex('0002')                      # w2: (w2 << 16 | hi(L2)) = $20000, code
    img[0x106:0x10a] = struct.pack('>I', 0x1180)                  # L2
    r = roots.scan(bytes(img), 0)
    assert 0x1180 in r and 'ptr' in r[0x1180], sorted(hex(a) for a in r)


def offset_image():
    """1.0.86 (SWIV): offset tables the code adds to a base. $2000 a behaviour table of (word, offset) pairs read with
    movem and added twice to a base (SWIV's $16422 / $16564); $2200 a relative jump table (move.w + jmp (T,pc,d0))."""
    img = bytearray(bytes.fromhex('4e71') * 0x180)                # nops: the linear decode stays in step
    put = lambda a, hx: img.__setitem__(slice(a - 0x2000, a - 0x2000 + len(hx) // 2), bytes.fromhex(hx))
    put(0x2000, '41fa003e')                    # lea $2040(pc),a0          the table
    put(0x2004, '4c980006')                    # movem.w (a0)+,d1/d2
    put(0x2008, '4a416704b24066f4')            # tst.w d1 ; beq ; cmp.w d0,d1 ; bne $2004
    put(0x2010, '41fa006e')                    # lea $2080(pc),a0          the base
    put(0x2014, 'd0c2d0c24e75')                # adda.w d2,a0 (twice: offset * 2) ; rts
    for k, rel in enumerate((0x40, 0x48, 0x50, 0x58)):
        img[0x40 + 4 * k:0x44 + 4 * k] = struct.pack('>Hh', 0x0404 + k, rel)
    put(0x2080, '4e75')                        # the base itself: code (SWIV: a bra)
    for k in range(4):
        put(0x2100 + 0x10 * k, '70%02x4e75' % k)                  # four handlers
    put(0x2200, '303b00084efb0004')            # move.w $220a(pc,d0.w),d0 ; jmp $220a(pc,d0.w)
    put(0x2208, '4e71')
    for k, o in enumerate((0x16, 0x26, 0x36, 0x46)):
        img[0x20a + 2 * k:0x20c + 2 * k] = struct.pack('>h', o)
    put(0x2212, '0000')                        # an offset 0 ends the table
    for k in range(4):
        put(0x2220 + 0x10 * k, '72%02x4e75' % k)
    put(0x2290, '41fa0000d0c34e75')            # lea + adda without a table before it: nothing
    return bytes(img)


def test_offset_tables_from_the_code_that_reads_them(tmp_path, capsys):
    data = offset_image()
    tabs = roots.offset_tables(data, 0x2000, 0x2000, 0x2300)
    got = {(t['table'], t['base'], t['stride'], t['field'], t['scale'], t['site']): t['targets'] for t in tabs}
    assert got == {(0x2040, 0x2080, 4, 2, 2, 0x2014): [0x2100, 0x2110, 0x2120, 0x2130],
                   (0x220a, 0x220a, 2, 0, 1, 0x2204): [0x2220, 0x2230, 0x2240, 0x2250]}, got
    r = roots.scan(data, 0x2000, kinds=('ofs',))
    assert set(r) == {0x2100, 0x2110, 0x2120, 0x2130, 0x2220, 0x2230, 0x2240, 0x2250}
    assert roots.offset_tables(data, 0x2000, 0x2000, 0x2300, min_ofs=5) == []   # four entries, five asked
    assert 'ofs' in roots.scan(data, 0x2000)[0x2100]                            # the default kinds include it
    f = tmp_path / 'ofs.bin'
    f.write_bytes(data)
    assert cli.main(['roots', str(f), '--base', '0x2000', '--kinds', 'ofs']) == 0
    out = capsys.readouterr()
    assert '002100 ofs' in out.out and 'offset table 002040: base 002080, 4-byte entries, offset at +2, x2, added at 002014: 4 targets' in out.err


def test_a_root_inside_a_short_bra_table_brings_the_table():
    """1.0.99 (Turrican II, boss 3-2): `lea` finds the first entry of a table of three bra.w (shorter than min_slots 4);
    the other entries the code reaches by a computed address become roots too. Two bra.w in a row next to a root are not
    enough (a 6000 xxxx pair also occurs in data); min_table = 0 turns the rule off; slot_table follows a run both ways."""
    import struct
    img = bytearray(0x200)
    img[0x00:0x06] = bytes.fromhex('41fa' '00fe' '4e75')                 # lea $100(pc),a0 ; rts  -> the table at $100
    for k, t in enumerate((0x140, 0x140, 0x160)):                         # bra.w to $140, $140, $160
        at = 0x100 + 4 * k
        img[at:at + 4] = struct.pack('>Hh', 0x6000, t - (at + 2))
    img[0x140:0x142] = bytes.fromhex('4e75'); img[0x160:0x162] = bytes.fromhex('4e75')
    img[0x180:0x184] = struct.pack('>Hh', 0x6000, 0x140 - 0x182)         # a pair of bra.w after a code root at $17c
    img[0x184:0x188] = struct.pack('>Hh', 0x6000, 0x160 - 0x186)
    img[0x17c:0x180] = bytes.fromhex('4e71' '4e75')
    r = roots.scan(bytes(img), 0, kinds=('slots', 'lea'))
    assert {0x100, 0x104, 0x108} <= set(r) and 'slots' in r[0x104] and 'slots' in r[0x108]
    off = roots.scan(bytes(img), 0, kinds=('slots', 'lea'), min_table=0)
    assert 0x100 in off and 0x104 not in off and 0x108 not in off
    assert roots.slot_table(bytes(img), 0, 0x108) == [0x100, 0x104, 0x108] and roots.slot_table(bytes(img), 0, 0x140) == []
    assert roots.slot_table(bytes(img), 0, 0x184) == [0x180, 0x184]      # a pair: found, but below min_table 3
    assert 0x184 not in r
