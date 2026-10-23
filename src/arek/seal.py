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

This is a lock, not a licence: the files are still derived from the original.
"""
import base64
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


def _b64(b):
    return base64.b64encode(b).decode()


def seal(files, disk_sets, content_key=None):
    """files: {path: bytes}; disk_sets: [[adf bytes, ...], ...] - each set that may open them.
    Returns (manifest, {path: sealed bytes})."""
    if not disk_sets or any(not s for s in disk_sets):
        raise ValueError('seal needs at least one set of disks')
    ck = content_key or os.urandom(32)
    aes = _aes(ck)
    manifest = {'seal': VERSION, 'files': [], 'keys': []}
    blobs = {}
    for path, data in files.items():
        iv = os.urandom(12)
        blobs[path] = aes.encrypt(iv, bytes(data), path.encode())
        manifest['files'].append({'path': path, 'iv': _b64(iv), 'size': len(data),
                                  'sha256': hashlib.sha256(data).hexdigest()})
    for disks in disk_sets:
        iv = os.urandom(12)
        manifest['keys'].append({'disks': [hashlib.sha256(bytes(d)).hexdigest() for d in disks], 'iv': _b64(iv),
                                 'wrapped': _b64(_aes(set_key(disks)).encrypt(iv, ck, KEY_AAD))})
    return manifest, blobs


def unseal(manifest, blobs, disks):
    """The plain files for ``disks`` (ValueError when no key entry takes them or a file was altered)."""
    from cryptography.exceptions import InvalidTag
    ids = [hashlib.sha256(bytes(d)).hexdigest() for d in disks]
    entry = next((k for k in manifest['keys'] if k['disks'] == ids), None)
    if entry is None:
        raise ValueError('no key for these disks (%s)' % ', '.join(i[:12] for i in ids))
    try:
        ck = _aes(set_key(disks)).decrypt(base64.b64decode(entry['iv']), base64.b64decode(entry['wrapped']), KEY_AAD)
        aes = _aes(ck)
        return {f['path']: aes.decrypt(base64.b64decode(f['iv']), blobs[f['path']], f['path'].encode())
                for f in manifest['files']}
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
