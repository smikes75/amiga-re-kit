// wb-pad.js 1.0 (kit 1.0.89) - gamepads and joysticks for the rebuilds' pages (amiga-re-kit). The games' own pad.js
// (Alien Breed II: two players, Superfrog: a jump button) made general: each player's controller and fire button,
// read once a frame into the page's joystick bits. No game data. Works as a <script> (global WBPAD) and as CommonJS; the
// reading is pure (a fake navigator.getGamepads in Node).
//
//   const pads = WBPAD.create({ players: 2 });            // opt: read = () => navigator.getGamepads(), bits = { right: 1,
//                                                          // left: 2, up: 4, down: 8, fire: 16 } (the page's own order)
//   // once a frame, in the page's loop:  const [p1, p2] = pads.poll();  joy1 |= p1;  ... p2 -> the second player's input
//   pads.set(0, { pad: 'auto' | '0'..'3', fire: 'auto' | '0'..'15', up: 'none' | '0'..'15' })   // from the settings
//   pads.rows({ section: 'controls', players: 2, lang: 'en' | 'cs' }) -> wb-nastaveni 1.4 spec.rows (controller, fire,
//       jump per player; perMode false); pads.fromMenu(menu.get('controls')) applies them
//   pads.status(lang) -> 'Player 1: Xbox Wireless Controller · Player 2: none' ; pads.list() -> connected pads
//
// The reading (as the games had it): a standard mapping - the d-pad (buttons 12-15) and the left stick (axes 0 / 1 past
// 0.4) move, A / B / X / right trigger (0, 1, 2, 7) fire; any other controller - axes 0 / 1, the hat on axis 9 (eight
// directions, -1..1), buttons 0-3 and 7 fire. A chosen fire button fires alone; an 'up' button (Superfrog's jump on A)
// pushes up and no longer fires. 'auto' gives player 1 the first connected pad and player 2 the next one player 1 does
// not use; a chosen pad that is not connected reads 0. A browser shows pads only after a button was pressed on the page.
'use strict';
const WBPAD = (() => {
    const VERSION = '1.0';
    const BITS = { right: 1, left: 2, up: 4, down: 8, fire: 16 };
    const DEAD = .4;
    const pressed = (pad, n) => { const b = pad && pad.buttons && pad.buttons[n]; return typeof b === 'number' ? b > .5 : !!b && (!!b.pressed || b.value > .5); };
    const num = (v) => (typeof v === 'number' || /^\d+$/.test(String(v))) ? +v : null;

    /** One pad's directions and fire: { right, left, up, down, fire } for a fire button / an up button ('auto' / 'none' / n). */
    function state(pad, fire, up) {
        const s = { right: false, left: false, up: false, down: false, fire: false };
        if (!pad) return s;
        const x = (pad.axes && pad.axes[0]) || 0, y = (pad.axes && pad.axes[1]) || 0, std = pad.mapping === 'standard';
        const fi = num(fire), ui = num(up), other = (n) => n !== ui && pressed(pad, n);
        s.up = y < -DEAD || (std && pressed(pad, 12)) || (ui !== null && pressed(pad, ui));
        s.down = y > DEAD || (std && pressed(pad, 13));
        s.left = x < -DEAD || (std && pressed(pad, 14));
        s.right = x > DEAD || (std && pressed(pad, 15));
        s.fire = fi !== null ? pressed(pad, fi) : (std ? [0, 1, 2, 7] : [0, 1, 2, 3, 7]).some(other);
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
              player: 'Player', nopad: 'none', press: 'no controller - connect one and press a button' },
        cs: { pad: 'Ovladač', fire: 'Tlačítko střelby', up: 'Tlačítko skoku (nahoru)', auto: 'Automaticky', none: 'Žádné', slot: 'Ovladač', button: 'Tlačítko',
              player: 'Hráč', nopad: 'žádný', press: 'žádný ovladač - připoj ho a stiskni tlačítko' },
    };

    function create(opt) {
        opt = opt || {};
        const players = Math.max(1, Math.min(4, opt.players || 1));
        const read = opt.read || (() => (typeof navigator !== 'undefined' && navigator.getGamepads && navigator.getGamepads()) || []);
        const bits = Object.assign({}, BITS, opt.bits || {});
        const cfg = Array.from({ length: players }, () => ({ pad: 'auto', fire: 'auto', up: 'none' }));
        let pads = [], used = new Array(players).fill(null);
        const list = () => { try { pads = Array.from(read() || []).filter((p) => p && p.connected !== false); } catch (e) { pads = []; } return pads; };
        /** Which pad each player reads: a chosen index, or 'auto' = the first connected pad no earlier player took. */
        function assign() {
            const taken = new Set();
            for (let i = 0; i < players; i++) {
                const c = cfg[i].pad;
                if (c !== 'auto') { const p = pads.find((q) => String(q.index) === String(c)) || null; used[i] = p; if (p) taken.add(p); }
            }
            for (let i = 0; i < players; i++) {
                if (cfg[i].pad !== 'auto') continue;
                const p = pads.find((q) => !taken.has(q)) || null; used[i] = p; if (p) taken.add(p);
            }
            return used;
        }
        return {
            VERSION, bits,
            /** Once a frame: each player's bits (0 without a controller). */
            poll() { list(); assign(); return used.map((p, i) => toBits(state(p, cfg[i].fire, cfg[i].up), bits)); },
            /** Each player's { right, left, up, down, fire } from the last poll's pads. */
            states() { return used.map((p, i) => state(p, cfg[i].fire, cfg[i].up)); },
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
            /** 'Player 1: <id> · Player 2: none', or the hint when no controller is seen. */
            status(lang) {
                const t = TEXTS[lang] || TEXTS.en;
                if (!pads.length) return t.press;
                return used.map((p, i) => (players > 1 ? t.player + ' ' + (i + 1) + ': ' : '') + (p ? String(p.id).replace(/\s*\(.*$/, '') || t.slot + ' ' + (p.index + 1) : t.nopad)).join(' · ');
            },
        };
    }
    return { VERSION, BITS, state, create, TEXTS };
})();
if (typeof module !== 'undefined' && module.exports) module.exports = WBPAD;
