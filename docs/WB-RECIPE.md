# WB-RECIPE - the display layer of the kit for a new game, on one page (kit 1.0)

The canon `WB-PLYNULOST.md` says WHY every piece is as it is, with the measurements behind it. This page says WHAT a
game writes. The contract is frozen at kit 1.0: wb-takt 1.4, wb-obraz 1.6, wb-scene 2.1 (kit 1.0.2), wb-obraz 1.7 (kit 1.0.3), wb-scene 2.2 (kit 1.0.17: window.palTop), wb-menu 1.0 + wb.css (kit 1.0.17: the Workbench bar), wb-scene 2.3 (kit 1.0.18: palAnchor, objects with the ground), wb-scene 2.4 (kit 1.0.19: the anchor per pair), wb-scene 2.5 / 2.6 (kit 1.0.28 / 1.0.30: the back layer, camMean not across a jump), wb-obraz 1.8 (kit 1.0.32: `new Screen(game, canvas, { crtEnhanced: 'original' })` - a game whose Enhanced only smooths the motion draws the Original CRT in both modes), wb-scene 2.7 / 2.8 / 2.9 / 2.10 (kit 1.0.33 / 1.0.34 / 1.0.35 / 1.0.37: objects on the screen stand still, objects[].screen; objects[].alpha; camMean past the newest frame, a new history when time goes back; objects[].scale, anchor), wb-scene 2.13 (kit 1.0.68: `passTime` and `rec.next` - the objects' passes on the time of the game's computation; off unless set), wb-scene 2.14 (kit 1.0.75: `objMean` - an object's world position as the mean over its passes; off unless set), wb-scene 2.15 (kit 1.0.76: `objects[].group` - the parts of one thing move as one piece), wb-scenerec 1.0 (kit 1.0.77: the host's scene recorder `arek_scene.h` as wb-scene's record - the window, the objects, the HUD and rec.next from the hardware with one hint of the game; WB-PLYNULOST.md I), wb-takt 1.7 + wb-pagesim 1.0 (kit 1.0.78: `takt.late()`, the page's loop without a browser; WB-PLYNULOST.md 2.16), wb-scene 2.16 (kit 1.0.79: `objects[].lead`, an object's own latency - the player nearer to the keys than the enemies; WB-PLYNULOST.md 2.17), wb-scene 2.19 (kit 1.0.85: an object or a sprite fixed on the screen takes the palette of its screen row, not of the world row under it; WB-PLYNULOST.md 2.21), wb-kresba 1.0 (kit 1.0.87: Enhanced drawn from the game's state - the composition's terrain, objects by their picture, foreground cover, shadows, flashes and extras on a 2D canvas, the game's adapter says where they are; WB-KRESBA.md), wb-kresba 1.1 (kit 1.0.100: the view starts at compose()'s `cam` - 1.0 drew a view with margins `ext` px off; the hardware sprites `c.sprs` drawn as `WBSCENE.reference` draws them; `opt.window`: 'over' / 'all' puts the game's own window picture into the terrain in frame B's raster - a safety net for what the state does not explain; `opt.sprites: false` leaves the sprites out), wb-kresba 1.2 (kit 1.0.101: a composition with `palScreen` - wb-scene `palAnchor: 'screen'` - is coloured as the reference colours it, every device row by its screen row: the terrain at device rows, objects and sprites by the screen rows they are drawn on), wb-obraz 1.10 (kit 1.0.88: the CRT in Enhanced without the darkened edges - `Screen.crt()` sets `--crt-edge` 0 on the game element, so a page's own copy of the vignette rule obeys too; `new Screen(game, canvas, { edgeEnhanced: true })` keeps them; `info().crtEdge`), wb-obraz 1.11 (kit 1.0.91: `zoomSteps(W0, W, dpr, limit, par)` - the exact zooms for wb-nastaveni's `spec.zoomSteps`; `watchDpr(fn)` - a devicePixelRatio change, a monitor of another scale; zoom 0 is called 'auto'), wb-obraz 1.12 (kit 1.0.92: a stepless zoom - `stepless(zoom, W0, W, dpr, limit, par)` -> `{ S, shrink }`, the game drawn at the whole S and the presenter's last pass shrinks it linearly, `size(..., shrink)`, `crt({ ..., shrink })`: the canvas stays its backing, the Original CRT keeps one line per game row), wb-pad 1.0 (kit 1.0.89: gamepads and joysticks - `WBPAD.create({ players })`, `poll()` once a frame gives each player's joystick bits (right 1, left 2, up 4, down 8, fire 16, or the page's `bits`); 'auto' gives player 1 the first controller and player 2 the next; per player a fire button and an up (jump) button; `rows()` are wb-nastaveni 1.4 rows, `fromMenu()` applies them, `status()` names the controllers), wb-pad 1.1 (kit 1.0.90: 'auto' gives player 1 the device used first and player 2 the next one used, never a device nobody used (a receiver resting with an axis at -1) nor the twin of another player's device (one controller listed twice, first used in the same poll, until the two differ for 10 polls); `status()` reads the devices itself and names their slots and the unused ones; `create({ reserve: [1] })` + `button(i, n)` for a page's own buttons (Turrican: B = Space); a chosen fire button does nothing else), wb-nastaveni 1.3 (kit 1.0.68: `spec.omit`, rows a page leaves out), wb-nastaveni 1.4 (kit 1.0.84: `spec.rows`, the game's own rows - select, check, range, button; per mode or for both, only in some modes, only while another row has a value, marked "changes the game", a section of its own such as Debug into `spec.hosts`), wb-nastaveni 1.5 (kit 1.0.91: with `zoom: 'snap'` buttons under the slider - 'auto' and the exact zooms from 1x up; 'auto' (0) is the default of a page that gives none; a zoom the player has not chosen follows the page's default (`zoomOwn` in the store), wb-nastaveni 1.6 (kit 1.0.92: `spec.stepless` + `spec.zoomFit()` - the row 'Stepless zoom', off by default; on, the slider runs 1x .. the window in 0.01 steps, an exact zoom within 0.04 catches it), wb-nastaveni 1.7 + wb.css 1.1 (kit 1.0.97: compact menus - a panel at most 400 px wide (a long note wraps instead of stretching it over the game), dense rows, `.mode-picker` on one line, the six colour rows in a folded group 'Colours' (`spec.groups: false` keeps them open), CRT detail / shape only while CRT is on, and while a row is adjusted the panel turns see-through but for that row (`wb-peek`, `spec.peek: false` turns it off); keep a page's notes in a panel short - one or two lines), wb-mixer 1.0 (kit 1.0.93: the sound mixer window - `WBMIXER.build(host, { groups, defaults, store })`, once a frame `apply(E._engine_aud_mix)` and `lights(counts)`; the game's hook tags each sound with its kind at its start, `host_aud_tag(ch, kind)` - kind i on Paula, 32 + i on an extra voice; Original all 100 %), wb-mixer 1.1 (kit 1.0.94: `headroom` - Enhanced plays every channel at that base level, `WBMIXER.VAMIGA` = 0.4096 is vAmiga's level (the kit's Paula is 7.75 dB louder), so a mix tuned there behaves the same under the limiter; `apply` sends it as `engine_aud_mix(-1, base)`, 1 in Original; `forget()` after a new engine), wb-zvuk-worklet 1.1 (kit 1.0.93: a dropout holds the last level and fades it, 100 ms, back with a 5 ms crossfade), wb-pagesim 1.1 (kit 1.0.84: `player(c)`, the samples' sixth element), wb-vtr 1.0 (kit 1.0.84: VTR2 records from JavaScript - a rewrite that has no RAM of the original projects its fields onto the original's addresses for `arek trace compare`), wb-zvuk
1.1, WBLONGRUN 1.5; it changes only for a gap a game measures (KIT-GAPS), never for a new idea - those wait after 1.0.
(Revised with Alien Breed SE92's notes from its migration, R1-R15.)

## The ten lines

```js
// the clock: the display's tep grants the game its frames, gives them times and the pairs for the interpolation
// fps: the game's measured frame - PAL 312 lines x 227 CCK x 8 / 28.37516 MHz = 19.968 ms = 50.08 Hz (at 50.0 the sound
// drifts five frames a minute); allow(n): an engine in a thread wakes on it, a coroutine on the main thread runs its
// frames right there: `allow: (n) => { while (done < n) step(); }`
const takt = WBTAKT.create({ fps: 50.08, ahead: 2, latC: 20 /* 30 with a coroutine engine */, latO: 40, lock: 'auto', allow: (n) => engine_allow(n) });
// the presenter: ONE canvas (<canvas id="screen"> before <canvas class="crt-layer"> in .game), WebGL2 or 2D, the CRT above it;
// no border on the canvas (the presenter sets its CSS size; a 1 px border with border-box resamples the picture by 2 px)
// (wb.css draws no frame around it since kit 1.0.66; `arek web test` checks the canvas's content box against its backing)
const pr = new WBOBRAZ.Presenter(document.getElementById('screen'), { gl: 'auto' });
const screen = new WBOBRAZ.Screen(document.querySelector('.game'), pr.canvas);
// the scene: one record per game frame in, the composition out - into the presenter's framebuffer, nowhere else
const scene = new WBSCENE.Scene({ takt, camMean: { tau: 20 }, pairOlder: 2, extrapolateObjects: 1, jumpMax: 40 });
scene.attach(pr);
// every game frame (the engine finished frame n):
scene.frame({ n, t: takt.stamp(n), pass: tOfThePass, cam, limits, window: { w, h, idx, pal, over }, map, objects, sprites, hud });
takt.pass(tOfThePass);                                       // when the game's drawing pass (the 25 Hz loop) completed
//   pass = the time t of the frame in which the game's drawing pass COMPLETED (the objects of that record are the positions
//   that pass drew); a frame without a new pass repeats the previous pass time; the module pairs objects by it
// every display frame:
takt.tick(ts, engine_done(), paused);
pr.present({ draw: scene.drawer(ts, view) });                // view = { W, H, S, extX, extY, x0, y0 } of the mode
//   W = win.w + 2 extX, H = win.h + 2 extY; x0, y0 = the band's top-left in the presenter's framebuffer in device px: y0 =
//   the top HUD's rows x S (an odd window width stays odd: extX whole); the presenter sized W x (H + HUD rows) at S
//   without WebGL2 the page composes at S = 1 and gives present({pixels}) the W x H reference (the presenter scales);
//   the Original mode may instead show the game's exact picture through present({pixels}) - the scene is for the wider view
//   (`engine_rgb` after `engine_dac(1)`, once after the engine loads: the colours as the Amiga's converter gives them, the same as
//   the scene's x17 - without it the picture is vAmiga's monitor, darker by 25 of 255 on average; a Node tool that compares hashes: open(dir, { dac: true }))
//   view.hudY = [top, bottom] (device px of each HUD row's top-left) when a transition cuts the view out fractionally
```

The sound: an engine in a thread (`arek host engine --thread`, the page served with COOP / COEP) writes its ring in
shared memory, `WBZVUKOUT.bind({ sab, ring, n, widx, ridx })` plays it through the kit's worklet with a 30 ms reserve;
the thread computes on without a permit under 15 ms of reserve. Without shared memory `out.push(int16LR)` per frame.

## The record (what the game knows, in world coordinates)

| field | what | rule |
|---|---|---|
| `cam`, `limits` | the game's camera and where it may go | the view clamps; a narrow map is centred on a whole pixel |
| `window.idx`, `pal` | the CLEAN window: indices (255 = none), a palette row per line | without the objects and sprites the game blits - from a restore bitmap or a clean buffer; `palTop` (2.2): `pal` may hold extra rows for the margins, `palTop` of them above the window - a margin row takes `clamp(wy - winY + palTop, 0, rows - 1)`, so a copper gradient continues past the window; without it the margins take the edge rows; the Scene option `palAnchor: 'screen'` (2.3) keeps the palette rows on the screen rows of the game's camera between frames (a gradient fixed to the screen does not saw under a vertical scroll), the default `'window'` moves them with frame B's picture |
| `window.over` | what the game drew over the window and the record cannot name | `WBSCENE.unexplained(rec, gameIdx)` finds it - give it only the objects the GAME drew, not the page's additions; one layer per record, not interpolated; what the game clips (an object cut at the window's edge) is the game's, over cannot hide it |
| `map` | atlas (up to 1024 slots of 16 x 16 in a 512 x 512 texture) + cells (0xffff = no tile: black, not the palette's colour 0 - give that colour its own slot), `gen`, `dirty` slots | the margins beyond the window; the kit uploads every frame's dirty slots |
| `objects[]` | `id`, `x, y` the LOGICAL position, `ox, oy` the drawing's offset, `w, h, idx`, `pass` | interpolated between PASSES; `steady` for one the camera tracks (a player that is a blitter object): it stays on the screen; the others are anchored per pair and axis (2.4): the same world position in both frames = with the ground in whole device pixels, the same screen position = on the screen (under `subpixel` the objects go into the shifted picture by `steady` as in 1.6) |
| `sprites[]` | `k`, `id`, `x, y` the hardware position, `h, idx` | interpolated between frames; `screen: true` for one fixed on the screen; anchored per pair and axis like the objects (2.4): a sprite standing in the world goes with the ground, one holding its hardware position while the world moves stays on the screen - a player sprite needs no flag; `freshSprites` draws them from the newest frame; only occurrences the hardware would SHOW - a sprite parked beyond the display window (HSTART past the window) stays out, the kit does not clip to the DIW |
| `hud` | `top / bottom: { h, rgba, split }`, `under` | widened or narrowed by the splits - a split is the column that REPEATS (the cut column itself, 0-based), not the one before it; `under` when a sprite may reach into the HUD rows; the colour channels (RGB 50-150 %) and the palette belong to the record's `pal` - the page recolours the palette, not the frames |

Rules that are not options: a camera, object or sprite that jumps more than `jumpMax` (40 px) is shown at the new
place, not crossed; a frame without a new pass for `passMax` (100 ms) counts as a pass; an older pass after a newer
one is ignored; after a jump or a restart `takt.reset(done)`; the atlas `dirty` of a frame never drawn is still
uploaded; the view's camera is never left of the map's edge.

## The decisions a game makes (each behind a Debug switch until the author chooses)

| option | what it trades | who chose what |
|---|---|---|
| `subpixel` | even motion on a 60 / 144 Hz display against sharp edges on whole pixels | Superfrog off (a platformer at zoom 3), Alien Breed II on (top-down) |
| the mode transition | the presenter's (wb-obraz, 450 ms smoothstep): ONE scale for the whole transition - the larger mode's - the canvas at the larger view, the viewport cropped in device pixels (fractions through the shift), the display size by CSS only while it runs; the CRT's pattern from a mode's whole scale, the source's in the first half, the target's in the second, dipped to 40 % | never a fractional scale per frame nor a presenter resize per frame (G60: the kit's 0.9.15 transition did both and shimmered) |
| the player's latency | the sprite moves WITH its ground - a player drawn from a newer frame than the ground leads it at every start, stop and turn and sinks into walls (G60: 0.9.16 freshSprites, 10-15 ms, removed) | the clock's latC is the whole budget |
| `latC` / `latO` | less display delay against missing pairs (extrapolation fills them); latO >= the pass period + how late a pass reaches the page (`takt.late()`, a high percentile), + objMean's tau to avoid its slope - measure in `wb-pagesim.js` with the browser's engine speed, not with records at their own time (WB-PLYNULOST.md 2.16) | 20 / 40 with a thread, 28 / 48 Superfrog, 50 / 76 + ahead 4 SWIV (engine thread 14-16 ms a frame in Chromium) |
| `lock` | one game frame per k display frames on a k x 50 Hz display | 'auto' |

## The hooks the page gives (`globalThis.WBLONGRUN`)

`ready()`, `cam()`, `objs()`, `scale()`, `missing()`, `ahead()`, `audio()`, `status()`, `keys`, `prepare()`, `route`,
`interp()`, `player()` (`[x, y]` or `[x, y, image]` - a player the camera tracks exactly never moves on the screen, it changes its picture first, so give the image as the third value) for `arek web smooth` (the canon's limits: 0 dropped frames, jitter < 0.05 px, 0 % missing,
key -> camera <= 70 ms, 0 sound dropouts under stalls); `done()`, `state()`, `inputs()` for `arek web replay` (the
same game state at 50, 60, 120 and 144 Hz). `wbObrazTest.set / fill / gl` for `arek web test` (the presenter's
geometry, the CRT, one canvas under the CRT layer).

    arek web test URL --quick        # the presenter's contract
    arek web smooth URL --gpu        # the canon's limits
    arek web replay URL --hz 50,60,120,144 --frames 300 --route 1:120,2:60,0:120
    scene.read() against WBSCENE.reference(composition)   # 0 mismatches at any time, any scale
    # (the reference is a CPU composition of the whole band - run the check on its own, not during a smoothness measurement: it drops a frame)

## The page's life (kit 1.0.41)

- **A lost WebGL context** (a phone in the background, a GPU switch): the presenter asks for it back and rebuilds
  itself, the scene attaches again - the page only keeps presenting. While it is gone `presenter.lost` is true and
  `present()` returns false; `presenter.onLost(fn)` / `onRestore(fn)` for a note or a pause.
- **A hidden tab**: rAF stops, the sound and an engine thread do not. `WBTAKT.lifecycle({ onHide, onShow(ms) })` - pause
  the game and suspend the AudioContext in `onHide`; in `onShow` resume, then `takt.reset(done)`, `scene.reset()` and
  `out.flush()`, as after any restart.
- **Keys**: `WBTAKT.keyboard()` leaves a key pressed with Cmd / Ctrl / Alt to the browser and releases every key when
  Meta goes up, the window loses the focus or the page is hidden. A page with its own key code needs the same three.
  A modifier the map names (`ControlLeft: 16` for fire) is the game's key and so are the mapped keys pressed with it
  (wb-takt 1.6, kit 1.0.66; before, the keydown of Control carried its own flag and never went down).
- **Sound, messages mode**: `out.push(view)` keeps the caller's buffer unless the view is the whole of a plain
  ArrayBuffer - a view into the engine's memory can be pushed as it is.
- **The modules in the game's folder**: `arek web copy DIR` writes `wb-kit.json`; `arek web copy DIR --check` says per
  file current / stale (which kit it came from) / modified / own, and exits 1 unless all are current or the page's
  own. A kit file the game edited is kept (`--force` replaces it). Run the check in the game's build.

## The Workbench bar (wb-menu.js + wb.css, kit 1.0.17)

The bar of Alien Breed II and Superfrog on arek.fun: Project / Display / Game / Sound / ? at the top, the menus
suspend the game while open, requesters for About and Help, a notice line. `arek web copy` brings both files (a
page's own copy is kept; `--force` replaces it). The page writes the markup, the module only opens and closes it:

```html
<link rel="stylesheet" href="wb.css">
<main id="shell">
  <nav id="wbbar" aria-label="Main menu"><span class="wbname">Game · rebuild</span>
    <div class="wbmenu"><button id="menu-project" class="wbtitle" type="button" aria-expanded="false">Project</button>
      <div id="project-panel" class="wbpanel" hidden><button class="wbitem" type="button" data-close-menu>Start game</button></div></div>
    <!-- Display / Game / Sound the same; the Display and Sound panels hold WBNASTAVENI's sections -->
    <div id="wbstatus"><output id="status"></output><output id="wbnotice" hidden></output></div>
    <button id="help-open" class="wbtitle" type="button">?</button><span id="run-state">Enhanced</span><span class="wbgadget"></span></nav>
  <div id="stage"><div class="game"><canvas id="screen"></canvas><canvas class="crt-layer"></canvas></div></div>
  <div id="help-shade" class="requester-shade" hidden><section class="wbwin requester"><div class="wbwtitle"><h2>Help</h2>
    <button type="button" data-close-dialog>×</button></div><p>…</p></section></div>   <!-- requesters inside #shell -->
</main>
<script src="wb-menu.js"></script>
```

```js
const shell = new WbMenu.Shell(document.getElementById('shell'), { suspend: () => { menuPause = true; }, restore: () => { menuPause = false; canvas.focus(); } });
document.getElementById('help-open').onclick = () => shell.openDialog('help-shade');
// the game's keys: none while shell.busy or WbMenu.editable(e.target); shell.message('Saved') for a short notice
```

## What the kit does not do (yet)

A screen of another size than the game's window (a hires 640-px title, an interlude, a terminal) goes through
`pr.present({ source | pixels + size: [w, h], rect: [x, y, w, h] /* game px of the content */, smooth })` (wb-obraz
1.7, kit 1.0.3: nearest by whole numbers, or linear with `smooth`; the rest black; present again after a `size()`).
A transparent object (a fade-in) and a HUD at another scale than the playfield stay the page's (Alien Breed SE92's
G1 and G2 - the author decided against them in the kit).

## What is not in the kit on purpose

An automatic high-score save, a muzzle flash moved with the player, spawner previews, a fade-in of enemies at the
window's edge: game knowledge, on the page after `compose()` (`draw(ts, view, fbo, d, comp)` takes a composition
the page changed). Run-ahead (a frame computed ahead with the held input) is an experiment for after 1.0.
