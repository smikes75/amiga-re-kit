// wb-scene.js 2.8 - the scene of a rebuild on the display's clock (amiga-re-kit, docs/WB-PLYNULOST.md, module G, kit 0.9.0; 1.1 kit 0.9.1
// after Superfrog's switch - KIT-GAPS 40-43: screen-fixed sprites, the means over the interpolated camera, a layer of
// drawings without identity, a guard for a pass that never changes, one timebase; 1.2 kit 0.9.2 - KIT-GAPS 44-46: no
// interpolation across a jump, sprites[].id, camMean for both axes; 1.3 kit 0.9.3 - objects[].ox/oy, the drawing's offset
// from the logical position; 1.4 kit 0.9.4 - hud.under: the sprites above the HUD rows as the hardware draws them; 1.5 kit
// 0.9.8 - subpixel: the playfield shifted by the fraction of a device pixel, the motion even on a 60 / 144 Hz display;
// 1.6 kit 0.9.10 - under subpixel the objects move with the playfield unless objects[].steady, unexplained() - the window's
// pixels the model does not explain, for window.over; 1.6.1 kit 0.9.11 - the atlas slots of every frame since the last
// draw are uploaded, not only B's (Alien Breed II G56); 1.7 kit 0.9.12 - extrapolateObjects (the objects past the last
// pass, so latO can stay fixed - Alien Breed II's engine did it), the widened HUD cached, a narrow map centred on a
// whole game pixel, softClamp / smoothY deprecated; 1.8 kit 0.9.15 - any scale S (the device sizes rounded, the
// sampling by a float32 multiply on both paths); 2.0 kit 1.0 - the contract frozen, softClamp / smoothY removed; 2.0.1 kit 1.0.1 -
// a HUD wider than the view is narrowed at its splits (Superfrog KIT-GAPS 52); the sampling of the playfield and the images in
// whole numbers only on both paths - no float on the GPU (Alien Breed II G59: WebKit differed at S = 702 / 352); 2.1 kit 1.0.2 -
// transition() (0.9.15) and freshSprites (0.9.16) removed: the author found both counterproductive in every game (G60) - a
// mode transition keeps one scale and crops in device pixels (the presenter's), a player drawn ahead of its ground sinks
// into walls); 2.1.1 kit 1.0.3 - view.hudY: where the HUD rows go in device px when the view is cut out fractionally; 2.2 kit
// 1.0.17 - window.palTop (Turrican II KIT-GAP 24): pal may hold palette rows for the margins above and below the window too,
// so a game whose colours change per line (a copper gradient) shows them in the margins instead of the edge row's band;
// 2.3 kit 1.0.18 - palAnchor: 'screen' (Turrican II KIT-GAP 27: the palette rows stay on the screen rows of the game's
// camera between the frames, not with frame B's picture - a copper gradient no longer saws under a vertical scroll);
// without subpixel the objects but the steady ones go with the ground in whole device pixels, as under subpixel (KIT-GAP 28:
// round((x - cam) * S) against the ground's floor(cam * S) made a standing object shake by a device pixel); 2.4 kit 1.0.19 -
// the anchor per pair (Turrican II KIT-GAP 29): a sprite or object whose WORLD position is the same in both frames of its
// pair goes with the ground, one whose SCREEN position is the same stays on the screen - per axis, no flag needed (a player
// sprite stands on the screen while the camera tracks it and in the world while the camera coasts); steady still forces the screen
// (a game's own transition at one scale - Alien Breed SE92); 2.5 kit 1.0.28 - back (Xenon 2 KIT-GAP 8): a layer under the window with a
// camera of its own, a parallax background that interpolates between frames at its own speed; window.or: bits ORed onto it;
// 2.6 kit 1.0.30 - camMean never averages across a jump (Xenon 2 KIT-GAP 10: the camera put back 109 px at a checkpoint was
// spread over frames of ~20 px): the window is clipped to the jump's side; camMean.step is passed on (it was ignored);
// 2.7 kit 1.0.33 - an object on the screen stands still (Xenon 2 KIT-GAP 13: a countdown digit at a fixed screen position flipped
// a device row ~17 times a second): its SCREEN position is interpolated (its world position less its own frame's camera) and drawn
// at round((ext + screen) * S), not its world position less a camera taken at another time under another smoothing; objects[].screen
// = true marks an object fixed on the screen in every pass (also when the camera stood still between the pair);
// 2.8 kit 1.0.34 - objects[].alpha (Xenon 2 KIT-GAP 14: enemies the game spawns in an experimental band below the window fade in):
// interpolated between the pair like the position, quantised to a = round(alpha * 256), blended after the palette lookup in RGB
// with what is drawn below in whole numbers on both paths, (below * (256 - a) + colour * a + 128) >> 8; alpha 1 draws as before.
// Extracted from the Alien Breed II page (tools/web/gl.js, tools/host/view.h) with Superfrog's measured options
// (docs/POHYB-AUDIT.md, PLYNULOST-K4.md): one way to draw the wider, smoother view for every project.
//
// The project gives one RECORD per game frame (world coordinates in game pixels, the window = the original's playfield):
//   { n, t, pass,                        frame number, its time (wb-takt stamp, ms), the time of the drawing pass the
//                                        objects belong to (optional; frames of one pass share it - objects interpolate
//                                        between passes, the camera and the sprites between frames)
//     cam: [x, y],                       the game's camera: world position of the window's top-left
//     limits: { x0, x1, y0, y1},         the game's own camera range (the window never leaves it)
//     window: { w, h, idx, pal, over },  the window's CLEAN picture (no moving objects): idx = Uint8Array(w*h) colour
//                                        indices (255 = none, the map shows through), pal = Uint8Array(h*32*4) RGBA per row;
//                                        2.2: pal may hold rows = pal.length / 128 >= h rows with palTop (default 0) of
//                                        them above the window - the device row of game row wy takes palette row
//                                        clamp(wy - winY + palTop, 0, rows - 1); without palTop nothing changes;
//                                        over (1.1, optional) = Uint8Array(w*h) of what the game drew over it without an
//                                        object record (a popping score, a picked coin, the player in an interlude): shown
//                                        with the window, above the terrain and below the objects, not interpolated
//     back: { cam, w, h, idx, origin, wrap },   2.5, optional: a layer under the window and the map with a camera of its own
//                                        (a parallax background): cam = [x, y] its position shown at the window's top-left in
//                                        this frame, in its own pixels; idx = Uint8Array(w*h) (255 = none, black) with its
//                                        top-left at origin (default cam); wrap = 'x', 'y', 'xy' or true: the picture repeats
//                                        on that axis (a ring of rows - Xenon 2's coral, 192 rows), and the camera
//                                        interpolates the short way round. It shows where the window and the map have no
//                                        index, with the window's palette rows; window.or (optional) = Uint8Array(w*h) of bits
//                                        ORed onto what shows through a hole (stars ORed with the background: the index 0 when
//                                        nothing shows), below window.over
//     map: { gen, atlas, nslots, dirty, cols, rows, cells, origin },   optional, for the margins: atlas = Uint8Array(nslots*256)
//                                        16 x 16 tiles (32 per atlas row, 512 x 512 texture), gen changes when the atlas is
//                                        rebuilt, dirty = Uint16Array of slots changed since the last frame (null = none),
//                                        cells = Uint16Array(cols*rows) slot per 16 x 16 cell (0xffff = none), origin = [wx, wy]
//                                        world px of cell (0, 0)
//     objects: [{ id, key, w, h, idx, x, y, ox, oy }],   moving things drawn by the game's own records: id = identity
//                                        across frames (for the interpolation), key = a content key of the graphics (the
//                                        texture cache; the module computes fnv1a(idx) when absent), idx = Uint8Array(w*h)
//                                        (255 = transparent), x, y = the object's LOGICAL position in world px (fractions
//                                        allowed) - the position the game moves, not the drawing's corner (an animation shifts
//                                        the corner by a few px, which would interpolate as motion - Superfrog); ox, oy (1.3,
//                                        optional) = the drawing's offset from x, y, so the image need not carry blank pixels;
//                                        screen (2.7, optional) = true: fixed on the screen in every pass (a countdown digit
//                                        the game draws at one screen position), drawn at its screen position, never with the ground;
//                                        alpha (2.8, optional, 0..1, default 1) = blended with what is below it (a fade-in)
//     sprites: [{ k, h, idx, x, y, screen, id }],   hardware sprites of this frame: k = sprite number (lower on top), idx =
//                                        Uint8Array(16*h), x, y = the HARDWARE position of the occurrence (hs, vs) in screen px
//                                        relative to the window, the image carrying its blank columns and rows - not the box of
//                                        the visible pixels, which moves with the animation (Superfrog); screen = true (1.1): fixed
//                                        on the screen (a badge in a corner), so the clamp at a map edge does not move it;
//                                        id (1.2, optional) = the identity for the interpolation when k is not one (several
//                                        runs of the same sprite number: the player and a one-line leftover) - default k.
//                                        Only real sprite occurrences with stable ids belong here: pixels that merely differ
//                                        from the clean window (a diff layer) go into window.over, else they pair with a
//                                        real sprite of the same id and split it (Superfrog)
//     hud: { top: { h, rgba, split }, bottom: {...}, under } }   optional rows above / below the playfield: rgba = Uint8Array(w*h*4) of
//                                        the original's width, split = columns repeated to widen it (Alien Breed II: 6 cuts);
//                                        under = true (1.4): the HUD is drawn before the sprites, so a sprite reaching into the
//                                        HUD rows shows above them as the hardware draws it (Superfrog's frog at a level entry)
// The view: { W, H, S, extX, extY, x0, y0 } - the wider window (W = window.w + 2 extX, H = window.h + 2 extY), S device pixels
// per game pixel, x0 / y0 = where the view's top-left lands in the presenter's framebuffer (device px from the top).
// Options (all measured in Superfrog, off unless set): extrapolate (frames the camera may run past the newest pair when
// the next frame is missing, default 0), extrapolateObjects (1.7: passes the objects may run past the last pass, default
// = extrapolate; with 1 the objects keep moving when the next 25 Hz pass has not come, so the objects' latency can stay
// a fixed 40 ms instead of adapting up to 120 - a wrong guess is at most one pass and jumpMax still guards), jumpMax (1.2, default 40 game px: a camera, object or sprite that
// moves farther than that between two frames is not interpolated - a teleport after a death crossed the map), camMean
// { tau, shape } (1.2: the terrain's camera as the mean of the clamped camera over t +- tau on both axes, always, sampled
// every 5 ms - Superfrog's best measured smoothing, symmetric so without lag; it replaces softClamp and smoothY when set;
// the sprites keep their screen position as in the original, shifted only by the stop at a map edge; 2.0: softClamp and
// smoothY of 1.0 are gone - camMean replaced them in 1.2 and no game set them), pairOlder (a blinking sprite / object paired with up to n older
// frames), fixedAxis
// { axis, value } (a level whose camera axis is fixed: black outside), passMax (1.1, default 100 ms: when
// no new pass came for longer, every frame counts as a pass - an interlude drawn by other code), x17 (12-bit colours * 17),
// subpixel (1.5: the playfield is drawn at the camera snapped to whole device pixels and shifted by the remaining fraction
// as a blend of the four neighbouring device pixels - integer weights /256, the GPU and the reference bit for bit; a 50 Hz
// game on a 60 Hz display then scrolls 1.67 device px every frame instead of 2, 2, 1; an edge softens by one device pixel.
// 1.6: the objects are drawn into the shifted picture, so they sit on the ground as the game drew them (Alien Breed SE92's
// finding); an object the camera tracks - a player that is a blitter object, Alien Breed II - is marked objects[].steady and
// stays on whole device pixels relative to the view's camera (shifted with the ground it would wobble by up to half a pixel
// in a sawtooth); sprites and the HUD stay on whole pixels). 2.3: without subpixel too the objects but the steady ones go
// with the ground (at round(x * S) - the ground's whole device camera), so a standing object never shakes against it;
// 2.4: the anchor is decided per pair and axis for objects and sprites alike - the same world position in both frames =
// with the ground, the same screen position = on the screen (steady forces the screen; under subpixel the objects go into
// the shifted picture by steady as in 1.6, the sprites by the pair);
// palAnchor (2.3): 'window' (default) - a window row's palette row moves with frame B's picture; 'screen' - the palette
// rows stay on the screen rows of the game's camera between the frames (a copper gradient fixed to the screen).
// One timebase: ts of the drawer and rec.t must come from the same clock (the page's requestAnimationFrame timestamps and
// wb-takt's stamps are performance.now() based; a worker's absolute times must be converted) - the module warns once when
// the newest frame is more than 500 ms behind ts.
//
//   const scene = new WBSCENE.Scene({ takt, camMean: { tau: 20 }, pairOlder: 2, extrapolateObjects: 1 });
//   scene.attach(presenter);   per game frame: scene.frame(rec);   per display frame: presenter.present({ draw: scene.drawer(ts, view) })
//   scene.compose(ts, view) -> the composition the GPU draws, also as a CPU reference (WBSCENE.reference(c)) for a 0-mismatch test.
// Pure functions (Node too): lerp, clampCam, windowMean, pairById, fnv1a, x17, reference. No game data.
'use strict';
const WBSCENE = (() => {
    const VERSION = '2.8';
    const lerp = (a, b, f) => a + (b - a) * f;

    /** The camera of a view extX / extY wider than the window, inside the game's limits: the game's camera minus the
     *  extension, clamped to [x0 - extX .. x1 + extX] shrunk so that the view never shows beyond what the game's own
     *  camera range plus the margins allow; a map narrower than the view is centred (mapW = x1 - x0 + window w). */
    function clampCam(cx, cy, lim, win, ext) {
        const W = win.w + 2 * ext.x, H = win.h + 2 * ext.y;
        const mapW = lim.x1 - lim.x0 + win.w, mapH = lim.y1 - lim.y0 + win.h;
        let vx = cx - ext.x, vy = cy - ext.y;
        if (mapW <= W) vx = lim.x0 - Math.floor((W - mapW) / 2); else vx = Math.min(Math.max(vx, lim.x0), lim.x0 + mapW - W);   // 1.7: a narrow map centred on a whole game pixel (as Alien Breed II's engine)
        if (mapH <= H) vy = lim.y0 - Math.floor((H - mapH) / 2); else vy = Math.min(Math.max(vy, lim.y0), lim.y0 + mapH - H);
        return [vx, vy];
    }
    /** The mean of pick(frame) over the frames within tau ms of t; past the newest frame the newest value continues
     *  with the velocity of the last two frames for at most tau ms (Superfrog's soft clamp: the stop at a map edge is
     *  not a step 5 -> 2.3 -> 0). Returns null without frames. */
    /** pick(frame) interpolated at time s between the frames around s (frames in time order); before the first frame
     *  its value, past the newest the newest continued with the velocity of the last two frames for at most tau ms. */
    function valueAt(frames, s, pick, tau) {
        const n = frames.length; if (!n) return null;
        if (s <= frames[0].t) return pick(frames[0]);
        const last = frames[n - 1];
        if (s >= last.t) {
            const prev = n > 1 ? frames[n - 2] : null, v = prev && last.t > prev.t ? (pick(last) - pick(prev)) / (last.t - prev.t) : 0;
            return pick(last) + v * Math.min(s - last.t, tau);
        }
        let lo = 0, hi = n - 1;
        while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (frames[mid].t <= s) lo = mid; else hi = mid; }
        const a = frames[lo], b = frames[hi];
        return b.t > a.t ? lerp(pick(a), pick(b), (s - a.t) / (b.t - a.t)) : pick(b);
    }
    /** The mean of the interpolated pick over a window around t, sampled every `step` ms (1.1: the frames are 20 ms
     *  apart, a mean of the frames alone jumps as 2 or 3 of them fall into the window - Superfrog KIT-GAPS 41):
     *  shape 'box' = t - tau .. t + tau with equal weights (the soft clamp at a map edge); 'past' = t - tau .. t with a
     *  triangle weight rising to 1 at t (the vertical smoothing). Returns null without frames. */
    function windowMean(frames, t, tau, pick, opts) {
        if (!frames.length) return null;
        const step = (opts && opts.step) || 5, past = !!(opts && opts.shape === 'past');
        let sum = 0, wsum = 0;
        for (let s = t - tau; s <= (past ? t : t + tau) + 1e-9; s += step) {
            const w = past ? (s - (t - tau)) / tau : 1; if (w <= 0) continue;
            sum += w * valueAt(frames, s, pick, tau); wsum += w;
        }
        return wsum ? sum / wsum : valueAt(frames, t, pick, tau);
    }
    /** 2.6 (Xenon 2 KIT-GAP 10): the run of frames around B with no jump between neighbours - a mean over a time window is
     *  taken on B's side of a jump only, as the pair interpolation never crosses one. */
    function runOf(frames, B, isJump) {
        const i = frames.indexOf(B); if (i < 0) return frames;
        let lo = i, hi = i;
        while (lo > 0 && !isJump(frames[lo - 1], frames[lo])) lo--;
        while (hi < frames.length - 1 && !isJump(frames[hi], frames[hi + 1])) hi++;
        return lo === 0 && hi === frames.length - 1 ? frames : frames.slice(lo, hi + 1);
    }
    /** The pairs for the interpolation of things with an identity: for every item of b (by id) the same id in a, or in
     *  up to `older` frames before a (a blinking player drawn every other frame - Superfrog: paired 86 % -> 99.6 %).
     *  frames = [..., a2, a1, a] newest last. Returns [{ to, from, f }]: from = null when nothing pairs (drawn at `to`). */
    function pairById(a, b, f, items, older, history, fmax) {
        const top = fmax === undefined ? 1 : fmax;                                       // 1.7: past 1 when extrapolating
        const out = [];
        const byId = (list) => { const m = new Map(); for (const o of list || []) m.set(o.id, o); return m; };
        const ma = byId(a ? items(a) : []), olds = (older > 0 ? (history || []).slice(-older) : []).reverse().map((fr) => ({ fr, m: byId(items(fr)) }));
        for (const o of items(b)) {
            let from = ma.get(o.id), ff = f;
            if (!from) for (const h of olds) { const p = h.m.get(o.id); if (p) { from = p; ff = b.t > h.fr.t ? (lerp(a ? a.t : b.t, b.t, f) - h.fr.t) / (b.t - h.fr.t) : f; break; } }
            out.push({ to: o, from: from || null, f: from ? Math.min(Math.max(ff, 0), top) : 1 });
        }
        return out;
    }
    function fnv1a(bytes, seed) {
        let h = seed === undefined ? 0x811c9dc5 : seed >>> 0;
        for (let i = 0; i < bytes.length; i++) { h ^= bytes[i]; h = Math.imul(h, 0x01000193) >>> 0; }
        return h >>> 0;
    }
    /** A 12-bit Amiga colour as the DAC gives it: nibble * 17 (an emulator's monitor model darkens it - Alien Breed II). */
    function x17(c) { return [((c >> 8) & 15) * 17, ((c >> 4) & 15) * 17, (c & 15) * 17, 255]; }
    const SPLIT_DEFAULT = [];
    /** A HUD row widened from w0 to W by repeating columns at the split points (a panel's bars stretch, its numbers do not). */
    function widenColumns(w0, W, split) {
        const cols = new Int32Array(W); const cuts = (split && split.length ? split : SPLIT_DEFAULT).filter((c) => c > 0 && c < w0);
        const extra = W - w0; if (extra === 0) { for (let x = 0; x < W; x++) cols[x] = x; return cols; }
        if (extra < 0) {                                         // 2.0.1 (Superfrog KIT-GAPS 52): a view narrower than the HUD drops the columns after each cut, as the widening repeats them - not the right end
            const miss = -extra, n = cuts.length || 1, per = Math.floor(miss / n), rest = miss - per * n, cutAt = (i) => cuts.length ? cuts[i] : Math.floor(w0 / 2);
            let x = 0, k = 0, sx = 0;
            while (sx < w0 && x < W) { cols[x++] = sx; if (k < n && sx === cutAt(k)) { sx += per + (k < rest ? 1 : 0); k++; } sx++; }
            while (x < W) cols[x++] = w0 - 1;
            return cols;
        }
        const n = cuts.length || 1, per = Math.floor(extra / n), rest = extra - per * n; let x = 0, k = 0;
        for (let sx = 0; sx < w0; sx++) {
            cols[x++] = sx;
            if (k < n && sx === (cuts.length ? cuts[k] : Math.floor(w0 / 2))) { const rep = per + (k < rest ? 1 : 0); for (let i = 0; i < rep && x < W; i++) cols[x++] = sx; k++; }
        }
        while (x < W) cols[x++] = w0 - 1;
        return cols;
    }

    /** What is drawn in one display frame: the view camera, the window and map to show, the objects and sprites with
     *  their interpolated positions, the HUD. compose() builds it; the GPU and the reference draw it the same way. */
    function compose(frames, ts, view, opts, takt) {
        const o = opts || {}, ext = { x: view.extX || 0, y: view.extY || 0 };
        let tv = ts, tvO = ts, p, q;
        // the objects move with the game's drawing passes (a 25 Hz loop: every other frame): the pair for them is taken
        // among the first frames of the passes (rec.pass = the pass's time; without it every frame is a pass)
        let passes = []; let lastPass = null;
        for (const fr of frames) { const ps = fr.pass === undefined ? fr.t : fr.pass; if (ps !== lastPass) { passes.push(fr); lastPass = ps; } }
        const passMax = o.passMax === undefined ? 100 : o.passMax;
        if (frames.length && passMax > 0 && frames[frames.length - 1].t - passes[passes.length - 1].t > passMax) passes = frames;   // 1.1: no new pass for a while: every frame is one
        const extC = o.extrapolate || 0, extO = o.extrapolateObjects !== undefined ? o.extrapolateObjects : extC;   // 1.7
        if (takt) { const v = takt.view(ts); tv = v.tv; tvO = v.tvO; }
        if (takt) { p = takt.pair(frames, tv, extC > 0 ? true : undefined); q = takt.pair(passes, tvO, extO > 0 ? true : undefined); }
        else { p = pairOf(frames, tv); q = pairOf(passes, tvO); }
        if (!p) return null;
        const jumpMax = o.jumpMax === undefined ? 40 : o.jumpMax;
        const jumped = (u, v) => jumpMax > 0 && (Math.abs(u[0] - v[0]) > jumpMax || Math.abs(u[1] - v[1]) > jumpMax);
        const A = p.a, B = p.b || p.a;
        let f = Math.min(Math.max(p.f, 0), p.b ? 1 + extC : 0);
        if (p.b && jumped(A.cam, B.cam)) f = 1;                                   // 1.2 (KIT-GAPS 44): a jump is shown, not crossed
        const OA = q ? q.a : A, OB = q ? (q.b || q.a) : B, of = q ? Math.min(Math.max(q.f, 0), q.b ? 1 + extO : 0) : 0;
        const win = B.window, lim = B.limits;
        // the game's camera between the frames, the view's camera clamped; soft clamp and vertical smoothing as means over frames
        const gcam = [lerp(A.cam[0], B.cam[0], f), lerp(A.cam[1], B.cam[1], f)];
        let vcam = clampCam(gcam[0], gcam[1], lim, win, ext);
        if (o.fixedAxis) { if (o.fixedAxis.axis === 'y') vcam[1] = o.fixedAxis.value; else vcam[0] = o.fixedAxis.value; }
        const spriteCam = vcam.slice();
        const clampedOf = (fr, i) => clampCam(fr.cam[0], fr.cam[1], fr.limits, fr.window, ext)[i];
        if (o.camMean && o.camMean.tau > 0) {                                       // 1.2 (KIT-GAPS 46): the symmetric mean on both axes, always
            const sh = { shape: o.camMean.shape || 'box', step: o.camMean.step }, cl = clampCam(gcam[0], gcam[1], lim, win, ext);
            const run = runOf(frames, B, (u, v) => jumped(u.cam, v.cam));          // 2.6: not across a jump
            const mx = windowMean(run, tv, o.camMean.tau, (fr) => clampedOf(fr, 0), sh), my = windowMean(run, tv, o.camMean.tau, (fr) => clampedOf(fr, 1), sh);
            if (mx !== null) { vcam = [o.fixedAxis && o.fixedAxis.axis === 'x' ? vcam[0] : mx, o.fixedAxis && o.fixedAxis.axis === 'y' ? vcam[1] : my]; }
            spriteCam[0] = cl[0]; spriteCam[1] = cl[1];                             // the sprites: the original's screen position plus the hard stop at an edge
        }
        const history = passes.filter((fr) => fr.t < (OA ? OA.t : 0));
        const objs = pairById(OA, OB, of, (fr) => fr.objects || [], o.pairOlder || 0, history, 1 + extO).map((pr) => {
            const from = pr.from && !jumped([pr.from.x, pr.from.y], [pr.to.x, pr.to.y]) ? pr.from : null;
            const fc = from ? frameCam(passes, from, OA, 'objects') : null, tc = OB.cam;   // 2.4: the anchor per axis - the same screen position (and not the same world one) = on the screen
            const screen = !!pr.to.screen;                                          // 2.7: fixed on the screen, said by the record
            const sx = screen || !!pr.to.steady || (!!from && from.x !== pr.to.x && from.x - fc[0] === pr.to.x - tc[0]), sy = screen || !!pr.to.steady || (!!from && from.y !== pr.to.y && from.y - fc[1] === pr.to.y - tc[1]);
            const scr = from ? [lerp(from.x - fc[0], pr.to.x - tc[0], pr.f), lerp(from.y - fc[1], pr.to.y - tc[1], pr.f)] : [pr.to.x - tc[0], pr.to.y - tc[1]];   // 2.7: on the screen, between its own frames
            const al = (o) => (o.alpha === undefined ? 1 : Math.min(Math.max(o.alpha, 0), 1)), alpha = from ? lerp(al(from), al(pr.to), Math.min(Math.max(pr.f, 0), 1)) : al(pr.to);
            return { o: pr.to, x: from ? lerp(from.x, pr.to.x, pr.f) : pr.to.x, y: from ? lerp(from.y, pr.to.y, pr.f) : pr.to.y, sx, sy, scr, screen, a: Math.round(alpha * 256) }; });   // 2.8: a /256
        const shist = frames.filter((fr) => fr.t < A.t);
        const sprs = pairById(A, B, f, (fr) => (fr.sprites || []).map((s) => Object.assign({ id: s.id !== undefined ? s.id : s.k }, s)), o.pairOlder || 0, shist, 1 + extC).map((pr) => {
            if (pr.to.screen) return { s: pr.to, x: vcam[0] + ext.x + pr.to.x, y: vcam[1] + ext.y + pr.to.y, screen: true, sx: true, sy: true };   // 1.1: fixed on the screen
            // screen px relative to the window -> world (window of its own frame) -> the view; a jump is not crossed (1.2)
            const fc = pr.from ? frameCam(frames, pr.from, A) : null, fw = fc ? [pr.from.x + fc[0], pr.from.y + fc[1]] : null, tw = [pr.to.x + B.cam[0], pr.to.y + B.cam[1]];
            const from = fw && !jumped(fw, tw) ? fw : null;
            const sx = !!from && pr.from.x === pr.to.x && from[0] !== tw[0], sy = !!from && pr.from.y === pr.to.y && from[1] !== tw[1];   // 2.4 (KIT-GAP 29): on the screen only when the hardware position held and the world one moved
            return { s: pr.to, x: from ? lerp(from[0], tw[0], pr.f) : tw[0], y: from ? lerp(from[1], tw[1], pr.f) : tw[1], sx, sy };
        });
        const sub = subOf(vcam, view.S || 1, o);
        return { A, B, f, OA, OB, of, cam: vcam, spriteCam, gcam, win, map: B.map || null, limits: lim, objs, sprs, hud: B.hud || null, back: backOf(frames, A, B, f, tv, o, ext, view.S || 1, sub, jumped),
                 W: win.w + 2 * ext.x, H: win.h + 2 * ext.y, S: view.S || 1, ext, fixed: o.fixedAxis || null, n: B.n, sub,
                 palScreen: o.palAnchor === 'screen' ? Math.round(gcam[1] - vcam[1]) : null };   // 2.3 (KIT-GAP 27): the band row of the game's screen row 0
    }
    /** 2.5 (Xenon 2 KIT-GAP 8): the back layer's camera at display time - between the frames as the window's (the same pair
     *  and fraction, or camMean's window), on a wrapped axis the short way round, less the view's margins - and in whole
     *  device pixels: floor(cam * S), or under subpixel round(cam * S - the playfield's fraction), since the picture it is
     *  drawn into is shifted by that fraction afterwards (the background within half a device pixel). */
    function backOf(frames, A, B, f, tv, o, ext, S, sub, jumped) {
        const bk = B.back; if (!bk) return null;
        const wrap = wrapOf(bk.wrap);
        const near = (fr, i) => { const v = fr.back ? fr.back.cam[i] : bk.cam[i]; if (!wrap[i]) return v; const per = i ? bk.h : bk.w, d = ((v - bk.cam[i]) % per + per) % per; return bk.cam[i] + (d > per / 2 ? d - per : d); };
        let bc;
        if (o.camMean && o.camMean.tau > 0) {
            const sh = { shape: o.camMean.shape || 'box', step: o.camMean.step }, nb = (fr) => [near(fr, 0), near(fr, 1)];
            const run = runOf(frames, B, (u, v) => jumped(u.cam, v.cam) || (!!u.back && !!v.back && jumped(nb(u), nb(v))));   // 2.6
            bc = [windowMean(run, tv, o.camMean.tau, (fr) => near(fr, 0), sh), windowMean(run, tv, o.camMean.tau, (fr) => near(fr, 1), sh)];
        }
        else { const fa = A.back ? [near(A, 0), near(A, 1)] : null, from = fa && !jumped(fa, bk.cam) ? fa : bk.cam; bc = [lerp(from[0], bk.cam[0], f), lerp(from[1], bk.cam[1], f)]; }
        bc = [bc[0] - ext.x, bc[1] - ext.y];
        const d = sub ? [Math.round(bc[0] * S - sub.w[0] / 256), Math.round(bc[1] * S - sub.w[1] / 256)] : [Math.floor(bc[0] * S), Math.floor(bc[1] * S)];
        return { rec: bk, cam: bc, d, origin: bk.origin || bk.cam, wrap };
    }
    function wrapOf(wr) { return [wr === true || wr === 'x' || wr === 'xy', wr === true || wr === 'y' || wr === 'xy']; }
    /** The back layer's index at its game pixel (gx, gy), 255 outside a picture that does not wrap. */
    function backIdx(back, gx, gy) {
        const bk = back.rec; let x = gx - back.origin[0], y = gy - back.origin[1];
        if (back.wrap[0]) x = ((x % bk.w) + bk.w) % bk.w;
        if (back.wrap[1]) y = ((y % bk.h) + bk.h) % bk.h;
        return x >= 0 && y >= 0 && x < bk.w && y < bk.h ? bk.idx[y * bk.w + x] : 255;
    }
    /** 1.5: the playfield's camera snapped to whole device pixels and the remaining fraction as weights /256 (x, y). */
    function subOf(cam, S, o) {
        if (!o.subpixel) return null;
        const d = [cam[0] * S, cam[1] * S], i = [Math.floor(d[0]), Math.floor(d[1])];
        return { cam: [i[0] / S, i[1] / S], d: i, w: [Math.round((d[0] - i[0]) * 256), Math.round((d[1] - i[1]) * 256)] };
    }
    function frameCam(frames, item, fallback, key) { key = key || 'sprites'; for (const fr of frames) if (fr[key] && fr[key].indexOf(item) >= 0) return fr.cam; return fallback.cam; }
    /** The pair around time t without wb-takt: the two frames around t, f in [0, 1] (or > 1 past the newest). */
    function pairOf(frames, t) {
        if (!frames.length) return null;
        let a = frames[0], b = null;
        for (const fr of frames) { if (fr.t <= t) a = fr; else { b = fr; break; } }
        if (!b) { const i = frames.indexOf(a); if (i > 0) { const pa = frames[i - 1]; return { a: pa, b: a, f: a.t > pa.t ? (t - pa.t) / (a.t - pa.t) : 1 }; } return { a, b: null, f: 0 }; }
        return { a, b, f: b.t > a.t ? (t - a.t) / (b.t - a.t) : 0 };
    }

    /** The reference: the composition drawn on the CPU at S device pixels per game pixel, RGBA rows top-down, W*S x H*S
     *  (the playfield band only). The same rules as the shader: a device pixel shows the game pixel floor(px / S + cam);
     *  the window's clean picture where it has an index, the map's tile elsewhere, black outside; then the objects at
     *  round((x - cam) * S) (255 transparent, the palette row of the window row under it), then the sprites, lower k on top.
     *  With c.sub (1.5) the playfield is drawn one device pixel wider and taller at the snapped camera and blended by the
     *  weights; the objects and sprites go on top at the view's camera as before. */
    function reference(c) {
        const S = c.S, Wd = Math.round(c.W * S), Hd = Math.round(c.H * S);
        const obXY = (ob) => [ob.x + (ob.o.ox || 0), ob.y + (ob.o.oy || 0)];        // 1.3: the drawing's offset from the logical position
        let out;
        const camd = c.sub ? c.sub.d : [Math.floor(c.cam[0] * S), Math.floor(c.cam[1] * S)];   // 2.0.1 (G59): the camera in whole device pixels - the only camera the sampling sees
        if (c.sub) {                                                                 // 1.6: the objects into the shifted picture, the steady ones after it
            const Wm = Wd + 1, Hm = Hd + 1, mid = playfield(c, camd, Wm, Hm), b = blitter(c, mid, c.sub.cam, camd, Wm, Hm);
            for (const ob of c.objs) if (!ob.o.steady && !ob.screen) b(ob.o.idx, ob.o.w, ob.o.h, ...obXY(ob), undefined, undefined, undefined, ob.a);   // 2.7: not the ones fixed on the screen
            out = subBlend(mid, Wd, Hd, c.sub.w);
        } else out = playfield(c, camd, Wd, Hd);
        const blit = blitter(c, out, c.cam, camd, Wd, Hd);
        for (const ob of c.objs) if (ob.o.steady || ob.screen || !c.sub) blit(ob.o.idx, ob.o.w, ob.o.h, 0, 0, 0, 0, objDev(c, ob, camd), ob.a);   // 2.3 / 2.4 / 2.7: the anchor per axis from compose()
        const sprs = c.sprs.slice().sort((p, q) => q.s.k - p.s.k);
        for (const sp of sprs) { const dx = sp.screen ? 0 : c.cam[0] - c.spriteCam[0], dy = sp.screen ? 0 : c.cam[1] - c.spriteCam[1];   // on the screen: at the sprites' camera; with the ground: at the view's
            blit(sp.s.idx, 16, sp.s.h, sp.sx ? sp.x + dx : sp.x, sp.sy ? sp.y + dy : sp.y, sp.sx, sp.sy); }
        return out;
    }
    /** blit(idx, w, h, x, y) into out (Wd x Hd at camera cam): the image at round((x - cam) * S) (255 transparent), the
     *  palette row of the window row under the device row - as the shader's mode 1; sx / sy (2.4, per axis): true = on the
     *  screen at round((x - cam) * S), false = with the ground at round(x * S) - camd, the device pixels the playfield moves by;
     *  undefined = on the screen when cam is given. */
    function blitter(c, out, cam, camd, Wd, Hd) {
        const S = c.S, win = c.win, winY = c.B.cam[1], bandH = c.H, bandHd = Math.round(c.H * S);
        const gameY = (dy) => Math.floor((dy + camd[1]) * bandH / bandHd);           // 2.0.1 (G59): whole numbers only, as the shader
        const palTop = win.palTop | 0, palRows = win.palTop == null ? win.h : Math.max(1, (win.pal.length / 128) | 0);   // 2.2 (KIT-GAP 24): the margins' own rows
        const scr = c.palScreen == null ? null : c.palScreen;                      // 2.3 (KIT-GAP 27): the band row minus the screen's offset
        const palRow = (wy, dy) => Math.min(Math.max((scr === null ? wy - winY : Math.floor(dy * bandH / bandHd) - scr) + palTop, 0), palRows - 1);
        const put = (dx, dy, idx, row) => { const p = (dy * Wd + dx) * 4, q = (row * 32 + idx) * 4; out[p] = win.pal[q]; out[p + 1] = win.pal[q + 1]; out[p + 2] = win.pal[q + 2]; out[p + 3] = 255; };
        const mix = (dx, dy, idx, row, a) => { const p = (dy * Wd + dx) * 4, q = (row * 32 + idx) * 4;   // 2.8: (below * (256 - a) + colour * a + 128) >> 8
            for (let k = 0; k < 3; k++) out[p + k] = (out[p + k] * (256 - a) + win.pal[q + k] * a + 128) >> 8; out[p + 3] = 255; };
        return (idx, w, h, x, y, sx, sy, dev, a) => {                                // 1.8: the quad round(w * S) x round(h * S); its device pixel (i, j) shows image pixel (i * w) div qw
            if (a !== undefined && a <= 0) return;
            if (sx === undefined) sx = !!cam; if (sy === undefined) sy = !!cam;
            const q = quadOf(w, h, S), dx0 = dev ? dev[0] : sx ? Math.round((x - cam[0]) * S) : Math.round(x * S) - camd[0], dy0 = dev ? dev[1] : sy ? Math.round((y - cam[1]) * S) : Math.round(y * S) - camd[1];   // 2.7: dev = the quad's place given
            for (let j = 0; j < q.h; j++) { const dy = dy0 + j; if (dy < 0 || dy >= Hd) continue; const row = Math.floor(j * h / q.h) * w;
                for (let i = 0; i < q.w; i++) { const dx = dx0 + i; if (dx < 0 || dx >= Wd) continue;
                    const v = idx[row + Math.floor(i * w / q.w)]; if (v === 255) continue;
                    if (a !== undefined && a < 256) mix(dx, dy, v, palRow(gameY(dy), dy), a); else put(dx, dy, v, palRow(gameY(dy), dy)); } }
        };
    }
    /** 2.7: an object's quad position in band device pixels, the same on both paths: steady = at round((x - cam) * S) (1.6);
     *  on the screen (by its pair or objects[].screen) = at round((ext + its interpolated screen position) * S), so an object
     *  the game draws at one screen position stands still (Xenon 2 KIT-GAP 13); with the ground = round(x * S) - camd. */
    function objDev(c, ob, camd) {
        const S = c.S, ox = ob.o.ox || 0, oy = ob.o.oy || 0, X = ob.x + ox, Y = ob.y + oy, ext = c.ext || { x: 0, y: 0 };
        const at = (i, v, off, on) => ob.o.steady ? Math.round((v - c.cam[i]) * S) : on ? Math.round(((i ? ext.y : ext.x) + ob.scr[i] + off) * S) : Math.round(v * S) - camd[i];
        return [at(0, X, ox, ob.sx), at(1, Y, oy, ob.sy)];
    }
    /** 1.8: an image of w x h game pixels at scale S: the quad in whole device pixels and the image pixel per device pixel. */
    function quadOf(w, h, S) { const qw = Math.round(w * S), qh = Math.round(h * S); return { w: qw, h: qh, sx: Math.fround(w / qw), sy: Math.fround(h / qh) }; }
    /** 1.6: the window's pixels the model does not explain (Alien Breed SE92's check of its model against the game's own
     *  picture). The model of the window: the clean picture where it has an index, the map through the holes, then the
     *  record's objects at round(x - cam) (what the game blitted into this picture; the project passes the objects the
     *  game had drawn when it captured gameIdx); hardware sprites are not in the picture. gameIdx: win.w x win.h indices
     *  of what the game really drew. Returns { over, count, model }: over for window.over (255 where the model explains
     *  the pixel, the game's index elsewhere - drawn over the window, moving with the camera), count the number of
     *  such pixels (a diagnostic: how well the model knows the game). */
    function unexplained(rec, gameIdx) {
        const win = rec.window, map = rec.map, cam = rec.cam, W = win.w, H = win.h, model = new Uint8Array(W * H);
        for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
            let v = win.idx[y * W + x]; const hole = v === 255;
            if (v === 255 && map) {
                const wx = cam[0] + x - map.origin[0], wy = cam[1] + y - map.origin[1], cx = Math.floor(wx / 16), cy = Math.floor(wy / 16);
                if (cx >= 0 && cy >= 0 && cx < map.cols && cy < map.rows) { const sl = map.cells[cy * map.cols + cx]; if (sl !== 0xffff) v = map.atlas[sl * 256 + (wy & 15) * 16 + (wx & 15)]; }
            }
            if (v === 255 && rec.back) v = backIdx({ rec: rec.back, origin: rec.back.origin || rec.back.cam, wrap: wrapOf(rec.back.wrap) }, rec.back.cam[0] + x, rec.back.cam[1] + y);   // 2.5
            if (hole && win.or && win.or[y * W + x]) v = (v === 255 ? 0 : v) | win.or[y * W + x];
            model[y * W + x] = v;
        }
        for (const ob of rec.objects || []) {
            const x0 = Math.round(ob.x + (ob.ox || 0) - cam[0]), y0 = Math.round(ob.y + (ob.oy || 0) - cam[1]);
            for (let j = 0; j < ob.h; j++) for (let i = 0; i < ob.w; i++) { const v = ob.idx[j * ob.w + i]; if (v === 255) continue;
                const x = x0 + i, y = y0 + j; if (x >= 0 && x < W && y >= 0 && y < H) model[y * W + x] = v; }
        }
        const over = new Uint8Array(W * H).fill(255); let count = 0;
        for (let i = 0; i < W * H; i++) if (gameIdx[i] !== model[i]) { over[i] = gameIdx[i]; count++; }
        return { over, count, model };
    }
    /** 1.5: out(x, y) = the four device pixels around (x + wx/256, y + wy/256) of mid (Wd + 1 wide), integer arithmetic. */
    function subBlend(mid, Wd, Hd, w) {
        const out = new Uint8Array(Wd * Hd * 4), Wm = Wd + 1, wx = w[0], wy = w[1];
        for (let y = 0; y < Hd; y++) for (let x = 0; x < Wd; x++) {
            const p = (y * Wd + x) * 4, a = (y * Wm + x) * 4, b = a + 4, cc = a + Wm * 4, d = cc + 4;
            for (let k = 0; k < 3; k++) { const top = (256 - wx) * mid[a + k] + wx * mid[b + k], bot = (256 - wx) * mid[cc + k] + wx * mid[d + k]; out[p + k] = ((256 - wy) * top + wy * bot + 32768) >> 16; }
            out[p + 3] = 255;
        }
        return out;
    }
    /** The playfield alone (the window's clean picture, the map, black outside) at camera cam, Wd x Hd device pixels. */
    function playfield(c, camd, Wd, Hd) {
        const S = c.S, out = new Uint8Array(Wd * Hd * 4), bandWd = Math.round(c.W * S), bandHd = Math.round(c.H * S), bandH = c.H;
        const win = c.win, winX = c.B.cam[0], winY = c.B.cam[1], map = c.map, back = c.back;
        const fixed = c.fixed, lim = c.limits;
        // 2.0.1 (Alien Breed II G59): the device pixel (dx, dy) with the camera camd (whole device pixels) shows game pixel
        // floor((dx + camd) * W / Wd) - whole numbers only on both paths, so no GPU's float rounding (WebKit fused a multiply-add
        // at S = 702 / 352: 802 pixels) can differ from the reference
        const gameX = (dx) => Math.floor((dx + camd[0]) * c.W / bandWd), gameY = (dy) => Math.floor((dy + camd[1]) * c.H / bandHd);
        const palTop = win.palTop | 0, palRows = win.palTop == null ? win.h : Math.max(1, (win.pal.length / 128) | 0);   // 2.2 (KIT-GAP 24): the margins' own rows
        const scr = c.palScreen == null ? null : c.palScreen;                      // 2.3 (KIT-GAP 27): the band row minus the screen's offset
        const palRow = (wy, dy) => Math.min(Math.max((scr === null ? wy - winY : Math.floor(dy * bandH / bandHd) - scr) + palTop, 0), palRows - 1);
        const put = (dx, dy, idx, row) => { const p = (dy * Wd + dx) * 4, q = (row * 32 + idx) * 4; out[p] = win.pal[q]; out[p + 1] = win.pal[q + 1]; out[p + 2] = win.pal[q + 2]; out[p + 3] = 255; };
        for (let dy = 0; dy < Hd; dy++) for (let dx = 0; dx < Wd; dx++) {
            const wx = gameX(dx), wy = gameY(dy);
            let idx = -1;
            if (fixed && (fixed.axis === 'y' ? (wy < lim.y0 || wy >= lim.y1 + win.h) : (wx < lim.x0 || wx >= lim.x1 + win.w))) idx = -1;
            else {
                const bx = wx - winX, by = wy - winY;
                const inWin = bx >= 0 && bx < win.w && by >= 0 && by < win.h;
                if (inWin) { const v = win.idx[by * win.w + bx]; if (v !== 255) idx = v; }
                if (idx < 0 && map) {
                    const cx = Math.floor((wx - map.origin[0]) / 16), cy = Math.floor((wy - map.origin[1]) / 16);
                    if (cx >= 0 && cy >= 0 && cx < map.cols && cy < map.rows) { const sl = map.cells[cy * map.cols + cx];
                        if (sl !== 0xffff) idx = map.atlas[sl * 256 + ((wy - map.origin[1]) & 15) * 16 + ((wx - map.origin[0]) & 15)]; }
                }
                const hole = idx < 0;
                if (hole && back) { const v = backIdx(back, Math.floor((dx + back.d[0]) * c.W / bandWd), Math.floor((dy + back.d[1]) * c.H / bandHd)); if (v !== 255) idx = v; }   // 2.5: the back layer
                if (hole && inWin && win.or) { const v = win.or[by * win.w + bx]; if (v) idx = (idx < 0 ? 0 : idx) | v; }
                if (inWin && win.over) { const v = win.over[by * win.w + bx]; if (v !== 255) idx = v; }   // 1.1: the game's own drawings over the window
            }
            if (idx >= 0) put(dx, dy, idx, palRow(wy, dy)); else { const p = (dy * Wd + dx) * 4; out[p + 3] = 255; }
        }
        return out;
    }

    // ---------------------------------------------------------------- the GPU (WebGL2, inside the presenter's framebuffer)
    const VS = `#version 300 es
    in vec2 a_pos; in vec2 a_uv; out vec2 v_uv; uniform vec2 u_size;
    void main() { v_uv = a_uv; vec2 p = a_pos / u_size * 2.0 - 1.0; gl_Position = vec4(p.x, -p.y, 0.0, 1.0); }`;
    const FS = `#version 300 es
    precision highp float; precision highp int;
    in vec2 v_uv; out vec4 o;
    uniform sampler2D u_tex; uniform sampler2D u_pal; uniform int u_mode; uniform ivec2 u_camd; uniform ivec4 u_ratio; uniform vec2 u_band;
    uniform ivec2 u_qpos; uniform ivec2 u_qsize; uniform ivec2 u_qimg; uniform int u_alpha;   // 2.8: mode 4 blends by u_alpha / 256 with u_mid = the pixels below
    int fdiv(int a, int b) { int q = a / b; return (a % b != 0 && a < 0) ? q - 1 : q; }   // floor division, b > 0
    uniform ivec2 u_winpos; uniform ivec2 u_winsize; uniform ivec4 u_palrows; uniform highp usampler2D u_grid; uniform sampler2D u_atlas; uniform ivec4 u_map; uniform ivec4 u_fixed; uniform sampler2D u_over; uniform int u_hasover;
    uniform sampler2D u_mid; uniform ivec2 u_w; uniform int u_midh;
    uniform sampler2D u_back; uniform sampler2D u_or; uniform ivec4 u_bk; uniform ivec2 u_bcamd; uniform ivec3 u_bflags; uniform int u_hasor;   // 2.5
    int ix8(sampler2D t, ivec2 p) { return int(texelFetch(t, p, 0).r * 255.0 + 0.5); }
    ivec4 px8(ivec2 p) { return ivec4(texelFetch(u_mid, p, 0) * 255.0 + 0.5); }
    void main() {
      if (u_mode == 0) { o = texture(u_tex, v_uv); return; }
      if (u_mode == 3) {                                      // 1.5: the playfield drawn at the snapped camera (u_mid, one px wider and taller), shifted by u_w / 256
        ivec2 d = ivec2(int(gl_FragCoord.x - 0.5 - u_band.x), int(u_band.y - gl_FragCoord.y - 0.5));
        ivec2 t = ivec2(d.x, u_midh - d.y);                   // u_mid's rows run bottom-up: row u_midh is the band's top row
        ivec4 a = px8(t), b = px8(t + ivec2(1, 0)), c = px8(t - ivec2(0, 1)), e = px8(t + ivec2(1, -1));
        ivec4 top = (256 - u_w.x) * a + u_w.x * b, bot = (256 - u_w.x) * c + u_w.x * e;
        ivec4 v = ((256 - u_w.y) * top + u_w.y * bot + 32768) >> 16;
        o = vec4(vec3(v.rgb) / 255.0, 1.0); return;
      }
      // the game pixel under this device pixel (its top-left corner; gl_FragCoord is the centre): floor(px / S + cam),
      // the camera as an integer part and a float32 fraction so that the CPU reference computes the same floor
      // the game pixel under this device pixel (2.0.1, G59: whole numbers only): the device pixel (d) plus the camera in
      // whole device pixels (u_camd), times W / Wd (u_ratio.xy) and H / Hd (u_ratio.zw), floored - as the CPU reference
      ivec2 dd = ivec2(int(gl_FragCoord.x - 0.5 - u_band.x), int(u_band.y - gl_FragCoord.y - 0.5)) + u_camd;
      ivec2 w = ivec2(fdiv(dd.x * u_ratio.x, u_ratio.y), fdiv(dd.y * u_ratio.z, u_ratio.w));
      int row = clamp((u_palrows.z == 1 ? fdiv((dd.y - u_camd.y) * u_ratio.z, u_ratio.w) - u_palrows.w : w.y - u_winpos.y) + u_palrows.x, 0, u_palrows.y - 1);   // 2.2: x = palTop, y = the palette's rows; 2.3: z = 1 on the screen rows, w = their band offset
      if (u_mode == 2) {
        int idx = -1;
        if (u_fixed.x == 1 && (w.y < u_fixed.y || w.y >= u_fixed.z)) idx = -1;
        else if (u_fixed.x == 2 && (w.x < u_fixed.y || w.x >= u_fixed.z)) idx = -1;
        else {
          ivec2 b = w - u_winpos;
          bool inWin = b.x >= 0 && b.x < u_winsize.x && b.y >= 0 && b.y < u_winsize.y;
          if (inWin) { int v = ix8(u_tex, b); if (v != 255) idx = v; }
          if (idx < 0 && u_map.z > 0) { ivec2 m = w - u_map.xy; ivec2 c = m >> 4;
            if (m.x >= 0 && m.y >= 0 && c.x < u_map.z && c.y < u_map.w) { uint sl = texelFetch(u_grid, c, 0).r;
              if (sl != 0xffffu) idx = ix8(u_atlas, ivec2(int(sl % 32u) * 16 + (m.x & 15), int(sl / 32u) * 16 + (m.y & 15))); } }
          bool hole = idx < 0;
          if (hole && u_bflags.x == 1) {                     // 2.5: the back layer at its own camera, whole numbers as the reference
            ivec2 bd = ivec2(int(gl_FragCoord.x - 0.5 - u_band.x), int(u_band.y - gl_FragCoord.y - 0.5)) + u_bcamd;
            ivec2 q = ivec2(fdiv(bd.x * u_ratio.x, u_ratio.y), fdiv(bd.y * u_ratio.z, u_ratio.w)) - u_bk.xy;
            if (u_bflags.y == 1) q.x -= fdiv(q.x, u_bk.z) * u_bk.z;
            if (u_bflags.z == 1) q.y -= fdiv(q.y, u_bk.w) * u_bk.w;
            if (q.x >= 0 && q.y >= 0 && q.x < u_bk.z && q.y < u_bk.w) { int v = ix8(u_back, q); if (v != 255) idx = v; }
          }
          if (hole && inWin && u_hasor == 1) { int v = ix8(u_or, b); if (v != 0) idx = (idx < 0 ? 0 : idx) | v; }
          if (inWin && u_hasover == 1) { int v = ix8(u_over, b); if (v != 255) idx = v; }
        }
        if (idx < 0) { o = vec4(0.0, 0.0, 0.0, 1.0); return; }
        o = texelFetch(u_pal, ivec2(idx, row), 0); return;
      }
      // mode 1 (1.8): the image on the quad at u_qpos (band coordinates) of u_qsize device px; the device pixel d maps to
      // image pixel (d * image size) div quad size - whole numbers (2.0.1), as the reference
      ivec2 d = ivec2(int(gl_FragCoord.x - 0.5 - u_band.x), int(u_band.y - gl_FragCoord.y - 0.5)) - u_qpos;
      if (d.x < 0 || d.y < 0 || d.x >= u_qsize.x || d.y >= u_qsize.y) discard;
      ivec2 ts = textureSize(u_tex, 0); ivec2 p = ivec2((d.x * u_qimg.x) / u_qsize.x, (d.y * u_qimg.y) / u_qsize.y);
      if (p.x < 0 || p.y < 0 || p.x >= ts.x || p.y >= ts.y) discard;
      int idx = int(texelFetch(u_tex, p, 0).r * 255.0 + 0.5); if (idx == 255) discard;
      if (u_mode == 4) {                                      // 2.8: the colour over the copy of what is below, whole numbers as the reference
        ivec4 c = ivec4(texelFetch(u_pal, ivec2(idx, row), 0) * 255.0 + 0.5), b = ivec4(texelFetch(u_mid, ivec2(d.x, u_qsize.y - 1 - d.y), 0) * 255.0 + 0.5);
        ivec3 v = (b.rgb * (256 - u_alpha) + c.rgb * u_alpha + 128) >> 8;
        o = vec4(vec3(v) / 255.0, 1.0); return;
      }
      o = texelFetch(u_pal, ivec2(idx, row), 0);
    }`;

    class Scene {
        constructor(opts) {
            this.opts = opts || {}; this.takt = this.opts.takt || null; this.frames = []; this.ring = this.opts.ring || 32;
            this.gl = null; this.cache = new Map(); this.pool = []; this.stats = { objs: 0, sprs: 0, uploads: 0, ms: 0, frames: 0 };
            this.atlasGen = -1; this.own = null; this.last = null; this.dirty = new Set();   // 1.6.1: the atlas slots changed by frames not yet drawn (G56)
        }
        /** A game frame record (see the header); keeps the last `ring` frames in time order. */
        frame(rec) {
            if (rec.objects) for (const ob of rec.objects) if (ob.key === undefined) ob.key = fnv1a(ob.idx, (ob.w << 16) ^ ob.h);
            if (rec.map && rec.map.dirty) for (let i = 0; i < rec.map.dirty.length; i++) this.dirty.add(rec.map.dirty[i]);   // G56: a frame that is never B still changed the atlas
            this.frames.push(rec); if (this.frames.length > this.ring) this.frames.shift(); this.stats.frames++;
        }
        reset() { this.frames.length = 0; this.last = null; this.atlasGen = -1; this.dirty.clear(); }
        /** The map's atlas on the GPU: the whole of it at a new generation, otherwise every slot any frame since the last
         *  draw marked dirty (G56: only B's own dirty list was uploaded, a frame skipped between two display frames left
         *  its slots stale). */
        _uploadMap(map) {
            if (map.gen !== this.atlasGen) { this.atlasGen = map.gen; this._atlasAll(map); }
            else { if (map.dirty) for (let i = 0; i < map.dirty.length; i++) this.dirty.add(map.dirty[i]); for (const sl of this.dirty) this._slot(map, sl); }
            this.dirty.clear();
        }
        _atlasAll(map) { this.gl.texImage2D(this.gl.TEXTURE_2D, 0, this.gl.R8, 512, 512, 0, this.gl.RED, this.gl.UNSIGNED_BYTE, null); for (let sl = 0; sl < map.nslots; sl++) this._slot(map, sl); }
        compose(ts, view) {
            const c = compose(this.frames, ts, view, this.opts, this.takt);
            if (c && ts - c.B.t > 500) { this.stats.stale = (this.stats.stale || 0) + 1; if (!this.warned) { this.warned = true; console.warn('wb-scene: the newest frame is ' + Math.round(ts - c.B.t) + ' ms behind ts - rec.t and the drawer\'s ts must share one clock (performance.now() based)'); } }
            return c;
        }
        /** Attach to the presenter's WebGL2 context (wb-obraz 1.5 Presenter.g); false without WebGL2 - the page then draws
         *  the reference on the 2D path (reference(compose(...)) into present({pixels})). */
        attach(presenter) {
            const gl = presenter && presenter.g; if (!gl) return false;
            try {
                this.gl = gl; this.presenter = presenter;
                const sh = (t, src) => { const s = gl.createShader(t); gl.shaderSource(s, src); gl.compileShader(s); if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s)); return s; };
                const prog = this.prog = gl.createProgram(); gl.attachShader(prog, sh(gl.VERTEX_SHADER, VS)); gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, FS)); gl.linkProgram(prog);
                if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(prog));
                gl.useProgram(prog); this.u = {};
                for (const n of ['u_size', 'u_tex', 'u_pal', 'u_mode', 'u_camd', 'u_ratio', 'u_band', 'u_winpos', 'u_winsize', 'u_palrows', 'u_grid', 'u_atlas', 'u_map', 'u_fixed', 'u_over', 'u_hasover', 'u_qpos', 'u_qsize', 'u_qimg', 'u_mid', 'u_w', 'u_midh', 'u_back', 'u_or', 'u_bk', 'u_bcamd', 'u_bflags', 'u_hasor', 'u_alpha']) this.u[n] = gl.getUniformLocation(prog, n);
                this.vao = gl.createVertexArray(); gl.bindVertexArray(this.vao); this.vbo = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, this.vbo);
                const aPos = gl.getAttribLocation(prog, 'a_pos'), aUv = gl.getAttribLocation(prog, 'a_uv');
                gl.enableVertexAttribArray(aPos); gl.vertexAttribPointer(aPos, 2, gl.FLOAT, false, 16, 0); gl.enableVertexAttribArray(aUv); gl.vertexAttribPointer(aUv, 2, gl.FLOAT, false, 16, 8);
                gl.bindVertexArray(null);
                this.texWin = this._tex(); this.texPal = this._tex(); this.texGrid = this._tex(); this.texAtlas = this._tex(); this.texHud = [this._tex(), this._tex()]; this.texOver = this._tex(); this.texBack = this._tex(); this.texOr = this._tex(); this.texBelow = this._tex();
                this.quad = new Float32Array(24);
                gl.canvas.addEventListener('webglcontextlost', () => { this.gl = null; });
                return true;
            } catch (e) { this.gl = null; return false; }
        }
        _tex() { const gl = this.gl, t = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, t); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE); return t; }
        _r8(t, w, h, data) { const gl = this.gl; gl.bindTexture(gl.TEXTURE_2D, t); gl.texImage2D(gl.TEXTURE_2D, 0, gl.R8, w, h, 0, gl.RED, gl.UNSIGNED_BYTE, data); }
        _quad(x0, y0, w, h) {
            const gl = this.gl, q = this.quad;
            q.set([x0, y0, 0, 0, x0 + w, y0, 1, 0, x0, y0 + h, 0, 1, x0, y0 + h, 0, 1, x0 + w, y0, 1, 0, x0 + w, y0 + h, 1, 1]);
            gl.bindBuffer(gl.ARRAY_BUFFER, this.vbo); gl.bufferData(gl.ARRAY_BUFFER, q, gl.STREAM_DRAW); gl.drawArrays(gl.TRIANGLES, 0, 6);
        }
        _objTex(ob) {
            let e = this.cache.get(ob.key); if (e) return e;
            if (this.cache.size >= 4096) { for (const v of this.cache.values()) this.gl.deleteTexture(v.t); this.cache.clear(); }
            e = { t: this._tex(), w: ob.w, h: ob.h }; this._r8(e.t, ob.w, ob.h, ob.idx); this.cache.set(ob.key, e); this.stats.uploads++; return e;
        }
        /** The draw callback for presenter.present({ draw }): the composition at display time ts into the framebuffer,
         *  the band's top-left at (view.x0, view.y0) device px from the top. */
        drawer(ts, view) { return (gl, fbo, d) => this.draw(ts, view, fbo, d); }
        /** comp: a composition already made (read(): the GPU and the reference must draw the very same one - the clock's
         *  view() adapts its latencies, so two compose() calls can differ). */
        draw(ts, view, fbo, d, comp) {
            const gl = this.gl; if (!gl) return false; const t0 = performance.now();
            const c = comp || this.compose(ts, view); if (!c) return false; this.last = c;
            const S = c.S, Wd = Math.round(c.W * S), Hd = Math.round(c.H * S), x0 = view.x0 || 0, y0 = view.y0 || 0, vy = d.h - y0 - Hd;
            const u = this.u, win = c.win;
            gl.bindFramebuffer(gl.FRAMEBUFFER, fbo); gl.useProgram(this.prog); gl.bindVertexArray(this.vao); gl.disable(gl.BLEND); gl.disable(gl.DEPTH_TEST); gl.disable(gl.SCISSOR_TEST); gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
            const camd = c.sub ? c.sub.d : [Math.floor(c.cam[0] * S), Math.floor(c.cam[1] * S)];   // 2.0.1 (G59): the camera in whole device pixels, the ratios W / Wd and H / Hd as whole numbers
            gl.viewport(x0, vy, Wd, Hd); gl.uniform2f(u.u_size, Wd, Hd); gl.uniform2i(u.u_camd, camd[0], camd[1]); gl.uniform4i(u.u_ratio, c.W, Wd, c.H, Hd); gl.uniform2f(u.u_band, x0, vy + Hd);
            gl.uniform2i(u.u_winpos, c.B.cam[0], c.B.cam[1]); gl.uniform2i(u.u_winsize, win.w, win.h); const palRows = win.palTop == null ? win.h : Math.max(1, (win.pal.length / 128) | 0); gl.uniform4i(u.u_palrows, win.palTop | 0, palRows, c.palScreen == null ? 0 : 1, c.palScreen | 0);
            const fx = c.fixed; gl.uniform4i(u.u_fixed, fx ? (fx.axis === 'y' ? 1 : 2) : 0, fx ? (fx.axis === 'y' ? c.limits.y0 : c.limits.x0) : 0, fx ? (fx.axis === 'y' ? c.limits.y1 + win.h : c.limits.x1 + win.w) : 0, 0);
            gl.uniform1i(u.u_tex, 0); gl.uniform1i(u.u_pal, 1); gl.uniform1i(u.u_grid, 2); gl.uniform1i(u.u_atlas, 3); gl.uniform1i(u.u_over, 4); gl.uniform1i(u.u_mid, 5);
            gl.activeTexture(gl.TEXTURE4); gl.bindTexture(gl.TEXTURE_2D, this.texOver);
            if (win.over) gl.texImage2D(gl.TEXTURE_2D, 0, gl.R8, win.w, win.h, 0, gl.RED, gl.UNSIGNED_BYTE, win.over);
            gl.uniform1i(u.u_hasover, win.over ? 1 : 0);
            gl.activeTexture(gl.TEXTURE1); gl.bindTexture(gl.TEXTURE_2D, this.texPal); gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 32, palRows, 0, gl.RGBA, gl.UNSIGNED_BYTE, win.pal.subarray(0, palRows * 128));
            const map = c.map;
            if (map) {
                gl.activeTexture(gl.TEXTURE3); gl.bindTexture(gl.TEXTURE_2D, this.texAtlas);
                this._uploadMap(map);
                gl.activeTexture(gl.TEXTURE2); gl.bindTexture(gl.TEXTURE_2D, this.texGrid);
                gl.texImage2D(gl.TEXTURE_2D, 0, gl.R16UI, map.cols, map.rows, 0, gl.RED_INTEGER, gl.UNSIGNED_SHORT, map.cells);
                gl.uniform4i(u.u_map, map.origin[0], map.origin[1], map.cols, map.rows);
            } else gl.uniform4i(u.u_map, 0, 0, 0, 0);
            gl.uniform1i(u.u_back, 6); gl.uniform1i(u.u_or, 7);                    // 2.5: the back layer and the bits ORed onto it
            const bk = c.back;
            gl.activeTexture(gl.TEXTURE6);
            if (bk) { this._r8(this.texBack, bk.rec.w, bk.rec.h, bk.rec.idx); gl.uniform4i(u.u_bk, bk.origin[0], bk.origin[1], bk.rec.w, bk.rec.h); gl.uniform2i(u.u_bcamd, bk.d[0], bk.d[1]); gl.uniform3i(u.u_bflags, 1, bk.wrap[0] ? 1 : 0, bk.wrap[1] ? 1 : 0); }
            else { gl.bindTexture(gl.TEXTURE_2D, this.texBack); gl.uniform3i(u.u_bflags, 0, 0, 0); }
            gl.activeTexture(gl.TEXTURE7);
            if (win.or) this._r8(this.texOr, win.w, win.h, win.or); else gl.bindTexture(gl.TEXTURE_2D, this.texOr);
            gl.uniform1i(u.u_hasor, win.or ? 1 : 0);
            gl.activeTexture(gl.TEXTURE0); this._r8(this.texWin, win.w, win.h, win.idx);
            if (c.sub) this._subpixel(c, fbo, x0, vy, Wd, Hd); else { gl.uniform1i(u.u_mode, 2); this._quad(0, 0, Wd, Hd); }
            const under = !!(c.hud && c.hud.under), topD = under && c.hud.top ? Math.round(c.hud.top.h * S) : 0, botD = under && c.hud.bottom ? Math.round(c.hud.bottom.h * S) : 0;
            if (under) { this._hud(c, view, d, x0, y0); gl.viewport(x0, vy, Wd, Hd); gl.uniform2f(u.u_size, Wd, Hd); gl.activeTexture(gl.TEXTURE0); }   // 1.4: the HUD first, the sprites over it
            gl.uniform1i(u.u_mode, 1); let objs = 0, sprs = 0;
            for (const ob of c.objs) { if (c.sub && !ob.o.steady && !ob.screen) continue;   // 1.6: drawn with the playfield in _subpixel
                const e = this._objTex(ob.o); gl.bindTexture(gl.TEXTURE_2D, e.t); const dv = objDev(c, ob, camd);   // 2.3 / 2.4 / 2.7: the anchor per axis - as the reference
                if (ob.a <= 0) continue;
                if (ob.a < 256) this._blend(e, ob.a, dv[0], dv[1], x0, vy + Hd); else this._image(e.w, e.h, dv[0], dv[1], S, 0); objs++; }
            const sorted = c.sprs.slice().sort((p, q) => q.s.k - p.s.k), dx = c.cam[0] - c.spriteCam[0], dy = c.cam[1] - c.spriteCam[1];
            if (under) { gl.viewport(x0, vy - botD, Wd, Hd + topD + botD); gl.uniform2f(u.u_size, Wd, Hd + topD + botD); }   // the sprites may reach into the HUD rows
            for (const sp of sorted) { if (!this.pool[sprs]) this.pool[sprs] = this._tex(); this._r8(this.pool[sprs], 16, sp.s.h, sp.s.idx);
                this._image(16, sp.s.h, sp.sx ? Math.round((sp.x + (sp.screen ? 0 : dx) - c.cam[0]) * S) : Math.round(sp.x * S) - camd[0], sp.sy ? Math.round((sp.y + (sp.screen ? 0 : dy) - c.cam[1]) * S) : Math.round(sp.y * S) - camd[1], S, topD); sprs++; }   // 2.4: the anchor per axis
            if (c.hud && !under) this._hud(c, view, d, x0, y0);
            gl.bindVertexArray(null); this.stats.objs = objs; this.stats.sprs = sprs; this.stats.ms = performance.now() - t0;
            return true;
        }
        /** 1.5: the playfield into an own texture one device pixel wider and taller at the snapped camera, then into the
         *  band shifted by the fraction (mode 3); the objects, sprites and HUD follow at the view's camera as always. */
        _subpixel(c, fbo, x0, vy, Wd, Hd) {
            const gl = this.gl, u = this.u, sub = c.sub, Wm = Wd + 1, Hm = Hd + 1, S = c.S;
            gl.activeTexture(gl.TEXTURE5);                   // the texture is made and sized on its own unit, never left on unit 0 under the window (KIT-GAPS 50: a feedback loop on the first draw)
            if (!this.mid) this.mid = { fbo: gl.createFramebuffer(), t: this._tex(), w: 0, h: 0 };
            if (this.mid.w !== Wm || this.mid.h !== Hm) { this.mid.w = Wm; this.mid.h = Hm; gl.bindTexture(gl.TEXTURE_2D, this.mid.t); gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, Wm, Hm, 0, gl.RGBA, gl.UNSIGNED_BYTE, null); gl.bindFramebuffer(gl.FRAMEBUFFER, this.mid.fbo); gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, this.mid.t, 0); }
            gl.bindTexture(gl.TEXTURE_2D, null);             // unit 5 empty while the texture is the target
            gl.bindFramebuffer(gl.FRAMEBUFFER, this.mid.fbo);
            gl.viewport(0, 0, Wm, Hm); gl.uniform2f(u.u_size, Wm, Hm); gl.uniform2f(u.u_band, 0, Hm);   // u_camd = sub.d and u_ratio are the band's, set by draw()
            gl.uniform1i(u.u_mode, 2); this._quad(0, 0, Wm, Hm);
            gl.uniform1i(u.u_mode, 1); gl.activeTexture(gl.TEXTURE0); let glued = 0;   // 1.6: the objects on the ground go with it
            for (const ob of c.objs) if (!ob.o.steady && !ob.screen && ob.a > 0) { const e = this._objTex(ob.o); gl.bindTexture(gl.TEXTURE_2D, e.t); const qx = Math.round((ob.x + (ob.o.ox || 0) - sub.cam[0]) * S), qy = Math.round((ob.y + (ob.o.oy || 0) - sub.cam[1]) * S);
                if (ob.a < 256) this._blend(e, ob.a, qx, qy, 0, Hm); else this._image(e.w, e.h, qx, qy, S, 0); glued++; }
            this.stats.glued = glued;
            gl.bindFramebuffer(gl.FRAMEBUFFER, fbo); gl.activeTexture(gl.TEXTURE5); gl.bindTexture(gl.TEXTURE_2D, this.mid.t);
            gl.viewport(x0, vy, Wd, Hd); gl.uniform2f(u.u_size, Wd, Hd); gl.uniform2f(u.u_band, x0, vy + Hd);
            gl.uniform2i(u.u_w, sub.w[0], sub.w[1]); gl.uniform1i(u.u_midh, Hd);
            gl.uniform1i(u.u_mode, 3); this._quad(0, 0, Wd, Hd);
            gl.bindTexture(gl.TEXTURE_2D, null); gl.activeTexture(gl.TEXTURE0);
        }
        /** 2.8: an object with alpha a / 256 at (qx, qy): the framebuffer's pixels under its quad copied into texBelow (unit 5),
         *  then mode 4 blends the palette colour with them in whole numbers. bandX / bandTop = the band's GL x and top y. */
        _blend(e, a, qx, qy, bandX, bandTop) {
            const gl = this.gl, u = this.u, q = quadOf(e.w, e.h, this.last ? this.last.S : 1);
            gl.activeTexture(gl.TEXTURE5); gl.bindTexture(gl.TEXTURE_2D, this.texBelow);
            gl.copyTexImage2D(gl.TEXTURE_2D, 0, gl.RGB, bandX + qx, bandTop - qy - q.h, q.w, q.h, 0);
            gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, e.t);
            gl.uniform1i(u.u_mode, 4); gl.uniform1i(u.u_alpha, a);
            this._image(e.w, e.h, qx, qy, this.last ? this.last.S : 1, 0);
            gl.uniform1i(u.u_mode, 1);
        }
        /** 1.8: an image of w x h game pixels at (qx, qy) band device px (the quad drawn yOff lower in a widened viewport):
         *  round(w * S) x round(h * S) device px, each sampling the image at its top-left corner (quadOf, as the reference). */
        _image(w, h, qx, qy, S, yOff) {
            const gl = this.gl, u = this.u, q = quadOf(w, h, S);
            gl.uniform2i(u.u_qpos, qx, qy); gl.uniform2i(u.u_qsize, q.w, q.h); gl.uniform2i(u.u_qimg, w, h);
            this._quad(qx, qy + yOff, q.w, q.h);
        }
        _slot(map, sl) { this.gl.texSubImage2D(this.gl.TEXTURE_2D, 0, (sl % 32) * 16, ((sl / 32) | 0) * 16, 16, 16, this.gl.RED, this.gl.UNSIGNED_BYTE, map.atlas.subarray(sl * 256, sl * 256 + 256)); }
        _hud(c, view, d, x0, y0) {
            const gl = this.gl, u = this.u, S = c.S, Wd = Math.round(c.W * S), Hd = Math.round(c.H * S);
            gl.uniform1i(u.u_mode, 0);
            [['top', -1], ['bottom', 1]].forEach(([k, side], i) => {
                const h = c.hud[k]; if (!h) return;
                let wide = h._wide;                                  // 1.7: the widened rows cached on the HUD object (the same rgba, split and width -> the same picture)
                if (!wide || wide.W !== c.W || wide.src !== h.rgba || wide.split !== h.split) {
                    const w0 = h.rgba.length / 4 / h.h, cols = widenColumns(w0, c.W, h.split), rgba = new Uint8Array(c.W * h.h * 4);
                    for (let y = 0; y < h.h; y++) for (let x = 0; x < c.W; x++) { const s = (y * w0 + cols[x]) * 4, t = (y * c.W + x) * 4; rgba[t] = h.rgba[s]; rgba[t + 1] = h.rgba[s + 1]; rgba[t + 2] = h.rgba[s + 2]; rgba[t + 3] = 255; }
                    wide = h._wide = { W: c.W, src: h.rgba, split: h.split, rgba }; this.stats.hudWidened = (this.stats.hudWidened || 0) + 1;
                }
                const hd = Math.round(h.h * S), ty = view.hudY ? view.hudY[i] : (side < 0 ? y0 - hd : y0 + Hd), vy = d.h - ty - hd;   // 2.1.1: view.hudY = [top, bottom] device px of the HUD rows' top-left (a transition's fractional cut-out - Alien Breed SE92)
                gl.viewport(x0, vy, Wd, hd); gl.uniform2f(u.u_size, Wd, hd);
                gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, this.texHud[i]);
                if (!this.hudUp) this.hudUp = [null, null];
                if (this.hudUp[i] !== wide) { gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, c.W, h.h, 0, gl.RGBA, gl.UNSIGNED_BYTE, wide.rgba); this.hudUp[i] = wide; }
                this._quad(0, 0, Wd, hd);
            });
        }
        /** The band drawn into an own framebuffer and read back, RGBA rows top-down: the GPU against reference() (a 0-mismatch
         *  test as Alien Breed II ran one, 0 of 60 M pixels). */
        read(ts, view) {
            const gl = this.gl; if (!gl) return null;
            const c = this.compose(ts, view); if (!c) return null; const w = Math.round(c.W * c.S), h = Math.round(c.H * c.S);
            if (!this.own) this.own = { fbo: gl.createFramebuffer(), t: this._tex(), w: 0, h: 0 };
            if (this.own.w !== w || this.own.h !== h) { this.own.w = w; this.own.h = h; gl.bindTexture(gl.TEXTURE_2D, this.own.t); gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, w, h, 0, gl.RGBA, gl.UNSIGNED_BYTE, null); gl.bindFramebuffer(gl.FRAMEBUFFER, this.own.fbo); gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, this.own.t, 0); }
            const hud = c.hud; c.hud = null;                        // the band only, the same composition
            this.draw(ts, Object.assign({}, view, { x0: 0, y0: 0 }), this.own.fbo, { w, h }, c); c.hud = hud;
            const px = new Uint8Array(w * h * 4), out = new Uint8Array(w * h * 4);
            gl.bindFramebuffer(gl.FRAMEBUFFER, this.own.fbo); gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, px); gl.bindFramebuffer(gl.FRAMEBUFFER, null);
            for (let y = 0; y < h; y++) out.set(px.subarray((h - 1 - y) * w * 4, (h - y) * w * 4), y * w * 4);
            return { pixels: out, w, h, composition: c };
        }
    }
    return { VERSION, lerp, clampCam, valueAt, windowMean, runOf, objDev, pairById, pairOf, fnv1a, x17, widenColumns, compose, reference, unexplained, quadOf, backIdx, Scene };
})();
if (typeof globalThis !== 'undefined') globalThis.WBSCENE = WBSCENE;
if (typeof module !== 'undefined') module.exports = WBSCENE;
