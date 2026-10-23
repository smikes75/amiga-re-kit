"""Sealed files (arek.seal, web/wb-seal.js): derived code that only the original disk opens."""
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

pytest.importorskip('cryptography')
from arek import cli, seal

WEB = Path(__file__).parent.parent / 'src' / 'arek' / 'web'
D1, D1B, D2 = bytes(range(256)) * 8, bytes(range(255, -1, -1)) * 8, b'second disk' * 100
FILES = {'engine.wasm': b'\0asm' + bytes(5000), 'js/logic.js': b'console.log("level 1");'}


def test_round_trip_versions_and_sets():
    manifest, blobs = seal.seal(FILES, [[D1], [D1B], [D1, D2]])
    assert all(FILES[p] not in blobs[p] for p in FILES)
    assert seal.unseal(manifest, blobs, [D1]) == FILES
    assert seal.unseal(manifest, blobs, [D1B]) == FILES                    # another version of the disk
    assert seal.unseal(manifest, blobs, [D1, D2]) == FILES                 # a game that needs two disks
    with pytest.raises(ValueError, match='no key'):
        seal.unseal(manifest, blobs, [D2])
    with pytest.raises(ValueError, match='no key'):
        seal.unseal(manifest, blobs, [D2, D1])                              # order matters
    assert manifest['keys'][0]['disks'] == [hashlib.sha256(D1).hexdigest()]


def test_the_public_hash_is_not_the_key():
    # the page shows each disk's sha256; the key comes from the contents with a different prefix
    assert seal.disk_key(D1) != hashlib.sha256(D1).digest()


def test_tampering_is_detected():
    manifest, blobs = seal.seal(FILES, [[D1]])
    bad = dict(blobs)
    bad['engine.wasm'] = blobs['engine.wasm'][:-1] + bytes([blobs['engine.wasm'][-1] ^ 1])
    with pytest.raises(ValueError, match='do not match'):
        seal.unseal(manifest, bad, [D1])
    swapped = {'engine.wasm': blobs['js/logic.js'], 'js/logic.js': blobs['engine.wasm']}
    with pytest.raises(ValueError):
        seal.unseal(manifest, swapped, [D1])


def test_cli_and_browser_side(tmp_path, capsys):
    root = tmp_path / 'present'
    (root / 'js').mkdir(parents=True)
    for p, d in FILES.items():
        (root / p).write_bytes(d)
    (tmp_path / 'd1.adf').write_bytes(D1)
    (tmp_path / 'd2.adf').write_bytes(D2)
    out = tmp_path / 'sealed'
    assert cli.main(['web', 'seal', str(root / 'engine.wasm'), str(root / 'js/logic.js'), '--root', str(root),
                     '--set', str(tmp_path / 'd1.adf'), '--set', '%s,%s' % (tmp_path / 'd1.adf', tmp_path / 'd2.adf'),
                     '--out', str(out)]) == 0
    assert '2 files sealed for 2 disk sets' in capsys.readouterr().out
    manifest, blobs = seal.read_dir(out)
    assert seal.unseal(manifest, blobs, [D1]) == FILES
    node = shutil.which('node')
    if not node:
        pytest.skip('no node')
    script = """
const S = require(%s), fs = require('fs');
(async () => {
  const m = JSON.parse(fs.readFileSync(%s, 'utf8'));
  const box = await S.open(m, [fs.readFileSync(%s)]);
  const plain = Buffer.from(await box.get('js/logic.js', fs.readFileSync(%s)));
  let refused = false;
  try { await S.open(m, [fs.readFileSync(%s)]); } catch (e) { refused = /no key/.test(e.message); }
  console.log(JSON.stringify({plain: plain.toString(), refused, ids: await S.ids([fs.readFileSync(%s)])}));
})();
""" % tuple(json.dumps(str(x)) for x in (WEB / 'wb-seal.js', out / 'seal.json', tmp_path / 'd1.adf',
                                          out / 'js/logic.js.sealed', tmp_path / 'd2.adf', tmp_path / 'd1.adf'))
    r = json.loads(subprocess.run([node, '-e', script], capture_output=True, text=True, check=True).stdout)
    assert r['plain'] == FILES['js/logic.js'].decode() and r['refused']
    assert r['ids'] == [hashlib.sha256(D1).hexdigest()]


