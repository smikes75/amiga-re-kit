"""arek.fuzz: random joystick input, the same file for the emulator and a rebuild."""
import pytest

from arek import cli, fuzz
from arek.headless import trace


def test_deterministic_and_well_formed():
    a = fuzz.inputs(seed=7, frames=3000, hold=(3, 22), start=100)
    assert a == fuzz.inputs(7, 3000, (3, 22), 100) and a != fuzz.inputs(8, 3000, (3, 22), 100)
    assert len(a) == 3000 and all(x == '' for x in a[:100]) and any(a[100:])
    assert all(set(x) <= trace.INPUT_KEYS for x in a)
    assert all(not ('R' in x and 'L' in x) and not ('U' in x and 'D' in x) for x in a)
    # spans: a change of the held keys at least 3 frames apart (except the first after start)
    changes = [k for k in range(101, 3000) if a[k] != a[k - 1]]
    gaps = [b - c for c, b in zip(changes, changes[1:])]
    assert gaps and min(gaps) >= 3                                          # same keys twice in a row make longer gaps
    assert sum(1 for x in a[100:] if x == '') / 2900 < 0.6                  # mostly something held


def test_keys_subset_and_edges():
    assert set(''.join(fuzz.inputs(1, 500, keys='RL'))) <= {'R', 'L'}
    assert fuzz.inputs(1, 0) == [] and fuzz.inputs(1, 5, start=9) == [''] * 5
    with pytest.raises(ValueError):
        fuzz.inputs(1, 10, hold=(5, 2))


def test_cli_writes_a_file_the_trace_side_accepts(tmp_path, capsys):
    out = tmp_path / 'in.txt'
    assert cli.main(['fuzz', '--seed', '3', '--frames', '400', '--start', '20', '--out', str(out)]) == 0
    assert '400 frames, seed 3' in capsys.readouterr().out
    assert trace.check_inputs(str(out)) == 400
    assert cli.main(['fuzz', '--seed', '3', '--frames', '5']) == 0
    assert len(capsys.readouterr().out.splitlines()) == 5
