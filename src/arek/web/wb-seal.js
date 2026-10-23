// wb-seal.js - open files sealed by `arek web seal` with the visitor's own disks (amiga-re-kit).
// Code derived from a game lies on the page encrypted (AES-GCM); its key is stored once per accepted disk
// set, wrapped with a key computed from the disk contents. WebCrypto only: needs https or localhost.
//
//   const box = await WBSEAL.open(await (await fetch('sealed/seal.json')).json(), [adf1, adf2]);
//   const wasm = await box.fetch('engine.wasm', 'sealed/');        // ArrayBuffer of the plain file
//
// Files sealed with --gzip are inflated here (DecompressionStream), so a page always gets the plain bytes.
// WBSEAL.ids(disks) gives the sha256 of each disk (hex), as seal.json lists them - for messages;
// manifest.keys[i].label names the accepted version of the disk.
'use strict';
const WBSEAL = (() => {
    const enc = new TextEncoder();
    const subtle = () => globalThis.crypto.subtle;
    const b64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
    const hex = (buf) => Array.from(new Uint8Array(buf), (x) => x.toString(16).padStart(2, '0')).join('');
    function concat(parts) {
        const n = parts.reduce((s, p) => s + p.byteLength, 0), out = new Uint8Array(n);
        let o = 0;
        for (const p of parts) { out.set(new Uint8Array(p instanceof ArrayBuffer ? p : p.buffer.slice(p.byteOffset, p.byteOffset + p.byteLength)), o); o += p.byteLength; }
        return out;
    }
    const sha = async (...parts) => new Uint8Array(await subtle().digest('SHA-256', concat(parts)));
    const diskKey = (adf) => sha(enc.encode('arek-seal-v1\0'), adf);
    async function setKey(disks) {
        if (disks.length === 1) return diskKey(disks[0]);
        const keys = [];
        for (const d of disks) keys.push(await diskKey(d));
        return sha(enc.encode('arek-seal-v1-set\0'), ...keys);
    }
    async function ids(disks) {
        const out = [];
        for (const d of disks) out.push(hex(await subtle().digest('SHA-256', concat([d]))));
        return out;
    }
    const aes = (raw, usage) => subtle().importKey('raw', raw, 'AES-GCM', false, [usage]);

    /** The key entry for these disks -> { get(path, sealedBytes), fetch(path, base) }; throws when none fits. */
    async function open(manifest, disks) {
        if (manifest.seal !== 'arek-seal-1') throw new Error('not an arek seal: ' + manifest.seal);
        const have = await ids(disks);
        const entry = manifest.keys.find((k) => k.disks.length === have.length && k.disks.every((d, i) => d === have[i]));
        if (!entry) throw new Error('no key for these disks');
        const wrap = await aes(await setKey(disks), 'decrypt');
        const ck = await subtle().decrypt({ name: 'AES-GCM', iv: b64(entry.iv), additionalData: enc.encode('arek-seal-key') },
                                          wrap, b64(entry.wrapped));
        const key = await aes(ck, 'decrypt');
        const files = new Map(manifest.files.map((f) => [f.path, f]));
        async function get(path, sealed) {
            const f = files.get(path);
            if (!f) throw new Error('not sealed here: ' + path);
            const plain = await subtle().decrypt({ name: 'AES-GCM', iv: b64(f.iv), additionalData: enc.encode(path) }, key, sealed);
            if (f.encoding !== 'gzip') return plain;
            const ds = new DecompressionStream('gzip');
            return new Response(new Blob([plain]).stream().pipeThrough(ds)).arrayBuffer();
        }
        return {
            get,
            async fetch(path, base) {
                const r = await fetch((base || '') + path + '.sealed');
                if (!r.ok) throw new Error(path + '.sealed: HTTP ' + r.status);
                return get(path, await r.arrayBuffer());
            },
        };
    }
    return { open, ids };
})();
if (typeof globalThis !== 'undefined') globalThis.WBSEAL = WBSEAL;
if (typeof module !== 'undefined') module.exports = WBSEAL;
