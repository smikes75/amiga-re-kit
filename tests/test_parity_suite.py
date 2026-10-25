"""arek.parity.suite: scenarios of state, picture and sound against the original."""
import json
import struct

from arek import cli, parity
from arek.headless import trace


def rec(hit, ram, base=0xc00000):
    return {'kind': 'VTR2', 'addr': 0x1000, 'hit': hit, 'frame': hit + 100, 'v': 0, 'h': 0, 'sr': 0x2000,
            'd': [0] * 8, 'a': [0] * 8, 'pc': 0x1000, 'ranges': {base: bytes(ram)}, 'hashes': {}}


def write_trace(path, rams):
    path.write_bytes(b''.join(trace.encode(rec(k, r)) for k, r in enumerate(rams)))


def ramp(n, at=None, value=0):
    out = []
    for k in range(n):
        r = bytearray(64)
        r[0:2] = k.to_bytes(2, 'big')
        if at is not None and k >= at:
            r[10:12] = value.to_bytes(2, 'big')
        out.append(r)
    return out


def write_shots(prefix, frames, pixel=(10, 20, 30), odd=None):
    for f in frames:
        px = list(pixel)
        if odd and f in odd:
            px = [min(255, c + odd[f]) for c in px]
        (prefix.parent / ('%s_%d.raw' % (prefix.name, f))).write_bytes(bytes(px) * 6)      # 3 x 2 pixels


def write_reglog(path, writes):
    """writes: [(frame, reg, value)] by the CPU."""
    path.write_bytes(b''.join(struct.pack('<4I', f, 0, (reg << 16) | v, 0x1000) for f, reg, v in writes))


def test_suite_state_picture_sound(tmp_path):
    write_trace(tmp_path / 'o.vtr', ramp(20))
    write_trace(tmp_path / 'r.vtr', ramp(20, at=12, value=7))                 # the rebuild leaves at tick 12
    write_trace(tmp_path / 'r2.vtr', ramp(20)[1:] + [ramp(21)[20]])          # one tick ahead
    write_shots(tmp_path / 'os', range(0, 20, 5))
    write_shots(tmp_path / 'rs', range(0, 20, 5), odd={10: 5, 15: 40})       # a small and a big difference
    aud = [(f, 0x0a6, f * 2) for f in range(10)] + [(f, 0x096, 0x8001) for f in range(10)]
    write_reglog(tmp_path / 'o.reg', aud)
    write_reglog(tmp_path / 'r.reg', [(f + 14, reg, v) for f, reg, v in aud][:-2] + [(23, 0x096, 0x8002)])   # 14 frames late, last frame wrong
    cfg = {'scenarios': [
        {'name': 'leaves', 'original': {'trace': 'o.vtr', 'shots': 'os', 'reglog': 'o.reg'},
         'rebuild': {'trace': 'r.vtr', 'shots': 'rs', 'reglog': 'r.reg'}, 'tolerance': 8, 'audio_shifts': 20},
        {'name': 'ahead', 'original': {'trace': 'o.vtr'}, 'rebuild': {'trace': 'r2.vtr'}, 'shifts': 2},
        {'name': 'none', 'original': {}, 'rebuild': {}},
    ]}
    rows = parity.suite(cfg, base=str(tmp_path))
    st = rows[0]['state']
    assert st['pairs'] == 20 and st['equal'] == 12 and st['first'] == 12 and st['best_shift'] == 0
    pic = rows[0]['picture']
    assert pic['pairs'] == 4 and pic['equal'] == 3 and pic['worst'] == (15, 6) and pic['differing'] == 6
    snd = rows[0]['sound']
    assert snd['shift'] == 14 and snd['frames'] == 20 and snd['equal'] == 18 and snd['first'] == 8   # DMACON missing at 8, wrong at 9
    assert rows[1]['state']['best_shift'] == -1 and rows[1]['state']['equal_shifted'] == 19 and rows[1]['picture'] is None
    assert rows[2] == {'name': 'none', 'state': None, 'picture': None, 'sound': None}
    text = parity.format_suite(rows)
    assert '12/20 (60.0%)' in text and '3/4' in text and 's+14' in text and 'none' in text


def test_make_runs_once_and_cli(tmp_path, capsys):
    write_trace(tmp_path / 'src.vtr', ramp(5))
    write_trace(tmp_path / 'r.vtr', ramp(5))
    cfg = {'scenarios': [{'name': 'made', 'original': {'trace': 'o.vtr', 'make': 'cp src.vtr o.vtr'},
                          'rebuild': {'trace': 'r.vtr'}}]}
    (tmp_path / 'suite.json').write_text(json.dumps(cfg))
    rows = parity.suite(cfg, base=str(tmp_path), run=False)
    assert rows[0]['state'] is None                                   # not made, not compared
    assert cli.main(['parity', str(tmp_path / 'suite.json'), '--base', str(tmp_path)]) == 0
    assert '5/5 (100.0%)' in capsys.readouterr().out and (tmp_path / 'o.vtr').exists()
    assert cli.main(['parity', str(tmp_path / 'suite.json'), '--base', str(tmp_path), '--json']) == 0
    assert json.loads(capsys.readouterr().out)[0]['state']['equal'] == 5


def test_first_difference_carries_frame_and_hit_and_reglog_round_trip(tmp_path):
    write_trace(tmp_path / 'o.vtr', ramp(6))
    write_trace(tmp_path / 'r.vtr', ramp(6, at=4, value=1))
    rows = parity.suite({'scenarios': [{'name': 's', 'original': {'trace': 'o.vtr'}, 'rebuild': {'trace': 'r.vtr'}}]}, base=str(tmp_path))
    st = rows[0]['state']
    assert (st['first'], st['first_frame'], st['first_hit']) == (4, 104, 4)
    assert '4/f104' in parity.format_suite(rows)
    rows_in = [{'frame': 3, 'v': 10, 'h': 20, 'reg': 0x0a6, 'value': 0x1234, 'pc': 0x1000, 'agnus': False}, (5, 0x096, 0x8001), (7, 1, 2, 0x0b6, 9)]
    data = trace.encode_reglog(rows_in)
    back = trace.read_reglog(data)
    assert [(r['frame'], r['v'], r['h'], r['reg'], r['value'], r['pc'], r['agnus']) for r in back] == \
        [(3, 10, 20, 0x0a6, 0x1234, 0x1000, False), (5, 0, 0, 0x096, 0x8001, 0, False), (7, 1, 2, 0x0b6, 9, 0, False)]
