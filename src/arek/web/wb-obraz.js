// wb-obraz.js - reference implementation of the display contract "wb-shell obraz 1.3"
// (amiga-re-kit, WB-OBRAZ-CRT.md). Whole device pixels per game pixel (S), zoom = window width in
// multiples of the Original's width W0, the CRT as a second canvas in device pixels, blur 0.8 game
// pixel at 100 %, the content placed on a whole device pixel by layout (left/top) - never transform.
// No game data. Works as a <script> (global WBOBRAZ, also globalThis.WBOBRAZ - an ES module that imports
// nothing can read it there), as CommonJS (require) and in Node for tests.
// Projects copy this file (`arek web copy DIR`) and keep its sha256 in their docs.
//
// Test hooks a page provides for `arek web test URL` (contract §5):
//   window.wbObrazTest.set(mode, {zoom, crtDetail, crtShape, crt, blur}) -> info
//       mode 'original' | 'enhanced'; zoom: window width in multiples of W0, 0 = fit; returns
//       {scale: S, W, H, P, D, origin: [x, y] device px, backing: [w, h], content: [W*S, H*S],
//        crtLayer: [w, h], crtOrigin: [x, y]}   (Screen.info() gives origin/backing/crtLayer/crtOrigin)
//   window.wbObrazTest.fill(kind) -> true      kind 'grey' | 'rows' | 'cols' (testPattern); the pattern must stay
//       on the canvas until the next set() - a running game must not paint over it (pause it, or hold the pattern)
// arek web test needs `pip install amiga-re-kit[web]` and `python -m playwright install chromium`.
'use strict';
const WBOBRAZ = (() => {
    const VERSION = '1.3';
    const CRT_DETAILS = ['fine', 'standard', 'strong'];
    const CRT_SHAPES = ['lines', 'grid'];
    // 1.3 values (Alien Breed / Turrican II, 2026-10-22: larger steps between the levels)
    const CRT_ROW = { fine: .25, standard: .40, strong: .55 };                    // Original: dark part of a game row
    const CRT_SCREEN = { fine: 2, standard: 3, strong: 4 };                       // Enhanced: fixed grid of device pixels
    const CRT_LINE = { original: { fine: .12, standard: .35, strong: .65 }, enhanced: { fine: .08, standard: .25, strong: .50 } };
    const CRT_RGB = { fine: .01, standard: .03, strong: .06 };
    const MODE_MS = 450;
    const VIEW_DEFAULTS = { original: { zoom: 2, crt: true, crtDetail: 'strong', crtShape: 'lines', blur: 0 },
                            enhanced: { zoom: 3, crt: true, crtDetail: 'fine', crtShape: 'lines', blur: 20 } };
    const WORDS = { fit: 'fit', limited: 'limited to', actual: 'actually' };   // games pass their own (Czech: do okna, omezeno na, skutečně)
    const dprNow = () => (typeof window !== 'undefined' && window.devicePixelRatio) || 1;

    /** S, whole device pixels per game pixel (§1). zoom = window width in multiples of w0 (0 = fit), w = logical
     *  canvas width, limit = the largest CSS px per game pixel that fits. Zoom: round(zoom*w0/w*dpr), fit: floor(limit*dpr). */
    function deviceScale(zoom, w0, w, dpr, limit) {
        const floor = Math.max(1, Math.floor(limit * dpr + 1e-6));
        return zoom > 0 ? Math.min(Math.max(1, Math.round(zoom * w0 / w * dpr)), floor) : floor;
    }
    /** Period P and dark band D in device pixels (§2): Original P = max(2, S), D = round(P * row); Enhanced fixed P, D = 1. */
    function crtParams(mode, detail, S) {
        const P = mode === 'original' ? Math.max(2, S) : (CRT_SCREEN[detail] || 3);
        const D = mode === 'original' ? Math.max(1, Math.round(P * (CRT_ROW[detail] || .40))) : 1;
        return { P, D };
    }
    /** Scanlines and R/G/B mask into a canvas whose backing is w x h device pixels (§2). shape 'grid' also darkens
     *  the end of every column period (squares), crossings only once. Returns { P, D, shape }. */
    function drawCrt(c, mode, detail, S, dpr, w, h, shape) {
        const { P, D } = crtParams(mode, detail, S);
        const line = (CRT_LINE[mode] || CRT_LINE.enhanced)[detail] || .35, rgb = CRT_RGB[detail] || .03;
        c.width = w; c.height = h;
        if (c.style) { c.style.width = w / dpr + 'px'; c.style.height = h / dpr + 'px'; }
        const g = c.getContext('2d'); g.clearRect(0, 0, w, h);
        ['255,0,0', '0,255,0', '0,0,255'].forEach((col, k) => {
            g.fillStyle = 'rgba(' + col + ',' + rgb + ')';
            for (let x = k; x < w; x += 3) g.fillRect(x, 0, 1, h);
        });
        g.fillStyle = 'rgba(0,0,0,' + line + ')';
        if (shape === 'grid')
            for (let y = 0; y < h; y += P) {
                const bot = Math.min(h, y + P - D);
                for (let x = P - D; x < w; x += P) g.fillRect(x, y, D, bot - y);
            }
        for (let y = P - D; y < h; y += P) g.fillRect(0, y, w, D);
        return { P, D, shape: shape === 'grid' ? 'grid' : 'lines' };
    }
    /** CSS filter of the game canvas (§3): monitor knobs only when not 100 %, blur = blur/100 * 0.8 * pixel
     *  (pixel = CSS px per game pixel = S/dpr); nothing at all when everything is neutral (no extra layer). */
    function filter(look, pixel) {
        const parts = [], k = (v) => (typeof v === 'number' ? v : 100);
        const b = k(look.brightness), c = k(look.contrast), s = k(look.saturation);
        if (Math.round(b) !== 100) parts.push('brightness(' + (b / 100).toFixed(3) + ')');
        if (Math.round(c) !== 100) parts.push('contrast(' + (c / 100).toFixed(3) + ')');
        if (Math.round(s) !== 100) parts.push('saturate(' + (s / 100).toFixed(3) + ')');
        if (look.blur > .05) parts.push('blur(' + (look.blur / 100 * 0.8 * pixel).toFixed(2) + 'px)');
        return parts.length ? parts.join(' ') : 'none';
    }
    /** CRT opacity during the mode change (§4): both with CRT - the old pattern fades to 40 % and the new one
     *  takes over at half time; otherwise linear. */
    function crtOn(e, from, to) {
        if (from > 0 && to > 0) return e < .5 ? from * (1 - 1.2 * e) : 1 - 1.2 * (1 - e);
        return from + (to - from) * e;
    }
    const smoothstep = (t) => t * t * (3 - 2 * t);
    /** The zoom as the player wished it and as whole device pixels made it ("3x - limited to 2.5x"). */
    function zoomLabel(wish, S, dpr, w0, w, words) {
        const t = Object.assign({}, WORDS, words || {}), real = S / dpr * w / w0;
        const x = (n) => String(+n.toFixed(2)) + '×';
        if (!(wish > 0)) return t.fit + ' (' + x(real) + ')';
        if (Math.abs(real - wish) < .005) return x(wish);
        return x(wish) + ' · ' + (S < Math.round(wish * w0 / w * dpr) ? t.limited : t.actual) + ' ' + x(real);
    }
    /** Layout quantum (1.3): a canvas is drawn exactly only when its CSS position and size are whole CSS pixels
     *  (Chromium keeps layout in 1/64 CSS px and paints a half CSS px a device row off - Alien Breed, dpr 2).
     *  q = the fewest device pixels that are a whole number of CSS px: 1 at dpr 1, 5 at 1.25, 3 at 1.5, 2 at 2.
     *  Sizes and positions are kept on multiples of q; otherwise an edge row blends, a row doubles or goes. */
    function quantum(dpr) {
        for (let q = 1; q <= 64; q++) { const u = q / dpr; if (Math.abs(u - Math.round(u)) < 1e-6) return q; }
        return 1;
    }
    /** n device pixels rounded up to the layout quantum (the canvas backing; the game draws into its top left W·S x H·S). */
    function padded(n, dpr) { const q = quantum(dpr); return Math.ceil(n / q) * q; }
    /** Offset (CSS px) that puts a box whose left/top are at `left`, `top` CSS px on whole device pixels that are
     *  multiples of the layout quantum. */
    function snap(left, top, dpr) {
        const q = quantum(dpr), at = (v) => (Math.round(v * dpr / q) * q - v * dpr) / dpr;
        return [at(left), at(top)];
    }
    /** Fill the W x H game picture (S device pixels per game pixel, top left of the canvas) with a test pattern
     *  (§5): 'grey' (#808080, §5.4), 'rows' - game row y gets the grey 32 + 24 * (y mod 8), so a doubled or
     *  missing row shows (§5.4b) - or 'cols', the same per game column. The padding beyond W*S x H*S stays black. */
    function testPattern(c, kind, W, H, S) {
        const g = c.getContext('2d');
        g.fillStyle = '#000'; g.fillRect(0, 0, c.width, c.height);
        if (kind === 'grey') { g.fillStyle = '#808080'; g.fillRect(0, 0, W * S, H * S); return; }
        if (kind === 'cols') {
            for (let x = 0; x < W; x++) {
                const v = 32 + 24 * (x % 8);
                g.fillStyle = 'rgb(' + v + ',' + v + ',' + v + ')';
                g.fillRect(x * S, 0, S, H * S);
            }
            return;
        }
        for (let y = 0; y < H; y++) {
            const v = 32 + 24 * (y % 8);
            g.fillStyle = 'rgb(' + v + ',' + v + ',' + v + ')';
            g.fillRect(0, y * S, W * S, S);
        }
    }

    /** The game box .game: the CRT layer (redrawn only when its key changes), --crt-on, data-crt / data-mode,
     *  and the content on a whole device pixel by layout (1.3: position relative + left/top, no transform). */
    class Screen {
        constructor(gameEl, canvas) {
            this.game = gameEl; this.canvas = canvas;
            this.layer = gameEl.querySelector('.crt-layer');
            if (!this.layer) {
                this.layer = document.createElement('canvas'); this.layer.className = 'crt-layer';
                this.layer.setAttribute('aria-hidden', 'true'); gameEl.appendChild(this.layer);
            }
            this.key = ''; this.pd = { P: 3, D: 1, shape: 'lines' }; this.ax = 0; this.ay = 0; this.on = 0;
            if (getComputedStyle(gameEl).position === 'static') gameEl.style.position = 'relative';
        }
        /** o = { mode, detail, shape, S, dpr, w, h, on }: w, h = the game content in device pixels (W*S x H*S). */
        crt(o) {
            const key = [o.w, o.h, o.S, o.dpr, o.mode, o.detail, o.shape].join(':');
            if (key !== this.key) { this.key = key; this.pd = drawCrt(this.layer, o.mode, o.detail, o.S, o.dpr, Math.max(1, o.w), Math.max(1, o.h), o.shape); }
            this.on = o.on;
            this.game.style.setProperty('--crt-on', (+o.on).toFixed(3));
            this.game.dataset.crt = o.detail; this.game.dataset.mode = o.mode;
            return this.pd;
        }
        /** §1.4 (1.3): the top left corner of the canvas content on a whole device pixel, by left/top. */
        align() {
            const r = this.canvas.getBoundingClientRect(); if (!r.width) return;
            const dpr = dprNow(), bw = this.canvas.clientLeft || 0, bt = this.canvas.clientTop || 0;
            const [nx, ny] = snap(r.left + bw - this.ax, r.top + bt - this.ay, dpr);
            if (Math.abs(nx - this.ax) < 1e-4 && Math.abs(ny - this.ay) < 1e-4) return;
            this.ax = nx; this.ay = ny;
            this.game.style.translate = ''; this.game.style.transform = '';
            this.game.style.left = nx ? nx.toFixed(4) + 'px' : ''; this.game.style.top = ny ? ny.toFixed(4) + 'px' : '';
        }
        /** Diagnostics (§5.6). */
        info() {
            const dpr = dprNow(), r = this.canvas.getBoundingClientRect(), l = this.layer.getBoundingClientRect();
            return { version: VERSION, origin: [(r.left + (this.canvas.clientLeft || 0)) * dpr, (r.top + (this.canvas.clientTop || 0)) * dpr],
                     backing: [this.canvas.width, this.canvas.height], crtLayer: [this.layer.width, this.layer.height],
                     crtOrigin: [l.left * dpr, l.top * dpr], crtOn: this.on, crtP: this.pd.P, crtD: this.pd.D, crtShape: this.pd.shape,
                     crtMode: this.game.dataset.mode, crtDetail: this.game.dataset.crt, offset: [this.ax, this.ay] };
        }
    }
    return { VERSION, CRT_DETAILS, CRT_SHAPES, CRT_ROW, CRT_SCREEN, CRT_LINE, CRT_RGB, MODE_MS, VIEW_DEFAULTS, WORDS,
             deviceScale, crtParams, drawCrt, filter, crtOn, smoothstep, zoomLabel, quantum, padded, snap, testPattern, Screen };
})();
if (typeof globalThis !== 'undefined') globalThis.WBOBRAZ = WBOBRAZ;
if (typeof module !== 'undefined') module.exports = WBOBRAZ;
