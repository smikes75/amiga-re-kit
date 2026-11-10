"""Scripted screenshots through the headless vAmiga (``VAHeadless``).

Builds a RetroShell script, runs the binary, converts the raw RGB24 frame
(716 x 285) to PNG. Times are emulator seconds from power-on, nothing is
assumed about the game. ``events`` is ``[(t_seconds, 'retroshell command')]``
- joystick / key presses that drive the game to the state you want to see.
RetroShell spells them ``joystick2 press 1`` / ``joystick2 unpress 1`` (port in the
name, button number), ``joystick2 pull left|right|up|down`` / ``joystick2 release x|y``,
``mouse1 press left|right``, ``mouse1 move dx=DX dy=DY`` (1.0.22: the counters by whole steps, negative = left / up;
key=value because RetroShell reads a bare ``-3`` as a flag),
``keyboard press KEYCODE`` (docs/HEADLESS.md).

Why ``denise set FRAME_SKIPPING 0``: in warp mode Denise swaps buffers only
every 17th frame, so the screenshot would lag the RAM state by up to 16
frames. With it off the texture is the last rendered frame.
"""
import os
import re
import subprocess
import tempfile
from pathlib import Path

from . import config

RAW_W, RAW_H = 716, 285


class HeadlessError(RuntimeError):
    pass


_SPACED = re.compile(r'^(joystick|mouse)\s+\d')
_NAMED_BUTTON = re.compile(r'^joystick\d\s+(press|unpress)\s+\D')
_MOUSE_MOVE = re.compile(r'^mouse\d\s+move\s+(.*)$')
_MOUSE_MOVE_OK = re.compile(r'^dx=-?\d+\s+dy=-?\d+$')


def check_event(cmd):
    """Refuse input spellings RetroShell rejects (the script would stop at that line)."""
    c = cmd.strip()
    if _SPACED.match(c):
        raise HeadlessError('%r: RetroShell writes the port into the name, e.g. "joystick2 press 1", '
                            '"mouse1 press left"' % cmd)
    if _NAMED_BUTTON.match(c):
        raise HeadlessError('%r: a joystick button is a number, e.g. "joystick2 press 1"' % cmd)
    m = _MOUSE_MOVE.match(cmd)
    if m and not _MOUSE_MOVE_OK.match(m.group(1).strip()):
        raise HeadlessError('%r: mouse movement is "mouse1 move dx=5 dy=-3" (key=value: RetroShell reads a bare -3 as a flag; kit 1.0.22, vamiga-mouse-899da5d.patch)' % cmd)
    return cmd


def check_disk(conf, adf):
    """The disk image must exist before the emulator is started (it only says
    "Unsupported file type")."""
    if not adf:
        raise config.ConfigError('no ADF (set ADF1 in local.conf)')
    if not os.path.isfile(adf):
        raise config.ConfigError('ADF does not exist: %s (relative paths in local.conf resolve against '
                                 'the directory of the conf file)' % adf)
    size = os.path.getsize(adf)
    if adf.lower().endswith('.adf') and size not in (901120, 1802240):
        raise config.ConfigError('%s has %d bytes; an ADF has 901120 (DD) or 1802240 (HD) - the emulator '
                                 'would say only "Unsupported file type"' % (adf, size))
    return adf


def build_script(conf, adf, events, t_shot, out_png, setup=()):
    lines = [
        'regression setup %s "%s"' % (conf.get('MACHINE', 'A500_OCS_1MB'), conf['ROM']),
        'amiga set WARP_MODE ALWAYS',
        'denise set FRAME_SKIPPING 0',
    ]
    lines += list(setup)
    lines.append('regression run "%s"' % adf)
    now = 0
    # 1.0.43: RetroShell waits in whole seconds ('wait %d' cut 2.5 to 2: the event came early, the run ended early, and
    # nothing said so; 'wait N frames' is not exact either, docs/HEADLESS.md). A time with a fraction is refused.
    for t in [t for t, _ in events] + [t_shot]:
        if t != int(t):
            raise HeadlessError('time %s: the emulator script waits in whole seconds - give a whole second (an event inside a '
                                'second is placed by a breakpoint or by a line of the inputs file, docs/HEADLESS.md)' % t)
    for t, cmd in sorted(events, key=lambda e: e[0]):
        if t > t_shot:
            break
        if t > now:
            lines.append('wait %d' % (t - now))
            now = t
        lines.append(check_event(cmd))
    if t_shot > now:
        lines.append('wait %d' % (t_shot - now))
    lines.append('screenshot save %s' % out_png)
    return '\n'.join(lines) + '\n'


