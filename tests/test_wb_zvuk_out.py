"""wb-zvuk-worklet.js (Paula's output into Web Audio, the canon's module D): its ring logic in Node under a shim of
the AudioWorklet globals - priming, the reserve, an underrun, a flush, the shared-memory mode with the counters;
wb-zvuk-out.js loads. The real thing runs in `arek web smooth` over smooth-demo.html (both modes under stalls)."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from arek import web

WEB = Path(web.__file__).parent
node = shutil.which('node')
SHIM = """globalThis.sampleRate = 48000; globalThis.currentTime = 0; globalThis.__msgs = [];
globalThis.AudioWorkletProcessor = class { constructor() { this.port = { postMessage: (m) => globalThis.__msgs.push(m), onmessage: null }; } };
globalThis.registerProcessor = (n, c) => { globalThis.__name = n; globalThis.__P = c; };
require(%s);
const P = globalThis.__P, p = new P(), out = [[new Float32Array(128), new Float32Array(128)]];
const frame = (v) => { const f = new Int16Array(960 * 2); for (let i = 0; i < 960; i++) { f[2 * i] = v; f[2 * i + 1] = -v; } return f; };
"""


def js(body):
    if not node:
        pytest.skip('no node')
    code = SHIM % json.dumps(str(WEB / 'wb-zvuk-worklet.js')) + body
    return json.loads(subprocess.run([node, '-e', code], capture_output=True, text=True, check=True).stdout)


def test_messages_mode_primes_plays_and_runs_dry():
    r = js("""p.port.onmessage({ data: { prefill: 20, target: 30 } });
        p.process(null, out); const silent = out[0][0][0];
        p.port.onmessage({ data: frame(10000) }); p.process(null, out); const one = [p.primed, out[0][0][0]];   // 960 < prefill 960? exactly: primes
        p.port.onmessage({ data: frame(10000) }); p.process(null, out);
        const l = out[0][0][5], rr = out[0][1][5];
        let n = 0; while (p.primed && n < 40) { p.process(null, out); n++; }
        globalThis.currentTime = 1; p.process(null, out); const st = globalThis.__msgs[globalThis.__msgs.length - 1];
        p.port.onmessage({ data: 'flush' });
        console.log(JSON.stringify({ name: globalThis.__name, silent, one, l: +l.toFixed(3), r: +rr.toFixed(3), blocks: n, under: p.under, st, w: p.w, rd: p.rd }));""")
    assert r['name'] == 'wb-paula' and r['silent'] == 0
    assert r['l'] == 0.305 and r['r'] == -0.305                                     # 10000 / 32768
    assert 10 <= r['blocks'] <= 20 and r['under'] == 1                            # 1920 samples = 15 blocks of 128, then it ran dry once
    assert r['st']['under'] == 1 and r['st']['shared'] is False and r['st']['primed'] is False
    assert r['w'] == 0 and r['rd'] == 0


def test_overflow_drops_a_frame_and_speed_follows_the_reserve():
    r = js("""p.port.onmessage({ data: { prefill: 20, target: 30 } });
        for (let k = 0; k < 60; k++) p.port.onmessage({ data: frame(100) });          // 57 600 samples into a ring of 48 000: the rest dropped
        const drop = p.drop; p.process(null, out); const rd1 = p.rd;
        console.log(JSON.stringify({ drop, w: p.w, rd1 }));""")
    assert r['drop'] > 0 and r['w'] <= 48000 and r['rd1'] >= r['w'] - 1440 - 128     # kept at the target 30 ms (+ one block) when far ahead


def test_shared_mode_reads_the_engines_ring_and_counts():
    r = js("""const n = 4800, sab = new SharedArrayBuffer(n * 4 + 8), ring = new Int16Array(sab, 0, n * 2), idx = new Int32Array(sab, n * 4, 2);
        p.port.onmessage({ data: { prefill: 20, target: 30 } });
        p.port.onmessage({ data: { sab, ring: 0, n, widx: n * 4, ridx: n * 4 + 4 } });
        for (let i = 0; i < 2000; i++) { ring[2 * i] = 8000; ring[2 * i + 1] = 8000; } Atomics.store(idx, 0, 2000);
        p.process(null, out); const a = [p.primed, out[0][0][3].toFixed(3), Atomics.load(idx, 1)];
        p.process(null, out); const b = Atomics.load(idx, 1);
        console.log(JSON.stringify({ a, b, shared: !!p.shared }));""")
    assert r['shared'] and r['a'][0] is True and r['a'][1] == '0.244' and r['a'][2] == 128 and r['b'] == 256


def test_page_side_loads():
    if not node:
        pytest.skip('no node')
    code = "const O = require(%s); console.log(JSON.stringify([O.VERSION, O.PRESETS.shared, typeof O.create]));" % json.dumps(str(WEB / 'wb-zvuk-out.js'))
    assert json.loads(subprocess.run([node, '-e', code], capture_output=True, text=True, check=True).stdout) == ['1.0', {'prefill': 20, 'target': 30, 'low': 15}, 'function']
    assert 'wb-zvuk-out.js' in web.FILES and 'wb-zvuk-worklet.js' in web.FILES
