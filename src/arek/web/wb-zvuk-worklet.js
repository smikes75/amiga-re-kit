// wb-zvuk-worklet.js 1.0 - Paula's output into Web Audio (amiga-re-kit, docs/WB-PLYNULOST.md, module D): an
// AudioWorkletProcessor over a ring of stereo int16 at 48 kHz. Extracted from the Alien Breed II page (audio-worklet.js)
// and Superfrog's. Only the source: the Amiga 500's filters, the stereo width and the volume follow it in the kit's
// chain (wb-zvuk.js). Two modes:
//   - messages (an engine without shared memory): the page sends the game's frames (Int16Array, L R interleaved)
//     through the port into the worklet's own ring of 1 s;
//   - shared memory (an engine in a thread, the page with COOP/COEP): {sab, ring, n, widx, ridx} = the engine's ring
//     inside the wasm memory, the count of samples written (by the engine) and read (by the worklet: the engine's
//     thread sees the reserve run low and computes on without the page's permit). The page is not in the path: a
//     stalled main thread does not interrupt the sound.
// The reserve is kept at `target` by reading up to 1 % faster or slower (the game gives 960 samples per 19.968 ms,
// 0.16 % more than 48 000/s); `prefill` before the first sample after a start or an underrun; running out counts as
// a dropout (under) and primes again; a frame that would overflow is dropped (drop). The state goes to the page
// every 250 ms: {fill: ms, under, drop, primed, shared}. Messages: 'flush', {prefill, target} (ms), {sab, ...}, a frame.
class WbPaula extends AudioWorkletProcessor {
  constructor() {
    super();
    this.n = 48000; this.ring = new Int16Array(this.n * 2); this.w = 0; this.rd = 0; this.primed = false;
    this.shared = null; this.prefill = 1920; this.target = 2400;
    this.under = 0; this.drop = 0; this.fillSum = 0; this.fillN = 0; this.last = 0;
    this.port.onmessage = (e) => {
      const d = e.data;
      if (d === 'flush') { if (this.shared) this.rd = Atomics.load(this.shared.w, 0); else { this.w = 0; this.rd = 0; } this.primed = false; return; }
      if (d && d.sab) {                                    // the engine's ring in shared memory
        this.shared = { ring: new Int16Array(d.sab, d.ring, d.n * 2), w: new Int32Array(d.sab, d.widx, 1), r: new Int32Array(d.sab, d.ridx, 1), n: d.n };
        this.rd = Atomics.load(this.shared.w, 0); this.primed = false; return;
      }
      if (d && d.target) { this.target = Math.round(d.target * 48); this.prefill = Math.round((d.prefill || d.target * 0.8) * 48); return; }
      if (this.shared) return;
      const s = d instanceof Int16Array ? d : new Int16Array(d), m = s.length >> 1;
      if (this.w - this.rd + m > this.n - 128) { this.drop += m; return; }      // would overflow: the frame is dropped
      for (let i = 0; i < m; i++) { const o = ((this.w + i) % this.n) * 2; this.ring[o] = s[2 * i]; this.ring[o + 1] = s[2 * i + 1]; }
      this.w += m;
    };
  }
  process(_, outputs) {
    const out = outputs[0], L = out[0], R = out[1] || out[0], sh = this.shared;
    const ring = sh ? sh.ring : this.ring, n = sh ? sh.n : this.n;
    let rd = this.rd; const w = sh ? Atomics.load(sh.w, 0) : this.w;
    if (w < Math.floor(rd)) { rd = w; this.primed = false; }  // the engine started again (its count from zero)
    const fill = w - rd, T = this.target;
    const adj = Math.max(-0.01, Math.min(0.01, (fill - T) / T * 0.01)), step = 48000 / sampleRate * (1 + adj);
    if (fill > 2 * T + 960) rd = w - T;                    // the game far ahead (after a pause, a jump): keep the target
    if (!this.primed && fill >= this.prefill) this.primed = true;
    let gap = false;
    for (let i = 0; i < L.length; i++) {
      let l = 0, r = 0;
      if (this.primed && rd + 1 < w) {
        const k = Math.floor(rd), f = rd - k, o = (k % n) * 2, o2 = ((k + 1) % n) * 2;
        l = (ring[o] * (1 - f) + ring[o2] * f) / 32768; r = (ring[o + 1] * (1 - f) + ring[o2 + 1] * f) / 32768; rd += step;
      } else if (this.primed) { gap = true; }
      L[i] = l; R[i] = r;
    }
    if (gap) { this.under++; this.primed = false; }        // ran dry: a dropout, prime again
    this.rd = rd; if (sh) Atomics.store(sh.r, 0, Math.floor(rd));
    this.fillSum += w - rd; this.fillN++;
    if (currentTime - this.last > 0.25) {
      this.last = currentTime; this.port.postMessage({ fill: this.fillSum / Math.max(1, this.fillN) / 48, under: this.under, drop: this.drop, primed: this.primed, shared: !!sh });
      this.fillSum = 0; this.fillN = 0;
    }
    return true;
  }
}
registerProcessor('wb-paula', WbPaula);
