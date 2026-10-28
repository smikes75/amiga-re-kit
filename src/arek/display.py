"""OCS display from RAM: what the Amiga shows for one frame, computed from chip RAM.

The Copper runs from COP1LC at the start of the frame and writes the registers; bitplane
and sprite DMA read chip RAM; Denise turns it into a 12-bit colour per lowres pixel. Nothing
about a game is assumed - the picture follows from RAM and the copper list alone.

    frame = render(ram, cop1lc, chips=None)      # Frame: 312 lines x 456 lowres pixels
    rgb = to_screenshot(frame)                   # 716 x 285 RGB24 like a vAmiga screenshot
    diff(rgb, open('stable.raw', 'rb').read())   # differing pixels and their bounding box

Modelled: Copper MOVE/WAIT (with masks)/SKIP, COPJMP1/2; lowres bitplanes 1-6 with DDF/DIW,
modulos, BPLCON1 scroll per playfield; dual playfield (BPLCON0 bit 10, BPLCON2 PF2PRI);
EHB (6 planes, no HAM, no dual playfield); sprites 0-7 with attached pairs, priorities against
the playfields (BPLCON2 PF1P/PF2P; in single playfield mode PF2P), their DMA as vAmiga's Agnus
and Denise do it (see ``render``): the control words at the end of vertical blank and at VSTOP,
the data from VSTART on, taken in the sprite's slots of the line ($15 + 4n and $17 + 4n, lines
25-310) after the Copper's writes before them, a data word arming the sprite and a CTL word
(by DMA or the Copper) disarming it, so a sprite whose VSTOP passes while sprite DMA is off
keeps showing its last data; sprites only inside the display window; HAM6 (BPLCON0 bit 11 with 6 planes: bits 4-5 of a pixel = palette / blue /
red / green modified from the previous pixel, the chain starting at COLOR00 on every line); hires
(two pixels per lowres pixel, 2 words per 8-CCK block, 4 planes, the Copper's slots in 4-CCK blocks;
``Frame.hires[v]`` holds the 912 hires pixels of such a line and ``to_screenshot`` uses them, the
lowres ``pixels`` hold the average of each pair); sprite DMA only with DMACON SPREN and DMAEN (when
DMACON is known; a Copper write to DMACON sets or clears its bits); with 6 lowres planes the Copper
gets both free even slots of a fetch group; the Copper runs vAmiga's state machine (as the bus
model does): FETCH, MOVE or WAIT_OR_SKIP, WAIT1, WAIT2, each in a free even cycle two cycles after
the last, the comparator on the beam two colour clocks ahead of the current line, so a WAIT whose
words end a line is first compared on the next one (WAIT 255,$DE then WAIT $21,0 passes on line
289, as Alien Breed II measured, G36). Not modelled: superhires, collisions, interlace
(the host alternates LOF), AGA. The HAM, hires, sprite DMA and 6-plane rules were measured by the
Alien Breed II project and ``arek selftest display`` against vAmiga (kit 0.7.1).

Timing measured against vAmiga in the Superfrog Sonnet project (``docs/M5-FRAME.md``, 0 px
on six frames): the Copper uses even colour clocks not taken by bitplane DMA (and not the
free slot at position 4 of each fetch group), a MOVE takes two slots, waking from a WAIT
takes one; a sprite starts one lowres pixel right of its HSTART; the first bitplane pixel
is at ``2*DDFSTRT + 17 + scroll``; with DDFSTRT not a multiple of 8 the scroll is delayed by
``2 * (DDFSTRT & 7)`` (mod 16), and on a line with bitplane DMA the sprite DMA slots from
``DDFSTRT - 1`` on are not served (DDFSTRT $24: sprite 3 gets one word, sprites 4-7 none; the
missing word keeps the old register), both measured by the Alien Breed II project against
vAmiga (needs DMACON from ``chips`` or ``regs``). The screenshot of vAmiga maps lowres pixel h
of line v to ``x = 2h - 196``, ``y = v - 26``.

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
_PLANE_AT_HR = (4, 2, 3, 1)             # hires fetch block of 4 CCK: position -> bitplane


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
    the Copper's register writes ``(v, cck, reg, value)``; ``regs``: the registers at the end;
    ``hires``: {v: [912 colours]} for lines drawn in hires (``pixels`` then holds the pair averages)."""

    def __init__(self, pixels, writes, regs, hires=None):
        self.pixels, self.writes, self.regs, self.hires = pixels, writes, regs, hires or {}


