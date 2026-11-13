"""The web side of a rebuild: the reference files of the display and sound contracts, the shared menu, the
Workbench bar (wb-menu.js + wb.css), the
seal, the ATN! decruncher and the content key for a page, the touch controls (``arek web copy``), the payload of a
game's files for ``arek web seal --payload`` (``payload_atn``), a development server that serves a bundle with the
disks of local.conf (``arek web serve``, localhost only; ``--isolated`` adds the COOP/COEP headers an engine with
shared memory needs), the variant stripper (``arek web strip``: lines and blocks marked ``//@TAG`` for one build) and
the long-run smoothness check of a page (``arek web longrun``, playwright; the page's ``globalThis.WBLONGRUN`` hook)."""
import functools
import hashlib
import http.server
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = ('wb-obraz.js', 'wb-seal.js', 'wb-nastaveni.js', 'wb-zvuk.js', 'wb-atn.js', 'wb-bytekiller.js', 'wb-content.js', 'wb-touch.js', 'wb-takt.js', 'wb-zvuk-out.js', 'wb-zvuk-worklet.js', 'wb-scene.js', 'wb-scenerec.js', 'wb-datadisk.js', 'wb-menu.js', 'wb.css')
# the Workbench bar (1.0.17, Turrican II KIT-GAP 25): the games wrote these two first; a page's own copy is kept without an error
SHELL = ('wb-menu.js', 'wb.css')
CONTENT_KIND = 'arek-atn-files-1'
MANIFEST = 'wb-kit.json'


def _sha(path):
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def module_version(path):
    """The VERSION constant of a kit module (None: the file has none)."""
    with open(path, encoding='utf-8', errors='replace') as f:
        m = re.search(r"\b(?:VERSION|version)\s*[=:]\s*'([\d.]+)'", f.read())
    return m.group(1) if m else None


