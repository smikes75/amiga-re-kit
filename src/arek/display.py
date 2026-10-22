"""OCS display from RAM: what the Amiga shows for one frame, computed from chip RAM.

The Copper runs from COP1LC at the start of the frame and writes the registers; bitplane
and sprite DMA read chip RAM; Denise turns it into a 12-bit colour per lowres pixel. Nothing
about a game is assumed - the picture follows from RAM and the copper list alone.

    frame = render(ram, cop1lc, chips=None)      # Frame: 312 lines x 456 lowres pixels
    rgb = to_screenshot(frame)                   # 716 x 285 RGB24 like a vAmiga screenshot
    diff(rgb, open('stable.raw', 'rb').read())   # differing pixels and their bounding box

Modelled: Copper MOVE/WAIT (with masks)/SKIP, COPJMP1/2; lowres bitplanes 1-6 with DDF/DIW,
modulos, BPLCON1 scroll per playfield; dual playfield (BPLCON0 bit 10, BPLCON2 PF2PRI);
EHB (6 planes, no HAM, no dual playfield); sprites 0-7 with attached pairs, control words
loaded by DMA at the end of vertical blank (from pointers the Copper set in this frame) and
at VSTOP, priorities against the playfields (BPLCON2 PF1P/PF2P; in single
playfield mode PF2P). Not modelled: hires/superhires, HAM, collisions, interlace, AGA.

Timing measured against vAmiga in the Superfrog Sonnet project (``docs/M5-FRAME.md``, 0 px
on six frames): the Copper uses even colour clocks not taken by bitplane DMA (and not the
free slot at position 4 of each fetch group), a MOVE takes two slots, waking from a WAIT
takes one; a sprite starts one lowres pixel right of its HSTART; the first bitplane pixel
is at ``2*DDFSTRT + 17 + scroll``. The screenshot of vAmiga maps lowres pixel h of line v
to ``x = 2h - 196``, ``y = v - 26``.

Colours: ``vamiga_rgb`` is vAmiga's monitor conversion (YUV matrix, gamma 2.8 in / 2.2 out,
defaults), taken over from the Turrican II and Alien Breed renderers; EHB halves the 8-bit
components before it. It reproduces all 97 colours measured on Superfrog screenshots.
"""
import struct

LINES, CCKS = 312, 228                  # PAL lines per frame, colour clocks per line
WIDTH = 2 * CCKS                        # lowres pixels per line
SHOT_W, SHOT_H, SHOT_X, SHOT_Y = 716, 285, 196, 26
HALF = 0x1000                           # EHB: this colour at half brightness
VBLANK_END = 25                         # first line of sprite DMA (PAL)
_PLANE_AT = (99, 4, 6, 2, 99, 3, 5, 1)  # lowres fetch group: position -> bitplane (1-based)


def _rgb_table():
    y = (0.299, 0.587, 0.114)
    u = (-0.147, -0.289, 0.436)
    v = (0.615, -0.515, -0.100)
    m = [[y[i] + 1.140 * v[i] for i in range(3)],
         [y[i] - 0.396 * u[i] - 0.581 * v[i] for i in range(3)],
         [y[i] + 2.029 * u[i] for i in range(3)]]
    adj = [[[round(m[o][i] * ((x / 255.0) ** 2.8) * 255.0 * 65536.0) for x in range(256)]
            for i in range(3)] for o in range(3)]
    gamma = [round(min(255, max(0, (i / 255.0) ** (1 / 2.2) * 255.0))) for i in range(256)]
    return adj, gamma


_ADJ, _GAMMA = _rgb_table()
_CACHE = {}


def vamiga_rgb(c):
    """12-bit colour (``| HALF`` for an EHB half-bright one) -> (r, g, b) as vAmiga shows it."""
    if c not in _CACHE:
        rgb8 = [((c >> s) & 15) << 4 for s in (8, 4, 0)]
        if c & HALF:
            rgb8 = [x >> 1 for x in rgb8]
        out = []
        for o in range(3):
            acc = sum(_ADJ[o][i][rgb8[i]] for i in range(3))
            out.append(_GAMMA[0 if acc < 0 else 255 if acc > (255 << 16) else acc >> 16])
        _CACHE[c] = tuple(out)
    return _CACHE[c]


def plain_rgb(c):
    """12-bit colour -> (r, g, b) with each nibble x 17 (no monitor model)."""
    k = 1 if c & HALF else 0
    return tuple((((c >> s) & 15) * 17) >> k for s in (8, 4, 0))


