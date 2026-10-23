"""recomp --profile: per routine calls, clocks and written pages, and the arek profile reader."""
import pytest

from arek import cli
from arek.m68k import profile, recomp

from test_recomp_semantics import BASE, run

# 1000: bsr 1014 ; bsr 1014 ; move.l #1,$c00010.l ; rts        (the sub called twice)
# 1014: move.l #$12345678,$3000.l ; move.w #7,$4ffe.l ; rts     (6 bytes per call: pages $c and $13)
PROG = ('6100 0012' '6100 000e' '23fc 0000 0001 00c0 0010' '4e75'
        '23fc 1234 5678 0000 3000' '33fc 0007 0000 4ffe' '4e75').replace(' ', '')


def test_profile_counts_calls_clocks_and_pages(tmp_path):
    out = tmp_path / 'prof.txt'
    run(tmp_path, PROG, {}, auto=(BASE, 0x1014), timing=True, profile=True, slow=(0xc00000, 0x80000),
        env={'AREK_PROFILE': str(out)})
    rows = profile.read(str(out))
    assert rows[0] == {'memsz': 0x80000, 'slowbase': 0xc00000, 'slowsz': 0x80000}
    by = {r['addr']: r for r in rows[1:]}
    assert by[0x1000]['calls'] == 1 and by[0x1014]['calls'] == 2
    assert by[0x1014]['bytes'] == 12 and by[0x1014]['pages'] == [(0x3000, 0x3400), (0x4c00, 0x5000)]
    # the main: the two return addresses bsr pushed (stack page $7fc00) and 4 bytes in slow RAM
    assert by[0x1000]['bytes'] == 12 and by[0x1000]['pages'] == [(0x7fc00, 0x80000), (0xc00000, 0xc00400)]
    # clocks of the sub alone: 2 x (move.l #,abs.l 28 + move.w #,abs.l 20 + rts 16) = 128, bsr 18 x 2 + the rest in main
    assert by[0x1014]['clocks'] == 128 and by[0x1000]['clocks'] == 80   # 2 x bsr 18 + move.l 28 + rts 16
    s = profile.summary(rows, 'clocks', top=5)
    assert s[0]['addr'] == 0x1014 and abs(s[0]['share'] - 128 / 208) < 1e-9
    assert cli.main(['profile', str(out), '--by', 'calls']) == 0


def test_profile_off_by_default_and_not_in_lib_modules():
    src, _, _ = recomp.generate(bytes.fromhex('4e75'), BASE, auto=[BASE])
    assert 'prof_enter' not in src and '#define PROF_WRITE(a) ((void)0)' in src
    from arek.m68k.decoder import Flow
    src, _, _ = recomp.generate(bytes.fromhex('4e75'), BASE, auto=[BASE], profile=True,
                                flow=Flow(prefix=('m_', BASE, BASE + 0x100), lib=True))
    assert 'prof_enter' not in src


def test_reader_and_summary_from_text():
    text = 'H 80000 c00000 0\nR 1 1000 2 100 8 3 5-6\nR 2 1000 1 50 0\nR 2 2000 4 200 1 200\n'
    rows = profile.read(text)
    assert rows[1]['pages'] == [(0xc00, 0x1000), (0x1400, 0x1c00)]
    s = profile.summary(rows)
    assert [a['addr'] for a in s] == [0x2000, 0x1000] and s[1]['calls'] == 3 and s[1]['frames'] == 2
    assert profile.summary(rows, frame=2)[1]['clocks'] == 50
    assert '002000' in profile.format_summary(s)
