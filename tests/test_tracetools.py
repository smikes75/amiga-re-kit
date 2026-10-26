"""Trace tools from the Alien Breed II project: indirect jump targets, per-instruction timing, records by pc,
full-RAM pair differences, a host's slot maps against a bus log, and translated routines call by call."""
import json
import os
import shutil
import struct
import subprocess

import pytest

from arek import bus, cli
from arek.headless import trace, tracetools
from arek.m68k import recomp, verify


def rec(pc, frame=0, v=0, h=0, d=None, a=None, ranges=None, sr=0):
    return {'kind': 'VTR2', 'addr': pc, 'pc': pc, 'frame': frame, 'v': v, 'h': h, 'sr': sr,
            'd': d or [0] * 8, 'a': a or [0] * 8, 'ranges': ranges or {}, 'hashes': {}}


def write_trace(path, recs):
    with open(path, 'wb') as f:
        for r in recs:
            f.write(trace.encode(r))


def test_indirect_targets(tmp_path):
    img = bytearray(0x2000)
    img[0x1000:0x1002] = bytes.fromhex('4ed0')                       # jmp (a0)
    img[0x1002:0x1006] = bytes.fromhex('4eb10004')                   # jsr 4(a1,d0.w)
    img[0x1006:0x100a] = bytes.fromhex('4efb2802')                   # jmp 2(pc,d2.l)
    recs = [rec(0x1000, a=[0x2000] + [0] * 7), rec(0x1000, a=[0x2100] + [0] * 7), rec(0x1000, a=[0x2000] + [0] * 7),
            rec(0x1002, d=[0x10] + [0] * 7, a=[0, 0x3000] + [0] * 6), rec(0x1002, d=[0xfff0] + [0] * 7, a=[0, 0x3000] + [0] * 6),
            rec(0x1006, d=[0, 0, 0x100] + [0] * 5)]
    t = tracetools.indirect_targets(recs, bytes(img), 0)
    assert t[0x1000] == {0x2000: 2, 0x2100: 1} and t[0x1002] == {0x3014: 1, 0x2ff4: 1} and t[0x1006] == {0x110a: 1}
    out = tracetools.format_targets(t)
    assert 'site $001000: 3 hits, 2 targets' in out and '--indirect 1002=2ff4,3014' in out
    write_trace(tmp_path / 't.vtr', recs)
    (tmp_path / 'img.bin').write_bytes(img)
    assert cli.main(['trace', 'targets', str(tmp_path / 't.vtr'), str(tmp_path / 'img.bin'), '--base', '0', '--out', str(tmp_path / 't.json'),
                     '--only', '0x1006']) == 0
    assert json.load(open(tmp_path / 't.json')) == {'1006': ['110a']}


def test_pc_compare_and_drift():
    orig = [rec(0x100, 10, 0, 50), rec(0x104, 10, 0, 60), rec(0x108, 10, 0, 70), rec(0x100, 10, 1, 20), rec(0x104, 10, 1, 30), rec(0x200, 10, 1, 40)]
    host = [(10, 0x100, 0, 50), (10, 0x104, 0, 60), (10, 0x108, 0, 72), (10, 0x100, 1, 22), (10, 0x104, 1, 33), (10, 0x300, 1, 40)]
    r = tracetools.pc_compare(orig, host, tick=0x100)
    assert r['seq'] == 5 and r['exact'] == 2 and r['first_time_diff'] == 2 and r['seq_diff'] == (5, 0x200, 0x300, 0x104)
    assert [(k, d, dd, pc) for k, d, dd, pc, *_ in r['drift']] == [(2, 2, 2, 0x108), (4, 3, 1, 0x104)]
    text = tracetools.format_pc_compare(r)
    assert '5 passes with the same pc sequence' in text and 'parts at pass 5: original 000200, host 000300' in text


