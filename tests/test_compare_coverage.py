"""1.0.39: a comparison says "equal" only when it compared what it was asked to. Every case here is one where the old
code reported a pass (or 100 %) although one side was short, empty, elsewhere, or the bytes were never looked at -
the audit of 2026-11-10 (the measuring side). Synthetic data only."""
import os
import struct
import sys

import pytest

from arek import cli, contract, copper, parity
from arek.headless import shot, trace, tracetools
from arek.packers import bytekiller, scan


def rec(hit, ranges, hashes=None, frame=None, pc=0x1000):
    return {'kind': 'VTR2', 'addr': pc, 'hit': hit, 'frame': hit + 100 if frame is None else frame, 'v': 0, 'h': 0,
            'sr': 0x2000, 'd': [0] * 8, 'a': [0] * 8, 'pc': pc, 'ranges': dict(ranges), 'hashes': hashes or {}}


def same(n, base=0xc00000):
    return [rec(k, {base: bytes([k & 255]) * 16}) for k in range(n)]


# ------------------------------------------------------------------ records
def test_a_rebuild_that_ends_early_is_not_complete():
    r = parity.compare(same(50), same(10))
    assert r['pairs'] == 10 and r['equal'] == 10 and r['short'] == 40 and not r['complete']
    assert r['original'] == 50 and r['rebuild'] == 10
    assert 'NOT COMPLETE' in parity.format_compare(r)
    r = parity.compare(same(10), same(50))                       # the rebuild ran longer: said, not a failure
    assert r['complete'] and r['extra'] == 40


def test_an_empty_side_is_nothing_compared():
    r = parity.compare(same(10), [])
    assert r['pairs'] == 0 and not r['complete'] and 'NOTHING COMPARED' in parity.format_compare(r)
    assert not parity.compare([], [])['complete']


def test_ranges_the_rebuild_did_not_capture_are_differences():
    a = [rec(0, {0x1000: b'\x01\x02\x03\x04'})]
    for other in ({0x2000: b'\x01\x02\x03\x04'}, {}, {0x1000: b'\x01\x02'}):
        r = parity.compare(a, [rec(0, other)])
        assert r['equal'] == 0 and not r['complete'], other
    d = parity.diff_records(a[0], rec(0, {0x1000: b'\x01\x02'}))
    assert d == [(('missing', 0x1002), 2, 0)]
    assert 'did not capture' in parity.format_compare(parity.compare(a, [rec(0, {})]))


def test_hashes_need_a_partner_of_the_same_length():
    a = [rec(0, {}, hashes={0x5000: (16, 123)})]
    assert not parity.compare(a, [rec(0, {})])['complete']                              # the rebuild has no hash
    assert not parity.compare(a, [rec(0, {}, hashes={0x5000: (8, 123)})])['complete']   # over another length
    assert parity.compare(a, [rec(0, {}, hashes={0x5000: (16, 123)})])['complete']


def test_odd_bytes_are_compared():
    def one(ra, rb, **kw):
        return parity.diff_records(rec(0, {0x1000: ra}), rec(0, {0x1000: rb}), **kw)
    assert one(b'\x01', b'\x02') == [(0x1000, 1, 2)]                                    # a one-byte range
    assert one(b'\x00\x00\x01', b'\x00\x00\x02') == [(0x1002, 1, 2)]                    # the odd last byte
    assert one(b'\x00\x01\x00', b'\x00\x02\x00', ranges=[(0x1001, 1)]) == [(0x1001, 1, 2)]   # --range ADDR:1 at an odd address
    assert one(b'\x09\x00', b'\x08\x00', ignore=[(0x1001, 1)]) == [(0x1000, 9, 8)]       # ignoring the odd byte keeps the even one
    assert one(b'\x12\x34\x56\x78', b'\x12\x34\x56\x79') == [(0x1002, 0x5678, 0x5679)]   # words stay words


