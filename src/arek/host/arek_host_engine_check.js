// arek_host_engine_check.js - the ASYNCIFY engine (arek host engine) in Node: the game for N frames with the check's
// keys (frame f: up when (f / 40) is odd, else right), then the same line the native build prints
// (`arek_host_engine STATE.bin N`): frames done, the last frame's number and the hash of its picture and chip RAM.
//   node arek_host_engine_check.js ENGINE_DIR STATE.bin FRAMES [DISK0.adf [DISK1.adf ...]]
// No game data: the state and the disks come from the command line.
const fs = require('fs'), path = require('path');
const dir = process.argv[2], statePath = process.argv[3], N = +process.argv[4] || 100, disks = process.argv.slice(5);
if (!dir || !statePath) { console.error('node arek_host_engine_check.js ENGINE_DIR STATE.bin FRAMES [DISK.adf ...]'); process.exit(2); }
(async () => {
  const Engine = require(path.resolve(dir, 'engine.js'));
  const M = await Engine({ wasmBinary: fs.readFileSync(path.resolve(dir, 'engine.wasm')) });
  const st = fs.readFileSync(statePath); const p = M._engine_alloc(st.length); M.HEAPU8.set(st, p);
  const init = M._engine_init(p, st.length);
  if (init) { console.error('engine_init', init); process.exit(1); }
  disks.forEach((f, i) => { const b = fs.readFileSync(f), q = M._engine_alloc(b.length); M.HEAPU8.set(b, q); M._engine_set_disk(i, q, b.length); });
  const run = M.ccall('engine_run', 'number', [], [], { async: true });
  run.then((r) => { console.log('engine_run returned', r); });
  for (let f = 0; f < N; f++) {
    M._engine_keys(((f / 40) | 0) % 2 ? 4 : 1);
    M._engine_allow(f + 1);
    if (M.__engineResume) M.__engineResume();
    await new Promise((r) => setImmediate(r));
    if (M._engine_error()) { console.log('error', M._engine_error().toString(16)); break; }
    if (M._engine_ended()) break;
  }
  const n = M._engine_done();
  console.log('frames ' + n + ' frame ' + M._engine_fr_frame(n - 1) + ' hash ' + M.ccall('engine_hash_hex', 'string', [], []));
  process.exit(0);
})();
