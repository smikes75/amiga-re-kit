"""Sealed files: code derived from a game on a public page, usable only with the original disk.

A rebuild's translated or rewritten code is derived from the original. ``seal`` encrypts such
files (AES-GCM) with a random content key and stores that key once per accepted disk set, wrapped
with a key computed from the **contents** of the disks - not from their published sha256, which a
page shows to tell versions apart. A visitor who loads the disk gets the key in the browser
(``web/wb-seal.js``, WebCrypto); without the disk the files are noise.

    manifest, blobs = seal({'engine.wasm': data}, [[disk1], [disk1_v2]])
    write_dir('build/present/sealed', manifest, blobs)       # seal.json + engine.wasm.sealed

Keys: disk key = SHA-256("arek-seal-v1\\0" + ADF bytes); a set of several disks (a game that needs
two) = SHA-256("arek-seal-v1-set\\0" + disk keys in order). Each file's path is its associated
data, so files cannot be swapped. Needs the optional ``cryptography`` package (``[web]`` extra).

A **payload key** (0.5.12) is computed from the game's own content instead of the raw disk:
SHA-256("arek-seal-v1-payload\\0" + payload), where the payload is what the rebuild actually reads
(the unpacked game files in a fixed order, built by the page's own loader). Every disk version
that yields the same files opens it, whichever group cracked the boot block; a version with
different game data opens nothing - and would not run the rebuild correctly anyway.

    manifest, blobs = seal({'engine.wasm': data}, [[disk1]], payloads=[payload], payload_labels=['retail or crack, same files'])

This is a lock, not a licence: the files are still derived from the original.
"""
import base64
import gzip
import hashlib
import json
import os
from pathlib import Path

VERSION = 'arek-seal-1'
KEY_AAD = b'arek-seal-key'


def _aes(key):
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as e:
        raise RuntimeError('sealing needs the cryptography package: pip install amiga-re-kit[web]') from e
    return AESGCM(key)


def disk_key(adf):
    return hashlib.sha256(b'arek-seal-v1\0' + bytes(adf)).digest()


def set_key(disks):
    if len(disks) == 1:
        return disk_key(disks[0])
    return hashlib.sha256(b'arek-seal-v1-set\0' + b''.join(disk_key(d) for d in disks)).digest()


def payload_key(payload):
    return hashlib.sha256(b'arek-seal-v1-payload\0' + bytes(payload)).digest()


def _b64(b):
    return base64.b64encode(b).decode()


def seal(files, disk_sets, content_key=None, labels=None, compress=False, payloads=None, payload_labels=None):
    """files: {path: bytes}; disk_sets: [[adf bytes, ...], ...] - each set that may open them,
    ``labels`` one text per set (which version of the disk); ``compress``: gzip before sealing
    (wb-seal.js inflates on open; ``size``/``sha256`` describe the plain file); ``payloads``:
    game contents that open them too (see ``payload_key``), ``payload_labels`` one text each.
    Returns (manifest, {path: sealed bytes})."""
    disk_sets = list(disk_sets or [])
    payloads = list(payloads or [])
    if any(not s for s in disk_sets) or any(not p for p in payloads):
        raise ValueError('an empty disk set or payload cannot open anything')
    if not disk_sets and not payloads:
        raise ValueError('seal needs at least one set of disks or one payload')
    ck = content_key or os.urandom(32)
    aes = _aes(ck)
    manifest = {'seal': VERSION, 'files': [], 'keys': []}
    blobs = {}
    for path, data in files.items():
        iv = os.urandom(12)
        body = gzip.compress(bytes(data), 9, mtime=0) if compress else bytes(data)
        blobs[path] = aes.encrypt(iv, body, path.encode())
        entry = {'path': path, 'iv': _b64(iv), 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        if compress:
            entry['encoding'] = 'gzip'
            entry['stored'] = len(body)
        manifest['files'].append(entry)
    for k, disks in enumerate(disk_sets):
        iv = os.urandom(12)
        entry = {'disks': [hashlib.sha256(bytes(d)).hexdigest() for d in disks], 'iv': _b64(iv),
                 'wrapped': _b64(_aes(set_key(disks)).encrypt(iv, ck, KEY_AAD))}
        if labels and k < len(labels) and labels[k]:
            entry['label'] = labels[k]
        manifest['keys'].append(entry)
    for k, payload in enumerate(payloads):
        iv = os.urandom(12)
        entry = {'payload': hashlib.sha256(bytes(payload)).hexdigest(), 'iv': _b64(iv),
                 'wrapped': _b64(_aes(payload_key(payload)).encrypt(iv, ck, KEY_AAD))}
        if payload_labels and k < len(payload_labels) and payload_labels[k]:
            entry['label'] = payload_labels[k]
        manifest['keys'].append(entry)
    return manifest, blobs


def unseal(manifest, blobs, disks=None, payload=None):
    """The plain files for ``disks``, or for a game ``payload`` (ValueError when no key entry takes
    them or a file was altered)."""
    from cryptography.exceptions import InvalidTag
    if payload is not None:
        pid = hashlib.sha256(bytes(payload)).hexdigest()
        entry = next((k for k in manifest['keys'] if k.get('payload') == pid), None)
        if entry is None:
            raise ValueError('no key for this game content (%s)' % pid[:12])
        wrap = payload_key(payload)
    else:
        ids = [hashlib.sha256(bytes(d)).hexdigest() for d in disks or []]
        entry = next((k for k in manifest['keys'] if k.get('disks') == ids), None)
        if entry is None:
            raise ValueError('no key for these disks (%s)' % ', '.join(i[:12] for i in ids))
        wrap = set_key(disks)
    try:
        ck = _aes(wrap).decrypt(base64.b64decode(entry['iv']), base64.b64decode(entry['wrapped']), KEY_AAD)
        aes = _aes(ck)
        out = {}
        for f in manifest['files']:
            body = aes.decrypt(base64.b64decode(f['iv']), blobs[f['path']], f['path'].encode())
            out[f['path']] = gzip.decompress(body) if f.get('encoding') == 'gzip' else body
        return out
    except InvalidTag:
        raise ValueError('the disks or the sealed files do not match') from None


def write_dir(out, manifest, blobs):
    """``out/seal.json`` and ``out/<path>.sealed``."""
    out = Path(out)
    for path, data in blobs.items():
        p = out / (path + '.sealed')
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'seal.json').write_text(json.dumps(manifest, indent=1) + '\n')
    return out / 'seal.json'


