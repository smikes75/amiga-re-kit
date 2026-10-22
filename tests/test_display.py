"""arek.display on synthetic chip RAM: Copper timing, bitplanes, playfields, sprites, colours.
(Checked against vAmiga screenshots too: a synthetic boot disk with dual playfield, EHB and
sprites, and five Superfrog frames - 0 differing pixels each; see the module docstring.)"""
import struct

import pytest

from arek import display
from arek.display import HALF

COP = 0x1000


def ram_with(copper, extra=()):
    ram = bytearray(0x80000)
    struct.pack_into('>%dH' % len(copper), ram, COP, *copper)
    for addr, words in extra:
        struct.pack_into('>%dH' % len(words), ram, addr, *words)
    return ram


def setup(planes=1, con0=None, con1=0, con2=0x24, ptrs=(0x10000,)):
    c = [0x100, con0 if con0 is not None else (planes << 12) | 0x200, 0x102, con1, 0x104, con2,
         0x08e, 0x2c81, 0x090, 0x2cc1, 0x092, 0x38, 0x094, 0xd0, 0x108, 0, 0x10a, 0]
    for k, p in enumerate(ptrs):
        c += [0x0e0 + 4 * k, p >> 16, 0x0e2 + 4 * k, p & 0xffff]
    return c


END = [0xffff, 0xfffe]


def test_first_bitplane_pixel_and_window():
    # one plane, first word $8000: only the very first fetched pixel is set
    ram = ram_with(setup() + [0x180, 0x000, 0x182, 0xf00] + END, [(0x10000, [0x8000])])
    f = display.render(ram, COP)
    line = f.pixels[0x2c]
    first = 2 * 0x38 + 17                         # 129
    assert line[first] == 0xf00 and line[first + 1] == 0 and line[first - 1] == 0
    assert f.pixels[0x2b][first] == 0             # above DIWSTRT: background
    assert display.to_screenshot(f)[((0x2c - 26) * 716 + 2 * first - 196) * 3:][:3] != b'\0\0\0'


def test_scroll_moves_the_playfield_right():
    ram = ram_with(setup(con1=0x0003) + [0x182, 0xf00] + END, [(0x10000, [0x8000])])
    assert display.render(ram, COP).pixels[0x2c][129 + 3] == 0xf00


def test_wait_changes_colour_mid_line():
    # WAIT $40,$61 then COLOR00 = $0f0: the change lands a few colour clocks after $60
    ram = ram_with([0x180, 0x00f, 0x4061, 0xfffe, 0x180, 0x0f0] + END)
    line = display.render(ram, COP).pixels[0x40]
    change = next(h for h, c in enumerate(line) if c == 0x0f0)
    assert line[0] == 0x00f and 2 * 0x60 <= change <= 2 * 0x60 + 12
    assert all(c == 0x0f0 for c in line[change:])


def test_skip_and_copjmp():
    # COP2LC -> list B; SKIP at line 0 skips the next MOVE, then COPJMP2 runs B (COLOR00 = $f0f)
    b = 0x2000
    ram = ram_with([0x084, 0, 0x086, b, 0x0001, 0xff01, 0x180, 0x00f, 0x08a, 0] + END,
                   [(b, [0x180, 0xf0f] + END)])
    f = display.render(ram, COP)
    assert f.pixels[2][300] == 0xf0f
    assert not any(w[2] == 0x180 and w[3] == 0x00f for w in f.writes)


def test_dual_playfield_priority():
    # PF1 (plane 1) colour 1, PF2 (plane 2) colour 9; PF2PRI decides who is in front
    words = [(0x10000, [0xffff] * 23), (0x11000, [0xffff] * 23)]          # first fetched line only
    for con2, front in ((0x00, 0x111), (0x40, 0x999)):
        c = setup(planes=2, con0=0x2600, con2=con2, ptrs=(0x10000, 0x11000)) + [0x182, 0x111, 0x192, 0x999] + END
        assert display.render(ram_with(c, words), COP).pixels[0x2c][200] == front


def test_ehb_marks_half_bright():
    ptrs = tuple(0x10000 + 0x1000 * k for k in range(6))
    words = [(p, [0xffff if k in (0, 5) else 0] * 23) for k, p in enumerate(ptrs)]   # index 33
    c = setup(planes=6, con0=0x6200, ptrs=ptrs) + [0x182, 0xeee] + END
    assert display.render(ram_with(c, words), COP).pixels[0x2c][200] == 0xeee | HALF


def _sprite(addr, vstart, vstop, hstart, rows, attach=False):
    pos = (vstart & 0xff) << 8 | (hstart >> 1) & 0xff
    ctl = (vstop & 0xff) << 8 | (0x80 if attach else 0) | (vstart >> 8 & 1) << 2 | (vstop >> 8 & 1) << 1 | hstart & 1
    return (addr, [pos, ctl] + [w for r in rows for w in r] + [0, 0])


def _sprite_copper(ptrs):
    c = []
    for k, p in enumerate(ptrs):
        c += [0x120 + 4 * k, p >> 16, 0x122 + 4 * k, p & 0xffff]
    return c


