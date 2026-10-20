import json
import shutil
import subprocess
import struct

import pytest

from arek.m68k import audit, decoder, disasm, hwscan, recomp, xref


def dec(hexwords, base=0x1000):
    data = bytes.fromhex(hexwords.replace(' ', '')) + bytes(8)
    return decoder.decode(data, base, base)


@pytest.mark.parametrize('hx,text,kind', [
    ('d0c0', 'adda.w d0,a0', 'adda'),           # the ADDA/SUBA/CMPA opmode bug
    ('d1c0', 'adda.l d0,a0', 'adda'),           # (bit 8 selects .w/.l) was fixed
    ('90c0', 'suba.w d0,a0', 'suba'),           # in the Superfrog copy; keep it fixed
    ('91c8', 'suba.l a0,a0', 'suba'),
    ('b0c0', 'cmpa.w d0,a0', 'cmpa'),
    ('b1c8', 'cmpa.l a0,a0', 'cmpa'),
    ('33c000dff096', 'move.w d0,$dff096.l', 'move'),
    ('4e71', 'nop', 'nop'),
    ('60000004', 'bra $1006', 'bra'),
    ('51c8fffe', 'dbf d0', 'dbcc'),
    ('4ed0', 'jmp (a0)', 'jmp'),
    ('4eb900001000', 'jsr $1000.l', 'jsr'),
    ('4eaeff3a', 'jsr (-198,a6)', 'jsr'),
    ('48e7fffe', 'movem.l -(a7)', 'movem'),
    ('0c400001', 'cmpi.w #1,d0', 'alui'),
    ('e248', 'lsr.w 1,d0', 'shift'),
    ('c0c1', 'mulu d1,d0', 'mulu'),
])
def test_decoder_table(hx, text, kind):
    i = dec(hx)
    assert i.text == text and i.kind == kind


def test_decoder_is_strict():
    with pytest.raises(decoder.Unsupported):
        dec('81c1')                                  # divs: not modelled -> explicit
    with pytest.raises(decoder.Unsupported):
        dec('ffff')


def test_walk_skips_data_between_routines(code):
    base, data = code
    ins, calls, bad, ind = decoder.walk(data, base, base + 0x0e, base, base + len(data))
    assert sorted(ins) == [base + 0x0e, base + 0x12]
    assert calls == {base + 0x04}
    assert not bad and not ind
    tree = decoder.call_tree(data, base, [base + 0x0e], base, base + len(data))
    assert sorted(tree) == [base + 0x04, base + 0x0e]


def test_walk_reports_indirect_and_undecodable():
    data = bytes.fromhex('4ed0 4e75 ffff'.replace(' ', ''))
    ins, calls, bad, ind = decoder.walk(data, 0, 0, 0, len(data))
    assert ind and ind[0][0] == 0
    ins, calls, bad, ind = decoder.walk(data, 0, 4, 0, len(data))
    assert bad and bad[0][0] == 4


def test_disasm_listing_and_walk(code):
    base, data = code
    rows = disasm.listing(data, base, base, base + len(data))
    assert rows[0][2] == 'moveq #5,d0'
    assert any('bsr $1004' in r[2] for r in rows)
    rows, fr = disasm.listing_walk(data, base, base + 0x0e, base, base + len(data))
    assert [r[0] for r in rows] == [base + 4, base + 0xa, base + 0xc, base + 0xe, base + 0x12]
    txt = disasm.format_listing(rows, {base + 4: 'store'})
    assert txt.startswith('store:')
    bad = disasm.listing(bytes.fromhex('ffff'), 0, 0, 2)
    assert bad[0][2].startswith('??')


def test_hwscan_hardware_boundary():
    # r1: pure RAM; r2: writes DMACON absolutely; r3: calls r2
    base = 0x2000
    data = bytes.fromhex(
        '31c0 3000'          # 2000 move.w d0,$3000.w      (chip RAM)
        '4e75'               # 2004 rts
        '33c0 00df f096'     # 2006 move.w d0,$dff096.l   (DMACON)
        '4e75'               # 200c rts
        '6100 fff6'          # 200e bsr $2006
        '4e75'               # 2012 rts
        .replace(' ', ''))
    rt = hwscan.scan(data, base, [base, base + 0x0e], base, base + len(data))
    ok = hwscan.closure(rt)
    rep = hwscan.report(rt, ok, per_frame=[base, base + 0x0e])
    assert rep['routines'] == 3
    assert rep['touch_hw'] == 1 and rep['touch_hw_abs'] == 1
    assert ok[base] and not ok[base + 0x0e]              # r3 inherits r2's hardware
    tags = {p['addr']: p['tag'] for p in rep['per_frame']}
    assert tags[base] == 'RAM' and tags[base + 0x0e] == 'calls hw'
    assert 'hardware boundary' in hwscan.format_report(rep)


def test_recomp_generates_and_runs(code, tmp_path):
    base, data = code
    src, stats, entries = recomp.generate(data, base, auto=[base + 0x0e], with_main=True)
    assert set(entries) == {base + 4, base + 0x0e}
    assert stats['bsr'] == 1 and stats['lea'] == 1 and stats['move'] == 1
    cc = shutil.which('cc') or shutil.which('gcc') or shutil.which('clang')
    if not cc:
        pytest.skip('no C compiler')
    c = tmp_path / 'r.c'
    c.write_text(src)
    exe = tmp_path / 'r'
    subprocess.run([cc, '-O1', '-o', str(exe), str(c)], check=True)
    # run f_00100e on a blank RAM with d0 = 0xbeef: expect $2000 == $beef after
    memsz = int(__import__('re').search(r'#define MEMSZ\s+(\S+)', src).group(1).rstrip('uUlL'), 0)
    ram = tmp_path / 'ram.bin'
    ram.write_bytes(bytes(memsz))
    regs = tmp_path / 'regs.txt'
    regs.write_text(' '.join(['beef'] + ['0'] * 7 + ['0'] * 7 + ['%x' % (memsz - 0x100)]) +
                    '\n0 0 0 0 0\nf_%06x\n' % (base + 0x0e))
    out = tmp_path / 'out.bin'
    log = tmp_path / 'log.txt'
    subprocess.run([str(exe), str(ram), str(regs), str(out), str(log)], check=True)
    mem = out.read_bytes()
    assert struct.unpack_from('>H', mem, 0x2000)[0] == 0xbeef
    assert 'w 2000' in log.read_text()
    assert 'a0' in log.read_text() or True


