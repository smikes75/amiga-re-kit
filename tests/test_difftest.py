"""arek.m68k.difftest: the translation against the 68000. The corpus was recorded with Moira (vAmiga 899da5d); its replay needs a
C compiler alone. A sweep against Moira itself runs when $AREK_MOIRA names the vAmiga source."""
import os
import shutil
from pathlib import Path

import pytest

from arek import cli
from arek.m68k import difftest, recomp

CORPUS = Path(__file__).parent / 'data' / 'moira68000_semantics.txt.gz'


def compiler():
    if not (shutil.which('cc') or shutil.which('gcc') or shutil.which('clang')):
        pytest.skip('no C compiler')


def test_the_recorded_cases_agree(tmp_path):
    compiler()
    res = difftest.check_corpus(CORPUS, str(tmp_path))
    assert res['cases'] > 3000 and not res['crashed']
    assert not res['mismatches'], difftest.summary(res)
    # every kind the decoder has, the ones that leave the straight line among them
    assert {'negx', 'bcd', 'divu', 'divs', 'movem', 'link', 'sr', 'trap', 'rte', 'rts', 'bsr', 'jsr', 'jmp', 'bcc', 'dbcc'} <= set(res['by_kind'])


@pytest.mark.parametrize('old, new, kind, field', [
    ('return f_subx(m, d, 0, sz);', 'uint32_t r_ = f_sub(m, d, 0, sz); r_ = f_sub(m, m->x, r_, sz); return r_;', 'negx', 'ccr'),
    ('m->v = 1; m->c = 0; m->n = 1; m->z = 0; return; }   /* pretecni: registr zustava; 1.0.26', 'm->v = 1; m->c = 0; return; }   /* 1.0.26', 'divu', 'ccr'),
    ('if (with_hi) m->srhi = v & 0xa700;', 'if (with_hi) m->srhi = v & 0xff00;', 'sr', 'sr'),
])
def test_a_slip_in_the_translation_is_found(tmp_path, monkeypatch, old, new, kind, field):
    """The tester has teeth: three slips the first sweep found, put back."""
    compiler()
    assert recomp.RUNTIME.count(old) == 1
    monkeypatch.setattr(recomp, 'RUNTIME', recomp.RUNTIME.replace(old, new))
    groups = [[p for p in g if p['kind'] == kind] for g in difftest.load_corpus(CORPUS)]
    res = difftest._compare_groups([g for g in groups if g], None, None, str(tmp_path))
    assert any(field in m['fields'] for m in res['mismatches'])


def test_differences_and_rows():
    line = '0 22 8008 2708 ' + ' '.join('%x' % i for i in range(16)) + ' 30000=12,30001=34'
    r = difftest.parse_result(line)
    assert r['cycles'] == 0x22 and r['pc'] == 0x8008 and r['d'][7] == 7 and r['a'][0] == 8 and r['mem'] == '30000=12,30001=34'
    assert difftest.differences(r, dict(r)) == []
    assert difftest.differences(r, dict(r, pc=0)) == []                               # a plain C return: no place to compare
    assert difftest.differences(r, dict(r, sr=0x2709)) == ['ccr']
    assert difftest.differences(r, dict(r, sr=0x2608)) == ['sr']
    assert difftest.differences(r, dict(r, cycles=1, mem='-')) == ['memory', 'cycles']
    assert difftest.differences(r, dict(r, d=[1] + r['d'][1:])) == ['d0']
    user = dict(r, sr=0x0708)                                                         # S lost: Moira's a7 is the USP, there is one a7 here
    assert difftest.differences(user, dict(user, a=r['a'][:7] + [1])) == []
    assert difftest.differences(r, dict(r, flags=16, pc=0x1234)) == ['unknown target $1234']


def test_corpus_through_the_command_line(tmp_path, capsys):
    compiler()
    groups = difftest.load_corpus(CORPUS)
    small = tmp_path / 'small.txt'
    with open(small, 'w') as f:
        f.write('G\n')
        s = groups[0][0]
        m = s['m']
        f.write('P %x %s %s %s - %x %s %s\n' % (s['base'], m['code'].hex(), ','.join('%x' % x for x in m['roots']), ','.join('%x' % x for x in m['exits']),
                                                m['self'], s['kind'], s['text']))
    (tmp_path / 'w').mkdir()
    assert cli.main(['difftest', '--corpus', str(small), '--work', str(tmp_path / 'w')]) == 0
    assert '0 mismatches' in capsys.readouterr().out
    with pytest.raises(SystemExit, match='--moira'):
        cli.main(['difftest', '--work', str(tmp_path / 'w')])
    with pytest.raises(FileNotFoundError, match='Moira.cpp'):
        difftest.moira_dir(tmp_path)


@pytest.mark.skipif(not os.environ.get('AREK_MOIRA'), reason='$AREK_MOIRA names the vAmiga source')
def test_sweep_against_moira(tmp_path):
    res = difftest.sweep(os.environ['AREK_MOIRA'], tmp_path / 'moira', work=str(tmp_path), kinds={'trap', 'rte', 'rts'})
    assert res['cases'] > 30 and not res['mismatches'], difftest.summary(res)


def test_a_target_compared_on_32_bits_is_found(tmp_path, monkeypatch):
    """1.0.27 (Xenon 2 KIT-GAP 6): call_addr without the 24-bit mask - the recorded jsr/jmp through a register with a flag
    in its top byte must fail."""
    compiler()
    emit = recomp.Gen.emit
    monkeypatch.setattr(recomp.Gen, 'emit', lambda self, s='': None if s.strip().startswith('a = ADDR24(a);') else emit(self, s))
    groups = [[p for p in g if p['kind'] in ('jsr', 'jmp') and p['m']['dyn']] for g in difftest.load_corpus(CORPUS)]
    res = difftest._compare_groups([g for g in groups if g], None, None, str(tmp_path))
    assert any(m['fields'][0].startswith('unknown target') for m in res['mismatches'])
