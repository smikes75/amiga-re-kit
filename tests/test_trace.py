import struct

import pytest

from arek.headless import trace


def _head(magic, addr, hit, n, frame=100, v=44, h=8, sr=0x2000):
    d = list(range(1, 9))
    a = [0x100 * i for i in range(8)]
    return struct.pack('<24I', magic, addr, hit, frame, v, h, sr, *d, *a, n)


def _vtr1(addr, hit, ram):
    return _head(trace.VTR1, addr, hit, len(ram)) + ram


def _vtr2(addr, hit, ranges, magic=trace.VTR2, pc=None):
    out = _head(magic, addr, hit, len(ranges))
    if pc is not None:
        out += struct.pack('<I', pc)
    for start, data in ranges:
        out += struct.pack('<II', start, len(data)) + data
    return out


def test_records_all_three_kinds():
    ram = bytearray(64)
    ram[0x10:0x12] = b'\xbe\xef'
    slow = b'\x00\x01\x02\x03'
    blob = (_vtr1(0x1234, 0, bytes(ram))
            + _vtr2(0x2000, 1, [(0xc00000, slow), (0xdff00a, b'\x12\x34')])
            + _vtr2(0xc00002, 2, [(0xc00000, slow)], magic=trace.VTW2, pc=0x4abc))
    recs = list(trace.records(blob))
    assert [r['kind'] for r in recs] == ['VTR1', 'VTR2', 'VTW2']
    assert recs[0]['d'] == list(range(1, 9)) and recs[0]['a'][7] == 0x700 and recs[0]['sr'] == 0x2000
    assert trace.read(recs[0], 0x10, 'H') == 0xbeef
    assert trace.read(recs[1], 0xc00001, 'B') == 1 and trace.read(recs[1], 0xdff00a, 'H') == 0x1234
    assert trace.read(recs[1], 0x10, 'H') is None                  # not captured
    assert trace.read(recs[1], 0xc00003, 'H') is None              # crosses the range end
    assert recs[2]['pc'] == 0x4abc and recs[2]['addr'] == 0xc00002
    assert recs[1]['pc'] == 0x2000                                  # breakpoint: pc = address


def test_records_reject_bad_input(tmp_path):
    good = _vtr2(0x10, 0, [(0, b'abcd')])
    with pytest.raises(trace.TraceError):
        list(trace.records(good[:-1]))                              # truncated range data
    with pytest.raises(trace.TraceError):
        list(trace.records(b'XXXX' + good[4:]))                      # unknown magic
    with pytest.raises(trace.TraceError):
        list(trace.records(good[:50]))                               # truncated header
    f = tmp_path / 't.vtr'
    f.write_bytes(good * 3)
    assert [r['hit'] for r in trace.records(str(f))] == [0, 0, 0]


def test_summary_env_and_arm_events():
    blob = _vtr2(0x2000, 7, [(0xc00000, b'\x00\x05\xff\xfe')])
    rows = trace.summary(blob, {'x': (0xc00000, 'H'), 'y': (0xc00002, 'h')})
    assert rows[0]['x'] == 5 and rows[0]['y'] == -2 and rows[0]['ranges'] == {'c00000': 4}
    assert '1 records' in trace.format_summary(rows, ['x'])
    e = trace.env('/tmp/x.vtr', [(0, 0x80000), (0xc00000, 0x80000)], 1024)
    assert e == {'VAHL_TRACE': '/tmp/x.vtr', 'VAHL_TRACE_RANGES': '0:80000,c00000:80000', 'VAHL_TRACE_LEN': '1024'}
    ev = trace.arm_events(196, [0xc01106], [0xc0599e])
    assert ev == [(196, 'debugger'), (196, 'break at $c01106 0'), (196, 'watch at $c0599e 0'), (196, 'commander')]


def test_capture_builds_script_and_reads_back(tmp_path, monkeypatch):
    from arek.headless import shot
    adf, rom = tmp_path / 'g.adf', tmp_path / 'k.rom'
    adf.write_bytes(bytes(901120))
    rom.write_bytes(b'x')
    conf = {'ROM': str(rom), 'ADF1': str(adf), 'VAHL': '/bin/true', 'MACHINE': 'A500_OCS_1MB'}
    out = str(tmp_path / 'run.vtr')
    seen = {}

    def fake_run(conf, script, capture=False, env=None, timeout=0):
        seen['script'], seen['env'] = script, env
        with open(env['VAHL_TRACE'], 'wb') as f:
            f.write(_vtr2(0x100, 0, [(0, b'ab')]) + _vtr2(0x100, 1, [(0, b'cd')]))
        return 'log'

    monkeypatch.setattr(shot, 'run_script', fake_run)
    n = trace.capture(conf, out, [(14, 'mouse1 press left')], 20, 22, breaks=[0x100], ranges=[(0, 2)])
    assert n == 2
    s = seen['script']
    assert s.index('mouse1 press left') < s.index('break at $100 0') < s.index('commander')
    assert seen['env']['VAHL_TRACE_RANGES'] == '0:2'
    assert (tmp_path / 'run.vtr.retrosh').exists() and (tmp_path / 'run.vtr.log').read_text() == 'log'
    with pytest.raises(trace.TraceError):
        trace.capture(conf, out, [], 1, 2)                           # nothing to trace


