// wb-kresba.js 1.1 (kit 1.0.100) - wb-scene's composition drawn from the GAME'S STATE on a 2D canvas, not from the chips' picture
// (decision 2026-11-17: Enhanced = the exact translated logic + a renderer of its own; SWIV's web/sw_draw.js made general, docs/WB-KRESBA.md).
// 1.1 (Turrican II KIT-GAP, kit 1.0.100): the view starts at c.cam (compose() gives the view's top-left; 1.0 took ext off it again,
// so with margins the whole picture was ext px off - SWIV has none); the hardware sprites c.sprs are drawn as WBSCENE.reference
// draws them (after the objects, lower k on top, on the screen or with the ground per axis, a sprite fixed on the screen with its
// screen rows' palette); opt.window puts the game's own window picture into the terrain's indices in the world raster of frame B.
//   const K = WBKRESBA.create(document);                 // or any object with createElement('canvas') (an OffscreenCanvas shim)
//   const r = K.paint(ctx, c, S, game, opt);             // c = scene.compose(...) of wb-scene, S = device px per game px
// game (the game's adapter; everything optional but terrain):
//   terrain(wy, x0, w, out) -> bool   palette indices (0..31) of world row wy, world columns x0 .. x0 + w - 1, into out (Uint8Array w);
//                                     false = nothing there (drawn black). The game's own buffer where it drew into the ground
//                                     (craters), its map elsewhere - the adapter decides.
//   cover(wy, x0, w, out) -> bool     1 where the foreground covers world row wy (objects that are behind it are hidden there)
//   frame(ob) -> { pix, w, h, ox, oy, key, used? } | null    the object's picture by its identity (graphics from the disk, a frame
//                                     built at run time from RAM ...): indices, 255 transparent; null = the composition's own ob.idx
//   skip(ob) -> bool                  not drawn at all (SWIV: a band object whose node the window object draws whole)
//   behind(ob) -> bool                drawn behind the foreground (needs cover and a whole S)
//   op(ob) -> 0 | 1 | 2               1 = a shadow (every pixel shadowColour), 2 = a flash (every pixel flashColour)
//   shadowColour (0), flashColour (9)
//   after(ob, put) -> void            extras drawn right after the object (SWIV: the rotor disc): put(im, key, alpha, ax, ay) draws
//                                     the picture im at the object's anchor + (ax, ay) game px with the object's palette rows
//   indices(tidx, v), ground(ctx, v), top(ctx, v)    stage hooks: the terrain's indices before the palette (stamps), after the
//                                     terrain is drawn (water), after everything (overlays); v = { S, k, top, left, rows, cols, vx, vy,
//                                     ext, VW, VH, palRow, pal, p32, tidx, timg, tx0, ty0, c }: the terrain's rows top.. / columns left..,
//                                     tidx / timg its indices / RGBA (cols x rows), tx0 / ty0 where its column / row 0 lands (device px)
// opt: blend (true) - a fractional camera as two whole-pixel layers blended by the fraction (sharp pixels, even motion), else the
//      nearest device pixel; subpixel (true) - objects and sprites at their fractional position (smoothed), else on whole device
//      pixels; soft (0) - a shadow's blur in game px (0 = hard);
//      window (false) - 1.1: 'over' = c.win.over (what the game drew that the state does not explain: a safety net, a transition
//      grid, a boss without a hook) over the terrain where it is not 255; 'all' = c.win.idx (at window.origin, its rows) and then
//      c.win.over, as WBSCENE.reference's playfield; both after game.indices and below the objects, not interpolated (frame B);
//      sprites (true) - 1.1: draw c.sprs. Not drawn: c.back, c.win.or, c.hud.
// Returns { pos, ms }: pos = [id, x, y] where each object was really drawn (world px, its logical anchor - websmooth's objs),
// ms = the paint's time (WBLONGRUN.drawMs). Palette: c.win.pal rows (RGBA) from c.win.palTop; an object with the ground takes the
// rows of the world rows it covers, an object fixed on the screen the rows of its screen rows (wb-scene 2.19). The view is
// c.W x c.H game px from c.cam (compose() gives the view's top-left, the window at ext inside it); a camera fraction on x and y.
'use strict';
(function (root) {
    const VERSION = '1.1';
    const fnv = (a) => { let h = 0x811c9dc5; for (let i = 0; i < a.length; i++) h = Math.imul(h ^ a[i], 16777619); return h >>> 0; };
    const usedOf = (pix) => { let u = 0; for (let i = 0; i < pix.length; i++) if (pix[i] !== 255) u |= 1 << (pix[i] & 31); return u >>> 0; };
    function create(doc) {
        const st = { cache: new Map(), used: new Map(), pos: [], ms: undefined, msMax: 0, sprs: 0 };
        const canvas = (w, h) => { const c = doc.createElement('canvas'); c.width = Math.max(1, w); c.height = Math.max(1, h); return c; };
        const keep = (key, cv) => { if (st.cache.size > 800) st.cache.delete(st.cache.keys().next().value); st.cache.set(key, cv); return cv; };
        // the colours an image uses, per its rows: the key changes only when one of ITS colours changes (a pulsing colour elsewhere
        // does not recolour every image - SWIV: colour 7 every 4 frames filled the cache, 38-51 fps)
        function sigOf(p32, used, h, rp) {
            let out = '', last = -1;
            for (let yy = 0; yy < h; yy++) { const q = rp(yy) * 32; let hh = 0x811c9dc5; for (let c = 0, u = used; u; c++, u >>>= 1) if (u & 1) hh = Math.imul(hh ^ p32[q + c], 16777619);
                hh >>>= 0; if (hh !== last) { out += yy + ':' + hh.toString(36) + ','; last = hh; } }
            return out;
        }
        // indices coloured by their rows' palettes, enlarged k x by the nearest neighbour, with a transparent border of 1 device px
        function image(key, pix, w, h, k, rp, pal, op, sc, fc) {
            let cv = st.cache.get(key); if (cv) { st.cache.delete(key); st.cache.set(key, cv); return cv; }
            const small = canvas(w, h), g0 = small.getContext('2d'), img = g0.createImageData(w, h), d = img.data;
            for (let y = 0; y < h; y++) { const q0 = rp(y) * 128;
                for (let x = 0; x < w; x++) { let c = pix[y * w + x]; if (c === 255) continue; if (op === 1) c = sc; else if (op === 2) c = fc;
                    const q = q0 + (c & 31) * 4, o = (y * w + x) * 4; d[o] = pal[q]; d[o + 1] = pal[q + 1]; d[o + 2] = pal[q + 2]; d[o + 3] = 255; } }
            g0.putImageData(img, 0, 0);
            cv = canvas(w * k + 2, h * k + 2); const g = cv.getContext('2d'); g.imageSmoothingEnabled = false; g.drawImage(small, 1, 1, w * k, h * k);
            return keep(key, cv);
        }
        function softOf(key, cv, k, w, h, dw, dh, blur) {
            const bk = key + '|soft' + blur; let b = st.cache.get(bk); if (b) return b;
            const p = Math.ceil(3 * blur); b = canvas(dw + 2 * p, dh + 2 * p); const g = b.getContext('2d'); g.filter = 'blur(' + blur.toFixed(2) + 'px)';
            g.drawImage(cv, 1, 1, w * k, h * k, p, p, dw, dh); b._p = p; return keep(bk, b);
        }
        let tcv = null, timg = null, tidx = null, trow = null, layer = null, mcv = null, mb = null, crow = null, w2 = null;
        // 1.1: the game's window picture into the terrain's indices (top / left = the terrain's world row / column 0): idx at
        // window.origin (default frame B's cam) with its rows, then over at frame B's cam - the world raster of frame B, as the reference
        function windowInto(c, win, top, left, rows, cols, all) {
            const put = (src, x0, y0, h) => { for (let y = 0; y < h; y++) { const ty = y0 + y - top; if (ty < 0 || ty >= rows) continue;
                for (let x = 0; x < win.w; x++) { const tx = x0 + x - left; if (tx < 0 || tx >= cols) continue; const val = src[y * win.w + x]; if (val !== 255) tidx[ty * cols + tx] = val; } } };
            const bx = Math.round(c.B.cam[0]), by = Math.round(c.B.cam[1]);
            if (all && win.idx) { const org = c.winAt || [bx, by]; put(win.idx, Math.round(org[0]), Math.round(org[1]), c.winRows || Math.floor(win.idx.length / win.w)); }
            if (win.over) put(win.over, bx, by, win.h);
        }
        function paint(ctx, c, S, game, opt) {
            const t0 = typeof performance !== 'undefined' ? performance.now() : 0;
            const o = Object.assign({ blend: true, subpixel: true, soft: 0, window: false, sprites: true }, opt || {}), G = game || {};
            const ext = c.ext || { x: 0, y: 0 }, VW = c.W, VH = c.H, Wd = Math.round(VW * S), Hd = Math.round(VH * S), k = Math.max(1, Math.floor(S));
            const win = c.win, pal = win.pal, prow = pal.length / 128, palTop = win.palTop | 0, winY = c.B.cam[1];
            const p32 = new Uint32Array(pal.buffer, pal.byteOffset, pal.length / 4);
            const palRow = (wy) => Math.min(Math.max(wy - winY + palTop, 0), prow - 1);
            const scr0 = c.palScreen != null ? c.palScreen : ext.y;          // the band row of the screen's row 0 (wb-scene 2.19)
            const vx = c.cam[0], vy = c.cam[1];                               // the view's top-left in the world (fractional): compose()'s cam (1.1)
            const left = Math.floor(vx), top = Math.floor(vy), cols = VW + 2, rows = VH + 2;
            // the terrain: whole world rows / columns, coloured by the palette of their world row
            if (!tcv || tcv.width !== cols || tcv.height !== rows) { tcv = canvas(cols, rows); timg = tcv.getContext('2d').createImageData(cols, rows); tidx = new Uint8Array(cols * rows); trow = new Uint8Array(cols); }
            for (let y = 0; y < rows; y++) { if (G.terrain && G.terrain(top + y, left, cols, trow)) tidx.set(trow, y * cols); else tidx.fill(0, y * cols, (y + 1) * cols); }
            const v = { S, k, top, left, rows, cols, vx, vy, ext, VW, VH, palRow, pal, p32, tidx, timg, c };
            if (G.indices) G.indices(tidx, v);
            if (o.window) windowInto(c, win, top, left, rows, cols, o.window === 'all');
            { const d32 = new Uint32Array(timg.data.buffer);
                for (let y = 0; y < rows; y++) { const q = palRow(top + y) * 32; for (let x = y * cols, e = x + cols; x < e; x++) d32[x] = p32[q + (tidx[x] & 31)]; } }
            tcv.getContext('2d').putImageData(timg, 0, 0);
            ctx.save(); ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.imageSmoothingEnabled = false; ctx.globalAlpha = 1; ctx.fillStyle = '#000'; ctx.fillRect(0, 0, Wd, Hd);
            const fx = (vx - left) * S, fy = (vy - top) * S;
            const tx0 = -Math.round(fx), ty0 = -Math.round(fy);              // where the terrain's column / row 0 lands (device px) for the masks
            if (o.blend) {                                                     // two whole-pixel layers per axis, blended by the fraction
                const lx = Math.floor(fx), ly = Math.floor(fy), ax = fx - lx, ay = fy - ly, put = (dx, dy, a) => { if (a <= 0.002) return; ctx.globalAlpha = a; ctx.drawImage(tcv, 0, 0, cols, rows, -lx - dx, -ly - dy, cols * S, rows * S); };
                ctx.globalAlpha = 1; ctx.drawImage(tcv, 0, 0, cols, rows, -lx, -ly, cols * S, rows * S);
                if (ay > 0.002) put(0, 1, ay);
                if (ax > 0.002) { if (!w2 || w2.width !== Wd || w2.height !== Hd) w2 = canvas(Wd, Hd); const g2 = w2.getContext('2d'); g2.globalAlpha = 1; g2.clearRect(0, 0, Wd, Hd); g2.imageSmoothingEnabled = false; g2.drawImage(tcv, 0, 0, cols, rows, -lx - 1, -ly, cols * S, rows * S);
                    if (ay > 0.002) { g2.globalAlpha = ay; g2.drawImage(tcv, 0, 0, cols, rows, -lx - 1, -ly - 1, cols * S, rows * S); }
                    ctx.globalAlpha = ax; ctx.drawImage(w2, 0, 0); }
                ctx.globalAlpha = 1;
            } else ctx.drawImage(tcv, 0, 0, cols, rows, tx0, ty0, cols * S, rows * S);
            v.tx0 = tx0; v.ty0 = ty0;
            if (G.ground) G.ground(ctx, v);
            const pos = st.pos = [], sc = G.shadowColour === undefined ? 0 : G.shadowColour, flc = G.flashColour === undefined ? 9 : G.flashColour;
            for (const e of c.objs) {
                const a = e.a === undefined ? 256 : e.a; if (a <= 0) continue; const ob = e.o;
                if (G.skip && G.skip(ob)) continue;
                const fr = G.frame ? G.frame(ob) : null, op = G.op ? G.op(ob) | 0 : 0;
                let pix, w, h, ox, oy, key, used;
                if (fr && fr.w > 0) { pix = fr.pix; w = fr.w; h = fr.h; ox = fr.ox; oy = fr.oy; key = 'f' + fr.key + ':' + op;
                    used = op === 1 ? (1 << sc) >>> 0 : op === 2 ? (1 << flc) >>> 0 : fr.used !== undefined ? fr.used : (fr.used = usedOf(fr.pix)); }
                else { if (!ob.idx) continue; pix = ob.idx; w = ob.w; h = ob.h; ox = ob.ox || 0; oy = ob.oy || 0; key = 'i' + w + 'x' + h + ':' + (ob.key || fnv(ob.idx)) + ':' + op;
                    used = st.used.get(key); if (used === undefined) { if (st.used.size > 2000) st.used.clear(); st.used.set(key, used = op === 1 ? (1 << sc) >>> 0 : op === 2 ? (1 << flc) >>> 0 : usedOf(pix)); } }
                const sx = !!e.sx || !!e.screen, sy = !!e.sy || !!e.screen;
                const gx = sx ? ext.x + e.scr[0] + ox : e.x + ox - vx, gy = sy ? ext.y + e.scr[1] + oy : e.y + oy - vy;   // in the view (game px, fractions)
                const wy0 = Math.floor(vy + gy), sr0 = Math.floor(gy) - scr0 + palTop;
                const rp = sy ? (yy) => Math.min(Math.max(sr0 + yy, 0), prow - 1) : (yy) => palRow(wy0 + yy), sig = sigOf(p32, used, h, rp);
                const cv = image(key + '|' + sig + '|' + k, pix, w, h, k, rp, pal, op, sc, flc);
                const px = gx * S, py = gy * S, dw = w * S, dh = h * S;
                ctx.globalAlpha = a / 256;
                const anchor = [gx - ox + vx, gy - oy + vy];
                const masked = G.cover && G.behind && G.behind(ob) && !sy && Number.isInteger(S);
                let done = false;
                if (masked) {                                                  // behind the foreground: the object on its own layer, the cover cut out in the terrain's grid
                    const mx0 = Math.floor((px - tx0) / S + left), mx1 = Math.floor((px + dw - 1e-6 - tx0) / S + left), my0 = Math.floor((py - ty0) / S + top), my1 = Math.floor((py + dh - 1e-6 - ty0) / S + top);
                    const mw = Math.max(0, mx1 - mx0 + 1), mh = Math.max(0, my1 - my0 + 1); let any = false;
                    if (!mb || mb.length < mw * mh) mb = new Uint8Array(mw * mh * 2); mb.fill(0, 0, mw * mh);
                    if (!crow || crow.length < mw) crow = new Uint8Array(mw * 2);
                    for (let my = my0; my <= my1; my++) { const cr = crow.subarray(0, mw); cr.fill(0); if (!G.cover(my, mx0, mw, cr)) continue;
                        for (let i = 0; i < mw; i++) if (cr[i]) { mb[(my - my0) * mw + i] = 1; any = true; } }
                    if (any) {
                        const Lx = Math.floor(px), Ly = Math.floor(py), Lw = Math.ceil(dw) + 2, Lh = Math.ceil(dh) + 2;
                        if (!layer || layer.width < Lw || layer.height < Lh) layer = canvas(Math.max(Lw, layer ? layer.width : 0), Math.max(Lh, layer ? layer.height : 0));
                        const g = layer.getContext('2d'); g.globalCompositeOperation = 'source-over'; g.globalAlpha = 1; g.clearRect(0, 0, Lw, Lh);
                        g.imageSmoothingEnabled = !!o.subpixel; g.drawImage(cv, 1, 1, w * k, h * k, o.subpixel ? px - Lx : Math.round(px) - Lx, o.subpixel ? py - Ly : Math.round(py) - Ly, dw, dh);
                        if (!mcv || mcv.width < mw || mcv.height < mh) mcv = canvas(Math.max(mw, mcv ? mcv.width : 0, 64), Math.max(mh, mcv ? mcv.height : 0, 64));
                        const mg = mcv.getContext('2d'), mi = mg.createImageData(mw, mh); for (let i = 0; i < mw * mh; i++) if (mb[i]) mi.data[i * 4 + 3] = 255; mg.putImageData(mi, 0, 0);
                        g.globalCompositeOperation = 'destination-out'; g.imageSmoothingEnabled = false; g.drawImage(mcv, 0, 0, mw, mh, (mx0 - left) * S + tx0 - Lx, (my0 - top) * S + ty0 - Ly, mw * S, mh * S); g.globalCompositeOperation = 'source-over';
                        if (o.soft > 0 && op === 1) { ctx.filter = 'blur(' + (o.soft * S).toFixed(2) + 'px)'; ctx.imageSmoothingEnabled = true; ctx.drawImage(layer, 0, 0, Lw, Lh, Lx, Ly, Lw, Lh); ctx.filter = 'none'; }
                        else { ctx.imageSmoothingEnabled = false; ctx.drawImage(layer, 0, 0, Lw, Lh, Lx, Ly, Lw, Lh); }
                        pos.push([ob.id, anchor[0], anchor[1]]); done = true;
                    }
                }
                if (!done) {
                    if (o.soft > 0 && op === 1) { const b = softOf(key + '|' + sig + '|' + k, cv, k, w, h, Math.round(dw), Math.round(dh), o.soft * S); ctx.imageSmoothingEnabled = true; ctx.drawImage(b, px - b._p, py - b._p); pos.push([ob.id, anchor[0], anchor[1]]); }
                    else if (!o.subpixel || (Math.abs(px - Math.round(px)) < 0.01 && Math.abs(py - Math.round(py)) < 0.01 && k === S)) {
                        ctx.imageSmoothingEnabled = false; ctx.drawImage(cv, 1, 1, w * k, h * k, Math.round(px), Math.round(py), dw, dh); pos.push([ob.id, Math.round(px) / S - ox + vx, Math.round(py) / S - oy + vy]); }
                    else { ctx.imageSmoothingEnabled = true; ctx.drawImage(cv, 1, 1, w * k, h * k, px, py, dw, dh); pos.push([ob.id, anchor[0], anchor[1]]); }
                }
                if (G.after) {                                                 // extras at the object's anchor with its palette rows
                    const ax0 = gx - ox, ay0 = gy - oy, a0 = a / 256;
                    G.after(ob, (im, ikey, alpha, ax, ay) => {
                        const rq = (yy) => rp(yy + ay + (im.oy || 0) - oy), iu = im.used !== undefined ? im.used : (im.used = usedOf(im.pix)), isig = sigOf(p32, iu, im.h, rq);
                        const icv = image(ikey + '|' + isig + '|' + k, im.pix, im.w, im.h, k, rq, pal, 0, sc, flc);
                        const qx = (ax0 + ax + (im.ox || 0)) * S, qy = (ay0 + ay + (im.oy || 0)) * S; ctx.globalAlpha = a0 * alpha; ctx.imageSmoothingEnabled = !!o.subpixel;
                        if (o.subpixel) ctx.drawImage(icv, 1, 1, im.w * k, im.h * k, qx, qy, im.w * S, im.h * S); else ctx.drawImage(icv, 1, 1, im.w * k, im.h * k, Math.round(qx), Math.round(qy), im.w * S, im.h * S);
                        ctx.globalAlpha = a0; });
                }
            }
            ctx.globalAlpha = 1;
            if (o.sprites && c.sprs && c.sprs.length) {                         // 1.1: the hardware sprites as WBSCENE.reference: lower k on top
                const sprs = c.sprs.slice().sort((p, q) => q.s.k - p.s.k), scam = c.spriteCam || c.cam;
                for (const sp of sprs) {
                    const s = sp.s, h = s.h | 0; if (!s.idx || h <= 0) continue;
                    const X = sp.sx && !sp.screen ? sp.x + c.cam[0] - scam[0] : sp.x, Y = sp.sy && !sp.screen ? sp.y + c.cam[1] - scam[1] : sp.y;
                    const gx = X - vx, gy = Y - vy;                              // in the view (game px)
                    const sr0 = Math.floor(gy) - scr0 + palTop, wy0 = Math.floor(vy + gy);
                    const rp = sp.screen ? (yy) => Math.min(Math.max(sr0 + yy, 0), prow - 1) : (yy) => palRow(wy0 + yy);
                    const key = 's' + h + ':' + (s.key || fnv(s.idx)); let used = st.used.get(key);
                    if (used === undefined) { if (st.used.size > 2000) st.used.clear(); st.used.set(key, used = usedOf(s.idx)); }
                    const cv = image(key + '|' + sigOf(p32, used, h, rp) + '|' + k, s.idx, 16, h, k, rp, pal, 0, 0, 0);
                    const px = gx * S, py = gy * S, dw = 16 * S, dh = h * S;
                    if (!o.subpixel || (Math.abs(px - Math.round(px)) < 0.01 && Math.abs(py - Math.round(py)) < 0.01 && k === S)) {
                        ctx.imageSmoothingEnabled = false; ctx.drawImage(cv, 1, 1, 16 * k, h * k, Math.round(px), Math.round(py), dw, dh); }
                    else { ctx.imageSmoothingEnabled = true; ctx.drawImage(cv, 1, 1, 16 * k, h * k, px, py, dw, dh); }
                    st.sprs++;
                }
            }
            if (G.top) G.top(ctx, v);
            ctx.restore();
            let ms;
            if (t0) { ms = performance.now() - t0; st.ms = st.ms === undefined ? ms : st.ms * 0.95 + ms * 0.05; if (ms > st.msMax) st.msMax = ms; }
            return { pos, ms };
        }
        return { VERSION, st, paint, clear() { st.cache.clear(); st.used.clear(); }, info: () => ({ cache: st.cache.size, ms: st.ms, msMax: st.msMax }) };
    }
    const api = { VERSION, create, usedOf };
    if (typeof module !== 'undefined') module.exports = api; else root.WBKRESBA = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
