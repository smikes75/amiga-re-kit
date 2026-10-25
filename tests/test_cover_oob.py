"""recomp --cover (which translated instructions ran) and --oob zero (reads outside the modelled RAM)."""
import os
import shutil
import subprocess

import pytest

from arek import cli
from arek.m68k import cover, recomp

BASE = 0x1000
MEMSZ = 0x80000


def build_run(tmp_path, prog, auto, env=None, expect_rc=0, **gen):
    """Translate ``prog`` at BASE with the verification driver, run it on a zeroed RAM holding
    the program; return (log text, cover dict, return code)."""
    cc = shutil.which('cc') or shutil.which('gcc') or shutil.which('clang')
    if not cc:
        pytest.skip('no C compiler')
    cov = {}
    src, _, _ = recomp.generate(prog, BASE, auto=list(auto), with_main=True, cover=cov, **gen)
    c, exe = tmp_path / 'r.c', tmp_path / 'r'
    c.write_text(src)
    subprocess.run([cc, '-O1', '-o', str(exe), str(c)], check=True)
    ram = bytearray(MEMSZ)
    ram[BASE:BASE + len(prog)] = prog
    (tmp_path / 'ram.bin').write_bytes(ram)
    regs = ' '.join(['0'] * 15 + ['%x' % (MEMSZ - 0x100)])
    (tmp_path / 'regs.txt').write_text(regs + '\n0 0 0 0 0\nf_%06x\n' % BASE)
    log = tmp_path / 'log.txt'
    r = subprocess.run([str(exe), str(tmp_path / 'ram.bin'), str(tmp_path / 'regs.txt'), str(tmp_path / 'out.bin'), str(log)],
                       env={**os.environ, **(env or {})}, capture_output=True, text=True)
    assert r.returncode == expect_rc, r.stderr
    return (log.read_text() if log.exists() else ''), cov, r


# moveq #1,d0 ; rts            at 1000 (runs)
# moveq #2,d0 ; nop ; rts      at 1004 (translated, never called)
PROG = bytes.fromhex('7001 4e75 7002 4e71 4e75'.replace(' ', ''))


def test_cover_marks_what_ran(tmp_path):
    log, cov, _ = build_run(tmp_path, PROG, (BASE, BASE + 4), env={'AREK_COVER': str(tmp_path / 'run.cov')})
    assert cov['lo'] == BASE and cov['routines'] == {'1000': [[0x1000, 0x1002]], '1004': [[0x1004, 0x1008]]}
    ran = cover.read(tmp_path / 'run.cov')
    assert ran == {0x1000, 0x1002}
    r = cover.report(ran, cov)
    assert (r['instructions'], r['executed']) == (5, 2) and r['never'] == [0x1004]
    assert r['routines'][0]['addr'] == 0x1004 and r['routines'][0]['share'] == 0.0
    assert r['routines'][1] == {'addr': 0x1000, 'instructions': 2, 'executed': 2, 'share': 1.0}
    text = cover.format_report(r)
    assert '2 of 5 translated instructions ran (40.0 %), 1 routines never ran' in text and '001004' in text
    (tmp_path / 'side.json').write_text(__import__('json').dumps(cov))
    assert cli.main(['cover', str(tmp_path / 'run.cov'), str(tmp_path / 'side.json')]) == 0


def test_cover_with_timing_and_profile(tmp_path):
    log, cov, _ = build_run(tmp_path, PROG, (BASE, BASE + 4), env={'AREK_COVER': str(tmp_path / 'run.cov')},
                            timing=True, profile=True)
    assert cover.read(tmp_path / 'run.cov') == {0x1000, 0x1002} and 'cycles 20' in log


def test_cli_cover_writes_the_sidecar(tmp_path, capsys):
    (tmp_path / 'p.bin').write_bytes(PROG)
    out = tmp_path / 'p.c'
    assert cli.main(['recomp', str(tmp_path / 'p.bin'), '--base', '0x1000', '--auto', '0x1000', '--cover', '--out', str(out)]) == 0
    assert 'COV_MARK(0x1000u);' in out.read_text()
    side = __import__('json').loads((tmp_path / 'p.c.cover.json').read_text())
    assert side == {'lo': BASE, 'routines': {'1000': [[0x1000, 0x1002]]}}


# move.l $c00000,d0 ; move.w d0,$c00004 ; rts   - slow RAM is not modelled here
OOB = bytes.fromhex('2039 00c00000 33c0 00c00004 4e75'.replace(' ', ''))


def test_oob_stop_is_the_default(tmp_path):
    _, _, r = build_run(tmp_path, OOB, (BASE,), expect_rc=3)
    assert 'outside the modelled RAM' in r.stderr and '00c00000' in r.stderr


def test_oob_zero_reads_zero_and_drops_writes(tmp_path):
    log, _, r = build_run(tmp_path, OOB, (BASE,), oob='zero')
    assert log.splitlines()[0] == '00000000' and 'oob 6' in log      # 4 bytes read + 2 written
    assert r.stderr.count('outside the modelled RAM') == 1               # one note per KB
    with pytest.raises(ValueError):
        recomp.generate(OOB, BASE, auto=[BASE], oob='maybe')