def test_web_copy_brings_both_modules(tmp_path, capsys):
    assert cli.main(['web', 'copy', str(tmp_path)]) == 0
    assert (tmp_path / 'wb-seal.js').exists() and (tmp_path / 'wb-obraz.js').exists()


def test_gzip_and_labels(tmp_path):
    big = {'engine.wasm': b'\0asm' + bytes(200000) + b'end'}
    manifest, blobs = seal.seal(big, [[D1], [D1B]], labels=['disk 1, retail', 'disk 1, crack'], compress=True)
    f = manifest['files'][0]
    assert f['encoding'] == 'gzip' and f['stored'] < 5000 and f['size'] == len(big['engine.wasm'])
    assert len(blobs['engine.wasm']) < 5000
    assert [k['label'] for k in manifest['keys']] == ['disk 1, retail', 'disk 1, crack']
    assert seal.unseal(manifest, blobs, [D1B]) == big
    out = tmp_path / 's'
    seal.write_dir(out, manifest, blobs)
    node = shutil.which('node')
    if not node:
        pytest.skip('no node')
    script = """
const S = require(%s), fs = require('fs');
(async () => {
  const m = JSON.parse(fs.readFileSync(%s, 'utf8'));
  const box = await S.open(m, [fs.readFileSync(%s)]);
  const plain = Buffer.from(await box.get('engine.wasm', fs.readFileSync(%s)));
  console.log(JSON.stringify({len: plain.length, head: plain.subarray(0, 4).toString(), tail: plain.subarray(-3).toString()}));
})();
""" % tuple(json.dumps(str(x)) for x in (WEB / 'wb-seal.js', out / 'seal.json', tmp_path / 'd1.adf', out / 'engine.wasm.sealed'))
    (tmp_path / 'd1.adf').write_bytes(D1)
    r = json.loads(subprocess.run([node, '-e', script], capture_output=True, text=True, check=True).stdout)
    assert r == {'len': len(big['engine.wasm']), 'head': '\0asm', 'tail': 'end'}


def test_bundle_check(tmp_path, capsys):
    b = tmp_path / 'present'
    (b / 'sealed').mkdir(parents=True)
    (b / 'index.html').write_bytes(b'<html>')
    manifest, blobs = seal.seal({'engine.wasm': b'\0asm'}, [[D1]], labels=['disk 1'])
    seal.write_dir(b / 'sealed', manifest, blobs)
    entries = []
    for rel in ('index.html', 'sealed/seal.json', 'sealed/engine.wasm.sealed'):
        data = (b / rel).read_bytes()
        entries.append({'path': rel, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
                        'derived': rel.endswith('.sealed'), 'sealed': rel.endswith('.sealed')})
    (b / 'manifest.json').write_text(json.dumps({'files': entries}))
    r = seal.check_bundle(b)
    assert r['problems'] == [] and r['sealed'] == ['engine.wasm'] and r['files'] == 4
    assert cli.main(['web', 'check', str(b)]) == 0
    # game data, a derived file in the clear, a stale manifest size
    (b / 'game.adf').write_bytes(bytes(901120))
    (b / 'engine.wasm').write_bytes(b'\0asm')
    (b / 'index.html').write_bytes(b'<html><body>')
    p = seal.check_bundle(b)['problems']
    assert any('game data' in x for x in p) and any('also present in the clear' in x for x in p)
    assert any('manifest size' in x for x in p) and any('not in the manifest' in x for x in p)
    assert cli.main(['web', 'check', str(b)]) == 1
