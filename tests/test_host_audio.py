"""arek_audio.h (the host's 48 kHz stereo mix of Paula's sample events): the default stereo wiring bit for bit as before,
and 0.8.6 (Alien Breed II G52) the per-channel gain matrix with a linear ramp across one ara_until() call; 1.0.93 (SWIV)
the host's voices as channels 4-7, the compressor-limiter while one sounds and the mixer levels as timed events. A small C
program around the header, held against the mix computed here. Synthetic events, no game data."""
import os
import random
import shutil
import subprocess

import pytest

from arek import host

HOST = os.path.dirname(os.path.abspath(host.__file__))
RATE, CCK = 48000.0, 3546895.0
PROG = r'''
#include <stdio.h>
#include <stdlib.h>
#include "arek_audio.h"
int main(int argc, char **argv) {
    /* argv[1]: mode (default | half | ramp | loud | twice); argv[2]: t_start - the first call sets the sample clock (one
     * sample); argv[3]: t_end; events on stdin as "t ch v" lines, then ara_until(t_end) renders the rest */
    const char *mode = argv[1]; double t_start = atof(argv[2]), t_end = atof(argv[3]), t; int ch, v;
    ara_reset();
    ara_until(t_start);
    if (!strcmp(mode, "half")) ara_gain(0, 0.5, 0.5);
    if (!strcmp(mode, "loud")) { ara_gain(1, 1, 0); ara_gain(2, 1, 0); }            /* all four on the left: clamps */
    if (!strcmp(mode, "ramp")) ara_gain_to(0, 0, 1);                                /* ch0 moves from left to right across the call */
    if (!strcmp(mode, "twice")) { ara_gain(0, 0.5, 0.5); ara_gain(0, 1, 0); }       /* set and set back = default */
    while (scanf("%lf %d %d", &t, &ch, &v) == 3) {
        if (ch >= 8) ara_level_at(ch - 8, t, v / 4096.0);                           /* 1.0.93: "t 8+ch level*4096" */
        else ara_event(ch, t, v);
    }
    ara_until(t_end);
    printf("%d\n", ARA_N);
    for (int i = 0; i < ARA_N; i++) printf("%d %d\n", ARA_BUF[2 * i], ARA_BUF[2 * i + 1]);
    printf("gain %g %g %g %g %g %g %g %g ramp %d\n", ARA_GAIN[0][0], ARA_GAIN[0][1], ARA_GAIN[1][0], ARA_GAIN[1][1],
           ARA_GAIN[2][0], ARA_GAIN[2][1], ARA_GAIN[3][0], ARA_GAIN[3][1], ARA_RAMP);
    printf("limit %d %.6f\n", ara_limit_on(), ARA_LIMIT_MIN);
    return 0;
}
'''


def _build(tmp_path):
    cc = shutil.which('cc') or shutil.which('clang') or shutil.which('gcc')
    if not cc:
        pytest.skip('no C compiler')
    (tmp_path / 'mix.c').write_text(PROG)
    exe = tmp_path / 'mix'
    subprocess.run([cc, '-O1', '-I', HOST, str(tmp_path / 'mix.c'), '-lm', '-o', str(exe)], check=True)
    return exe


def _run(exe, mode, t0, t_end, events, limit=False):
    out = subprocess.run([str(exe), mode, repr(t0), repr(t_end)], input=''.join('%r %d %d\n' % e for e in events), capture_output=True, text=True, check=True).stdout.splitlines()
    n = int(out[0])
    samples = [tuple(int(x) for x in line.split()) for line in out[1:1 + n]]
    if limit:                                         # (on, lowest gain) of the limiter
        return samples, (int(out[2 + n].split()[1]), float(out[2 + n].split()[2]))
    return samples, out[1 + n]


def _reference(events, t0, t_end, gain):
    """The mix as the header defines it: a sample every CCK/48000 from the first call's time (that call renders one
    silent sample, the events come after it), each channel holding its last event's value, left = sum ch * gain[ch][0],
    right = sum ch * gain[ch][1], times 2."""
    ev = sorted(events, key=lambda e: e[0])           # stable, like the header's insertion sort
    step = CCK / RATE
    level, out, t, i = [0, 0, 0, 0], [(0, 0)], t0 + step, 0
    while t <= t_end:
        while i < len(ev) and ev[i][0] <= t:
            level[ev[i][1]] = ev[i][2]
            i += 1
        l = sum(level[c] * gain[c][0] for c in range(4)) * 2
        r = sum(level[c] * gain[c][1] for c in range(4)) * 2
        out.append((int(max(-32768, min(32767, round(l)))), int(max(-32768, min(32767, round(r))))))
        t += step
    return out


