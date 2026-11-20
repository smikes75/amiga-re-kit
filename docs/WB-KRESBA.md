# WB-KRESBA: drawing Enhanced from the game's state

Decision of 2026-11-17: **Original** stays the translated logic with the emulated chips (100 % parity, the measuring
base); **Enhanced** is the same exact translated logic with a renderer of its own that draws from the game's state - the
object list, the pictures' identities, the camera, the map, the graphics from the disk - the way a JavaScript rewrite
draws, instead of taking the chips' picture apart into objects again. Guessing from pixels (a rotor from black pixels,
a bullet's colours below the window, a HUD row's palette, a shadow's hole) is what went wrong in Enhanced; the state
does not need it. Gameplay that Enhanced has to change (a wider field, a band below the window) is a readable
replacement of the routines concerned, keyed by address, with an Original / Enhanced switch and a measurement.

SWIV did the first game (its `docs/RENDERER.md`, `docs/JS-OBRAZ.md`): at alpha 1 and the original window its picture
from the state is the original's pixel for pixel (objects, HUD, bullets 0 px in all 7 landscapes; the terrain differs
only where the game draws a crater one pass before it shows it), and its smoothness is better than the chips' picture
taken apart (object jitter 0.004-0.006 px against 0.05-0.09 px). `wb-kresba.js` is the general part of it.

## The layers

| layer | who | kit |
|---|---|---|
| the logic | the translation (`arek recomp`) | as for Original |
| the record of the state | the game's hooks into its own routines (draw routine, buffer swap, camera) | `arek_scene.h` / `wb-scenerec.js`, or the game's own record |
| the scene on the display's clock | interpolation by identity, the view's camera, the pair of passes | `wb-scene.js` (`compose`) |
| **the drawing** | **the terrain, the objects by their picture, the foreground cover, shadows, flashes, the palette per row, extras** | **`wb-kresba.js`** |
| the monitor | CRT, the knobs | `wb-obraz.js` (`present({ source })`) |
| the chips' picture | not needed in Enhanced | `engine_picture(0)` (1.0.86) |

## The adapter (what a game gives)

```js
const K = WBKRESBA.create(document);
const game = {
  terrain(wy, x0, w, out) {...},   // palette indices of world row wy from world column x0 (the game's buffer where it drew into
                                   // the ground, its map elsewhere); false = nothing there
  cover(wy, x0, w, out) {...},     // 1 where the foreground covers (the game's foreground plane, its map's attribute)
  frame(ob) {...},                 // the object's picture by its identity: { pix, w, h, ox, oy, key } (the disk's graphics, a frame
                                   // the game builds at run time read from RAM); null = the composition's own pixels
  skip(ob), behind(ob), op(ob),    // not drawn / behind the foreground / 1 shadow, 2 flash (shadowColour, flashColour)
  after(ob, put),                  // extras after the object at its anchor (SWIV's rotor disc)
  indices(tidx, v), ground(ctx, v), top(ctx, v),   // stage hooks: stamps into the terrain, water over it, overlays
};
const { pos, ms } = K.paint(ctx, scene.compose(ts, view), S, game, { blend: true, subpixel: true, soft: 1 });
presenter.present({ source: ctx.canvas, rect: [0, 0, W, H] });
```

- The view is `c.W x c.H` game px from `c.cam` (compose() gives the view's top-left, the window at `ext` inside it; 1.0 took
  `ext` off once more - with margins the picture was `ext` px off, 1.1 fixed it); the camera may be fractional on both axes (SWIV scrolls vertically,
  Turrican II both ways). With `blend` a fraction is two whole-pixel layers per axis mixed by the fraction - sharp
  pixels, even motion; without it the nearest device pixel.
- The palette: `c.win.pal` rows from `c.win.palTop`. An object with the ground takes the rows of the world rows it
  covers, an object fixed on the screen those of its screen rows (wb-scene 2.19); an image is recoloured only when one of
  ITS colours changes on its rows (SWIV: a pulsing colour elsewhere refilled the cache every 4 frames).
- Behind the foreground: the object is drawn at its fractional position into a layer and the cover is cut out of it in
  the terrain's grid (SWIV: on the device grid the objects behind stood still 31-34 per mille, websmooth 1.11).
- `pos` is where each object was really drawn (world px of its logical anchor) for `arek web smooth`'s objs, `ms` the
  paint's time for `WBLONGRUN.drawMs`.

## 1.1 (kit 1.0.100): margins, sprites, the game's window

- `c.cam` from `compose()` is the view's top-left (the window sits at `ext` inside it). 1.0 subtracted `ext` again; a page
  with margins (Turrican II: 72 / 48 px) got the whole picture `ext` px off. SWIV has no margins and was not affected.
- The hardware sprites `c.sprs` are drawn after the objects exactly as `WBSCENE.reference` draws them: lower `k` on top, on
  the screen or with the ground per axis (wb-scene 2.4), a sprite fixed on the screen (`screen: true`, a HUD badge in a
  corner) with the palette of its screen rows. `opt.sprites: false` leaves them out (a game that draws them as objects).
- `opt.window`: `'over'` puts `c.win.over` (what the game drew that the state does not explain) into the terrain's indices,
  `'all'` first `c.win.idx` (at `window.origin`, its rows) and then `c.win.over` - frame B's raster in the world grid, as the
  reference's playfield; after `game.indices`, below the objects, not interpolated. A page drawing from the state keeps it
  as its safety net and counts what it shows. Not drawn: `c.back`, `c.win.or`, `c.hud`.

## Checks

- `tests/test_wb_kresba.py`: at a whole camera, alpha 1 and whole device pixels the drawing is wb-scene's reference
  picture pixel for pixel (Chromium), also with margins, two sprites (one on the screen) and the window layer (1.1); the shadow and flash colours of the row, the cover, the extras with the object's
  rows, a fractional camera on y and on x (each device pixel the mean of its two rows / columns).
- SWIV (kit session, its page read-only): every 10th paint of its `sw_draw.js` painted again by `wb-kresba.js` with an
  adapter made of `sw_draw`'s own rules - the numbers are in the CHANGELOG of 1.0.87.

## Next

Turrican II: its adapter (the 14-byte BOB descriptor as the identity, frames from the disk 83 %, built at run time and read
from RAM 16 %, the terrain from the tile map in live RAM, parallax), and the wider field's spawner / removal / collisions
as routine replacements instead of `patch_ext.py`.
