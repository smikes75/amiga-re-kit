"""A refusal lists every frontier as data (routine, site, kind, insn, operand, target),
while its text stays what tools already parse."""
import json
import re

import pytest

from arek import cli
from arek.m68k import decoder, recomp
from arek.m68k.decoder import Unsupported

BASE = 0x1000
# 1000 bsr 100a ; 1004 jsr (a0) ; 1006 bsr 1010 ; 100a jmp (2,a1,d0.w) ; 100e rts ; 1010 dc.w $b008 (undecodable)
PROG = bytes.fromhex('6100 0008 4e90 6100 0008 4ef1 0002 4e75 b008'.replace(' ', ''))

# the expression Superfrog's tools/m6_autoiter.py applies to the end of the output
TOOL_RE = re.compile(r'refused: routine \$(\w+), (?:indirect jump: )?(jsr|jmp) (.*) @(\w+)\s*$')


def test_every_frontier_is_listed_once():
    with pytest.raises(Unsupported) as e:
        recomp.generate(PROG, BASE, auto=[BASE])
    fr = {(f['kind'], f['site']): f for f in e.value.frontiers}
    assert set(fr) == {('indirect', 0x1004), ('indirect', 0x100a), ('undecodable', 0x1010)}
    assert fr[('indirect', 0x1004)]['insn'] == 'jsr' and fr[('indirect', 0x1004)]['operand'] == '(a0)'
    # 100a is reached first by falling through from 1006 in routine 1000: listed once, with that routine
    assert fr[('indirect', 0x100a)]['insn'] == 'jmp' and fr[('indirect', 0x100a)]['routine'] == BASE
    assert len(e.value.frontiers) == 3
    assert str(e.value).startswith('routine $')                     # the first one's text, as before


def test_data_after_call_frontier_names_the_callee():
    # bsr sub ; dc.w 1 ; ... sub: movea.l (a7)+,a1 ; jmp (a1)
    p = bytes.fromhex('6100 0004 0001 225f 4ed1'.replace(' ', ''))
    with pytest.raises(Unsupported) as e:
        recomp.generate(p, BASE, auto=[BASE])
    kinds = {f['kind']: f for f in e.value.frontiers}
    assert kinds['data_after_call']['target'] == 0x1006 and kinds['data_after_call']['site'] == BASE


def test_frontier_helper():
    assert decoder.frontier(1, 2, 'jmp (2,a6)') == {'routine': 1, 'site': 2, 'why': 'jmp (2,a6)',
                                                   'kind': 'indirect', 'insn': 'jmp', 'operand': '(2,a6)'}
    assert decoder.frontier(1, 2, 'op fa84')['kind'] == 'undecodable'


def test_cli_refusals_file_and_unchanged_last_line(tmp_path, capsys):
    f = tmp_path / 'p.bin'
    f.write_bytes(PROG)
    ref = tmp_path / 'ref.json'
    assert cli.main(['recomp', str(f), '--base', '0x1000', '--auto', '0x1000', '--refusals', str(ref),
                     '-o', str(tmp_path / 'p.c')]) == 2
    err = capsys.readouterr().err
    assert '3 frontiers (all in' in err
    data = json.loads(ref.read_text())
    assert {(x['kind'], x['site']) for x in data['frontiers']} == {('indirect', '1004'), ('indirect', '100a'),
                                                                   ('undecodable', '1010')}
    # an output that ends with an indirect jump still parses with the existing expression
    p2 = bytes.fromhex('4e90 4e75'.replace(' ', ''))
    f.write_bytes(p2)
    cli.main(['recomp', str(f), '--base', '0x1000', '--auto', '0x1000', '--refusals', str(ref),
              '-o', str(tmp_path / 'q.c')])
    m = TOOL_RE.search(capsys.readouterr().err.strip())
    assert m and m.groups() == ('1000', 'jsr', '(a0)', '1000')
    # a later successful run removes the stale file
    f.write_bytes(bytes.fromhex('4e75'))
    assert cli.main(['recomp', str(f), '--base', '0x1000', '--auto', '0x1000', '--refusals', str(ref),
                     '-o', str(tmp_path / 'r.c')]) == 0
    assert not ref.exists()


def test_mcp_recomp_returns_the_refusal(tmp_path):
    pytest.importorskip('mcp')
    from arek import mcp_server
    f = tmp_path / 'p.bin'
    f.write_bytes(PROG)
    r = mcp_server.recomp(str(f), '0x1000', str(tmp_path / 'p.c'), auto=['0x1000'])
    assert len(r['refused']['frontiers']) == 3 and r['refused']['message'].startswith('routine $')
