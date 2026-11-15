"""arek discover (kit 1.0.81): the record of the first run-time target the translation does not know (-DAREK_DISCOVER) -
a routine (exit 40) or an overlay module (exit 41, its area dumped) - as one JSON line in $AREK_UNKNOWN, with the
coverage written first. Synthetic programs only."""
import json
import subprocess

import pytest

from arek.m68k.decoder import Flow

from test_overlays import MAIN, MAIN_FLOW, MOD_A, MOD_X, module
from test_recomp_semantics import run


def test_an_unknown_routine_is_one_record_and_exit_40(tmp_path):
    """jsr (a0) (dynamic) to $1010, which the translation does not have: the record names the target and the routine
    that met it; the coverage up to there is written; without -DAREK_DISCOVER the old message and exit 4 stay."""
    rec, cov = tmp_path / 'unknown.jsonl', tmp_path / 'cover.txt'
    with pytest.raises(subprocess.CalledProcessError) as e:
        run(tmp_path, MAIN, {}, auto=(0x1000,), flow=MAIN_FLOW, ram_init={0x2000: MOD_A}, pre_c='#define AREK_DISCOVER 1\n',
            extra_c='\n' + module(MOD_A, 'ovA_'), cover={}, env={'AREK_UNKNOWN': str(rec), 'AREK_COVER': str(cov)})
    assert e.value.returncode == 40
    r = [json.loads(x) for x in rec.read_text().splitlines()]
    assert len(r) == 1 and r[0]['kind'] == 'routine' and r[0]['target'] == '001010' and r[0]['fn'] == 'call_addr'
    assert r[0]['line'] > 0 and r[0]['file'].endswith('r.c')
    ran = cov.read_text().splitlines()
    assert ran[0].startswith('H 1000') and any(x.startswith('1000-') for x in ran[1:])
    with pytest.raises(subprocess.CalledProcessError) as e:
        run(tmp_path, MAIN, {}, auto=(0x1000,), flow=MAIN_FLOW, ram_init={0x2000: MOD_A}, extra_c='\n' + module(MOD_A, 'ovA_'))
    assert e.value.returncode == 4


def test_an_unknown_module_is_dumped_and_exit_41(tmp_path):
    """The overlay area holds a module nobody registered: its area as the RAM holds it goes beside the record, with the
    base, the size, the entry, the key and the fingerprint the translation would register it by."""
    from arek.headless.trace import fnv1a64
    rec = tmp_path / 'unknown.jsonl'
    with pytest.raises(subprocess.CalledProcessError) as e:
        run(tmp_path, MAIN, {}, auto=(0x1000, 0x1010), flow=MAIN_FLOW, ram_init={0x2000: MOD_X}, pre_c='#define AREK_DISCOVER 1\n',
            extra_c='\n' + module(MOD_A, 'ovA_'), env={'AREK_UNKNOWN': str(rec)})
    assert e.value.returncode == 41
    r = json.loads(rec.read_text())
    assert r['kind'] == 'module' and r['base'] == '002000' and r['size'] == '100' and r['entry'] == '002000' and r['key'] == 4
    assert r['fp'] == '%016x' % fnv1a64(MOD_X)
    d = (tmp_path / r['dump'].split('/')[-1]).read_bytes()
    assert len(d) == 0x100 and d[:4] == MOD_X


def test_discover_keeps_the_generated_text_of_the_call_sites():
    """Only the runtime's preamble and overlay_call gain the discover block: the call sites' text is the same (projects
    patch the generated C by its text)."""
    from arek.m68k import recomp
    from test_recomp_semantics import BASE
    src, _, _ = recomp.generate(bytes.fromhex(MAIN), 0x1000, auto=[0x1000], with_main=True, flow=MAIN_FLOW)
    assert 'unknown_call(a);' in src and 'static void unknown_call(uint32_t a) { fprintf(stderr, "unknown routine %06x\\n", a); exit(4); }' in src
    assert src.count('#ifdef AREK_DISCOVER') == 3 and BASE


