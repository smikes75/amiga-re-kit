// wb-pad.js 1.1 (kit 1.0.90) - gamepads and joysticks for the rebuilds' pages (amiga-re-kit). The games' own pad.js
// (Alien Breed II: two players, Superfrog: a jump button) made general: each player's controller and fire button,
// read once a frame into the page's joystick bits. No game data. Works as a <script> (global WBPAD) and as CommonJS; the
// reading is pure (a fake navigator.getGamepads in Node).
//
//   const pads = WBPAD.create({ players: 2 });            // opt: read = () => navigator.getGamepads(), bits = { right: 1,
//                                                          // left: 2, up: 4, down: 8, fire: 16 } (the page's own order),
//                                                          // reserve = [1] (buttons the page reads itself: no auto fire)
//   // once a frame, in the page's loop:  const [p1, p2] = pads.poll();  joy1 |= p1;  ... p2 -> the second player's input
//   pads.button(0, 1) -> player 1's button B held (Turrican: B = Space); false for the player's chosen fire button
//   pads.set(0, { pad: 'auto' | '0'..'3', fire: 'auto' | '0'..'15', up: 'none' | '0'..'15' })   // from the settings
//   pads.rows({ section: 'controls', players: 2, lang: 'en' | 'cs' }) -> wb-nastaveni 1.4 spec.rows (controller, fire,
//       jump per player; perMode false); pads.fromMenu(menu.get('controls')) applies them
//   pads.status(lang) -> 'Player 1: Xbox Wireless Controller (Controller 2) · Player 2: none · not used: USB Receiver
//       (Controller 1)' - reads the controllers itself; pads.list() -> connected pads
//
// The reading (as the games had it): a standard mapping - the d-pad (buttons 12-15) and the left stick (axes 0 / 1 past
// 0.4) move, A / B / X / right trigger (0, 1, 2, 7) fire; any other controller - axes 0 / 1, the hat on axis 9 (eight
// directions, -1..1), buttons 0-3 and 7 fire. A chosen fire button fires and does nothing else; an 'up' button
// (Superfrog's jump on A) pushes up and no longer fires. A browser shows pads only after a button was pressed on the page.
//
// 1.1 (kit 1.0.90, the user 2026-11-18: "the automatic detection does not work well"): 'auto' no longer takes the first
// device the browser lists - that is often not the controller (a receiver, a headset, a virtual device) or the same
// controller listed twice. 'auto' now gives player 1 the device that was used first (a button, the stick or the hat off
// where it rests - centred on a standard mapping, as first seen on any other device), player 2 the next one used - a device nobody used is never given (a receiver resting with an
// axis at -1 would hold a direction); the controller is taken in the poll it is first used, so nothing is lost.
// Devices first used in the same poll may be one controller listed twice: auto gives no player the twin of another
// player's device until the two have differed (used or not, the directions) for 10 polls in a row. status() reads the devices itself and names the
// slot (as in the menu) and the devices nobody uses. reserve + button() for a page's own buttons.
'use strict';
const WBPAD = (() => {
    const VERSION = '1.1';
    const BITS = { right: 1, left: 2, up: 4, down: 8, fire: 16 };
    const DEAD = .4, MOVED = .5, APART = 10;
    const pressed = (pad, n) => { const b = pad && pad.buttons && pad.buttons[n]; return typeof b === 'number' ? b > .5 : !!b && (!!b.pressed || b.value > .5); };
    const num = (v) => (typeof v === 'number' || /^\d+$/.test(String(v))) ? +v : null;
    const axis = (pad, n) => { const v = pad && pad.axes && pad.axes[n]; return Number.isFinite(v) ? v : 0; };
    const hatOf = (pad) => { const v = pad && pad.axes && pad.axes[9]; return Number.isFinite(v) ? v : 9; };   // 9 = no hat (out of range like centred)

    /** One pad's directions and fire: { right, left, up, down, fire } for a fire button / an up button ('auto' / 'none' / n),
     *  and the buttons the page reads itself (reserve: no auto fire). */
    function state(pad, fire, up, reserve) {
        const s = { right: false, left: false, up: false, down: false, fire: false };
        if (!pad) return s;
        const x = axis(pad, 0), y = axis(pad, 1), std = pad.mapping === 'standard';
        const fi = num(fire), ui = num(up), own = (n) => n !== fi && pressed(pad, n);
        const keep = new Set((reserve || []).map(Number).concat(ui !== null ? [ui] : []));
        s.up = y < -DEAD || (std && own(12)) || (ui !== null && own(ui));
        s.down = y > DEAD || (std && own(13));
        s.left = x < -DEAD || (std && own(14));
        s.right = x > DEAD || (std && own(15));
        s.fire = fi !== null ? pressed(pad, fi) : (std ? [0, 1, 2, 7] : [0, 1, 2, 3, 7]).some((n) => !keep.has(n) && pressed(pad, n));
        const hat = std ? undefined : pad.axes && pad.axes[9];
        if (Number.isFinite(hat) && hat >= -1 && hat <= 1) {
            const h = Math.round((hat + 1) * 3.5);
            s.up = s.up || [0, 1, 7].includes(h); s.right = s.right || [1, 2, 3].includes(h);
            s.down = s.down || [3, 4, 5].includes(h); s.left = s.left || [5, 6, 7].includes(h);
        }
        return s;
    }
    const toBits = (s, b) => (s.right ? b.right : 0) | (s.left ? b.left : 0) | (s.up ? b.up : 0) | (s.down ? b.down : 0) | (s.fire ? b.fire : 0);

    const TEXTS = {
        en: { pad: 'Controller', fire: 'Fire button', up: 'Jump (up) button', auto: 'Automatic', none: 'None', slot: 'Controller', button: 'Button',
              player: 'Player', nopad: 'none', unused: 'not used', press: 'no controller - connect one and press a button',
              hint: 'press a button on the controller', found: 'found' },
        cs: { pad: 'Ovladač', fire: 'Tlačítko střelby', up: 'Tlačítko skoku (nahoru)', auto: 'Automaticky', none: 'Žádné', slot: 'Ovladač', button: 'Tlačítko',
              player: 'Hráč', nopad: 'žádný', unused: 'nepoužitý', press: 'žádný ovladač - připoj ho a stiskni tlačítko',
              hint: 'stiskni tlačítko na ovladači', found: 'nalezeno' },
    };

    function create(opt) {
        opt = opt || {};
        const players = Math.max(1, Math.min(4, opt.players || 1));
        const read = opt.read || (() => (typeof navigator !== 'undefined' && navigator.getGamepads && navigator.getGamepads()) || []);
        const bits = Object.assign({}, BITS, opt.bits || {}), reserve = (opt.reserve || []).map(Number);
        const cfg = Array.from({ length: players }, () => ({ pad: 'auto', fire: 'auto', up: 'none' }));
        let pads = [], used = new Array(players).fill(null), tick = 0;
        const seen = new Map();   // pad index -> { id, rest: [x, y, hat], at: the poll it was first used (0 = not yet), on, sig, calm, twins: index -> polls apart }
        const list = () => { try { pads = Array.from(read() || []).filter((p) => p && p.connected !== false); } catch (e) { pads = []; } return pads; };
        /** Which devices were used, and when first: a button, the stick or the hat moved from where they rested. */
        function observe() {
            tick++;
            const first = [], here = new Set();
            for (const p of pads) {
                let r = seen.get(p.index);
                if (!r || r.id !== p.id) {   // where it rests: a standard mapping rests centred; a hat in range is pressed (centred = 3.29)
                    const h = hatOf(p), hr = h >= -1 && h <= 1 ? 3.2857 : h;
                    r = { id: p.id, rest: p.mapping === 'standard' ? [0, 0, hr] : [axis(p, 0), axis(p, 1), hr], at: 0, on: false, twins: new Map() };
                    seen.set(p.index, r);
                }
                here.add(p.index);
                r.on = (p.buttons || []).some((_, n) => pressed(p, n)) || Math.abs(axis(p, 0) - r.rest[0]) > MOVED || Math.abs(axis(p, 1) - r.rest[1]) > MOVED
                    || Math.abs(hatOf(p) - r.rest[2]) > .1;
                r.sig = (r.on ? 32 : 0) | (toBits(state(p), BITS) & 15);   // used + directions: one device listed twice gives the same
                if (r.calm === undefined) r.calm = !(r.sig & 15) && !r.on;   // quiet when first seen (not an axis resting at -1)
                if (!r.at && r.on) { r.at = tick; first.push(p.index); }
            }
            for (const k of [...seen.keys()]) if (!here.has(k)) { seen.delete(k); for (const r of seen.values()) r.twins.delete(k); }
            for (const a of first) for (const b of first) if (a !== b) seen.get(a).twins.set(b, 0);   // first used in the same poll: maybe one device twice
            for (const [k, r] of seen) for (const [t, n] of r.twins) {
                const o = seen.get(t), m = r.sig !== o.sig ? n + 1 : 0;
                if (m >= APART) { r.twins.delete(t); o.twins.delete(k); } else r.twins.set(t, m);
            }
        }
        const order = (p) => { const r = seen.get(p.index) || {}; return [r.at ? 0 : 1, r.at || 0, p.mapping === 'standard' ? 0 : 1, r.calm ? 0 : 1, p.index]; };
        const before = (a, b) => { const x = order(a), y = order(b); for (let i = 0; i < x.length; i++) if (x[i] !== y[i]) return x[i] - y[i]; return 0; };
        /** Which pad each player reads: a chosen index, or 'auto' = the first used device no earlier player took (nor its twin);
         *  among devices first used in the same poll a standard-mapped one, then one quiet when first seen. */
        function assign() {
            const taken = new Set(), twin = (p) => [...taken].some((t) => seen.has(t) && seen.get(t).twins.has(p.index));
            const take = (i, p) => { used[i] = p || null; if (p) taken.add(p.index); };
            for (let i = 0; i < players; i++) if (cfg[i].pad !== 'auto') take(i, pads.find((q) => String(q.index) === String(cfg[i].pad)));
            const free = pads.slice().sort(before);
            for (let i = 0; i < players; i++) if (cfg[i].pad === 'auto') take(i, free.find((q) => (seen.get(q.index) || {}).at && !taken.has(q.index) && !twin(q)));
            return used;
        }
        const refresh = () => { list(); observe(); assign(); };
        return {
            VERSION, bits,
            /** Once a frame: each player's bits (0 without a controller). */
            poll() { refresh(); return used.map((p, i) => toBits(state(p, cfg[i].fire, cfg[i].up, reserve), bits)); },
            /** Each player's { right, left, up, down, fire } from the last poll's pads. */
            states() { return used.map((p, i) => state(p, cfg[i].fire, cfg[i].up, reserve)); },
            /** Player i's button n held (a page's own button, e.g. reserve [1] and B = Space); false for the chosen fire button. */
            button(i, n) { const p = used[i]; return !!p && !!cfg[i] && num(cfg[i].fire) !== +n && pressed(p, +n); },
            set(i, c) { if (cfg[i]) for (const k of ['pad', 'fire', 'up']) if (c && c[k] !== undefined) cfg[i][k] = String(c[k]); return cfg[i]; },
            config: () => cfg.map((c) => Object.assign({}, c)),
            list: () => list().map((p) => ({ index: p.index, id: p.id, mapping: p.mapping, buttons: (p.buttons || []).length })),
            /** wb-nastaveni 1.4 rows: per player a controller (auto, slots 1-4), a fire button and an up button (auto / 1-16). */
            rows(o) {
                o = o || {}; const t = TEXTS[o.lang] || TEXTS.en, section = o.section || 'controls', n = Math.max(1, Math.min(players, o.players || players));
                const buttons = Array.from({ length: 16 }, (_, k) => String(k)), out = [];
                for (let i = 0; i < n; i++) {
                    const pre = n > 1 ? t.player + ' ' + (i + 1) + ': ' : '', id = 'pad' + (i + 1);
                    const bl = Object.fromEntries(buttons.map((b) => [b, t.button + ' ' + (+b + 1)]));
                    out.push({ id: id, section, kind: 'select', perMode: false, label: pre + t.pad, options: ['auto', '0', '1', '2', '3'], def: 'auto',
                               labels: { auto: t.auto, 0: t.slot + ' 1', 1: t.slot + ' 2', 2: t.slot + ' 3', 3: t.slot + ' 4' } });
                    out.push({ id: id + '-fire', section, kind: 'select', perMode: false, label: pre + t.fire, options: ['auto'].concat(buttons), def: 'auto',
                               labels: Object.assign({ auto: t.auto }, bl) });
                    if (o.up) out.push({ id: id + '-up', section, kind: 'select', perMode: false, label: pre + t.up, options: ['none'].concat(buttons), def: o.up === true ? 'none' : String(o.up),
                                         labels: Object.assign({ none: t.none }, bl) });
                }
                return out;
            },
            /** Applies the rows' values (menu.get(section)). */
            fromMenu(v) { if (!v) return; for (let i = 0; i < players; i++) { const id = 'pad' + (i + 1); this.set(i, { pad: v[id], fire: v[id + '-fire'], up: v[id + '-up'] }); } },
            /** 'Player 1: <name> (Controller 2) · Player 2: none · not used: <name> (Controller 1)'; 'press a button on the
             *  controller · found: ...' while no player has one; the hint when no controller is seen. Reads them itself. */
            status(lang) {
                const t = TEXTS[lang] || TEXTS.en;
                refresh();
                if (!pads.length) return t.press;
                const name = (p) => (String(p.id).replace(/\s*\(.*$/, '') || t.slot) + ' (' + t.slot + ' ' + (p.index + 1) + ')';
                const out = used.map((p, i) => (players > 1 ? t.player + ' ' + (i + 1) + ': ' : '') + (p ? name(p) : t.nopad));
                if (used.every((p) => !p)) return t.hint + ' · ' + t.found + ': ' + pads.map(name).join(', ');
                const rest = pads.filter((p) => !used.includes(p));
                if (rest.length) out.push(t.unused + ': ' + rest.map(name).join(', '));
                return out.join(' · ');
            },
        };
    }
    return { VERSION, BITS, state, create, TEXTS };
})();
if (typeof module !== 'undefined' && module.exports) module.exports = WBPAD;
