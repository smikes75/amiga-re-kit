"""wb-datadisk.js in Node: the storage alone (base64 under a key, the size check), and a disk opened over a fake engine -
load() puts a saved disk into the heap, poll() saves what the game wrote when the generation moved, clear() empties
both, a failing storage is reported, the clear button arms on the first click and clears on the second."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).parent.parent / 'src' / 'arek' / 'web'
node = shutil.which('node')

SETUP = '''
const mem = new Map(); let fail = false;
globalThis.localStorage = { getItem: (k) => mem.has(k) ? mem.get(k) : null, setItem: (k, v) => { if (fail) throw new Error('quota'); mem.set(k, v); }, removeItem: (k) => mem.delete(k) };
const D = require(%s);
const heap = new Uint8Array(4096); let gen = 0, okCalls = [];
const host = { buf: () => 1024, size: () => 512, heap: () => heap, set: (ok) => okCalls.push(ok), gen: () => gen };
const logs = []; const saved = [];
const dd = D.open({ key: 'k', host, label: 'Hall of Fame', log: (s) => logs.push(s), onSave: (b, err) => saved.push([b.length, err]) });
const out = {};
'''


def js(body):
    if not node:
        pytest.skip('no node')
    code = SETUP % json.dumps(str(WEB / 'wb-datadisk.js')) + body + '\nconsole.log(JSON.stringify(out));'
    r = subprocess.run([node, '-e', code], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_storage_alone():
    out = js('''
out.version = D.VERSION;
out.empty = D.read('k', 512);
out.err = D.write('k', Uint8Array.from([1, 2, 3, 250]));
out.raw = mem.get('k');
out.any = Array.from(D.read('k', 0)); out.wrong = D.read('k', 512);
mem.set('k', '***'); out.bad = D.read('k', 0);
D.remove('k'); out.gone = D.read('k', 0);
fail = true; out.fail = D.write('k', new Uint8Array(2)); fail = false;
const big = new Uint8Array(70000); for (let i = 0; i < big.length; i++) big[i] = i & 255;
D.write('k', big); const back = D.read('k', 70000); let same = back && back.length === 70000; for (let i = 0; same && i < 70000; i++) same = back[i] === (i & 255);
out.big = same;
''')
    assert out['version'] == '1.0' and out['empty'] is None and out['err'] == '' and out['raw'] == 'AQID+g=='
    assert out['any'] == [1, 2, 3, 250] and out['wrong'] is None and out['bad'] is None and out['gone'] is None
    assert out['fail'] == 'quota' and out['big'] is True


def test_disk_over_the_engine():
    out = js('''
out.load0 = dd.load(); out.ok0 = okCalls.slice(); out.has0 = dd.has(); out.poll0 = dd.poll();
const disk = new Uint8Array(512); for (let i = 0; i < 512; i++) disk[i] = (i * 3) & 255;
D.write('k', disk);
out.load1 = dd.load(); out.ok1 = okCalls.slice(); out.heap = [heap[1024], heap[1025], heap[1024 + 511], heap[1023], heap[1024 + 512]];
for (let i = 0; i < 512; i++) heap[1024 + i] = 255 - (i & 255);
out.poll1 = dd.poll();                                      // the generation did not move: nothing saved
gen++; out.poll2 = dd.poll(); out.poll3 = dd.poll();        // one save per generation
const b = dd.bytes(); out.bytes = [b.length, b[0], b[1], b[511]]; out.saved = saved.slice();
gen++; fail = true; out.poll4 = dd.poll(); fail = false;
dd.clear(); out.has1 = dd.has(); out.ok2 = okCalls.slice(); out.logs = logs.slice();
const el = { textContent: 'Clear', onclick: null }; dd.button(el, { ms: 50 });
D.write('k', disk); el.onclick(); out.armed = [el.textContent, dd.has()]; el.onclick(); out.cleared = [el.textContent, dd.has()];
el.onclick(); out.armed2 = el.textContent; setTimeout(() => { out.relaxed = el.textContent; console.log(JSON.stringify(out)); }, 120);
''')
    assert out['load0'] is False and out['ok0'] == [False] and out['has0'] is False and out['poll0'] is False
    assert out['load1'] is True and out['ok1'] == [False, True] and out['heap'] == [0, 3, (511 * 3) & 255, 0, 0]
    assert out['poll1'] is False and out['poll2'] is True and out['poll3'] is False
    assert out['bytes'] == [512, 255, 254, 255 - (511 & 255)] and out['saved'] == [[512, '']]
    assert out['poll4'] is False and out['has1'] is False and out['ok2'] == [False, True, False]
    assert out['logs'] == ['Hall of Fame saved in this browser', 'Hall of Fame not saved: quota',
                           'saved Hall of Fame cleared (the game shows what it loaded until a restart)']
    assert out['armed'] == ['Click again to clear', True] and out['cleared'] == ['Clear', False]
    assert out['armed2'] == 'Click again to clear' and out['relaxed'] == 'Clear'
