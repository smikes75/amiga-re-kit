# WB-PLYNULOST - the canon of a smooth picture and sound in the browser (kit 0.8.x)

The rebuilds of the kit (Superfrog, Alien Breed, Turrican II, Alien Breed II) show a game whose logic runs at 50 Hz on
displays of 60, 120 or 144 Hz, in Chromium and in Safari, on weaker machines too. The canon says which layer does
what, which numbers a page must reach and how the kit measures them. Written from the Alien Breed II project's
measurements (its `docs/code.md` M10-M13) and its specification for the kit (`docs/ZADANI-KIT-PLYNULOST.md`,
2026-10-28); the modules B-F arrive as kit 0.8.x, each with a self-test.

## A. Layers and who owns them

| layer | owner | what |
|---|---|---|
| 1 the game's logic | the project (the kit's translation) | 50 Hz, never changed |
| 2 the engine in a thread | the kit's host (module E) | the project adds only "what the scene of this game is": the camera, the sprites, the objects with an identity, the time of a drawing pass, the palette per line |
| 3 the clock | the kit (module C, `wb-takt.js`) | frames of the game allowed by the display's clock, the timeline, the interpolation, the keys at the event |
| 4 the sound | the kit (module D; the filters are `wb-zvuk.js`) | an AudioWorklet over shared memory, a 30 ms reserve |
| 5 the drawing | the kit's presenter (module B, `wb-obraz.js` 1.5) | the content of the layers is the project's |
| 6 the measurement | the kit (module F, `arek web smooth`) | the project provides the hooks |

The limits (checked by F in Chromium and WebKit, 60 Hz, no frame cap):

| what | limit | Alien Breed II measured |
|---|---|---|
| dropped display frames in 30 s of play | 0 | |
| the camera's step between display frames, deviation | < 0.05 game px | 0.03 (Chromium) |
| the next game frame / drawing pass missing for the interpolation | 0 % | |
| key -> camera moves, median | <= 70 ms | 66 ms (thread), 82 ms (coroutine) |
| sound dropouts over 10 stalls of the main thread of 150 ms | 0 | 0 (thread), 10 (coroutine) |
| sound reserve | about 30 ms; the browser's output latency is measured and reported | |

## B. The presenter (`wb-obraz.js` 1.5, kit 0.8.0) - done

One visible canvas, WebGL2 when the browser has it or the 2D path with the same API; `present({pixels})`,
`present({draw})`, the geometry of contract 1.4 on both paths, §3 in the shader. WB-OBRAZ-CRT.md §1.6. The reason: a
WebGL canvas copied into a 2D canvas every frame stutters in Safari (the 2D canvas the CPU writes to lives in CPU
memory, the copy waits for the GPU).

## F. The measurement (`arek web smooth`, kit 0.8.1) - done

    arek web smooth URL [--seconds 30] [--browser chromium|webkit|all] [--stalls 10] [--stall-ms 150] [--json]