def test_cli_and_mcp_trace(tmp_path, capsys):
    from arek import cli
    f = tmp_path / 't.vtr'
    f.write_bytes(_vtr2(0x2000, 0, [(0xc00000, b'\x00\x2a')]) + _vtr2(0x2000, 1, [(0xc00000, b'\x00\x2b')]))
    assert cli.main(['trace', 'show', str(f), '--field', 'v=0xc00000:H']) == 0
    out = capsys.readouterr().out
    assert '2 records' in out and 'v=42' in out and 'v=43' in out
    assert cli.main(['trace', 'run', str(tmp_path / 'x.vtr')]) == 1          # missing --arm/--end/--break
    pytest.importorskip('mcp')
    import asyncio
    from arek import mcp_server

    async def go():
        r = await mcp_server.mcp.call_tool('trace_records', {'path': str(f), 'fields': {'v': '0xc00000:H'}})
        txt = r.content[0].text if hasattr(r, 'content') else str(r)
        assert '"total": 2' in txt.replace("'", '"') or 'total' in txt
        r = await mcp_server.mcp.call_tool('kit_info', {})
        txt = r.content[0].text if hasattr(r, 'content') else str(r)
        assert 'decoder_sha256' in txt
    asyncio.run(go())


# --- vamiga-inputs-reglog-899da5d.patch: inputs per frame, hashed ranges, register and audio logs

def test_hashed_range_record():
    data = b'\x01\x02\x03\x04'
    blob = _head(trace.VTR2, 0x100, 3, 2) + struct.pack('<II', 0, 2) + b'ab' + \
        struct.pack('<IIQ', 0x50000, 4 | 0x80000000, trace.fnv1a64(data))
    rec = next(trace.records(blob))
    assert rec['ranges'] == {0: b'ab'} and rec['hashes'] == {0x50000: (4, trace.fnv1a64(data))}
    assert trace.summary(blob)[0]['hashes'] == {'50000': '%016x' % trace.fnv1a64(data)}
    assert trace.fnv1a64(b'') == 0xcbf29ce484222325


def test_range_spellings():
    assert trace.parse_range('50000:1000') == (0x50000, 0x1000, False)
    assert trace.parse_range('c00000:80000h') == (0xc00000, 0x80000, True)
    assert trace.ranges_arg([(0, 0x10), (0xc00000, 0x80000, True)]) == '0:10,c00000:80000h'


def test_input_file_check_and_env(tmp_path):
    good = tmp_path / 'in.txt'
    good.write_text('\nR\nRF\nUL\nS\n\n')
    assert trace.check_inputs(good) == 6
    bad = tmp_path / 'bad.txt'
    bad.write_text('R\nfire\n')
    with pytest.raises(trace.TraceError, match='line 2'):
        trace.check_inputs(bad)
    e = trace.env('/t.vtr', inputs=good, reglog='r.bin', audlog='a.bin', skip=5, from_frame=0)
    assert e['VAHL_INPUTS'] == str(good) and e['VAHL_TRACE_SKIP'] == '5' and e['VAHL_TRACE_FROM_FRAME'] == '0'
    assert e['VAHL_REGLOG'].endswith('r.bin') and e['VAHL_AUDLOG'].endswith('a.bin')
    with pytest.raises(trace.TraceError):
        trace.env('/t.vtr', inputs=bad)