BUILD = r'''
import json, subprocess, sys
from pathlib import Path
from arek.m68k import recomp
from arek.m68k.decoder import Flow
here = Path(sys.argv[1])
prog = bytes.fromhex(sys.argv[2] + '4e75')
roots = [int(x.split('#')[0], 16) for x in (here / 'discover/roots.txt').read_text().splitlines() if x.split('#')[0].strip()] if (here / 'discover/roots.txt').exists() else []
src, _, _ = recomp.generate(prog, 0x1000, auto=[0x1000] + roots, with_main=True, flow=Flow(overlays=[(0x2000, 0x100, 4)], dynamic={0x100a}))
mods = json.loads((here / 'discover/modules.json').read_text()) if (here / 'discover/modules.json').exists() else []
for i, m in enumerate(mods):
    code = (here / m['dump']).read_bytes()
    s, _, _ = recomp.generate(code[:4], int(m['base'], 16), auto=[int(m['entry'], 16)],
                              flow=Flow(prefix=('ov%d_' % i, 0x2000, 0x2100), lib=True, module=(int(m['base'], 16), m['key'])))
    src += '\n' + s
(here / 'r.c').write_text('#define AREK_DISCOVER 1\n' + src)
subprocess.run(['cc', '-O1', '-o', str(here / 'r'), str(here / 'r.c')], check=True)
ram = bytearray(0x80000); ram[0x1000:0x1000 + len(prog)] = prog; ram[0x2000:0x2004] = bytes.fromhex(sys.argv[3])
(here / 'ram.bin').write_bytes(ram)
(here / 'regs.txt').write_text(' '.join(['0'] * 15 + ['%x' % (0x80000 - 0x100)]) + '\n0 0 0 0 0\nf_001000\n')
'''


def project(tmp_path, prog, module_hex, scen=None):
    import sys
    (tmp_path / 'build.py').write_text(BUILD)
    conf = {'build': '%s build.py . %s %s' % (sys.executable, prog, module_hex),
            'run': './r ram.bin regs.txt {dir}/out.bin {dir}/log.txt',
            'code': [['1000', '1100']], 'areas': [['2000', '100']], 'clean': '',
            'scenarios': scen or [{'name': 'main', 'frames': 1}]}
    (tmp_path / 'DISCOVER.json').write_text(json.dumps(conf))
    return tmp_path / 'DISCOVER.json'


def test_the_loop_finds_a_module_and_a_routine_and_runs_clean(tmp_path, monkeypatch):
    """Run 1 meets the module nobody registered (its dump goes to discover/modules/), run 2 the routine call_addr does
    not know (a root), run 3 is clean - the project's own build reads the files each time."""
    import os
    from arek import cli, discover
    if not __import__('shutil').which('cc'):
        pytest.skip('no C compiler')
    monkeypatch.setenv('PYTHONPATH', os.pathsep.join([str(__import__('pathlib').Path(discover.__file__).parents[1])] + os.environ.get('PYTHONPATH', '').split(os.pathsep)))
    conf = project(tmp_path, MAIN, MOD_X.hex())
    res = discover.run(conf, log=lambda *a: None)
    assert len(res) == 1 and res[0]['status'] == 'clean' and res[0]['rounds'] == 3, res
    assert res[0]['roots'] == ['001010'] and len(res[0]['modules']) == 1 and res[0]['module_roots'] == []
    mods = json.loads((tmp_path / 'discover/modules.json').read_text())
    assert mods[0]['base'] == '002000' and (tmp_path / mods[0]['dump']).read_bytes()[:4] == MOD_X
    assert (tmp_path / 'discover/roots.txt').read_text() == '001010\n'
    why = json.loads((tmp_path / 'discover/found.jsonl').read_text())
    assert why['addr'] == '001010' and why['why'].startswith('main run 2: call_addr line ')
    assert sorted(p.name for p in (tmp_path / 'discover/runs').iterdir()) == ['main-001', 'main-002', 'main-003']
    assert cli.main(['discover', str(conf), '--json']) == 0          # all known now: clean at once


def test_a_wild_jump_is_reported_not_added(tmp_path, monkeypatch):
    """A target outside the code ranges (here $1011: odd) is a wild jump - the loop stops and names the place."""
    import os
    from arek import discover
    if not __import__('shutil').which('cc'):
        pytest.skip('no C compiler')
    monkeypatch.setenv('PYTHONPATH', os.pathsep.join([str(__import__('pathlib').Path(discover.__file__).parents[1])] + os.environ.get('PYTHONPATH', '').split(os.pathsep)))
    wild = MAIN.replace('207c00001010', '207c00001011')
    res = discover.run(project(tmp_path, wild, MOD_A.hex()), log=lambda *a: None)
    assert res[0]['status'] == 'wild jump' and res[0]['wild']['target'] == '001011' and res[0]['wild']['fn'] == 'call_addr'
    assert not (tmp_path / 'discover/roots.txt').exists()


# ---- 1.0.81: the project's changes to the game by address (--hook, --operand, --declare) instead of text patches

