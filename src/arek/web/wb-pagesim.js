// wb-pagesim.js 1.0 (kit 1.0.78) - the page's loop without a browser (amiga-re-kit, docs/WB-PLYNULOST.md 2.16). Node and the page alike.
// The clock (wb-takt) grants frames as it does in the page, an engine model computes them in turn (ms a frame as a parameter:
// an engine thread in a browser is slower than in Node - SWIV measured 14-16 ms a game frame in Chromium, 4-6 ms in Node), the
// page's own feed() turns every finished frame into wb-scene's record at the display frame it would reach the page, and
// wb-scene's compose() draws every display frame. The samples are WBLONGRUN's ([ts, cam, objs, missing, ahead]), so
// `arek web smooth --samples FILE` judges them with the browser's measure. Taken from SWIV's tools/m9/page_sim.js, whose
// simulation of a browser run (the same game, its records at the same display frames) put 48 386 object positions where
// the browser had them, 0 apart. An offline composition that has every record at its own time is not this: a page never
// has a record before the engine has computed it.
//   const r = WBPAGESIM.run({ WBTAKT, WBSCENE, from, count, feed, takt: { fps, ahead, latC, latO, horizon }, scene: { ...wb-scene's
//       options }, view: { W, H, S }, hz: 60, engine: 5 | [4, 16] | (k, rnd) => ms, spike: [probability, ms] });
//   feed(n, takt) -> the record of game frame n as the page makes it (its t from takt.stamp(), its pass, takt.pass() on a new
//       pass, rec.next - the page's feedScene), or null (none: the run of records starts again). It is called once per n in
//       order when the engine has finished frame n (done > n), the frames older than done - skip (24) left out as the page does.
//   r = { samples, shown, extrapolated (display frames whose objects ran past their newest pass), lost (record times more
//       than 1.5 frames apart), late: [median, max] ms (a record's arrival after its time, wb-takt 1.7), version }
// Options: msgMs (2: allow -> the engine starts), warm (240 display frames before the first sample: the clock measures the
// display), minRun (4 records before composing), keep (32 records in the list), seed, t0 (1000 ms), objs(c) -> the samples'
// objects (default every composed object [id, x, y], as a page's WBLONGRUN.objs() over scene.last). The order within a display
// frame is the page's: the engine's progress, feed, compose, takt.tick(ts, done). No game data.
'use strict';
(function (root) {
    const VERSION = '1.0';
    function run(o) {
        const T = o.WBTAKT, S = o.WBSCENE, F = o.from | 0, N = o.count | 0, HZ = o.hz || 60, msg = o.msgMs != null ? o.msgMs : 2;
        const keep = o.keep || 32, minRun = o.minRun || 4, warm = o.warm != null ? o.warm : 240, skip = o.skip || 24;
        let seed = o.seed || 12345;
        const rnd = () => { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return seed / 0x7fffffff; };
        const eng = o.engine === undefined ? 5 : o.engine;
        const cost = (k) => { let x = typeof eng === 'function' ? eng(k, rnd) : Array.isArray(eng) ? eng[0] + rnd() * (eng[1] - eng[0]) : eng;
            if (o.spike && rnd() < o.spike[0]) x += o.spike[1]; return x; };
        let now = 0, permit = F, done = F, lastComp = 0;
        const grant = new Map(), comp = new Map();
        const takt = T.create(Object.assign({ fps: 50 }, o.takt || {}, { now: () => now,
            allow: (g) => { for (let k = permit + 1; k <= g; k++) grant.set(k, now + msg); permit = Math.max(permit, g); } }));
        takt.reset(F);
        const opts = Object.assign({}, o.scene || {}), view = Object.assign({ W: 320, H: 200, S: 1, extX: 0, extY: 0 }, o.view || {});
        const objsOf = o.objs || ((c) => c.objs.map((ob) => [ob.o.id, ob.x, ob.y]));
        const frames = [], samples = [], late = [];
        let fed = F - 1, valid = 0, shown = 0, ext = 0, lost = 0, lastT = 0;
        const t0 = o.t0 != null ? o.t0 : 1000, cap = warm + 4 * N * HZ / 50 + 1000;
        for (let i = 0; fed < F + N - 1 && i < cap; i++) {
            const ts = t0 + i * 1000 / HZ; now = ts;
            for (let k = done + 1; k <= permit; k++) {                                // the engine: frame k starts at its permit or after k - 1
                if (!comp.has(k)) { lastComp = Math.max(lastComp, grant.get(k)) + cost(k); comp.set(k, lastComp); }
                if (comp.get(k) <= ts) done = k; else break;
            }
            for (let n = Math.max(fed + 1, done - skip); n < done && n < F + N; n++) {   // the page's feedScene
                fed = n; const rec = o.feed(n, takt);
                if (!rec) { valid = 0; frames.length = 0; continue; }
                if (lastT && rec.t - lastT > 1.5 * takt.fm()) lost++;
                lastT = rec.t; late.push(ts - rec.t);
                frames.push(rec); if (frames.length > keep) frames.shift(); valid++;
            }
            if (i > warm && valid >= minRun && frames.length > 1) {
                const c = S.compose(frames, ts, view, opts, takt);
                if (c) { shown++; if (c.of > 1 + 1e-4) ext++; samples.push([ts, c.cam.slice(), objsOf(c), takt.missing, takt.stats().ahead]); }
            }
            takt.tick(ts, done, false);
        }
        const s = late.slice().sort((a, b) => a - b);
        return { version: VERSION, samples, shown, extrapolated: ext, lost, late: s.length ? [+s[s.length >> 1].toFixed(1), +s[s.length - 1].toFixed(1)] : null };
    }
    const api = { VERSION, run };
    if (typeof module !== 'undefined') module.exports = api; else root.WBPAGESIM = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