def test_filter_and_pair_diff(tmp_path):
    ram_a, ram_b = bytes(range(64)), bytearray(range(64))
    ram_b[10] = 0xee
    recs_a = [rec(0x100, 5, 1, 2, ranges={0: ram_a}), rec(0x200, 5, 3, 4, ranges={0: ram_a}), rec(0x100, 6, 1, 2, ranges={0: ram_a})]
    recs_b = [rec(0x100, 5, 1, 2, ranges={0: ram_a}), rec(0x200, 5, 3, 5, ranges={0: bytes(ram_b)}), rec(0x100, 7, 1, 2, ranges={0: ram_a})]
    write_trace(tmp_path / 'a.vtr', recs_a)
    n = tracetools.filter_pcs(str(tmp_path / 'a.vtr'), str(tmp_path / 'f.vtr'), {0x100})
    assert n == 2 and [r['frame'] for r in trace.records(str(tmp_path / 'f.vtr'))] == [5, 6]
    rows = tracetools.pair_diff(recs_a, recs_b)
    assert [r['key'] for r in rows] == [(5, 0x100, 0), (5, 0x200, 0), (6, 0x100, 0), (7, 0x100, 0)]
    assert rows[0]['diffs'] == [] and rows[1]['diffs'] == [(10, 10, 0xee)] and rows[2]['only'] == 'orig' and rows[3]['only'] == 'host'
    assert tracetools.pair_diff(recs_a, recs_b, ignore=[(8, 4)])[1]['diffs'] == []
    text = tracetools.format_pair_diff(rows)
    assert '1 B: $a:0a/ee' in text and 'only in host' in text
    write_trace(tmp_path / 'b.vtr', recs_b)
    assert cli.main(['trace', 'pairdiff', str(tmp_path / 'a.vtr'), str(tmp_path / 'b.vtr')]) == 0
    assert cli.main(['trace', 'filter', str(tmp_path / 'a.vtr'), str(tmp_path / 'g.vtr'), '--pc', '0x200']) == 0


def test_own_compare():
    H, NL = 227, 313
    line_log = bytearray(H); line_log[1] = line_log[3] = 2; line_log[20:24] = b'\x19' * 4; line_log[30] = 1
    line_host = bytearray(line_log); line_host[24] = 0x19; line_host[30] = 0; line_host[31] = 1       # one blitter slot more, CPU moved
    log = {'lines': {(100, v): bytes(line_log) for v in range(NL)}, 'blits': []}
    own = struct.pack('<q', 0) + bytes(line_host) * NL
    frames = bus.own_frames(own, 100, H, NL)
    assert list(frames) == [100]
    rows = bus.own_compare(log, frames, H, NL)
    assert rows[0]['frame'] == 100 and rows[0]['counts'][25] == (4 * NL, 5 * NL) and rows[0]['lines'] == list(range(NL))
    assert rows[0]['first_dma'] == (0, 24, (0, 25)) and rows[0]['dma'] == {(0, 25): NL}
    assert '100  ' in bus.format_own_compare(rows) and 'b:1252/1565' in bus.format_own_compare(rows)


def test_verify_calls(tmp_path):
    cc = bus.compiler()
    if not cc:
        pytest.skip('no C compiler')
    img = bytearray(0x2000)
    img[0x1000:0x1008] = bytes.fromhex('4eb9000011004e71')            # jsr $1100.l; nop
    img[0x1008:0x100a] = bytes.fromhex('4e75')
    img[0x1100:0x110a] = bytes.fromhex('33fc123400004000' + '4e75')  # move.w #$1234,$4000; rts
    src, _, _ = recomp.generate(bytes(img), 0, auto=[0x1000, 0x1100], with_main=True)
    (tmp_path / 'g.c').write_text(src)
    drv = tmp_path / 'drv'
    subprocess.run([cc, '-O1', '-o', str(drv), str(tmp_path / 'g.c')], check=True)
    ram = bytearray(0x80000); ram[:len(img)] = img
    after = bytearray(ram); after[0x4000:0x4002] = bytes.fromhex('1234')
    after[0x7effc:0x7f000] = bytes.fromhex('00001006')                  # the return address the jsr pushed stays below the stack
    wrong = bytearray(ram); wrong[0x7effc:0x7f000] = bytes.fromhex('00001006')
    a7 = [0] * 7 + [0x7f000]
    recs = [rec(0x1000, 7, ranges={0: bytes(ram)}, a=a7), rec(0x1006, 7, ranges={0: bytes(after)}, a=a7),
            rec(0x1000, 8, ranges={0: bytes(ram)}, a=a7), rec(0x1006, 8, ranges={0: bytes(wrong)}, a=a7)]   # the second pair: a wrong "after"
    res = verify.calls(recs, str(drv), bytes(img), 0)
    r1, r2 = res[0x1100]
    assert r1['chip_diff'] == 0 and r1['regs_equal'] and r2['chip_diff'] == 2 and r2['first'] == ['$4000', '$4001']
    assert '1 of 2 calls equal' in verify.format_calls(res)
    write_trace(tmp_path / 'v.vtr', recs)
    (tmp_path / 'img.bin').write_bytes(img)
    assert cli.main(['verify', 'calls', str(tmp_path / 'v.vtr'), str(drv), str(tmp_path / 'img.bin'), '--json', str(tmp_path / 'v.json')]) == 0
    assert '1100' in json.load(open(tmp_path / 'v.json'))