def test_sprite_position_colours_and_dma_reload():
    s0 = 0x20000
    rows = [(0x8000, 0x8000)] * 4
    # sprite 0: two appearances, the second from the control words DMA reads at the first VSTOP
    first = [0x4000 | 0x40, 0x4400] + [w for r in rows for w in r]
    second = [0x6000 | 0x50, 0x6200, 0x8000, 0x0000, 0x8000, 0x0000, 0, 0]
    ram = ram_with(_sprite_copper([s0] + [0x30000] * 7) + [0x1a6, 0xf00, 0x1a2, 0x0f0, 0x104, 0x24] + END,
                   [(s0, first + second)])
    f = display.render(ram, COP)
    hs = 0x40 << 1
    assert f.pixels[0x40][hs + 1] == 0xf00 and f.pixels[0x40][hs] == 0     # one pixel right of HSTART
    assert f.pixels[0x44][hs + 1] == 0                                       # VSTOP
    assert f.pixels[0x60][(0x50 << 1) + 1] == 0x0f0                          # reloaded, colour 1


def test_attached_sprites_use_sixteen_colours():
    a, b = _sprite(0x20000, 0x40, 0x42, 0x100, [(0x8000, 0)] * 2), \
        _sprite(0x20100, 0x40, 0x42, 0x100, [(0x8000, 0)] * 2, attach=True)
    ram = ram_with(_sprite_copper([0x20000, 0x20100] + [0x30000] * 6) + [0x1a2 + 2 * 4, 0x0ff] + END, [a, b])
    assert display.render(ram, COP).pixels[0x40][0x101] == 0x0ff               # index 1 | 4 = 5 -> COLOR21


def test_sprite_behind_playfield_by_priority():
    words = [(0x10000, [0xffff] * 23)]
    spr = _sprite(0x20000, 0x2c, 0x2e, 0x100, [(0x8000, 0)] * 2)
    base = setup(con2=0x00) + [0x182, 0x111, 0x1a2, 0xf00]
    for con2, want in ((0x24, 0xf00), (0x00, 0x111)):     # PF2P=4: sprites in front; 0: behind
        c = base + [0x104, con2] + _sprite_copper([0x20000] + [0x30000] * 7) + END
        assert display.render(ram_with(c, words + [spr]), COP).pixels[0x2c][0x101] == want


# measured on vAmiga screenshots (Superfrog Sonnet project); EHB halves the 8-bit components
@pytest.mark.parametrize('c, rgb', [(0x000, (0, 0, 0)), (0x400, (0x2b, 0, 0)), (0x777, (0x59, 0x59, 0x59)),
                                    (0xfff | HALF, (0x60, 0x60, 0x60)), (0x111 | HALF, (0, 0, 0))])
def test_vamiga_colours(c, rgb):
    assert display.vamiga_rgb(c) == rgb


def test_diff_and_plain_colours():
    a = bytes(716 * 285 * 3)
    b = bytearray(a)
    b[(10 * 716 + 20) * 3] = 1
    d = display.diff(a, bytes(b))
    assert d['pixels'] == 1 and d['box'] == (20, 10, 20, 10) and d['rows'] == [10]
    assert display.plain_rgb(0xf80) == (255, 136, 0) and display.plain_rgb(0xf80 | HALF) == (127, 68, 0)
    with pytest.raises(ValueError):
        display.diff(a, a[:-3])


def test_render_takes_cop1lc_and_registers_from_chips():
    ram = ram_with([0x180, 0x0f0] + END)
    f = display.render(ram, chips={'copper': {'COP1LC': COP}, 'agnus': {'BPLCON0': 0x0200}})
    assert f.pixels[100][100] == 0x0f0 and f.regs[0x180] == 0x0f0


def test_render_cli_and_mcp_on_a_capture_folder(tmp_path, capsys):
    import json
    from arek import cli
    ram = ram_with(setup() + [0x182, 0xf00] + END, [(0x10000, [0xf0f0] * 23)])
    cap = tmp_path / 'cap'
    cap.mkdir()
    (cap / 'ram_4004c_0.bin').write_bytes(bytes(ram))
    (cap / 'cpu.json').write_text(json.dumps({'ram_file': 'ram_4004c_0.bin', 'chips': {'copper': {'COP1LC': COP}}}))
    ref = display.to_screenshot(display.render(ram, COP))
    (cap / 'stable.raw').write_bytes(ref)
    assert cli.main(['render', str(cap)]) == 0
    out = capsys.readouterr().out
    assert '0 of 204060 pixels differ' in out and (cap / 'render.png').read_bytes()[:4] == b'\x89PNG'
    bad = bytearray(ref)
    bad[0:3] = b'\x01\x01\x01'
    (cap / 'stable.raw').write_bytes(bytes(bad))
    assert cli.main(['render', str(cap), '--fail']) == 1
    pytest.importorskip('mcp')
    from arek import mcp_server
    r = mcp_server.render(capture=str(cap))
    assert r['diff']['pixels'] == 1 and r['copper_writes'] > 5


def test_selftest_display_disk_is_bootable():
    from arek import adf
    from arek.headless import selftest
    d = selftest.display_disk()
    assert len(d) == adf.SIZE and struct.unpack('>I', d[4:8])[0] == adf.bootblock_checksum(d[:1024])
    assert len(selftest.DISPLAY_BOOT) <= 1012                    # fits the boot block
    # the copper list inside the payload (copied to $40000) starts with BPLCON0 = $4600
    off = 12 + 0x1a + (selftest.DISPLAY_COPPER - 0x40000)
    assert d[off:off + 4] == b'\x01\x00\x46\x00'