def test_a_range_nobody_captured_is_not_a_pass():
    a, b = same(5), same(5)
    r = parity.compare(a, b, ranges=[(0xd00000, 4)])
    assert not r['complete'] and r['first']['diffs'][0][0] == ('uncaptured', 0xd00000)
    r = parity.compare([rec(k, {}) for k in range(5)], [rec(k, {}) for k in range(5)])   # records without any RAM
    assert r['empty'] and not r['complete'] and 'NOTHING COMPARED' in parity.format_compare(r)
    assert parity.compare([rec(0, {})], [rec(0, {})], regs=True)['complete']             # the registers are something


def write_trace(path, recs):
    with open(path, 'wb') as f:
        for r in recs:
            f.write(trace.encode(r))


def test_trace_compare_fail_and_exit_status(tmp_path, capsys):
    o, short, empty = (str(tmp_path / n) for n in ('o.vtr', 'short.vtr', 'empty.vtr'))
    write_trace(o, same(20))
    write_trace(short, same(5))
    write_trace(empty, [])
    assert cli.main(['trace', 'compare', o, o, '--fail']) == 0
    assert cli.main(['trace', 'compare', o, short, '--fail']) == 1          # passed before: 5 of 5 pairs equal
    assert cli.main(['trace', 'compare', o, empty, '--fail']) == 1          # passed before: 0 pairs, no first difference
    assert cli.main(['trace', 'compare', o, empty]) == 1                    # nothing compared is never exit 0
    assert cli.main(['trace', 'compare', o, short]) == 0                    # a report without --fail
    assert 'NOT COMPLETE' in capsys.readouterr().out


# ------------------------------------------------------------------ pictures
def shots(prefix, frames, pixel=(1, 2, 3), size=716 * 4):
    for f in frames:
        with open('%s_%06d.raw' % (prefix, f), 'wb') as fh:
            fh.write(bytes(pixel) * size)


def test_pictures_the_rebuild_lacks_are_not_equal(tmp_path):
    o, r = str(tmp_path / 'o'), str(tmp_path / 'r')
    shots(o, range(10))
    shots(r, [3])
    res = parity.compare_shots(o, r)
    assert res['pairs'] == 1 and res['equal'] == 1 and len(res['missing']) == 9 and not res['complete']
    assert 'NOT COMPLETE' in parity.format_shots(res)
    assert cli.main(['shots', o, r]) == 1                                    # was exit 0: "1 of 1 pairs equal"
    assert not parity.compare_shots(o, str(tmp_path / 'none'))['complete']


def test_an_empty_picture_is_an_error(tmp_path):
    o, r = str(tmp_path / 'o'), str(tmp_path / 'r')
    for p in (o, r):
        open(p + '_000001.raw', 'wb').close()
    with pytest.raises(ValueError):
        parity.compare_shots(o, r)                                           # was "1 of 1 pairs equal, 0 of 0 pixels"


def test_an_alignment_shift_is_reported(tmp_path):
    w, h = 716, 24
    a = bytearray(w * h * 3)
    for y in range(8, 16):
        for x in range(100, 140):
            a[(y * w + x) * 3] = 200
    b = bytearray(w * h * 3)
    for y in range(8, 16):
        for x in range(104, 144):                                            # the same block 4 pixels to the right
            b[(y * w + x) * 3] = 200
    o, r = str(tmp_path / 'o'), str(tmp_path / 'r')
    open(o + '_000001.raw', 'wb').write(a)
    open(r + '_000001.raw', 'wb').write(b)
    res = parity.compare_shots(o, r, align=8)
    assert res['equal'] == 1 and res['aligned'] == 1
    text = parity.format_shots(res)
    assert 'shifted before comparing' in text and 'shift (4, 0)' in text     # was silent without --all


# ------------------------------------------------------------------ sound
def reglog(path, writes):
    with open(path, 'wb') as f:
        f.write(trace.encode_reglog(writes))


def test_writes_only_the_rebuild_makes_cannot_be_shifted_away(tmp_path):
    o, r = str(tmp_path / 'o.reg'), str(tmp_path / 'r.reg')
    reglog(o, [])
    reglog(r, [(100, 0x0a6, 1), (150, 0x0a6, 2), (260, 0x0a6, 3)])
    res = parity.compare_audio(o, r)
    assert res['frames'] == 3 and res['equal'] == 0                         # was 3 of 3 equal at shift -1
    reglog(o, [(f, 0x0a6, f) for f in range(10)])
    reglog(r, [(f + 5, 0x0a6, f) for f in range(10)])
    res = parity.compare_audio(o, r)
    assert (res['shift'], res['frames'], res['equal']) == (5, 10, 10)