def test_reglog_and_audlog(tmp_path, capsys):
    from arek import cli
    regs = struct.pack('<4I', 16, (189 << 16) | 33, (0x09a << 16) | 0x7fff, 0xfc0118) + \
        struct.pack('<4I', 17, (2 << 16) | 9, (0x0a8 << 16) | 64, 0x1000000 | 0x40010)
    r = trace.read_reglog(regs)
    assert r[0] == {'frame': 16, 'v': 189, 'h': 33, 'reg': 0x09a, 'name': 'INTENA', 'value': 0x7fff,
                    'pc': 0xfc0118, 'agnus': False}
    assert r[1]['name'] == 'AUD0VOL' and r[1]['agnus'] and r[1]['pc'] == 0x40010
    with pytest.raises(trace.TraceError):
        trace.read_reglog(regs[:-1])
    aud = struct.pack('<3I', 5, (10 << 16) | 3, (0xff80 << 16) | 2)
    assert trace.read_audlog(aud) == [(5, 10, 3, -128, 2)]
    (tmp_path / 'r.bin').write_bytes(regs)
    (tmp_path / 'a.bin').write_bytes(aud * 3)
    assert cli.main(['trace', 'regs', str(tmp_path / 'r.bin'), '--reg', 'AUD0VOL']) == 0
    out = capsys.readouterr().out
    assert 'AUD0VOL  0040' in out and 'INTENA' not in out and '(DMA)' in out
    assert cli.main(['trace', 'audio', str(tmp_path / 'a.bin')]) == 0
    assert 'channel 2: 3 samples, frames 5-5' in capsys.readouterr().out


def test_capture_passes_inputs_and_logs(tmp_path, monkeypatch):
    from arek.headless import shot
    seen = {}

    def fake_run(conf, script, capture=False, env=None, timeout=0):
        seen['env'] = env
        with open(env['VAHL_TRACE'], 'wb') as f:
            f.write(_vtr2(0x100, 0, [(0, b'ab')]))
        return ''

    monkeypatch.setattr(shot, 'run_script', fake_run)
    adf, rom, inp = tmp_path / 'g.adf', tmp_path / 'k.rom', tmp_path / 'in.txt'
    adf.write_bytes(bytes(901120))
    rom.write_bytes(b'x')
    inp.write_text('R\nF\n')
    conf = {'ROM': str(rom), 'ADF1': str(adf), 'VAHL': '/bin/true'}
    trace.capture(conf, str(tmp_path / 'r.vtr'), [], 1, 2, breaks=[0x100], inputs=str(inp),
                  reglog=str(tmp_path / 'regs.bin'), from_frame=3)
    assert seen['env']['VAHL_INPUTS'] == str(inp) and seen['env']['VAHL_TRACE_FROM_FRAME'] == '3'
    assert 'VAHL_AUDLOG' not in seen['env']


def test_selftest_disk_and_key_decoding():
    from arek import adf
    from arek.headless import selftest
    d = selftest.disk()
    assert len(d) == adf.SIZE and d[:4] == b'DOS\0'
    assert struct.unpack('>I', d[4:8])[0] == adf.bootblock_checksum(d[:1024])
    # boot code: lea pay(pc),a0 ... and the handler entry the trace breaks on
    assert d[12:14] == b'\x41\xfa' and selftest.HANDLER == 0x40028
    assert selftest.keys_of(0x0000, 0xff) == ''
    assert selftest.keys_of(0x0003, 0xff) == 'R'            # right: bit 1, bit 0 = bit 1 (no down)
    assert selftest.keys_of(0x0300, 0x7f) == 'LF'           # left: bit 9, bit 8 = bit 9 (no up)
    assert selftest.keys_of(0x0100, 0xff) == 'U' and selftest.keys_of(0x0001, 0xff) == 'D'


def test_a_build_without_the_patch_is_named(tmp_path):
    old = tmp_path / 'VAHeadless'
    old.write_bytes(b'\x00VAHL_TRACE\x00VAHL_TRACE_RANGES\x00')
    trace.require_patch(str(old), ['VAHL_TRACE', 'VAHL_TRACE_RANGES'])
    with pytest.raises(trace.TraceError, match='vamiga-inputs-reglog-899da5d.patch.*VAHL_INPUTS'):
        trace.require_patch(str(old), ['VAHL_TRACE', 'VAHL_INPUTS'])
    adf, rom, inp = tmp_path / 'g.adf', tmp_path / 'k.rom', tmp_path / 'in.txt'
    adf.write_bytes(bytes(901120))
    rom.write_bytes(b'x')
    inp.write_text('R\n')
    conf = {'ROM': str(rom), 'ADF1': str(adf), 'VAHL': str(old)}
    with pytest.raises(trace.TraceError, match='VAHL_INPUTS'):
        trace.capture(conf, str(tmp_path / 'r.vtr'), [], 1, 2, breaks=[0x100], inputs=str(inp))
    with pytest.raises(trace.TraceError, match='VAHL_TRACE_SKIP'):          # hashed range
        trace.capture(conf, str(tmp_path / 'r.vtr'), [], 1, 2, breaks=[0x100], ranges=[(0, 4, True)])
