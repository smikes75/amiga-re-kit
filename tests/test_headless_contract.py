import json

import pytest

from arek import contract
from arek.headless import bpstate, config, shot


def test_config_load_and_paths(tmp_path):
    (tmp_path / 'local.conf').write_text('MACHINE = A500_OCS_1MB\nROM = "roms/k.rom"\nADF1 = disks/a.adf\n'
                                         'VAHL = bin/VAHeadless\nOBJDUMP = m68k-elf-objdump\n# x = y\n')
    c = config.load(tmp_path / 'local.conf')
    assert c['ROM'] == str(tmp_path / 'roms' / 'k.rom')
    assert c['ADF1'].endswith('a.adf') and c['OBJDUMP'] == 'm68k-elf-objdump'
    with pytest.raises(config.ConfigError):
        config.require(c, 'ROM')                         # file does not exist
    with pytest.raises(config.ConfigError):
        config.load(tmp_path / 'nope.conf')


def test_shot_script():
    s = shot.build_script({'ROM': '/r', 'MACHINE': 'A500_OCS_1MB'}, '/a.adf',
                          [(3, 'joystick 1 press fire'), (1, 'keyboard press 0x40')], 5, '/o.png')
    lines = s.splitlines()
    assert lines[0] == 'regression setup A500_OCS_1MB "/r"'
    assert 'denise set FRAME_SKIPPING 0' in lines
    assert lines[3:] == ['regression run "/a.adf"', 'wait 1', 'keyboard press 0x40',
                         'wait 2', 'joystick 1 press fire', 'wait 2', 'screenshot save /o.png']


RCPU = '''
D0 - D3 : 0x00000001 0x00000027 0x00000000 0xdeadbeef
D4 - D7 : 0x00000000 0x00000000 0x00000000 0x00000000
A0 - A3 : 0x00020000 0x00dff000 0x00000000 0x00000000
A4 - A7 : 0x00000000 0x00000000 0x00000000 0x0007fffc
PC      : 0x00020700
Flags   : ttSm-<0>---xNZvc
Clock   : 123456
Frame   : 42 (PAL)
Position: (100,20)
'''


def test_parse_regs_and_beam():
    st = bpstate.parse_regs(RCPU)
    assert st['d'][3] == 0xdeadbeef and st['a'][1] == 0xdff000 and st['pc'] == 0x20700
    assert st['ccr'] == {'x': 0, 'n': 1, 'z': 1, 'v': 0, 'c': 0}
    assert bpstate.parse_beam(RCPU) == {'clock': 123456, 'frame': 42, 'position': [100, 20]}
    with pytest.raises(ValueError):
        bpstate.parse_beam('nothing')


def _capture(folder, ram, pc=0x1000, d0=0):
    folder.mkdir()
    (folder / 'cpu.json').write_text(json.dumps({'breakpoint': pc, 'skip': 0, 'pc': pc,
                                                 'd': [d0] + [0] * 7, 'a': [0] * 8, 'regions': []}))
    (folder / ('ram_%x_0.bin' % pc)).write_bytes(ram)


def test_contract_compare(tmp_path):
    a = bytearray(4096)
    b = bytearray(4096)
    b[0x100:0x104] = b'\x01\x02\x03\x04'
    b[0x800] = 0xff
    _capture(tmp_path / 'a', bytes(a))
    _capture(tmp_path / 'b', bytes(b), d0=7)
    x, y = contract.load(tmp_path / 'a'), contract.load(tmp_path / 'b')
    runs = contract.compare(x['ram'], y['ram'])
    assert [(s, e) for s, e, _, _ in runs] == [(0x100, 0x104), (0x800, 0x801)]
    assert contract.compare(x['ram'], y['ram'], [(0x200, 0x400)]) == []
    assert contract.untouched(x['ram'], y['ram'], [(0x0, 0x200)])
    assert contract.diff_regs(x, y) == {'d0': (0, 7)}
    assert contract.format_runs([]) == 'OK - no differences'
    assert '000100-000104' in contract.format_runs(runs)
