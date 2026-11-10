// wb-zvuk-out.js 1.0 - the page's side of Paula's output (amiga-re-kit, docs/WB-PLYNULOST.md, module D): loads
// wb-zvuk-worklet.js into an AudioContext, feeds it either the engine's ring in shared memory (bind: an engine in a
// thread, the page with COOP/COEP; reserve 30 ms, prefill 20, the engine computes on without a permit under `low`
// 15 ms) or the game's frames by messages (push: the fallback without shared memory; reserve 50 ms, prefill 40),
// and reports the reserve, the dropouts and the browser's output latency for the page's WBLONGRUN.audio() hook.
//   const out = await WBZVUKOUT.create(ctx, { module: 'wb-zvuk-worklet.js' });   out.node -> connect to the kit's chain
//   out.bind({ sab, ring, n, widx, ridx })  |  out.push(int16LR)  |  out.flush()  |  out.stats() -> { reserve, dropouts,
//   dropped, primed, shared, latency }  |  out.preset.low (samples the engine gets from engine_aud_low)
// No game data.
'use strict';
const WBZVUKOUT = (() => {
  const VERSION = '1.1';
  const PRESETS = { shared: { prefill: 20, target: 30, low: 15 }, messages: { prefill: 40, target: 50, low: 0 } };   // ms
  async function create(ctx, opts) {
    opts = opts || {};
    await ctx.audioWorklet.addModule(opts.module || 'wb-zvuk-worklet.js');
    const node = new AudioWorkletNode(ctx, 'wb-paula', { outputChannelCount: [2] });
    let st = { fill: 0, under: 0, drop: 0, primed: false, shared: false };
    node.port.onmessage = (e) => { st = e.data; };
    const out = {
      version: VERSION, node, mode: 'messages', preset: PRESETS.messages,
      setTarget(prefill, target) { node.port.postMessage({ prefill, target }); },
      bind(sh) { out.mode = 'shared'; out.preset = PRESETS.shared; out.setTarget(out.preset.prefill, out.preset.target); node.port.postMessage({ sab: sh.sab, ring: sh.ring, n: sh.n, widx: sh.widx, ridx: sh.ridx }); },
      // 1.1: the caller keeps its buffer unless the view is the whole of a plain ArrayBuffer (then it is transferred, as
      // before); a view into a larger buffer or into the engine's memory (WebAssembly.Memory: transferring it throws,
      // and a part of the page's own buffer would be detached with all of it) is copied first
      push(samples) {
        const b = samples.buffer, whole = b instanceof ArrayBuffer && samples.byteOffset === 0 && samples.byteLength === b.byteLength && !out.keep;
        if (whole) { try { node.port.postMessage(samples, [b]); return; } catch (e) { out.keep = true; } }   // not transferable (wasm memory): copy from now on
        const copy = samples.slice(); node.port.postMessage(copy, [copy.buffer]);
      },
      flush() { node.port.postMessage('flush'); },
      stats() { return { reserve: st.fill, dropouts: st.under, dropped: st.drop, primed: st.primed, shared: st.shared, mode: out.mode,
                         latency: 1000 * ((ctx.outputLatency || 0) + (ctx.baseLatency || 0)) }; },
    };
    out.setTarget(PRESETS.messages.prefill, PRESETS.messages.target);
    return out;
  }
  return { VERSION, PRESETS, create };
})();
if (typeof globalThis !== 'undefined') globalThis.WBZVUKOUT = WBZVUKOUT;
if (typeof module !== 'undefined') module.exports = WBZVUKOUT;
