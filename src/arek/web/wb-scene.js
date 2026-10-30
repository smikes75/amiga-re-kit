// wb-scene.js 1.0 - the scene of a rebuild on the display's clock (amiga-re-kit, docs/WB-PLYNULOST.md, module G, kit 0.9.0).
// Extracted from the Alien Breed II page (tools/web/gl.js, tools/host/view.h) with Superfrog's measured options
// (docs/POHYB-AUDIT.md, PLYNULOST-K4.md): one way to draw the wider, smoother view for every project.
//
// The project gives one RECORD per game frame (world coordinates in game pixels, the window = the original's playfield):
//   { n, t, pass,                        frame number, its time (wb-takt stamp, ms), the time of the drawing pass the
//                                        objects belong to (optional; frames of one pass share it - objects interpolate
//                                        between passes, the camera and the sprites between frames)
//     cam: [x, y],                       the game's camera: world position of the window's top-left
//     limits: { x0, x1, y0, y1},         the game's own camera range (the window never leaves it)
//     window: { w, h, idx, pal },        the window's CLEAN picture (no moving objects): idx = Uint8Array(w*h) colour
//                                        indices (255 = none, the map shows through), pal = Uint8Array(h*32*4) RGBA per row
//     map: { gen, atlas, nslots, dirty, cols, rows, cells, origin },   optional, for the margins: atlas = Uint8Array(nslots*256)
//                                        16 x 16 tiles (32 per atlas row, 512 x 512 texture), gen changes when the atlas is
//                                        rebuilt, dirty = Uint16Array of slots changed since the last frame (null = none),
//                                        cells = Uint16Array(cols*rows) slot per 16 x 16 cell (0xffff = none), origin = [wx, wy]
//                                        world px of cell (0, 0)
//     objects: [{ id, key, w, h, idx, x, y, pass, opaque }],   moving things drawn by the game's own records: id = identity
//                                        across frames (for the interpolation), key = a content key of the graphics (the
//                                        texture cache; the module computes fnv1a(idx) when absent), idx = Uint8Array(w*h)
//                                        (255 = transparent), x, y = world px (fractions allowed), pass = the time of the
//                                        drawing pass the position belongs to (objects of a 25 Hz loop move every other frame)
//     sprites: [{ k, h, idx, x, y }],    hardware sprites of this frame: k = sprite number (lower on top), idx = Uint8Array(16*h),
//                                        x, y = screen px relative to the window
//     hud: { top: { h, rgba, split }, bottom: {...} } }   optional rows above / below the playfield: rgba = Uint8Array(w*h*4) of
//                                        the original's width, split = columns repeated to widen it (Alien Breed II: 6 cuts)
// The view: { W, H, S, extX, extY, x0, y0 } - the wider window (W = window.w + 2 extX, H = window.h + 2 extY), S device pixels
// per game pixel, x0 / y0 = where the view's top-left lands in the presenter's framebuffer (device px from the top).
// Options (all measured in Superfrog, off unless set): softClamp { tau } (the stopped camera at a map edge as the mean over
// tau ms, extrapolated past the newest frame by at most tau), smoothY { tau } (the terrain's vertical camera as a mean over
// tau ms; sprites keep their screen position as in the original), pairOlder (a blinking sprite / object paired with up to n
// older frames), fixedAxis { axis, value } (a level whose camera axis is fixed: black outside), x17 (12-bit colours * 17).
//
//   const scene = new WBSCENE.Scene({ takt, softClamp: { tau: 20 }, pairOlder: 2 });
//   scene.attach(presenter);   per game frame: scene.frame(rec);   per display frame: presenter.present({ draw: scene.drawer(ts, view) })
//   scene.compose(ts, view) -> the composition the GPU draws, also as a CPU reference (WBSCENE.reference(c)) for a 0-mismatch test.
// Pure functions (Node too): lerp, clampCam, windowMean, pairById, fnv1a, x17, reference. No game data.
'use strict';
const WBSCENE = (() => {
    const VERSION = '1.0';
    const lerp = (a, b, f) => a + (b - a) * f;

    /** The camera of a view extX / extY wider than the window, inside the game's limits: the game's camera minus the
     *  extension, clamped to [x0 - extX .. x1 + extX] shrunk so that the view never shows beyond what the game's own
     *  camera range plus the margins allow; a map narrower than the view is centred (mapW = x1 - x0 + window w). */
    function clampCam(cx, cy, lim, win, ext) {
        const W = win.w + 2 * ext.x, H = win.h + 2 * ext.y;
        const mapW = lim.x1 - lim.x0 + win.w, mapH = lim.y1 - lim.y0 + win.h;
        let vx = cx - ext.x, vy = cy - ext.y;
        if (mapW <= W) vx = lim.x0 - (W - mapW) / 2; else vx = Math.min(Math.max(vx, lim.x0), lim.x0 + mapW - W);
        if (mapH <= H) vy = lim.y0 - (H - mapH) / 2; else vy = Math.min(Math.max(vy, lim.y0), lim.y0 + mapH - H);
        return [vx, vy];
    }
    /** The mean of pick(frame) over the frames within tau ms of t; past the newest frame the newest value continues
     *  with the velocity of the last two frames for at most tau ms (Superfrog's soft clamp: the stop at a map edge is
     *  not a step 5 -> 2.3 -> 0). Returns null without frames. */
    function windowMean(frames, t, tau, pick) {
        let sum = 0, n = 0, newest = null, prev = null;
        for (const fr of frames) {
            if (fr.t > t + tau) continue;
            if (!newest || fr.t > newest.t) { prev = newest; newest = fr; }
            if (fr.t >= t - tau) { sum += pick(fr); n++; }
        }
        if (!newest) return null;
        if (t > newest.t) {
            const dt = Math.min(t - newest.t, tau);
            const v = prev && newest.t > prev.t ? (pick(newest) - pick(prev)) / (newest.t - prev.t) : 0;
            sum += pick(newest) + v * dt; n++;
        }
        return n ? sum / n : pick(newest);
    }
    /** The pairs for the interpolation of things with an identity: for every item of b (by id) the same id in a, or in
     *  up to `older` frames before a (a blinking player drawn every other frame - Superfrog: paired 86 % -> 99.6 %).
     *  frames = [..., a2, a1, a] newest last. Returns [{ to, from, f }]: from = null when nothing pairs (drawn at `to`). */
    function pairById(a, b, f, items, older, history) {
        const out = [];
        const byId = (list) => { const m = new Map(); for (const o of list || []) m.set(o.id, o); return m; };
        const ma = byId(a ? items(a) : []), olds = (older > 0 ? (history || []).slice(-older) : []).reverse().map((fr) => ({ fr, m: byId(items(fr)) }));
        for (const o of items(b)) {
            let from = ma.get(o.id), ff = f;
            if (!from) for (const h of olds) { const p = h.m.get(o.id); if (p) { from = p; ff = b.t > h.fr.t ? (lerp(a ? a.t : b.t, b.t, f) - h.fr.t) / (b.t - h.fr.t) : f; break; } }
            out.push({ to: o, from: from || null, f: from ? Math.min(Math.max(ff, 0), 1) : 1 });
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
        const extra = W - w0; if (extra <= 0) { for (let x = 0; x < W; x++) cols[x] = Math.min(x, w0 - 1); return cols; }
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
        const passes = []; let lastPass = null;
        for (const fr of frames) { const ps = fr.pass === undefined ? fr.t : fr.pass; if (ps !== lastPass) { passes.push(fr); lastPass = ps; } }
        if (takt) { const v = takt.view(ts); tv = v.tv; tvO = v.tvO; p = takt.pair(frames, tv); q = takt.pair(passes, tvO); }
        else { p = pairOf(frames, tv); q = pairOf(passes, tvO); }
        if (!p) return null;
        const A = p.a, B = p.b || p.a, f = Math.min(Math.max(p.f, 0), p.b ? 1 + (o.extrapolate || 0) : 0);
        const OA = q ? q.a : A, OB = q ? (q.b || q.a) : B, of = q ? Math.min(Math.max(q.f, 0), 1) : 0;
        const win = B.window, lim = B.limits;
        // the game's camera between the frames, the view's camera clamped; soft clamp and vertical smoothing as means over frames
        const gcam = [lerp(A.cam[0], B.cam[0], f), lerp(A.cam[1], B.cam[1], f)];
        let vcam = clampCam(gcam[0], gcam[1], lim, win, ext);
        if (o.fixedAxis) { if (o.fixedAxis.axis === 'y') vcam[1] = o.fixedAxis.value; else vcam[0] = o.fixedAxis.value; }
        const spriteCam = vcam.slice();
        const clampedOf = (fr, i) => clampCam(fr.cam[0], fr.cam[1], fr.limits, fr.window, ext)[i];
        if (o.softClamp && o.softClamp.tau > 0) {
            const stopped = vcam[0] !== gcam[0] - ext.x || vcam[1] !== gcam[1] - ext.y;
            if (stopped) { const mx = windowMean(frames, tv, o.softClamp.tau, (fr) => clampedOf(fr, 0)), my = windowMean(frames, tv, o.softClamp.tau, (fr) => clampedOf(fr, 1));
                if (mx !== null) vcam = [mx, my]; }
            spriteCam[0] = vcam[0]; spriteCam[1] = vcam[1];
        }
        if (o.smoothY && o.smoothY.tau > 0 && !(o.fixedAxis && o.fixedAxis.axis === 'y')) {
            const my = windowMean(frames, tv, o.smoothY.tau, (fr) => clampedOf(fr, 1)); if (my !== null) vcam[1] = my;   // sprites keep spriteCam
        }
        const history = passes.filter((fr) => fr.t < (OA ? OA.t : 0));
        const objs = pairById(OA, OB, of, (fr) => fr.objects || [], o.pairOlder || 0, history).map((pr) => ({
            o: pr.to, x: pr.from ? lerp(pr.from.x, pr.to.x, pr.f) : pr.to.x, y: pr.from ? lerp(pr.from.y, pr.to.y, pr.f) : pr.to.y }));
        const shist = frames.filter((fr) => fr.t < A.t);
        const sprs = pairById(A, B, f, (fr) => (fr.sprites || []).map((s) => Object.assign({ id: s.k }, s)), o.pairOlder || 0, shist).map((pr) => {
            // screen px relative to the window -> world (window of its own frame) -> the view
            const wx = pr.from ? lerp(pr.from.x + frameCam(frames, pr.from, A)[0], pr.to.x + B.cam[0], pr.f) : pr.to.x + B.cam[0];
            const wy = pr.from ? lerp(pr.from.y + frameCam(frames, pr.from, A)[1], pr.to.y + B.cam[1], pr.f) : pr.to.y + B.cam[1];
            return { s: pr.to, x: wx, y: wy };
        });
        return { A, B, f, OA, OB, of, cam: vcam, spriteCam, gcam, win, map: B.map || null, limits: lim, objs, sprs, hud: B.hud || null,
                 W: win.w + 2 * ext.x, H: win.h + 2 * ext.y, S: view.S || 1, ext, fixed: o.fixedAxis || null, n: B.n };
    }
    function frameCam(frames, item, fallback) { for (const fr of frames) if (fr.sprites && fr.sprites.indexOf(item) >= 0) return fr.cam; return fallback.cam; }
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
     *  round((x - cam) * S) (255 transparent, the palette row of the window row under it), then the sprites, lower k on top. */
    function reference(c) {
        const S = c.S, W = c.W, H = c.H, Wd = W * S, Hd = H * S, out = new Uint8Array(Wd * Hd * 4);
        const win = c.win, winX = c.B.cam[0], winY = c.B.cam[1], map = c.map;
        const fixed = c.fixed, lim = c.limits, fr32 = Math.fround;
        const camI = [Math.floor(c.cam[0]), Math.floor(c.cam[1])], camF = [fr32(c.cam[0] - camI[0]), fr32(c.cam[1] - camI[1])];
        const gameX = (dx) => Math.floor(fr32(fr32(dx / S) + camF[0])) + camI[0], gameY = (dy) => Math.floor(fr32(fr32(dy / S) + camF[1])) + camI[1];   // as the shader (float32)
        const palRow = (wy) => Math.min(Math.max(wy - winY, 0), win.h - 1);
        const put = (dx, dy, idx, row) => { const p = (dy * Wd + dx) * 4, q = (row * 32 + idx) * 4; out[p] = win.pal[q]; out[p + 1] = win.pal[q + 1]; out[p + 2] = win.pal[q + 2]; out[p + 3] = 255; };
        for (let dy = 0; dy < Hd; dy++) for (let dx = 0; dx < Wd; dx++) {
            const wx = gameX(dx), wy = gameY(dy);
            let idx = -1;
            if (fixed && (fixed.axis === 'y' ? (wy < lim.y0 || wy >= lim.y1 + win.h) : (wx < lim.x0 || wx >= lim.x1 + win.w))) idx = -1;
            else {
                const bx = wx - winX, by = wy - winY;
                if (bx >= 0 && bx < win.w && by >= 0 && by < win.h) { const v = win.idx[by * win.w + bx]; if (v !== 255) idx = v; }
                if (idx < 0 && map) {
                    const cx = Math.floor((wx - map.origin[0]) / 16), cy = Math.floor((wy - map.origin[1]) / 16);
                    if (cx >= 0 && cy >= 0 && cx < map.cols && cy < map.rows) { const sl = map.cells[cy * map.cols + cx];
                        if (sl !== 0xffff) idx = map.atlas[sl * 256 + ((wy - map.origin[1]) & 15) * 16 + ((wx - map.origin[0]) & 15)]; }
                }
            }
            if (idx >= 0) put(dx, dy, idx, palRow(wy)); else { const p = (dy * Wd + dx) * 4; out[p + 3] = 255; }
        }
        const blit = (idx, w, h, x, y, k) => {
            const dx0 = Math.round((x - c.cam[0]) * S), dy0 = Math.round((y - c.cam[1]) * S);
            for (let j = 0; j < h * S; j++) { const dy = dy0 + j; if (dy < 0 || dy >= Hd) continue;
                for (let i = 0; i < w * S; i++) { const dx = dx0 + i; if (dx < 0 || dx >= Wd) continue;
                    const v = idx[Math.floor(j / S) * w + Math.floor(i / S)]; if (v === 255) continue;
                    put(dx, dy, v, palRow(gameY(dy))); } }
        };
        for (const ob of c.objs) blit(ob.o.idx, ob.o.w, ob.o.h, ob.x, ob.y);
        const sprs = c.sprs.slice().sort((p, q) => q.s.k - p.s.k);
        for (const sp of sprs) { const camy = c.spriteCam[1], d = c.cam[1] - camy; blit(sp.s.idx, 16, sp.s.h, sp.x, sp.y + d); }
        return out;
    }

    // ---------------------------------------------------------------- the GPU (WebGL2, inside the presenter's framebuffer)
    const VS = `#version 300 es
    in vec2 a_pos; in vec2 a_uv; out vec2 v_uv; uniform vec2 u_size;
    void main() { v_uv = a_uv; vec2 p = a_pos / u_size * 2.0 - 1.0; gl_Position = vec4(p.x, -p.y, 0.0, 1.0); }`;
    const FS = `#version 300 es
    precision highp float; precision highp int;
    in vec2 v_uv; out vec4 o;
    uniform sampler2D u_tex; uniform sampler2D u_pal; uniform int u_mode; uniform float u_S; uniform ivec2 u_cami; uniform vec2 u_camf; uniform vec2 u_band;
    uniform ivec2 u_winpos; uniform ivec2 u_winsize; uniform highp usampler2D u_grid; uniform sampler2D u_atlas; uniform ivec4 u_map; uniform ivec4 u_fixed;
    int ix8(sampler2D t, ivec2 p) { return int(texelFetch(t, p, 0).r * 255.0 + 0.5); }
    void main() {
      if (u_mode == 0) { o = texture(u_tex, v_uv); return; }
      // the game pixel under this device pixel (its top-left corner; gl_FragCoord is the centre): floor(px / S + cam),
      // the camera as an integer part and a float32 fraction so that the CPU reference computes the same floor
      vec2 g = vec2((gl_FragCoord.x - 0.5 - u_band.x) / u_S + u_camf.x, (u_band.y - gl_FragCoord.y - 0.5) / u_S + u_camf.y);
      ivec2 w = ivec2(floor(g)) + u_cami;
      int row = clamp(w.y - u_winpos.y, 0, u_winsize.y - 1);
      if (u_mode == 2) {
        int idx = -1;
        if (u_fixed.x == 1 && (w.y < u_fixed.y || w.y >= u_fixed.z)) idx = -1;
        else if (u_fixed.x == 2 && (w.x < u_fixed.y || w.x >= u_fixed.z)) idx = -1;
        else {
          ivec2 b = w - u_winpos;
          if (b.x >= 0 && b.x < u_winsize.x && b.y >= 0 && b.y < u_winsize.y) { int v = ix8(u_tex, b); if (v != 255) idx = v; }
          if (idx < 0 && u_map.z > 0) { ivec2 m = w - u_map.xy; ivec2 c = m >> 4;
            if (m.x >= 0 && m.y >= 0 && c.x < u_map.z && c.y < u_map.w) { uint sl = texelFetch(u_grid, c, 0).r;
              if (sl != 0xffffu) idx = ix8(u_atlas, ivec2(int(sl % 32u) * 16 + (m.x & 15), int(sl / 32u) * 16 + (m.y & 15))); } }
        }
        if (idx < 0) { o = vec4(0.0, 0.0, 0.0, 1.0); return; }
        o = texelFetch(u_pal, ivec2(idx, row), 0); return;
      }
      ivec2 ts = textureSize(u_tex, 0); ivec2 p = ivec2(int(floor(v_uv.x * float(ts.x))), int(floor(v_uv.y * float(ts.y))));
      if (p.x < 0 || p.y < 0 || p.x >= ts.x || p.y >= ts.y) discard;
      int idx = int(texelFetch(u_tex, p, 0).r * 255.0 + 0.5); if (idx == 255) discard;
      o = texelFetch(u_pal, ivec2(idx, row), 0);
    }`;

    class Scene {
        constructor(opts) {
            this.opts = opts || {}; this.takt = this.opts.takt || null; this.frames = []; this.ring = this.opts.ring || 32;
            this.gl = null; this.cache = new Map(); this.pool = []; this.stats = { objs: 0, sprs: 0, uploads: 0, ms: 0, frames: 0 };
            this.atlasGen = -1; this.own = null; this.last = null;
        }
        /** A game frame record (see the header); keeps the last `ring` frames in time order. */
        frame(rec) {
            if (rec.objects) for (const ob of rec.objects) if (ob.key === undefined) ob.key = fnv1a(ob.idx, (ob.w << 16) ^ ob.h);
            this.frames.push(rec); if (this.frames.length > this.ring) this.frames.shift(); this.stats.frames++;
        }
        reset() { this.frames.length = 0; this.last = null; }
        compose(ts, view) { return compose(this.frames, ts, view, this.opts, this.takt); }
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
                for (const n of ['u_size', 'u_tex', 'u_pal', 'u_mode', 'u_S', 'u_cami', 'u_camf', 'u_band', 'u_winpos', 'u_winsize', 'u_grid', 'u_atlas', 'u_map', 'u_fixed']) this.u[n] = gl.getUniformLocation(prog, n);
                this.vao = gl.createVertexArray(); gl.bindVertexArray(this.vao); this.vbo = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, this.vbo);
                const aPos = gl.getAttribLocation(prog, 'a_pos'), aUv = gl.getAttribLocation(prog, 'a_uv');
                gl.enableVertexAttribArray(aPos); gl.vertexAttribPointer(aPos, 2, gl.FLOAT, false, 16, 0); gl.enableVertexAttribArray(aUv); gl.vertexAttribPointer(aUv, 2, gl.FLOAT, false, 16, 8);
                gl.bindVertexArray(null);
                this.texWin = this._tex(); this.texPal = this._tex(); this.texGrid = this._tex(); this.texAtlas = this._tex(); this.texHud = [this._tex(), this._tex()];
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
            const S = c.S, Wd = c.W * S, Hd = c.H * S, x0 = view.x0 || 0, y0 = view.y0 || 0, vy = d.h - y0 - Hd;
            const u = this.u, win = c.win;
            gl.bindFramebuffer(gl.FRAMEBUFFER, fbo); gl.useProgram(this.prog); gl.bindVertexArray(this.vao); gl.disable(gl.BLEND); gl.disable(gl.DEPTH_TEST); gl.disable(gl.SCISSOR_TEST); gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
            const ci = [Math.floor(c.cam[0]), Math.floor(c.cam[1])];
            gl.viewport(x0, vy, Wd, Hd); gl.uniform2f(u.u_size, Wd, Hd); gl.uniform1f(u.u_S, S); gl.uniform2i(u.u_cami, ci[0], ci[1]); gl.uniform2f(u.u_camf, c.cam[0] - ci[0], c.cam[1] - ci[1]); gl.uniform2f(u.u_band, x0, vy + Hd);
            gl.uniform2i(u.u_winpos, c.B.cam[0], c.B.cam[1]); gl.uniform2i(u.u_winsize, win.w, win.h);
            const fx = c.fixed; gl.uniform4i(u.u_fixed, fx ? (fx.axis === 'y' ? 1 : 2) : 0, fx ? (fx.axis === 'y' ? c.limits.y0 : c.limits.x0) : 0, fx ? (fx.axis === 'y' ? c.limits.y1 + win.h : c.limits.x1 + win.w) : 0, 0);
            gl.uniform1i(u.u_tex, 0); gl.uniform1i(u.u_pal, 1); gl.uniform1i(u.u_grid, 2); gl.uniform1i(u.u_atlas, 3);
            gl.activeTexture(gl.TEXTURE1); gl.bindTexture(gl.TEXTURE_2D, this.texPal); gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 32, win.h, 0, gl.RGBA, gl.UNSIGNED_BYTE, win.pal);
            const map = c.map;
            if (map) {
                gl.activeTexture(gl.TEXTURE3); gl.bindTexture(gl.TEXTURE_2D, this.texAtlas);
                if (map.gen !== this.atlasGen) { this.atlasGen = map.gen; gl.texImage2D(gl.TEXTURE_2D, 0, gl.R8, 512, 512, 0, gl.RED, gl.UNSIGNED_BYTE, null); for (let sl = 0; sl < map.nslots; sl++) this._slot(map, sl); }
                else if (map.dirty) for (let i = 0; i < map.dirty.length; i++) this._slot(map, map.dirty[i]);
                gl.activeTexture(gl.TEXTURE2); gl.bindTexture(gl.TEXTURE_2D, this.texGrid);
                gl.texImage2D(gl.TEXTURE_2D, 0, gl.R16UI, map.cols, map.rows, 0, gl.RED_INTEGER, gl.UNSIGNED_SHORT, map.cells);
                gl.uniform4i(u.u_map, map.origin[0], map.origin[1], map.cols, map.rows);
            } else gl.uniform4i(u.u_map, 0, 0, 0, 0);
            gl.activeTexture(gl.TEXTURE0); this._r8(this.texWin, win.w, win.h, win.idx);
            gl.uniform1i(u.u_mode, 2); this._quad(0, 0, Wd, Hd);
            gl.uniform1i(u.u_mode, 1); let objs = 0, sprs = 0;
            for (const ob of c.objs) { const e = this._objTex(ob.o); gl.bindTexture(gl.TEXTURE_2D, e.t); this._quad(Math.round((ob.x - c.cam[0]) * S), Math.round((ob.y - c.cam[1]) * S), e.w * S, e.h * S); objs++; }
            const sorted = c.sprs.slice().sort((p, q) => q.s.k - p.s.k), dy = c.cam[1] - c.spriteCam[1];
            for (const sp of sorted) { if (!this.pool[sprs]) this.pool[sprs] = this._tex(); this._r8(this.pool[sprs], 16, sp.s.h, sp.s.idx);
                this._quad(Math.round((sp.x - c.cam[0]) * S), Math.round((sp.y + dy - c.cam[1]) * S), 16 * S, sp.s.h * S); sprs++; }
            if (c.hud) this._hud(c, view, d, x0, y0);
            gl.bindVertexArray(null); this.stats.objs = objs; this.stats.sprs = sprs; this.stats.ms = performance.now() - t0;
            return true;
        }
        _slot(map, sl) { this.gl.texSubImage2D(this.gl.TEXTURE_2D, 0, (sl % 32) * 16, ((sl / 32) | 0) * 16, 16, 16, this.gl.RED, this.gl.UNSIGNED_BYTE, map.atlas.subarray(sl * 256, sl * 256 + 256)); }
        _hud(c, view, d, x0, y0) {
            const gl = this.gl, u = this.u, S = c.S, Wd = c.W * S;
            gl.uniform1i(u.u_mode, 0);
            [['top', -1], ['bottom', 1]].forEach(([k, side], i) => {
                const h = c.hud[k]; if (!h) return;
                const w0 = h.rgba.length / 4 / h.h, cols = widenColumns(w0, c.W, h.split), rgba = new Uint8Array(c.W * h.h * 4);
                for (let y = 0; y < h.h; y++) for (let x = 0; x < c.W; x++) { const s = (y * w0 + cols[x]) * 4, t = (y * c.W + x) * 4; rgba[t] = h.rgba[s]; rgba[t + 1] = h.rgba[s + 1]; rgba[t + 2] = h.rgba[s + 2]; rgba[t + 3] = 255; }
                const ty = side < 0 ? y0 - h.h * S : y0 + c.H * S, vy = d.h - ty - h.h * S;
                gl.viewport(x0, vy, Wd, h.h * S); gl.uniform2f(u.u_size, Wd, h.h * S);
                gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, this.texHud[i]); gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, c.W, h.h, 0, gl.RGBA, gl.UNSIGNED_BYTE, rgba);
                this._quad(0, 0, Wd, h.h * S);
            });
        }
        /** The band drawn into an own framebuffer and read back, RGBA rows top-down: the GPU against reference() (a 0-mismatch
         *  test as Alien Breed II ran one, 0 of 60 M pixels). */
        read(ts, view) {
            const gl = this.gl; if (!gl) return null;
            const c = this.compose(ts, view); if (!c) return null; const w = c.W * c.S, h = c.H * c.S;
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
    return { VERSION, lerp, clampCam, windowMean, pairById, pairOf, fnv1a, x17, widenColumns, compose, reference, Scene };
})();
if (typeof globalThis !== 'undefined') globalThis.WBSCENE = WBSCENE;
if (typeof module !== 'undefined') module.exports = WBSCENE;
