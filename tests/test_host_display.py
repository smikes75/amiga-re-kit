"""The C renderer (arek_display.h) against arek.display (Python) on synthetic chip RAM, and the two measured
rules both carry: the DDFSTRT delay of the first pixel and the sprite slots the bitplanes take."""
import struct

import pytest

from arek import display, host
from arek.display import HALF

COP = 0x1000
END = [0xffff, 0xfffe]


def ram_with(copper, extra=()):
    ram = bytearray(0x80000)
    struct.pack_into('>%dH' % len(copper), ram, COP, *copper)
    for addr, words in extra:
        struct.pack_into('>%dH' % len(words), ram, addr, *words)
    return ram


def setup(planes=1, con0=None, con1=0, con2=0x24, ptrs=(0x10000,), ddfstrt=0x38):
    c = [0x100, con0 if con0 is not None else (planes << 12) | 0x200, 0x102, con1, 0x104, con2,
         0x08e, 0x2c81, 0x090, 0x2cc1, 0x092, ddfstrt, 0x094, 0xd0, 0x108, 0, 0x10a, 0]
    for k, p in enumerate(ptrs):
        c += [0x0e0 + 4 * k, p >> 16, 0x0e2 + 4 * k, p & 0xffff]
    return c


def sprite(addr, vstart, vstop, hstart, rows, attach=False):
    pos = (vstart & 0xff) << 8 | (hstart >> 1) & 0xff
    ctl = (vstop & 0xff) << 8 | (0x80 if attach else 0) | (vstart >> 8 & 1) << 2 | (vstop >> 8 & 1) << 1 | hstart & 1
    return (addr, [pos, ctl] + [w for r in rows for w in r] + [0, 0])


def sprite_copper(ptrs):
    c = []
    for k, p in enumerate(ptrs):
        c += [0x120 + 4 * k, p >> 16, 0x122 + 4 * k, p & 0xffff]
    return c


PLANES = [(0x10000 + 0x2000 * k, [0xf0f0 ^ (0x1111 * k)] * 20 + [0x8001] * 20) for k in range(6)]
COLORS = [0x180 + 2 * i for i in range(32)]
PALETTE = [((i * 37) & 0xf) << 8 | ((i * 11) & 0xf) << 4 | (i & 0xf) for i in range(32)]


def with_colours(c):
    return c + [x for pair in zip(COLORS, PALETTE) for x in pair]


CASES = {
    'one plane': ram_with(with_colours(setup()) + END, PLANES[:1]),
    'five planes scrolled': ram_with(with_colours(setup(5, con1=0x35, ptrs=[p for p, _ in PLANES[:5]])) + END, PLANES[:5]),
    'dual playfield pf2 front': ram_with(with_colours(setup(4, con0=0x4600, con2=0x44, ptrs=[p for p, _ in PLANES[:4]])) + END, PLANES[:4]),
    'ehb': ram_with(with_colours(setup(6, ptrs=[p for p, _ in PLANES])) + END, PLANES),
    'wait and move mid line': ram_with(with_colours(setup()) + [0x4007, 0xfffe, 0x182, 0x0f0, 0x4051, 0xfffe, 0x182, 0x00f] + END, PLANES[:1]),
    'sprites attached and priority': ram_with(with_colours(setup(2, con2=0x02, ptrs=[p for p, _ in PLANES[:2]])) + sprite_copper([0x20000, 0x20100, 0x20200]) + END,
                                              PLANES[:2] + [sprite(0x20000, 0x40, 0x50, 0x100, [(0x8000, 0x4000)] * 16),
                                                            sprite(0x20100, 0x40, 0x50, 0x100, [(0x2000, 0x1000)] * 16, attach=True),
                                                            sprite(0x20200, 0x30, 0x60, 0x120, [(0xffff, 0)] * 48)]),
    'ham6': ram_with(with_colours(setup(6, con0=0x6a00, ptrs=[p for p, _ in PLANES])) + [0x4007, 0xfffe, 0x180, 0x123] + END, PLANES),
    'hires 4 planes': ram_with(with_colours(setup(4, con0=0xc200, ddfstrt=0x3c, ptrs=[p for p, _ in PLANES[:4]])) + [0x094, 0xd4, 0x4007, 0xfffe, 0x182, 0x0f0] + END, PLANES[:4]),
    'six planes copper mid line': ram_with(with_colours(setup(6, ptrs=[p for p, _ in PLANES])) + [0x4007, 0xfffe, 0x180, 0x0f0, 0x4055, 0xfffe, 0x180, 0x00f] + END, PLANES),
    'sprite dma off': ram_with(with_colours(setup(2, con2=0x02, ptrs=[p for p, _ in PLANES[:2]])) + sprite_copper([0x20000]) + END,
                               PLANES[:2] + [sprite(0x20000, 0x30, 0x60, 0x120, [(0xffff, 0)] * 48)]),
    # sprite DMA off between lines $48 and $50 (the Copper clears and sets DMACON SPREN): sprite 0's VSTOP $4c passes
    # without its slots, so it keeps its last data to the end of the vertical window ($12c); sprite 1 resumes after the
    # band, and its control words at VSTOP $58 come from the lagging data; sprite 2 reaches below the window
    'sprite dma off band': ram_with(with_colours(setup(2, con2=0x02, ptrs=[p for p, _ in PLANES[:2]])) + sprite_copper([0x20000, 0x20100, 0x20200])
                                    + [0x4807, 0xfffe, 0x096, 0x0020, 0x5007, 0xfffe, 0x096, 0x8020] + END,
                                    PLANES[:2] + [sprite(0x20000, 0x40, 0x4c, 0x120, [(0xffff, 0)] * 12),
                                                  sprite(0x20100, 0x40, 0x58, 0x140, [(0x8000, 0)] * 24),
                                                  sprite(0x20200, 0x100, 0x140, 0x160, [(0xffff, 0xffff)] * 64)]),
    'ddfstrt 24 with sprites 3 and 4': ram_with(with_colours(setup(3, con1=0x88, ddfstrt=0x24, ptrs=[p for p, _ in PLANES[:3]]))
                                                + sprite_copper([0x20200, 0x20200, 0x20200, 0x20000, 0x20100]) + END,
                                                PLANES[:3] + [sprite(0x20000, 0x40, 0x50, 0x180, [(0xf0f0, 0x0ff0)] * 16),
                                                              sprite(0x20100, 0x40, 0x50, 0x1a0, [(0xffff, 0xffff)] * 16),
                                                              sprite(0x20200, 0x40, 0x50, 0x1c0, [(0x8000, 0)] * 16)]),
}


