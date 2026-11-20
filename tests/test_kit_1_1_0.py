"""1.1.0 (JUMP-amiga's KIT-GAPs 3 and 4 and its small ones): pictures compared by their bytes first, FNV-1a 64 in C
with the same value, the rebuild's sound frames after the original's log not counted and "until", a step in
--shot-frames, a pipe closed early."""
import os
import subprocess
import sys

from arek import parity
from arek.headless import trace


def test_equal_pictures_by_their_bytes_and_a_differing_row():
    w, h = 16, 8
    a = (bytes(range(256)) * 2)[:w * h * 3]
    assert parity.diff_shots(a, a, width=w) == (0, None)
    b = bytearray(a); b[(3 * w + 5) * 3] ^= 0xff
    assert parity.diff_shots(a, bytes(b), width=w) == (1, (5, 3, 5, 3))
    assert parity.diff_shots(a, bytes(b), tolerance=255, width=w) == (0, None)   # the tolerance as before


def test_fnv_native_is_the_python_hash():
    for n in (0, 1, 1023, 1024, 4097, 70000):
        d = os.urandom(n)
        assert trace.fnv1a64(d) == trace.fnv1a64(d, native=False)
    assert trace.fnv1a64(bytearray(b'\x00' * 5000)) == trace.fnv1a64(b'\x00' * 5000, native=False)
    assert trace.fnv1a64(b'') == 0xcbf29ce484222325


def _log(path, rows):
    open(path, 'wb').write(trace.encode_reglog([{'frame': f, 'v': v, 'h': 10, 'reg': reg, 'value': val, 'pc': 0, 'agnus': False}
                                                for f, v, reg, val in rows]))


def test_sound_after_the_originals_log_and_until(tmp_path):
    o, r = str(tmp_path / 'o.reg'), str(tmp_path / 'r.reg')
    same = [(f, 50, 0x0a8, f) for f in range(10, 20)]
    _log(o, same + [(20, 30, 0x180, 0)])                       # the original's log ends early in frame 20 (a colour write)
    _log(r, same + [(20, 40, 0x180, 0), (21, 50, 0x0a8, 21), (22, 50, 0x0a8, 22)])   # the rebuild ran on
    s = parity.compare_audio(o, r, range(0, 1))
    assert (s['frames'], s['equal'], s['beyond'], s['short']) == (10, 10, 2, 0), s
    _log(r, same[:5] + [(f, 50, 0x0a8, 99) for f in range(15, 20)])
    s = parity.compare_audio(o, r, range(0, 1), until=14)       # frames 15 .. differ, compared up to 14 only
    assert (s['frames'], s['equal']) == (5, 5), s
    assert parity.compare_audio(o, r, range(0, 1))['equal'] == 5


def test_shot_frames_with_a_step():
    assert trace.shot_windows('100:110:5') == [(100, 100), (105, 105), (110, 110)]
    assert trace.shot_windows('100:110:5,200') == [(100, 100), (105, 105), (110, 110), (200, 200)]
    assert trace.shot_windows('100:110:5', step=False) == [(100, 110)]
    assert trace.shot_windows('1:3') == [(1, 3)] and trace.shot_windows((4, 9)) == [(4, 9)]
    e = trace.env('/tmp/x.vtr', shots='/tmp/x', shot_frames='0:1000:10')
    assert e.get('VAHL_SHOTS_FRAMES') == '0:1000' and 'VAHL_SHOTS_LIST' not in e   # 101 frames > 64 windows: the whole window, the rest deleted after
    e = trace.env('/tmp/x.vtr', shots='/tmp/x', shot_frames='0:100:50')
    assert e.get('VAHL_SHOTS_LIST') == '0:0,50:50,100:100'


def test_a_pipe_closed_early_prints_no_error():
    code = "import sys; sys.argv = ['arek', 'docs', 'HOST']; from arek import cli; raise SystemExit(cli.main(['docs', 'HOST']))"
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(p for p in sys.path if p))
    p = subprocess.Popen([sys.executable, '-c', code], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    p.stdout.read(5); p.stdout.close()
    err = p.stderr.read().decode()
    assert p.wait() == 0 and 'BrokenPipe' not in err, err