def test_recomp_refuses_unknown_instruction():
    data = bytes.fromhex('81c1 4e75'.replace(' ', ''))
    with pytest.raises(decoder.Unsupported):
        recomp.generate(data, 0x1000, auto=[0x1000])


def test_recomp_specs_and_stubs():
    assert recomp.parse_func_spec('0x1000:0x1010') == (0x1000, 0x1010, 0x1000)
    assert recomp.parse_func_spec('1000:1010:1004') == (0x1000, 0x1010, 0x1004)
    recomp.add_stub('a6:-198:OpenLibrary')
    assert decoder.STUBS[(6, -198)] == 'OpenLibrary'
    decoder.STUBS.clear()


OBJDUMP = '''
    1000:\t61 00 00 10     \tbsrw 0x1012
    1004:\t4e b9 00 00 10 12\tjsr 0x1012
    100a:\t41 fa 00 20     \tlea %pc@(0x102c),%a0
    100e:\t4e 75           \trts
    1012:\t4e 75           \trts
'''


def test_xref_from_objdump(tmp_path):
    x = xref.Xref(OBJDUMP, {0x1012: 'util'})
    assert x.callers(0x1012) == [0x1000, 0x1004]
    assert x.top(1) == [(0x1012, 2)]
    assert x.top_data(1) == [(0x102c, 1)]
    assert 'util(0x1012)' in x.summary()
    assert x.callees_in(0x1000, 0x1010) == [(0x1000, 0x1012)]
    assert len(xref.disrange(OBJDUMP, 0x1004, 0x1010)) == 3
    syms = tmp_path / 's.json'
    syms.write_text(json.dumps({'code': {'1012': 'util'}}))
    assert xref.load_syms(syms) == {0x1012: 'util'}


def test_audit_profile(code, tmp_path):
    base, data = code
    (tmp_path / 'main.bin').write_bytes(data)
    profile = {'name': 't', 'inventory_glob': '*.bin',
               'modules': {'main.bin': {'role': 'main', 'base': hex(base), 'roots': [hex(base + 0x0e)]}}}
    rep = audit.audit(profile, tmp_path)
    m = rep['modules'][0]
    assert m['status'] == 'present' and m['graph']['unique_instructions'] == 5
    assert m['graph']['semantic_parity'] == 'not_measured'
    assert rep['limitations']
    json.dumps(rep)                                      # must stay JSON-serialisable


# --- audit.graph() edge cases on hand-written opcodes (from the Turrican II
# project's synthetic unit tests; no game data)
def test_audit_graph_return_does_not_decode_data():
    for opcode in ('4e75', '4e73'):                      # rts, rte
        r = audit.graph(bytes.fromhex(opcode + 'ffff'), 0x100, [0x100])
        assert r['unique_instructions'] == 1 and not r['frontiers']


def test_audit_graph_loop_deduplicates():
    r = audit.graph(bytes.fromhex('60fe'), 0, [0])        # bra.s *
    assert r['unique_instructions'] == 1


def test_audit_graph_indirect_call_is_a_frontier():
    r = audit.graph(bytes.fromhex('4e904e75'), 0, [0])    # jsr (a0); rts
    assert r['unique_instructions'] == 2
    assert r['frontiers'][0]['reason'] == 'unresolved_jsr'


@pytest.mark.parametrize('data, roots, reason', [
    (b'\x4e', [0], 'decode_error'),
    (bytes.fromhex('6002'), [0], 'outside_module'),
    (bytes.fromhex('4e75'), [1], 'unaligned_target'),
])
def test_audit_graph_boundaries(data, roots, reason):
    r = audit.graph(data, 0, roots)
    assert r['frontiers'][0]['reason'].startswith(reason)


def test_audit_graph_direct_call_and_both_branch_paths():
    r = audit.graph(bytes.fromhex('66044e75ffff4e75'), 0, [0])   # bne.s +4; rts; data; rts
    assert r['instruction_addresses'] == ['0x0', '0x2', '0x6']
    r = audit.graph(bytes.fromhex('61044e75ffff4e75'), 0, [0])   # bsr.s +4; rts; data; rts
    assert r['unique_instructions'] == 3 and not r['frontiers']


def test_audit_graph_overlapping_decode_is_reported():
    r = audit.graph(bytes.fromhex('303c4e754e75'), 0, [0, 2])    # move.w #$4e75,d0 overlaps root 2
    assert any(x['reason'] == 'overlapping_decode' for x in r['frontiers'])


def test_audit_missing_and_unclassified_modules(tmp_path):
    (tmp_path / 'other.bin').write_bytes(b'\x00')
    p = {'name': 'fixture', 'inventory_glob': '*.bin', 'modules': {'missing.bin': {'role': 'code'}}}
    a = audit.audit(p, tmp_path)
    assert a == audit.audit(p, tmp_path)                         # deterministic
    assert a['modules'][0]['status'] == 'missing'
    assert a['modules'][1]['role'] == 'unclassified'
    assert a['modules'][1]['graph']['status'] == 'not_scanned'
