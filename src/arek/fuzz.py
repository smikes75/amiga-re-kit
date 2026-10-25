"""Random input for a game: the same file drives the original in the headless emulator
(``arek trace run --inputs``) and a rebuild's engine, so both see one sequence.

One line per frame with the keys held, letters R L U D F S (right, left, up, down, fire,
space; ``arek.headless.trace.check_inputs``). A press lasts a human span (``hold`` frames,
3 to 22 by default), a share of the spans holds nothing, left and right never together.
Deterministic for a seed: a run that stalls can be repeated by its seed.

    lines = inputs(seed=1, frames=30000, start=320)      # nothing before frame 320
"""
import random

KEYS = 'RLUDFS'


def inputs(seed, frames, hold=(3, 22), start=0, rest=0.25, fire=0.4, space=0.1, keys=KEYS):
    """The lines (without newlines) of an input file of ``frames`` frames."""
    rng = random.Random(seed)
    lo, hi = hold
    if lo < 1 or hi < lo or frames < 0 or start < 0:
        raise ValueError('hold is (min, max) >= 1, frames and start >= 0')
    allowed = set(keys) & set(KEYS)
    lines = [''] * min(start, frames)
    while len(lines) < frames:
        span = rng.randint(lo, hi)
        held = ''
        if rng.random() >= rest:
            d = rng.choice(['R', 'L', 'U', 'D', 'R', 'L', ''])        # a direction, more often sideways
            vertical = rng.choice(['U', 'D', '']) if d in ('R', 'L') and rng.random() < 0.3 else ''
            held = d + vertical
            if rng.random() < fire:
                held += 'F'
            if rng.random() < space:
                held += 'S'
        held = ''.join(k for k in KEYS if k in held and k in allowed)
        lines.extend([held] * min(span, frames - len(lines)))
    return lines


def write(path, lines):
    with open(path, 'w') as f:
        f.write('\n'.join(lines) + ('\n' if lines else ''))
    return len(lines)
