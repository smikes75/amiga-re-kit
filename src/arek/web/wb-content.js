// wb-content.js - the game's content from the visitor's disks for the payload key of wb-seal.js (amiga-re-kit,
// `arek web payload`): every ATN! block on the disks (sector aligned) is unpacked when its size is listed in content.json,
// kept when its SHA-256 matches, and the files are joined in the listed order - so every disk version that holds the
// same files opens the sealed code, wherever they lie on it. Needs wb-atn.js. No game data.
//   const payload = await WBCONTENT.build([adf1, adf2], contentJson);   // Uint8Array or null when a file is missing
//   const box = await WBSEAL.open(manifest, disks, { payload });
// content.json: {"content": "arek-atn-files-1", "files": [{"size": n, "sha256": "..."}, ...]}.
'use strict';
const WBCONTENT = (() => {
    const hex = (b) => Array.from(new Uint8Array(b), (x) => x.toString(16).padStart(2, '0')).join('');
    async function build(disks, manifest, opts) {
        const unpacker = (opts && opts.unpack) || (typeof ATNUNPACK !== 'undefined' ? ATNUNPACK : null);
        if (!unpacker) throw new Error('wb-content.js needs wb-atn.js (ATNUNPACK)');
        const step = (opts && opts.step) || 512;
        const want = manifest.files, found = new Array(want.length).fill(null);
        const sizes = new Set(want.map((f) => f.size));
        for (const buf of disks) {
            const d = buf instanceof Uint8Array ? buf : new Uint8Array(buf);
            for (let o = 0; o + 12 <= d.length; o += step) {
                const h = unpacker.header(d, o);
                if (!h || !sizes.has(h.unpacked)) continue;
                let out; try { out = unpacker.unpack(d, o); } catch (e) { continue; }
                const sha = hex(await crypto.subtle.digest('SHA-256', out));
                want.forEach((f, i) => { if (!found[i] && f.size === out.length && f.sha256 === sha) found[i] = out; });
            }
        }
        if (found.some((x) => !x)) return null;
        const n = found.reduce((s, x) => s + x.length, 0), all = new Uint8Array(n); let p = 0;
        for (const x of found) { all.set(x, p); p += x.length; }
        return all;
    }
    /** Which listed files the disks yield (for the page's message): [true/false per file]. */
    async function check(disks, manifest, opts) {
        const unpacker = (opts && opts.unpack) || (typeof ATNUNPACK !== 'undefined' ? ATNUNPACK : null);
        const step = (opts && opts.step) || 512, want = manifest.files, have = new Array(want.length).fill(false);
        for (const buf of disks) {
            const d = buf instanceof Uint8Array ? buf : new Uint8Array(buf);
            for (let o = 0; o + 12 <= d.length; o += step) {
                const h = unpacker.header(d, o);
                if (!h || !want.some((f) => f.size === h.unpacked)) continue;
                let out; try { out = unpacker.unpack(d, o); } catch (e) { continue; }
                const sha = hex(await crypto.subtle.digest('SHA-256', out));
                want.forEach((f, i) => { if (f.size === out.length && f.sha256 === sha) have[i] = true; });
            }
        }
        return have;
    }
    return { VERSION: '1.0', build, check };
})();
if (typeof globalThis !== 'undefined') { globalThis.WBCONTENT = WBCONTENT; if (!globalThis.gameContent) globalThis.gameContent = (d, m) => WBCONTENT.build(d, m); }
if (typeof module !== 'undefined') module.exports = WBCONTENT;