# $1000: move.w #5,d0 ; addq.w #1,d0 ; move.w d0,d1 ; addi.w #248,d2 ; rts
PROG = '303c0005' '5240' '3200' '0642' '00f8'


def test_operand_and_hooks_by_address(tmp_path):
    from arek.m68k import recomp
    fl = recomp.flow_from_specs(b'', 0, operand=['1000=param_x + 1', '1008=0xf8u + extra()'],
                                hook=['1004=before_add', '1006=after_move:after'],
                                declare=['extern uint32_t param_x;', 'static uint32_t extra(void);'])
    c = ('\nuint32_t param_x = 39;\nstatic uint32_t extra(void) { return 2; }\n'
         'void before_add(M68 *m) { m->d[3] = 0x77; }\nvoid after_move(M68 *m) { m->d[4] = m->d[1] + 1; }\n')
    d, *_ = run(tmp_path, PROG, {}, flow=fl, extra_c=c)
    assert d[0] == 41 and d[1] == 41 and d[2] == 250 and d[3] == 0x77 and d[4] == 42
    fl = recomp.flow_from_specs(b'', 0, hook=['1004=add_ten:instead', '1006=no_move:skip'])
    c = '\nvoid add_ten(M68 *m) { m->d[0] += 10; }\nint no_move(M68 *m) { return 1; }\n'
    d, *_ = run(tmp_path, PROG, {}, flow=fl, extra_c=c)
    assert d[0] == 15 and d[1] == 0 and d[2] == 248


def test_a_hook_that_misses_an_instruction_fails_aloud(tmp_path, capsys):
    from arek.m68k import recomp
    from arek.m68k.decoder import Unsupported
    with pytest.raises(Unsupported, match=r'--hook \$1005: not the start'):
        recomp.generate(bytes.fromhex(PROG + '4e75'), 0x1000, auto=[0x1000], flow=recomp.flow_from_specs(b'', 0, hook=['1005=x']))
    with pytest.raises(Unsupported, match='changes the flow'):
        recomp.generate(bytes.fromhex(PROG + '4e75'), 0x1000, auto=[0x1000], flow=recomp.flow_from_specs(b'', 0, hook=['100c=x:after']))
    src, _, _ = recomp.generate(bytes.fromhex(PROG + '4e75'), 0x1000, auto=[0x1000], flow=recomp.flow_from_specs(b'', 0, hook=['2000=x']))
    assert 'is not in this translation' in capsys.readouterr().err and 'x(m)' not in src.split('void x(M68 *m);')[1]


def test_the_cli_takes_hooks_operands_and_declarations(tmp_path):
    from arek import cli
    f = tmp_path / 'p.bin'
    f.write_bytes(bytes.fromhex(PROG + '4e75'))
    assert cli.main(['recomp', str(f), '--base', '0x1000', '--auto', '0x1000', '--hook', '1004=h1', '--hook', '1006=h2:skip',
                     '--operand', '1008=0xf8u+band()', '--declare', 'static uint32_t band(void);', '-o', str(tmp_path / 'p.c')]) == 0
    c = (tmp_path / 'p.c').read_text()
    assert 'h1(m);   /* --hook */' in c and 'if (!h2(m)) {' in c and '((uint32_t)(0xf8u+band()) & 0xffffu)' in c
    assert 'static uint32_t band(void);' in c and 'void h1(M68 *m);' in c and 'int h2(M68 *m);' in c


def test_a_register_source_and_the_ea_rules(tmp_path):
    """SWIV's weapon lock ($187D4 move.b d0,(a1); $187D6 cmp.b d0,d1 read d1 instead): a register source by --operand;
    an <ea> that is a destination (eor d0,d1; add d0,(a0)) is refused."""
    from arek.m68k import recomp
    from arek.m68k.decoder import Unsupported
    fl = recomp.flow_from_specs(b'', 0, operand=['1000=m->d[2]', '1002=m->d[2]'])
    d, *_ = run(tmp_path, '3200' 'b200', {'d0': 5, 'd1': 0, 'd2': 9}, flow=fl)          # move.w d0,d1 ; cmp.b d0,d1
    assert d[1] == 9
    for prog in ('b141', 'd150'):                                                       # eor.w d0,d1 ; add.w d0,(a0)
        with pytest.raises(Unsupported, match='no immediate or register source'):
            recomp.generate(bytes.fromhex(prog + '4e75'), 0x1000, auto=[0x1000], flow=recomp.flow_from_specs(b'', 0, operand=['1000=1']))