# ------------------------------------------------------------------ suite
def test_the_suite_names_what_it_could_not_compare(tmp_path, capsys):
    write_trace(tmp_path / 'o.vtr', same(20))
    write_trace(tmp_path / 'short.vtr', same(5))
    write_trace(tmp_path / 'ok.vtr', same(20))
    cfg = {'scenarios': [
        {'name': 'short', 'original': {'trace': 'o.vtr'}, 'rebuild': {'trace': 'short.vtr'}},
        {'name': 'gone', 'original': {'trace': 'o.vtr'}, 'rebuild': {'trace': 'nowhere.vtr'}},
        {'name': 'ok', 'original': {'trace': 'o.vtr'}, 'rebuild': {'trace': 'ok.vtr'}}]}
    rows = parity.suite(cfg, base=str(tmp_path))
    assert [bool(r['problems']) for r in rows] == [True, True, False] and rows[2]['complete']
    text = parity.format_suite(rows)
    assert '5/20 (25.0%)' in text                                           # was 5/5 (100.0%)
    assert 'PROBLEM short' in text and 'PROBLEM gone' in text and 'nowhere.vtr' in text
    assert not parity.suite_ok(rows) and parity.suite_ok(rows[2:]) and parity.suite_ok(rows[2:], strict=True)
    import json
    (tmp_path / 's.json').write_text(json.dumps(cfg))
    assert cli.main(['parity', str(tmp_path / 's.json'), '--base', str(tmp_path)]) == 1
    cfg['scenarios'] = cfg['scenarios'][2:]
    (tmp_path / 's.json').write_text(json.dumps(cfg))
    assert cli.main(['parity', str(tmp_path / 's.json'), '--base', str(tmp_path), '--fail']) == 0


# ------------------------------------------------------------------ the other comparisons
def test_pair_diff_says_what_the_host_record_lacks():
    a = [rec(0, {0x1000: b'\x01\x02\x03\x04'}, hashes={0x2000: (4, 1)}, frame=1)]
    b = [rec(0, {0x3000: b'\x09'}, hashes={0x2000: (4, 2)}, frame=1)]
    row = tracetools.pair_diff(a, b)[0]
    assert row['missing'] == [(0x1000, 4)] and row['hashes'] == [0x2000]
    assert 'EQUAL' not in tracetools.format_pair_diff([row])                # printed EQUAL before
    row = tracetools.pair_diff(a, [rec(0, {0x1000: b'\x01'}, hashes={0x2000: (4, 1)}, frame=1)])[0]
    assert row['missing'] == [(0x1001, 3)]
    rows = tracetools.pair_diff(same(5), same(5), limit=2)
    assert rows[-1] == {'more': True} and 'limit' in tracetools.format_pair_diff(rows)
    assert 'EQUAL' in tracetools.format_pair_diff(tracetools.pair_diff(a, a))


def test_pc_compare_notices_a_host_log_that_stops():
    orig = [{'frame': 1, 'pc': 0x100 + 2 * k, 'v': 0, 'h': k} for k in range(50)]
    r = tracetools.pc_compare(orig, [(1, 0x100 + 2 * k, 0, k) for k in range(20)])
    assert r['short'] == 20 and 'NOT COMPLETE' in tracetools.format_pc_compare(r)
    assert tracetools.pc_compare(orig, [])['short'] == 0
    assert tracetools.pc_compare(orig, [(1, 0x100 + 2 * k, 0, k) for k in range(50)])['short'] is None


def test_contract_compare_refuses_a_range_outside_the_memory():
    a = bytes(0x1000)
    with pytest.raises(ValueError):
        contract.compare(a, a, ranges=[(0xc00000, 0xc01000)])               # was "OK - no differences"
    with pytest.raises(ValueError):
        contract.compare(a, a, ranges=[(0x800, 0x1800)])
    assert contract.compare(a, a, ranges=[(0x800, 0x1000)]) == []