class Frame:
    """``pixels[v][h]``: 12-bit colour (``| HALF``) of lowres pixel h on line v; ``writes``:
    the Copper's register writes ``(v, cck, reg, value)``; ``regs``: the registers at the end."""

    def __init__(self, pixels, writes, regs):
        self.pixels, self.writes, self.regs = pixels, writes, regs


class _Sprite:
    __slots__ = ('pt', 'pos', 'ctl', 'armed', 'on', 'pt_set')

    def __init__(self):
        self.pt = self.pos = self.ctl = 0
        self.armed = self.on = self.pt_set = False

    def vstart(self):
        return (self.pos >> 8) | ((self.ctl >> 2) & 1) << 8

    def vstop(self):
        return (self.ctl >> 8) | ((self.ctl >> 1) & 1) << 8

    def hstart(self):
        return ((self.pos & 0xff) << 1) | (self.ctl & 1)


# chips (cpu.json "chips" from arek bpstate) -> register offset
_CHIP_REGS = {('agnus', 'DMACON'): 0x096, ('agnus', 'BPLCON0'): 0x100, ('agnus', 'DDFSTRT'): 0x092,
              ('agnus', 'DDFSTOP'): 0x094, ('agnus', 'DIWSTRT'): 0x08e, ('agnus', 'DIWSTOP'): 0x090,
              ('denise', 'BPLCON1'): 0x102, ('denise', 'BPLCON2'): 0x104}


