// wb-datadisk.js 1.0 - the data disk of a rebuild, kept in the browser (amiga-re-kit): the sectors the game writes
// through arek_host_datadisk.h (a Team17 game saves its high-score table by hand to a "custom datadisk") live in
// localStorage under the page's key, go to the engine before the game runs and come back after every write.
// Extracted from the Alien Breed II page. No game data.
//   const dd = WBDATADISK.open({ key: 'game-datadisk', host: WBDATADISK.host(M), label: 'Hall of Fame', log: (s) => {} });
//     host: { buf() -> offset in the heap, size() -> bytes, heap() -> Uint8Array, set(ok), gen() -> int }
//           WBDATADISK.host(M) maps an Emscripten module with the header's exports (_ahdd_buf, _ahdd_size, _ahdd_set, _ahdd_gen)
//   dd.load()  -> true when a saved disk went into the engine (after the engine's init, before the game runs)
//   dd.poll()  -> true when the game wrote the disk and the write was saved (once per frame, or on a timer)
//   dd.clear() -> the saved disk is gone and the engine's drive is empty (the game keeps what it loaded until a restart)
//   dd.has()   -> a disk is saved;  dd.bytes() -> its bytes (Uint8Array) or null
//   dd.button(el, { armed: 'Click again to clear', ms: 3000 }) -> el clears on a second click within ms (the first arms it)
//   WBDATADISK.read(key, size) / write(key, bytes) / remove(key) - the storage alone: base64 under key; read wants size
//   bytes (0 = any) and gives null for anything else; write returns '' or the storage's error
'use strict';
const WBDATADISK = (() => {
  const VERSION = '1.0';
  const store = () => { try { return typeof localStorage !== 'undefined' ? localStorage : null; } catch (e) { return null; } };
  const b64 = (b) => { let s = ''; for (let i = 0; i < b.length; i += 0x2000) s += String.fromCharCode.apply(null, b.subarray(i, i + 0x2000)); return btoa(s); };
  function read(key, size) {
    const st = store(); if (!st) return null;
    let v; try { v = st.getItem(key); } catch (e) { return null; }
    if (!v) return null;
    let b; try { b = Uint8Array.from(atob(v), (c) => c.charCodeAt(0)); } catch (e) { return null; }
    return size && b.length !== size ? null : b;
  }
  function write(key, bytes) {
    const st = store(); if (!st) return 'no storage';
    try { st.setItem(key, b64(bytes)); return ''; } catch (e) { return (e && e.message) || String(e); }
  }
  function remove(key) { const st = store(); if (!st) return; try { st.removeItem(key); } catch (e) {} }
  function host(M) {
    return { buf: () => M._ahdd_buf(), size: () => M._ahdd_size(), heap: () => M.HEAPU8, set: (ok) => M._ahdd_set(ok ? 1 : 0), gen: () => M._ahdd_gen() };
  }
  function open(opt) {
    const key = opt.key, h = opt.host, log = opt.log || (() => {}), label = opt.label || 'data disk';
    let gen = h.gen();
    const dd = {
      load() { const b = read(key, h.size()); if (b) h.heap().set(b, h.buf()); h.set(!!b); gen = h.gen(); return !!b; },
      poll() {
        const g = h.gen(); if (g === gen) return false; gen = g;
        const p = h.buf(), b = h.heap().slice(p, p + h.size()), err = write(key, b);
        log(err ? label + ' not saved: ' + err : label + ' saved in this browser');
        if (opt.onSave) opt.onSave(b, err);
        return !err;
      },
      clear() { remove(key); h.set(0); log('saved ' + label + ' cleared (the game shows what it loaded until a restart)'); },
      has() { return !!read(key, h.size()); },
      bytes() { return read(key, h.size()); },
      button(el, o) {                                      // twice: a clear cannot be undone
        const armedText = (o && o.armed) || 'Click again to clear', ms = (o && o.ms) || 3000, label0 = el.textContent;
        let armed = 0;
        el.onclick = () => {
          if (!armed) { el.textContent = armedText; armed = setTimeout(() => { el.textContent = label0; armed = 0; }, ms); return; }
          clearTimeout(armed); armed = 0; el.textContent = label0; dd.clear();
        };
        return el;
      },
    };
    return dd;
  }
  return { VERSION, read, write, remove, host, open };
})();
if (typeof module !== 'undefined') module.exports = WBDATADISK;
