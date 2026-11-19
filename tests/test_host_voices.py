"""1.0.93 (SWIV, the user 2026-11-18: SWIV-projekt's extra voices): the host's output-only voices (arek_host.h host_voice_*,
mixed as channels 4-7 by arek_audio.h) and the engine's mixer gains (engine_aud_gain). A synthetic game through the native
engine, its frame hook plays square waves from chip RAM on the voices; the machine's state hash is the same with and
without them. No game data, no emulator."""
import struct
import subprocess

import pytest

from arek import bus, host
from arek.m68k import recomp

MAIN, L3 = 0x1000, 0x1100
WAIT_VBL = '30384002' 'b0784002' '67fa' '52784000' '60f0'
L3_H = '52784002' '33fc002000dff09c' '4e73'
SAMPLE = 0x1800
HOOK = r'''
void engine_aud_gain(int ch, double l, double r);
void engine_aud_mix(int group, double level);
static void voice_rec(int n) {
#if VOICES
#ifndef SRC
#define SRC 0
#endif
    if (n == 3) { if (SRC) { memset(host_voice_mem() + 0x100, 0x7f, 8); memset(host_voice_mem() + 0x108, 0x81, 8); }   /* 1.0.94: the same square in the host's memory */
                  host_voice_reg(0, 0, SRC ? 0x0100 : 0); host_voice_reg(0, 2, SRC ? 0x0100 : 0x1800); host_voice_reg(0, 4, 8); host_voice_reg(0, 6, 254);
                  host_voice_reg(0, 8, 64); host_voice_dma(0, 1); }
    if (n == 5) { host_voice_side(1, 0, 1); host_voice_reg(1, 0, 0); host_voice_reg(1, 2, 0x1800); host_voice_reg(1, 4, 8);
                  host_voice_reg(1, 6, 300); host_voice_reg(1, 8, 32); host_voice_dma(1, 1); }
    if (n == 9) host_voice_dma(0, 0);
    printf("busy %d %d %d\n", n, host_voice_busy(0), host_voice_busy(1));
#endif
#if GAIN
    if (n == 6) engine_aud_gain(5, 0, 0);                    /* the mixer silences voice 1 (channel 5) from frame 7 on */
#endif
#if TAG
    if (n == 3) host_aud_tag(4, 2);                          /* voice 0's sound is of kind 2, voice 1's of kind 3 */
    if (n == 5) { host_aud_tag(5, 3); host_aud_dropped(3); }
    if (n == 6 && TAG == 2) engine_aud_mix(2, 0.5);          /* the page: kind 2 at half from frame 7 on */
    if (n == 6 && TAG == 3) engine_aud_mix(-1, 0.5);         /* 1.0.94: every channel at half (the base) */
    if (n == 13) printf("counts %d %d %d %d\n", H_AUDCOUNT[2][0], H_AUDCOUNT[2][1], H_AUDCOUNT[3][1], H_AUDCOUNT[3][2]);
#endif
}
'''


