// wb-nastaveni.js - the shared Display / Sound menu of the rebuilds (amiga-re-kit, MENU-ZVUK.md, 1.2). One module builds
// the common controls with the same ids, ranges, defaults and storage in every game; the game adds its own items in
// the `extras` slots and supplies texts (English and Czech are built in) and the defaults it wants per mode.
// No game data, no CSS beyond the wb-nastaveni* classes (the game styles it). Works as a <script> (global WBNASTAVENI) and as
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
//   wished value snaps to the nearest step; `menu.refreshZoom()` after a resize or a dpr change (`{keep: true}`: the slider
//   shows the nearest step, the stored wish stays). Listeners get (state, what, {cause: 'set'|'reset'|'mode', id|section}).
//   Values show with the item's unit in the menu's language (`20 %`, `1,04`).
//   1.3: spec.omit = { sound: ['filter-fixed', 'filter-led'], display: [...] } leaves rows out (a machine that has no such
//   thing): the row is not built, its value is fixed - the filters off, any other item at its default - and menu.set ignores it.
//   1.4 (kit 1.0.84, SWIV): spec.rows - the game's own rows, described, built and kept by the menu like its own:
//     { id, section: 'display' | 'sound' | any other name (default 'display'), kind: 'select' | 'check' | 'range' | 'button',
//       label, options: [...], labels: { option: text }, def: value | { original, enhanced }, min / max / step / unit / digits,
//       modes: ['enhanced'] (shown only there), when: { otherId: value | [values] } (shown only while that row of the same
//       section has the value), perMode: false (one value for both modes: a trainer, a debug start), changesGame: true | [options]
//       (marked "changes the game" - the row or those options), run: (menu) => {} for a button }.
//     A row of 'display' / 'sound' goes after the kit's rows of that section; a row of another section into spec.hosts[section]
//     (an element - the page's Debug panel) or, without one, into a fieldset of its own (legend spec.texts[section]._). Its
//     control's id is 'wb-' + id; ids are unique across the menu. get(section) has the rows' values (a hidden row keeps its
//     value), set / reset / the listeners / the store treat them as the kit's own; a button keeps no value.
//
//   1.5 (kit 1.0.91, the user 2026-11-18: buttons under the slider, an automatic zoom): with spec.zoom = 'snap' the zoom row
//     gets buttons (.zoom-buttons): 'auto' (zoom 0 - the largest exact zoom that fits, following the window) and the exact
//     zooms from 1x up (zoomButtons: the whole and half ones when at least two are exact here, else every exact one; at most
//     7, the whole ones first when there are more). The zoom a page gives no default for is 'auto'. A zoom the player has not
//     chosen (slider, button, menu.set - stored as zoomOwn per mode; a store from 1.4 has none) follows the page's default,
//     so a page that moves to 'auto' moves its old visitors too; "Default picture" makes it unchosen again. In 'auto' the
//     slider stands on the largest step (the one auto uses) and shows "auto (3×)". The page calls menu.refreshZoom({ keep:
//     true }) after a resize, a full screen change and a devicePixelRatio change (WBOBRAZ.watchDpr, wb-obraz 1.11).
//   1.6 (kit 1.0.92, the user 2026-11-18: a stepless zoom): spec.stepless = true adds the row 'stepless' (Display, a check,
//     off by default; without spec.stepless the row is left out and off). While it is on, the slider runs from 1x to
//     spec.zoomFit() (the zoom that fills the window: limit * par * W / W0) in 0.01 steps and an exact zoom (zoomSteps)
//     within 0.04 catches it; the buttons stay ('auto' then fills the window - WBOBRAZ.stepless). Turned off, the zoom goes
//     back to the nearest exact step. The page draws with WBOBRAZ.stepless(zoom, ...) -> { S, shrink } while it is on.
//
// The file is wb-nastaveni.js (not wb-menu.js: that name is the games' own Workbench bar). Every value is kept per mode (original / enhanced). Test hooks (arek web test §6): window.wbMenuTest = menu.testHooks().
'use strict';
const WBNASTAVENI = (() => {
    const VERSION = '1.6';
    const MODES = ['original', 'enhanced'];
    const ITEMS = {
        display: [
            { id: 'zoom', kind: 'select', options: [1, 1.5, 2, 2.5, 3, 4, 6, 0], def: { original: 2, enhanced: 3 } },
            { id: 'crt', kind: 'check', def: true },
            { id: 'crt-detail', kind: 'select', options: ['fine', 'standard', 'strong'], def: { original: 'strong', enhanced: 'fine' } },
            { id: 'crt-shape', kind: 'select', options: ['lines', 'grid'], def: 'lines' },
            { id: 'blur', kind: 'range', unit: '%', min: 0, max: 100, step: 1, def: { original: 0, enhanced: 20 } },
            { id: 'brightness', kind: 'range', unit: '%', min: 50, max: 150, step: 1, def: 100 },
            { id: 'contrast', kind: 'range', unit: '%', min: 50, max: 150, step: 1, def: 100 },
            { id: 'saturation', kind: 'range', unit: '%', min: 0, max: 200, step: 1, def: 100 },
            { id: 'red', kind: 'range', unit: '%', min: 50, max: 150, step: 1, def: 100 },
            { id: 'green', kind: 'range', unit: '%', min: 50, max: 150, step: 1, def: 100 },
            { id: 'blue', kind: 'range', unit: '%', min: 50, max: 150, step: 1, def: 100 },
            { id: 'par', kind: 'range', digits: 2, min: 1, max: 1.1, step: 0.01, def: { original: 1, enhanced: 1.04 } },
            { id: 'smooth', kind: 'check', def: { original: false, enhanced: true } },
            { id: 'stepless', kind: 'check', def: false },                     // 1.6: only with spec.stepless
        ],
        sound: [
            { id: 'sound', kind: 'check', def: true },
            { id: 'volume', kind: 'range', unit: '%', min: 0, max: 100, step: 1, def: 80 },
            { id: 'filter-fixed', kind: 'check', def: true, none: false },
            { id: 'filter-led', kind: 'select', options: ['auto', 'on', 'off'], def: 'auto', none: 'off' },
            { id: 'filter-hp', kind: 'check', def: true, none: false },
            { id: 'stereo', kind: 'range', unit: '%', min: 0, max: 100, step: 1, def: { original: 100, enhanced: 70 } },
        ],
    };
    const TEXTS = {
        en: { display: { _: 'Display', zoom: 'Zoom', crt: 'CRT', 'crt-detail': 'CRT detail', 'crt-shape': 'CRT shape', blur: 'Blur', brightness: 'Brightness',
                         contrast: 'Contrast', saturation: 'Saturation', red: 'Red', green: 'Green', blue: 'Blue', par: 'Pixel width', smooth: 'Smooth motion', stepless: 'Stepless zoom', defaults: 'Default picture for this mode',
                         fit: 'auto', fitTitle: 'the largest exact zoom that fits the window, follows it', fine: 'fine', standard: 'standard', strong: 'strong', lines: 'lines', grid: 'grid' },
              sound: { _: 'Sound', sound: 'Sound', volume: 'Volume', 'filter-fixed': 'Amiga 500 filter', 'filter-led': 'LED filter', 'filter-hp': 'High-pass',
                       stereo: 'Stereo width', defaults: 'Default sound for this mode', auto: 'as the game', on: 'on', off: 'off' },
              modes: { original: 'Original', enhanced: 'Enhanced' }, game: { changes: 'changes the game' } },
        cs: { display: { _: 'Obraz', zoom: 'Zvětšení', crt: 'CRT', 'crt-detail': 'Stupeň CRT', 'crt-shape': 'Tvar CRT', blur: 'Rozmazání', brightness: 'Jas',
                         contrast: 'Kontrast', saturation: 'Sytost', red: 'Červená', green: 'Zelená', blue: 'Modrá', par: 'Šířka bodu', smooth: 'Plynulé zobrazení', stepless: 'Plynulé zvětšení', defaults: 'Výchozí obraz tohoto režimu',
                         fit: 'auto', fitTitle: 'největší přesné zvětšení, které se vejde do okna; mění se s ním', fine: 'jemný', standard: 'střední', strong: 'silný', lines: 'řádky', grid: 'mřížka' },
              sound: { _: 'Zvuk', sound: 'Zvuk', volume: 'Hlasitost', 'filter-fixed': 'Filtr Amigy 500', 'filter-led': 'Filtr LED', 'filter-hp': 'Horní propust',
                       stereo: 'Šířka sterea', defaults: 'Výchozí zvuk tohoto režimu', auto: 'podle hry', on: 'zapnuto', off: 'vypnuto' },
              modes: { original: 'Originál', enhanced: 'Vylepšeno' }, game: { changes: 'mění hru' } },
    };
    const KIT_SECTIONS = ['display', 'sound'];

    /** 1.4: a game row with its kind, section and modes filled in; ids must be unique over the kit's items and the rows. */
    function rowsOf(list) {
        const seen = new Set(KIT_SECTIONS.flatMap((s) => ITEMS[s].map((it) => it.id)));
        return (list || []).map((r) => {
            if (!r || !r.id) throw new Error('wb-nastaveni: a row without an id');
            if (seen.has(r.id)) throw new Error('wb-nastaveni: the row id ' + r.id + ' is taken');
            seen.add(r.id);
            const kind = r.kind || (Array.isArray(r.options) ? 'select' : 'check');
            if (!['select', 'check', 'range', 'button'].includes(kind)) throw new Error('wb-nastaveni: row ' + r.id + ' kind ' + kind);
            if (kind === 'select' && !(Array.isArray(r.options) && r.options.length)) throw new Error('wb-nastaveni: row ' + r.id + ' has no options');
            return Object.assign({ section: 'display', perMode: true }, r, { kind, game: true });
        });
    }
    /** 1.4: a row's default for a mode (an object per mode or one value; none given: the first option, off, the minimum). */
    function rowDefault(r, mode) {
        const d = r.def !== null && typeof r.def === 'object' && !Array.isArray(r.def) ? r.def[mode] : r.def;
        if (d !== undefined) return coerce(r, d);
        return r.kind === 'select' ? r.options[0] : r.kind === 'range' ? r.min : false;
    }

    /** The default of an item for a mode: the game's override (spec.defaults[section][mode][id]) wins. */
    function defaults(section, mode, over, snap, omit) {
        const out = {}, o = (over && over[section] && over[section][mode]) || {}, om = omitted(omit, section);
        for (const it of ITEMS[section]) {
            const d = it.def !== null && typeof it.def === 'object' ? it.def[mode] : it.def;
            out[it.id] = om.has(it.id) && 'none' in it ? it.none : it.id in o ? coerce(it, o[it.id], snap) : snap && it.id === 'zoom' ? 0 : d;   // 1.3: a row the page left out has no effect; 1.5: snap - auto
        }
        return out;
    }
    /** 1.3: the rows a page leaves out (spec.omit = { display: [ids], sound: [ids] }) - a machine without the Amiga's filters
     *  has no rows for them. A row left out is not built, takes no stored value and cannot be set; its value is the item's
     *  `none` (the filters: off) or, where an item has none, the default of the mode (the page's override wins). */
    function omitted(omit, section) { return new Set((omit && omit[section]) || []); }
    /** 1.5: the exact zooms (values > 0) that get a button: from 1x up; the whole and half ones when at least two of them
     *  are exact here (a monitor at 100 %: 1 2 3, a Retina: 1 1.5 2 2.5 3), else every exact one (Windows at 125 %:
     *  1.6 2.4 3.2); more than 7 - the whole ones if at least two, then the 7 largest. */
    function zoomButtons(values) {
        const near = (v, k) => Math.abs(v * k - Math.round(v * k)) < 1e-3;
        const big = (values || []).filter((v) => typeof v === 'number' && v >= 1 - 1e-3).sort((a, b) => a - b);
        const half = big.filter((v) => near(v, 2));
        let out = half.length >= 2 ? half : big;
        if (out.length > 7) { const whole = out.filter((v) => near(v, 1)); if (whole.length >= 2) out = whole; }
        return out.slice(-7);
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
            if (found !== undefined) return found;
            const n = Number(v), nums = it.options.filter((o) => typeof o === 'number' && o > 0);   // 0 = fit only when asked for
            if (v !== '' && v !== null && isFinite(n) && n > 0 && nums.length)
                return nums.reduce((best, o) => (Math.abs(o - n) < Math.abs(best - n) ? o : best), nums[0]);   // e.g. an old 2.2 -> 2
            return it.options[0];
        }
        let n = Number(v);
        if (!isFinite(n)) n = it.min;
        n = Math.min(it.max, Math.max(it.min, n));
        const steps = Math.round((n - it.min) / it.step);
        return +(it.min + steps * it.step).toFixed(6);
    }
    /** Stored values (any shape) merged over the defaults: unknown ids dropped, every value coerced. */
    function merge(section, mode, stored, over, snap, omit) {
        const out = defaults(section, mode, over, snap, omit), s = (stored && stored[mode] && stored[mode][section]) || {}, om = omitted(omit, section);
        for (const it of ITEMS[section]) if (it.id in s && !om.has(it.id)) out[it.id] = coerce(it, s[it.id], snap);
        return out;
    }

    class Menu {
        constructor(host, spec) {
            this.spec = Object.assign({}, spec || {}); this.host = host;
            if (!this.spec.stepless || this.spec.zoom !== 'snap') {                     // 1.6: the stepless row only when the page draws it
                const om = Object.assign({}, this.spec.omit || {}); om.display = [...new Set([...(om.display || []), 'stepless'])]; this.spec.omit = om;
            }
            this.lang = this.spec.lang || 'en';
            this.texts = { display: Object.assign({}, (TEXTS[this.lang] || TEXTS.en).display, (this.spec.texts && this.spec.texts.display) || {}),
                           sound: Object.assign({}, (TEXTS[this.lang] || TEXTS.en).sound, (this.spec.texts && this.spec.texts.sound) || {}),
                           modes: Object.assign({}, (TEXTS[this.lang] || TEXTS.en).modes, (this.spec.texts && this.spec.texts.modes) || {}) };
            this.listeners = [];
            this.mode = MODES.includes(this.spec.mode) ? this.spec.mode : 'original';
            this.texts.game = Object.assign({}, (TEXTS[this.lang] || TEXTS.en).game, (this.spec.texts && this.spec.texts.game) || {});
            this.rows = rowsOf(this.spec.rows);                                       // 1.4: the game's rows
            this.sections = KIT_SECTIONS.concat([...new Set(this.rows.map((r) => r.section))].filter((s) => !KIT_SECTIONS.includes(s)));
            const stored = this.load();
            this.state = {};
            const snap = this.spec.zoom === 'snap';     // a stored exact zoom (e.g. 2 * 448 / 293) survives a reload; refreshZoom snaps it
            for (const m of MODES) {
                this.state[m] = { display: merge('display', m, stored, this.spec.defaults, snap, this.spec.omit), sound: merge('sound', m, stored, this.spec.defaults, false, this.spec.omit) };
                for (const sec of this.sections) this.state[m][sec] = Object.assign(this.state[m][sec] || {}, this.rowValues(sec, m, stored && stored[m] && stored[m][sec]));
            }
            this.zoomOwn = {};                                                         // 1.5: the player chose the zoom (per mode)
            for (const m of MODES) {
                this.zoomOwn[m] = !!(snap && stored && stored.zoomOwn && stored.zoomOwn[m]);
                if (snap && !this.zoomOwn[m]) this.state[m].display.zoom = defaults('display', m, this.spec.defaults, true, this.spec.omit).zoom;
            }
            this.shared = {};
            for (const sec of this.sections) this.shared[sec] = this.rowValues(sec, null, stored && stored.shared && stored.shared[sec]);
            if (stored && MODES.includes(stored.mode) && !this.spec.mode) this.mode = stored.mode;
            this.controls = {}; for (const sec of this.sections) this.controls[sec] = {};
            this.extras = {};
            if (host) this.render();
        }
        load() {
            try { const raw = this.spec.store && localStorage.getItem(this.spec.store); return raw ? JSON.parse(raw) : null; } catch (e) { return null; }
        }
        save() {
            try { if (this.spec.store) localStorage.setItem(this.spec.store, JSON.stringify(Object.assign({ mode: this.mode, version: VERSION, shared: this.shared, zoomOwn: this.zoomOwn }, this.state))); } catch (e) { /* private window, blocked storage */ }
        }
        /** 1.4: the values of a section's rows for a mode (mode null: the rows kept for both modes), stored values coerced
         *  over the defaults. */
        rowValues(section, mode, stored) {
            const out = {};
            for (const r of this.rows) {
                if (r.section !== section || r.kind === 'button' || (mode === null) !== (r.perMode === false)) continue;
                out[r.id] = stored && r.id in stored ? coerce(r, stored[r.id]) : rowDefault(r, mode || MODES[0]);
            }
            return out;
        }
        rowOf(section, id) { return this.rows.find((r) => r.section === section && r.id === id); }
        /** 1.4: a row is shown in its modes and while the rows it depends on (when) have the values it names. */
        visible(r) {
            if (r.modes && !r.modes.includes(this.mode)) return false;
            for (const [k, want] of Object.entries(r.when || {})) {
                const dep = this.rowOf(r.section, k);
                if (dep && dep !== r && !this.visible(dep)) return false;              // the row it depends on is hidden: so is it
                const v = this.get(r.section)[k], ok = Array.isArray(want) ? want.map(String).includes(String(v)) : String(want) === String(v);
                if (!ok) return false;
            }
            return true;
        }
        render() {
            const d = this.host.ownerDocument || document, root = d.createElement('div'); root.className = 'wb-nastaveni';
            for (const section of ['display', 'sound']) {
                const fs = d.createElement('fieldset'); fs.className = 'wb-nastaveni-' + section;
                const lg = d.createElement('legend'); lg.textContent = this.texts[section]._; fs.appendChild(lg);
                for (const it of ITEMS[section]) if (!omitted(this.spec.omit, section).has(it.id)) {
                    fs.appendChild(this.row(d, section, it));
                    if (it.id === 'zoom' && this.spec.zoom === 'snap') {                // 1.5: the buttons under the slider
                        const box = d.createElement('div'); box.className = 'zoom-buttons wb-nastaveni-zoom-buttons'; box.id = 'wb-zoom-buttons';
                        box.setAttribute('role', 'group'); box.setAttribute('aria-label', this.texts.display.zoom);
                        fs.appendChild(box); this.zoomBox = box;
                    }
                }
                for (const r of this.rows) if (r.section === section) fs.appendChild(this.row(d, section, r));   // 1.4
                const ex = d.createElement('div'); ex.className = 'wb-nastaveni-extras'; fs.appendChild(ex); this.extras[section] = ex;
                const btn = d.createElement('button'); btn.type = 'button'; btn.id = 'wb-defaults-' + section; btn.className = 'wb-nastaveni-defaults';
                btn.textContent = this.texts[section].defaults; btn.addEventListener('click', () => this.reset(section)); fs.appendChild(btn);
                root.appendChild(fs);
            }
            for (const section of this.sections.filter((s) => !KIT_SECTIONS.includes(s))) {   // 1.4: the game's own sections
                const host = this.spec.hosts && this.spec.hosts[section];
                const box = d.createElement(host ? 'div' : 'fieldset'); box.className = 'wb-nastaveni-' + section + ' wb-nastaveni-rows';
                if (!host) { const lg = d.createElement('legend'); lg.textContent = (this.spec.texts && this.spec.texts[section] && this.spec.texts[section]._) || section; box.appendChild(lg); }
                for (const r of this.rows) if (r.section === section) box.appendChild(this.row(d, section, r));
                (host || root).appendChild(box);
            }
            this.host.appendChild(root); this.root = root;
            this.refresh();
        }
        row(d, section, it) {
            const row = d.createElement('div'); row.className = 'wb-nastaveni-row wb-menu-' + it.kind + (it.game ? ' wb-nastaveni-game' : '') + (it.changesGame === true ? ' wb-nastaveni-changes' : '');
            const mark = (t, on) => (on ? t + ' (' + this.texts.game.changes + ')' : t);
            if (it.kind === 'button') {                                                // 1.4: a row that does something, keeps nothing
                const b = d.createElement('button'); b.type = 'button'; b.id = 'wb-' + it.id; b.className = 'wbitem wb-nastaveni-action';
                b.textContent = mark(it.label || it.id, it.changesGame === true); b.addEventListener('click', () => { if (it.run) it.run(this); });
                row.appendChild(b); this.controls[section][it.id] = { ctl: b, it, row };
                return row;
            }
            const label = d.createElement('label'); label.htmlFor = 'wb-' + it.id;
            label.textContent = it.game ? mark(it.label || it.id, it.changesGame === true) : (this.texts[section][it.id] || it.id);
            let ctl;
            if (it.id === 'zoom' && this.spec.zoom === 'snap' && !it.game) {
                ctl = d.createElement('input'); ctl.type = 'range'; ctl.min = 0; ctl.step = 1; ctl.max = 0; ctl.dataset.snap = '1';
            } else if (it.kind === 'select') {
                ctl = d.createElement('select');
                for (const o of it.options) {
                    const op = d.createElement('option'); op.value = String(o);
                    op.textContent = it.game ? mark(it.labels && String(o) in it.labels ? it.labels[String(o)] : typeof o === 'number' ? this.num(o) : String(o),
                                                    Array.isArray(it.changesGame) && it.changesGame.map(String).includes(String(o)))
                        : this.optionText(section, o);
                    ctl.appendChild(op);
                }
            } else {
                ctl = d.createElement('input'); ctl.type = it.kind === 'check' ? 'checkbox' : 'range';
                if (it.kind === 'range') { ctl.min = it.min; ctl.max = it.max; ctl.step = it.step; }
            }
            ctl.id = 'wb-' + it.id; ctl.dataset.section = section; ctl.dataset.item = it.id;
            const out = d.createElement('output'); out.htmlFor = ctl.id; out.className = 'wb-nastaveni-value';
            if (ctl.dataset.snap) ctl.addEventListener('input', () => {
                if (this.stepless()) { this.set(section, it.id, this.catchZoom(+ctl.value)); return; }      // 1.6: a value, not a step index
                const st = this.zoomSteps(); const k = Math.min(st.length - 1, Math.max(0, +ctl.value)); if (st[k]) this.set(section, it.id, st[k].value); });
            else ctl.addEventListener(it.kind === 'range' ? 'input' : 'change', () => this.set(section, it.id, it.kind === 'check' ? ctl.checked : ctl.value));
            row.appendChild(label); row.appendChild(ctl); if (it.kind === 'range' || ctl.dataset.snap) row.appendChild(out);
            this.controls[section][it.id] = { ctl, out, it, row };
            return row;
        }
        /** A number as the menu's language writes it (1,04 in Czech), with the item's unit (20 %). */
        num(v, digits) {
            const tag = this.lang === 'cs' ? 'cs-CZ' : 'en-GB';
            return Number(v).toLocaleString(tag, { minimumFractionDigits: digits || 0, maximumFractionDigits: digits === undefined ? 2 : digits });
        }
        valueText(it, v) { return this.num(v, it.digits) + (it.unit ? (this.lang === 'cs' ? '\u00a0' : '') + it.unit : ''); }
        optionText(section, o) {
            if (o === 0 && section === 'display') return this.texts.display.fit;
            const t = this.texts[section][String(o)];
            return t || (typeof o === 'number' ? this.num(o) + '×' : String(o));
        }
        /** 1.5: the buttons under the slider - built again when the exact zooms change, the one in use pressed. */
        zoomButtonsFill(st, v) {
            const box = this.zoomBox; if (!box) return;
            const pick = zoomButtons(st.map((z) => z.value)), key = pick.join(' ');
            if (box.dataset.steps !== key) {
                const d = box.ownerDocument; box.textContent = '';
                const add = (value, text, title) => {
                    const b = d.createElement('button'); b.type = 'button'; b.dataset.zoom = String(value); b.textContent = text;
                    if (title) b.title = title;
                    b.addEventListener('click', () => this.set('display', 'zoom', value)); box.appendChild(b);
                };
                add(0, this.texts.display.fit, this.texts.display.fitTitle);
                for (const z of pick) { const s = st.find((x) => Math.abs(x.value - z) < 1e-9); add(z, s ? s.label : this.num(z) + '×'); }
                box.dataset.steps = key;
            }
            const near = v > 0 ? this.snapZoom(v) : 0;
            for (const b of box.children) b.setAttribute('aria-pressed', Math.abs(Number(b.dataset.zoom) - near) < 1e-9 ? 'true' : 'false');
        }
        /** The zooms this display shows exactly (spec.zoomSteps), as [{value, label}] sorted by value; [] without snapping. */
        zoomSteps() {
            if (this.spec.zoom !== 'snap' || typeof this.spec.zoomSteps !== 'function') return [];
            return (this.spec.zoomSteps() || []).map((z) => (typeof z === 'number' ? { value: z, label: this.num(z) + '×' } : z))
                .filter((z) => z && typeof z.value === 'number').sort((a, b) => a.value - b.value);
        }
        /** 1.6: the stepless zoom is on (the page asked for it and the row is ticked). */
        stepless() { return !!(this.spec.stepless && this.spec.zoom === 'snap' && this.state[this.mode].display.stepless); }
        /** 1.6: the zoom that fills the window (spec.zoomFit), else the largest exact step. */
        zoomFit() {
            const f = typeof this.spec.zoomFit === 'function' ? Number(this.spec.zoomFit()) : NaN, st = this.zoomSteps().filter((z) => z.value > 0);
            return f > 0 ? +f.toFixed(2) : st.length ? st[st.length - 1].value : 1;
        }
        /** 1.6: a stepless value, caught by an exact zoom within 0.04. */
        catchZoom(v) {
            const st = this.zoomSteps().filter((z) => z.value > 0), near = st.find((z) => Math.abs(z.value - v) <= 0.04);
            return near ? near.value : +Number(v).toFixed(2);
        }
        /** The nearest exact zoom to `v` (0 = fit stays fit); 1.6: stepless - any zoom from 1x to the window. */
        snapZoom(v) {
            if (this.stepless()) return v > 0 ? Math.min(Math.max(1, v), Math.max(1, this.zoomFit())) : v;
            const st = this.zoomSteps(); if (!st.length || !(v > 0)) return v;
            return st.reduce((best, z) => (Math.abs(z.value - v) < Math.abs(best - v) ? z.value : best), st[0].value);
        }
        /** After a resize or a dpr change with snapping: the steps may have changed. The stored zoom snaps to the nearest step
         *  (and is saved); with { keep: true } only the slider moves to the nearest step and the stored wish stays. */
        refreshZoom(opts) {
            if (this.spec.zoom !== 'snap') return;
            if (!(opts && opts.keep)) { const z = this.state[this.mode].display.zoom; this.state[this.mode].display.zoom = this.snapZoom(z); this.save(); }
            this.refresh();
        }
        /** Controls show the current mode's values. */
        refresh() {
            if (!this.root) return;
            this.root.dataset.mode = this.mode;
            for (const r of this.rows) {                                               // 1.4: the game's rows - shown or hidden, values
                const c = this.controls[r.section][r.id]; if (!c) continue;
                c.row.hidden = !this.visible(r);
                if (r.kind === 'button') continue;
                const v = this.get(r.section)[r.id];
                if (r.kind === 'check') c.ctl.checked = !!v; else c.ctl.value = String(v);
                if (c.out) c.out.value = this.valueText(r, v);
            }
            for (const section of ['display', 'sound']) for (const it of ITEMS[section]) {
                const c = this.controls[section][it.id], v = this.state[this.mode][section][it.id];
                if (!c) continue;                                                       // 1.3: a row left out
                if (c.ctl.dataset.snap && this.stepless()) {                              // 1.6: 1x .. the zoom that fills the window
                    const st = this.zoomSteps(), fit = this.zoomFit();
                    c.ctl.min = 1; c.ctl.max = String(Math.max(1, fit)); c.ctl.step = 0.01;
                    c.ctl.value = String(v > 0 ? v : fit);
                    if (c.out) c.out.value = v > 0 ? this.num(v) + '×' : this.texts.display.fit + ' (' + this.num(fit) + '×)';
                    this.zoomButtonsFill(st, v);
                    continue;
                }
                if (c.ctl.dataset.snap) {
                    c.ctl.min = 0; c.ctl.step = 1;
                    const st = this.zoomSteps(); c.ctl.max = Math.max(0, st.length - 1);
                    const near = v > 0 ? this.snapZoom(v) : v, k = st.findIndex((z) => Math.abs(z.value - near) < 1e-9);   // off-step: nearest, value unchanged
                    const top = st.length - 1, kk = k >= 0 ? k : v > 0 ? 0 : top;      // 1.5: auto stands on the largest step (the one it uses)
                    c.ctl.value = String(Math.max(0, kk));
                    if (c.out) c.out.value = v > 0 ? (st[k] ? st[k].label : this.num(v) + '×')
                        : this.texts.display.fit + (st[top] && st[top].value > 0 ? ' (' + st[top].label + ')' : '');
                    this.zoomButtonsFill(st, v);
                    continue;
                }
                if (it.kind === 'check') c.ctl.checked = !!v; else c.ctl.value = String(v);
                if (c.out) c.out.value = this.valueText(it, v);
            }
        }
        get(section) {
            const s = this.state[this.mode];
            if (section) return Object.assign({}, s[section], this.shared[section]);
            const out = { mode: this.mode };
            for (const sec of this.sections) out[sec] = Object.assign({}, s[sec], this.shared[sec]);
            return out;
        }
        getMode(mode, section) { return Object.assign({}, this.state[mode][section], this.shared[section]); }
        setMode(mode) { if (!MODES.includes(mode)) return; this.mode = mode; this.refresh(); this.save(); this.emit('mode', { cause: 'mode' }); }
        set(section, id, value) {
            const r = this.rowOf(section, id);
            if (r) {                                                                   // 1.4: a game row
                if (r.kind === 'button') return;
                (r.perMode === false ? this.shared[section] : this.state[this.mode][section])[id] = coerce(r, value);
                this.refresh(); this.save(); this.emit(section, { cause: 'set', id });
                return;
            }
            const it = (ITEMS[section] || []).find((x) => x.id === id); if (!it || omitted(this.spec.omit, section).has(id)) return;
            this.state[this.mode][section][id] = (id === 'zoom' && this.spec.zoom === 'snap') ? this.snapZoom(Number(value) || 0) : coerce(it, value);
            if (id === 'zoom' && this.spec.zoom === 'snap') this.zoomOwn[this.mode] = true;   // 1.5: the player's choice
            if (id === 'stepless' && !value) { const d = this.state[this.mode].display; d.zoom = this.snapZoom(d.zoom); }   // 1.6: back to an exact step
            this.refresh(); this.save(); this.emit(section, { cause: 'set', id });
        }
        reset(section) {
            for (const sec of section ? [section] : this.sections) {
                this.state[this.mode][sec] = Object.assign(KIT_SECTIONS.includes(sec) ? defaults(sec, this.mode, this.spec.defaults, sec === 'display' && this.spec.zoom === 'snap', this.spec.omit) : {},
                                                           this.rowValues(sec, this.mode, null));
                this.shared[sec] = this.rowValues(sec, null, null);                    // 1.4: the rows kept for both modes too
                if (sec === 'display') this.zoomOwn[this.mode] = false;                 // 1.5: the zoom follows the default again
            }
            this.refresh(); this.save(); this.emit(section || 'all', { cause: 'reset', section: section || 'all' });
        }
        on(ev, fn) { this.listeners.push([ev, fn]); return this; }
        /** Listeners get (state, what, info): info.cause = 'set' (with info.id), 'reset' (with info.section) or 'mode'. */
        emit(what, info) { const st = this.get(); for (const [ev, fn] of this.listeners) if (ev === 'change' || ev === what) fn(st, what, info || {}); }
        /** window.wbMenuTest for arek web test. */
        testHooks() {
            return { version: VERSION, ids: () => ['display', 'sound'].map((s) => ITEMS[s].filter((it) => !omitted(this.spec.omit, s).has(it.id)).map((it) => 'wb-' + it.id)).flat(),
                     get: (section) => this.get(section), getMode: (m, s) => this.getMode(m, s), setMode: (m) => this.setMode(m),
                     set: (s, id, v) => { this.set(s, id, v); return this.get(s); }, reset: (s) => { this.reset(s); return this.get(s); },
                     rows: () => this.rows.map((r) => 'wb-' + r.id), shown: () => this.rows.filter((r) => this.visible(r)).map((r) => 'wb-' + r.id) };
        }
    }
    return { VERSION, MODES, ITEMS, TEXTS, defaults, coerce, merge, omitted, zoomButtons, rowsOf, rowDefault, Menu, build: (host, spec) => new Menu(host, spec) };
})();
if (typeof globalThis !== 'undefined') { globalThis.WBNASTAVENI = WBNASTAVENI; if (!globalThis.WBMENU) globalThis.WBMENU = WBNASTAVENI; }   // WBMENU: the 0.6.0 name
if (typeof module !== 'undefined') module.exports = WBNASTAVENI;
