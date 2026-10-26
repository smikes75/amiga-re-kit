// wb-nastaveni.js - the shared Display / Sound menu of the rebuilds (amiga-re-kit, MENU-ZVUK.md, 1.0). One module builds
// the common controls with the same ids, ranges, defaults and storage in every game; the game adds its own items in
// the `extras` slots and supplies texts (English and Czech are built in) and the defaults it wants per mode.
// No game data, no CSS beyond the wb-menu* classes (the game styles it). Works as a <script> (global WBNASTAVENI) and as
// CommonJS; the pure parts (ITEMS, defaults, coerce, merge) run in Node, build() needs a document.
//
//   const menu = WBNASTAVENI.build(host, { store: 'mygame-wb-menu-v1', lang: 'cs',
//                                     defaults: { display: { original: { par: 1 }, enhanced: { par: 1.04 } }, sound: { enhanced: { stereo: 70 } } },
//                                     texts: { display: { blur: 'Rozmazání' } } });
//   menu.on('change', (state) => applyToGame(state));          // state = menu.get(): { mode, display: {...}, sound: {...} }
//   menu.setMode('enhanced'); menu.get('display').par; menu.set('sound', 'stereo', 50); menu.reset('sound');
//   menu.extras.display / menu.extras.sound: elements the game fills with its own rows
//   spec.zoom = 'snap' with spec.zoomSteps = () => [{value, label}, ...]: the zoom becomes a slider over the zooms this
//   display can show exactly (whole device pixels per game pixel - the page lists them with WBOBRAZ.deviceScale), the
//   wished value snaps to the nearest step; `menu.refreshZoom()` after a resize or a dpr change.
//
// The file is wb-nastaveni.js (not wb-menu.js: that name is the games' own Workbench bar). Every value is kept per mode (original / enhanced). Test hooks (arek web test §6): window.wbMenuTest = menu.testHooks().
'use strict';
const WBNASTAVENI = (() => {
    const VERSION = '1.1';
    const MODES = ['original', 'enhanced'];
    const ITEMS = {
        display: [
            { id: 'zoom', kind: 'select', options: [1, 1.5, 2, 2.5, 3, 4, 6, 0], def: { original: 2, enhanced: 3 } },
            { id: 'crt', kind: 'check', def: true },
            { id: 'crt-detail', kind: 'select', options: ['fine', 'standard', 'strong'], def: { original: 'strong', enhanced: 'fine' } },
            { id: 'crt-shape', kind: 'select', options: ['lines', 'grid'], def: 'lines' },
            { id: 'blur', kind: 'range', min: 0, max: 100, step: 1, def: { original: 0, enhanced: 20 } },
            { id: 'brightness', kind: 'range', min: 50, max: 150, step: 1, def: 100 },
            { id: 'contrast', kind: 'range', min: 50, max: 150, step: 1, def: 100 },
            { id: 'saturation', kind: 'range', min: 0, max: 200, step: 1, def: 100 },
            { id: 'red', kind: 'range', min: 50, max: 150, step: 1, def: 100 },
            { id: 'green', kind: 'range', min: 50, max: 150, step: 1, def: 100 },
            { id: 'blue', kind: 'range', min: 50, max: 150, step: 1, def: 100 },
            { id: 'par', kind: 'range', min: 1, max: 1.1, step: 0.01, def: { original: 1, enhanced: 1.04 } },
            { id: 'smooth', kind: 'check', def: { original: false, enhanced: true } },
        ],
        sound: [
            { id: 'sound', kind: 'check', def: true },
            { id: 'volume', kind: 'range', min: 0, max: 100, step: 1, def: 80 },
            { id: 'filter-fixed', kind: 'check', def: true },
            { id: 'filter-led', kind: 'select', options: ['auto', 'on', 'off'], def: 'auto' },
            { id: 'filter-hp', kind: 'check', def: true },
            { id: 'stereo', kind: 'range', min: 0, max: 100, step: 1, def: { original: 100, enhanced: 70 } },
        ],
    };
    const TEXTS = {
        en: { display: { _: 'Display', zoom: 'Zoom', crt: 'CRT', 'crt-detail': 'CRT detail', 'crt-shape': 'CRT shape', blur: 'Blur', brightness: 'Brightness',
                         contrast: 'Contrast', saturation: 'Saturation', red: 'Red', green: 'Green', blue: 'Blue', par: 'Pixel width', smooth: 'Smooth motion', defaults: 'Default picture for this mode',
                         fit: 'fit', fine: 'fine', standard: 'standard', strong: 'strong', lines: 'lines', grid: 'grid' },
              sound: { _: 'Sound', sound: 'Sound', volume: 'Volume', 'filter-fixed': 'Amiga 500 filter', 'filter-led': 'LED filter', 'filter-hp': 'High-pass',
                       stereo: 'Stereo width', defaults: 'Default sound for this mode', auto: 'as the game', on: 'on', off: 'off' },
              modes: { original: 'Original', enhanced: 'Enhanced' } },
        cs: { display: { _: 'Obraz', zoom: 'Zvětšení', crt: 'CRT', 'crt-detail': 'Stupeň CRT', 'crt-shape': 'Tvar CRT', blur: 'Rozmazání', brightness: 'Jas',
                         contrast: 'Kontrast', saturation: 'Sytost', red: 'Červená', green: 'Zelená', blue: 'Modrá', par: 'Šířka bodu', smooth: 'Plynulé zobrazení', defaults: 'Výchozí obraz tohoto režimu',
                         fit: 'do okna', fine: 'jemný', standard: 'střední', strong: 'silný', lines: 'řádky', grid: 'mřížka' },
              sound: { _: 'Zvuk', sound: 'Zvuk', volume: 'Hlasitost', 'filter-fixed': 'Filtr Amigy 500', 'filter-led': 'Filtr LED', 'filter-hp': 'Horní propust',
                       stereo: 'Šířka sterea', defaults: 'Výchozí zvuk tohoto režimu', auto: 'podle hry', on: 'zapnuto', off: 'vypnuto' },
              modes: { original: 'Originál', enhanced: 'Vylepšeno' } },
    };

    /** The default of an item for a mode: the game's override (spec.defaults[section][mode][id]) wins. */
    function defaults(section, mode, over, snap) {
        const out = {}, o = (over && over[section] && over[section][mode]) || {};
        for (const it of ITEMS[section]) {
            const d = it.def !== null && typeof it.def === 'object' ? it.def[mode] : it.def;
            out[it.id] = it.id in o ? coerce(it, o[it.id], snap) : d;
        }
        return out;
    }
    /** A value into the item's domain (range clamped and rounded to the step, options checked, booleans). With zoom
     *  snapping (snap = true) the zoom is any number 0..the largest option: the exact steps are the page's, snapZoom picks. */
    function coerce(it, v, snap) {
        if (it.kind === 'check') return !!v && v !== 'false' && v !== '0';
        if (snap && it.id === 'zoom') {
            const n = Number(v), top = Math.max(...it.options);
            return isFinite(n) ? Math.min(top, Math.max(0, n)) : it.options[0];
        }
        if (it.kind === 'select') {
            const found = it.options.find((o) => String(o) === String(v));
            return found === undefined ? it.options[0] : found;
        }
        let n = Number(v);
        if (!isFinite(n)) n = it.min;
        n = Math.min(it.max, Math.max(it.min, n));
        const steps = Math.round((n - it.min) / it.step);
        return +(it.min + steps * it.step).toFixed(6);
    }
    /** Stored values (any shape) merged over the defaults: unknown ids dropped, every value coerced. */
    function merge(section, mode, stored, over, snap) {
        const out = defaults(section, mode, over, snap), s = (stored && stored[mode] && stored[mode][section]) || {};
        for (const it of ITEMS[section]) if (it.id in s) out[it.id] = coerce(it, s[it.id], snap);
        return out;
    }

    class Menu {
        constructor(host, spec) {
            this.spec = spec || {}; this.host = host;
            this.lang = this.spec.lang || 'en';
            this.texts = { display: Object.assign({}, (TEXTS[this.lang] || TEXTS.en).display, (this.spec.texts && this.spec.texts.display) || {}),
                           sound: Object.assign({}, (TEXTS[this.lang] || TEXTS.en).sound, (this.spec.texts && this.spec.texts.sound) || {}),
                           modes: Object.assign({}, (TEXTS[this.lang] || TEXTS.en).modes, (this.spec.texts && this.spec.texts.modes) || {}) };
            this.listeners = [];
            this.mode = MODES.includes(this.spec.mode) ? this.spec.mode : 'original';
            const stored = this.load();
            this.state = {};
            const snap = this.spec.zoom === 'snap';     // a stored exact zoom (e.g. 2 * 448 / 293) survives a reload; refreshZoom snaps it
            for (const m of MODES) this.state[m] = { display: merge('display', m, stored, this.spec.defaults, snap), sound: merge('sound', m, stored, this.spec.defaults) };
            if (stored && MODES.includes(stored.mode) && !this.spec.mode) this.mode = stored.mode;
            this.controls = { display: {}, sound: {} }; this.extras = {};
            if (host) this.render();
        }
        load() {
            try { const raw = this.spec.store && localStorage.getItem(this.spec.store); return raw ? JSON.parse(raw) : null; } catch (e) { return null; }
        }
        save() {
            try { if (this.spec.store) localStorage.setItem(this.spec.store, JSON.stringify(Object.assign({ mode: this.mode, version: VERSION }, this.state))); } catch (e) { /* private window, blocked storage */ }
        }
        render() {
            const d = this.host.ownerDocument || document, root = d.createElement('div'); root.className = 'wb-nastaveni';
            for (const section of ['display', 'sound']) {
                const fs = d.createElement('fieldset'); fs.className = 'wb-nastaveni-' + section;
                const lg = d.createElement('legend'); lg.textContent = this.texts[section]._; fs.appendChild(lg);
                for (const it of ITEMS[section]) fs.appendChild(this.row(d, section, it));
                const ex = d.createElement('div'); ex.className = 'wb-nastaveni-extras'; fs.appendChild(ex); this.extras[section] = ex;
                const btn = d.createElement('button'); btn.type = 'button'; btn.id = 'wb-defaults-' + section; btn.className = 'wb-nastaveni-defaults';
                btn.textContent = this.texts[section].defaults; btn.addEventListener('click', () => this.reset(section)); fs.appendChild(btn);
                root.appendChild(fs);
            }
            this.host.appendChild(root); this.root = root;
            this.refresh();
        }
        row(d, section, it) {
            const row = d.createElement('div'); row.className = 'wb-nastaveni-row wb-menu-' + it.kind;
            const label = d.createElement('label'); label.htmlFor = 'wb-' + it.id; label.textContent = this.texts[section][it.id] || it.id;
            let ctl;
            if (it.id === 'zoom' && this.spec.zoom === 'snap') {
                ctl = d.createElement('input'); ctl.type = 'range'; ctl.min = 0; ctl.step = 1; ctl.max = 0; ctl.dataset.snap = '1';
            } else if (it.kind === 'select') {
                ctl = d.createElement('select');
                for (const o of it.options) { const op = d.createElement('option'); op.value = String(o); op.textContent = this.optionText(section, o); ctl.appendChild(op); }
            } else {
                ctl = d.createElement('input'); ctl.type = it.kind === 'check' ? 'checkbox' : 'range';
                if (it.kind === 'range') { ctl.min = it.min; ctl.max = it.max; ctl.step = it.step; }
            }
            ctl.id = 'wb-' + it.id; ctl.dataset.section = section; ctl.dataset.item = it.id;
            const out = d.createElement('output'); out.htmlFor = ctl.id; out.className = 'wb-nastaveni-value';
            if (ctl.dataset.snap) ctl.addEventListener('input', () => { const st = this.zoomSteps(); const k = Math.min(st.length - 1, Math.max(0, +ctl.value)); if (st[k]) this.set(section, it.id, st[k].value); });
            else ctl.addEventListener(it.kind === 'range' ? 'input' : 'change', () => this.set(section, it.id, it.kind === 'check' ? ctl.checked : ctl.value));
            row.appendChild(label); row.appendChild(ctl); if (it.kind === 'range' || ctl.dataset.snap) row.appendChild(out);
            this.controls[section][it.id] = { ctl, out, it };
            return row;
        }
        optionText(section, o) {
            if (o === 0 && section === 'display') return this.texts.display.fit;
            const t = this.texts[section][String(o)];
            return t || (typeof o === 'number' ? String(o) + '×' : String(o));
        }
        /** The zooms this display shows exactly (spec.zoomSteps), as [{value, label}] sorted by value; [] without snapping. */
        zoomSteps() {
            if (this.spec.zoom !== 'snap' || typeof this.spec.zoomSteps !== 'function') return [];
            return (this.spec.zoomSteps() || []).map((z) => (typeof z === 'number' ? { value: z, label: String(+z.toFixed(2)) + '×' } : z))
                .filter((z) => z && typeof z.value === 'number').sort((a, b) => a.value - b.value);
        }
        /** The nearest exact zoom to `v` (0 = fit stays fit). */
        snapZoom(v) {
            const st = this.zoomSteps(); if (!st.length || !(v > 0)) return v;
            return st.reduce((best, z) => (Math.abs(z.value - v) < Math.abs(best - v) ? z.value : best), st[0].value);
        }
        /** After a resize or a dpr change with snapping: the steps and the value may have changed. */
        refreshZoom() { if (this.spec.zoom === 'snap') { const z = this.state[this.mode].display.zoom; this.state[this.mode].display.zoom = this.snapZoom(z); this.refresh(); } }
        /** Controls show the current mode's values. */
        refresh() {
            if (!this.root) return;
            this.root.dataset.mode = this.mode;
            for (const section of ['display', 'sound']) for (const it of ITEMS[section]) {
                const c = this.controls[section][it.id], v = this.state[this.mode][section][it.id];
                if (c.ctl.dataset.snap) {
                    const st = this.zoomSteps(); c.ctl.max = Math.max(0, st.length - 1);
                    const k = st.findIndex((z) => Math.abs(z.value - v) < 1e-9); c.ctl.value = String(k < 0 ? 0 : k);
                    if (c.out) c.out.value = v > 0 ? (st[k] ? st[k].label : String(v) + '×') : this.texts.display.fit;
                    continue;
                }
                if (it.kind === 'check') c.ctl.checked = !!v; else c.ctl.value = String(v);
                if (c.out) c.out.value = it.id === 'par' ? Number(v).toFixed(2) : String(v);
            }
        }
        get(section) {
            const s = this.state[this.mode];
            return section ? Object.assign({}, s[section]) : { mode: this.mode, display: Object.assign({}, s.display), sound: Object.assign({}, s.sound) };
        }
        getMode(mode, section) { return Object.assign({}, this.state[mode][section]); }
        setMode(mode) { if (!MODES.includes(mode)) return; this.mode = mode; this.refresh(); this.save(); this.emit('mode'); }
        set(section, id, value) {
            const it = ITEMS[section].find((x) => x.id === id); if (!it) return;
            this.state[this.mode][section][id] = (id === 'zoom' && this.spec.zoom === 'snap') ? this.snapZoom(Number(value) || 0) : coerce(it, value);
            this.refresh(); this.save(); this.emit(section);
        }
        reset(section) {
            for (const sec of section ? [section] : ['display', 'sound']) this.state[this.mode][sec] = defaults(sec, this.mode, this.spec.defaults, sec === 'display' && this.spec.zoom === 'snap');
            this.refresh(); this.save(); this.emit(section || 'all');
        }
        on(ev, fn) { this.listeners.push([ev, fn]); return this; }
        emit(what) { const st = this.get(); for (const [ev, fn] of this.listeners) if (ev === 'change' || ev === what) fn(st, what); }
        /** window.wbMenuTest for arek web test. */
        testHooks() {
            return { version: VERSION, ids: () => ['display', 'sound'].map((s) => ITEMS[s].map((it) => 'wb-' + it.id)).flat(),
                     get: (section) => this.get(section), getMode: (m, s) => this.getMode(m, s), setMode: (m) => this.setMode(m),
                     set: (s, id, v) => { this.set(s, id, v); return this.get(s); }, reset: (s) => { this.reset(s); return this.get(s); } };
        }
    }
    return { VERSION, MODES, ITEMS, TEXTS, defaults, coerce, merge, Menu, build: (host, spec) => new Menu(host, spec) };
})();
if (typeof globalThis !== 'undefined') { globalThis.WBNASTAVENI = WBNASTAVENI; if (!globalThis.WBMENU) globalThis.WBMENU = WBNASTAVENI; }   // WBMENU: the 0.6.0 name
if (typeof module !== 'undefined') module.exports = WBNASTAVENI;
