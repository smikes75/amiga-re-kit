"""wb-atn.js (the ATN! decruncher for a page) against arek.packers.atomik, wb-content.js (the game's files from
the visitor's disks for the payload key), `arek web payload` and the development server."""
import http.client
import json
import os
import random
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

from arek import cli, web
from arek.packers import atomik

WEB = Path(web.HERE)
node = shutil.which('node')


def js(expr, files=()):
    if not node:
        pytest.skip('no node')
    pre = ''.join("const %s = require(%s); " % (n, json.dumps(str(WEB / f))) for n, f in (('ATNUNPACK', 'wb-atn.js'), ('WBCONTENT', 'wb-content.js')))
    code = pre + "(async () => { const r = await (%s); console.log(JSON.stringify(r)); })().catch((e) => { console.error(e); process.exit(1); });" % expr
    p = subprocess.run([node, '-e', code], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def sample(seed, n=3000):
    rnd = random.Random(seed)
    out = bytearray()
    while len(out) < n:
        if rnd.random() < 0.4 and len(out) > 40:
            start = rnd.randrange(len(out) - 20)
            out += out[start:start + rnd.randrange(3, 20)]
        else:
            out += bytes(rnd.randrange(256) for _ in range(rnd.randrange(1, 12)))
    return bytes(out[:n])


@pytest.mark.parametrize('seed', [1, 2, 3])
def test_js_unpack_equals_python(seed):
    data = sample(seed)
    packed = atomik.pack(data, prime=seed % 8)
    assert atomik.unpack(packed) == data
    out = js("Array.from(ATNUNPACK.unpack(Uint8Array.from(%s), 0))" % list(packed))
    assert bytes(out) == data
    h = js("ATNUNPACK.header(Uint8Array.from(%s), 0)" % list(packed[:12]))
    assert h['unpacked'] == len(data) and h['packed'] == atomik.header(packed)['packed']
    lit = atomik.pack_literal(data[:100], skip_last=True)
    assert bytes(js("Array.from(ATNUNPACK.unpack(Uint8Array.from(%s), 0))" % list(lit))) == data[:100]


def test_payload_and_content_key(tmp_path):
    a, b = sample(10, 1500), sample(11, 2500)
    pa, pb = atomik.pack(a), atomik.pack(b)
    disk = bytearray(0x4000)
    disk[0x400:0x400 + len(pa)] = pa
    disk[0x1200:0x1200 + len(pb)] = pb
    (tmp_path / 'd1.adf').write_bytes(disk)
    conf = {'ADF1': str(tmp_path / 'd1.adf')}
    payload, content = web.payload_atn([('ADF1', 0x400), ('ADF1', 0x1200)], conf)
    assert payload == a + b and content['content'] == 'arek-atn-files-1' and [f['size'] for f in content['files']] == [1500, 2500]
    assert web.parse_block('ADF1:0x1200') == ('ADF1', 0x1200) and web.parse_block('/x/y.adf:1024') == ('/x/y.adf', 1024)
    # the page finds the same files on a disk where they lie elsewhere, in any order
    other = bytearray(0x5000)
    other[0x2000:0x2000 + len(pb)] = pb
    other[0x3800:0x3800 + len(pa)] = pa
    got = js("WBCONTENT.build([Uint8Array.from(%s)], %s).then((x) => x ? Array.from(x) : null)" % (list(other), json.dumps(content)))
    assert bytes(got) == payload
    assert js("WBCONTENT.check([Uint8Array.from(%s)], %s)" % (list(other[:0x3000]), json.dumps(content))) == [False, True]
    assert js("WBCONTENT.build([Uint8Array.from(%s)], %s)" % (list(other[:0x3000]), json.dumps(content))) is None
    (tmp_path / 'local.conf').write_text('ADF1 = %s\n' % (tmp_path / 'd1.adf'))
    assert cli.main(['web', 'payload', '--atn', 'ADF1:0x400', 'ADF1:0x1200', '--out', str(tmp_path / 'p.bin'),
                     '--content', str(tmp_path / 'content.json'), '--conf', str(tmp_path / 'local.conf')]) == 0
    assert (tmp_path / 'p.bin').read_bytes() == payload and json.load(open(tmp_path / 'content.json')) == content


def test_dev_server(tmp_path):
    site = tmp_path / 'site'
    site.mkdir()
    (site / 'index.html').write_text('<html>hi</html>')
    (tmp_path / 'd1.adf').write_bytes(b'\x01\x02\x03' * 100)
    (tmp_path / 'd2.adf').write_bytes(b'\x09' * 50)
    srv = web.serve(site, 0, {'ADF1': str(tmp_path / 'd1.adf'), 'ADF2': str(tmp_path / 'd2.adf'), 'ROM': 'x'})
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        c = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
        c.request('GET', '/local-disks/disk1.adf')
        r = c.getresponse()
        assert r.status == 200 and r.read() == b'\x01\x02\x03' * 100 and r.getheader('Cache-Control') == 'no-store'
        c.request('GET', '/local-disks/disk2.adf?x=1')
        assert c.getresponse().read() == b'\x09' * 50
        c.request('GET', '/index.html')
        assert c.getresponse().read() == b'<html>hi</html>'
        c.request('GET', '/local-disks/disk3.adf')
        assert c.getresponse().status == 404
    finally:
        srv.shutdown()
    assert sorted(srv.disks) == ['/local-disks/disk1.adf', '/local-disks/disk2.adf']
