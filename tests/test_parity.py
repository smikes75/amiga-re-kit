"""Long parity (arek.parity) and packed traces (trace.pack / encode)."""
import json

import pytest

from arek import cli, parity
from arek.headless import trace


def rec(hit, ram, base=0xc00000, frame=None, d0=0, hashes=None):
    return {'kind': 'VTR2', 'addr': 0x1000, 'hit': hit, 'frame': hit + 100 if frame is None else frame,
            'v': 0, 'h': 0, 'sr': 0x2000, 'd': [d0] + [0] * 7, 'a': [0] * 8, 'pc': 0x1000,
            'ranges': {base: bytes(ram)}, 'hashes': hashes or {}}


def trace_of(rams, **kw):
    return [rec(k, r, **kw) for k, r in enumerate(rams)]


def ramp(n, at=None, value=0):
    out = []
    for k in range(n):
        r = bytearray(64)
        r[0:2] = k.to_bytes(2, 'big')                 # a frame counter
        if at is not None and k >= at:
            r[10:12] = value.to_bytes(2, 'big')
        out.append(r)
    return out


def test_equal_traces():
    a = trace_of(ramp(10))
    r = parity.compare(a, trace_of(ramp(10)))
    assert r['pairs'] == 10 and r['equal'] == 10 and r['first'] is None


def test_first_difference_and_addresses():
    a, b = trace_of(ramp(10)), trace_of(ramp(10, at=4, value=0x1234))
    r = parity.compare(a, b)
    assert r['equal'] == 4 and r['first']['index'] == 4
    assert r['first']['diffs'] == [(0xc0000a, 0, 0x1234)]
    assert r['addresses'] == [(0xc0000a, 6)] and r['differing'][0] == (4, 1)
    assert parity.compare(a, b, ignore=[(0xc0000a, 2)])['first'] is None
    assert parity.compare(a, b, ranges=[(0xc00000, 4)])['first'] is None
    assert 'first difference: record 4' in parity.format_compare(r)


def test_phase_shift_is_found():
    a = trace_of(ramp(12))
    b = trace_of(ramp(12)[1:] + [bytearray(64)])          # the rebuild one record ahead
    assert parity.compare(a, b)['equal'] == 0
    assert parity.best_shift(a, b, range(-2, 3))[0][:2] == (-1, 11)


def test_registers_and_hashes():
    a, b = [rec(0, bytes(8), d0=1)], [rec(0, bytes(8), d0=2)]
    assert parity.compare(a, b)['first'] is None
    assert parity.compare(a, b, regs=True)['first']['diffs'] == [('d0', 1, 2)]
    data = bytes(range(16))
    ha = [rec(0, b'', hashes={0x50000: (16, trace.fnv1a64(data))})]
    hb = [{**rec(0, b''), 'ranges': {0x50000: data}}]           # the rebuild captured the bytes
    assert parity.compare(ha, hb)['first'] is None
    hb[0]['ranges'][0x50000] = bytes(16)
    assert parity.compare(ha, hb)['first']['diffs'][0][0] == ('hash', 0x50000)


def test_encode_pack_round_trip(tmp_path):
    rams = ramp(50, at=20, value=7)
    src = tmp_path / 'a.vtr'
    src.write_bytes(b''.join(trace.encode(r) for r in trace_of(rams)) +
                    trace.encode({**rec(50, bytes(8)), 'kind': 'VTW2', 'pc': 0x4242}))
    n, before, after = trace.pack(str(src), str(tmp_path / 'a.vtp'))
    assert n == 51 and after < before
    back = list(trace.records(str(tmp_path / 'a.vtp')))
    assert [r['ranges'] for r in back] == [r['ranges'] for r in trace.records(str(src))]
    assert back[-1]['kind'] == 'VTW2' and back[-1]['pc'] == 0x4242


def test_cli_compare_and_pack(tmp_path, capsys):
    a, b = tmp_path / 'o.vtr', tmp_path / 'n.vtr'
    a.write_bytes(b''.join(trace.encode(r) for r in trace_of(ramp(8))))
    b.write_bytes(b''.join(trace.encode(r) for r in trace_of(ramp(8, at=5, value=9))))
    assert cli.main(['trace', 'compare', str(a), str(b)]) == 0
    assert 'first difference: record 5' in capsys.readouterr().out
    assert cli.main(['trace', 'compare', str(a), str(b), '--fail']) == 1
    capsys.readouterr()
    assert cli.main(['trace', 'compare', str(a), str(b), '--ignore', 'c0000a:2', '--json']) == 0
    assert json.loads(capsys.readouterr().out)['equal'] == 8
    assert cli.main(['trace', 'compare', str(a), str(b), '--best-shift', '1']) == 0
    assert 'shift +0: 5 of 8 pairs equal' in capsys.readouterr().out
    assert cli.main(['trace', 'pack', str(a), str(tmp_path / 'o.vtp')]) == 0
    assert '8 records' in capsys.readouterr().out
    assert cli.main(['trace', 'compare', str(tmp_path / 'o.vtp'), str(a)]) == 0
    assert '8 of 8 record pairs equal' in capsys.readouterr().out


def test_mcp_trace_compare(tmp_path):
    pytest.importorskip('mcp')
    from arek import mcp_server
    a, b = tmp_path / 'o.vtr', tmp_path / 'n.vtr'
    a.write_bytes(b''.join(trace.encode(r) for r in trace_of(ramp(6))))
    b.write_bytes(b''.join(trace.encode(r) for r in trace_of(ramp(6, at=2, value=1))))
    r = mcp_server.trace_compare(str(a), str(b))
    assert r['equal'] == 2 and r['first']['index'] == 2
    assert mcp_server.trace_compare(str(a), str(b), best_shift=1)['shifts'][0]['shift'] == 0
