"""Scripted screenshots through the headless vAmiga (``VAHeadless``).

Builds a RetroShell script, runs the binary, converts the raw RGB24 frame
(716 x 285) to PNG. Times are emulator seconds from power-on, nothing is
assumed about the game. ``events`` is ``[(t_seconds, 'retroshell command')]``
- joystick / key presses that drive the game to the state you want to see.

Why ``denise set FRAME_SKIPPING 0``: in warp mode Denise swaps buffers only
every 17th frame, so the screenshot would lag the RAM state by up to 16
frames. With it off the texture is the last rendered frame.
"""
import os
import subprocess
import tempfile
from pathlib import Path

from . import config

RAW_W, RAW_H = 716, 285


class HeadlessError(RuntimeError):
    pass


def build_script(conf, adf, events, t_shot, out_png, setup=()):
    lines = [
        'regression setup %s "%s"' % (conf.get('MACHINE', 'A500_OCS_1MB'), conf['ROM']),
        'amiga set WARP_MODE ALWAYS',
        'denise set FRAME_SKIPPING 0',
    ]
    lines += list(setup)
    lines.append('regression run "%s"' % adf)
    now = 0
    for t, cmd in sorted(events, key=lambda e: e[0]):
        if t > t_shot:
            break
        if t > now:
            lines.append('wait %d' % (t - now))
            now = t
        lines.append(cmd)
    if t_shot > now:
        lines.append('wait %d' % (t_shot - now))
    lines.append('screenshot save %s' % out_png)
    return '\n'.join(lines) + '\n'


def run_script(conf, text, capture=False, env=None, timeout=600):
    config.require(conf, 'VAHL')
    fd, path = tempfile.mkstemp(prefix='arek', suffix='.retrosh')
    with os.fdopen(fd, 'w') as f:
        f.write(text)
    try:
        args = [conf['VAHL']] + (['-v'] if capture else []) + [path]
        p = subprocess.run(args, stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                           stderr=subprocess.STDOUT if capture else subprocess.DEVNULL,
                           timeout=timeout, env={**os.environ, **(env or {})})
        return p.stdout.decode('utf-8', 'replace') if capture else ''
    finally:
        os.unlink(path)


def raw_to_png(raw, png):
    try:
        from PIL import Image
    except ImportError as e:
        raise HeadlessError('Pillow is needed for PNG output (pip install amiga-re-kit[png])') from e
    d = Path(raw).read_bytes()
    if len(d) != RAW_W * RAW_H * 3:
        raise HeadlessError('unexpected raw frame size %s: %d' % (raw, len(d)))
    Image.frombytes('RGB', (RAW_W, RAW_H), d).save(png)
    return png


def shot(conf, prefix, t, events=(), adf=None, setup=()):
    """Run the machine to second ``t`` and return the PNG path."""
    adf = adf or conf.get('ADF1')
    if not adf or not os.path.isfile(adf):
        raise config.ConfigError('no ADF (set ADF1 in local.conf)')
    config.require(conf, 'ROM', 'VAHL')
    prefix = os.path.abspath(prefix)
    os.makedirs(os.path.dirname(prefix), exist_ok=True)
    png = '%s_t%d.png' % (prefix, t)
    raw = '%s_t%d.raw' % (prefix, t)
    if os.path.exists(raw):
        os.unlink(raw)
    run_script(conf, build_script(conf, adf, list(events), t, png, setup))
    if not os.path.exists(raw):
        raise HeadlessError('VAHeadless produced no %s (check VAHL/ROM/ADF, run with -v)' % raw)
    return raw_to_png(raw, png)
