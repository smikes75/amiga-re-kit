"""Data stored right after a call (``bsr sub ; dc.w ... ; code``): the routine takes its
return address as a pointer to the data and returns behind it with ``jmp (An)``.

The program, at BASE:

    1000  bsr    sub              (or jsr sub.w)
    1004  dc.w   $b008,$9800,$0222,$8000      b008 would decode as cmp.b a0,d0 - not a 68000 instruction
    100c  addq.l #1,d0
    100e  rts
    1010  sub: movea.l (a7)+,a1
    1012  .l:  move.w (a1)+,d1
    1014       bpl    .l
    1016       add.w  d1,d1
    1018       bne    .l              ; the list ends with the word $8000
    101a       jmp    (a1)
"""
import pytest

from arek import cli
from arek.m68k import decoder, hwscan, recomp
from arek.m68k.decoder import Flow, Inline, Unsupported

from test_recomp_semantics import run

BASE = 0x1000
SUB = 0x1010
DATA = 'b008 9800 0222 8000'
BODY = DATA + ' 5280 4e75 225f 3219 6afc d241 66f8 4ed1'
BSR = '6100 000e ' + BODY
JSR = '4eb8 1010 ' + BODY
INLINE = Flow(inline={SUB: Inline('until', 0x8000)})


def prog(text=BSR):
    return bytes.fromhex(text.replace(' ', ''))


def test_without_a_description_the_code_after_the_call_is_a_frontier_not_bad_words():
    tree = decoder.call_tree(prog(), BASE, [BASE], BASE, BASE + len(prog()))
    ins, calls, bad, ind = tree[BASE]
    assert calls == {SUB} and not bad
    assert ind == [(BASE, 'data after call $1010 (describe it with inline)')]
    assert 0x100c not in ins
    assert tree[SUB][3] == [(0x101a, 'jmp (a1)')]


@pytest.mark.parametrize('text', [BSR, JSR])
def test_described_data_is_skipped_and_the_routine_returns_behind_it(text):
    tree = decoder.call_tree(prog(text), BASE, [BASE], BASE, BASE + len(prog(text)), INLINE)
    ins, calls, bad, ind = tree[BASE]
    assert sorted(ins) == [BASE, 0x100c, 0x100e] and not bad and not ind
    assert tree[SUB][2:] == ([], [])


def test_a_routine_that_pushes_its_return_address_back_is_not_taken_for_one():
    # sub: move.l (a7)+,a0 ; move.l a0,-(a7) ; rts   (no jmp (a0))
    p = prog('6100 0004 4e75 205f 2f08 4e75')
    assert not decoder.pops_return(p, BASE, 0x1006, BASE, BASE + len(p))
    ins, _, _, ind = decoder.walk(p, BASE, BASE, BASE, BASE + len(p))
    assert 0x1004 in ins and not ind


@pytest.mark.parametrize('spec, data, end', [
    ('until=8000', '0001 8000 ffff', 0x2004),
    ('words=3', '', 0x2006),
    ('longs=2', '', 0x2008),
    ('string', '6162 0000', 0x2004),          # "ab",0 + pad
    ('string', '6162 6300', 0x2004),          # "abc",0
    ('until=1234', '0001 0002', None),        # no end inside the image
])
def test_inline_spec_kinds(spec, data, end):
    d = bytes.fromhex(data.replace(' ', '')) + b'\xff' * 8 if spec.startswith('words') or \
        spec.startswith('longs') else bytes.fromhex(data.replace(' ', ''))
    assert Inline.parse(spec).end(d, 0x2000, 0x2000, 0x2000 + len(d)) == end


def test_unknown_inline_kind_is_refused():
    with pytest.raises(ValueError):
        Inline.parse('bytes=3')


@pytest.mark.parametrize('text', [BSR, JSR])
def test_recompiled_call_returns_behind_the_data(tmp_path, text):
    d, a, _, _ = run(tmp_path, text.replace(' ', ''), {'d0': 0x41}, flow=INLINE)
    assert d[0] == 0x42 and d[1] == 0          # the code after the data ran; the list ended at $8000
    assert a[7] == 0x80000 - 0x100 + 4         # balanced: only the final rts popped (the driver pushes none)


def test_recomp_refuses_an_undescribed_call_with_data_after_it():
    with pytest.raises(Unsupported, match=r'data after call \$1010'):
        recomp.generate(prog(), BASE, auto=[BASE])


def test_recomp_refuses_an_indirect_call_to_such_a_routine():
    flow = Flow(inline={SUB: Inline('until', 0x8000)})
    g = recomp.Gen(prog(), BASE, [], {}, flow)
    with pytest.raises(Unsupported, match='only a direct call'):
        g.callseq(SUB, 0x1004)


def test_hwscan_follows_the_description():
    p = prog()
    plain = hwscan.scan(p, BASE, [BASE], BASE, BASE + len(p))
    assert plain[BASE].indirect and 0x100c not in plain[BASE].ins
    r = hwscan.scan(p, BASE, [BASE], BASE, BASE + len(p), flow=INLINE)
    assert not r[BASE].indirect and not r[SUB].indirect and 0x100c in r[BASE].ins


def test_flow_from_specs_inline():
    fl = recomp.flow_from_specs(b'', 0, inline=['6c82,6c88:until=8000', '200:string'])
    assert set(fl.inline) == {0x6c82, 0x6c88, 0x200}
    assert (fl.inline[0x6c88].kind, fl.inline[0x6c88].value) == ('until', 0x8000)
    assert fl.inline[0x200].kind == 'string'


def test_cli_walk_and_recomp_inline(tmp_path, capsys):
    f = tmp_path / 'p.bin'
    f.write_bytes(prog())
    cli.main(['walk', str(f), '--base', '0x1000', '--start', '0x1000'])
    assert 'data after call $1010' in capsys.readouterr().out
    cli.main(['walk', str(f), '--base', '0x1000', '--start', '0x1000', '--inline', '1010:until=8000'])
    out = capsys.readouterr().out
    assert 'routine 001000: 3 instructions' in out and 'indirect' not in out
    cli.main(['dis', str(f), '--base', '0x1000', '--walk', '0x1000', '--inline', '1010:until=8000'])
    assert '00100c' in capsys.readouterr().out
    cli.main(['recomp', str(f), '--base', '0x1000', '--auto', '0x1000', '--inline', '1010:until=8000',
              '-o', str(tmp_path / 'p.c')])
    assert 'INLINE_RET != 0x100cu' in (tmp_path / 'p.c').read_text()
