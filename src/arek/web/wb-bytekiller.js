// wb-bytekiller.js - the Bytekiller TAIL decruncher for a page (amiga-re-kit 1.0.45): a line-by-line port of
// arek.packers.bytekiller.unpack_tail (the unpacked length and the first bit word are the LAST two longs of the block, as a
// crunched executable has them), both code tables: 'b' the classic Bytekiller one, 'c' counted literal runs followed by one
// match (Xenon 2 KIT-GAP 17). So a page can rebuild a game's program from the visitor's disk. No game data.
// BKUNPACK.unpackTail(u8, off, end, code) -> { data: Uint8Array, exact } (exact: the bit stream was used up at off - the
// only evidence this layout offers) or throws; BKUNPACK.unpackTailAny(u8, off, end) -> { data, code } of the ONE table that
// decodes the block exactly, or throws. Works as a <script> (global BKUNPACK) and as CommonJS.
'use strict';
const BKUNPACK = (() => {
    const VERSION = '1.0';
    function reader(d, end, start) {
        let pos = end, buf = 0;
        const long = () => { pos -= 4; if (pos < start) throw new Error('the packed stream ran out - damaged data or a wrong offset'); return ((d[pos] << 24) | (d[pos + 1] << 16) | (d[pos + 2] << 8) | d[pos + 3]) >>> 0; };
        buf = long();
        const bit = () => { const c = buf & 1; buf >>>= 1; if (buf) return c; const n = long(); buf = ((c << 31) | (n >>> 1)) >>> 0; return n & 1; };
        const bits = (n) => { let v = 0; for (let i = 0; i < n; i++) v = (v << 1) | bit(); return v; };
        return { bit, bits, pos: () => pos };
    }
    function decodeB(br, size) {
        const out = new Uint8Array(size); let p = size;
        const literals = (n) => { if (p - n < 0) throw new Error('a literal run passes the start of the output - damaged data or a wrong offset'); for (let i = 0; i < n; i++) out[--p] = br.bits(8); };
        const match = (len, ofs) => { let s = p + ofs; if (p - len < 0 || s > size) throw new Error('a match passes the output - damaged data or a wrong offset'); for (let i = 0; i < len; i++) out[--p] = out[--s]; };
        while (p > 0) {
            if (br.bit() === 0) { if (br.bit() === 0) literals(br.bits(3) + 1); else match(2, br.bits(8)); }
            else { const sel = br.bits(2); if (sel === 0) match(3, br.bits(9)); else if (sel === 1) match(4, br.bits(10)); else if (sel === 2) { const n = br.bits(8) + 1; match(n, br.bits(12)); } else literals(br.bits(8) + 9); }
        }
        return out;
    }
    function decodeC(br, size) {
        const out = new Uint8Array(size); let p = size;
        for (;;) {
            let n = br.bits(3);
            if (n === 7) { if (br.bit() === 0) n = br.bits(4) + 7; else { n = br.bits(10); if (n === 0) n = br.bits(18); } }
            if (p - n < 0) throw new Error('a literal run passes the start of the output - damaged data or a wrong offset');
            for (let i = 0; i < n; i++) out[--p] = br.bits(8);
            if (p === 0) break;
            const c = br.bits(2); let len, width;
            if (c === 0) { len = 2; width = 8; }
            else if (c === 1) { len = 3; width = br.bit() ? 8 : 14; }
            else {
                if (c === 2) len = 4; else { const e = br.bits(2); len = e === 3 ? br.bits(8) : e === 2 ? br.bits(2) + 7 : e + 5; }
                width = br.bit() === 0 ? 16 : br.bit() ? 8 : 12;
            }
            const ofs = br.bits(width);
            if (p - len < 0 || ofs === 0 || p - 1 + ofs >= size) throw new Error('a match passes the output - damaged data or a wrong offset');
            for (let i = 0; i < len; i++) { p--; out[p] = out[p + ofs]; }
            if (p === 0) break;
        }
        return out;
    }
    const CODES = { b: decodeB, c: decodeC };
    function unpackTail(d, off, end, code) {
        off = off || 0; end = end === undefined || end === null ? d.length : end; code = code || 'b';
        if (!CODES[code]) throw new Error("code is 'b' or 'c'");
        if (end - off < 8 || end > d.length || (end - off) % 4) throw new Error('a TAIL block is whole longs between its start and its end (' + (end - off) + ' bytes)');
        const size = ((d[end - 4] << 24) | (d[end - 3] << 16) | (d[end - 2] << 8) | d[end - 1]) >>> 0;
        if (size === 0 || size > (8 << 20)) throw new Error('implausible unpacked length: ' + size + ' (the last long of the block)');
        const br = reader(d, end - 4, off), data = CODES[code](br, size);
        return { data, exact: br.pos() === off };
    }
    function unpackTailAny(d, off, end) {
        const hits = [], errors = [];
        for (const code of ['b', 'c']) {
            let r; try { r = unpackTail(d, off, end, code); } catch (e) { errors.push(code + ': ' + e.message); continue; }
            if (r.exact) hits.push({ data: r.data, code }); else errors.push(code + ': decoded, but the bit stream was not used up exactly');
        }
        if (hits.length !== 1) throw new Error('TAIL block: ' + (hits.length ? 'both code tables decode it exactly - name the code' : errors.join('; ')));
        return hits[0];
    }
    return { VERSION, unpackTail, unpackTailAny };
})();
if (typeof globalThis !== 'undefined') globalThis.BKUNPACK = BKUNPACK;
if (typeof module !== 'undefined') module.exports = BKUNPACK;
