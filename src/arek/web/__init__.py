"""The web side of a rebuild: the reference files of the display and sound contracts, the shared menu, the
seal, the ATN! decruncher and the content key for a page (``arek web copy``), the payload of a game's files for
``arek web seal --payload`` (``payload_atn``), and a development server that serves a bundle with the disks of
local.conf (``arek web serve``, localhost only)."""
import functools
import hashlib
import http.server
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = ('wb-obraz.js', 'wb-seal.js', 'wb-nastaveni.js', 'wb-zvuk.js', 'wb-atn.js', 'wb-content.js')
CONTENT_KIND = 'arek-atn-files-1'


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

    def do_GET(self):
        path = self.path.split('?')[0]
        if path in self.disks:
            with open(self.disks[path], 'rb') as f:
                data = f.read()
            self.send_response(200)
            self.send_header('Content-Type', 'application/octet-stream')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(data)
            return
        return super().do_GET()

    def log_message(self, *a):
        pass


def serve(site, port=8930, conf=None, host='127.0.0.1'):
    """A server for a bundle folder that also serves the disks of ``conf`` (local.conf) as
    ``/local-disks/disk1.adf``, ``disk2.adf``, ... (keys ADF1, ADF2, ...), on localhost only, so a page can load
    the game without a file dialog while developing. Returns the server (``serve_forever`` to run it)."""
    disks = {}
    for k in sorted(conf or {}):
        if k.startswith('ADF') and k[3:].isdigit() and conf[k]:
            disks['/local-disks/disk%s.adf' % k[3:]] = conf[k]
    handler = type('Handler', (_Handler,), {'disks': disks})
    srv = http.server.ThreadingHTTPServer((host, port), functools.partial(handler, directory=str(site)))
    srv.disks = disks
    return srv
