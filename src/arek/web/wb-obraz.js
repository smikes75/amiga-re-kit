// wb-obraz.js - reference implementation of the display contract "wb-shell obraz 1.5"
// (amiga-re-kit, WB-OBRAZ-CRT.md). Whole device pixels per game row (S), zoom = window width in
// multiples of the Original's width W0, the CRT as a second canvas in device pixels, blur 0.8 game
// pixel at 100 %, the content placed on a whole device pixel by layout (left/top) - never transform.
// 1.4: a pixel aspect ratio `par` (PAL lores 1.04 = 14.75/14.1875, NTSC lores 0.857 = 12.2727/14.31818, 1 = square;
// any value a game or its player picks) is applied INSIDE the
// backing - the picture is W*S*par device pixels wide (contentSize, blit resamples horizontally only), the
// rows stay exact, the CRT layer still equals the backing. Never stretch a canvas by CSS: that breaks §1-§2.
// 1.5: a Presenter owns the visible game canvas - WebGL2 when the browser has it (one canvas, no copy between
// contexts: Safari keeps a 2D canvas the CPU writes to in CPU memory and a drawImage from a WebGL canvas waits for
// the GPU every frame - Alien Breed II, G31) or the 2D path with the same API. present({pixels}) shows a W x H RGBA
// frame, present({draw}) lets the game draw its own layers into the presenter's framebuffer in device pixels
// (W*S x H*S, before the aspect; both together: pixels first, draw on top); the geometry of 1.4 holds on both paths
// and §3 (brightness, contrast, saturation, blur) runs in the shader on the WebGL path. 1.5.1: size() that resizes the
// canvas shows the last picture again at once (a page drawing only on a new game frame blinked at a mode change in Safari).
// No game data. Works as a <script> (global WBOBRAZ, also globalThis.WBOBRAZ - an ES module that imports
// nothing can read it there), as CommonJS (require) and in Node for tests.
// Projects copy this file (`arek web copy DIR`) and keep its sha256 in their docs.
//
// Test hooks a page provides for `arek web test URL` (contract §5):
//   window.wbObrazTest.set(mode, {zoom, crtDetail, crtShape, crt, blur, par}) -> info
//       mode 'original' | 'enhanced'; zoom: window width in multiples of W0, 0 = fit; par: pixel aspect (1.4,
//       default 1); returns {scale: S, W, H, P, D, par, origin: [x, y] device px, backing: [w, h],
//        content: [round(W*S*par), H*S], crtLayer: [w, h], crtOrigin: [x, y], gl: bool (1.5)}   (Screen.info() gives origin/backing/crtLayer/crtOrigin)
//   window.wbObrazTest.fill(kind) -> true      kind 'grey' | 'rows' | 'cols' (testPattern); the pattern must stay
//       on the canvas until the next set() - a running game must not paint over it (pause it, or hold the pattern)
//   window.wbObrazTest.gl() -> bool (1.5)      the WebGL path is on; a page honours ?gl=0 / ?gl=1 so the test runs both
// arek web test needs `pip install amiga-re-kit[web]` and `python -m playwright install chromium`.
'use strict';
const WBOBRAZ = (() => {
    const VERSION = '1.5';
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

    /** S, whole device pixels per game row (§1). zoom = window width in multiples of w0 (0 = fit), w = logical
     *  canvas width, limit = the largest CSS px per game pixel that fits (the page computes it with the aspect:
     *  min(aw / (W * par), ah / H)). Zoom: round(zoom*w0/w*dpr/par), fit: floor(limit*dpr). par (1.4) default 1. */
    function deviceScale(zoom, w0, w, dpr, limit, par) {
        par = par > 0 ? par : 1;
        const floor = Math.max(1, Math.floor(limit * dpr + 1e-6));
        return zoom > 0 ? Math.min(Math.max(1, Math.round(zoom * w0 / w * dpr / par)), floor) : floor;
    }
    /** The game content in device pixels (1.4): [round(W*S*par), H*S] - the aspect stretches the picture horizontally
     *  inside the backing, rows stay S device pixels each. */
    function contentSize(W, H, S, par) {
        par = par > 0 ? par : 1;
        return [Math.round(W * S * par), H * S];
    }
    let blitTmp = null;
    /** Draw the W x H game picture `src` (a canvas, image or bitmap) into the backing `c` as its content (1.4): every
     *  game row exactly S device rows; with par = 1 every column exactly S device columns (no smoothing), otherwise the
     *  columns are resampled horizontally only (a W*S*par x H pass with smoothing, then rows replicated without). */
    function blit(c, src, W, H, S, par) {
        const [w, h] = contentSize(W, H, S, par), g = c.getContext('2d');
        if (w === W * S) { g.imageSmoothingEnabled = false; g.drawImage(src, 0, 0, W, H, 0, 0, w, h); return [w, h]; }
        if (!blitTmp) blitTmp = (typeof OffscreenCanvas !== 'undefined') ? new OffscreenCanvas(w, H) : document.createElement('canvas');
        if (blitTmp.width !== w || blitTmp.height !== H) { blitTmp.width = w; blitTmp.height = H; }
        const t = blitTmp.getContext('2d');
        t.imageSmoothingEnabled = true; t.imageSmoothingQuality = 'high';
        t.drawImage(src, 0, 0, W, H, 0, 0, w, H);                                  // horizontal resample at 1 row per row
        g.imageSmoothingEnabled = false; g.drawImage(blitTmp, 0, 0, w, H, 0, 0, w, h);   // rows replicated S times, exact
        return [w, h];
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
    /** The zoom as the player wished it and as whole device pixels made it ("3x - limited to 2.5x"); par (1.4) default 1. */
    function zoomLabel(wish, S, dpr, w0, w, words, par) {
        par = par > 0 ? par : 1;
        const t = Object.assign({}, WORDS, words || {}), real = S * par / dpr * w / w0;
        const x = (n) => String(+n.toFixed(2)) + '×';
        if (!(wish > 0)) return t.fit + ' (' + x(real) + ')';
        if (Math.abs(real - wish) < .005) return x(wish);
        return x(wish) + ' · ' + (S < Math.round(wish * w0 / w * dpr / par) ? t.limited : t.actual) + ' ' + x(real);
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
    /** Fill the game content (contentSize, top left of the canvas) with a test pattern (§5): 'grey' (#808080,
     *  §5.4), 'rows' - game row y gets the grey 32 + 24 * (y mod 8), so a doubled or missing row shows (§5.4b) -
     *  or 'cols', the same per game column (under an aspect the columns are round(x*S*par) wide, crisp, unequal).
     *  The padding beyond the content stays black. par (1.4) default 1. */
    function testPattern(c, kind, W, H, S, par) {
        const [w, h] = contentSize(W, H, S, par), g = c.getContext('2d');
        g.fillStyle = '#000'; g.fillRect(0, 0, c.width, c.height);
        if (kind === 'grey') { g.fillStyle = '#808080'; g.fillRect(0, 0, w, h); return; }
        if (kind === 'cols') {
            for (let x = 0; x < W; x++) {
                const v = 32 + 24 * (x % 8), x0 = Math.round(x * w / W), x1 = Math.round((x + 1) * w / W);
                g.fillStyle = 'rgb(' + v + ',' + v + ',' + v + ')';
                g.fillRect(x0, 0, x1 - x0, h);
            }
            return;
        }
        for (let y = 0; y < H; y++) {
            const v = 32 + 24 * (y % 8);
            g.fillStyle = 'rgb(' + v + ',' + v + ',' + v + ')';
            g.fillRect(0, y * S, w, S);
        }
    }

    /** A W x H RGBA test pattern as pixels (1.5): 'grey' #808080, 'rows' 32 + 24 * (y mod 8), 'cols' the same per column. */
    function patternPixels(kind, W, H) {
        const p = new Uint8ClampedArray(W * H * 4);
        for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
            const v = kind === 'grey' ? 0x80 : 32 + 24 * ((kind === 'cols' ? x : y) % 8), i = (y * W + x) * 4;
            p[i] = p[i + 1] = p[i + 2] = v; p[i + 3] = 255;
        }
        return p;
    }
    // the WebGL path's shaders (1.5): a full-screen triangle; SCALE puts the W x H frame into the framebuffer with every
    // game pixel exactly S x S device pixels (the frame's row 0 is the top, the framebuffer's row 0 the bottom, as GL has
    // it); BLUR_H a horizontal gaussian; FINAL samples the framebuffer for the canvas: exact rows, the columns resampled
    // by the aspect (linear between device columns; 1:1 texel fetch at par 1), the vertical blur and §3 as CSS defines
    // them (brightness, contrast, saturate), the padding beyond the content black.
    const GLSL = {
        vs: '#version 300 es\nvoid main() { vec2 p = vec2((gl_VertexID & 1) * 4 - 1, (gl_VertexID & 2) * 2 - 1); gl_Position = vec4(p, 0.0, 1.0); }',
        scale: '#version 300 es\nprecision highp float; uniform sampler2D tex; uniform ivec3 geo; out vec4 o;\n' +
               'void main() { ivec2 d = ivec2(gl_FragCoord.xy); ivec2 g = ivec2(d.x / geo.z, geo.y - 1 - d.y / geo.z);\n' +
               '  o = vec4(texelFetch(tex, g, 0).rgb, 1.0); }',
        blurh: '#version 300 es\nprecision highp float; uniform sampler2D tex; uniform float sigma; uniform vec2 size; out vec4 o;\n' +
               'void main() { int r = int(ceil(3.0 * sigma)); vec3 acc = vec3(0.0); float wsum = 0.0;\n' +
               '  for (int k = -r; k <= r; k++) { float w = exp(-float(k * k) / (2.0 * sigma * sigma));\n' +
               '    acc += w * texture(tex, (gl_FragCoord.xy + vec2(float(k), 0.0)) / size).rgb; wsum += w; }\n' +
               '  o = vec4(acc / wsum, 1.0); }',
        final: '#version 300 es\nprecision highp float; uniform sampler2D tex; uniform vec2 size; uniform vec2 content; uniform float pad;\n' +
               'uniform float par; uniform float sigma; uniform vec4 look; out vec4 o;\n' +
               'vec3 fetch(float x, float y) { vec2 uv = vec2((x + 0.5) / par, floor(y) + 0.5) / size;\n' +
               '  return (par == 1.0 ? texelFetch(tex, ivec2(int(x), int(y)), 0) : texture(tex, uv)).rgb; }\n' +
               'void main() { float x = floor(gl_FragCoord.x), y = floor(gl_FragCoord.y) - pad;\n' +
               '  if (x >= content.x || y < 0.0) { o = vec4(0.0, 0.0, 0.0, 1.0); return; }\n' +
               '  vec3 c;\n' +
               '  if (sigma > 0.0) { int r = int(ceil(3.0 * sigma)); vec3 acc = vec3(0.0); float wsum = 0.0;\n' +
               '    for (int k = -r; k <= r; k++) { float yy = y + float(k); if (yy < 0.0 || yy >= content.y) continue;\n' +
               '      float w = exp(-float(k * k) / (2.0 * sigma * sigma)); acc += w * fetch(x, yy); wsum += w; }\n' +
               '    c = acc / wsum; } else c = fetch(x, y);\n' +
               '  c = c * look.x; c = (c - 0.5) * look.y + 0.5;\n' +
               '  float l = dot(c, vec3(0.2126, 0.7152, 0.0722)); c = mix(vec3(l), c, look.z);\n' +
               '  o = vec4(clamp(c, 0.0, 1.0), 1.0); }',
    };
    const isShared = (v) => typeof SharedArrayBuffer !== 'undefined' && v && v.buffer instanceof SharedArrayBuffer;

    /** The visible game canvas (1.5): the WebGL2 path when the browser has it and opts.gl is not 'off' ('on' insists:
     *  no fallback), otherwise the 2D path - the same API, so a page is written once; .gl is true on the WebGL path. Methods:
     *    size(W, H, S, par, dpr) -> { backing, content, redrawn }   allocates the backing (padded, §1.4), the framebuffer
     *        and the textures in one call (W, H may change every frame, e.g. during the mode transition), sets the CSS size;
     *        1.5.1: a resized canvas shows the last picture again at once (redrawn) - from the last frame when W x H is
     *        the same, from the framebuffer when W*S x H*S is; otherwise (redrawn false) present() in the same frame
     *    look({ brightness, contrast, saturation, blur })   §3; the WebGL path in the shader, the 2D path as CSS filter
     *    present({ pixels | source, draw }) -> bool          pixels: W x H RGBA (Uint8Array / Uint8ClampedArray /
     *        ImageData; a view over a SharedArrayBuffer is copied), source: a canvas / image / bitmap; draw(gl, fbo,
     *        { w: W*S, h: H*S }): the game draws into the presenter's framebuffer in device pixels before the aspect,
     *        row 0 at the bottom (GL); the presenter restores its own state afterwards. On the 2D path draw is not
     *        possible: present returns false and the game sends pixels (check .gl first).
     *    fill(kind) -> true                                  the test pattern (§5) through the same path
     *    info() -> { gl, content, backing } */
    class Presenter {
        constructor(canvas, opts) {
            opts = opts || {};
            this.canvas = canvas; this.W = 0; this.H = 0; this.S = 1; this.par = 1; this.dpr = 1;
            this.content = [0, 0]; this.backing = [0, 0]; this.lookv = { brightness: 100, contrast: 100, saturation: 100, blur: 0 };
            const want = opts.gl || 'auto';
            this.g = null; this.gl = false;
            if (want !== 'off' && canvas.getContext) {
                const gl = canvas.getContext('webgl2', { alpha: false, antialias: false, depth: false, stencil: false, premultipliedAlpha: false, preserveDrawingBuffer: !!opts.preserve });
                if (gl) { this._glInit(gl); this.gl = true; }
                else if (want === 'on') throw new Error('wb-obraz: no WebGL2');
            }
            if (!this.g) { this.ctx = canvas.getContext('2d'); this.frame = null; }
        }
        _program(gl, fs) {
            const mk = (type, src) => { const sh = gl.createShader(type); gl.shaderSource(sh, src); gl.compileShader(sh);
                if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) throw new Error('wb-obraz shader: ' + gl.getShaderInfoLog(sh)); return sh; };
            const pr = gl.createProgram(); gl.attachShader(pr, mk(gl.VERTEX_SHADER, GLSL.vs)); gl.attachShader(pr, mk(gl.FRAGMENT_SHADER, fs)); gl.linkProgram(pr);
            if (!gl.getProgramParameter(pr, gl.LINK_STATUS)) throw new Error('wb-obraz program: ' + gl.getProgramInfoLog(pr));
            return pr;
        }
        _tex(gl) {
            const t = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, t);
            gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
            gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
            return t;
        }
        _glInit(gl) {
            this.g = gl;
            this.vao = gl.createVertexArray();
            this.pScale = this._program(gl, GLSL.scale); this.pBlur = this._program(gl, GLSL.blurh); this.pFinal = this._program(gl, GLSL.final);
            this.tFrame = this._tex(gl); this.tFbo = this._tex(gl); this.tBlur = this._tex(gl);
            this.fbo = gl.createFramebuffer(); this.fboBlur = gl.createFramebuffer();
            this.u = {};
            for (const [name, pr] of [['scale', this.pScale], ['blur', this.pBlur], ['final', this.pFinal]]) {
                this.u[name] = {};
                for (const n of ['tex', 'geo', 'sigma', 'size', 'content', 'pad', 'par', 'look']) this.u[name][n] = gl.getUniformLocation(pr, n);
            }
            this.fboSize = [0, 0]; this.frameSize = [0, 0]; this.copy = null;
            gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false); gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false); gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
        }
        size(W, H, S, par, dpr) {
            par = par > 0 ? par : 1; dpr = dpr || dprNow();
            this.W = W; this.H = H; this.S = S; this.par = par; this.dpr = dpr;
            const [cw, ch] = contentSize(W, H, S, par), bw = padded(cw, dpr), bh = padded(ch, dpr);
            this.content = [cw, ch]; this.backing = [bw, bh];
            const c = this.canvas, resized = c.width !== bw || c.height !== bh;
            if (resized) { c.width = bw; c.height = bh; }                          // clears the canvas (both paths)
            if (c.style) { c.style.width = bw / dpr + 'px'; c.style.height = bh / dpr + 'px'; }
            const gl = this.g;
            let fboChanged = false, frameChanged = false;
            if (gl) {
                const fw = W * S, fh = H * S;
                if (this.fboSize[0] !== fw || this.fboSize[1] !== fh) {
                    fboChanged = true;
                    this.fboSize = [fw, fh];
                    for (const [t, f] of [[this.tFbo, this.fbo], [this.tBlur, this.fboBlur]]) {
                        gl.bindTexture(gl.TEXTURE_2D, t); gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, fw, fh, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
                        gl.bindFramebuffer(gl.FRAMEBUFFER, f); gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, t, 0);
                    }
                    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
                }
                if (this.frameSize[0] !== W || this.frameSize[1] !== H) {
                    frameChanged = true; this.frameSize = [W, H];
                    gl.bindTexture(gl.TEXTURE_2D, this.tFrame); gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, W, H, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
                }
            } else this.look(this.lookv);
            // 1.5.1: a resized canvas is blank until the next present - a page that draws only on a new game frame (the
            // Original mode) showed one empty frame at a mode change in Safari. The presenter shows the last picture again
            // at once: the last frame from its texture (pixels / source, same W x H), else the framebuffer (a draw()
            // content, same W*S x H*S); when neither survives the page must present() in the same display frame.
            let redrawn = false;
            if ((resized || fboChanged) && this.last) {
                if (!gl) { if (this.last.src && this.last.W === W && this.last.H === H) { this._blit2d(this.last.src); redrawn = true; } }
                else if (this.last.kind === 'frame' && !frameChanged) { this._scale(); this._finish(); redrawn = true; }
                else if (!fboChanged) { this._finish(); redrawn = true; }
                if (!redrawn) this.last = null;
            }
            return { backing: this.backing, content: this.content, redrawn };
        }
        _blit2d(src) {
            const g = this.ctx, [bw, bh] = this.backing;
            g.fillStyle = '#000'; g.fillRect(0, 0, bw, bh);
            blit(this.canvas, src, this.W, this.H, this.S, this.par);
        }
        _scale() {
            const gl = this.g, [fw, fh] = this.fboSize;
            this._pass(this.pScale, this.fbo, fw, fh, this.tFrame);
            gl.uniform1i(this.u.scale.tex, 0); gl.uniform3i(this.u.scale.geo, this.W, this.H, this.S);
            gl.drawArrays(gl.TRIANGLES, 0, 3);
        }
        _finish() {
            const gl = this.g, S = this.S, [fw, fh] = this.fboSize, [cw, ch] = this.content, [bw, bh] = this.backing;
            const l = this.lookv, k = (v) => (typeof v === 'number' ? v : 100) / 100, sigma = l.blur > .05 ? l.blur / 100 * 0.8 * S : 0;
            let tex = this.tFbo;
            if (sigma > 0) {                                                             // the horizontal half of the blur
                this._pass(this.pBlur, this.fboBlur, fw, fh, this.tFbo);
                gl.uniform1i(this.u.blur.tex, 0); gl.uniform1f(this.u.blur.sigma, sigma); gl.uniform2f(this.u.blur.size, fw, fh);
                gl.drawArrays(gl.TRIANGLES, 0, 3); tex = this.tBlur;
            }
            this._pass(this.pFinal, null, bw, bh, tex);
            gl.uniform1i(this.u.final.tex, 0); gl.uniform2f(this.u.final.size, fw, fh); gl.uniform2f(this.u.final.content, cw, ch);
            gl.uniform1f(this.u.final.pad, bh - ch); gl.uniform1f(this.u.final.par, this.par); gl.uniform1f(this.u.final.sigma, sigma);
            gl.uniform4f(this.u.final.look, k(l.brightness), k(l.contrast), k(l.saturation), 0);
            gl.drawArrays(gl.TRIANGLES, 0, 3);
        }
        look(v) {
            this.lookv = Object.assign({}, this.lookv, v || {});
            if (!this.g && this.canvas.style) this.canvas.style.filter = filter(this.lookv, this.S / this.dpr);
            return this.lookv;
        }
        _upload(content) {
            const gl = this.g, W = this.W, H = this.H;
            gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, this.tFrame);
            if (content.pixels) {
                let p = content.pixels.data || content.pixels;                             // ImageData or a view
                if (isShared(p)) { if (!this.copy || this.copy.length !== p.length) this.copy = new Uint8Array(p.length); this.copy.set(p); p = this.copy; }
                if (!(p instanceof Uint8Array)) p = new Uint8Array(p.buffer, p.byteOffset, p.byteLength);
                gl.texSubImage2D(gl.TEXTURE_2D, 0, 0, 0, W, H, gl.RGBA, gl.UNSIGNED_BYTE, p);
            } else gl.texSubImage2D(gl.TEXTURE_2D, 0, 0, 0, gl.RGBA, gl.UNSIGNED_BYTE, content.source);
        }
        _pass(pr, fb, w, h, tex) {
            const gl = this.g;
            gl.bindFramebuffer(gl.FRAMEBUFFER, fb); gl.viewport(0, 0, w, h); gl.disable(gl.BLEND); gl.disable(gl.SCISSOR_TEST);
            gl.disable(gl.DEPTH_TEST); gl.disable(gl.CULL_FACE); gl.colorMask(true, true, true, true);
            gl.useProgram(pr); gl.bindVertexArray(this.vao); gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, tex);
        }
        present(content) {
            content = content || {};
            const W = this.W, H = this.H, S = this.S;
            if (!W || !H) return false;
            if (!this.g) {
                if (content.draw && !content.pixels && !content.source) return false;
                const g = this.ctx, [bw, bh] = this.backing;
                let src = content.source;
                if (content.pixels) {
                    if (!this.frame) this.frame = document.createElement('canvas');
                    if (this.frame.width !== W || this.frame.height !== H) { this.frame.width = W; this.frame.height = H; }
                    const p = content.pixels.data || content.pixels;
                    const img = content.pixels.data ? content.pixels : new ImageData(new Uint8ClampedArray(p.buffer, p.byteOffset, W * H * 4), W, H);
                    this.frame.getContext('2d').putImageData(img, 0, 0); src = this.frame;
                }
                if (src) { this._blit2d(src); this.last = content.draw ? null : { src, W, H }; }
                else { g.fillStyle = '#000'; g.fillRect(0, 0, bw, bh); this.last = null; }
                return !content.draw;
            }
            const gl = this.g, [fw, fh] = this.fboSize;
            if (content.pixels || content.source) { this._upload(content); this._scale(); }
            else { gl.bindFramebuffer(gl.FRAMEBUFFER, this.fbo); gl.viewport(0, 0, fw, fh); gl.clearColor(0, 0, 0, 1); gl.clear(gl.COLOR_BUFFER_BIT); }
            if (content.draw) { gl.bindFramebuffer(gl.FRAMEBUFFER, this.fbo); gl.viewport(0, 0, fw, fh); content.draw(gl, this.fbo, { w: fw, h: fh }); }
            this._finish();
            this.last = { kind: (content.pixels || content.source) && !content.draw ? 'frame' : 'fbo' };
            return true;
        }
        fill(kind) {
            if (!this.g) { testPattern(this.canvas, kind, this.W, this.H, this.S, this.par); this.last = null; return true; }
            return this.present({ pixels: patternPixels(kind, this.W, this.H) });
        }
        info() { return { gl: this.gl, content: this.content, backing: this.backing }; }
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
             deviceScale, contentSize, blit, crtParams, drawCrt, filter, crtOn, smoothstep, zoomLabel, quantum, padded, snap,
             testPattern, patternPixels, GLSL, Presenter, Screen };
})();
if (typeof globalThis !== 'undefined') globalThis.WBOBRAZ = WBOBRAZ;
if (typeof module !== 'undefined') module.exports = WBOBRAZ;