def read_dir(folder):
    folder = Path(folder)
    manifest = json.loads((folder / 'seal.json').read_text())
    return manifest, {f['path']: (folder / (f['path'] + '.sealed')).read_bytes() for f in manifest['files']}


GAME_DATA = ('.adf', '.adz', '.dms', '.ipf', '.rom')
BIG = 10 * 1024 * 1024


def check_bundle(folder):
    """A presentation bundle (PREZENTACE-WEB.md): no game data, every derived file sealed and
    listed in seal.json, manifest.json matching the files on disk. Returns
    ``{'files': n, 'bytes': n, 'sealed': [...], 'problems': [...], 'big': [...]}``."""
    folder = Path(folder)
    problems, big, sealed = [], [], []
    present = {str(p.relative_to(folder)): p for p in folder.rglob('*') if p.is_file()}
    for rel, p in present.items():
        if p.suffix.lower() in GAME_DATA:
            problems.append('game data in the bundle: %s' % rel)
        if p.stat().st_size > BIG:
            big.append((rel, p.stat().st_size))
    seal_json = folder / 'sealed' / 'seal.json'
    if seal_json.exists():
        m = json.loads(seal_json.read_text())
        if m.get('seal') != VERSION:
            problems.append('sealed/seal.json: not %s' % VERSION)
        for f in m.get('files', []):
            sealed.append(f['path'])
            if not (folder / 'sealed' / (f['path'] + '.sealed')).exists():
                problems.append('sealed/seal.json lists %s but sealed/%s.sealed is missing' % (f['path'], f['path']))
            if (folder / f['path']).exists():
                problems.append('%s is sealed and also present in the clear' % f['path'])
        if not m.get('keys'):
            problems.append('sealed/seal.json has no disk sets')
    manifest = folder / 'manifest.json'
    if manifest.exists():
        mf = json.loads(manifest.read_text())
        entries = mf.get('files', mf if isinstance(mf, list) else [])
        listed = set()
        for e in entries:
            rel = e['path']
            listed.add(rel)
            p = present.get(rel)
            if p is None:
                problems.append('manifest lists %s, not in the bundle' % rel)
                continue
            if 'size' in e and e['size'] != p.stat().st_size:
                problems.append('%s: manifest size %d, file %d' % (rel, e['size'], p.stat().st_size))
            if 'sha256' in e and e['sha256'] != hashlib.sha256(p.read_bytes()).hexdigest():
                problems.append('%s: sha256 differs from the manifest' % rel)
            if e.get('derived') and not (rel.startswith('sealed/') and rel.endswith('.sealed')):
                problems.append('%s is derived from the game but not sealed' % rel)
        for rel in present:
            if rel not in listed and rel != 'manifest.json':
                problems.append('%s is in the bundle but not in the manifest' % rel)
    else:
        problems.append('no manifest.json')
    for rel in present:
        if rel.startswith('sealed/') and rel.endswith('.sealed') and rel[len('sealed/'):-len('.sealed')] not in sealed:
            problems.append('%s is not listed in sealed/seal.json' % rel)
    return {'files': len(present), 'bytes': sum(p.stat().st_size for p in present.values()),
            'sealed': sealed, 'problems': problems, 'big': big}
