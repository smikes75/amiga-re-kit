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


# --- vamiga-buslog-899da5d.patch: chip bus per line, CPU waits, blits

def _buslog():
    owners = bytes([0, 1, 2, 8, 9, 24, 25, 16, 0])
    return (b'L' + struct.pack('<IHH', 300, 44, len(owners)) + owners +
            b'W' + struct.pack('<IHHHIb', 300, 44, 3, 2, 0x40010, 8) +
            b'B' + struct.pack('<IHHHHHHIIIIhhhh', 300, 50, 20, 0x09f0, 0, 20, 16, 0x10000, 0, 0, 0x20000, 0, 0, 0, -2) +
            b'E' + struct.pack('<IHH', 300, 60, 100))


def test_buslog_reader_and_summary(tmp_path, capsys):
    from arek import cli
    log = trace.read_buslog(_buslog())
    assert log['lines'][(300, 44)][:3] == bytes([0, 1, 2])
    assert log['waits'] == [{'frame': 300, 'v': 44, 'h': 3, 'slots': 2, 'pc': 0x40010, 'owner': 'bpl1'}]
    b = log['blits'][0]
    assert (b['bltcon0'], b['width'], b['height'], b['pt'][3], b['mod'][3], b['end']) == (0x09f0, 20, 16, 0x20000, -2, (300, 60, 100))
    s = trace.bus_summary(log)[300]
    assert s['slots'] == {'free': 2, 'CPU': 1, 'refresh': 1, 'bitplane': 2, 'copper': 1, 'blitter': 1, 'sprite': 1}
    assert (s['cpu_waits'], s['cpu_wait_slots'], s['blits']) == (1, 2, 1)
    assert trace.bus_line(log['lines'][(300, 44)]) == '.CR12cbS.'
    with pytest.raises(trace.TraceError):
        trace.read_buslog(_buslog()[:-3])
    with pytest.raises(trace.TraceError):
        trace.read_buslog(b'Q')
    p = tmp_path / 'bus.bin'
    p.write_bytes(_buslog())
    assert cli.main(['trace', 'bus', str(p)]) == 0
    out = capsys.readouterr().out
    assert 'frame 300: 1 lines' in out and 'CPU waited 1 times, 2 slots; 1 blits' in out
    assert cli.main(['trace', 'bus', str(p), '--frame', '300']) == 0
    assert ' 44 .CR12cbS.' in capsys.readouterr().out
    e = trace.env('/t.vtr', buslog=str(p), bus_frames=(10, 20))
    assert e['VAHL_BUSLOG'] == str(p) and e['VAHL_BUSLOG_FRAMES'] == '10:20'


# --- vamiga-shots-regset-899da5d.patch: pictures of consecutive frames, chosen registers

def test_env_for_shots_and_register_sets(tmp_path):
    e = trace.env('/t.vtr', reglog='r.bin', reglog_regs='0e0-0f6,08e', shots=str(tmp_path / 'f'), shot_frames=(100, 104))
    assert e['VAHL_REGLOG_REGS'] == '0e0-0f6,08e' and e['VAHL_SHOTS_FRAMES'] == '100:104'
    assert e['VAHL_SHOTS'] == str(tmp_path / 'f')
    with pytest.raises(trace.TraceError, match='frame window'):
        trace.env('/t.vtr', shots='x')
    for k in (100, 101, 103):
        (tmp_path / ('f_%06d.raw' % k)).write_bytes(b'')
    (tmp_path / 'f_notes.raw').write_bytes(b'')
    assert [f for f, _ in trace.shot_files(str(tmp_path / 'f'))] == [100, 101, 103]


def test_register_names_beyond_the_audio_set():
    regs = struct.pack('<4I', 300, (44 << 16) | 9, (0x0e2 << 16) | 0x1234, 0x1000000 | 0x40010) + \
        struct.pack('<4I', 300, (44 << 16) | 13, (0x08e << 16) | 0x2c81, 0x1000000 | 0x40014)
    names = [r['name'] for r in trace.read_reglog(regs)]
    assert names == ['BPL1PTL', 'DIWSTRT']


def test_capture_with_only_pictures_needs_no_breakpoint(tmp_path, monkeypatch):
    from arek.headless import shot
    seen = {}

    def fake_run(conf, script, capture=False, env=None, timeout=0):
        seen['script'], seen['env'] = script, env
        open(env['VAHL_SHOTS'] + '_000300.raw', 'wb').write(bytes(716 * 285 * 3))
        return ''

    monkeypatch.setattr(shot, 'run_script', fake_run)
    adf, rom = tmp_path / 'g.adf', tmp_path / 'k.rom'
    adf.write_bytes(bytes(901120))
    rom.write_bytes(b'x')
    conf = {'ROM': str(rom), 'ADF1': str(adf), 'VAHL': '/nonexistent'}
    n = trace.capture(conf, str(tmp_path / 'r.vtr'), [], 1, 8, shots=str(tmp_path / 'f'), shot_frames=(300, 300))
    assert n == 0 and 'debugger' not in seen['script']
    assert (tmp_path / 'f_000300.png').read_bytes()[:4] == b'\x89PNG'


# --- vamiga-poke-899da5d.patch: writes into the machine at a frame or a PC

def test_poke_specs_and_file(tmp_path):
    blob = tmp_path / 'w.bin'
    blob.write_bytes(b'\x00\x02')
    assert trace.parse_poke('F8600:c00ffc=0002') == ('F', 8600, 0xc00ffc, b'\x00\x02')
    assert trace.parse_poke('c01b06:$c00faa=@%s' % blob) == ('P', 0xc01b06, 0xc00faa, b'\x00\x02')
    with pytest.raises(trace.TraceError):
        trace.parse_poke('c01b06=0002')
    p = trace.write_pokes(['F8600:c00ffc=0002', 'c01b06:c00faa=00000002'], str(tmp_path / 'x.poke'))
    assert open(p).read() == 'F 2198 c00ffc 0002\nP c01b06 c00faa 00000002\n'
    e = trace.env('/t.vtr', poke=p)
    assert e['VAHL_POKE'] == p
    with pytest.raises(trace.TraceError, match='vamiga-poke-899da5d.patch'):
        trace.require_patch('/bin/ls', ['VAHL_POKE'])
