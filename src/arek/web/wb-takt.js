// wb-takt.js 1.2 - the clock of a rebuild's page (amiga-re-kit, docs/WB-PLYNULOST.md, module C). Extracted from
// the Alien Breed II page (tools/web/main.js: PACE, pump, loopIn) and Superfrog's (web/main.js, web/worker.js):
//   - the game's clock comes from requestAnimationFrame: frames of the game are allowed up to "now + one frame", at
//     most `ahead` beyond what the engine has done; on a display of k x 50 Hz (within 0.6 Hz) exactly one game frame
//     per k display frames (the lock), otherwise the game's own 50 Hz with interpolation between frames;
//   - the timeline: every game frame gets a time (the permit's nominal time); a frame made without a permit (a busy
//     scene makes several in one run, a thread runs ahead for the sound) gets the previous time + one frame and the
//     clock continues behind it (the old time from a ring was Alien Breed II's stutter);
//   - the picture is drawn behind the game: the camera and the sprites by latC (30 ms; 20 with an engine in a thread),
//     the objects by latO (60 ms, adaptive up to 120 after the lengths of the drawing passes) so the next frame / pass
//     for the interpolation is there; without it the pair's fraction runs past 1 from the previous pair (extrapolation);
//   - the keys reach the game at the event, not at the next display frame (keyboard()).
// The page owns the engine: it gives allow(n) (let the game run to frame n) and reads the frames it made; the module
// gives the permits, the times and the pairs for the interpolation. No game data.
//   const takt = WBTAKT.create({ fps: 50, ahead: 2, latC: 30, latO: 60, lock: 'auto', allow: (n) => engine.allow(n) });
//   rAF loop: takt.tick(ts, engine.done(), paused); for every new frame n: f.t = takt.stamp(n); takt.pass(t) when a
//   drawing pass completes; const { tv, tvO } = takt.view(ts); const p = takt.pair(frames, tv); camera = lerp(p.a, p.b, p.f)
//   takt.stats() -> { hz, k, fm, granted, ahead, missing, latC, latO } for the page's WBLONGRUN hooks.
'use strict';
const WBTAKT = (() => {
    const VERSION = '1.2';
    const nowMs = () => (typeof performance !== 'undefined' ? performance.now() : Date.now());
    /** The display's rate from the last intervals: the median (Hz), 0 before 60 samples. */
    function medianHz(dts) {
        if (dts.length < 60) return 0;
        const s = [...dts].sort((a, b) => a - b);
        return 1000 / s[s.length >> 1];
    }
    /** The lock: k display frames per game frame when the display is k x fps within 0.6 Hz (k = 1..4), else 0. */
    function lockOf(hz, fps) {
        if (!hz) return 0;
        for (let j = 1; j <= 4; j++) if (Math.abs(hz / j - fps) < 0.6) return j;
        return 0;
    }
    class Takt {
        constructor(o) {
            o = o || {};
            this.fps = o.fps || 50; this.ahead = o.ahead || 2; this.LATC = o.latC != null ? o.latC : 30;
            this.LATO = o.latO != null ? o.latO : 60; this.latOMax = o.latOMax || 120; this.lock = o.lock || 'auto';
            this.allow = o.allow || (() => {}); this.extrap = !!o.extrapolate;
            this.dts = []; this.last = 0; this.cnt = 0; this.hz = 0; this.k = 0;
            this.clock = 0; this.granted = 0; this.tg = new Float64Array(256); this.tgN = new Int32Array(256).fill(-1); this.lastT = 0;
            this.latO = this.LATO; this.lens = []; this.lastPass = -1; this.missing = 0; this.granting = 0;
        }
        /** The display's interval (ms) of one game frame: locked k / hz, else 1000 / fps. */
        fm() { return this.k ? 1000 * this.k / this.hz : 1000 / this.fps; }
        /** Every display frame: measure the display, then (unless paused) grant frames up to now + one frame. */
        tick(ts, done, paused) {
            if (this.last) { const d = ts - this.last; if (d > 3 && d < 45) { this.dts.push(d); if (this.dts.length > 120) this.dts.shift(); } }
            this.last = ts; this.cnt++;
            if (this.dts.length >= 60 && this.cnt % 30 === 0) {
                this.hz = medianHz(this.dts);
                const k = this.lock === 'off' ? 0 : this.lock === 'on' ? 1 : lockOf(this.hz, this.fps);
                if (k !== this.k) { this.k = k; this.clock = 0; }
            }
            const FM = this.fm();
            if (paused) { this.clock = 0; return { granted: this.granted, fm: FM, k: this.k }; }
            if (!this.clock || ts - this.clock > 5 * FM) this.clock = ts;              // start, after a pause, a slow machine: from now
            let g = Math.max(this.granted, done);
            if (done > this.granted && this.lastT + FM > this.clock) this.clock = this.lastT + FM;   // the game ran past the permits: continue behind it
            while (this.clock <= ts + FM) {
                if (g < done + this.ahead) { g++; this.tg[g & 255] = this.clock; this.tgN[g & 255] = g; }
                this.clock += FM;
            }
            if (g > this.granted) { this.granted = g; this.granting++; this.allow(g); }
            return { granted: this.granted, fm: FM, k: this.k };
        }
        /** The time (ms) of game frame n as the page takes it from the engine: its permit's time, or the previous
         *  frame's + one frame when it was made without a permit; never earlier than the previous. */
        stamp(n) {
            const ix = n & 255;
            let t = this.tgN[ix] === n ? this.tg[ix] : (this.lastT ? this.lastT + this.fm() : nowMs());
            if (this.lastT && t < this.lastT + 1) t = this.lastT + 1;
            this.lastT = t;
            return t;
        }
        /** A drawing pass of the objects completed at time t (ms, the frame's time): its length feeds latO. 1.2 (Alien Breed
         *  II): a record of an older pass after a newer one (once in ~1500 frames in a browser) is not taken - a small
         *  step back is ignored (returns false), a big one (over 1 s: a new level, a restart) starts the axis anew. */
        pass(t) {
            if (this.lastPass >= 0 && t <= this.lastPass) {
                if (this.lastPass - t < 1000) return false;
                this.lens = []; this.lastPass = -1;
            }
            if (this.lastPass >= 0) { this.lens.push(t - this.lastPass); if (this.lens.length > 16) this.lens.shift(); }
            this.lastPass = t;
            return true;
        }
        /** The display times of this frame: the camera / sprites tv = ts - latC, the objects tvO = ts - latO (adaptive:
         *  the longest of the last 16 passes - the game's lead + 8 ms, within latO..latOMax, up 1 ms / down 0.1 ms per
         *  display frame; fixed when the engine extrapolates); under the lock the camera is one frame less 2 ms behind. */
        view(ts, newest) {
            const FM = this.fm();
            if (!this.extrap && this.lens.length) {
                const nw = newest != null ? newest : (this.lastT || ts);
                const target = Math.min(this.latOMax, Math.max(this.LATO, Math.max(...this.lens) - (nw - ts) + 8)), d = target - this.latO;
                this.latO += d > 0 ? Math.min(1, d) : Math.max(-0.1, d);
            } else this.latO = this.LATO;
            const latC = this.k ? FM - 2 : this.LATC, latO = this.k ? Math.max(this.latO, 2 * FM - 2) : this.latO;
            return { tv: ts - latC, tvO: ts - latO, latC, latO };
        }
        /** The pair around time t in `list` (objects with .t ascending): { a, b, f } with f in 0..1; without the next
         *  one, extrapolate from the previous pair (f up to 2, ext: true) when allowed, else the last one alone
         *  (f 0, missing: true - counted). */
        pair(list, t, extrapolate) {
            let i = -1;
            for (let j = list.length - 1; j >= 0; j--) if (list[j].t <= t) { i = j; break; }
            if (i < 0) return list.length ? { a: list[0], b: null, f: 0, missing: false } : null;
            const a = list[i], b = list[i + 1] || null;
            if (b && b.t > a.t) return { a, b, f: Math.min(1, Math.max(0, (t - a.t) / (b.t - a.t))) };
            const p = list[i - 1];
            if ((extrapolate != null ? extrapolate : this.extrap) && p && a.t > p.t)
                return { a: p, b: a, f: 1 + Math.min(1, Math.max(0, (t - a.t) / (a.t - p.t))), ext: true };
            this.missing++;
            return { a, b: null, f: 0, missing: true };
        }
        /** A restart, a jump or the end of frames the page allowed outside the clock (a jump to a level: allow(done + 24)):
         *  the timeline from zero and the permit taken back to `done` (allow(done)), so frames computed beyond it do not
         *  get times now + n frames and keep the timeline ahead for good (Alien Breed II: 140-172 ms of lead, the keys
         *  that much later). The page skips the frames it has not shown (its read position = done). */
        reset(done) {
            done = done || 0;
            this.clock = 0; this.granted = done; this.lastT = 0; this.tgN.fill(-1); this.lens = []; this.lastPass = -1; this.latO = this.LATO; this.missing = 0;
            this.allow(done);
        }
        stats() {
            return { version: VERSION, hz: this.hz ? +this.hz.toFixed(2) : 0, k: this.k, fm: +this.fm().toFixed(3), granted: this.granted,
                     ahead: this.lastT ? this.lastT - nowMs() : 0, missing: this.missing, latC: this.k ? this.fm() - 2 : this.LATC, latO: this.latO };
        }
    }
    /** The keys as bits, changed at the event: map = { KeyCode: bit }; onchange(bits) runs at once (the game takes
     *  them in its next frame, not the next display frame). Returns { bits(), dispose() }. */
    function keyboard(target, map, onchange) {
        let bits = 0;
        const down = (e) => { const b = map[e.code]; if (!b) return; if (!(bits & b)) { bits |= b; if (onchange) onchange(bits); } e.preventDefault(); };
        const up = (e) => { const b = map[e.code]; if (!b) return; if (bits & b) { bits &= ~b; if (onchange) onchange(bits); } };
        const blur = () => { if (bits) { bits = 0; if (onchange) onchange(0); } };
        target.addEventListener('keydown', down); target.addEventListener('keyup', up); target.addEventListener('blur', blur);
        return { bits: () => bits, dispose() { target.removeEventListener('keydown', down); target.removeEventListener('keyup', up); target.removeEventListener('blur', blur); } };
    }
    return { VERSION, medianHz, lockOf, Takt, create: (o) => new Takt(o), keyboard };
})();
if (typeof globalThis !== 'undefined') globalThis.WBTAKT = WBTAKT;
if (typeof module !== 'undefined') module.exports = WBTAKT;
