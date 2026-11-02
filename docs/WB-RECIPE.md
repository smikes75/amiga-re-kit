# WB-RECIPE - the display layer of the kit for a new game, on one page (kit 1.0)

The canon `WB-PLYNULOST.md` says WHY every piece is as it is, with the measurements behind it. This page says WHAT a
game writes. The contract is frozen at kit 1.0: wb-takt 1.4, wb-obraz 1.6, wb-scene 1.9, wb-zvuk 1.1, WBLONGRUN 1.5;
it changes only for a gap a game measures (KIT-GAPS), never for a new idea - those wait after 1.0.

## The ten lines

```js
// the clock: the display's tep grants the game its frames, gives them times and the pairs for the interpolation
const takt = WBTAKT.create({ fps: 50, ahead: 2, latC: 20 /* 30 with a coroutine engine */, latO: 40, lock: 'auto', allow: (n) => engine_allow(n) });
// the presenter: ONE canvas (<canvas id="screen"> before <canvas class="crt-layer"> in .game), WebGL2 or 2D, the CRT above it
const pr = new WBOBRAZ.Presenter(document.getElementById('screen'), { gl: 'auto' });
const screen = new WBOBRAZ.Screen(document.querySelector('.game'), pr.canvas);
// the scene: one record per game frame in, the composition out - into the presenter's framebuffer, nowhere else
const scene = new WBSCENE.Scene({ takt, camMean: { tau: 20 }, pairOlder: 2, extrapolateObjects: 1, jumpMax: 40 });
scene.attach(pr);
// every game frame (the engine finished frame n):
scene.frame({ n, t: takt.stamp(n), pass: tOfThePass, cam, limits, window: { w, h, idx, pal, over }, map, objects, sprites, hud });
takt.pass(tOfThePass);                                       // when the game's drawing pass (the 25 Hz loop) completed
// every display frame:
takt.tick(ts, engine_done(), paused);
pr.present({ draw: scene.drawer(ts, view) });                // view = { W, H, S, extX, extY, x0, y0 } of the mode
```

The sound: an engine in a thread (`arek host engine --thread`, the page served with COOP / COEP) writes its ring in
shared memory, `WBZVUKOUT.bind({ sab, ring, n, widx, ridx })` plays it through the kit's worklet with a 30 ms reserve;
the thread computes on without a permit under 15 ms of reserve. Without shared memory `out.push(int16LR)` per frame.

## The record (what the game knows, in world coordinates)

| field | what | rule |
|---|---|---|
| `cam`, `limits` | the game's camera and where it may go | the view clamps; a narrow map is centred on a whole pixel |
| `window.idx`, `pal` | the CLEAN window: indices (255 = none), a palette row per line | without the objects and sprites the game blits - from a restore bitmap or a clean buffer |
| `window.over` | what the game drew over the window and the record cannot name | `WBSCENE.unexplained(rec, gameIdx)` finds it; not interpolated |
| `map` | atlas + cells, `gen`, `dirty` slots | the margins beyond the window; the kit uploads every frame's dirty slots |
| `objects[]` | `id`, `x, y` the LOGICAL position, `ox, oy` the drawing's offset, `w, h, idx`, `pass` | interpolated between PASSES; `steady` for one the camera tracks (a player that is a blitter object) |
| `sprites[]` | `k`, `id`, `x, y` the hardware position, `h, idx` | interpolated between frames; `screen: true` for one fixed on the screen; `freshSprites` draws them from the newest frame |
| `hud` | `top / bottom: { h, rgba, split }`, `under` | widened by the splits; `under` when a sprite may reach into the HUD rows |

Rules that are not options: a camera, object or sprite that jumps more than `jumpMax` (40 px) is shown at the new
place, not crossed; a frame without a new pass for `passMax` (100 ms) counts as a pass; an older pass after a newer
one is ignored; after a jump or a restart `takt.reset(done)`; the atlas `dirty` of a frame never drawn is still
uploaded; the view's camera is never left of the map's edge.

## The decisions a game makes (each behind a Debug switch until the author chooses)

| option | what it trades | who chose what |
|---|---|---|
| `subpixel` | even motion on a 60 / 144 Hz display against sharp edges on whole pixels | Superfrog off (a platformer at zoom 3), Alien Breed II on (top-down) |
| `freshSprites` | a tracked player answers a key one display delay sooner against a 1-2 px lead over the ground while moving | measured 44 -> 28 ms key -> player |
| `WBSCENE.transition(from, to)` | the kit's mode transition (the real intermediate viewport, the latencies blended, the CRT by the measured rules) against the game's own | one for all games |
| `latC` / `latO` | less display delay against missing pairs (extrapolation fills them) | 20 / 40 with a thread, 28 / 48 Superfrog |
| `lock` | one game frame per k display frames on a k x 50 Hz display | 'auto' |

## The hooks the page gives (`globalThis.WBLONGRUN`)

`ready()`, `cam()`, `objs()`, `scale()`, `missing()`, `ahead()`, `audio()`, `status()`, `keys`, `prepare()`, `route`,
`interp()`, `player()` for `arek web smooth` (the canon's limits: 0 dropped frames, jitter < 0.05 px, 0 % missing,
key -> camera <= 70 ms, 0 sound dropouts under stalls); `done()`, `state()`, `inputs()` for `arek web replay` (the
same game state at 50, 60, 120 and 144 Hz). `wbObrazTest.set / fill / gl` for `arek web test` (the presenter's
geometry, the CRT, one canvas under the CRT layer).

    arek web test URL --quick        # the presenter's contract
    arek web smooth URL --gpu        # the canon's limits
    arek web replay URL --hz 50,60,120,144 --frames 300 --route 1:120,2:60,0:120
    scene.read() against WBSCENE.reference(composition)   # 0 mismatches at any time, any scale

## What is not in the kit on purpose

An automatic high-score save, a muzzle flash moved with the player, spawner previews, a fade-in of enemies at the
window's edge: game knowledge, on the page after `compose()` (`draw(ts, view, fbo, d, comp)` takes a composition
the page changed). Run-ahead (a frame computed ahead with the held input) is an experiment for after 1.0.