DEFAULT = [(1, 0), (0, 1), (0, 1), (1, 0)]


def _events(seed, t0, t_end, n=60, lo=-8128, hi=8128):
    rng = random.Random(seed)
    return [(t0 + rng.random() * (t_end - t0), rng.randrange(4), rng.randint(lo, hi)) for _ in range(n)]


def test_default_wiring_unchanged(tmp_path):
    """Left = channels 0 and 3, right = 1 and 2, value * 2: every sample as the old integer mix."""
    exe = _build(tmp_path)
    t0, t_end = 1000.0, 1000.0 + CCK / 50          # one PAL frame: 960 samples
    ev = _events(1, t0, t_end)
    samples, tail = _run(exe, 'default', t0, t_end, [(t0, 0, 0)] + ev)
    assert len(samples) in (960, 961) and samples == _reference([(t0, 0, 0)] + ev, t0, t_end, DEFAULT)   # 48000 / 50 a frame (+1 at the edge)
    assert any(s[0] for s in samples) and any(s[1] for s in samples)
    assert tail == 'gain 1 0 0 1 0 1 1 0 ramp 0'
    samples2, _ = _run(exe, 'twice', t0, t_end, [(t0, 0, 0)] + ev)   # a gain set and set back to the default takes the same path
    assert samples2 == samples


def test_gain_matrix_and_clamp(tmp_path):
    """Channel 0 at 0.5 left + 0.5 right (G52's smallest input); all four channels on the left clamp to int16."""
    exe = _build(tmp_path)
    t0, t_end = 0.0, CCK / 100
    ev = [(t0, 0, 100)]
    samples, tail = _run(exe, 'half', t0, t_end, ev)
    assert len(samples) > 100 and all(s == (100, 100) for s in samples[1:])   # 100 * 0.5 * 2 on each side
    assert tail == 'gain 0.5 0.5 0 1 0 1 1 0 ramp 0'
    ev = _events(2, t0, t_end)
    samples, _ = _run(exe, 'half', t0, t_end, [(t0, 0, 0)] + ev)
    assert samples == _reference([(t0, 0, 0)] + ev, t0, t_end, [(0.5, 0.5), (0, 1), (0, 1), (1, 0)])
    loud = [(t0, c, 8128) for c in range(4)]
    samples, _ = _run(exe, 'loud', t0, t_end, loud)
    assert all(s == (32767, 0) for s in samples[1:])                 # 4 * 8128 * 2 = 65024 clamped, nothing on the right
    quiet = [(t0, c, -8128) for c in range(4)]
    samples, _ = _run(exe, 'loud', t0, t_end, quiet)
    assert all(s == (-32768, 0) for s in samples[1:])


def test_ramp_across_one_call(tmp_path):
    """ara_gain_to(0, 0, 1): channel 0 (constant 100) moves from the left to the right linearly over the call's samples;
    at the end the matrix is the target and the ramp is off."""
    exe = _build(tmp_path)
    t0, t_end = 0.0, CCK / 100
    samples, tail = _run(exe, 'ramp', t0, t_end, [(t0, 0, 100)])
    samples = samples[1:]                                            # the first call's silent sample
    n = len(samples)
    assert n > 100
    left = [s[0] for s in samples]
    right = [s[1] for s in samples]
    assert left[0] == round(200 * (1 - 1 / n)) and right[0] == round(200 / n)
    assert left[-1] == 0 and right[-1] == 200
    assert all(a >= b for a, b in zip(left, left[1:])) and all(a <= b for a, b in zip(right, right[1:]))
    assert all(l + r in (199, 200, 201) for l, r in samples)        # the energy stays on one channel pair
    assert tail == 'gain 0 1 0 1 0 1 1 0 ramp 0'


DEFAULT8 = DEFAULT * 2                                 # 1.0.93: 4 and 7 left, 5 and 6 right


