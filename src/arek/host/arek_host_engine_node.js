// arek_host_engine_node.js 1.0 - the engine of a page (arek host engine, engine.js or engine_mt.js) driven from Node for
// measurements (amiga-re-kit 1.0.20): one loader, one synthetic start state, one schedule of keys and events at exact
// game frames, one hang guard - what the Turrican II rebuild wrote ten times over in its tools. No game data: the state,
// the disks and the addresses come from the caller.
//
//   const H = require('./lib/arek_host_engine_node.js');
//   const eng = await H.open('build/web/out', { state: H.synthState({ sr: 0x2000, entry: 0x1246, time: 39601, frame: 2645 }),
//                                              disks: ['local/disk1.adf', 'local/disk2.adf'] });
//   eng.schedule('300:16,310:0,1000:1');               // keys from frame f on (R 1 L 2 U 4 D 8 F 16), as the page's events
//   eng.at(1, () => eng.poke8(0xc7fff0, 1));           // an event after frame 1 is done, before frame 2 runs
//   await eng.run(2500, (f) => { if (f % 500 === 0) console.log(f, eng.hash()); });
//   eng.peek16(0x17e); eng.pix(); eng.dump(0, 0x80000); eng.hash();
//
// open(dir, { state, disks, name, hang }): state = a path, a Uint8Array (synthState) or nothing (init later); disks = paths
// or buffers in drive order; name = 'engine' / 'engine_mt' (found by itself); hang = ms without progress before run()
// throws ({ code: 'hung', frame }); an engine_error throws ({ code: 'error', addr }).
// synthState({ d, a, sr, time, intreq, entry, pra, sdr, icr, joy0, joy1, pot, frame, chip, slow, creg }): the AREKSTATE1
// file `arek host pack` writes - zero RAM and registers unless given (chip / slow / creg as bytes); time = the beam time
// v * 227 + h the engine starts at, frame = the frame counter's start (both as the original had them at the entry, measured
// with `arek bpstate`); entry = the pc the state names (HOST_ENTRY is what runs; the engine reads this field too).
// Events run after frame f is done while the game waits, before frame f + 1 is allowed - the same rule the page uses, so a
// measurement here and a replay in the page see the same game.
'use strict';
const fs = require('fs'), path = require('path');
const MAGIC = 'AREKSTATE1\0';
const hex = (v) => (v >>> 0).toString(16);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const immediate = () => new Promise((r) => setImmediate(r));

function synthState(o) {
    o = o || {};
    const d = o.d || [0, 0, 0, 0, 0, 0, 0, 0], a = o.a || [0, 0, 0, 0, 0, 0, 0, 0], line = (xs) => xs.map(hex).join(' ');
    const txt = line(d) + '\n' + line(a) + '\n' + hex(o.sr === undefined ? 0x2000 : o.sr) + ' ' + String(o.time || 0) + ' ' + hex(o.intreq || 0) + ' ' + hex(o.entry || 0) + '\n'
        + hex(o.pra === undefined ? 0xfe : o.pra) + ' ' + hex(o.sdr || 0) + ' ' + hex(o.icr || 0) + ' ' + hex(o.joy0 || 0) + ' ' + hex(o.joy1 || 0) + ' ' + hex(o.pot === undefined ? 0x5500 : o.pot) + '\n'
        + String(o.frame || 0) + '\n';
    const head = MAGIC.length, out = new Uint8Array(head + 0x80000 * 2 + 0x200 + txt.length + 1);
    for (let i = 0; i < head; i++) out[i] = MAGIC.charCodeAt(i);
    if (o.chip) out.set(o.chip.subarray(0, 0x80000), head);
    if (o.slow) out.set(o.slow.subarray(0, 0x80000), head + 0x80000);
    if (o.creg) out.set(o.creg.subarray(0, 0x200), head + 0x100000);
    for (let i = 0; i < txt.length; i++) out[head + 0x100200 + i] = txt.charCodeAt(i);
    return out;
}

