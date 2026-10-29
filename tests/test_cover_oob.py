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


def test_cover_in_tick_keeps_bodies_and_marks(tmp_path):
    cov = {}
    plain, _, _ = recomp.generate(PROG, BASE, auto=[BASE, BASE + 4], with_main=True, timing=True)
    src, _, _ = recomp.generate(PROG, BASE, auto=[BASE, BASE + 4], with_main=True, timing=True, cover=cov, cover_in_tick=True)
    assert 'COV_MARK(0x1000u);' not in src and '#define COV_TICK(pc) cov_mark(pc)' in src
    # every line of the plain translation's bodies is in the covered one, unchanged
    bodies = [l for l in plain.splitlines() if l.startswith('L00') or l.startswith('    ')]
    assert all(l in src for l in bodies)
    log, cov, _ = build_run(tmp_path, PROG, (BASE, BASE + 4), env={'AREK_COVER': str(tmp_path / 'run.cov')},
                            timing=True, cover_in_tick=True)
    assert cover.read(tmp_path / 'run.cov') == {0x1000, 0x1002}


def test_cover_union_of_runs_cli(tmp_path, capsys):
    (tmp_path / 'a.cov').write_text('H 1000 5\n1000-1000\n')
    (tmp_path / 'b.cov').write_text('H 1000 5\n1004-1006\n')
    assert cover.read([tmp_path / 'a.cov', tmp_path / 'b.cov']) == {0x1000, 0x1004, 0x1006}
    side = {'lo': BASE, 'routines': {'1000': [[0x1000, 0x1002]], '1004': [[0x1004, 0x1008]]}}
    (tmp_path / 'p.c.cover.json').write_text(__import__('json').dumps(side))
    assert cli.main(['cover', str(tmp_path / 'a.cov'), str(tmp_path / 'b.cov'), str(tmp_path / 'p.c.cover.json')]) == 0
    assert '3 of 5 translated instructions ran' in capsys.readouterr().out


# G48 (Alien Breed II): movea.l #$32000400,a0 ; move.w #$1234,(a0) ; move.w $80400,d0 ; swap d0 ; move.w $180400,d0 ; rts
MIRROR = bytes.fromhex('207c32000400 30bc1234 303900080400 4840 303900180400 4e75'.replace(' ', ''))
# move.w $2800a8,d0 ; rts  - unmapped on an A500 (24-bit $2800A8)
UNMAPPED = bytes.fromhex('3039002800a8 4e75'.replace(' ', ''))


def test_24_bit_addresses_and_chip_mirrors(tmp_path):
    """The 68000 ignores the top address byte, and 512K chip RAM repeats up to $1FFFFF: a write through $32000400 lands at
    $400 and reads back at $80400 and $180400 (the debris of Alien Breed II's level 15 read such addresses)."""
    log, _, r = build_run(tmp_path, MIRROR, (BASE,))
    assert log.splitlines()[0] == '12341234' and 'outside' not in r.stderr


def test_unmapped_reads_the_oob_value_and_never_exits_in_a_browser(tmp_path):
    log, _, r = build_run(tmp_path, UNMAPPED, (BASE,), oob='zero')
    assert log.splitlines()[0] == '00000000' and '002800a8' in r.stderr
    _, _, r = build_run(tmp_path, UNMAPPED, (BASE,), expect_rc=3)                # natively the default still stops
    src, _, _ = recomp.generate(UNMAPPED, BASE, auto=[BASE])
    assert '#if OOB_ZERO || defined(__EMSCRIPTEN__)' in src and '#define CHIP_MIRROR 0x200000u' in src
    assert 'if (n >= 64) return;' in src                                          # the log stops after 64 lines
