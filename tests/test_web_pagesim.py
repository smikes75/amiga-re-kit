"""wb-pagesim.js 1.0 (kit 1.0.78, SWIV): the page's loop without a browser - the clock grants, an engine model computes a frame
in the given ms, the page's feed makes the record when the frame is done, compose draws every display frame - and its
samples judged by `arek web smooth --samples` with the browser's measure; wb-takt 1.7's late(); websmooth 1.8's back steps."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from arek import cli, web, websmooth

WEB = Path(web.__file__).parent
node = shutil.which('node')

# a synthetic game: a pass every 2 frames, the object 4, 8, 4, 8 px on (uneven, never back), shown 2 or 1 frames after its
# computation; the page stamps record n with frame n + 1's time and gives the pass its computation's time + D (passTime) and
# the pass computed and not shown yet as rec.next - SWIV's feedScene
GAME = """const T = require(%s), S = require(%s), P = require(%s);
const win = { w: 320, h: 200, idx: new Uint8Array(64000), pal: new Uint8Array(200 * 128) }, lim = { x0: 0, x1: 0, y0: 0, y1: 2000 };
const X = (k) => 40 + 6 * k - (k %% 2 ? 2 : 0), fs = (k) => 2 * k + (k %% 2 ? 1 : 2);
const game = (D) => { let last = -1;
  return (n, takt) => { const t = takt.stamp(n + 1), fm = takt.fm(); let sh = -1, cp = -1;
    for (let k = 0; 2 * k <= n; k++) { cp = k; if (fs(k) <= n) sh = k; }
    if (sh < 0) return null;
    const pt = (k) => t - (n + 1 - 2 * k - 0.25) * fm + D;
    if (sh !== last) { last = sh; takt.pass(t); }
    const rec = { n, t, cam: [0, 0], limits: lim, window: win, pass: pt(sh), objects: [{ id: 1, x: X(sh) %% 280, y: 50, w: 1, h: 1, idx: new Uint8Array(1) }] };
    if (cp > sh) rec.next = { pass: pt(cp), cam: [0, 0], objects: [{ id: 1, x: X(cp) %% 280, y: 50 }] };
    return rec; }; };
const sim = (eng, spike, takt, count) => P.run({ WBTAKT: T, WBSCENE: S, from: 0, count: count || 1200, feed: game(30), hz: 60, engine: eng, spike,
  takt: Object.assign({ fps: 50 }, takt), scene: { passTime: true, extrapolateObjects: 1, jumpMax: 40, passMax: 200 } });
