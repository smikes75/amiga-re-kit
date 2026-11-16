// wb-vtr.js 1.0 (kit 1.0.84) - VTR2 trace records written from JavaScript (amiga-re-kit, docs/HEADLESS.md "A rebuild writes
// VTR2 records"). A rewrite that keeps its state in its own objects, not in the original's RAM (SWIV-projekt's hand-written
// JavaScript), projects the fields it shares with the original onto the original's addresses and writes one record per
// event the original's trace has a breakpoint for (a pass, an object made, destroyed, a sound): `arek trace compare
// ORIGINAL.vtr REWRITE.vtr --range START:LEN ...` then compares only those fields, record by record, with --shift /
// --best-shift / --fail as for a recompiled engine; --regs when the rewrite gives the registers it really has.
//   const w = WBVTR.writer();
//   w.add({ pc: 0x6160, frame: 812, d: [...], a: [...], fields: [[0x2a10, 'w', x], [0x2a12, 'w', y], [0x2a20, 'b', hp]] });
//   w.add({ pc, frame, ranges: [[start, bytes]] })     // or whole spans, bytes as in the Amiga's RAM (big-endian)
//   w.bytes() -> Uint8Array of every record (write it to a .vtr file; Node: fs.writeFileSync(path, w.bytes()))
// A record: 24 little-endian uint32 (magic 'VTR2', pc, hit, frame, v, hpos, sr, d0-d7, a0-a7, the number of ranges), then per
// range its start and length (uint32 little-endian) and its bytes. Fields: [address, 'b' | 'w' | 'l', value] - next to each
// other they become one range (a gap between them is a range boundary, not zeros the original never had there). hit counts
// the records of the same pc from 1 when not given. Registers the rewrite does not keep stay 0 (compare without --regs).
// Read back by arek.headless.trace.records(); arek.headless.trace.encode() writes the same from Python. No game data.
'use strict';
(function (root) {
    const VERSION = '1.0', MAGIC = 0x32525456, SIZE = { b: 1, w: 2, l: 4 };

    function fieldRanges(fields) {
        const fs = fields.map(([addr, fmt, value]) => {
            const n = SIZE[fmt];
            if (!n) throw new Error('wb-vtr: field format ' + fmt + ' (b, w or l)');
            const b = new Uint8Array(n);
            for (let i = 0; i < n; i++) b[i] = (Number(value) >>> (8 * (n - 1 - i))) & 0xff;   // big-endian, as in RAM
            return [addr >>> 0, b];
        }).sort((p, q) => p[0] - q[0]);
        const out = [];
        for (const [a, b] of fs) {
            const last = out[out.length - 1];
            if (last && a < last[0] + last[1].length) throw new Error('wb-vtr: fields overlap at $' + a.toString(16));
            if (last && a === last[0] + last[1].length) { const m = new Uint8Array(last[1].length + b.length); m.set(last[1]); m.set(b, last[1].length); last[1] = m; }
            else out.push([a, b]);
        }
        return out;
    }

    function record(r) {
        const ranges = (r.ranges || []).map(([s, b]) => [s >>> 0, b instanceof Uint8Array ? b : Uint8Array.from(b)]).concat(r.fields ? fieldRanges(r.fields) : []);
        const len = 96 + ranges.reduce((t, [, b]) => t + 8 + b.length, 0), out = new Uint8Array(len), v = new DataView(out.buffer);
        const d = r.d || [], a = r.a || [];
        const head = [MAGIC, r.pc || 0, r.hit || 0, r.frame || 0, r.v || 0, r.h || 0, r.sr || 0];
        for (let i = 0; i < 8; i++) head.push(d[i] || 0);
        for (let i = 0; i < 8; i++) head.push(a[i] || 0);
        head.push(ranges.length);
        head.forEach((x, i) => v.setUint32(i * 4, x >>> 0, true));
        let p = 96;
        for (const [s, b] of ranges) { v.setUint32(p, s, true); v.setUint32(p + 4, b.length, true); out.set(b, p + 8); p += 8 + b.length; }
        return out;
    }

    function writer() {
        const parts = [], hits = new Map();
        return {
            add(r) {
                const pc = r.pc || 0, hit = r.hit || (hits.get(pc) || 0) + 1;
                hits.set(pc, hit);
                parts.push(record(Object.assign({}, r, { hit })));
                return parts.length;
            },
            get count() { return parts.length; },
            bytes() {
                const n = parts.reduce((t, b) => t + b.length, 0), out = new Uint8Array(n);
                let p = 0;
                for (const b of parts) { out.set(b, p); p += b.length; }
                return out;
            },
        };
    }

    const api = { VERSION, record, writer, fieldRanges };
    if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.WBVTR = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