def run(tmp_path, name, defines, frames=14):
    if not bus.compiler():
        pytest.skip('no C compiler')
    img = bytearray(0x2000)
    for at, hx in {MAIN: '4df900dff000' '3d7cc020009a' + WAIT_VBL, L3: L3_H}.items():
        img[at:at + len(hx) // 2] = bytes.fromhex(hx)
    img[SAMPLE:SAMPLE + 16] = bytes([0x7f] * 8 + [0x81] * 8)          # one square period of 16 bytes = 8 words
    src, _, _ = recomp.generate(bytes(img), 0, auto=[MAIN, L3], timing=True, bus_table=True)
    d = tmp_path / name
    d.mkdir()
    (d / 'game.c').write_text(src)
    (d / 'voice.c').write_text(HOOK)
    st = d / 'state'
    st.mkdir()
    ram = bytearray(0x80000)
    ram[:len(img)] = img
    (st / 'chip.bin').write_bytes(ram)
    creg = bytearray(512)
    creg[0x96:0x98] = struct.pack('>H', 0x0200)
    (st / 'creg.bin').write_bytes(creg)
    (st / 'state.txt').write_text('0 0 0 0 0 0 0 0\n0 0 0 0 0 0 0 7f000\n2000 0 0 1000\nfe 0 0 0 0 5500\n100\n')
    host.pack(str(st), str(d / 'state.bin'))
    host.engine_build(str(d / 'n'), str(d / 'game.c'), 'f_%06x' % L3, 'f_%06x' % MAIN, native=True, src=str(d / 'voice.c'),
                      defines=['ENGINE_FRAME_RECORD=voice_rec'] + list(defines))
    r = subprocess.run([str(d / 'n' / 'arek_host_engine'), str(d / 'state.bin'), str(frames), '--audhash', '--audout', str(d / 'aud.raw'),
                        '--dump', str(d / 'chip.bin')], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    raw = (d / 'aud.raw').read_bytes()
    pcm = struct.unpack('<%dh' % (len(raw) // 2), raw)
    return r.stdout.splitlines(), pcm[0::2], pcm[1::2], (d / 'chip.bin').read_bytes()


def test_voices_sound_and_leave_the_machine_alone(tmp_path):
    """Voice 0 (left by default, a square of +-127 x 64) from frame 3 to 9, voice 1 placed right (volume 32) from frame 5:
    the left channel carries voice 0 only while it plays, the right one voice 1; the machine's hash and chip RAM are the
    same as without the voices (no DMA slot, no interrupt, no memory write); the limiter took part (a voice sounded)."""
    on_lines, on_l, on_r, on_mem = run(tmp_path, 'on', ['VOICES=1', 'GAIN=0', 'TAG=0'])
    off_lines, off_l, off_r, off_mem = run(tmp_path, 'off', ['VOICES=0', 'GAIN=0', 'TAG=0'])
    hash_on = [x for x in on_lines if x.startswith('frames ')][0]
    hash_off = [x for x in off_lines if x.startswith('frames ')][0]
    assert hash_on == hash_off and on_mem == off_mem                     # the machine never saw the voices
    assert not any(off_l) and not any(off_r)                            # the game itself makes no sound
    per = len(on_l) / 14.0                                               # samples a frame (~960)
    seg = lambda ch, f0, f1: ch[int(f0 * per):int(f1 * per)]
    assert max(abs(v) for v in seg(on_l, 4, 8)) > 8000 and not any(seg(on_l, 0, 3))   # voice 0 on the left
    assert not any(seg(on_l, 10.5, 14))                                  # stopped at frame 9 (the word finishes)
    assert max(abs(v) for v in seg(on_r, 6, 12)) > 3000 and not any(seg(on_r, 0, 4.5))   # voice 1 on the right
    busy = {int(x.split()[1]): (int(x.split()[2]), int(x.split()[3])) for x in on_lines if x.startswith('busy ')}
    assert busy[4] == (1, 0) and busy[6] == (1, 1) and busy[12] == (0, 1)
    audio = [x for x in on_lines if x.startswith('audio ')][0].split()
    assert float(audio[-1]) <= 1.0


def test_engine_aud_gain_ramps_a_channel_away(tmp_path):
    """engine_aud_gain(5, 0, 0) in frame 6's hook is taken at the next frame's start and ramps channel 5 (voice 1) down
    across that frame: the right channel is the same as without the call until then, falls over about one frame (not a
    step) and is silent after it; the left one (voice 0) is the same until the ramp (the limiter is stereo-linked: after it
    the left may move by a few steps)."""
    _, l_g, r_g, _ = run(tmp_path, 'gain', ['VOICES=1', 'GAIN=1', 'TAG=0'])
    _, l_n, r_n, _ = run(tmp_path, 'nogain', ['VOICES=1', 'GAIN=0', 'TAG=0'])
    per = len(l_g) / 14.0
    k = next(i for i in range(min(len(r_g), len(r_n))) if r_g[i] != r_n[i])
    assert 5.5 * per < k < 8 * per, (k, per)                             # the frame after the hook
    assert l_g[:k] == l_n[:k]
    end = next(i for i in range(k, len(r_g)) if not any(r_g[i:i + 200]))  # silent from here on
    assert 0.6 * per < end - k < 1.4 * per and not any(r_g[end:])        # about one frame long, then nothing
    ramp = r_g[k:end]
    assert max(abs(v) for v in ramp[:len(ramp) // 4]) > 2 * max(abs(v) for v in ramp[-len(ramp) // 4:])   # down, not a step
    assert max(abs(a - b) for a, b in zip(l_g, l_n)) < 0.02 * max(abs(v) for v in l_n)


def test_sound_kinds_take_the_groups_level(tmp_path):
    """host_aud_tag(ch, group) in the game's hook names the kind of the sound starting on a channel; engine_aud_mix(group,
    level) (the page's mixer) is taken at the next frame's start and changes the sounds of that kind playing now: voice 0
    (kind 2) is the same as untagged until frame 7, then about half (the limiter had pressed the loud original a little);
    voice 1 (kind 3, right) is untouched; tags at level 1 change nothing; the counters say played / extra / dropped."""
    lines, l_t, r_t, _ = run(tmp_path, 'tag', ['VOICES=1', 'GAIN=0', 'TAG=2'])
    ones, l_1, r_1, _ = run(tmp_path, 'tag1', ['VOICES=1', 'GAIN=0', 'TAG=1'])
    plain, l_n, r_n, _ = run(tmp_path, 'plain', ['VOICES=1', 'GAIN=0', 'TAG=0'])
    assert l_1 == l_n and r_1 == r_n                                     # level 1: bit for bit the untagged mix
    audio = lambda ls: [x for x in ls if x.startswith('audio ')][0]
    assert audio(ones) == audio(plain) != audio(lines)
    per = len(l_t) / 14.0
    k = next(i for i in range(len(l_t)) if l_t[i] != l_n[i])
    assert 5.5 * per < k < 8 * per, (k, per)                             # the frame after the hook
    seg = lambda ch, f0, f1: max(abs(v) for v in ch[int(f0 * per):int(f1 * per)])
    assert 0.5 < seg(l_t, 7.5, 8.8) / seg(l_n, 7.5, 8.8) < 0.75
    assert r_t[:k] == r_n[:k]
    counts = [x for x in lines if x.startswith('counts ')][0].split()[1:]
    assert counts == ['0', '1', '1', '1']                                # kind 2: once on a voice; kind 3: once on a voice, once dropped


def test_a_voice_plays_the_hosts_memory(tmp_path):
    """1.0.94 (SWIV KIT-GAP 22): a voice whose address is HOST_VMEM_BASE (AUDxLCH 0x0100) plays the host's memory - the same
    square written there by the hook sounds sample for sample as the one in chip RAM, the machine is the same."""
    lines, l_h, r_h, mem_h = run(tmp_path, 'host', ['VOICES=1', 'GAIN=0', 'TAG=0', 'SRC=1'])
    chip, l_c, r_c, mem_c = run(tmp_path, 'chip', ['VOICES=1', 'GAIN=0', 'TAG=0', 'SRC=0'])
    assert l_h == l_c and r_h == r_c and max(abs(v) for v in l_h) > 8000
    assert mem_h == mem_c and [x for x in lines if x.startswith('frames ')] == [x for x in chip if x.startswith('frames ')]


def test_the_base_level_takes_every_channel(tmp_path):
    """1.0.94: engine_aud_mix(-1, level) multiplies every channel's level from the next frame - tagged (voice 0, kind 2) and
    untagged alike; before it the mix is the same."""
    _, l_b, r_b, _ = run(tmp_path, 'base', ['VOICES=1', 'GAIN=0', 'TAG=3'])
    _, l_n, r_n, _ = run(tmp_path, 'nobase', ['VOICES=1', 'GAIN=0', 'TAG=1'])
    per = len(l_b) / 14.0
    k = next(i for i in range(len(l_b)) if l_b[i] != l_n[i])
    assert 5.5 * per < k < 8 * per and r_b[:k] == r_n[:k]
    seg = lambda ch, f0, f1: max(abs(v) for v in ch[int(f0 * per):int(f1 * per)])
    assert 0.5 < seg(l_b, 7.5, 8.8) / seg(l_n, 7.5, 8.8) < 0.75 and 0.45 < seg(r_b, 7.5, 8.8) / seg(r_n, 7.5, 8.8) < 0.75