def run_env(env=None):
    """The environment of an emulator run: the caller's, WITHOUT any VAHL_* variable it happens to export (1.0.39: a
    VAHL_INPUTS or VAHL_TRACE left over from a manual experiment silently changed every later measurement), plus
    the run's own ``env``."""
    return {**{k: v for k, v in os.environ.items() if not k.startswith('VAHL_')}, **(env or {})}


def run_script(conf, text, capture=False, env=None, timeout=600, log_path=None):
    """Run a RetroShell script; ``timeout`` in seconds of wall time (HeadlessError when exceeded). 1.0.39: the
    emulator's exit status is checked (HeadlessError with the end of its output), its output is always collected
    and, with ``log_path``, written there also when the run fails or times out."""
    config.require(conf, 'VAHL')
    fd, path = tempfile.mkstemp(prefix='arek', suffix='.retrosh')
    with os.fdopen(fd, 'w') as f:
        f.write(text)

    def keep(out):
        text = (out or b'').decode('utf-8', 'replace')
        if log_path:
            with open(log_path, 'w') as f:
                f.write(text)
        return text
    try:
        args = [conf['VAHL']] + (['-v'] if capture else []) + [path]
        p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout, env=run_env(env))
        log = keep(p.stdout)
        if p.returncode:
            raise HeadlessError('VAHeadless ended with status %d: %s%s\n%s' % (
                p.returncode, conf['VAHL'], ' (log: %s)' % log_path if log_path else '', log[-600:].strip()))
        return log if capture else ''
    except subprocess.TimeoutExpired as e:
        keep(e.stdout)
        raise HeadlessError('VAHeadless did not finish within %d s: %s (a build that hangs, or a '
                            'script waiting for input; see docs/HEADLESS.md%s)'
                            % (timeout, conf['VAHL'], '; log: %s' % log_path if log_path else '')) from None
    finally:
        os.unlink(path)


def write_png(path, width, height, rgb):
    """RGB24 bytes -> PNG with the standard library (no Pillow needed)."""
    import struct
    import zlib

    def chunk(kind, body):
        return (struct.pack('>I', len(body)) + kind + body
                + struct.pack('>I', zlib.crc32(kind + body) & 0xffffffff))
    stride = width * 3
    rows = b''.join(b'\0' + rgb[y * stride:(y + 1) * stride] for y in range(height))
    Path(path).write_bytes(b'\x89PNG\r\n\x1a\n'
                           + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
                           + chunk(b'IDAT', zlib.compress(rows, 6)) + chunk(b'IEND', b''))
    return path


def raw_to_png(raw, png):
    d = Path(raw).read_bytes()
    if len(d) != RAW_W * RAW_H * 3:
        raise HeadlessError('unexpected raw frame size %s: %d' % (raw, len(d)))
    return write_png(png, RAW_W, RAW_H, d)


def shot(conf, prefix, t, events=(), adf=None, setup=(), timeout=600):
    """Run the machine to second ``t`` and return the PNG path."""
    adf = check_disk(conf, adf or conf.get('ADF1'))
    config.require(conf, 'ROM', 'VAHL')
    prefix = os.path.abspath(prefix)
    os.makedirs(os.path.dirname(prefix), exist_ok=True)
    png = '%s_t%d.png' % (prefix, t)
    raw = '%s_t%d.raw' % (prefix, t)
    if os.path.exists(raw):
        os.unlink(raw)
    run_script(conf, build_script(conf, adf, list(events), t, png, setup), timeout=timeout)
    if not os.path.exists(raw):
        raise HeadlessError('VAHeadless produced no %s (check VAHL/ROM/ADF, run with -v)' % raw)
    return raw_to_png(raw, png)