Phases: scroll (the right key held, every display frame sampled: its timestamp, the camera, the objects, the missing
passes, the game's lead), latency (five key presses dispatched inside the page, the time until the camera moves),
stalls (busy loops in the main thread, the sound's counters before and after). Every limit of A passed or failed, per
browser. A step is judged per nominal display interval (step / dt * nominal), so the display's own timing jitter does
not count and an uneven motion does.

The page's hooks (`globalThis.WBLONGRUN` 1.1; `arek web longrun` reads the same object):

| hook | returns |
|---|---|
| `ready()` | the game runs |
| `cam()` | `[x, y]` the camera in game pixels as drawn in this display frame (fractional when interpolated) |
| `objs()` (optional) | `[[id, x, y], ...]` the objects on screen with an identity, game pixels as drawn |
| `missing()` (optional) | display frames drawn without the next game frame / pass for the interpolation, so far |
| `ahead()` (optional) | game frames computed ahead of the display |
| `audio()` (optional) | `{reserve: ms, dropouts: n (so far), latency: ms, simulated?: bool}` |
| `status()` (optional) | a line of text for the report |
| `keys` (optional) | `{left, right}`: the key codes that move the camera (default the arrows) |

The kit's synthetic page `smooth-demo.html` (`arek web demo`, then `/smooth-demo.html`) runs a 50 Hz game by the
display's clock with the picture 30 ms behind and the camera and objects interpolated: Chromium headless 59.9 Hz,
0 dropped, deviation 0.000 px, key -> camera 46 ms; WebKit headless 58.8 Hz the same (its sound is simulated).

## C. The clock (`wb-takt.js` 1.0, kit 0.8.1) - done

Extracted from Alien Breed II (PACE, pump, loopIn) and Superfrog (main.js, worker.js); the page owns the engine and
gives `allow(n)`, the module gives the permits, the times and the pairs:

- `takt.tick(ts, done, paused)` every display frame: measures the display (median of the last intervals), locks on
  a k x 50 Hz display (within 0.6 Hz: exactly one game frame per k display frames; `lock: 'auto' | 'on' | 'off'`),
  grants game frames up to now + one frame and at most `ahead` (2) beyond what the engine has done - the clock
  starts from now at the start, after a pause and after a stall of 5 frames, and continues behind the game when it
  ran past the permits;
- `takt.stamp(n)`: the time of game frame n (its permit's nominal time; a frame made without a permit gets the
  previous + one frame; never earlier than the previous);
- `takt.view(ts)`: the display times `tv` (camera, sprites: `latC` 30 ms behind the game, 20 with an engine in a
  thread, one frame less 2 ms under the lock) and `tvO` (objects: `latO` 60 ms, adaptive to the longest of the last
  16 drawing passes - the game's lead + 8 ms, up to 120; fed by `takt.pass(t)`);
- `takt.pair(list, t)`: the two frames around t and the fraction; without the next one the previous pair
  extrapolates (`f` up to 2) when allowed, else the last frame alone and `missing` counts it;
- `WBTAKT.keyboard(target, {code: bit}, onchange)`: the keys as bits changed at the event;
- `takt.reset(done)` for a restart or a jump, `takt.stats()` for the hooks (`hz`, `k`, `fm`, `ahead`, `missing`).

## D. The sound (`wb-zvuk-worklet.js` + `wb-zvuk-out.js` 1.0, kit 0.8.1) - done

Extracted from Alien Breed II (audio-worklet.js) and Superfrog: an AudioWorkletProcessor (`wb-paula`) over a ring of
stereo int16 at 48 kHz, only the source - the Amiga 500's filters, the stereo width and the volume follow in the
kit's chain (`wb-zvuk.js`). Two modes:

- shared memory (an engine in a thread, the page served with COOP/COEP): `out.bind({sab, ring, n, widx, ridx})` =
  the engine's ring inside the wasm memory with the count of samples written (the engine) and read (the worklet);
  reserve 30 ms, prefill 20; the engine's thread sees the reserve fall under `low` 15 ms and computes on without
  the page's permit, so a stalled main thread (GC, a long task) does not interrupt the sound;
- messages (no shared memory): `out.push(int16LR)` per game frame into the worklet's own ring of 1 s; reserve
  50 ms, prefill 40 - a stall longer than the reserve runs it dry (the canon's limit fails, as it should).

The reserve is held at the target by reading up to 1 % faster or slower (the game gives 960 samples per 19.968 ms);
running out counts a dropout and primes again; a frame that would overflow is dropped; after a pause or a jump the
read position keeps the target. `out.stats()` -> `{reserve, dropouts, dropped, primed, shared, mode, latency}` (the
browser's `outputLatency + baseLatency`) feeds the page's `WBLONGRUN.audio()`. The kit's synthetic page shows both:
served with `arek web serve --isolated` a worker fills the ring and 10 stalls of 150 ms cost 0 dropouts; served
plainly the page pushes frames and the stalls run the reserve dry.

## E. The engine in a thread (`arek host engine --thread`, kit 0.8.1) - done

From Alien Breed II (`tools/host/engine.c` GAME_THREAD, `tools/build_mt.sh`) into the kit's template
`arek_host_engine.c` (`-DENGINE_THREAD`): the game runs in its own thread (a pthread = a Web Worker in the browser)
and at the end of every frame waits for the page's permit (`engine_allow`, a futex; natively a condition), so no
ASYNCIFY is needed (a game's build takes minutes instead of tens of them). The page composes from the same memory.
The sound: every frame's samples go into the ring with a count written (`engine_aud_written`); the AudioWorklet of
module D reads the ring from the shared memory and writes the count read (`engine_aud_read`); under
`engine_aud_low(samples)` (15 ms) the thread computes on without a permit, so a stalled main thread does not
interrupt the sound. `engine_stop` parks the thread (a longjmp in its own thread), `engine_parked` tells when it
has, and `engine_run` after a new `engine_init` wakes it (a restart, a saved position). The coroutine build
(`arek host engine` without `--thread`) stays the fallback for a page without COOP / COEP; interrupt handlers are
called directly (G37), so both builds sleep in a handler's wait loop.

    arek host engine web/eng --game game.c --l3 f_c13e1c --entry f_c01c72 --src externs.c --thread --run   # engine_mt.js + .wasm
    arek host engine out --game game.c --l3 ... --entry ... --native --thread --run                      # arek_host_engine_mt
    node lib/arek_host_engine_check.js web/eng state0.bin 300 disk1.adf                                   # the same line as native

The check hashes the picture and the chip RAM at every frame's end (`engine_hash_on`), so the coroutine (which
runs on to its next wait loop) and the thread (which stops at the frame's end) give the same line; the synthetic
test holds native, native in a thread, wasm with ASYNCIFY and wasm in a thread against each other (200 frames: one
hash).

## A. The numbers (kit 0.8.1, the kit's synthetic page, headless)

`arek web smooth` over `smooth-demo.html` (wb-obraz 1.5 WebGL path, wb-takt 1.0, wb-zvuk-worklet over shared memory
from a worker; served with `arek web serve --isolated`), 8 s of scrolling, 10 stalls of 150 ms:

| browser | display | dropped | camera / objects deviation | missing | key -> camera | sound reserve, output latency, dropouts |
|---|---|---|---|---|---|---|
| Chromium 156 | 60.0 Hz | 0 | 0.000 / 0.000 px | 0 % | 47 ms | 49 ms, 29 ms, 0 |
| WebKit 27.2 | 60.0 Hz | 0 | 0.000 / 0.000 px | 0 % | 47 ms | 44 ms, 16 ms, 0 |

Served without COOP / COEP the same page sends its sound by messages and the stalls run the reserve dry - the
measurement fails, as the canon says it should. The games' baselines (Alien Breed II, Superfrog, Alien Breed) come
when their pages carry the hooks of F; Safari on a real display is the user's measurement (headless WebKit runs a
software compositor).
