// wb-zvuk.js - reference implementation of the sound contract "wb-shell zvuk 1.1" (amiga-re-kit, WB-ZVUK.md).
// One mixing rule for the stereo width, gain changes that ramp (no clicks), the Amiga 500's output filters, and
// test hooks for `arek web test` (§6). No game data. Works as a <script> (global WBZVUK, globalThis.WBZVUK),
// as CommonJS and in Node for the pure parts (mix, coefficients).
//
//   const z = WBZVUK.chain(audioCtx);            // input -> high-pass -> fixed low-pass -> LED low-pass -> width -> volume -> destination
//   z.input.connect-from your source; WBZVUK.apply(z, { on, volume, stereo, filterFixed, filterLed, filterHp }, led)
//
// Stereo width w = stereo / 100: l' = l*(1+w)/2 + r*(1-w)/2, r' = r*(1+w)/2 + l*(1-w)/2 (100 % = as the Amiga,
// 0 % = mono). Every gain change ramps linearly over RAMP_MS. Filter values are the Amiga 500's from the schematic
// (FILTERS, with the digital forms the contract prescribes); a game may pass its own in opts.filters.
//
// Test hooks a page provides (§6): window.wbZvukTest.render(settings) -> {l: [...], r: [...]} - the page's fixed
// test signal (wbZvukTest.signal()) through a chain built with `settings` in an OfflineAudioContext; WBZVUK.render
// does that for a page that keeps its chain to the reference.
'use strict';
const WBZVUK = (() => {
    const VERSION = '1.1';
    const RAMP_MS = 20;
    // Amiga 500 output stage from the schematic (Superfrog, after pt2-clone): the fixed one-pole RC low-pass
    // R321 360 ohm / C321 0.1 uF = 4420.97 Hz; the "LED" filter, a unity-gain Sallen-Key with R322 = R323 = 10 k,
    // C322 6800 pF, C323 3900 pF = 3090.53 Hz, Q 0.660225 (on while CIA-A PRA bit 1 is 0, the power LED bright);
    // the output coupling, a one-pole high-pass (R324 + R325) 1390 ohm / C334 22 uF = 5.2041 Hz. The analog output
    // is not measured; the stages are linear, so their order does not matter. Digital form (WB-ZVUK.md §4): one pole
    // low y += a(x - y), a = 1 - exp(-2 pi f / fs); one pole high y = r(y1 + x - x1), r = exp(-2 pi f / fs); the LED
    // stage an RBJ low-pass biquad (bilinear) with that f0 and Q. Every game uses these forms so the tests agree.
    const FILTERS = { fixed: { hz: 4420.97, order: 1 }, led: { hz: 3090.53, order: 2, q: 0.660225 }, hp: { hz: 5.2041, order: 1 } };
    const DEFAULTS = { on: true, volume: 80, stereo: 100, filterFixed: true, filterLed: 'auto', filterHp: true };

    /** The width gains: l' = l*a + r*b, r' = r*a + l*b. */
    function gains(stereo) {
        const w = Math.min(1, Math.max(0, (typeof stereo === 'number' ? stereo : 100) / 100));
        return { a: (1 + w) / 2, b: (1 - w) / 2 };
    }
    function mix(l, r, stereo) {
        const { a, b } = gains(stereo);
        return [l * a + r * b, r * a + l * b];
    }
    /** Two arrays through the mix (tests, offline paths). */
    function mixArrays(l, r, stereo) {
        const { a, b } = gains(stereo), n = Math.min(l.length, r.length), ol = new Float32Array(n), or = new Float32Array(n);
        for (let i = 0; i < n; i++) { ol[i] = l[i] * a + r[i] * b; or[i] = r[i] * a + l[i] * b; }
        return [ol, or];
    }
    /** One-pole low-pass y += a (x - y), a = 1 - exp(-2 pi f / fs), as IIRFilterNode feedforward/feedback arrays. */
    function onePoleLow(hz, sr) {
        const a = 1 - Math.exp(-2 * Math.PI * hz / sr);
        return { feedforward: [a], feedback: [1, -(1 - a)] };
    }
    /** One-pole high-pass y = r (y1 + x - x1), r = exp(-2 pi f / fs). */
    function onePoleHigh(hz, sr) {
        const r = Math.exp(-2 * Math.PI * hz / sr);
        return { feedforward: [r, -r], feedback: [1, -r] };
    }
    /** Second-order low-pass (RBJ cookbook), normalised so a0 = 1. */
    function biquadLow(hz, q, sr) {
        const w0 = 2 * Math.PI * hz / sr, cw = Math.cos(w0), sw = Math.sin(w0), al = sw / (2 * q);
        const b0 = (1 - cw) / 2, b1 = 1 - cw, b2 = (1 - cw) / 2, a0 = 1 + al, a1 = -2 * cw, a2 = 1 - al;
        return { feedforward: [b0 / a0, b1 / a0, b2 / a0], feedback: [1, a1 / a0, a2 / a0] };
    }
    /** Coefficients of the three filters for a sample rate; opts.filters overrides {fixed, led, hp}. */
    function coefficients(sr, opts) {
        const f = Object.assign({}, FILTERS, (opts && opts.filters) || {});
        return { fixed: onePoleLow(f.fixed.hz, sr), led: biquadLow(f.led.hz, f.led.q || Math.SQRT1_2, sr), hp: onePoleHigh(f.hp.hz, sr) };
    }
    /** Run one IIR filter over an array (tests, offline paths): y = sum ff[i]*x[n-i] - sum fb[i]*y[n-i], i >= 1 for fb. */
    function iir(x, c) {
        const ff = c.feedforward, fb = c.feedback, y = new Float32Array(x.length);
        for (let n = 0; n < x.length; n++) {
            let v = 0;
            for (let i = 0; i < ff.length; i++) if (n - i >= 0) v += ff[i] * x[n - i];
            for (let i = 1; i < fb.length; i++) if (n - i >= 0) v -= fb[i] * y[n - i];
            y[n] = v;
        }
        return y;
    }
    /** The whole contract offline on arrays: settings as apply() takes them, led = the game's LED bit (true = filter on). */
    function process(l, r, settings, led, sr, opts) {
        const s = Object.assign({}, DEFAULTS, settings || {}), c = coefficients(sr || 44100, opts);
        let a = Float32Array.from(l), b = Float32Array.from(r);
        if (!s.on) return [new Float32Array(a.length), new Float32Array(b.length)];
        if (s.filterHp) { a = iir(a, c.hp); b = iir(b, c.hp); }
        if (s.filterFixed) { a = iir(a, c.fixed); b = iir(b, c.fixed); }
        const ledOn = s.filterLed === 'on' || (s.filterLed === 'auto' && !!led);
        if (ledOn) { a = iir(a, c.led); b = iir(b, c.led); }
        const [ml, mr] = mixArrays(a, b, s.stereo), v = Math.min(1, Math.max(0, s.volume / 100));
        for (let i = 0; i < ml.length; i++) { ml[i] *= v; mr[i] *= v; }
        return [ml, mr];
    }

    /** Web Audio: input -> hp -> fixed -> led -> width (4 gains) -> volume -> ctx.destination (or opts.out). */
    function chain(ctx, opts) {
        const sr = ctx.sampleRate, c = coefficients(sr, opts), mk = (co) => ctx.createIIRFilter(co.feedforward, co.feedback);
        const input = ctx.createGain(), hp = mk(c.hp), fixed = mk(c.fixed), led = mk(c.led);
        const bypassHp = ctx.createGain(), bypassFixed = ctx.createGain(), bypassLed = ctx.createGain();
        const gHp = ctx.createGain(), gFixed = ctx.createGain(), gLed = ctx.createGain();
        const split = ctx.createChannelSplitter(2), merge = ctx.createChannelMerger(2);
        const ll = ctx.createGain(), lr = ctx.createGain(), rl = ctx.createGain(), rr = ctx.createGain();
        const volume = ctx.createGain(), out = (opts && opts.out) || ctx.destination;
        // each filter stage: wet (filter -> g) + dry (bypass), one of the two gains is 0
        const stage = (from, filt, g, bypass) => { from.connect(filt); filt.connect(g); from.connect(bypass); const sum = ctx.createGain(); g.connect(sum); bypass.connect(sum); return sum; };
        const s1 = stage(input, hp, gHp, bypassHp), s2 = stage(s1, fixed, gFixed, bypassFixed), s3 = stage(s2, led, gLed, bypassLed);
        s3.connect(split);
        split.connect(ll, 0); split.connect(lr, 0); split.connect(rl, 1); split.connect(rr, 1);
        ll.connect(merge, 0, 0); rl.connect(merge, 0, 0); rr.connect(merge, 0, 1); lr.connect(merge, 0, 1);
        merge.connect(volume); volume.connect(out);
        const z = { ctx, input, volume, width: { ll, lr, rl, rr }, stages: { hp: [gHp, bypassHp], fixed: [gFixed, bypassFixed], led: [gLed, bypassLed] }, settings: Object.assign({}, DEFAULTS), led: false };
        apply(z, DEFAULTS, false, 0);
        return z;
    }
    function ramp(param, value, ctx, ms) {
        const t = ctx.currentTime;
        param.cancelScheduledValues(t);
        if (!ms) { param.setValueAtTime(value, t); return; }
        param.setValueAtTime(param.value, t);
        param.linearRampToValueAtTime(value, t + ms / 1000);
    }
    /** Apply settings {on, volume, stereo, filterFixed, filterLed ('auto'|'on'|'off'), filterHp}; led = true when the game's
     *  filter is on (CIA-A PRA bit 1 = 0, the power LED bright). */
    function apply(z, settings, led, ms) {
        const s = Object.assign(z.settings, settings || {}), r = (p, v) => ramp(p, v, z.ctx, ms === undefined ? RAMP_MS : ms);
        z.led = !!led;
        const { a, b } = gains(s.stereo);
        r(z.width.ll.gain, a); r(z.width.rr.gain, a); r(z.width.lr.gain, b); r(z.width.rl.gain, b);
        r(z.volume.gain, s.on ? Math.min(1, Math.max(0, s.volume / 100)) : 0);
        const on = (name, wet) => { r(z.stages[name][0].gain, wet ? 1 : 0); r(z.stages[name][1].gain, wet ? 0 : 1); };
        on('hp', !!s.filterHp); on('fixed', !!s.filterFixed);
        on('led', s.filterLed === 'on' || (s.filterLed === 'auto' && z.led));
        return s;
    }
    /** The page's test hook body: `signal` {l, r} through a chain built with `settings` in an OfflineAudioContext. */
    function render(settings, led, signal, sr, opts) {
        const n = signal.l.length, ctx = new OfflineAudioContext(2, n, sr || 44100);
        const buf = ctx.createBuffer(2, n, ctx.sampleRate);
        buf.copyToChannel(Float32Array.from(signal.l), 0); buf.copyToChannel(Float32Array.from(signal.r), 1);
        const src = ctx.createBufferSource(); src.buffer = buf;
        const z = chain(ctx, opts); src.connect(z.input); apply(z, settings, led, 0); src.start();
        return ctx.startRendering().then((out) => ({ l: Array.from(out.getChannelData(0)), r: Array.from(out.getChannelData(1)) }));
    }
    /** A fixed stereo test signal: a left ramp, a right tone, a shared pulse - so width, volume and filters all show. */
    function testSignal(n, sr) {
        n = n || 4096; sr = sr || 44100;
        const l = new Float32Array(n), r = new Float32Array(n);
        for (let i = 0; i < n; i++) {
            const t = i / sr;
            l[i] = 0.5 * ((i % 256) / 256 - 0.5) + (i % 1024 < 8 ? 0.4 : 0);
            r[i] = 0.4 * Math.sin(2 * Math.PI * 440 * t) + (i % 1024 < 8 ? 0.4 : 0);
        }
        return { l, r };
    }
    return { VERSION, RAMP_MS, FILTERS, DEFAULTS, gains, mix, mixArrays, onePoleLow, onePoleHigh, biquadLow, coefficients, iir, process,
             chain, apply, render, testSignal };
})();
if (typeof globalThis !== 'undefined') globalThis.WBZVUK = WBZVUK;
if (typeof module !== 'undefined') module.exports = WBZVUK;