class _Sprite:
    """Agnus's sprite DMA state (vAmiga): ``dma`` on from VSTART to VSTOP, ``vstop`` the stop line (25 forced at the
    end of vertical blank), the pointer; Denise's ``armed``: shown from a data fetch until the next CTL write."""
    __slots__ = ('pt', 'pos', 'ctl', 'armed', 'dma', 'vstop', 'da', 'db')

    def __init__(self):
        self.pt = self.pos = self.ctl = self.da = self.db = 0
        self.vstop = 0
        self.armed = self.dma = False

    def vstart(self):
        return (self.pos >> 8) | ((self.ctl >> 2) & 1) << 8

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
        if off == 0x096:                                # DMACON: bit 15 sets, else clears
            r[off >> 1] = (r[off >> 1] | (v & 0x7fff)) if v & 0x8000 else (r[off >> 1] & ~(v & 0x7fff))
        else:
            r[off >> 1] = v
        writes.append((line, cck, off, v))
        if 0x0e0 <= off <= 0x0f6:
            k = (off - 0x0e0) >> 2
            bpl[k] = (bpl[k] & 0xffff) | (v & 0x1f) << 16 if not off & 2 else (bpl[k] & 0x1f0000) | (v & 0xfffe)
        elif 0x120 <= off <= 0x13e:
            s = spr[(off - 0x120) >> 2]
            s.pt = (s.pt & 0xffff) | (v & 0x1f) << 16 if not off & 2 else (s.pt & 0x1f0000) | (v & 0xfffe)
        elif 0x140 <= off <= 0x17e:
            s, kind = spr[(off - 0x140) >> 3], off & 6
            if kind == 0:
                s.pos = v
            elif kind == 2:                             # a CTL write sets VSTOP and disarms Denise
                s.ctl, s.armed = v, False
                s.vstop = (v >> 8) | ((v >> 1) & 1) << 8
        elif off == 0x080:
            lc[0] = (lc[0] & 0xffff) | (v & 0x1f) << 16
        elif off == 0x082:
            lc[0] = (lc[0] & 0x1f0000) | (v & 0xfffe)
        elif off == 0x084:
            lc[1] = (lc[1] & 0xffff) | (v & 0x1f) << 16
        elif off == 0x086:
            lc[1] = (lc[1] & 0x1f0000) | (v & 0xfffe)

    # the Copper as vAmiga's CopperEvents run it (and as the bus model does): every step needs a free bus cycle - even,
    # not taken by the bitplanes, not $E0 - and the next step comes two cycles later: FETCH (word 1), MOVE or
    # WAIT_OR_SKIP (word 2), then for a WAIT two more free cycles (WAIT1, WAIT2) before its comparator first runs, on
    # the beam two colour clocks ahead of the current line (h - $E0 in the line's last three cycles), vertically the
    # line's low byte. Passing at once, the next fetch follows two cycles later; otherwise the Copper wakes in the first
    # cycle the comparator passes (any cycle) and fetches two cycles after the first free even one. So a WAIT whose
    # words end a line is first compared on the next line (WAIT 255,$DE then WAIT $21,0 passes on line 289, G36). A
    # SKIP takes SKIP1 and SKIP2 and its comparator runs at the next fetch: true, it drops a MOVE that follows (a WAIT
    # clears it, as the emulator does). $FFFF $FFFE ends the list.
    cop = {'pc': lc[0], 'st': 1, 'next': 2, 'w1': 0, 'skip': False, 'skipcmd': False, 'wait': (0, 0, 0, 0)}

    def compare(v, c):
        wv, wh, vm, hm = cop['wait']
        vb = (v & 0xff) & vm
        if vb != (wv & vm):
            return vb > (wv & vm)
        hc = c + 2 if c < 0xe0 else c - 0xe0
        return (hc & hm) >= (wh & hm)

    def copper(v, c, busy):
        t, st = v * CCKS + c, cop['st']
        if not st or t < cop['next']:
            return
        if st == 6:                                     # waiting: the first cycle the comparator passes wakes it
            if not compare(v, c):
                cop['next'] = t + 1
                return
            st = cop['st'] = 9
        free = not (c & 1) and not busy and (c != 0xe0 or st == 9)
        if not free:
            cop['next'] = t + 1
            return
        if st == 9:                                     # awake in a free even cycle: the fetch two cycles later
            cop['st'] = 1
        elif st == 1:                                   # FETCH: the first word
            cop['w1'] = rd(cop['pc'])
            cop['pc'] += 2
            if cop['skipcmd']:
                cop['skip'], cop['skipcmd'] = compare(v, c), False
            cop['st'] = 3 if cop['w1'] & 1 else 2
        elif st == 2:                                   # MOVE: the second word, the write
            w2 = rd(cop['pc'])
            cop['pc'] += 2
            cop['st'] = 1
            if cop['skip']:
                cop['skip'] = False
            else:
                off = cop['w1'] & 0x1fe
                if off == 0x088 or off == 0x08a:        # COPJMP1/2
                    cop['pc'] = lc[(off - 0x088) >> 1]
                else:
                    write(off, w2, v, c)
        elif st == 3:                                   # WAIT_OR_SKIP: the second word
            w1, w2 = cop['w1'], rd(cop['pc'])
            cop['pc'] += 2
            if w1 == 0xffff and w2 == 0xfffe:
                cop['st'] = 0
                return
            cop['wait'] = (w1 >> 8, w1 & 0xfe, ((w2 >> 8) & 0x7f) | 0x80, w2 & 0xfe)
            cop['st'] = 7 if w2 & 1 else 4
        elif st == 4:                                   # WAIT1
            cop['st'] = 5
        elif st == 5:                                   # WAIT2: the comparator for the first time
            cop['skip'] = False
            if compare(v, c):
                cop['st'] = 1
            else:
                cop['st'], cop['next'] = 6, t + 1
                return
        elif st == 7:                                   # SKIP1
            cop['st'] = 8
        elif st == 8:                                   # SKIP2: the comparator runs at the next fetch
            cop['st'], cop['skipcmd'] = 1, True
        cop['next'] = t + 2

    def sprite_word(s):
        w = rd(s.pt)
        s.pt = (s.pt + 2) & 0x1ffffe
        return w

    hires = {}
    for v in range(lines):
        # sprites as vAmiga's Agnus and Denise do them: at the end of vertical blank (line 25, with sprite
        # DMA on) VSTOP of every sprite is forced to 25, so its control words are fetched; VSTART turns the
        # data DMA on, VSTOP off (the line's state is set before its slots); in the first slot of a sprite
        # ($15 + 4n) one at VSTOP fetches POS, otherwise with DMA on a data word (which arms Denise), in the
        # second ($17 + 4n) CTL (which disarms Denise) or the second data word. The slots are taken in the
        # line's order, after the Copper's writes before them (a DMACON write at the line start counts for
        # this line). With sprite DMA off (DMACON SPREN, DMAEN; DMACON unknown counts as on) or a slot the
        # bitplanes take (from DDFSTRT - 1 on a line with bitplane DMA, DMACON BPLEN known), nothing is fetched and the registers
        # keep their words: a sprite whose VSTOP passes with DMA off stays on the screen with its last data.
        # The slots exist on lines 25 to 310 only (vAmiga's DAS table masks the sprites outside them).
        def sdma():
            dmacon = r[0x096 >> 1]
            return (dmacon & 0x220) == 0x220 if dmacon else True
        for s in spr:
            if v == VBLANK_END:
                if sdma():
                    s.vstop = VBLANK_END
            elif v == lines - 1:
                s.dma = False
            elif v > VBLANK_END:
                if v == s.vstart():
                    s.dma = True
                if v == s.vstop:
                    s.dma = False
        con0 = r[0x100 >> 1]
        diwstrt, diwstop = r[0x08e >> 1] or 0x2c81, r[0x090 >> 1] or 0x2cc1
        v0, sv = diwstrt >> 8, diwstop >> 8
        vwin = v0 <= v < (sv | (0 if sv & 0x80 else 0x100))
        dmacon = r[0x096 >> 1]
        bpl_line = bool((con0 >> 12) & 7) and vwin and (dmacon & 0x300) == 0x300   # bitplane DMA takes slots (DMACON known)
        sline = []
        line = [0] * WIDTH
        hline = None
        fetch, words, base, fetch_end, nplanes, hr = 0, None, (0, 0), 0, 0, False
        ham = [r[0x180 >> 1] & 0xfff]                   # the HAM chain starts the line at COLOR00
        for c in range(CCKS):
            ddfstrt, ddfstop = r[0x092 >> 1] or 0x38, r[0x094 >> 1] or 0xd0
            if 0x15 <= c <= 0x33 and (c - 0x15) % 2 == 0 and VBLANK_END <= v < lines - 1:  # a sprite's DMA slot
                k, second = (c - 0x15) // 4, ((c - 0x15) // 2) % 2
                s = spr[k]
                free = sdma() and not (bpl_line and c >= ddfstrt - 1)
                if v == s.vstop:
                    s.dma = False
                    if free and not second:
                        s.pos = sprite_word(s)
                    elif free:
                        s.ctl, s.armed = sprite_word(s), False
                        s.vstop = (s.ctl >> 8) | ((s.ctl >> 1) & 1) << 8
                elif s.dma and free:
                    if not second:
                        s.da, s.armed = sprite_word(s), True
                    else:
                        s.db = sprite_word(s)
            if c == 0x34:
                sline = [(k, s.hstart() + 1, s.da, s.db, (s.ctl >> 7) & 1) for k, s in enumerate(spr) if s.armed]
            if c == ddfstrt:
                con0 = r[0x100 >> 1]
                n = (con0 >> 12) & 7
                diwstrt, diwstop = r[0x08e >> 1] or 0x2c81, r[0x090 >> 1] or 0x2cc1
                v0, sv = diwstrt >> 8, diwstop >> 8
                v1 = sv | (0 if sv & 0x80 else 0x100)
                hr = bool(con0 & 0x8000)
                if n and v0 <= v < v1:
                    nw = min(((ddfstop - ddfstrt) // 8 + 1) * (2 if hr else 1), 64)
                    n = min(n, 4 if hr else 6)
                    words = [[rd(bpl[k] + 2 * i) for i in range(nw)] for k in range(n)]
                    for k in range(n):
                        mod = r[(0x108 if k % 2 == 0 else 0x10a) >> 1]
                        bpl[k] = (bpl[k] + 2 * nw + (mod - 0x10000 if mod & 0x8000 else mod)) & 0x1ffffe
                    con1 = r[0x102 >> 1]
                    if hr:                                  # hires $3C = lowres $38: the same first pixel
                        start, ofs = 2 * ddfstrt + 9, 0
                    else:
                        start, ofs = 2 * ddfstrt + 17, 2 * (ddfstrt & 7)
                    base = (start + (((con1 & 15) + ofs) & 15), start + ((((con1 >> 4) & 15) + ofs) & 15))
                    fetch_end, nplanes, fetch = ddfstrt + (4 if hr else 8) * nw, n, 1
                else:
                    fetch = -1
            busy = False
            if not c & 1 and fetch == 1 and ddfstrt <= c < fetch_end:
                if hr:
                    busy = _PLANE_AT_HR[(c - ddfstrt) & 3] <= nplanes
                else:
                    pos = (c - ddfstrt) & 7                     # with 6 planes the Copper gets both free even slots
                    busy = _PLANE_AT[pos] <= nplanes or (pos == 4 and v >= 1 and nplanes < 6)
            copper(v, c, busy)
            for h in (2 * c, 2 * c + 1):
                if hr and fetch == 1:
                    if hline is None:
                        hline = [0] * (2 * WIDTH)
                        for x in range(2 * h):
                            hline[x] = line[x >> 1]
                    a = _pixel(r, h, words, base, nplanes, sline, ham, 0, vwin)
                    b = _pixel(r, h, words, base, nplanes, sline, ham, 1, vwin)
                    hline[2 * h], hline[2 * h + 1] = a, b
                    line[h] = _avg12(a, b)
                else:
                    line[h] = _pixel(r, h, words if fetch == 1 else None, base, nplanes, sline, ham, None, vwin)
                    if hline is not None:
                        hline[2 * h] = hline[2 * h + 1] = line[h]
        pixels.append(line)
        if hline is not None:
            hires[v] = hline
    return Frame(pixels, writes, {i * 2: x for i, x in enumerate(r) if x}, hires)


def _avg12(a, b):
    """The average of two 12-bit colours (two hires pixels in one lowres pixel)."""
    return (((((a >> 8) & 15) + ((b >> 8) & 15) + 1) >> 1) << 8) | (((((a >> 4) & 15) + ((b >> 4) & 15) + 1) >> 1) << 4) | (((a & 15) + (b & 15) + 1) >> 1)


def _pixel(r, h, words, base, n, sline, ham=None, sub=None, vwin=True):
    """Colour of lowres pixel h (``sub`` 0/1: the hires half of it): playfields, then sprites by
    priority; ``ham`` is the one-element HAM chain state of the line; outside the display window
    (``vwin`` vertically, DIWSTRT/DIWSTOP horizontally) everything is COLOR00."""
    con0, con2 = r[0x100 >> 1], r[0x104 >> 1]
    dual = bool(con0 & 0x400)
    pf1 = pf2 = idx = 0
    diwstrt, diwstop = r[0x08e >> 1] or 0x2c81, r[0x090 >> 1] or 0x2cc1
    inwin = vwin and (diwstrt & 0xff) <= h < ((diwstop & 0xff) | 0x100)
    if not inwin:
        if ham is not None and n == 6 and con0 & 0x0800:
            ham[0] = r[0x180 >> 1] & 0xfff
        return r[0x180 >> 1] & 0xfff
    if words:
        for k in range(n):
            i = h - base[k & 1]
            if sub is not None:
                i = 2 * i + sub
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
    if n == 6 and con0 & 0x0800 and ham is not None:    # HAM6: bits 4-5 = palette / blue / red / green
        c, ctl = idx & 15, (idx >> 4) & 3
        prev = ham[0]
        col = ((r[(0x180 >> 1) + c] & 0xfff) if ctl == 0 else (prev & 0xff0) | c if ctl == 1
               else (prev & 0x0ff) | (c << 8) if ctl == 2 else (prev & 0xf0f) | (c << 4))
        ham[0] = col
        if spc is not None and (spair < pri or not idx):
            return r[(0x180 >> 1) + spc] & 0xfff
        return col
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
        hl = frame.hires.get(v)
        if hl is not None:
            for x in range(SHOT_W):
                out[o:o + 3] = bytes(rgb(hl[x + SHOT_X]))
                o += 3
            continue
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