def manifest(dest):
    """``wb-kit.json`` of a folder ``arek web copy`` wrote into, or None (a copy made before 1.0.41)."""
    try:
        with open(os.path.join(dest, MANIFEST), encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def status(dest):
    """What the kit files in ``dest`` are against this kit: ``[(name, state, note)]`` with state ``current`` (the
    kit's file), ``stale`` (unchanged since it was copied from an older kit), ``modified`` (edited since it was
    copied - or, without wb-kit.json, simply not this kit's file), ``own`` (the page's own file under a kit name) or
    ``missing``. A game runs what is in its folder: this is how it learns that a module is behind or was changed."""
    from .. import __version__
    man = manifest(dest) or {}
    rows = []
    for name in FILES:
        path = os.path.join(dest, name)
        if not os.path.exists(path):
            rows.append((name, 'missing', ''))
            continue
        with open(path, 'rb') as f:
            head = f.read(4096)
        sha, rec = _sha(path), (man.get('files') or {}).get(name)
        if sha == _sha(os.path.join(HERE, name)):
            rows.append((name, 'current', 'kit %s' % __version__))
        elif b'amiga-re-kit' not in head:
            rows.append((name, 'own', "the page's own file"))
        elif rec and rec.get('sha256') == sha:
            rows.append((name, 'stale', 'from kit %s%s; this kit: %s' % (man.get('kit', '?'), ', module %s' % rec['version'] if rec.get('version') else '',
                                                                       module_version(os.path.join(HERE, name)) or __version__)))
        else:
            rows.append((name, 'modified', 'edited since kit %s copied it' % man['kit'] if rec else 'not the file of this kit, and no wb-kit.json says which kit it came from'))
    return rows


def copy(dest, force=False):
    """Copy the kit's web files into ``dest`` and write ``wb-kit.json`` (the kit version, per file its sha256 and
    module version). Returns ``{'copied': [(path, sha256)], 'kept': [...], 'own_bar': [...], 'edited': [...]}``: a
    file that is not the kit's (the page's own under a kit name) is kept, and so is a kit file that was edited since
    it was copied (1.0.41: it used to be overwritten without a word) - ``force`` replaces both."""
    import shutil
    from .. import __version__
    os.makedirs(dest, exist_ok=True)
    before = {name: state for name, state, _ in status(dest)}
    had_manifest = manifest(dest) is not None
    res = {'copied': [], 'kept': [], 'own_bar': [], 'edited': [], 'replaced_unknown': []}
    for name in FILES:
        out = os.path.join(dest, name)
        st = before[name]
        if st == 'own' and not force:
            res['own_bar' if name in SHELL else 'kept'].append(out)
            continue
        if st == 'modified' and had_manifest and not force:
            res['edited'].append(out)
            continue
        if st == 'modified' and not had_manifest:
            res['replaced_unknown'].append(out)
        shutil.copyfile(os.path.join(HERE, name), out)
        res['copied'].append((out, _sha(out)))
    files = {}
    for name in FILES:
        out = os.path.join(dest, name)
        if os.path.exists(out) and _sha(out) == _sha(os.path.join(HERE, name)):
            files[name] = {'sha256': _sha(out), 'version': module_version(out)}
    old = manifest(dest) or {}
    for name, rec in (old.get('files') or {}).items():          # a file kept as it was stays on record with the kit it came from
        if name not in files and name in FILES and os.path.exists(os.path.join(dest, name)):
            files[name] = dict(rec, kit=rec.get('kit', old.get('kit')))
    with open(os.path.join(dest, MANIFEST), 'w', encoding='utf-8') as f:
        json.dump({'kit': __version__, 'files': files}, f, indent=1, sort_keys=True)
        f.write('\n')
    return res


def payload_atn(blocks, conf=None):
    """The game's content for the payload key from ATN! blocks on the disks: ``blocks`` = [(disk, offset)] where
    disk is a path or a local.conf key (``ADF1``). Returns ``(payload bytes, content dict)``: the unpacked files
    joined in this order, and ``{"content": "arek-atn-files-1", "files": [{"size", "sha256"}]}`` for the page
    (``wb-content.js`` finds the same files on any disk version by size and hash). The payload goes to
    ``arek web seal --payload`` and never into a bundle; the content dict holds no game data."""
    from ..packers import atomik
    parts, files, cache = [], [], {}
    for disk, off in blocks:
        path = conf[disk] if conf and disk in conf else disk
        if path not in cache:
            with open(path, 'rb') as f:
                cache[path] = f.read()
        data = atomik.unpack(cache[path][off:])
        parts.append(data)
        files.append({'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
    return b''.join(parts), {'content': CONTENT_KIND, 'files': files}


def parse_block(spec):
    """``DISK:OFFSET`` (offset hex with 0x or decimal) -> (disk, offset)."""
    disk, _, off = spec.rpartition(':')
    if not disk:
        raise ValueError('block spec DISK:OFFSET, e.g. ADF1:0x57800 - got %r' % spec)
    return disk, int(off, 0)


class _Handler(http.server.SimpleHTTPRequestHandler):
    disks = {}
    isolated = False

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        if self.isolated:                                     # cross-origin isolation: SharedArrayBuffer, pthreads
            self.send_header('Cross-Origin-Opener-Policy', 'same-origin')
            self.send_header('Cross-Origin-Embedder-Policy', 'require-corp')
        super().end_headers()

    def do_GET(self):
        path = self.path.split('?')[0]
        if path in self.disks:
            with open(self.disks[path], 'rb') as f:
                data = f.read()
            self.send_response(200)
            self.send_header('Content-Type', 'application/octet-stream')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        return super().do_GET()

    def log_message(self, *a):
        pass


class Server(http.server.ThreadingHTTPServer):
    """The development server of `arek web serve` / `web demo` (1.0.18, Turrican II KIT-GAP 26): a listen backlog of 128
    instead of socketserver's 5 - a page with ~20 scripts and styles opens them at once, and on macOS / Chromium the
    sixth connection got ERR_CONNECTION_RESET (a script missing, `arek web smooth` timing out)."""
    request_queue_size = 128
    daemon_threads = True


def serve(site, port=8930, conf=None, host='127.0.0.1', isolated=False):
    """A server for a bundle folder that also serves the disks of ``conf`` (local.conf) as
    ``/local-disks/disk1.adf``, ``disk2.adf``, ... (keys ADF1, ADF2, ...), on localhost only, so a page can load
    the game without a file dialog while developing; ``isolated``: the COOP / COEP headers (an engine with shared
    memory - a static host like GitHub Pages sends none, so a bundle should not need them). Returns the server
    (``serve_forever`` to run it; ``server_address`` holds the port when 0 was given)."""
    disks = {}
    for k in sorted(conf or {}):
        if k.startswith('ADF') and k[3:].isdigit() and conf[k]:
            disks['/local-disks/disk%s.adf' % k[3:]] = conf[k]
    handler = type('Handler', (_Handler,), {'disks': disks, 'isolated': isolated})
    srv = Server((host, port), functools.partial(handler, directory=str(site)))
    srv.disks = disks
    return srv


STRIP_OPEN = re.compile(r'(?://@(\w+)\{|<!--@(\w+)\{-->)$')
STRIP_CLOSE = re.compile(r'(?://@\}(\w+)|<!--@\}(\w+)-->)$')
STRIP_LINE = re.compile(r'\s*(?://@(\w+)|<!--@(\w+)-->)$')


def strip(text, drop=('FULL',)):
    """One variant of a page's source: a line ending in ``//@TAG`` and a block between ``//@TAG{`` and ``//@}TAG``
    lines belong to variant TAG; the variants in ``drop`` are cut out at once, the markers of the others vanish
    (``arek web strip IN OUT --drop FULL --drop DEV``: the presentation without the full game's and the debug lines;
    the markers are gone after one pass, so every variant to drop goes into that one pass - Alien Breed II G51).
    0.8.6: HTML too - ``<!--@TAG-->`` at a line's end, ``<!--@TAG{-->`` ... ``<!--@}TAG-->`` blocks."""
    out, skip = [], None
    for line in text.split('\n'):
        t = line.strip()
        m = STRIP_OPEN.match(t)
        if m and skip is None:
            if (m.group(1) or m.group(2)) in drop:
                skip = m.group(1) or m.group(2)
            continue
        m = STRIP_CLOSE.match(t)
        if m:
            if skip == (m.group(1) or m.group(2)):
                skip = None
            continue
        if skip is not None:
            continue
        m = STRIP_LINE.search(line.rstrip())
        if m:
            if (m.group(1) or m.group(2)) in drop:
                continue
            line = line.rstrip()[:m.start()]
        out.append(line)
    return '\n'.join(out)


LONGRUN_SAMPLE_JS = """(ms) => new Promise((res) => { const out = []; const t0 = performance.now();
    const f = (ts) => { out.push([ts, ...(globalThis.WBLONGRUN.cam ? WBLONGRUN.cam() : [0, 0])]);
        if (performance.now() - t0 < ms) requestAnimationFrame(f); else res(out); };
    requestAnimationFrame(f); })"""


def longrun(url, minutes=3.0, interval=30.0, sample=3.0, keys=('ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'),
            seed=1, viewport=(1280, 800), timeout=30000):
    """Smoothness of a page over a longer play (playwright, Chromium): random keys held, every ``interval`` s a
    sample of ``sample`` s of requestAnimationFrame timestamps and the camera of the page's hook
    ``globalThis.WBLONGRUN = { ready() -> bool, cam() -> [x, y] (game pixels), status() -> text (optional) }``.
    Yields dicts per sample: ``t`` (s), ``frames``, ``late`` (intervals over 20 ms), ``max_ms``, ``step`` (mean camera
    step of the moving frames), ``jitter`` (its deviation), ``heap_mb`` (-1 without performance.memory), ``status``."""
    import random
    import time
    from playwright.sync_api import sync_playwright
    rng = random.Random(seed)
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={'width': viewport[0], 'height': viewport[1]})
        pg.goto(url)
        pg.wait_for_function('globalThis.WBLONGRUN && (!WBLONGRUN.ready || WBLONGRUN.ready())', timeout=timeout)
        pg.mouse.click(viewport[0] // 2, viewport[1] // 2)
        t0 = time.time()
        held, nxt = None, 0.0
        try:
            while time.time() - t0 < minutes * 60:
                if held:
                    pg.keyboard.up(held)
                held = rng.choice(list(keys))
                pg.keyboard.down(held)
                if time.time() - t0 >= nxt:
                    d = pg.evaluate(LONGRUN_SAMPLE_JS, sample * 1000)
                    dt = [y[0] - x[0] for x, y in zip(d, d[1:])]
                    st = [max(abs(y[1] - x[1]), abs(y[2] - x[2])) for x, y in zip(d, d[1:])]
                    mv = [x for x in st if 0 < x < 8]
                    mean = sum(mv) / len(mv) if mv else 0.0
                    dev = (sum((x - mean) ** 2 for x in mv) / len(mv)) ** .5 if mv else 0.0
                    heap = pg.evaluate('performance.memory ? Math.round(performance.memory.usedJSHeapSize / 1e6) : -1')
                    status = pg.evaluate('globalThis.WBLONGRUN.status ? String(WBLONGRUN.status()) : ""')
                    yield {'t': time.time() - t0, 'frames': len(d), 'late': sum(1 for x in dt if x > 20), 'max_ms': max(dt) if dt else 0.0,
                           'step': mean, 'jitter': dev, 'heap_mb': heap, 'status': status}
                    nxt += interval
                else:
                    time.sleep(0.4)
        finally:
            b.close()


def format_longrun(row):
    return '%4.0f s: frames %d, intervals >20 ms %d, max %.1f ms, step %.2f dev %.2f, heap %s MB%s' % (
        row['t'], row['frames'], row['late'], row['max_ms'], row['step'], row['jitter'], row['heap_mb'], (', ' + row['status']) if row['status'] else '')