@pytest.fixture(scope='module')
def exe(tmp_path_factory):
    if not host.compiler():
        pytest.skip('no C compiler')
    return host.compile_render(str(tmp_path_factory.mktemp('render') / 'arek_display_render'))


@pytest.mark.parametrize('name', sorted(CASES))
def test_c_renderer_equals_python(exe, name):
    ram = CASES[name]
    regs = {0x096: 0x8200 if name == 'sprite dma off' else 0x83e0}                # DMAEN (BPLEN COPEN BLTEN SPREN)
    frame = display.render(ram, COP, regs=regs)
    py = frame.pixels
    c, rgb = host.render(ram, COP, regs=regs, exe=exe)
    bad = [(v, h) for v in range(312) for h in range(456) if py[v][h] != c[v][h]]
    assert not bad, (name, bad[:5], py[bad[0][0]][bad[0][1]] if bad else None, c[bad[0][0]][bad[0][1]] if bad else None)
    assert host.render.hires == frame.hires
    assert len(rgb) == 716 * 285 * 3 and display.to_screenshot(frame) == rgb


def test_ddfstrt_delay_and_sprite_slots_in_python():
    """DDFSTRT $24: scroll 8 lands where scroll 0 + the delay 2 * (DDFSTRT & 7) = 8 does (mod 16), so the scroll-0
    picture is the scroll-8 picture moved 8 pixels right; sprite 3 gets one word per line (striped), sprite 4 none,
    with DMACON known; without DMACON every slot is served (the bitplanes take none, sprite DMA is on)."""
    ram8 = CASES['ddfstrt 24 with sprites 3 and 4']
    ram0 = ram_with(with_colours(setup(3, con1=0x00, ddfstrt=0x24, ptrs=[p for p, _ in PLANES[:3]])) + END, PLANES[:3])
    regs = {0x096: 0x83e0}
    p8, p0 = display.render(ram8, COP, regs=regs).pixels[0x2c], display.render(ram0, COP, regs=regs).pixels[0x2c]
    assert any(p8[h] for h in range(129, 400)) and all(p0[h] == p8[h - 8] for h in range(137, 400))
    line = display.render(ram8, COP, regs=regs).pixels[0x41]
    hs3, hs4 = 0x180 + 1, 0x1a0 + 1
    assert any(line[h] for h in range(hs3, hs3 + 16)) and len({line[h] for h in range(hs3, hs3 + 16)}) == 2   # one word: 2 colours
    assert not any(line[h] for h in range(hs4, hs4 + 16))                                                     # never fetched
    full = display.render(ram8, COP).pixels[0x41]
    assert any(full[h] for h in range(hs4, hs4 + 16)) and len({full[h] for h in range(hs3, hs3 + 16)}) > 2


def test_package_and_copy(tmp_path):
    from arek import cli
    assert cli.main(['host', 'copy', str(tmp_path)]) == 0
    for name in host.FILES:
        assert (tmp_path / name).exists()
    import tomllib
    from pathlib import Path
    data = tomllib.loads((Path(__file__).parent.parent / 'pyproject.toml').read_text())['tool']['setuptools']['package-data']
    assert data['arek.host'] == ['*.c', '*.h', '*.js'] and 'selftest_audio.s' in data['arek.headless']


