"""arek edges (kit 1.0.84, SWIV): the constants of a translation in a range of values, each shifted by a knob of one build
(arek recomp --flow-file / --immediates), the scenario run per executed candidate against the baseline. Synthetic
programs only."""
import json
import shutil
from pathlib import Path
import subprocess
import sys

import pytest

from arek import cli, edges
from arek.m68k import recomp

# move.w #300,d1 / cmpi.w #256,d1 / bcs.s +4 / move.w #1,d2 / move.w #200,d3 / tst.w d1 / bne.s +4 / move.w #250,d5 / (rts)
PROG = '323c012c' + '0c410100' + '6504' + '343c0001' + '363c00c8' + '4a41' + '6604' + '3a3c00fa'

BUILD = r'''
import json, subprocess, sys
from pathlib import Path
from arek.m68k import recomp
here = Path(sys.argv[1]); prog = bytes.fromhex(sys.argv[2] + '4e75')
hook, operand, declare = recomp.flow_file(here / 'edges/flow.txt')
flow = recomp.flow_from_specs(prog, 0x1000, hook=hook, operand=operand, declare=declare)
imms = []
src, _, _ = recomp.generate(prog, 0x1000, auto=[0x1000], with_main=True, flow=flow, immediates=imms)
(here / 'edges/immediates.json').write_text(json.dumps(imms))
(here / 'r.c').write_text(src)
subprocess.run(['cc', '-O1', '-w', '-o', str(here / 'r'), str(here / 'r.c')], check=True)
ram = bytearray(0x80000); ram[0x1000:0x1000 + len(prog)] = prog
(here / 'ram.bin').write_bytes(ram)
(here / 'regs.txt').write_text(' '.join(['0'] * 15 + ['%x' % (0x80000 - 0x100)]) + '\n0 0 0 0 0\nf_001000\n')
'''
RUN = r'''
import subprocess, sys
from pathlib import Path
here, d = Path(sys.argv[1]).resolve(), Path(sys.argv[2])
subprocess.run([str(here / 'r'), str(here / 'ram.bin'), str(here / 'regs.txt'), str(d / 'out.bin'), str(d / 'log.txt')], check=True)
rows = (d / 'log.txt').read_text().split('\n')
print('d3 %d' % int(rows[3], 16))
print('d2 %d' % int(rows[2], 16))
'''


def test_the_translation_lists_its_constants_and_reads_a_flow_file(tmp_path):
    """--immediates: every translated instruction with a constant source (an <ea> immediate and an addi / cmpi form), its
    size, unsigned and signed value; the never-reached code after a branch is translated, the code past the end is not.
    --flow-file: operand / hook / declare lines, comments and blank lines skipped, anything else refused."""
    prog = bytes.fromhex(PROG + '4e75')
    imms = []
    recomp.generate(prog, 0x1000, auto=[0x1000], with_main=True, immediates=imms)
    assert [(r['addr'], r['mn'], r['size'], r['imm']) for r in imms] == [
        ('001000', 'move', 2, 300), ('001004', 'cmpi', 2, 256), ('00100a', 'move', 2, 1), ('00100e', 'move', 2, 200), ('001016', 'move', 2, 250)]
    imms = []
    recomp.generate(bytes.fromhex('0641fff0' + '4e75'), 0x1000, auto=[0x1000], immediates=imms)
    assert imms[0]['imm'] == 0xfff0 and imms[0]['simm'] == -16 and imms[0]['text'].startswith('addi.w')
    f = tmp_path / 'flow.txt'
    f.write_text('# changes\n\noperand 1004=(256 + band())\nhook 100a=my_hook:after\ndeclare static uint32_t band(void) { return 0; }\n'
                 '  declare #include <stdio.h>\n')
    assert recomp.flow_file(f) == (['100a=my_hook:after'], ['1004=(256 + band())'], ['static uint32_t band(void) { return 0; }', '#include <stdio.h>'])
    f.write_text('patch 1004=1\n')
    with pytest.raises(ValueError, match='flow.txt:1'):
        recomp.flow_file(f)


