"""wb-takt.js (the canon's clock, module C): its permits, timeline, pairs, lock and keyboard in Node; the page
side runs in `arek web smooth` over smooth-demo.html."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from arek import web

WEB = Path(web.__file__).parent
node = shutil.which('node')


def js(expr):
    if not node:
        pytest.skip('no node')
    code = "const T = require(%s); const r = (%s); console.log(JSON.stringify(r));" % (json.dumps(str(WEB / 'wb-takt.js')), expr)
    return json.loads(subprocess.run([node, '-e', code], capture_output=True, text=True, check=True).stdout)


def test_lock_and_rate():
    assert js('T.VERSION') == '1.4' and 'wb-takt.js' in web.FILES
    assert js('[60, 100.3, 49.9, 150, 144, 200.5, 0].map((h) => T.lockOf(h, 50))') == [0, 2, 1, 3, 0, 4, 0]
    assert js('T.medianHz(Array(59).fill(16.7))') == 0 and abs(js('T.medianHz(Array(60).fill(16.667))') - 60) < 0.01


def test_permits_timeline_and_pairs():
    r = js("""(() => { const allowed = []; const t = T.create({ allow: (n) => allowed.push(n) }); let done = 0, ts = 1000; const g = [];
        for (let i = 0; i < 6; i++) { const r = t.tick(ts, done, false); g.push(r.granted); while (done < r.granted) { done++; t.stamp(done); } ts += 16.667; }
        const stamps = [t.stamp(done + 1), t.stamp(done + 2)];                       // frames without a permit: the previous + one frame
        const paused = t.tick(ts, done + 2, true).granted;
        return { g, allowed, lastT: t.lastT, stamps, paused, fm: t.fm() }; })()""")
    assert r['g'] == [2, 2, 3, 4, 5, 6] and r['allowed'] == [2, 3, 4, 5, 6] and r['fm'] == 20
    assert r['stamps'][1] - r['stamps'][0] == 20 and r['paused'] == 6
    p = js("""(() => { const t = T.create({}); const L = [{t: 1000}, {t: 1020}, {t: 1040}];
        return [t.pair(L, 1030), t.pair(L, 1050, true), t.pair(L, 1050, false), t.pair(L, 990), t.missing, t.pair([], 5)]; })()""")
    assert p[0] == {'a': {'t': 1020}, 'b': {'t': 1040}, 'f': 0.5}
    assert p[1] == {'a': {'t': 1020}, 'b': {'t': 1040}, 'f': 1.5, 'ext': True}
    assert p[2] == {'a': {'t': 1040}, 'b': None, 'f': 0, 'missing': True} and p[4] == 1
    assert p[3]['a'] == {'t': 1000} and p[3]['b'] is None and p[5] is None


def test_view_lag_adapts_and_lock_changes_it():
    r = js("""(() => { const t = T.create({ latC: 30, latO: 60, latOMax: 120 }); const v0 = t.view(1000, 1000);
        for (const x of [1000, 1080, 1160, 1240]) t.pass(x);                         // passes 80 ms apart: latO climbs 1 ms a frame towards 88 - lead + 8
        const steps = []; for (let i = 0; i < 40; i++) steps.push(t.view(1240 + i * 16, 1240 + i * 16).latO);
        t.hz = 100; t.k = 2; const locked = t.view(5000, 5000);
        return { v0: [v0.latC, v0.latO, v0.tv, v0.tvO], steps: steps.slice(0, 3), last: steps[39], locked: [locked.latC, locked.latO] }; })()""")
    assert r['v0'] == [30, 60, 970, 940] and r['steps'] == [61, 62, 63] and 85 <= r['last'] <= 88
    assert r['locked'] == [18, 88]                                                  # under the lock: a frame (20 ms) less 2, objects >= 2 frames - 2
    s = js("(() => { const t = T.create({}); t.hz = 59.94; t.reset(7); return [t.granted, t.lastT, t.stats().k, t.stats().fm]; })()")
    assert s == [7, 0, 0, 20]
    # 1.1: frames allowed outside the clock (a jump: allow(done + 24)) - reset takes the permit back to done and the next
    # frames get times from the clock again, not now + n frames (Alien Breed II)
    r = js("""(() => { const allowed = []; const t = T.create({ allow: (n) => allowed.push(n) });
        t.allow(30 + 24); t.reset(30); const back = allowed[allowed.length - 1];
        const g = t.tick(5000, 30, false).granted; const t31 = t.stamp(31);
        return [back, g, t31]; })()""")
    assert r[0] == 30 and r[1] == 32 and r[2] == 5000


def test_fixed_latency_by_default_and_the_clock_under_skips_pauses_and_overruns():
    """1.3: latO is fixed (40) unless latOMax is above it; two game frames in one slow display frame get permit times a frame
    apart; a lock switch restarts the clock with the locked interval; after a pause the clock starts from now; when the
    game ran past the permits the clock continues behind it."""
    r = js("""(() => { const t = T.create({}); for (const x of [1000, 1080, 1160, 1240]) t.pass(x); const v = []; for (let i = 0; i < 10; i++) v.push(t.view(1240 + i * 16, 1240 + i * 16).latO);
        return [t.LATO, t.latOMax, v[0], v[9]]; })()""")
    assert r == [40, 40, 40, 40]
    r = js("""(() => { const t = T.create({}); let done = 0; const g = t.tick(1000, 0, false).granted; const s = []; while (done < g) { done++; s.push(t.stamp(done)); }
        const slow = t.tick(1000 + 50, done, false).granted; const s2 = []; while (done < slow) { done++; s2.push(t.stamp(done)); }
        return [g, s, slow, s2]; })()""")
    assert r[0] == 2 and r[1] == [1000, 1020] and r[2] == 4 and r[3] == [1040, 1060]              # 50 ms later: two frames, a frame apart on the grid
    r = js("""(() => { const t = T.create({}); let ts = 1000; for (let i = 0; i < 90; i++) { t.tick(ts, 0, true); ts += 10; } const a = [t.hz, t.k, t.fm(), t.clock];
        for (let i = 0; i < 150; i++) { t.tick(ts, 0, true); ts += 16.667; } return [a, [Math.round(t.hz), t.k, t.fm()]]; })()""")
    assert r[0] == [100, 2, 20, 0] and r[1] == [60, 0, 20]                                         # 100 Hz: locked k = 2, the clock restarted; 60 Hz: unlocked
    r = js("""(() => { const t = T.create({}); let done = 0; const g = t.tick(1000, 0, false).granted; while (done < g) { done++; t.stamp(done); }
        t.tick(1016, done, true); const g2 = t.tick(5000, done, false).granted; const s3 = t.stamp(done + 1); return [g, g2, s3]; })()""")
    assert r == [2, 4, 5000]                                                                       # after the pause the next frame's time is now, not the old timeline
    r = js("""(() => { const t = T.create({ ahead: 2 }); let done = 0; const g = t.tick(1000, 0, false).granted; while (done < g) { done++; t.stamp(done); }
        const free = [t.stamp(3), t.stamp(4), t.stamp(5)]; done = 5;                           // three frames made without a permit (the sound's reserve)
        const g2 = t.tick(1016, done, false).granted; const s6 = t.stamp(6); return [free, g2, s6, t.clock]; })()""")
    assert r[0] == [1040, 1060, 1080] and r[1] == 5 and r[2] == 1100 and r[3] == 1100            # the game is ahead of the display: no new permit yet, the clock continues behind it (frame 6 at 1100)
    r = js("""(() => { const t = T.create({}); const g = t.tick(1000, 0, false).granted; const a = [t.timeOf(1), t.timeOf(2), t.timeOf(3), t.lastT]; t.stamp(1); return [g, a, t.timeOf(1), t.lastT]; })()""")
    assert r == [2, [1000, 1020, None, 0], 1000, 1000]                                            # 1.3.1: timeOf reads the permit's time without moving the timeline
    r = js("""(() => { const out = []; for (const h of ['display', 'game', 12]) { const t = T.create({ horizon: h }); t.hz = 144; out.push([t.tick(1000, 0, false).granted, +t.horizonMs().toFixed(2)]); }
        const u = T.create({}); out.push([u.tick(1000, 0, false).granted, u.horizonMs()]); return out; })()""")
    assert r == [[1, 8.94], [2, 20], [1, 12], [2, 20]]                                          # 1.4 (G57): at 144 Hz a frame is granted a display frame + 2 ms ahead, not a game frame; unmeasured display = a game frame


def test_keyboard_changes_bits_at_the_event():
    r = js("""(() => { const H = {}; const target = { addEventListener: (k, f) => { H[k] = f; }, removeEventListener: () => {} };
        const seen = []; const kb = T.keyboard(target, { ArrowRight: 1, ArrowLeft: 2 }, (b) => seen.push(b));
        const ev = (code) => ({ code, preventDefault() {} });
        H.keydown(ev('ArrowRight')); H.keydown(ev('ArrowRight')); H.keydown(ev('ArrowLeft')); H.keyup(ev('ArrowRight')); H.keydown(ev('KeyX')); H.blur();
        return [seen, kb.bits()]; })()""")
    assert r == [[1, 3, 2, 0], 0]


def test_pass_ignores_an_older_record():
    """1.2 (Alien Breed II): an older pass after a newer one is not taken; a big step back restarts the axis."""
    r = js("""(() => { const t = T.create({}); const a = [t.pass(1000), t.pass(1080), t.pass(1060), t.pass(1160)];
        const lens = t.lens.slice(); const b = t.pass(100); return [a, lens, b, t.lens.length, t.lastPass]; })()""")
    assert r == [[True, True, False, True], [80, 80], True, 0, 100]