class Engine {
    constructor(M, opts) {
        this.M = M; this.threaded = !!M._engine_threaded(); this.hang = (opts && opts.hang) || 20000;
        this.events = []; this.k = 0; this.started = false;
    }
    init(state) {
        const b = typeof state === 'string' ? fs.readFileSync(state) : state, M = this.M, p = M._engine_alloc(b.length);
        M.HEAPU8.set(b, p); const r = M._engine_init(p, b.length);
        if (r) throw new Error('engine_init ' + r);
        return this;
    }
    disk(i, f) {
        const b = typeof f === 'string' ? fs.readFileSync(f) : f, M = this.M, p = M._engine_alloc(b.length);
        M.HEAPU8.set(b, p); M._engine_set_disk(i, p, b.length);
        return this;
    }
    start() {
        if (this.started) return this; this.started = true;
        if (this.threaded) { const r = this.M._engine_run(); if (r) throw new Error('engine_run ' + r); }
        else this.M.ccall('engine_run', 'number', [], [], { async: true });
        return this;
    }
    keys(mask) { this.k = mask; this.M._engine_keys(mask); return this; }
    /** keys from frame f on: 'f:mask,f:mask' or [[f, mask]] */
    schedule(spec) {
        const list = typeof spec === 'string' ? spec.split(',').filter(Boolean).map((x) => x.split(':').map(Number)) : spec;
        for (const [f, m] of list) this.at(f, () => this.keys(m));
        return this;
    }
    /** fn(f) after frame f is done and the game waits, before frame f + 1 is allowed */
    at(f, fn) { this.events.push({ f, fn }); this.events.sort((p, q) => p.f - q.f); return this; }
    done() { return this.M._engine_done(); }
    error() { return this.M._engine_error(); }
    ended() { return !!this.M._engine_ended(); }
    async wait(f) {
        const M = this.M, t0 = Date.now();
        const hung = () => { if (Date.now() - t0 > this.hang) throw Object.assign(new Error('engine hung at frame ' + M._engine_done()), { code: 'hung', frame: M._engine_done() }); };
        while (M._engine_done() < f && !M._engine_error() && !M._engine_ended()) {
            hung();
            if (this.threaded) await sleep(0); else { if (M.__engineResume) M.__engineResume(); await immediate(); }
        }
        if (this.threaded) while (!M._engine_waiting() && !M._engine_error() && !M._engine_ended()) { hung(); await sleep(0); }
        if (M._engine_error()) throw Object.assign(new Error('engine error at ' + M._engine_error().toString(16)), { code: 'error', addr: M._engine_error() });
    }
    /** one game frame: the events of the frame done, then the next frame allowed and waited for; returns the frame done */
    async step() {
        this.start();
        const f = this.done();
        while (this.events.length && this.events[0].f <= f) { const e = this.events.shift(); e.fn(f); }
        this.M._engine_allow(f + 1);
        await this.wait(f + 1);
        return this.done();
    }
    /** up to frame n (or the game's end); onFrame(f) after every frame */
    async run(n, onFrame) {
        this.start();
        while (this.done() < n && !this.ended()) { const f = await this.step(); if (onFrame) await onFrame(f); }
        return this.done();
    }
    peek8(a) { return this.M._engine_peek8(a); }
    peek16(a) { return (this.peek8(a) << 8) | this.peek8(a + 1); }
    peek32(a) { return ((this.peek16(a) << 16) | this.peek16(a + 2)) >>> 0; }
    poke8(a, v) { this.M._engine_poke8(a, v & 255); return this; }
    poke16(a, v) { return this.poke8(a, v >> 8).poke8(a + 1, v); }
    poke32(a, v) { return this.poke16(a, v >>> 16).poke16(a + 2, v); }
    /** len bytes from address a (chip or slow RAM) as a copy */
    dump(a, len) { const out = new Uint8Array(len); for (let i = 0; i < len; i++) out[i] = this.M._engine_peek8(a + i); return out; }
    hash() { return this.M.ccall('engine_hash_hex', 'string', [], []); }
    /** the last frame's picture: 12-bit colours, { w, h, data } (a copy) */
    pix() { const M = this.M, w = M._engine_pix_w(), h = M._engine_pix_h(); return { w, h, data: new Uint16Array(M.HEAPU8.buffer, M._engine_pix(), w * h).slice() }; }
    /** the last frame's picture as RGB24, { w, h, data } (a copy; vAmiga's 716 x 285 layout) */
    rgb() { const M = this.M, w = M._engine_rgb_w(), h = M._engine_rgb_h(); return { w, h, data: M.HEAPU8.slice(M._engine_rgb(), M._engine_rgb() + w * h * 3) }; }
    frameNo(n) { return this.M._engine_fr_frame(n === undefined ? this.done() - 1 : n); }
}

async function open(dir, opts) {
    opts = opts || {};
    const name = opts.name || (fs.existsSync(path.resolve(dir, 'engine_mt.js')) ? 'engine_mt' : 'engine');
    const Factory = require(path.resolve(dir, name + '.js'));
    const M = await Factory({ wasmBinary: fs.readFileSync(path.resolve(dir, name + '.wasm')) });
    const eng = new Engine(M, opts);
    if (opts.hash) M._engine_hash_on(1);
    if (opts.state) eng.init(opts.state);
    if (opts.disks) opts.disks.forEach((f, i) => eng.disk(i, f));
    return eng;
}

module.exports = { VERSION: '1.0', open, synthState, Engine };
