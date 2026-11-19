// wb-mixer.js 1.1 - the sound mixer window of a rebuild's page (amiga-re-kit 1.0.93; SWIV, the user 2026-11-18: SWIV-projekt's
// mixer for SWIV-recomp). The game's sounds by kind: a slider per group of the page (0-200 %), a master and an "extra voices"
// row, a light per group (played / on an extra voice / silenced), "defaults", "all 100 %", "copy values"; a double-click on a row
// gives it its default. Only Enhanced: in Original every level is 1 (the engine's mix is then bit for bit the plain one).
// No game data: the page gives the groups (names and numbers only) and its defaults. Works as a <script> (global WBMIXER) and
// as CommonJS; without a document (Node, tests) the state works the same and no window is built.
//
//   const mixer = WBMIXER.build(null, { groups: [{ id: 'fire', label: 'player shots' }, { id: 'expl', label: { en: 'explosions', cs: 'výbuchy' } }],
//                                      defaults: { master: 1.35, extra: 0.95, fire: 2 }, store: 'mygame-wb-mixer-v1', lang: 'cs',
//                                      name: 'MYGAME', focusGame: () => canvas.focus() });
//   mixer.setMode('enhanced');                 // 'original': everything 1, the sliders off
//   mixer.toggle();                            // the window (a .wbwin of wb.css, fixed at the top right, not modal)
//   each frame: mixer.apply(E._engine_aud_mix); mixer.lights(new Int32Array(E.HEAP32.buffer, E._engine_aud_counts(), 192));
//
// The engine (arek_host_engine.c 1.0.93): group i of spec.groups is the engine's sound kind i on Paula and 32 + i on the
// host's extra voices - the game's hook tags each sound at its start (arek_host.h host_aud_tag(ch, kind)) and counts the ones
// it drops (host_aud_dropped(kind)). levels()[i] = master * group, levels()[32 + i] = master * extra * group; apply(fn) calls
// fn(kind, level) for the kinds whose level changed since the last apply (all 64 the first time). lights(counts) reads
// engine_aud_counts (int32 [64][3]: played on Paula, played on an extra voice, dropped) and lights the groups whose counts
// moved since the last call (silenced over extra over played).
// The store keeps only what the player chose (own values); a value never moved follows the page's default, so a page that
// tunes its defaults moves its old visitors too. Test hooks: window.wbMixerTest = mixer.testHooks().
// 1.1 (kit 1.0.94, the user 2026-11-19: "only Enhanced quieter"): spec.headroom (0..1, default 1) - Enhanced plays every
// channel at that base level so the boosts have room under the limiter; the kit's Paula is 7.75 dB louder than vAmiga's
// (one channel at full volume = 0.496 of full scale against vAmiga's 0.2032), WBMIXER.VAMIGA = 0.4096 gives SWIV-projekt's
// gain staging, for which its defaults were tuned. apply(fn) also sends fn(-1, base) (engine_aud_mix(-1, level): every
// channel, tagged or not) - the headroom in Enhanced, 1 in Original (the plain mix, bit for bit). base() says it.
'use strict';
const WBMIXER = (() => {
    const VERSION = '1.1';
    const KINDS = 64, EXTRA = 32;
    const VAMIGA = 0.4096;                     // 1.1: vAmiga's level against the kit's: 0.2048 / 128 per step over 2 / 32768 * 64
    const TEXTS = {
        en: { title: 'Sound mixer', master: 'master volume', extra: 'extra voices', defaults: 'defaults', unity: 'all 100 %', copy: 'copy values',
              copied: 'copied', close: 'Close', enhanced: 'Enhanced: a change applies at once, also to the sounds playing now',
              original: 'Original plays every sound at 100 % - switch to Enhanced to mix',
              help: 'light: green = played, orange = on an extra voice, red = silenced (the original would not play it) · double-click a row = its default · orange value = not the default' },
        cs: { title: 'Mixér zvuku', master: 'celková hlasitost', extra: 'hlasy navíc', defaults: 'výchozí', unity: 'vše 100 %', copy: 'kopírovat hodnoty',
              copied: 'zkopírováno', close: 'Zavřít', enhanced: 'Vylepšeno: změna platí hned, i pro právě hrající zvuky',
              original: 'Originál hraje všechny zvuky na 100 % - mixér platí ve Vylepšeno',
              help: 'kontrolka: zelená = zahráno, oranžová = na hlasu navíc, červená = umlčeno (originál by ho nezahrál) · dvojklik na řádek = výchozí · oranžová hodnota = není výchozí' },
    };
    const LIGHTS = ['played', 'extra', 'silenced'];

    /** A level: a number 0..2 in steps of 0.05 (5 %); anything else is null. */
    function coerce(v) {
        const n = typeof v === 'string' ? parseFloat(v) : v;
        if (typeof n !== 'number' || !Number.isFinite(n)) return null;
        return Math.round(Math.min(2, Math.max(0, n)) * 20) / 20;
    }
    /** The groups checked: ids unique, not 'master' / 'extra', at most 32. */
    function groupsOf(list) {
        const seen = new Set(['master', 'extra']);
        const out = (list || []).map((g) => {
            if (!g || !g.id) throw new Error('wb-mixer: a group without an id');
            if (seen.has(g.id)) throw new Error('wb-mixer: the group id ' + g.id + ' is taken');
            seen.add(g.id);
            return { id: String(g.id), label: g.label === undefined ? String(g.id) : g.label };
        });
        if (out.length > EXTRA) throw new Error('wb-mixer: at most ' + EXTRA + ' groups');
        return out;
    }
    /** The engine's 64 levels for the values v ({ master, extra, id: level }) - all 1 in Original. */
    function levels(groups, v, mode) {
        const out = new Float64Array(KINDS).fill(1);
        if (mode === 'original') return out;
        groups.forEach((g, i) => {
            const lv = v.master * v[g.id];
            out[i] = Math.min(4, lv); out[EXTRA + i] = Math.min(4, lv * v.extra);
        });
        return out;
    }
    /** The light of a group from the counts' change: silenced over extra over played, null when nothing moved. */
    function lightOf(i, now, before) {
        const d = (k) => (now[i * 3 + k] - before[i * 3 + k]) + (now[(EXTRA + i) * 3 + k] - before[(EXTRA + i) * 3 + k]);
        return d(2) > 0 ? 'silenced' : d(1) > 0 ? 'extra' : d(0) > 0 ? 'played' : null;
    }
    function storage() { try { return globalThis.localStorage || null; } catch (e) { return null; } }

    class Mixer {
        constructor(host, spec) {
            this.spec = spec || {};
            this.groups = groupsOf(this.spec.groups);
            this.ids = ['master', ...(this.spec.extra === false ? [] : ['extra']), ...this.groups.map((g) => g.id)];
            this.lang = TEXTS[this.spec.lang] ? this.spec.lang : 'en';
            this.t = Object.assign({}, TEXTS[this.lang], this.spec.texts || {});
            this.mode = this.spec.mode === 'original' ? 'original' : 'enhanced';
            this.listeners = [];
            this.own = {};
            this.sent = null; this.sentBase = null;
            const h = Number(this.spec.headroom);
            this.headroom = Number.isFinite(h) && h > 0 && h <= 1 ? h : 1;
            this.seen = null;
            this.load();
            this.el = null;
            if (host !== null && typeof document !== 'undefined') this.buildWindow(host || document.body);
        }
        /** The default of a row: the page's (spec.defaults[id]), else 1. */
        def(id) { const d = coerce((this.spec.defaults || {})[id]); return d === null ? 1 : d; }
        /** Every row's value: the player's own, else the default. */
        get() {
            const v = {};
            for (const id of this.ids) v[id] = id in this.own ? this.own[id] : this.def(id);
            if (!('extra' in v)) v.extra = 1;
            return v;
        }
        set(id, value) {
            const c = coerce(value);
            if (!this.ids.includes(id) || c === null) return;
            this.own[id] = c; this.save(); this.changed('set', id);
        }
        /** reset('defaults'): every row follows the page's default again; reset('unity'): every row at 100 % (chosen). */
        reset(how) {
            this.own = {};
            if (how === 'unity') for (const id of this.ids) this.own[id] = 1;
            this.save(); this.changed('reset', how === 'unity' ? 'unity' : 'defaults');
        }
        /** A row back to its default (the double-click). */
        unset(id) { if (id in this.own) { delete this.own[id]; this.save(); this.changed('set', id); } }
        setMode(mode) { this.mode = mode === 'original' ? 'original' : 'enhanced'; this.changed('mode', this.mode); }
        levels() { return levels(this.groups, this.get(), this.mode); }
        /** 1.1: every channel's base level - spec.headroom in Enhanced, 1 in Original. */
        base() { return this.mode === 'original' ? 1 : this.headroom; }
        /** fn(kind, level) for each of the engine's kinds whose level changed since the last apply, and fn(-1, base) when the
         *  base changed (1.1); all of them the first time and after forget(); returns how many calls. */
        apply(fn) {
            const lv = this.levels(), b = this.base(); let n = 0;
            if (this.sentBase !== b) { fn(-1, b); n++; this.sentBase = b; }
            for (let k = 0; k < KINDS; k++) if (!this.sent || this.sent[k] !== lv[k]) { fn(k, lv[k]); n++; }
            this.sent = lv;
            return n;
        }
        /** The next apply sends everything again (a new engine). */
        forget() { this.sent = null; this.sentBase = null; }
        /** Lights from engine_aud_counts (int32 [64][3]); returns { id: 'played' | 'extra' | 'silenced' } of the groups that moved. */
        lights(counts) {
            const now = Array.from(counts || []).slice(0, KINDS * 3), out = {};
            if (now.length < KINDS * 3) return out;
            if (this.seen) this.groups.forEach((g, i) => { const how = lightOf(i, now, this.seen); if (how) { out[g.id] = how; this.ping(g.id, how); } });
            this.seen = now;
            return out;
        }
        /** Light a group's lamp for a moment (the page may call it itself). */
        ping(id, how) {
            if (!this.el || !LIGHTS.includes(how)) return;
            const lamp = this.el.querySelector('[data-mix="' + id + '"] .wb-mixer-light');
            if (!lamp) return;
            lamp.dataset.light = how; clearTimeout(lamp._t);
            lamp._t = setTimeout(() => { delete lamp.dataset.light; }, 400);
        }
        /** The values that are not 100 %, as the page's defaults would take them. */
        copyText() {
            const v = this.get(), out = {};
            for (const id of this.ids) if (v[id] !== 1) out[id] = v[id];
            return (this.spec.name ? this.spec.name + ' ' : '') + 'mixer ' + JSON.stringify(out);
        }
        on(ev, fn) { this.listeners.push([ev, fn]); return this; }
        changed(cause, what) {
            this.refresh();
            const v = this.get();
            for (const [ev, fn] of this.listeners) if (ev === 'change' || ev === cause) fn(v, { cause, id: what, mode: this.mode });
        }
        load() {
            const st = storage(); if (!st || !this.spec.store) return;
            try {
                const o = JSON.parse(st.getItem(this.spec.store) || 'null');
                if (o && typeof o.own === 'object') for (const id of this.ids) { const c = coerce(o.own[id]); if (c !== null) this.own[id] = c; }
            } catch (e) { /* a broken store: the defaults */ }
        }
        save() {
            const st = storage(); if (!st || !this.spec.store) return;
            try { st.setItem(this.spec.store, JSON.stringify({ version: VERSION, own: this.own })); } catch (e) { /* full or blocked */ }
        }
        label(id) {
            if (id === 'master' || id === 'extra') return this.t[id];
            const g = this.groups.find((x) => x.id === id), l = g.label;
            return typeof l === 'object' && l ? (l[this.lang] || l.en || id) : String(l);
        }
        // ---- the window --------------------------------------------------------------------------------------------------
        buildWindow(host) {
            const mk = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; };
            const win = mk('section', 'wbwin wb-mixer'); win.hidden = true; win.setAttribute('role', 'dialog'); win.setAttribute('aria-label', this.t.title);
            const bar = mk('div', 'wbwtitle'), h = mk('h2', '', this.t.title), x = mk('button', 'wb-mixer-close', '✕');
            x.type = 'button'; x.setAttribute('aria-label', this.t.close); x.onclick = () => this.close();
            bar.append(h, x);
            const note = mk('p', 'wbnote wb-mixer-note'), rows = mk('div', 'wb-mixer-rows');
            for (const id of this.ids) {
                if (id === this.groups[0]?.id) rows.append(mk('hr'));
                const row = mk('label', 'wb-mixer-row'); row.dataset.mix = id;
                const lamp = mk('span', 'wb-mixer-light'); if (id === 'master' || id === 'extra') lamp.classList.add('none');
                const name = mk('span', 'wb-mixer-name', this.label(id)); name.title = this.label(id);
                const inp = mk('input'); inp.type = 'range'; inp.min = '0'; inp.max = '200'; inp.step = '5'; inp.id = 'wb-mix-' + id;
                inp.setAttribute('aria-label', this.label(id));
                inp.oninput = () => this.set(id, +inp.value / 100);
                inp.addEventListener('pointerup', () => setTimeout(() => this.spec.focusGame && this.spec.focusGame(), 0));
                row.ondblclick = (e) => { e.preventDefault(); this.unset(id); };
                row.append(lamp, name, inp, mk('output', 'wb-mixer-value'));
                rows.append(row);
            }
            const btns = mk('div', 'wb-mixer-buttons'), msg = mk('output', 'wb-mixer-msg');
            const b = (cls, text, fn) => { const e = mk('button', cls, text); e.type = 'button'; e.onclick = fn; btns.append(e); return e; };
            b('wb-mixer-defaults', this.t.defaults, () => this.reset('defaults'));
            b('wb-mixer-unity', this.t.unity, () => this.reset('unity'));
            b('wb-mixer-copy', this.t.copy, () => {
                const text = this.copyText(), show = (s) => { msg.textContent = s; clearTimeout(msg._t); msg._t = setTimeout(() => { msg.textContent = ''; }, 6000); };
                const cb = typeof navigator !== 'undefined' && navigator.clipboard;
                if (cb && cb.writeText) cb.writeText(text).then(() => show(this.t.copied), () => show(text)); else show(text);
            });
            btns.append(msg);
            win.append(bar, note, rows, btns, mk('p', 'wbnote wb-mixer-help', this.t.help));
            win.addEventListener('keydown', (e) => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); this.close(); } });
            host.append(win);
            this.el = win;
            this.refresh();
        }
        refresh() {
            if (!this.el) return;
            const v = this.get(), off = this.mode === 'original';
            this.el.toggleAttribute('data-off', off);
            this.el.querySelector('.wb-mixer-note').textContent = off ? this.t.original : this.t.enhanced;
            for (const row of this.el.querySelectorAll('.wb-mixer-row')) {
                const id = row.dataset.mix, inp = row.querySelector('input'), pc = Math.round(v[id] * 100);
                inp.value = String(pc); inp.disabled = off;
                row.querySelector('output').textContent = pc + ' %';
                row.classList.toggle('changed', v[id] !== this.def(id));
            }
        }
        get isOpen() { return !!this.el && !this.el.hidden; }
        open() { if (!this.el) return; this.el.hidden = false; this.refresh(); this.el.querySelector('.wb-mixer-close').focus({ preventScroll: true }); }
        close() { if (!this.el || this.el.hidden) return; this.el.hidden = true; if (this.spec.focusGame) this.spec.focusGame(); }
        toggle() { if (this.isOpen) this.close(); else this.open(); }
        get element() { return this.el; }
        /** window.wbMixerTest for the page's tests. */
        testHooks() {
            return { version: VERSION, ids: () => this.ids.slice(), get: () => this.get(), set: (id, v) => { this.set(id, v); return this.get(); },
                     reset: (how) => { this.reset(how); return this.get(); }, levels: () => Array.from(this.levels()), base: () => this.base(), mode: () => this.mode,
                     setMode: (m) => this.setMode(m), open: () => this.open(), close: () => this.close(), isOpen: () => this.isOpen };
        }
    }
    return { VERSION, KINDS, EXTRA, VAMIGA, TEXTS, coerce, groupsOf, levels, lightOf, Mixer, build: (host, spec) => new Mixer(host, spec) };
})();
if (typeof globalThis !== 'undefined') globalThis.WBMIXER = WBMIXER;
if (typeof module !== 'undefined') module.exports = WBMIXER;