# ------------------------------------------------------------------ the emulator runner
def fake_vahl(tmp_path, body):
    p = tmp_path / 'vahl.sh'
    # the names are what trace.require_patch looks for in the binary
    p.write_text('#!/bin/sh\n# VAHL_TRACE VAHL_REGLOG VAHL_SHOTS VAHL_SHOTS_FRAMES\n' + body + '\n')
    p.chmod(0o755)
    return str(p)


@pytest.mark.skipif(sys.platform == 'win32', reason='a shell script stands in for the emulator')
def test_a_failed_emulator_run_is_an_error_and_keeps_its_log(tmp_path):
    conf = {'VAHL': fake_vahl(tmp_path, 'echo boom; exit 3')}
    log = str(tmp_path / 'run.log')
    with pytest.raises(shot.HeadlessError) as e:
        shot.run_script(conf, 'x\n', capture=True, log_path=log)
    assert 'status 3' in str(e.value) and 'boom' in str(e.value) and 'boom' in open(log).read()
    conf = {'VAHL': fake_vahl(tmp_path, 'echo slow; sleep 5')}
    with pytest.raises(shot.HeadlessError):
        shot.run_script(conf, 'x\n', capture=True, log_path=log, timeout=1)
    assert os.path.exists(log)                                               # the log of a timed-out run was thrown away


def test_the_run_does_not_inherit_vahl_variables(monkeypatch):
    monkeypatch.setenv('VAHL_INPUTS', '/stale/inputs.txt')
    monkeypatch.setenv('VAHL_TRACE', '/stale/trace')
    e = shot.run_env({'VAHL_REGLOG': '/new'})
    assert 'VAHL_INPUTS' not in e and 'VAHL_TRACE' not in e and e['VAHL_REGLOG'] == '/new' and 'PATH' in e


@pytest.mark.skipif(sys.platform == 'win32', reason='a shell script stands in for the emulator')
def test_capture_drops_the_files_of_an_earlier_run_and_wants_every_picture(tmp_path):
    adf, rom = tmp_path / 'g.adf', tmp_path / 'k.rom'
    adf.write_bytes(bytes(901120))
    rom.write_bytes(b'x')
    out, reg, pre = str(tmp_path / 'r.vtr'), str(tmp_path / 'r.reg'), str(tmp_path / 'f')
    open(reg, 'wb').write(bytes(16))                                         # an earlier run's log
    open(pre + '_000100.raw', 'wb').write(bytes(716 * 285 * 3))              # and its picture
    conf = {'ROM': str(rom), 'ADF1': str(adf), 'VAHL': fake_vahl(tmp_path, 'exit 0')}   # an emulator that writes nothing
    with pytest.raises(trace.TraceError) as e:
        trace.capture(conf, out, [], 1, 2, reglog=reg, shots=pre, shot_frames=(500, 501))
    assert 'not written' in str(e.value)
    assert not os.path.exists(reg) and not os.path.exists(pre + '_000100.raw')   # both were returned as this run's
    conf['VAHL'] = fake_vahl(tmp_path, 'exit 3')
    with pytest.raises(shot.HeadlessError):                                  # the exit status was ignored: 0 records, no error
        trace.capture(conf, out, [], 1, 2, reglog=reg)
    with pytest.raises(Exception) as e:                                      # a conf without the ROM: KeyError before
        trace.capture({'ADF1': str(adf), 'VAHL': conf['VAHL']}, out, [], 1, 2, reglog=reg)
    assert 'ROM' in str(e.value) and not isinstance(e.value, KeyError)


# ------------------------------------------------------------------ small false results
def test_bytekiller_refuses_a_packed_length_past_the_data():
    for fn in (bytekiller.unpack_b, bytekiller.unpack_a):
        with pytest.raises(ValueError):                                      # unpack_b: 1000 zero bytes, checksum "ok"
            fn(struct.pack('>II', 1000, 0x100000) + bytes(16))
    assert bytekiller.detect(struct.pack('>II', 1000, 0x100000) + bytes(16)) is None