def render(ram, cop1lc=None, chips=None, colors=None, regs=None, lines=LINES):
    """One frame from chip RAM (bytes from address 0). ``cop1lc``: the Copper list (default:
    ``chips['copper']['COP1LC']``); ``chips``: cpu.json "chips" for the registers the Copper
    does not set; ``colors``: COLOR00-31 at the start of the frame (default 0);
    ``regs``: {offset: value} overriding both."""
    r = [0] * 0x100                                   # word registers, index = offset / 2
    for (chip, name), off in _CHIP_REGS.items():
        v = ((chips or {}).get(chip) or {}).get(name)
        if isinstance(v, int):
            r[off >> 1] = v
    for i, c in enumerate(colors or ()):
        r[(0x180 >> 1) + i] = c & 0xfff
    for off, v in (regs or {}).items():
        r[off >> 1] = v & 0xffff
    if cop1lc is None:
        cop1lc = ((chips or {}).get('copper') or {}).get('COP1LC', 0)
    cop2lc = ((chips or {}).get('copper') or {}).get('COP1LC#2', 0)
    size = len(ram)

    def rd(a):
        a &= 0x1ffffe
        return (ram[a] << 8) | ram[a + 1] if a + 1 < size else 0

    bpl = [0] * 6
    spr = [_Sprite() for _ in range(8)]
    lc = [cop1lc & 0x1ffffe, cop2lc & 0x1ffffe]
    writes, pixels = [], []

    def write(off, v, line, cck):
        r[off >> 1] = v
        writes.append((line, cck, off, v))
        if 0x0e0 <= off <= 0x0f6:
            k = (off - 0x0e0) >> 2
            bpl[k] = (bpl[k] & 0xffff) | (v & 0x1f) << 16 if not off & 2 else (bpl[k] & 0x1f0000) | (v & 0xfffe)
        elif 0x120 <= off <= 0x13e:
            s = spr[(off - 0x120) >> 2]
            s.pt = (s.pt & 0xffff) | (v & 0x1f) << 16 if not off & 2 else (s.pt & 0x1f0000) | (v & 0xfffe)
            s.pt_set = True
        elif 0x140 <= off <= 0x17e:
            s, kind = spr[(off - 0x140) >> 3], off & 6
            if kind == 0:
                s.pos = v
            elif kind == 2:
                s.ctl, s.armed, s.on = v, True, False     # writing CTL arms the sprite, waits for VSTART
        elif off == 0x080:
            lc[0] = (lc[0] & 0xffff) | (v & 0x1f) << 16
        elif off == 0x082:
            lc[0] = (lc[0] & 0x1f0000) | (v & 0xfffe)
        elif off == 0x084:
            lc[1] = (lc[1] & 0xffff) | (v & 0x1f) << 16
        elif off == 0x086:
            lc[1] = (lc[1] & 0x1f0000) | (v & 0xfffe)

    cop = {'pc': lc[0], 'need': 2, 'wait': None, 'skip': False, 'done': False}

    def copper(line, cck):
        if cop['done']:
            return
        if cop['wait'] is not None:
            wv, wh, vm, hm = cop['wait']
            if ((line & 0xff) & vm, cck & hm) >= (wv & vm, wh & hm):
                cop['wait'] = None                      # waking costs this slot
            return
        cop['need'] -= 1
        if cop['need']:
            return
        cop['need'] = 2
        w1, w2 = rd(cop['pc']), rd(cop['pc'] + 2)
        cop['pc'] += 4
        if cop['skip']:
            cop['skip'] = False
            return
        if not w1 & 1:                                  # MOVE
            off = w1 & 0x1fe
            if off == 0x088 or off == 0x08a:            # COPJMP1/2
                cop['pc'] = lc[(off - 0x088) >> 1]
            else:
                write(off, w2, line, cck)
            return
        if w1 == 0xffff and w2 == 0xfffe:
            cop['done'] = True
            return
        wv, wh = w1 >> 8, w1 & 0xfe
        vm, hm = ((w2 >> 8) & 0x7f) | 0x80, w2 & 0xfe
        if w2 & 1:                                      # SKIP
            cop['skip'] = ((line & 0xff) & vm, cck & hm) >= (wv & vm, wh & hm)
        else:
            cop['wait'] = (wv, wh, vm, hm)

    for v in range(lines):
        # sprites: at the end of vertical blank DMA loads the control words of every sprite
        # whose pointer the Copper set in this frame; VSTOP ends a sprite and loads the next
        # control words; VSTART starts it
        sline = []
        for k, s in enumerate(spr):
            if v == VBLANK_END and s.pt_set and not s.armed and not s.on:
                s.pos, s.ctl = rd(s.pt), rd(s.pt + 2)
                s.pt = (s.pt + 4) & 0x1ffffe
                s.armed = bool(s.pos or s.ctl)
            if s.on and v == s.vstop():
                s.on = False
                s.pos, s.ctl = rd(s.pt), rd(s.pt + 2)
                s.pt = (s.pt + 4) & 0x1ffffe
                s.armed = bool(s.pos or s.ctl)
            if s.armed and v == s.vstart() and s.vstart() != s.vstop():
                s.on, s.armed = True, False
            if s.on:
                sline.append((k, s.hstart() + 1, rd(s.pt), rd(s.pt + 2), (s.ctl >> 7) & 1))
                s.pt = (s.pt + 4) & 0x1ffffe
        line = [0] * WIDTH
        fetch, words, base, fetch_end, nplanes = 0, None, (0, 0), 0, 0
        for c in range(CCKS):
            ddfstrt, ddfstop = r[0x092 >> 1] or 0x38, r[0x094 >> 1] or 0xd0
            if c == ddfstrt:
                con0 = r[0x100 >> 1]
                n = (con0 >> 12) & 7
                diwstrt, diwstop = r[0x08e >> 1] or 0x2c81, r[0x090 >> 1] or 0x2cc1
                v0, sv = diwstrt >> 8, diwstop >> 8
                v1 = sv | (0 if sv & 0x80 else 0x100)
                if n and v0 <= v < v1 and not con0 & 0x8000:
                    nw = min((ddfstop - ddfstrt) // 8 + 1, 64)
                    words = [[rd(bpl[k] + 2 * i) for i in range(nw)] for k in range(n)]
                    for k in range(n):
                        mod = r[(0x108 if k % 2 == 0 else 0x10a) >> 1]
                        bpl[k] = (bpl[k] + 2 * nw + (mod - 0x10000 if mod & 0x8000 else mod)) & 0x1ffffe
                    con1 = r[0x102 >> 1]
                    start = 2 * ddfstrt + 17
                    base = (start + (con1 & 15), start + ((con1 >> 4) & 15))
                    fetch_end, nplanes, fetch = ddfstrt + 8 * nw, n, 1
                else:
                    fetch = -1
            if not c & 1:
                busy = False
                if fetch == 1 and ddfstrt <= c < fetch_end:
                    pos = (c - ddfstrt) & 7
                    busy = _PLANE_AT[pos] <= nplanes or (pos == 4 and v >= 1)
                if not busy:
                    copper(v, c)
            for h in (2 * c, 2 * c + 1):
                line[h] = _pixel(r, h, words if fetch == 1 else None, base, nplanes, sline)
        pixels.append(line)
    return Frame(pixels, writes, {i * 2: x for i, x in enumerate(r) if x})


def _pixel(r, h, words, base, n, sline):
    """Colour of lowres pixel h: playfields, then sprites by priority."""
    con0, con2 = r[0x100 >> 1], r[0x104 >> 1]
    dual = bool(con0 & 0x400)
    pf1 = pf2 = idx = 0
    if words:
        diwstrt, diwstop = r[0x08e >> 1] or 0x2c81, r[0x090 >> 1] or 0x2cc1
        if (diwstrt & 0xff) <= h < ((diwstop & 0xff) | 0x100):
            for k in range(n):
                i = h - base[k & 1]
                if 0 <= i < len(words[k]) * 16:
                    idx |= ((words[k][i >> 4] >> (15 - (i & 15))) & 1) << k
            if dual:
                pf1 = (idx & 1) | (idx >> 1 & 2) | (idx >> 2 & 4)          # planes 1, 3, 5
                pf2 = (idx >> 1 & 1) | (idx >> 2 & 2) | (idx >> 3 & 4)     # planes 2, 4, 6
    spc, spair = None, 4
    for k, hs, da, db, att in sline:
        if k & 1 and att:
            continue
        if hs <= h < hs + 16:
            b = 15 - (h - hs)
            s = ((da >> b) & 1) | ((db >> b) & 1) << 1
            mate = [x for x in sline if x[0] == k + 1 and x[4]] if not k & 1 else []
            if mate:
                s |= ((mate[0][2] >> b) & 1) << 2 | ((mate[0][3] >> b) & 1) << 3
                col = 16 + s
            else:
                col = 16 + 4 * (k >> 1) + s
            if s:
                spc, spair = col, k >> 1
                break                                   # lower numbered sprites win
    if dual:
        pf2pri = bool(con2 & 0x40)
        order = [(pf2, 8 + pf2, (con2 >> 3) & 7), (pf1, pf1, con2 & 7)]
        if not pf2pri:
            order.reverse()
        for nz, col, pri in order:                      # front playfield first
            if spc is not None and spair < pri:
                return r[(0x180 >> 1) + spc] & 0xfff
            if nz:
                return r[(0x180 >> 1) + col] & 0xfff
        return r[(0x180 >> 1) + spc] & 0xfff if spc is not None else r[0x180 >> 1] & 0xfff
    pri = (con2 >> 3) & 7                               # single playfield: PF2P
    if spc is not None and (spair < pri or not idx):
        return r[(0x180 >> 1) + spc] & 0xfff
    if n == 6 and not con0 & 0x0c00 and idx & 32:       # EHB
        return (r[(0x180 >> 1) + (idx & 31)] & 0xfff) | HALF
    return r[(0x180 >> 1) + idx] & 0xfff


def to_screenshot(frame, rgb=vamiga_rgb):
    """The frame as vAmiga's screenshot: 716 x 285 RGB24 bytes (``x = 2h - 196``, ``y = v - 26``)."""
    out = bytearray(SHOT_W * SHOT_H * 3)
    for y in range(SHOT_H):
        v = y + SHOT_Y
        if v >= len(frame.pixels):
            break
        line = frame.pixels[v]
        o = y * SHOT_W * 3
        for x in range(SHOT_W):
            h = (x + SHOT_X) >> 1
            if h < WIDTH:
                out[o:o + 3] = bytes(rgb(line[h]))
            o += 3
    return bytes(out)


def diff(a, b, width=SHOT_W):
    """Differing pixels between two RGB24 images of the same size:
    ``{'pixels': n, 'total': n, 'box': (x0, y0, x1, y1) or None, 'rows': [y, ...]}``."""
    if len(a) != len(b):
        raise ValueError('images differ in size: %d and %d bytes' % (len(a), len(b)))
    n, box, rows = 0, None, set()
    for i in range(0, len(a), 3):
        if a[i:i + 3] != b[i:i + 3]:
            x, y = (i // 3) % width, (i // 3) // width
            n += 1
            rows.add(y)
            box = (x, y, x, y) if box is None else (min(box[0], x), min(box[1], y), max(box[2], x), max(box[3], y))
    return {'pixels': n, 'total': len(a) // 3, 'box': box, 'rows': sorted(rows)}


def copper_list(ram, addr, limit=512):
    """The Copper list at ``addr`` as text lines (MOVE/WAIT/SKIP/END) - for reading, not timing."""
    from .copper import disassemble
    return disassemble(bytes(ram[addr:addr + 4 * limit]), addr, limit)


def words(ram, addr, n):
    return list(struct.unpack_from('>%dH' % n, ram, addr))
