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
    regs = {0x096: 0x83e0}                                                       # DMAEN BPLEN COPEN BLTEN SPREN
    py = display.render(ram, COP, regs=regs).pixels
    c, rgb = host.render(ram, COP, regs=regs, exe=exe)
    bad = [(v, h) for v in range(312) for h in range(456) if py[v][h] != c[v][h]]
    assert not bad, (name, bad[:5], py[bad[0][0]][bad[0][1]] if bad else None, c[bad[0][0]][bad[0][1]] if bad else None)
    assert len(rgb) == 716 * 285 * 3 and display.to_screenshot(display.Frame(py, [], {})) == rgb


def test_ddfstrt_delay_and_sprite_slots_in_python():
    """DDFSTRT $24: scroll 8 lands where scroll 0 + the delay 2 * (DDFSTRT & 7) = 8 does (mod 16), so the scroll-0
    picture is the scroll-8 picture moved 8 pixels right; sprite 3 gets one word per line (striped), sprite 4 none,
    with DMACON known; without DMACON every slot is served as before."""
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
    assert data['arek.host'] == ['*.c', '*.h'] and 'selftest_audio.s' in data['arek.headless']