def test_scan_survives_a_magic_at_the_end():
    rep = scan.scan(bytes(96) + b'ATN!' + bytes(4))                          # TypeError before
    assert scan.format_report(rep)


def test_regname_of_every_register():
    for r in range(0, 0x200, 2):
        assert copper.regname(r)                                             # $0AC raised IndexError
    assert copper.regname(0x0ac) == '$0AC' and copper.regname(0x0a8) == 'AUD0VOL'


# ------------------------------------------------------------------ 1.0.44 (Turrican II KIT-GAPS 31, 32)
def test_a_hashed_range_is_checked_against_a_full_capture():
    """The original hashed two ranges, the rebuild captured the whole RAM as bytes: the hash is taken from the rebuild's
    bytes wherever its range starts. Before 1.0.39 the pair was skipped (100 %), 1.0.39-1.0.43 called it missing."""
    ram = bytes((i * 7) & 255 for i in range(0x400))
    h = {0x100: (0x80, trace.fnv1a64(ram[0x100:0x180])), 0x200: (0x100, trace.fnv1a64(ram[0x200:0x300]))}
    a = [rec(0, {}, h)]
    assert parity.diff_records(a[0], rec(0, {0: ram})) == []
    r = parity.compare(a, [rec(0, {0: ram})])
    assert r['complete'] and r['hashes'] == 2
    bad = bytearray(ram); bad[0x250] ^= 1
    d = parity.diff_records(a[0], rec(0, {0: bytes(bad)}))
    assert [x[0] for x in d] == [('hash', 0x200)]
    assert parity.diff_records(a[0], rec(0, {0: ram[:0x280]})) == [(('missing hash', 0x200), 0x100, 0)]   # not wholly captured: not checked


def test_a_few_different_bytes_in_a_large_record_are_found_fast():
    """512 KB records that differ in a handful of bytes took minutes each (every word in Python); found by blocks now,
    with the same answer - odd starts, block borders and the last odd byte included."""
    import time
    a = bytearray(os.urandom(0x80000 + 1))
    b = bytearray(a)
    for at in (1, 0xfff, 0x1000, 0x2345, 0x7ffff, 0x80000):
        b[at] ^= 0x55
    ra, rb = rec(0, {1: bytes(a[1:])}), rec(0, {1: bytes(b[1:])})
    t = time.time()
    for _ in range(20):
        d = parity.diff_records(ra, rb)
    assert time.time() - t < 5
    assert [x[0] for x in d] == [1, 0xffe, 0x1000, 0x2344, 0x7fffe, 0x80000]
    assert d[0][1:] == (a[1], b[1]) and d[1][1:] == (int.from_bytes(a[0xffe:0x1000], 'big'), int.from_bytes(b[0xffe:0x1000], 'big'))


def test_sound_after_the_end_of_the_rebuilds_log_is_named(tmp_path):
    """1.0.44 (Alien Breed II G61): the rebuild's run ended with the level, the original went on writing to Paula - those
    frames were counted as unequal without a word, while a short trace is a PROBLEM."""
    o, r = str(tmp_path / 'o.reg'), str(tmp_path / 'r.reg')
    reglog(o, [(f, 0x0a6, f) for f in range(100)])
    reglog(r, [(f, 0x0a6, f) for f in range(78)] + [(79, 0x09a, 0x8020)])   # the last logged write of any register: frame 79
    res = parity.compare_audio(o, r)
    assert res['shift'] == 0 and res['equal'] == 78 and res['short'] == 20
    reglog(r, [(f, 0x0a6, f) for f in range(78)] + [(120, 0x09a, 0x8020)])  # the log goes on: the rebuild ran, and was silent
    assert parity.compare_audio(o, r)['short'] == 0
    reglog(r, [(f, 0x0a6, f) for f in range(100)])
    assert parity.compare_audio(o, r)['short'] == 0
    cfg = {'scenarios': [{'name': 's', 'original': {'reglog': o}, 'rebuild': {'reglog': r}}]}
    reglog(r, [(f, 0x0a6, f) for f in range(78)])
    rows = parity.suite(cfg, base=str(tmp_path), run=False)
    assert any('ends 22 frames' in p for p in rows[0]['problems']) and not parity.suite_ok(rows)