def test_ham6_hires_sprite_dma_and_six_planes_in_python():
    """HAM6 chains from COLOR00 and modifies one component; hires lines carry 912 pixels and the lowres average;
    sprites vanish without SPREN; with 6 planes the Copper's MOVE lands earlier (the second free even slot)."""
    ham = display.render(CASES['ham6'], COP, regs={0x096: 0x83e0})
    line = ham.pixels[0x2c]
    assert any(line[h] for h in range(129, 400))
    # the first visible pixel of the line: bits 4-5 of the plane pattern decide the component modified from COLOR00 (0)
    idx = sum(((0xf0f0 ^ (0x1111 * k)) >> 15 & 1) << k for k in range(6))
    ctl, c = (idx >> 4) & 3, idx & 15
    first = line[129]
    assert (ctl == 0 and first == PALETTE[c]) or (ctl == 1 and first == c) or (ctl == 2 and first == c << 8) or (ctl == 3 and first == c << 4)
    assert ham.pixels[0x40][129] != line[129] or ham.regs.get(0x180) == 0x123     # the WAIT at line $40 changed COLOR00, the chain start
    hr = display.render(CASES['hires 4 planes'], COP, regs={0x096: 0x83e0})
    assert 0x2c in hr.hires and len(hr.hires[0x2c]) == 912 and 0x10 not in hr.hires
    hl, ll = hr.hires[0x2c], hr.pixels[0x2c]
    assert all(ll[h] == display._avg12(hl[2 * h], hl[2 * h + 1]) for h in range(129, 400))
    assert any(hl[2 * h] != hl[2 * h + 1] for h in range(129, 400))              # real hires detail, not pairs
    off = display.render(CASES['sprite dma off'], COP, regs={0x096: 0x8200}).pixels[0x40]
    on = display.render(CASES['sprite dma off'], COP, regs={0x096: 0x8220}).pixels[0x40]
    assert not any(off[h] for h in range(0x121, 0x131)) and any(on[h] for h in range(0x121, 0x131))
    six = display.render(CASES['six planes copper mid line'], COP, regs={0x096: 0x83e0}).writes
    five = display.render(ram_with(with_colours(setup(5, ptrs=[p for p, _ in PLANES[:5]])) + [0x4007, 0xfffe, 0x180, 0x0f0, 0x4055, 0xfffe, 0x180, 0x00f] + END, PLANES[:5]), COP, regs={0x096: 0x83e0}).writes
    w6 = [w for w in six if w[0] == 0x40 and w[2] == 0x180 and w[3] == 0x00f][0]
    w5 = [w for w in five if w[0] == 0x40 and w[2] == 0x180 and w[3] == 0x00f][0]
    assert (w6[1], w5[1]) == (0x5c, 0x5a)                                          # WAIT $54 (seen from $52, h + 2): 5 planes wake at $52 (slot of plane 6 free), 6 planes at $54


def test_sprite_dma_off_band_window_and_dmacon_writes_in_python():
    """A sprite whose VSTOP passes while sprite DMA is off keeps its last data until the vertical window ends; one whose
    DMA resumes vanishes at VSTOP as usual; sprites are blank below DIWSTOP; a Copper write to DMACON sets or clears bits."""
    f = display.render(CASES['sprite dma off band'], COP, regs={0x096: 0x83e0})
    px = f.pixels
    s0 = lambda v: any(px[v][h] for h in range(0x121, 0x131))
    s1 = lambda v: any(px[v][h] for h in range(0x141, 0x151))
    s2 = lambda v: any(px[v][h] for h in range(0x161, 0x171))
    assert s0(0x47) and s0(0x4b) and s0(0x4c) and s0(0x60) and s0(0x12b) and not s0(0x12c)   # kept to the window's end
    assert s1(0x47) and s1(0x50) and s1(0x57) and not s1(0x58) and not s1(0x60)          # VSTOP with DMA on: gone
    assert not s2(0xff) and s2(0x100) and s2(0x12b) and not s2(0x12c) and not s2(0x130)   # below DIWSTOP: blank
    assert f.regs[0x096] == 0x83e0 and [w[3] for w in f.writes if w[2] == 0x096] == [0x0020, 0x8020]
    ram = ram_with(with_colours(setup(2, con2=0x02, ptrs=[p for p, _ in PLANES[:2]])) + [0x090, 0x80c1] + sprite_copper([0x20000])
                   + [0x4807, 0xfffe, 0x096, 0x0020] + END, PLANES[:2] + [sprite(0x20000, 0x40, 0x4c, 0x120, [(0xffff, 0)] * 12)])
    sv = display.render(ram, COP, regs={0x096: 0x83e0}).pixels                                             # DIWSTOP v $80
    assert any(sv[0x7f][h] for h in range(0x121, 0x131)) and not any(sv[0x80][h] for h in range(0x121, 0x131))
