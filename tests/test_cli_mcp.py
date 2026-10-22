import asyncio
import json
import struct

from arek import adf, cli
from arek.packers import atomik, bytekiller, pp20


def _disk(rnd):
    d = bytearray(adf.SIZE)
    d[0:4] = b'DOS\0'
    struct.pack_into('>I', d, 4, adf.bootblock_checksum(d[:1024]))
    blk = bytekiller.pack_b_literal(rnd(300))
    d[8000:8000 + len(blk)] = blk
    at = atomik.pack(b'atomik payload ' * 20)
    d[20000:20000 + len(at)] = at
    return bytes(d)


def test_cli_roundtrip(tmp_path, capsys, rnd, code):
    disk = tmp_path / 'd.adf'
    disk.write_bytes(_disk(rnd))
    assert cli.main(['adf', 'info', str(disk)]) == 0
    assert json.loads(capsys.readouterr().out)['bootblock']['bootable']
    assert cli.main(['scan', str(disk)]) == 0
    assert '00001f40' in capsys.readouterr().out
    pp = tmp_path / 'p.pp'
    pp.write_bytes(pp20.pack_literal(b'hello amiga'))
    assert cli.main(['pp20', str(pp), '-o', str(tmp_path / 'p.out')]) == 0
    assert (tmp_path / 'p.out').read_bytes() == b'hello amiga'
    at = tmp_path / 'a.atn'
    at.write_bytes(b'\0' * 100 + atomik.pack(b'atomik block in an image' * 4))
    assert cli.main(['atn', str(at), '-o', str(tmp_path / 'a.out'), '--offset', '100']) == 0
    assert (tmp_path / 'a.out').read_bytes() == b'atomik block in an image' * 4
    base, data = code
    cb = tmp_path / 'c.bin'
    cb.write_bytes(data)
    assert cli.main(['dis', str(cb), '--base', hex(base)]) == 0
    assert 'moveq #5,d0' in capsys.readouterr().out
    assert cli.main(['recomp', str(cb), '--base', hex(base), '--auto', hex(base + 0x0e),
                     '-o', str(tmp_path / 'o.c')]) == 0
    assert (tmp_path / 'o.c').read_text().count('f_00100e') >= 1
    assert cli.main(['init', str(tmp_path / 'proj')]) == 0
    assert (tmp_path / 'proj' / 'local.conf').exists()
    assert cli.main(['shot', 'x', '1', '--conf', str(tmp_path / 'proj' / 'local.conf')]) == 1
    err = capsys.readouterr().err
    assert 'ADF does not exist' in err and 'directory of the conf file' in err


def test_mcp_tools(tmp_path, rnd, code):
    pytest = __import__('pytest')
    pytest.importorskip('mcp')
    from arek import mcp_server
    disk = tmp_path / 'd.adf'
    disk.write_bytes(_disk(rnd))
    base, data = code
    cb = tmp_path / 'c.bin'
    cb.write_bytes(data)

    async def go():
        names = {t.name for t in await mcp_server.mcp.list_tools()}
        assert {'adf_info', 'scan_packed', 'unpack', 'walk', 'hwscan', 'recomp', 'diff_captures'} <= names
        r = await mcp_server.mcp.call_tool('scan_packed', {'path': str(disk)})
        txt = r.content[0].text if hasattr(r, 'content') else str(r)
        assert '8000' in txt
        r = await mcp_server.mcp.call_tool('unpack', {'path': str(disk), 'out': str(tmp_path / 'u.bin'),
                                                      'offset': '8000'})
        assert (tmp_path / 'u.bin').stat().st_size == 300
        r = await mcp_server.mcp.call_tool('unpack', {'path': str(disk), 'out': str(tmp_path / 'a.bin'),
                                                      'offset': '20000'})
        assert (tmp_path / 'a.bin').read_bytes() == b'atomik payload ' * 20
        txt = (r.content[0].text if hasattr(r, 'content') else str(r))
        assert 'atn' in txt
        r = await mcp_server.mcp.call_tool('walk', {'path': str(cb), 'base': hex(base), 'start': hex(base + 0x0e)})
        txt = r.content[0].text if hasattr(r, 'content') else str(r)
        assert 'bsr $1004' in txt
    asyncio.run(go())


def test_version_and_module_entry_point():
    import re
    import subprocess
    import sys
    from pathlib import Path
    import arek
    assert re.fullmatch(r'\d+\.\d+\.\d+', arek.__version__)
    pyproject = (Path(arek.__file__).parents[2] / 'pyproject.toml').read_text()
    assert 'dynamic = ["version"]' in pyproject and 'attr = "arek.__version__"' in pyproject
    assert not re.search(r'^version = "', pyproject, re.M)       # no static copy: arek.__version__ is the source
    r = subprocess.run([sys.executable, '-m', 'arek', '--help'], capture_output=True, text=True)
    assert r.returncode == 0 and 'arek' in r.stdout
