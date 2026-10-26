// wb-atn.js - the Atomik (ATN!) decruncher for a page (amiga-re-kit): a line-by-line port of arek.packers.atomik.unpack
// (verified against the games' own unpackers: Superfrog, Alien Breed, Alien Breed II - 0 differences), so a page can
// rebuild the game's files from the visitor's disks (wb-content.js, the payload key of wb-seal.js). No game data.
// ATNUNPACK.unpack(u8, offset) -> Uint8Array or throws; ATNUNPACK.header(u8, offset) -> {unpacked, packed} | null.
// Works as a <script> (global ATNUNPACK) and as CommonJS.
'use strict';
const ATNUNPACK = (() => {
    const TRAILER = 46, LBH = [6, 10, 10, 18], LBM = 2, LBITS = [1, 1, 1, 1, 2, 3, 3, 4, 4, 5, 7, 14];
    const u32 = (d, o) => ((d[o] << 24) | (d[o + 1] << 16) | (d[o + 2] << 8) | d[o + 3]) >>> 0;
    function header(d, o) {
        o = o || 0;
        if (o + 12 > d.length || d[o] !== 0x41 || d[o + 1] !== 0x54 || d[o + 2] !== 0x4e || d[o + 3] !== 0x21) return null;
        return { unpacked: u32(d, o + 4), packed: u32(d, o + 8) };
    }
    function unpack(d, o, maxOut) {
        o = o || 0; maxOut = maxOut || (16 << 20);
        const h = header(d, o); if (!h) throw new Error('missing ATN! header');
        const outSize = h.unpacked, P = h.packed;
        if (P < 12 || o + P + TRAILER > d.length) throw new Error('truncated ATN! stream/trailer');
        if (!(outSize > 0 && outSize <= maxOut)) throw new Error('invalid ATN! output size');
        const src = d.slice(o, o + P);
        for (let i = 0; i < 3; i++) for (let j = 0; j < 4; j++) src[8 - 4 * i + j] = d[o + P + 4 * i + j];
        let literal = u32(d, o + P + 12);
        const initBits = (d[o + P + 16] << 8) | d[o + P + 17];
        const tb = o + P + 18, obase = [], obits = [];
        for (let i = 0; i < 8; i++) { let v = (d[tb + 2 * i] << 8) | d[tb + 2 * i + 1]; if (v & 0x8000) v -= 0x10000; obase.push(v); }
        for (let i = 0; i < 12; i++) obits.push(d[tb + 16 + i]);
        let cursor = P - ((initBits & 0x8000) ? 0 : 1), buf = initBits & 255;
        const out = new Uint8Array(outSize); let dest = outSize;
        const pop = () => { cursor--; if (cursor < 0) throw new Error('ATN! source underrun'); return src[cursor]; };
        const bit = () => {
            let carry = buf >> 7; buf = (buf << 1) & 255;
            if (buf === 0) { const v = pop(); buf = ((v << 1) | carry) & 255; carry = v >> 7; }
            return carry;
        };
        const bits = (n) => { if (n < 1 || n > 32) throw new Error('invalid ATN! bit count'); let v = 0; for (let i = 0; i < n; i++) v = (v * 2) + bit(); return v; };
        for (;;) {
            if (literal > dest) throw new Error('ATN! literal run exceeds output');
            for (let i = 0; i < literal; i++) { dest--; out[dest] = pop(); }
            if (dest === 0) break;
            let length = 2, cat = 0;
            while (cat < 4 && bit()) { length++; cat++; }
            if (cat === 4) { length = bit() ? pop() : bits(3) + 6; cat = 3; }
            let li = cat, lb = 0;
            if (bit()) { if (bit()) { lb = LBH[cat]; li += 8; } else { lb = LBM; li += 4; } }
            literal = (bits(LBITS[li]) + lb) & 65535;
            let oi = cat, ob = 0;
            if (bit()) { if (bit()) { ob = obase[4 + cat]; oi += 8; } else { ob = obase[cat]; oi += 4; } }
            const dist = ob + 1 + bits(obits[oi]);
            length = length || 256;
            if (length > dest || dist < 1 || dest + dist > outSize) throw new Error('invalid ATN! back reference');
            for (let i = 0; i < length; i++) { dest--; out[dest] = out[dest + dist]; }
        }
        if (cursor !== 0) throw new Error('ATN! final source pointer ' + cursor + ', expected 0');
        return out;
    }
    return { header, unpack };
})();
if (typeof globalThis !== 'undefined') globalThis.ATNUNPACK = ATNUNPACK;
if (typeof module !== 'undefined') module.exports = ATNUNPACK;
