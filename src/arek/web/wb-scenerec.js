// wb-scenerec.js 1.0 (kit 1.0.77) - the host's scene record (arek_scene.h) as wb-scene's record. Node and the page alike.
//   const R = WBSCENEREC.reader(Module);            // Module of the engine built with arek_scene.h (ars_rec, ars_layout)
//   const r = R.rec(n);                             // frame n's record (null if the ring has moved on), r.valid, r.reason
//   const sc = WBSCENEREC.toScene(r, st, lut, opts) // { cam, limits, window, objects, sprites } for scene.frame(...)
//   const nx = WBSCENEREC.nextOf(r, sc, st)         // { passF, passC, objects } for rec.next (the page turns passF / passC into its time)
// st: one object the page keeps across frames (identities, the offsets of the game's units, which objects keep the screen).
// lut: 4096 x 3 bytes, a 12-bit colour -> RGB (the page's DAC; default component x 17).
// opts: runOf(img) - the run of an object from its picture word (wb-scene objMean breaks its mean where the run changes; default
//   none), groupOf(ob) - the group of an object (default: the node, a shadow apart), noScreen - do not detect objects that keep
//   their place on the screen, hudId - the HUD object's id.
// The window is the playfield under the objects (the clean picture), the objects are what the hinted routine drew, at their
// logical position from the game's own fields (x, y) with the drawing's offset (ox, oy); the HUD (what lies above the playfield:
// a fifth plane, lines outside its chain) is one object fixed on the screen; window.over is what the record does not explain
// (a CPU's drawing into the buffer, a blit outside the routine) - drawn as the game had it, not interpolated.
'use strict';
(function (root) {
    const VERSION = '1.0';
    function reader(M) {
        const L = (i) => M._ars_layout(i), size = L(0), NR = L(9), OBJ = L(11), SL = L(12), NX = L(13);
        const off = { pal: L(1), raw: L(2), clean: L(3), hud: L(4), obj: L(5), pix: L(6), sl: L(7), nx: L(8) };
        return {
            size,
            rec(n) {
                const p = M._ars_rec() + (n % NR) * size, buf = M.HEAPU8.buffer, v = new DataView(buf, p, size), I = (i) => v.getInt32(i * 4, true);
                if (I(0) !== n) return null;
                const r = { n, valid: I(1), reason: I(2), pass: I(3), passF: I(4), passC: I(5), camx: I(6), camy: I(7), w: I(8), h: I(9), v0: I(10), h0: I(11),
                    nobj: I(12), pool: I(13), nsl: I(14), nnx: I(15), nxPass: I(16), nxF: I(17), nxC: I(18), rows: I(19), planes: I(20),
                    hasCam: I(23), pcam: [I(24), I(25)], ncam: [I(26), I(27)], objs: [], sl: [], nx: [] };
                const u8 = (o, len) => new Uint8Array(buf.slice(p + o, p + o + len));
                r.pal = new Uint16Array(buf.slice(p + off.pal, p + off.pal + r.h * 64));
                r.nsl = Math.min(r.nsl, 2048);
                for (let i = 0; i < r.nsl; i++) { const q = off.sl + i * SL;
                    r.sl.push({ y: v.getInt16(q, true), k: v.getInt16(q + 2, true), hs: v.getInt16(q + 4, true), att: v.getInt16(q + 6, true), da: v.getUint16(q + 8, true), db: v.getUint16(q + 10, true) }); }
                if (!r.valid) return r;
                const W = r.w, H = r.h;
                r.raw = u8(off.raw, W * H); r.clean = u8(off.clean, W * H); r.hud = u8(off.hud, W * H); r.pix = u8(off.pix, r.pool);
                for (let i = 0; i < r.nobj; i++) { const q = off.obj + i * OBJ, J = (k) => v.getInt32(q + 4 * k, true);
                    r.objs.push({ node: v.getUint32(q, true), serial: J(1), k: J(2), kind: J(3), x: J(4), y: J(5), img: J(6) & 0xffff, pass: J(7), sx: J(8), sy: J(9), w: J(10), h: J(11), pix: J(12) }); }
                for (let i = 0; i < r.nnx; i++) { const q = off.nx + i * NX;
                    r.nx.push({ node: v.getUint32(q, true), x: v.getInt16(q + 4, true), y: v.getInt16(q + 6, true), img: v.getInt16(q + 8, true) & 0xffff }); }
                return r;
            },
        };
    }
    const s16 = (v) => ((((v | 0) + 0x8000) & 0xffff) - 0x8000);
    // the game's 16-bit position as a number of the kit's world: the offset between the two is learnt from the first object
    // and kept (a game's coordinates differ from the kit's camera by a constant; the 16 bits wrap, the kit's do not)
    function logical(st, axis, raw, world) {
        const K = st.K || (st.K = [null, null]);
        if (K[axis] === null) K[axis] = s16(raw - world);
        return world + K[axis] + s16(raw - world - K[axis]);
    }
    const x17 = (() => { const t = new Uint8Array(4096 * 3); for (let c = 0; c < 4096; c++) { t[3 * c] = ((c >> 8) & 15) * 17; t[3 * c + 1] = ((c >> 4) & 15) * 17; t[3 * c + 2] = (c & 15) * 17; } return t; })();
    function toScene(r, st, lut, opts) {
        opts = opts || {}; lut = lut || x17; st = st || {};
        const W = r.w, H = r.h, camX = r.camx, camY = r.camy;
        const pal = new Uint8Array(H * 32 * 4);
        for (let y = 0; y < H; y++) for (let c = 0; c < 32; c++) { const k = r.pal[y * 32 + c], q = (y * 32 + c) * 4; pal[q] = lut[k * 3]; pal[q + 1] = lut[k * 3 + 1]; pal[q + 2] = lut[k * 3 + 2]; pal[q + 3] = 255; }
        const comp = r.clean.slice(), owner = new Int32Array(W * H).fill(-1), objects = [];
        const scr = st.scr || (st.scr = new Map()), seen = new Set(), camMoved = st.lastCam !== undefined && st.lastCam !== camY;
        if (st.lastCam !== camY) st.lastCam = camY;
        for (const o of r.objs) {
            const X = camX + o.sx, Y = camY + o.sy, lx = logical(st, 0, o.x, X), ly = logical(st, 1, o.y, Y);
            const ob = { id: (o.node * 8 + Math.min(o.k, 7)) * 2 + o.kind, w: o.w, h: o.h, idx: r.pix.slice(o.pix, o.pix + o.w * o.h), x: lx, y: ly, ox: X - lx, oy: Y - ly, img: o.img, node: o.node, kind: o.kind };
            ob.group = opts.groupOf ? opts.groupOf(ob) : o.node * 2 + o.kind;
            if (opts.runOf) ob.run = opts.runOf(o.img);
            if (!opts.noScreen) {                      // the camera moved: an object that kept its place on the screen is on the screen
                const key = o.node, s = scr.get(key); seen.add(key);
                if (!s) scr.set(key, { y: ly, cam: camY, on: false });
                else { if (camMoved && s.cam !== camY) { if (ly !== s.y && ly - camY === s.y - s.cam) s.on = true; else if (ly === s.y) s.on = false; } s.y = ly; s.cam = camY; }
                if (scr.get(key).on) ob.screen = true;
            }
            for (let yy = 0; yy < o.h; yy++) { const sy = o.sy + yy; if (sy < 0 || sy >= H) continue;
                for (let xx = 0; xx < o.w; xx++) { const sx = o.sx + xx, c = ob.idx[yy * o.w + xx]; if (c === 255 || sx < 0 || sx >= W) continue;
                    comp[sy * W + sx] = c; owner[sy * W + sx] = objects.length * 65536 + yy * o.w + xx; } }
            objects.push(ob);
        }
        if (!opts.noScreen) for (const k of scr.keys()) if (!seen.has(k)) scr.delete(k);
        let h0 = -1, h1 = -1;
        for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) if (r.hud[y * W + x] !== 255) { if (h0 < 0) h0 = y; h1 = y; comp[y * W + x] = r.hud[y * W + x]; owner[y * W + x] = -1; }
        const over = new Uint8Array(W * H).fill(255);
        for (let i = 0; i < W * H; i++) if (comp[i] !== r.raw[i]) { over[i] = r.raw[i]; if (owner[i] >= 0) objects[owner[i] >> 16].idx[owner[i] & 0xffff] = 255; }
        if (h0 >= 0) { const hh = h1 - h0 + 1, idx = new Uint8Array(W * hh).fill(255); idx.set(r.hud.subarray(h0 * W, (h1 + 1) * W));
            objects.push({ id: opts.hudId !== undefined ? opts.hudId : 0x7fff0000, w: W, h: hh, idx, x: camX, y: camY + h0, ox: 0, oy: 0, screen: true }); }
        const sprites = [], runs = {};
        for (const s of r.sl.slice().sort((a, b) => a.k - b.k || a.y - b.y)) {
            let run = runs[s.k]; if (!run || run.y + run.rows.length !== s.y || run.hs !== s.hs) { run = runs[s.k] = { k: s.k, y: s.y, hs: s.hs, rows: [] }; sprites.push(run); }
            run.rows.push(s);
        }
        const spr = sprites.map((run, i) => { const h = run.rows.length, idx = new Uint8Array(16 * h).fill(255);
            run.rows.forEach((s, yy) => { for (let b = 0; b < 16; b++) { const val = ((s.da >> (15 - b)) & 1) | (((s.db >> (15 - b)) & 1) << 1); if (val) idx[yy * 16 + b] = 16 + 4 * (s.k >> 1) + val; } });
            return { k: run.k, h, w: 16, idx, x: run.hs - r.h0, y: run.y - r.v0, id: run.k * 1000 + i }; });
        return { cam: [camX, camY], limits: { x0: -1e9, x1: 1e9, y0: -1e9, y1: 1e9 }, window: { w: W, h: H, idx: r.clean, pal, over }, objects, sprites: spr };
    }
    // rec.next: the objects of the last shown pass at the positions the game's logic has given them since (the routine's object
    // fields read where the hint says the logic is done) and, with the hint's camera words, the logic's camera; without them
    // objects on the screen keep their place (the record has no camera of the logic)
    function nextOf(r, sc, st, opts) {
        if (!r.nx || !r.nx.length || r.nxPass <= r.pass) return null;
        opts = opts || {};
        const cam = r.hasCam ? [sc.cam[0] + s16(r.ncam[0] - r.pcam[0]), sc.cam[1] + s16(r.ncam[1] - r.pcam[1])] : undefined;
        const at = new Map(); for (const q of r.nx) at.set(q.node, q);
        const objects = [];
        for (const o of sc.objects) {
            if (o.node === undefined || (o.screen && !cam)) continue;
            const q = at.get(o.node); if (!q) continue;
            if (opts.runOf && opts.runOf(q.img) !== o.run) continue;
            const x = logical(st, 0, q.x, o.x + o.ox), y = logical(st, 1, q.y, o.y + o.oy);
            if (Math.abs(x - o.x) > 40 || Math.abs(y - o.y) > 40) continue;
            objects.push({ id: o.id, x, y, run: o.run });
        }
        return { passF: r.nxF, passC: r.nxC, cam, objects };
    }
    const api = { VERSION, reader, toScene, nextOf, logical };
    if (typeof module !== 'undefined') module.exports = api; else root.WBSCENEREC = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