def test_candidates_and_the_flow_lines():
    imms = [{'addr': '001004', 'text': 'cmpi.w #256,d1', 'mn': 'cmpi', 'size': 2, 'imm': 256, 'simm': 256},   # meets d1: its range is kept
            {'addr': '001012', 'text': 'addi.w #-300,d1', 'mn': 'addi', 'size': 2, 'imm': 0xfed4, 'simm': -300},
            {'addr': '001020', 'text': 'move.w #250,d5', 'mn': 'move', 'size': 2, 'imm': 250, 'simm': 250},
            {'addr': '001030', 'text': 'move.w #4,d5', 'mn': 'move', 'size': 2, 'imm': 4, 'simm': 4}]
    assert [c['addr'] for c in edges.candidates(imms, 200, 340)] == ['001004', '001020']
    assert [c['addr'] for c in edges.candidates(imms, -340, -200)] == ['001012']                       # signed
    assert [c['addr'] for c in edges.candidates(imms, 200, 340, mn={'cmpi'})] == ['001004']
    assert [c['addr'] for c in edges.candidates(imms, 200, 340, exclude=['1004'])] == ['001020']
    t = edges.flow_lines(edges.candidates(imms, 200, 340))
    assert 'operand 001004=(0x100u + (uint32_t)arek_knob_d(0, (int32_t)(int16_t)m->d[1]))' in t and 'operand 001020=(0xfau + (uint32_t)arek_knob(1))' in t
    assert t.count('\ndeclare ') == len(edges.runtime(2)) and 'arek_knob_v[2]' in t


def test_a_scenario_per_candidate_finds_the_constant_that_decides(tmp_path, capsys):
    """The real loop on a synthetic program: the build lists 5 constants, 4 lie in 200..340 (move #300, cmpi #256, move
    #200 and move #250 behind a branch never taken); the baseline reads 3 of them; at +64 only the cmpi changes the outcome
    (d2); the move #200 changes a metric (d3) and not the outcome, the move #300 neither; the unexecuted one is reported,
    not run."""
    if not shutil.which('cc'):
        pytest.skip('no C compiler')
    (tmp_path / 'build.py').write_text(BUILD)
    (tmp_path / 'run.py').write_text(RUN)
    py = shlex_quote(sys.executable)
    conf = {'build': '%s build.py . %s' % (py, PROG), 'run': '%s run.py . {dir}' % py, 'values': [200, 340], 'shift': 64,
            'outcome': '^d2 .*$', 'metrics': {'d3': r'^d3 (\d+)'}, 'jobs': 2,
            'scenario': {'env': {'PYTHONPATH': str(Path(recomp.__file__).parents[2])}}}       # the kit under test in the project's commands
    (tmp_path / 'EDGES.json').write_text(json.dumps(conf))
    rep = edges.Project(tmp_path / 'EDGES.json').scan(log=lambda *a: None)
    assert rep['immediates'] == 5 and rep['candidates'] == 4 and rep['executed'] == 3 and rep['unexecuted'] == ['001016']
    assert rep['base']['outcome'] == 'd2 1' and rep['base']['metrics'] == {'d3': 200.0}
    runs = {r['addr']: r for r in rep['runs']}
    assert runs['001004']['changed'] and runs['001004']['outcome'] == 'd2 0' and runs['001004']['reads'] == 1
    assert runs['001004']['other'] == [300, 300] and runs['00100e']['other'] is None                   # cmpi #256 meets d1 = 300
    assert runs['001004']['place'] == 'screen' and runs['00100e']['place'] is None
    assert not runs['00100e']['changed'] and runs['00100e']['metrics'] == {'d3': 264.0} and not runs['001000']['changed']
    assert rep['runs'][0]['addr'] == '001004'                                                          # the changed first
    assert json.loads((tmp_path / 'edges/runs/report.json').read_text())['executed'] == 3
    text = edges.format_report(rep)
    assert '001004 CHANGED' in text and 'meets 300..300 screen' in text and '00100e same' in text and 'd3 264.0' in text and '1 of 3 executed candidates change' in text
    assert cli.main(['edges', str(tmp_path / 'EDGES.json'), '--list']) == 0
    assert '4 candidates of 5 constants' in capsys.readouterr().out
    assert cli.main(['edges', str(tmp_path / 'EDGES.json'), '--only', '1004', '--shift', '-100', '--json']) == 0
    r = json.loads(capsys.readouterr().out)
    assert r['candidates'] == 1 and r['runs'][0]['addr'] == '001004' and not r['runs'][0]['changed']   # 156: 300 >= 156, still d2 1


def shlex_quote(s):
    import shlex
    return shlex.quote(s)


def test_place_sorts_the_met_range():
    """1.0.85: SWIV $14F1E addi.w #256,d7 met the camera (-6614..-6048) and was read as no screen edge; it is the bullets'
    deletion line 256 below the camera."""
    assert edges.place(256, [-48, 327]) == 'screen' and edges.place(288, [32, 298]) == 'screen'
    assert edges.place(256, [-6614, -6048]) == 'world' and edges.place(256, [7000, 9000]) == 'world'
    assert edges.place(256, [0, 2500]) == 'wide' and edges.place(-256, [-6614, 100]) == 'wide'
    assert edges.place(256, None) is None
