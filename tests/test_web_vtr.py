"""wb-vtr.js 1.0 (kit 1.0.84, SWIV-projekt): VTR2 records written from JavaScript - a rewrite without the original's RAM
projects its fields onto the original's addresses; `arek trace compare` reads them as it reads a recompiled engine's."""
import json
import os
import shutil
import subprocess

import pytest

from arek import parity, web
from arek.headless import trace

WEB = os.path.dirname(os.path.abspath(web.__file__))
node = shutil.which('node')


def _write(tmp_path, body):
    if not node:
        pytest.skip('no node')
    out = tmp_path / 'js.vtr'
    code = 'const V = require(%s); const w = V.writer(); %s; require("fs").writeFileSync(%s, w.bytes()); console.log(JSON.stringify([V.VERSION, w.count]));' % (
        json.dumps(os.path.join(WEB, 'wb-vtr.js')), body, json.dumps(str(out)))
    return json.loads(subprocess.run([node, '-e', code], capture_output=True, text=True, check=True).stdout), out


def test_files_and_version():
    import tomllib                                                            # web copy ships it, so does the wheel
    from pathlib import Path
    data = tomllib.loads((Path(__file__).parent.parent / 'pyproject.toml').read_text())['tool']['setuptools']['package-data']['arek.web']
    assert 'wb-vtr.js' in web.FILES and 'wb-vtr.js' in data and set(web.FILES) <= set(data)


def test_fields_read_back_and_compare_with_the_original(tmp_path):
    """Three events of two kinds: fields next to each other merge into one range, a gap starts a new one, the hit counts per
    pc, the registers and the frame read back; the same fields from Python (the original's side) compare equal over their
    ranges, a changed field is the first difference at its address."""
    (ver, n), out = _write(tmp_path, """
        w.add({ pc: 0x6160, frame: 812, d: [1, 2, 0xffffffff], a: [0x2a00], fields: [[0x2a12, 'w', 0x00c8], [0x2a10, 'w', 0x0140], [0x2a20, 'b', 7]] });
        w.add({ pc: 0x6160, frame: 815, fields: [[0x2a10, 'w', 0x0141], [0x2a12, 'w', 0x00c9], [0x2a20, 'b', 7]] });
        w.add({ pc: 0x4c0c, frame: 815, ranges: [[0x7000, [0xde, 0xad]]], fields: [[0x7004, 'l', 0x12345678]] })""")
    assert ver == '1.0' and n == 3
    recs = list(trace.records(str(out)))
    assert [(r['addr'], r['hit'], r['frame']) for r in recs] == [(0x6160, 1, 812), (0x6160, 2, 815), (0x4c0c, 1, 815)]
    assert recs[0]['d'][:3] == [1, 2, 0xffffffff] and recs[0]['a'][0] == 0x2a00
    assert recs[0]['ranges'] == {0x2a10: bytes([0x01, 0x40, 0x00, 0xc8]), 0x2a20: bytes([7])}
    assert trace.read(recs[1], 0x2a10, 'H') == 0x141 and trace.read(recs[2], 0x7004, 'I') == 0x12345678 and recs[2]['ranges'][0x7000] == b'\xde\xad'

    def orig(pc, hit, frame, x, y, hp):                      # the original's record: a whole span of its RAM
        ram = bytearray(0x20)
        ram[0:2], ram[2:4], ram[0x10] = x.to_bytes(2, 'big'), y.to_bytes(2, 'big'), hp
        return {'kind': 'VTR2', 'addr': pc, 'hit': hit, 'frame': frame, 'ranges': {0x2a10: bytes(ram)}}
    a = [orig(0x6160, 1, 812, 0x140, 0xc8, 7), orig(0x6160, 2, 815, 0x141, 0xc9, 7)]
    fields = [(0x2a10, 4), (0x2a20, 1)]
    r = parity.compare(a, recs[:2], fields)
    assert r['complete'] and r['bytes'] == 10
    a[1] = orig(0x6160, 2, 815, 0x141, 0xca, 7)
    r = parity.compare(a, recs[:2], fields)
    assert not r['complete'] and r['first']['index'] == 1 and r['first']['diffs'][0][0] == 0x2a12   # by word


def test_overlapping_fields_and_a_bad_format_are_refused(tmp_path):
    if not node:
        pytest.skip('no node')
    for body in ("w.add({ fields: [[0x10, 'l', 1], [0x12, 'w', 2]] })", "w.add({ fields: [[0x10, 'q', 1]] })"):
        p = subprocess.run([node, '-e', 'const V = require(%s); const w = V.writer(); %s' % (json.dumps(os.path.join(WEB, 'wb-vtr.js')), body)], capture_output=True, text=True)
        assert p.returncode != 0 and 'wb-vtr' in p.stderr