def _reference8(events, t0, t_end):
    """The 8-channel mix without the limiter's action: each channel's last value times its mixer level (events on 8 + ch
    carry level * 4096 from their time on), placed by DEFAULT8, times 2."""
    ev = sorted(events, key=lambda e: e[0])
    step = CCK / RATE
    level, lvl, out, t, i = [0] * 8, [1.0] * 8, [(0, 0)], t0 + step, 0
    while t <= t_end:
        while i < len(ev) and ev[i][0] <= t:
            if ev[i][1] >= 8:
                lvl[ev[i][1] - 8] = ev[i][2] / 4096.0
            else:
                level[ev[i][1]] = ev[i][2]
            i += 1
        l = sum(level[c] * DEFAULT8[c][0] * lvl[c] for c in range(8)) * 2
        r = sum(level[c] * DEFAULT8[c][1] * lvl[c] for c in range(8)) * 2
        out.append((int(max(-32768, min(32767, round(l)))), int(max(-32768, min(32767, round(r))))))
        t += step
    return out


def test_a_quiet_voice_is_mixed_exactly(tmp_path):
    """1.0.93: the host's voices (channels 4-7) sound - the limiter is in, but under its knee (-9 dBFS) its gain is exactly 1:
    every sample is the plain 8-channel sum, voice 0 and 3 on the left, 1 and 2 on the right."""
    exe = _build(tmp_path)
    t0, t_end = 0.0, CCK / 50
    rng = random.Random(7)
    ev = [(t0, 0, 0)] + [(t0 + rng.random() * (t_end - t0), rng.randrange(8), rng.randint(-1200, 1200)) for _ in range(120)]
    samples, (on, low) = _run(exe, 'default', t0, t_end, ev, limit=True)
    assert on == 1 and low == 1.0
    assert samples == _reference8(ev, t0, t_end)
    assert any(e[1] >= 4 for e in ev) and any(s[0] for s in samples) and any(s[1] for s in samples)


def test_a_loud_voice_is_limited_and_lets_go_smoothly(tmp_path):
    """1.0.93: two Paula channels and two voices at full level on the left (65024 before the clamp): after the 3 ms attack
    the limiter holds the left side steady near -4.4 dBFS (ratio 8 over -6 dBFS: 1.98 of full scale -> 0.60), the right
    side silent; when the voices stop the level rises back over the 150 ms release without a step."""
    exe = _build(tmp_path)
    t0, t_mid, t_end = 0.0, CCK * 0.1, CCK * 0.4
    ev = [(t0, 0, 8128), (t0, 3, 8128), (t0, 4, 8128), (t0, 7, 8128), (t_mid, 4, 0), (t_mid, 7, 0)]
    samples, (on, low) = _run(exe, 'default', t0, t_end, ev, limit=True)
    left = [s[0] for s in samples]
    assert on == 1 and 0.25 < low < 0.35 and not any(s[1] for s in samples)
    k_mid = int(0.1 * RATE)
    steady = left[int(0.03 * RATE):k_mid - 2]
    assert max(steady) - min(steady) <= 2 and 18800 < steady[-1] < 20400, (min(steady), max(steady))
    assert max(left) <= 32767 and sum(1 for v in left if v == 32767) < 0.003 * RATE   # clamped only inside the attack
    after = left[k_mid + 2:]
    assert after[0] < steady[-1] and after[-1] > after[0] * 1.2                # half the signal, then the gain comes back
    assert all(0 <= b - a <= 40 for a, b in zip(after, after[1:]))            # rising, sample to sample, no step


def test_mixer_levels_are_timed_events(tmp_path):
    """1.0.93: ara_level_at(ch, t, level) works from the sample at t on (a sound's level from its start, not from the frame's
    start): channel 0 at 0.5 from the middle of the frame, channel 1 at 2 from the same time (the limiter is in, still
    under its knee: exact); levels of exactly 1 keep the plain integer mix bit for bit."""
    exe = _build(tmp_path)
    t0, t_end = 0.0, CCK / 50
    t_mid = t_end / 2
    ev = [(t0, 0, 1000), (t0, 1, 1000), (t_mid, 8, 2048), (t_mid, 9, 8192)]
    samples, (on, low) = _run(exe, 'default', t0, t_end, ev, limit=True)
    assert samples == _reference8(ev, t0, t_end) and on == 1 and low == 1.0
    k = next(i for i, s in enumerate(samples) if s[0] == 1000)
    assert abs(k - 480) <= 1 and samples[k - 1] == (2000, 2000) and samples[k] == (1000, 4000)
    ev = _events(3, t0, t_end)
    plain, _ = _run(exe, 'default', t0, t_end, [(t0, 0, 0)] + ev)
    ones, (on, _) = _run(exe, 'default', t0, t_end, [(t0, 0, 0)] + ev + [(t_mid, 8 + c, 4096) for c in range(8)], limit=True)
    assert ones == plain and on == 0