"""


def run_js(body):
    if not node:
        pytest.skip('no node')
    code = GAME % tuple(json.dumps(str(WEB / f)) for f in ('wb-takt.js', 'wb-scene.js', 'wb-pagesim.js')) + 'console.log(JSON.stringify((' + body + ')));'
    return json.loads(subprocess.run([node, '-e', code], capture_output=True, text=True, check=True).stdout)


def test_files_and_versions():
    assert 'wb-pagesim.js' in web.FILES
    assert run_js('[P.VERSION, T.VERSION]') == ['1.0', '1.7']


def test_the_clock_measures_how_late_a_frame_came():
    """wb-takt 1.7: late() = [median, max] of (the clock's time at stamp(n)) - (frame n's time); the time source is the page's
    (create({ now })); reset() starts it anew."""
    r = run_js("""(() => { let now = 1000; const t = T.create({ now: () => now }); t.tick(1000, 0, false);
        const out = []; for (let n = 1; n <= 9; n++) { now = 1000 + n * 20 + (n === 9 ? 70 : 5); t.stamp(n); }
        out.push(t.late(), t.stats().late); t.reset(0); out.push(t.late()); return out; })()""")
    assert r[0] == [25, 90] and r[1] == r[0] and r[2] is None          # frame n at 1000 + (n - 1) * 20, stamped 25 ms later, the last 90


def test_a_slow_engine_makes_objects_step_back():
    """The loop with a fast engine (5 ms a frame, as in Node) composes every display frame from a pass it has: no object runs
    past its newest pass and none steps back. An engine at a browser thread's speed (12-18 ms, now and then 40 ms more) brings
    the records 20-100 ms after their time: at the objects' 40 ms the objects run past their pass and come back (SWIV's
    helicopters); a latency that covers the records' lateness takes most of it back."""
    r = run_js("""(() => { const o = {}; for (const [k, e, s, t] of [['fast', 5, null, { ahead: 2, latC: 30, latO: 40 }],
            ['slow', [12, 18], [0.05, 40], { ahead: 2, latC: 30, latO: 40 }], ['slow76', [12, 18], [0.05, 40], { ahead: 4, latC: 50, latO: 76 }]]) {
            const v = sim(e, s, t); o[k] = { samples: v.samples, extrapolated: v.extrapolated, shown: v.shown, late: v.late, lost: v.lost }; }
        return o; })()""")
    j = {k: websmooth.judge_samples(v) for k, v in r.items()}
    assert r['fast']['extrapolated'] == 0 and j['fast']['obj_back'] == 0 and j['fast']['missing_pct'] == 0, j['fast']
    assert j['fast']['obj_moving'] > 1000 and r['fast']['late'][1] < 20
    assert r['slow']['extrapolated'] > 100 and j['slow']['obj_back'] > 30 and r['slow']['late'][0] >= 15, (r['slow']['late'], j['slow'])
    assert any("stepped back" in f for f in j["slow"]["fails"]) and not any('stepped back' in f for f in j['fast']['fails'])
    assert j['slow76']['obj_back'] < j['slow']['obj_back'] / 2 and r['slow76']['extrapolated'] < r['slow']['extrapolated'] / 2


def test_back_steps_against_the_motion():
    """websmooth 1.8: a step against the mean of the 9 around it, where that mean is over 0.3 px a frame, is a back step;
    an uneven motion, a turn, a slow drift and the steps around a jump are not."""
    even, uneven = [2.5] * 40, [2.0, 4.0] * 20
    assert websmooth.backsteps(even) == (0, 32) and websmooth.backsteps(uneven) == (0, 32)
    over = [2.5] * 10 + [5.0, -2.5] + [2.5] * 10                 # ran past the pass and came back
    assert websmooth.backsteps(over)[0] == 1
    turn = [2.0] * 10 + [0.5, -0.5] + [-2.0] * 10
    assert websmooth.backsteps(turn)[0] == 0
    assert websmooth.backsteps([0.1, -0.1] * 20) == (0, 0)        # a drift has no direction
    wrap = [2.5] * 10 + [-277.0] + [2.5] * 10                   # a wrap is a jump, not motion
    assert websmooth.backsteps(wrap)[0] == 0
    assert websmooth.overjumps([2.5] * 5 + [6.0] + [2.5] * 5) == 1


def test_cli_judges_samples_without_a_browser(tmp_path, capsys):
    r = run_js("(() => { const v = sim([12, 18], [0.05, 40], { ahead: 2, latC: 30, latO: 40 }, 600); return v; })()")
    f = tmp_path / 'slow.json'
    f.write_text(json.dumps(r))
    assert cli.main(['web', 'smooth', '--samples', str(f)]) == 1
    out = capsys.readouterr().out
    assert 'FAILED' in out and 'stepped back' in out and 'records late' in out and 'past their newest pass' in out
    g = tmp_path / 'list.json'
    g.write_text(json.dumps([[1000 + i * 16.667, [0, 0], [[1, 40 + 2.5 * i, 50]], 0, 0] for i in range(200)]))
    assert cli.main(['web', 'smooth', '--samples', str(g), '--json']) == 0
    res = json.loads(capsys.readouterr().out)
    assert res[str(g)]['passed'] and res[str(g)]['obj_back'] == 0 and res[str(g)]['obj_moving'] > 100
