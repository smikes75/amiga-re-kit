# WB-PLYNULOST - the canon of a smooth picture and sound in the browser (kit 0.8.x - 1.0)

**Frozen at kit 1.0 (2026-11-02):** the display layer's contract is wb-takt 1.4, wb-obraz 1.7, wb-scene 2.1, wb-zvuk
1.1 / wb-zvuk-out 1.0, WBLONGRUN 1.5 and `arek web test / smooth / replay` as they stand. From here it changes only for
a gap a game measures (KIT-GAPS), never for a new idea - those wait after 1.0 (run-ahead, a per-sprite shift). What a
game writes is on one page: `WB-RECIPE.md`; this file stays the reasons and the measurements. 2.0 of the scene removed
`softClamp` and `smoothY` (camMean replaced them in 1.2, no game set them); the adaptive objects' latency stays an
opt-in (`latOMax` above `latO`).

After 1.0 (gaps only): 1.0.1 - Superfrog on 0.9.16 (7f96dbf: both switches, the kit's transition 0 mismatches in 6
checks half way at S 3.99-4.01, W 376-478, with freshSprites too) found KIT-GAPS 52: `widenColumns` cropped a HUD
wider than the view from the right (W < w0 kept the left columns), so the transition's intermediate views lost the
HUD's right group - now the columns after each split go, as the widening repeats them; and 53: key -> player in a
game whose camera tracks the player measured the camera, not the player (the sprite does not move on the screen; its
picture changes first: with freshSprites 8.3 ms sooner, 83.3 -> 75.0 ms under a virtual clock, 18 presses) - `player()`
may give the sprite's image as a third value and the probe counts its change. Alien Breed II on 1.0.0 (M47) found
G59: in WebKit one step of the kit's transition (extX 11, extY 5, S = 702 / 352) drew 802 of 346 086 pixels differently
from the reference while Chromium and every other S gave 0 - WebKit's shader compiler fuses a multiply-add, so a
float32 product plus the camera's fraction rounds once there and twice on the CPU. The sampling is whole numbers only
now (2.0.1): the camera in whole device pixels, game x = floor((dx + camd) * W / Wd) with W and Wd whole, an image
pixel = (i * w) div qw; no float is left in it on either path, so any GPU equals the reference at any scale (the
kit's test runs the fractional case in Chromium and WebKit). Alien Breed SE92's migration (kit-scena branch) read
the recipe cold and listed what it lacked (R1-R15, folded into WB-RECIPE.md) and three gaps of its own: a transparent
object (G1), a HUD at another scale (G2), a source of another size into a rectangle (G3) - the author decides.

G60 (kit 1.0.2, wb-scene 2.1): the author tried the kit's mode transition (1.8, kit 0.9.15) and `freshSprites` (1.9,
kit 0.9.16) in Alien Breed II and the other rebuilds and found both counterproductive; they are removed. The
transition: `extX` / `extY` rounded at every step made the viewport grow in jumps of S device pixels, a fractional S
changing every frame gave pixels of unequal width (the picture shimmered - the same phenomenon G59 measured), and a
presenter resized every frame reallocated its canvas and textures (Safari had flickered on that before). The games'
own transition - the presenter's - is right: ONE scale for the whole transition (the larger mode's), the canvas at
the larger view, the viewport cropped in device pixels, the display size by CSS only while the 450 ms run; so the
"real intermediate viewport" of the Codex rebuild stays an idea that measured worse than a crop. `freshSprites`: a
player drawn from a newer frame than its ground leads the ground by the camera's motion over latC at every start,
stop and turn and sinks into a wall; the gain was 10-15 ms (Chromium 61.4 -> 49.5, WebKit 61.3 -> 44.9 ms key ->
player), under one 60 Hz frame - not a fault of the module but of the idea: the sprite and its ground move together.
The whole-number sampling (2.0.1) and `player()` stay. The frozen contract is now wb-scene 2.1.
Of Alien Breed SE92's three gaps the author took G3 (kit 1.0.3, wb-obraz 1.7): `present({ source | pixels + size,
rect, smooth })` draws a source of any size into a rectangle of the content on both paths (whole-number nearest or
linear; a page test holds the WebGL and the 2D path to the same pixels) - a hires title, an interlude or a terminal
no longer needs the page's own program; G1 (a transparent object) and G2 (a HUD at another scale) stay the page's.
Alien Breed SE92 on 1.0.2 (a237315) with its own transition back - one S = max of both modes for the whole 450 ms, the
presenter sized once to the larger view, the scene drawing ceil(ext) and black cropping the fractional cut-out in device
pixels, CSS blending the size - measured GPU against the reference 0 (Chromium and WebKit, S 1-4 incl. fractional, with
and without the shift, 4 x 29 checks), replay EQUAL, web test 286 / 0, smooth with the shift: camera 0.006 / 0.000 px,
key -> camera 23.5 / 28 ms, key -> player 47 / 46 ms. Its one note: the scene drew the HUD rows at the whole-number
view's edges, so a fractional cut-out clipped half a row of text - `view.hudY` (2.1.1) puts the rows where the page says.
Superfrog on 1.0.2 (7af6f45): the kit's transition and freshSprites gone from the page, its own transition stays,
`player()` gives the frog's sprite indices as the image; replay unchanged, key -> player 12-14 ms median; the camera's
jitter moves with the machine's load (0.029-0.099 around the 0.05 limit) and is the same for wb-scene 2.1 and 1.9 run
in pairs (0.056 / 0.056, 0.029 / 0.029) - the whole-number sampling changed nothing in the motion.
Alien Breed SE92 on 1.0.3 (6daa8a1): its screens outside a level, the hires ones included, go through
`present({ source, rect })` and its own GL program is gone - the loading screen at S 2 byte-identical to it in both
modes (at another S a hires column can differ: the kit takes source pixel (i * sw) div dw, the old program the pixel
under the device pixel's centre); `view.hudY = [cut-out top, cut-out bottom - 7 S]` keeps both HUD rows whole at the
fractional edge of its transition and its own HUD blit is gone; GPU against the reference 0 (4 x 29 checks), replay
EQUAL, web test 286 / 0.
Its step 4 (f317ae2): the core in its own thread behind a switch - not `arek host engine --thread` (the game has its
own core with a hardware model) but the existing Asyncify core in a plain Web Worker with Paula and the disk loading,
shared memory (COOP / COEP) for the permit, done, the inputs by frame in a ring of 64, 16 frame slots of creg + 1 MB
core memory, the sound through the kit's `WBZVUKOUT.bind` ring; sound dropouts under 10 x 150 ms stalls 10 / 10 ->
0 / 10 in Chromium and WebKit, key -> camera 27-29 ms, missing 0-0.1 %, replay the same fingerprint as on the main
thread. A rule for the canon's E from it: a frame computed WITHOUT a permit (the sound's reserve ran low) must take
the page's LIVE input, not the per-frame ring - the ring's entry for it does not exist yet and the input was lost (on
the hires title the page could not keep up with the captures, the worker ran ahead on sound, fire never arrived);
the page writes the live input every display frame (joystick plus a key with a sequence number), unpermitted frames
read it, permitted ones the ring, so the replay stays deterministic.
Alien Breed SE92 confirmed G59 and its fix on 1.0.1 (83f5a70): 29 checks of 24.4 M pixels each at S 1, 1.5, 702/352, 2,
2.37, 2.5, 3, 3.1415 and 4, with and without the shift - 0 mismatches in Chromium and WebKit with 2.0.1, where 2.0
had given WebKit 2 146 differing pixels with the shift (Chromium 0); replay and the contract unchanged.
Alien Breed II on 1.0.2 (M49) found G59's other face, in Chromium at S = 1 without the shift: in 2.0 the pieces of a
door's animation (objects of 16 x 14 to 32 x 16) took the colours of another palette row - the HUD's 238,0,0 and
255,255,34 - for one pass, which the author saw as a flash at the end of the animation; the GPU agreed with the
reference, so the fault was in the float32 row (floor(fr32(dy * invS + camF)) landing one row off at a boundary), on
both paths alike. With 2.0.1's whole-number row the same pieces are grey, as in the native picture.

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
| 5 the drawing | the kit's presenter (module B, `wb-obraz.js` 1.5) and the scene (module G, `wb-scene.js` 1.0, kit 0.9.0); ONE canvas - the presenter's: the scene draws into its framebuffer (`scene.attach(presenter)`, `present({draw})`), the filters and the CRT layer above it, no other canvas in the game box (`arek web test` §5.5; an overlay canvas says `data-wb-overlay`) | the project gives one record per game frame (the window's clean picture, the map, the objects with an identity, the sprites, the HUD); the module composes the wider, smoother view on the GPU |
| 6 the measurement | the kit (module F, `arek web smooth`) | the project provides the hooks |

The limits (checked by F in Chromium and WebKit, 60 Hz, no frame cap):

| what | limit | Alien Breed II measured |
|---|---|---|
| dropped display frames in 30 s of play | 0 | |
| the camera's and the objects' jitter (a step against the median of the 3 around it, within a moving stretch) | < 0.05 game px | 0.0001 (thread), 0.0002 (coroutine) |
| the objects' steps against their motion (1.8, kit 1.0.78: against the mean of the 9 steps around, that mean over 0.3 px a frame) | <= 4 per mille of such moving steps | SWIV 1.9-2.6 (ahead 4, 50 / 76), 6.2-6.6 (ahead 2, 30 / 40) |
| the next game frame / drawing pass missing for the interpolation | 0 % | |
| key -> camera moves, median | <= 70 ms | 62-63 ms (thread), 96-97 ms (coroutine) |
| sound dropouts over 10 stalls of the main thread of 150 ms | 0 | 0 (thread), 10 (coroutine) |
| dropped display frames, missing passes (Alien Breed II) | | 0, 0 % in all four runs |
| sound reserve | about 30 ms; the browser's output latency is measured and reported | |

## B. The presenter (`wb-obraz.js` 1.5, kit 0.8.0) - done

One visible canvas, WebGL2 when the browser has it or the 2D path with the same API; `present({pixels})`,
`present({draw})`, the geometry of contract 1.4 on both paths, §3 in the shader. WB-OBRAZ-CRT.md §1.6. The reason: a
WebGL canvas copied into a 2D canvas every frame stutters in Safari (the 2D canvas the CPU writes to lives in CPU
memory, the copy waits for the GPU).

## F. The measurement (`arek web smooth`, kit 0.8.1) - done

    arek web smooth URL [--seconds 30] [--browser chromium|webkit|all] [--stalls 10] [--stall-ms 150] [--gpu] [--json]

Every result names the WebGL renderer and the machine's load average before and after (1.3, G45: headless
Chromium draws WebGL in software - SwiftShader - so the presenter runs on the CPU there, and a loaded machine
dropped 500 of 1034 frames in one run); `--gpu` launches Chromium on the GPU (macOS: ANGLE on Metal).
Headless Chromium also draws no CSS `blur()` under about 1 px (Superfrog: the default 20 % blur of Enhanced is 0.32 px
at S 4 / dpr 2, the screenshots with and without the filter had one md5; headed with the GPU the same blur takes 2-4 %
of the sharpness) - a blur check in headless verifies nothing, measure it headed or in the presenter's shader path.

Phases: scroll (the right key held, every display frame sampled: its timestamp, the camera, the objects, the missing
passes, the game's lead), latency (five key presses dispatched inside the page, the time until the camera moves),
stalls (busy loops in the main thread, the sound's counters before and after). Every limit of A passed or failed, per
browser. A step is judged per nominal display interval (step / dt * nominal), so the display's own timing jitter does
not count; 1.1 (G43, Alien Breed II): the limit is on the jitter - the mean deviation of a step from the median of the
3 steps around it within a stretch of motion - not on the spread of the speeds: a camera that runs 1.66 px per
display frame and then 0.83 (catching up with the player) has a speed deviation of 0.415 px and no jitter; a single
uneven step or an alternating pattern (1.4 0.6 1.4 ...) is jitter. The speed deviation is still reported.

The page's hooks (`globalThis.WBLONGRUN` 1.1; `arek web longrun` reads the same object):

| hook | returns |
|---|---|
| `ready()` | the game runs; 1.2: false outside the game (a map fly-over after a death, a menu) - nothing is sampled or judged then, and a latency probe waits for it (up to 10 s) or is void and repeated |
| `cam()` | `[x, y]` the camera in game pixels as drawn in this display frame (fractional when interpolated) |
| `objs()` (optional) | `[[id, x, y], ...]` the objects on screen with an identity, in the world in game pixels so that `x - cam()[0]` is where the object is drawn on the screen (1.2, G44: objects are judged on the screen, a step over 1 game px - an animation frame's offset - is a jump, not jitter) |
| `scale()` (optional, 1.2) | S, device pixels per game pixel, when the page draws its objects on whole device pixels: their steps on the screen are then judged within 1/S |
| `missing()` (optional) | display frames drawn without the next game frame / pass for the interpolation, so far - counted only where the page interpolates (not on a screen outside the game: a map fly-over after a death, a menu; Alien Breed II) |
| `ahead()` (optional) | game frames computed ahead of the display |
| `audio()` (optional) | `{reserve: ms, dropouts: n (so far), latency: ms, simulated?: bool}` |
| `status()` (optional) | a line of text for the report |
| `keys` (optional) | `{left, right}`: the key codes that move the camera (default the arrows) |
| `focus` (optional, 1.1) | a selector or `[x, y]` to click into the game (default the largest canvas; G41: a page's menu at the corner pauses the game) |
| `prepare()` (optional, 1.1) | brings the page into the game (past an intro and a menu); may return a promise; `ready()` is then awaited (G42) |
| `route` (optional, 1.1) | `[[key, ms], ...]` held in turn and cycled while sampling (a maze: short free stretches; G42); the latency probes alternate left and right |
| `player()` (optional, 1.5, kit 0.9.16) | `[x, y]` or `[x, y, image]` (1.5.1, Superfrog KIT-GAPS 53) the player as drawn on the screen in this display frame: a second latency, key -> player, reported beside key -> camera and not judged (a player the camera tracks does not move on the screen - it changes its picture first, so the image counts as the third value) |
| `interp()` (optional, 1.4) | false when the page draws the game's frames as they are, without interpolation (an original mode); `--no-interp` says the same for a page without the hook |
| `axis` (optional, 1.6, kit 1.0.27) | `'x'` (default) or `'y'`: the camera's axis that is judged and probed after a key (a vertical auto-scroller, Xenon 2); `--axis` |
| `gameLatency` (optional, 1.7, kit 1.0.29) | ms, a number or a function: the original's own delay from a key to the screen, measured in the page's engine (the median over the phases of its input pass - Xenon 2 reads the joystick once per 3-frame pass and shows the double buffer a pass later: 60 / 80 / 100 ms); the latency limit applies to the measured value less this; `--game-latency` |
| `late()` (optional, 1.8, kit 1.0.78) | `[median, max]` ms, how long after its time a game frame's record reached the page (wb-takt 1.7 `takt.late()`); reported |
| `keysMove` (optional, 1.6) | `'camera'` (default) or `'player'`: when the keys move the player and not the camera, the key latency judged is key -> player (`player()` needed) and the camera is not probed; `--keys-move` |

1.4 (kit 0.8.5, Superfrog KIT-GAPS 38): without interpolation a 50 Hz game on a 60 Hz display repeats every sixth
game frame. The camera's 0 step ends a stretch of motion, so its jitter stays low, but an object moving on the screen
steps 1 1 1 1 1 0, which is jitter by the definition above. Such a mode cannot meet the jitter limit and is not meant
to: the jitter and the missing passes are reported and not judged; dropped frames, the key latency and the sound
are. The canon's limits are for the interpolated mode. 1.6: there the camera's moving steps are reported, not judged
either: an original camera that moves 1 px every few frames has no stretch of motion at all. 1.7.1 (kit 1.0.31, Xenon 2
KIT-GAP 11): a camera step over 40 game px (a respawn at a checkpoint, shown at once by the scene's jumpMax) ends a moving
stretch like a stop; before, one such step in a 20 s run put the camera jitter at 0.115-0.157 px.
1.9 (kit 1.0.79, SWIV KIT-GAP 13): the key -> player probe waits until the player stands (its position and presence unchanged
for 10 display frames, up to 3 s, else the probe is void and repeated) and ends at a move in the key's direction over 0.5
game px, or at a change of an image that held during the rest. Before, the first change over 0.01 px answered: a
respawn's blinking (SWIV's hook lost the player every other frame) gave 7-15 ms and 93-261 ms where the page's real
latency was latO + 0-10 ms.
1.8 (kit 1.0.78, SWIV): the jitter leaves out a step further than 1 px from the median of its 3 (an animation frame's
offset), so an object that runs past its newest pass and comes back 2.5-10 px was not in the number - SWIV's helicopters
knocked at 0.139 px of jitter with 443 such steps and 89 against their motion in 2701 display frames. Every object of a
stable id is now also counted on both axes for the steps AGAINST its motion (the sign against the mean of the 9 steps
around, where that mean is over 0.3 px a frame - a turn, a stop, a drift and the steps around a jump over 40 px have no
direction) and for the steps over 1 px; the back steps are judged, <= 4 per mille of the moving steps (at least 100 of
them). An even or uneven motion that never turns back has none at any rounding to device pixels. Measured on SWIV's page
(Chromium on the GPU, 60 Hz, 45 s, load 6-7, all objects, both axes): 1.9 and 2.6 per mille with ahead 4, latC 50, latO 76;
6.2 and 6.6 with ahead 2, 30 / 40 - the limit lies between. The objects' jitter is also reported as the mean over the
objects (`obj_jitter_mean`); the limit stays on the worst object, which a short track (30 display frames of an object in
SWIV's band) can decide from run to run. A page whose `objs()` gives an object kept on the screen must give where it is
drawn (wb-scene: `ob.scr` + the view's camera on that axis), not its world position - SWIV's hook judged the world against
a camera of another time there. `--samples FILE` judges
samples made without a browser (`wb-pagesim.js`, G 2.16) with the same measure, without the keys and the sound.

Alien Breed II's baseline (kit 0.8.1, level 1, enhanced 522 x 357, headless 60 Hz, engine in a thread / coroutine,
Chromium / WebKit): 0 dropped frames and 0 % missing passes in all four; jitter 0.0001-0.0002 px (max 0.25);
key -> camera 62 / 63 ms (thread), 96 / 97 ms (coroutine - over the limit); sound dropouts under 10 x 150 ms 0 / 0
(thread), 10 / 10 (coroutine - over the limit); reserve 24 ms (thread), 31-40 ms (coroutine); output latency 29 ms
(Chromium), 16 ms (WebKit); game lead -0.4 to -0.8 frames; WebGL in Chromium, not in WebKit headless. The thread
meets every limit; the coroutine is the fallback for a page without COOP / COEP and misses two, as the canon
expects.

Alien Breed II on kit 0.8.2 (`arek web smooth` 1.1, `prepare()` = level 1 enhanced, `route` left / right 2.8 s, engine
in a thread, 522 x 357, 60 Hz, 25 s): Chromium 1 dropped frame of 1516, camera jitter 0.004 px, missing 0 %, key ->
camera 61 ms, 0 sound dropouts; WebKit 0 dropped, camera jitter 0.012 px, missing 0.13 % (2 frames), 62 ms, 0
dropouts. The object jitter (0.27-0.60 px) was the measurement's own: objects drawn on whole device pixels against a
fractional camera, and the animation frames' offsets - judged on the screen within 1/S with jumps left out since 1.2
(G44).

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
  thread, one frame less 2 ms under the lock) and `tvO` (objects: `latO` 40 ms; 1.3, kit 0.9.12: fixed - the
  inventory found the games running fixed 40-48 ms and nobody the adaptive latency; `latOMax` above `latO` turns the
  adaptation on: the longest of the last 16 drawing passes - the game's lead + 8 ms, up to latOMax, fed by
  `takt.pass(t)`; with wb-scene 1.7 `extrapolateObjects` the objects run one pass past the last one instead);
- `takt.pass(t)` (1.2): a record of an older drawing pass after a newer one (once in ~1500 frames in a browser,
  Alien Breed II) is not taken - a small step back is ignored, a big one (over 1 s: a new level) starts the axis anew;
- `takt.pair(list, t)`: the two frames around t and the fraction; without the next one the previous pair
  extrapolates (`f` up to 2) when allowed, else the last frame alone and `missing` counts it;
- `WBTAKT.keyboard(target, {code: bit}, onchange)`: the keys as bits changed at the event;
- `horizon` (1.4, Alien Breed II G57): how far ahead of now a frame is granted - `'display'` (default) one display
  frame + 2 ms, so the game computes its frame in the last display frame before its time and reads the freshest
  input (at 120 / 144 Hz 10-11 ms fresher than a game frame; 1.3 ms at 60 Hz), `'game'` one game frame (the
  behaviour up to 1.3, and before the display's rate is measured), or a number of ms;
- `takt.timeOf(n)` (1.3.1, Superfrog KIT-GAPS 51): the permit's time of frame n without side effects, for an engine
  in a worker that stamps its scene packet inside `allow(g)` before the page calls `stamp(n)`;
- `takt.reset(done)` for a restart, a jump or the end of frames allowed outside the clock (1.1, Alien Breed II: a
  jump to a level allows `done + 24`): it takes the permit back (`allow(done)`) and the page skips the frames it has
  not shown, otherwise they get times now + n frames and the timeline stays ahead for good (140-172 ms, the keys that
  much later); `takt.stats()` for the hooks (`hz`, `k`, `fm`, `ahead`, `missing`);
- `takt.late()` (1.7, kit 1.0.78, SWIV): `[median, max]` ms of how long after its time a frame reached `stamp()`, over the
  last 256 (also `stats().late`) - what the objects' latency has to cover (G 2.16); `create({ now })` gives the clock's
  time source (default `performance.now`; wb-pagesim passes its simulated time).

Superfrog on wb-takt (4a7244e, kit 0.9.10: fps 50, ahead 2, latC 28, latO 48 fixed, lock auto; its worker computes
a frame without a permit under 15 ms of sound reserve, up to 12 past the permit, never under replay): `arek web
smooth --gpu`, 30 s, 10 stalls of 150 ms on a loaded machine (load 4-15), two runs each - 0 dropped frames; camera
jitter 0.042 / 0.029 px against its own clock's 0.086 / 0.060; missing passes 2.5 / 2.3 % against 2.4 (a case for
wb-scene 1.7 `extrapolateObjects`); key -> camera 7-13 ms; sound dropouts 0 / 0 (66 / 70 frames without a permit)
against 10 / 10. WebKit under load 5-14: 9 dropped, jitter 0.057, 1 dropout against 0 dropped, 0.014, 18 dropouts.
Replay EQUAL at the four rates with the same fingerprint under both clocks; GPU against the reference 0.

Alien Breed II on wb-takt (M42, kit 0.9.12: fps 49.92, ahead 2 - replay 1, latC 20 thread / 30 coroutine, latO 40
fixed, lock from its menu; `reset(done)` at a jump; the original mode without interpolation moves tv to ts + 2; its
PACE behind a Debug switch for one release; wb-scene 1.7 with `extrapolateObjects: 1`, its own adaptive latency and
the G56 workaround gone, the HUD shared between records): replay EQUAL in Chromium and WebKit with the same
fingerprints as under PACE, GPU against the reference 0 in both browsers with the thread and the coroutine, `arek web
test` 284 / 0; `arek web smooth` on a loaded machine (SwiftShader, load 7-10) inconclusive - dropped frames 27-82
against 1-128, key -> camera 37-101 against 35-57 ms, missing 0 %, sound 0 dropouts. It found G57: the kit granted a
frame one GAME frame ahead where PACE granted one DISPLAY frame + 2 ms ahead (the frame is computed in the last
display frame before its time and reads fresher input: 1.3 ms at 60 Hz, 10-11 ms at 120 / 144 Hz) - `horizon` in 1.4.

Superfrog on kit 0.9.13 (cbb61a2: `timeOf`, latO 48 fixed, the default horizon, `extrapolateObjects: 1` as its
default): `arek web smooth --gpu`, Chromium, 30 s, 10 stalls, load 3-5, two runs each - without the objects'
extrapolation missing passes 2.3 / 2.2 % and jitter 0.059 / 0.056; with it missing 0.0 / 0.0 % and jitter 0.056 /
0.029, every limit of A passed; both 0 dropped, 0 sound dropouts, key -> camera 12-14 ms. Replay EQUAL with the
fingerprints of 0.9.10; GPU against the reference 0.

The blind test of the subpixel shift (Superfrog, Debug "Posun A / B", 2026-11-01): the author preferred the picture
WITHOUT the shift - the sharp edges on whole device pixels over the even motion in a platformer at zoom 3 with a
tracked sprite. In Alien Breed II (a top-down game scrolling in eight directions) the same author's best feel was
the scene module WITH the shift. So the option stays in the module, the default is the game's (the author decides
per game), and a per-sprite shift is not pursued.

1.8 (kit 0.9.15): the mode transition from the kit, and any scale. `WBSCENE.transition(from, to, { ms: 450, t0,
win })` gives `at(ts)` = the view for the drawer between two modes: e = smoothstep(t); the viewport in whole game
pixels (`extX`, `extY` rounded), the band in whole device pixels (`Wd` blended and rounded, S = Wd / W - whole only
at the ends, `Hd` = round(H * S)), the band's origin and the DISPLAY LATENCIES blended (`view.latC` / `latO`, which
`compose()` takes over the clock's: the Enhanced picture 20-48 ms behind the game and the Original's at the game -
without the blend the camera jumped at the end of the transition while moving), and the CRT of the source mode in
the first half, of the target's in the second, its opacity dipped to 40 % (Superfrog's measured rules: the pattern's
pitch from a mode's whole scale, never from the intermediate one). The ends are the views themselves; a reversal is
`transition(cur.at(ts), from, { t0: ts })`. The scene composes the real intermediate viewport at every display frame -
nothing is stretched from a finished picture. For that the module takes any S: the device sizes are round(W * S),
round(H * S), an image of w game pixels is round(w * S) device pixels whose pixel i shows image pixel floor(i * w /
qw) (`quadOf`), and the playfield's sampling multiplies by the float32 reciprocal of S instead of dividing (a
float32 product is correctly rounded on the GPU, a division need not be) - so the GPU equals the reference at any
scale (the kit's test: 0 mismatches half way through 2 -> 3 on the synthetic page). The presenter (wb-obraz 1.6)
takes the fractional S too (its framebuffer and content rounded). A game puts the kit's transition behind a Debug
switch next to its own until the author chooses; the Original mode's view carries latC -2 (no interpolation) and
the Enhanced one its clock's latencies.

1.9 (kit 0.9.16, the response): `freshSprites = true` draws the hardware sprites from the NEWEST game frame not later
than the display time, at the screen position the hardware gave them, over the view's camera - instead of the pair at
the delayed display time (latC 20-48 ms behind the game, the price of the interpolation). A player the camera tracks
stands on the screen anyway, so nothing is lost there, and it answers a key one display delay sooner: on the synthetic
page (Chromium on the GPU, 60 Hz, latC 30) key -> player 44 ms without and 28.5 ms with (25.8-44.8: the probe lands
before or after a game frame), key -> camera 45 ms in both. Turrican II's rebuilds drew their player this way. The
cost: while the camera moves the sprite leads its ground by the camera's motion over the display delay (1-2 px at
walking speed, nothing when standing), and a sprite the camera does not track drifts by that much - so a game with
enemy sprites judges by eye; the option is per game behind a Debug switch like the others. Under the lock the picture
stays one display frame behind the permit (latC = FM - 2): the engine runs in another thread, so a frame granted at
this tick is ready at the next; drawing it in the same tick would need the engine on the main thread.

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
interrupt the sound. Such a frame takes the page's live input (the keys as held now), not an input scheduled
by frame - that entry does not exist yet (Alien Breed SE92 lost fire presses that way; the kit's engine reads
`engine_keys` live). `engine_stop` parks the thread (a longjmp in its own thread), `engine_parked` tells when it
has, and `engine_run` after a new `engine_init` wakes it (a restart, a saved position). `engine_init` takes the ring's write position and the count written back to zero and the count read to none
(1.0.38, Xenon 2 KIT-GAP 16): the worklet reads the place `count % n`, sees the count go back and primes again. The coroutine build
(`arek host engine` without `--thread`) stays the fallback for a page without COOP / COEP; interrupt handlers are
called directly (G37), so both builds sleep in a handler's wait loop.

    arek host engine web/eng --game game.c --l3 f_c13e1c --entry f_c01c72 --src externs.c --thread --run   # engine_mt.js + .wasm
    arek host engine out --game game.c --l3 ... --entry ... --native --thread --run                      # arek_host_engine_mt
    node lib/arek_host_engine_check.js web/eng state0.bin 300 disk1.adf                                   # the same line as native

The check hashes the picture and the chip RAM at every frame's end (`engine_hash_on`), so the coroutine (which
runs on to its next wait loop) and the thread (which stops at the frame's end) give the same line; the synthetic
test holds native, native in a thread, wasm with ASYNCIFY and wasm in a thread against each other (200 frames: one
hash).

## G. The scene (`wb-scene.js` 1.0, kit 0.9.0) - done

One way to draw the wider, smoother view for every project, extracted from Alien Breed II (tools/web/gl.js,
tools/host/view.h: the terrain on the GPU from a tile atlas and a grid, the objects and sprites as quads with index
textures and a palette per row, the GPU held against a CPU composition pixel for pixel) with Superfrog's measured
options (docs/POHYB-AUDIT.md, PLYNULOST-K4.md). The project gives one RECORD per game frame, in world coordinates:
the game's camera and its limits, the window's CLEAN picture (indices, 255 = none, a palette per row - Alien Breed II
reads it from the game's restore bitmap while the bitplane DMA fetches the line; Superfrog has a clean buffer too),
the map for the margins (atlas + cells; "map only" where a project proved the map equals the frame), the objects
with an identity and the time of their drawing pass, the hardware sprites of the frame, the HUD rows. The module
composes: the camera between frames (wb-takt's pairs), the objects between drawing passes (a 25 Hz loop moves them
every other frame - pairing consecutive frames would hold and jump), the sprites between frames, everything placed
on whole device pixels. `WBSCENE.reference(composition)` is the CPU reference of the same composition, so a page can
check its GPU path for 0 mismatches at any time (`scene.read()`), and a page without WebGL2 draws the reference.
The scene draws into the presenter's canvas - the ONE game canvas of the page (the rule of A, since kit 0.9.15:
Superfrog had added a second presenter with its own canvas for the module beside its old renderer, Alien Breed II
attached the scene to the one presenter it had) - and that canvas must lie UNDER the presenter's `.crt-layer`: Superfrog
appended its own canvas for the module after the layer and the CRT vanished but its vignette (its row contrast 0.42
against 8.91 with the old drawing; found by the author's eye, fixed by inserting the canvas before the layer,
dc26710). Since wb-obraz 1.5.2 the Screen moves the layer above a canvas that comes after it and warns; `arek web
test` checks the order (§5.5).

Options (off unless set, each measured in Superfrog): `softClamp { tau }` - at a map edge the stopped camera is
the mean over tau ms of the clamped cameras, extrapolated past the newest frame by at most tau (a stop 5 -> 2.3 -> 0
was jitter: 0.104 -> 0.028 px); `smoothY { tau }` - the terrain's vertical camera as a mean over tau ms, while the
sprites keep their screen position as in the original (the player's landing stays the player's, not the ground's);
`pairOlder` - a blinking sprite or object (drawn every other frame after a hit) paired with up to n older frames
(paired 86 % -> 99.6 %); `fixedAxis { axis, value }` - a level whose camera axis is fixed, black outside the range;
`x17(c)` - 12-bit colours as the DAC gives them. The clean window and the map are sampled at the device pixel's
top-left corner with the camera split into an integer and a float32 fraction, on both paths, so the floor is the same.

1.1 (kit 0.9.1, after Superfrog's switch - its KIT-GAPS 40-43): the means of the soft clamp and the vertical
smoothing are taken over the camera interpolated between the frames and sampled every 5 ms (a mean of the 2 or 3
frames that fall into the window jumps by a step as a third one enters; Superfrog measured y jitter 0.34-0.44 px with
that, 0.02 with the sampled mean), the vertical one as a triangle over the last tau ms; `sprites[].screen = true` for
a sprite fixed on the screen (a badge in a corner, which the clamp at a map edge must not move); `window.over` for
what the game drew over the clean window without an object record (a popping score, a picked coin, the player in an
interlude - above the terrain, below the objects, not interpolated); `passMax` (100 ms) makes every frame a pass when
no new pass came for longer (an interlude drawn by other code); the module warns once when the newest frame is more
than 500 ms behind the drawer's ts (rec.t and ts must share one clock). Superfrog on 1.0: 0 of 3 622 080 px against
the reference in Chromium and WebKit, 0 dropped, object jitter 0.

1.2 (kit 0.9.2, Superfrog's KIT-GAPS 44-46 after its measurements on 1.1: 0 of 7 845 552 px against the reference over
worlds 1-7; the module's camera jitter 0.077 px against its old path's 0.057 came from the smoothing's lag and the
interpolation across a teleport): `jumpMax` (40 game px) - a camera, object or sprite that moves farther between two
frames is shown at the new place, not interpolated across (a teleport after a death crossed the map); `sprites[].id`
- the identity for the pairs when the sprite number is not one (the player and a one-line leftover of the same
sprite); `camMean { tau, shape }` - the terrain's camera as the symmetric mean of the clamped camera over t +- tau on
both axes, always (Superfrog's best measured smoothing: no lag, the corners at a turn rounded), replacing softClamp
and smoothY, while the sprites keep the original's screen position shifted only by the hard stop at a map edge.

1.3 (kit 0.9.3): `objects[].ox, oy` - the drawing's offset from the object's logical position. x, y must be the
position the game moves, not the drawing's corner: an animation shifts the corner by a few pixels, which the
interpolation would take for motion (Superfrog measured 0.84-2.5 px per frame on the screen instead of 1.25).
Superfrog on 1.2 (camMean 20, pairOlder 2, level 1, 30 s, a loaded machine): 0 dropped of 1 774, camera jitter
0.032 px against its old path's 0.052, objects 0, 0 of 2 535 456 px against the reference.

1.4 (kit 0.9.4): `hud.under = true` draws the HUD rows before the sprites, so a sprite reaching into them shows
above the HUD as the hardware draws it (Superfrog's frog hangs with its head across the HUD for 61 frames at every
level entry); `sprites[].x, y` are the hardware position of the occurrence with the image carrying its blank
columns and rows (the box of the visible pixels moves with the animation and interpolated the halves of a
two-sprite player apart); only real sprite occurrences with stable ids belong in `sprites[]`, a diff layer goes
into `window.over`.

1.5 (kit 0.9.8, from the Codex Superfrog rebuild's renderer): `subpixel = true` moves the playfield by fractions of a
device pixel. A 50 Hz game on a 60 Hz display at zoom 2 scrolls 1.67 device px per display frame, which whole
pixels show as 2, 2, 1, 2, 2, 1 (at zoom 1: 1, 1, 1, 1, 1, 0 - a stand-still every sixth frame); the measurement
does not count that as jitter, the eye may. With the option the playfield (window and map) is drawn one device
pixel wider and taller at the camera snapped to whole device pixels, then into the band shifted by the remaining
fraction as a blend of the four neighbouring device pixels - integer weights /256 on both the GPU (a mode-3 pass
over an own texture) and the reference (`subBlend`), so the 0-mismatch check holds: a magnified-sharp picture
moved by a fraction, not a bilinear magnification; an edge softens by one device pixel, the interior of a game
pixel stays flat. Objects, sprites and the HUD keep their whole-device-pixel positions relative to the view's
camera: a player the camera tracks stands still on the screen (shifting them with the playfield would make it
wobble by up to half a pixel in a sawtooth), an object standing on the ground may wobble by that much against
the smoothly moving ground instead - the trade the blind test on Superfrog decides (the games put the option
behind a Debug switch; `scene.opts.subpixel` can change at run time). On a 50 or 100 Hz display, or when the
camera lands on the device grid, the picture is identical to the plain drawing.
Superfrog's switch (kit 0.9.8, Debug "Posun A / B" with a reveal button, the letter drawn once per browser, the
default without the shift): replay of Enhanced on the scene module with the shift, 1000 frames with a route, EQUAL
at the four rates and the same fingerprint as without it. KIT-GAPS 50 (0.9.9): the shift's own texture was made on
unit 0 under the window's, so the page's first draw into it formed a feedback loop (GL_INVALID_OPERATION once, 1 of
14 974 calls); it is now made and sized on its own unit; the synthetic page's `compare()` reports `glErr`.

1.6 (kit 0.9.10, from the Alien Breed SE92 rebuild's comparison with the kit): under `subpixel` the objects are
drawn into the shifted picture, so an object standing on the ground moves with it as the game drew it, its edges
blending like the ground's; an object the camera tracks - a player that is a blitter object, Alien Breed II -
is marked `objects[].steady` and stays on whole device pixels relative to the view's camera, as all objects did
in 1.5 (shifted with the ground it would wobble by up to half a pixel in a sawtooth as the fraction crosses the
rounding). Sprites (hardware sprites: Superfrog's frog, Alien Breed SE92's player) and the HUD stay on whole
pixels. `WBSCENE.unexplained(rec, gameIdx)` is Alien Breed SE92's check of the model against the game's own
picture as a pure function: the clean window, the map through its holes and the record's objects at their
positions against what the game really drew (win.w x win.h indices) -> `{ over, count, model }`; `over` is
`window.over` (the game's pixels where the model differs, drawn over the window and moving with the camera, so
nothing the model does not know is lost), `count` how well the model knows the game (Alien Breed SE92: under
10 px per frame). The project passes the objects the game had drawn when it captured the picture; hardware
sprites are not in it.
Superfrog on 1.6 (ce085bf, no code change - the frog is a hardware sprite, no object is tracked): 0 differing
pixels of 1.09-1.27 M in pause and, with a real fraction under a virtual 144 Hz clock (S = 3, dpr 2, weights up
to 229/256), 0 of 1 629 936 in each of 7 checks; 0 GL errors of 40 044 draws; replay with the shift EQUAL over
1000 frames with the fingerprint of before. The "newest frame is N ms behind ts" warning fires once when the
page pauses the game while the display clock runs on - expected there, not a fault.

Alien Breed II on 1.6 (its move to the scene module, the old path behind a Debug switch): the engine's scene record
composed as `reference()` at the record's camera equals its own composition at 0 mismatches in 11 levels (about
2000 frames a level, 300-450 M pixels) once its one addition - the muzzle flash moved with the player - is done on
the page after `compose()` and handed to `draw(..., comp)` as a steady object; in Chromium `read()` against the
reference 0 of 19 checks walking the map with the shift on; a record costs about 0.13 ms a game frame; its players
are hardware sprites, so no object is marked steady. G56 (1.6.1, kit 0.9.11): `draw()` uploaded only B's
`map.dirty`, so a frame with dirty slots that was never B (two game frames between two display frames) left those
slots stale in the atlas texture; `frame()` now collects every frame's dirty slots and `draw()` uploads the union.

1.7 (kit 0.9.12, the inventory's clean-up): `extrapolateObjects` (passes the objects may run past the last pass when
the next 25 Hz pass has not come; default = `extrapolate`, which stays for the camera) - Alien Breed II's engine
did this, so its objects' latency could stay a fixed 40 ms where the kit adapted 60-120; now the kit does the same
and wb-takt 1.3 is fixed by default; `jumpMax` still guards a wrong guess. The widened HUD rows are cached on the
HUD object (the same rgba, split and width give the same picture; uploaded once) - they were rebuilt and uploaded
every draw. A map narrower than the view is centred on a whole game pixel (floor), as Alien Breed II's engine
does (the half pixel made one column of difference). `softClamp` and `smoothY` warn once as deprecated - `camMean`
replaced them in 1.2 and no game sets them; they go away in 1.0.

The mode transition (planned for the scene module, 1.6; the Codex Superfrog rebuild's recipe: one presentational
state - the viewport's size, the scale, the CRT, the display's latency - interpolated by smoothstep over 450 ms,
a real intermediate viewport drawn every display frame, the latency blended so the picture does not jerk at the
end, the CRT dimmed to 40 % with its pattern switched once in the middle). Superfrog built the CRT part into
its own transition first (6ff23f6) and measured two rules the kit's module must keep: the pattern's pitch comes
from the whole-number scale of a mode, never from `Math.round` of the intermediate scale (it re-tuned in the
first half and made moire); the pattern is the source mode's in the first half and the target mode's in the
second - exactly two patterns per transition, and the end of the transition is the settled pattern (taking the
detail from the wrong side made the CRT jump at the end); a mode without CRT keeps the other's pattern all along.

2.5 (kit 1.0.28, Xenon 2 KIT-GAP 8): a game with a parallax background - two scrolling layers drawn into one 4-plane
picture (Xenon 2: the coral in bitplanes 0-1, a ring of 192 rows copied every pass and moving a row every 2 passes; the
tiles in bitplanes 2-3, a row every pass) - gives the record `back: { cam, w, h, idx, origin, wrap }`: its own camera,
interpolated between frames at its own speed (or by camMean, the short way round a wrapped axis), shown where the window
and the map leave a hole, with the window's palette rows. `window.or` holds bits ORed onto what shows through a hole (the
stars in bitplanes 2-3 over the coral). Under the shift the back's device camera is rounded against the playfield's
fraction, so it lands within half a device pixel. The GPU equals the reference with it (`?back=1` on the synthetic page).

2.6 (kit 1.0.30, Xenon 2 KIT-GAP 10): camMean never averages across a jump - after a death Xenon 2 puts the camera back
109 px to its checkpoint, and the mean over +-tau spread that over frames of ~20 px (camera jitter 0.148 px, a step of 22.7);
the window is now clipped to the jump's side (the frames around B with no move over jumpMax between neighbours), for the
back layer too. `camMean.step` (the sampling of the mean, default 5 ms) is passed on; it had been ignored. Xenon 2 measured
step 1 better than 5 with tau = half its 59.9 ms pass.

2.7 (kit 1.0.33, Xenon 2 KIT-GAP 13): an object the game draws at one screen position (Xenon 2's boost countdown digit, at
(152, 160) every pass) flipped a device row about 17 times a second in Enhanced: it was drawn at its world position between
passes (at the objects' time, latO) less the view's camera (at the camera's time, latC, under camMean) - two times, two
smoothings. An object on the screen - by its pair (2.4) or by `objects[].screen` - now interpolates its SCREEN position (its world
position less its own frame's camera) and is drawn at round((ext + screen) * S), the same on both paths (objDev); with
`screen` it stays there also when the camera stood still between the pair, and under the shift it is not glued to the ground.

2.8 (kit 1.0.34, Xenon 2 KIT-GAP 14): `objects[].alpha` (0..1, default 1) - an object the game spawns in Xenon 2's experimental
band below the window fades in instead of appearing out of nothing. The alpha interpolates between the pair like the position, is
quantised once to a = round(alpha * 256) and blended after the palette lookup in RGB with whatever is below:
(below * (256 - a) + colour * a + 128) >> 8. On the GPU the pixels under the quad are copied (copyTexImage2D) and the shader blends
them in whole numbers, so the GPU equals the reference (Chromium and WebKit, 0 px, `?alpha=1` on the synthetic page); alpha 1 draws
byte for byte as before, alpha 0 not at all.

2.9 (kit 1.0.35, Xenon 2 KIT-GAP 11): Xenon 2's camera moves a row every 3-frame pass and its newest frame came a few ms after
the end of camMean's window (latC 28, tau 29.952); past the newest frame the value was carried by the last two frames' velocity -
0 or a whole row on that staircase - and the camera stepped 0.07 px unevenly (0.09 / 0.20 / 0.28 px with the newest frame 0 / 9 /
15 ms late in a simulation). The window past the newest frame is now the mean of the window that ends at the newest frame,
carried on by the slope over 2 tau: 0.0005 px at any of those delays. Where the window does not reach past the newest frame
(a page whose engine runs ahead) nothing changes. `scene.frame()` also starts a new history when a frame's time goes back: after
a clock reset the old frames kept the mean on the oldest camera for 280 ms (a 10-row step in Xenon 2's measurement).

2.10 (kit 1.0.37, Xenon 2 KIT-GAP 15): `objects[].scale = [sx, sy]` (default 1) and `objects[].anchor = [ax, ay]` (in the object's
own pixels, default [0, 0]: the point of the image that stays at (x + ox, y + oy)) - Xenon 2's GET READY line, which the game redraws
at 16 sizes one per 3-4 frames, can grow at the display's rate. The scale interpolates between the pair like the position; the quad
is round(w * sx * S) x round(h * sy * S) device px and each of its pixels shows the source pixel (i * w) div qw, whole numbers on
both paths, so the GPU equals the reference (`?scale=1`, Chromium and WebKit, 0 px, with the shift and with alpha too). Scale 1 draws
byte for byte as before; a first appearance is at its own scale; scale 0 not at all.

The synthetic page `scene-demo.html` (`arek web demo`, then `/scene-demo.html?s=2&pair=2&soft=1&smooth=1`; `?gl=0`
the 2D path; `?fine=1` the subpixel shift) runs a generated map, a clean window with decorations the map does not have and holes the map shows
through, three objects on a 25 Hz loop (one blinking), a sprite and HUD rows on the kit's clock; its hooks are
WBLONGRUN 1.4 and `wbSceneTest.compare()` (the GPU band against the reference). Tests: the pure parts in Node, the
GPU equality (0 of 114 688 and 458 752 pixels at S = 1 and 2, with and without the options, with the subpixel shift
at S = 2 and 3) and `arek web smooth`
over the page in Chromium (0 missing passes, camera and object jitter under the limit).

**2.13 (kit 1.0.68): the passes on the time of the game's computation (`passTime`, `rec.next`).** SWIV computes a pass
every 2 frames and swaps its buffers 1 to 4 frames later, in places after 3, 1, 3, 1 frames. The scene paired the
objects' passes by the frame a pass was first shown in, so an even 6 px step came out at 60 Hz as steps from -2.3 to
5 px a frame (a double step, a stand). Two things, both off unless the page asks:

- `passTime: true`: `rec.pass` is the time of the computation (ms on `rec.t`'s clock) and the passes are paired on it.
  The camera, the window, the sprites and the back layer stay on `rec.t` (the camera on the passes' axis was measured
  too: the same numbers).
- `rec.next = { pass, cam, objects: [{ id, x, y }] }`: the pass the game has computed and not shown yet. Its positions
  are in the game's RAM before its picture exists; the scene makes it one more pass - the last pass's pictures at
  next's positions - so the objects need not wait for the swap. Read it where the game's logic is done (a mark at the
  pc where drawing begins), not at the frame's end: SWIV's RAM at the end of the frame of the computation had 124 of
  6 562 positions of the pass before (the logic had not finished); from the start of drawing 0 of 14 285.

The page adds one constant D to every pass time. A pass is known some ms after its time, and with D = 0 the scene runs
past the newest pass by the last velocity for a part of every pass: right for a steady flight, an overshoot for
whatever starts, stops or turns. Measured in SWIV (60 Hz, latency 40 ms, mean change of the step in px a frame; all
objects / the player / one helicopter, frames 4100-4400 and 4200-5200):

| | 4100-4400 | 4200-5200 |
|---|---|---|
| before | 0.218 / 0.072 / 0.324 | 0.284 / 0.499 / 0.361 |
| passTime + next, D = 0 | 0.140 / 0.139 / 0.224 | 0.324 / 0.559 / 0.331 |
| D = 30 ms | 0.176 / 0.087 / 0.215 | 0.270 / 0.484 / 0.323 |

D = 30 ms was the smallest that put the long stretch under the numbers before for the objects and the player; objects
on the ground stayed at 0.000 px against the background in every variant. `passTime` without `next` needs a latency
that covers the wait for the swap and was worse than before. The synthetic rhythm in the tests (a pass every 2 frames,
shown after 3, 1, 3, 1): before -2.33 .. 5.00 px a frame, `passTime` + `next` 2.50 flat.

**2.14 (kit 1.0.75): the objects' own unevenness (`objMean`).** With the passes on their time SWIV's helicopters still
knock: the game itself moves them by whole pixels a pass, unevenly (dy 0, -1, 1, -1, 1, 0, 1, 0, 1, 0, 2 ... while
accelerating, dx 1, 1, 1, 1, 2 in a cycle of 5). `objMean: { tau, step }` takes every object's WORLD position as the
mean over its own passes within tau ms of the objects' time (`windowMean` on the pass axis, `rec.next` included) - the
camera's `camMean` for each object. Per object only an unbroken row of passes counts: the row ends where its id is
missing, where it jumps farther than `jumpMax`, and where its `run` changes (optional, any value the page sets: another
picture set, a new life). A ground target stands (the mean of one position); an axis anchored on the screen, `screen`
and `steady` objects are left alone. Measured in SWIV (60 Hz, latency 40 ms, passTime, D = 30 ms; mean change of the
step in px a frame of the objects anchored to the world, y / x; the camera's own 0.009):

| | 4100-4400 | 4200-5200 | helicopter (set 4) |
|---|---|---|---|
| without | 0.198 / 0.102 | 0.258 / 0.128 | 0.215 / 0.134 |
| tau 33 ms | 0.137 / 0.071 | | 0.158 / 0.095 |
| tau 50 ms | 0.133 / 0.059 | 0.212 / 0.087 | 0.158 / 0.083 |
| a line fitted through the passes, 100 ms | 0.091 / 0.062 | 0.234 / 0.103 | 0.165 / 0.090 |

tau 50 (a little over one pass each side) is the setting to start from; the fitted line won the short stretch and lost
the long one (turns), so it is not offered. The player (on the screen) is unchanged. A wider window lags behind a
turn: past the newest pass the mean is carried by the last slope, as `camMean` does.

**2.15 (kit 1.0.76): the parts of one thing (`objects[].group`).** SWIV's helicopters are several objects - one per
part of the node's picture, a blade part drawn only every other pass, a copy in the band below the window. A part that
was not there in the pass before had no pair and was drawn where it is while the body slid: the helicopter split, at
diagonal motion visibly (fuzz_23 4100-4400, 60 Hz: 272 splits >= 0.5 px in 350 display frames, up to 5.3 px; with
`objMean` 578, since parts with rows of different length average apart; the player's parts too, up to 3.7 px).
`group` (any value) names the parts of one thing: the first paired part of a group leads and every other part takes
its shift from its own record's position, on both axes and for parts on the screen too - the group moves as one
piece. SWIV with group = the node (the shadow apart): 0 splits, with and without `objMean`, with and without the band.
A game that can merge the parts into one picture should; `group` is for parts that cannot be merged (the window's
part and the band's part of one node).

**2.16 (kit 1.0.78): the page's latencies and the loop without a browser (wb-takt 1.7, `wb-pagesim.js` 1.0).** The numbers
of 2.13-2.15 were composed with every record present at its own time. A page never has that: a frame's record exists
when the engine has computed it, and an engine thread in a browser is slower than the same wasm in Node. SWIV (Chromium
headless, ANGLE Metal, 60 Hz): the engine thread 14-16 ms a game frame against 4.3 ms in Node (5.7 with the scene
recorder; Node under `taskpolicy -b`, the efficiency cores, 12.7 ms); a frame's record reached the scene 26 ms (median,
max 94) after `stamp(n + 1)`; with `ahead` 2 the game lost 133 frames' times; 620 of 2701 display frames drew the objects
past their newest pass, and the helicopters stepped back 2.5-10 px - the knocking of "Enhanced", not `objMean`.

The objects' latency has to cover the pass period and the record's lateness. With P the pass period, D the page's
constant added to a pass time (2.13) and L how long after its pass time a pass reaches the page (its record's arrival -
`takt.late()` measures it against the frame's time - less D, less where the logic ends inside its frame): between two
passes the newest one is P + L old at most, so without extrapolation `latO >= P + L` at a high percentile of L, not its
median; with `objMean` the window's future half (tau) is carried by the slope unless latO covers it as well. SWIV (P 40,
D 30, records 46 ms after their frame's time) chose `ahead 4, latC 50, latO 76`. In its own simulation of the page's loop
(set 4, the engine 5 ms / 15 ms / 15 ms with stalls) the objects' jitter went from 0.175 / 0.213 / 0.302 (ahead 2, 30 / 40)
to 0.114 / 0.124 / 0.141, with 0-1 back steps. latC adds to the key latency: check `arek web smooth`'s 70 ms.

`wb-pagesim.js` is that simulation for every game (taken from SWIV's tools/m9/page_sim.js, whose run of the same game
with the browser's record arrivals put 48 386 object positions where the browser had them, 0 apart): the clock grants as
in the page, an engine model computes a frame in the given ms (a number, a range, a function; occasional stalls), the
page's own `feed(n, takt)` makes the record when frame n is done, and compose draws every display frame. Its samples are
WBLONGRUN's, so `arek web smooth --samples` judges the browser's measure on them. In the kit's synthetic game (a pass
every 2 frames, uneven 4 / 8 px steps, passTime + next, D 30; 1500 game frames at 60 Hz): an engine of 5 ms gives 0 frames past the newest pass and 0
back steps at latO 40; 12-18 ms with 5 % stalls of 40 ms gives records 20 ms late (max 107), 243 of 1720 frames past the
pass and 97 back steps; latO 76 with ahead 4 takes most of it back. Tune latC / latO / ahead there, then confirm in the
browser.

**2.17 (kit 1.0.79, SWIV KIT-GAP 13): an object's own latency (`objects[].lead`).** One objects' latency for all objects
makes the enemies' smoothness cost the player's response: SWIV's key -> drawn player was latO + 0-10 ms (39 ms at latO 40,
80 ms at 76 - the original's own 80 ms). `lead` (ms, optional, per object) composes that object at the objects' time +
lead from its own pair of passes (`rec.next` included, past the newest pass by `extrapolateObjects`, objMean's window and
the screen anchors at that time); give it to every part of a group alike. Measured in SWIV's page loop (its records,
frames 4100-5200, 60 Hz, ahead 4, latC 50, latO 76, the engine 5 / 15 ms; a reversal of the player's x in `rec.next` to
the first drawn step in the new direction, median):

| | player reversal -> picture | player jitter | player back steps | set 4 jitter y / x |
|---|---|---|---|---|
| no lead, 5 ms | 50 ms | 0.365 | 3 of 457 | 0.116 / 0.055 |
| lead 36 on the player, 5 ms | 17 ms | 0.418 | 17 of 461 | 0.116 / 0.055 |
| no lead, 15 ms | 33 ms | 0.370 | 4 of 460 | 0.138 / 0.061 |
| lead 36 on the player, 15 ms | 0 ms | 0.446 | 17 of 475 | 0.138 / 0.061 |
| ahead 2, 30 / 40, 15 ms (before) | 0 ms | 0.454 | 14 of 482 | 0.248 / 0.107 |

The player with a lead is the player of the old latency - its response and its knocks - while the enemies keep the new
smoothness; the trade is the page's (SWIV: a Debug switch). A player's shots drawn without the player's lead start up to
the lead's motion behind its nose; give them the same lead.

## I. The scene recorder (`arek_scene.h` + `wb-scenerec.js`, kit 1.0.77) - one hint instead of a recorder per game

Until 1.0.77 every game wrote its own scene record for G: SWIV's `src/swiv_scene.c` (307 lines: its buffers, its node list,
the PCs of its blits) and `web/sw_rec.js`, Xenon 2's and Alien Breed II's the same way. The kit's host now records the
scene from what the game does to the hardware and asks the game for one thing it cannot see: where an object is.

- **What the kit finds itself** (`arek_scene.h`, from the display model's new `ard_fetch_cb` and the hooks the host had):
  the window and the palette of every row as the display used them; the playfield's planes and what lies above them
  (a line with more planes than most - SWIV's fifth plane - or outside the playfield's chain = the HUD, one object fixed on
  the screen); the camera from the chain of plane-0 addresses through a ring of rows (learnt from the pointer reloaded to
  the ring's start inside the window, per buffer) - the window's top row unwrapped over the frames; the objects from the
  blits masked by A (a cookie-cut with B, a shadow or flash without it, also SWIV's shadow `D = A & C` with an inverted
  mask), placed by plane, row and column in the shown ring - the rows the window does not show and the margin that is
  the next row's left edge included, all parts of one call one picture; the clean playfield from the word under the first
  object blit, kept until a restore or a copy writes the word; which objects a frame shows from the words' generations
  (a restore makes them new, another object over a part does not); the hardware sprites by line.
- **The hint** (`ArsConf`): `obj_pc` the first instruction of the routine that draws one object (its blits happen with
  the stack at or under the entry's, its return ends the object), `obj_reg` the register with the object's address,
  `obj_x` / `obj_y` the offsets of its logical position (the one the game moves), `obj_img` its picture word (wb-scene's
  `run`); optional `pass_pc` (where a pass starts: passTime), `logic_pc` (where the logic is done: `rec.next` from the
  objects' own fields), `cam_x` / `cam_y` (the game's camera words, read there: the next pass's camera, so an object the
  game keeps on the screen stays there). SWIV: `{ 0x12dcc, a0, 12, 14, 10, 0x15fec, 0x13834, 0, 0x25b2 }`.
- **The page**: `WBSCENEREC.reader(Module).rec(n)`, `toScene(r, st, lut, { runOf })` - wb-scene's record (the clean window
  and its palettes, `over` = what the record does not explain, objects at their logical position with the drawing's
  offset, `group` per object and kind, the HUD object, the sprites) - and `nextOf(r, sc, st)` for `rec.next`.
- **Not covered** (the record's `reason`): hires, dual playfield, HAM and EHB lines (2); a playfield whose ring the kit has
  not seen wrap yet (1) - a linear buffer, a screen redrawn by copying, a horizontal ring: the next games will show what
  to add. Line-mode blits are ignored; a CPU's drawing into the buffer stays in the window and, where it covers an
  object, in `over`.

Measured on SWIV (city, fuzz_23, frames 4200-5200; SWIV's own recorder and the kit's in one engine, the scene with SWIV's
page options at 60 Hz):

| | SWIV's recorder | the kit's |
|---|---|---|
| valid frames | 1000 | 1000 |
| camera | - | SWIV's + one constant in every frame |
| objects at SWIV's place to the pixel | - | 14 181 (19 more wholly in the margin or the hidden rows, placed at the nearer edge) |
| pixels the record does not explain | 72 | 0 |
| wb-scene motion, 42 common objects (y / x px) | equal to three decimals | equal to three decimals |
| mean over the objects | 0.159 / 0.103 (its HUD counted) | 0.157 / 0.101 (2 small objects SWIV leaves in its window) |

On the way the kit learnt three things SWIV had shown: a shadow cut with `D = A & C` is a mask too; ownership by whole
words lost a helicopter under the player's 16 px (the generations do not); the frame's pass is the one most of its objects
come from (SWIV draws a piece of the next pass into the shown buffer - one frame with the newest pass's time made four
helicopters 0.03-0.05 px rougher). Synthetic test: `tests/test_host_scene.py` (two rings scrolled by the Copper, restores,
a picture in two parts, a shadow, a picture across the left edge, pictures cut by the ring's end and the window, a score
line in a fifth plane: the composition equals the shown picture to the pixel, the camera keeps its row, every object
where it was drawn), and the web side on the same record.

## H. The display never touches the game (`arek web replay`, kit 0.9.6) - done

A page replayed under a virtual clock: `requestAnimationFrame` and `performance.now` are replaced before the page's
scripts run, the tool ticks the clock at 50, 60, 120 and 144 Hz (any list) with the same inputs scheduled by GAME
frame, and reads the page's own fingerprint of the game state after N game frames. Equal fingerprints across the
rates prove that the number of display frames drawn between two game frames - the interpolation, a mode transition,
a sub-pixel shift, any presentation option - changes nothing in the game; a difference names the rate. The run
needs no display and is as fast as the page computes (the Codex Superfrog rebuild verified its renderer this way:
500-tick replays at four controlled rates with one hash of the final state).

    arek web replay http://127.0.0.1:8920/scene-demo.html --hz 50,60,120,144 --frames 300 --route 1:120,2:60,0:120

The page's hooks (`WBLONGRUN` 1.5, beside those of F): `done()` the game frames computed so far; `state()` a string
fingerprint of the game's state (a hash of its RAM, or of what moves: the camera and the objects); `inputs([[frame,
mask], ...])` (optional) holds the keys `mask` from game frame `frame` on - a page without it is replayed without
input. The hooks may return promises (the tool awaits them). A page whose engine runs in a worker (Superfrog, kit
0.9.7): `done()` waits until the worker has computed every frame the clock permitted and reports at most one more
than the last call, `state()` is the fingerprint of exactly that frame from the ring in shared memory - otherwise
the worker runs past N and the fingerprints differ by rate. `prepare()` must return only once the game runs from a
verified set of disks: Superfrog's first DIFFERS was one byte, the game had started before the page verified its
last disk, and a click on a still-disabled button hung the next context. Measured: Superfrog Original and Enhanced,
300 frames with a route, EQUAL at the four rates; Enhanced on the scene module EQUAL over 1000; without the route
a different fingerprint, so the inputs take. Alien Breed II (kit 0.9.8, f668692): 300 frames with a route, EQUAL at
the four rates in Chromium (300 / 360 / 719 / 863 display frames) and the same fingerprint in WebKit; no route and
another route give other fingerprints. Its hooks: under the virtual clock the page grants the game at most one
frame per rAF round (ahead 1, so exactly N frames at every rate, never N + 1); the keys come from the schedule by
game frame instead of the keyboard; `prepare()` jumps to level 1 ticking the virtual clock itself at a fixed 20 ms,
so every rate starts from the same point, and `done()` counts from the end of the jump; `state()` is FNV-1a 32 over
chip RAM and slow RAM plus the frame number; the coroutine engine suffices. The tool reads `done()` and `state()` in
one call (kit 0.9.13): the fingerprint belongs to the frame `done()` reports - Superfrog's worker, a frame ahead under
`ahead`, answered 1001 to a second `done()` and the fingerprints differed by rate; a page keeps the two consistent
within one display frame, and the tool names the overshoot when the counts differ. The synthetic scene page implements all three; the kit's test replays
it with a route at the four rates (equal state, more display frames at the higher rates) and checks that the route
changes the state.

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
