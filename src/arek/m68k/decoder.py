"""Strict Motorola 68000 decoder and flow-graph walker.

Transplanted unchanged (apart from the module split) from ``recomp.py`` of
the Superfrog project, which carries the fixed ADDA/SUBA/CMPA size decoding.
The decoder deliberately raises :class:`Unsupported` on every instruction or
addressing mode it does not implement: a silent mistranslation would be worse
than no translation at all.

Public API
----------
decode(data, base, addr) -> Insn       one instruction, or raise Unsupported
successors(insn) -> [addr, ...]        where execution can continue
walk(data, base, start, lo, hi)        instructions reachable from ``start``
call_tree(data, base, roots, lo, hi)   same, transitively over bsr/jsr targets
STUBS                                   {(An, disp): name} indirect-call stubs
"""
import struct

import sys, argparse, struct

# ---------------------------------------------------------------- dekoder

SZ_B, SZ_W, SZ_L = 0, 1, 2
SZNAME = {SZ_B: 'b', SZ_W: 'w', SZ_L: 'l'}
CC = ['t', 'f', 'hi', 'ls', 'cc', 'cs', 'ne', 'eq',
      'vc', 'vs', 'pl', 'mi', 'ge', 'lt', 'gt', 'le']


class Unsupported(Exception):
    pass


class Reader:
    def __init__(self, data, base, pc):
        self.data, self.base, self.pc = data, base, pc

    def w(self):
        o = self.pc - self.base
        if o < 0 or o + 2 > len(self.data):
            raise Unsupported('outside the image $%x' % self.pc)
        v = struct.unpack('>H', self.data[o:o + 2])[0]
        self.pc += 2
        return v

    def l(self):
        o = self.pc - self.base
        if o < 0 or o + 4 > len(self.data):
            raise Unsupported('outside the image $%x' % self.pc)
        v = struct.unpack('>I', self.data[o:o + 4])[0]
        self.pc += 4
        return v


class EA:
    """Efektivni adresa prelozena do C.

    kind: 'd' (datovy registr), 'a' (adresovy), 'mem' (adresa v .addr),
          'imm' (konstanta v .imm)
    pre:  radky C, ktere se musi vykonat pred pouzitim (vypocet adresy,
          post/pre inkrement)
    """
    def __init__(self, kind, reg=None, addr=None, imm=None, pre=None, text='',
                 mode=None, areg=None, disp=None, absval=None):
        self.kind, self.reg, self.addr, self.imm = kind, reg, addr, imm
        self.pre = pre or []
        self.text = text
        self.mode, self.areg, self.disp, self.absval = mode, areg, disp, absval

    def read(self, sz):
        if self.kind == 'd':
            return {SZ_B: '(uint8_t)m->d[%d]' % self.reg,
                    SZ_W: '(uint16_t)m->d[%d]' % self.reg,
                    SZ_L: 'm->d[%d]' % self.reg}[sz]
        if self.kind == 'a':
            return {SZ_B: '(uint8_t)m->a[%d]' % self.reg,
                    SZ_W: '(uint16_t)m->a[%d]' % self.reg,
                    SZ_L: 'm->a[%d]' % self.reg}[sz]
        if self.kind == 'imm':
            return '0x%xu' % (self.imm & {SZ_B: 0xff, SZ_W: 0xffff, SZ_L: 0xffffffff}[sz])
        return {SZ_B: 'rd8(%s)', SZ_W: 'rd16(%s)', SZ_L: 'rd32(%s)'}[sz] % self.addr

    def write(self, sz, val):
        if self.kind == 'd':
            return 'setd(m, %d, %d, %s);' % (self.reg, sz, val)
        if self.kind == 'a':
            return 'seta(m, %d, %d, %s);' % (self.reg, sz, val)
        if self.kind == 'mem':
            return {SZ_B: 'wr8(%s, %s);', SZ_W: 'wr16(%s, %s);',
                    SZ_L: 'wr32(%s, %s);'}[sz] % (self.addr, val)
        raise Unsupported('zapis do %s' % self.kind)


def ea_allowed(mode, reg, need):
    """68000 addressing categories: 'd' data (no An), 'm' memory (no Dn/An), 'c' control
    ((An), (d16,An), (d8,An,Xn), abs, PC-relative), 'a' alterable (no PC-relative, no #imm)."""
    if mode == 7 and reg > 4:
        return False
    if 'd' in need and mode == 1:
        return False
    if 'm' in need and mode in (0, 1):
        return False
    if 'c' in need and (mode in (0, 1, 3, 4) or (mode == 7 and reg == 4)):
        return False
    if 'a' in need and mode == 7 and reg in (2, 3, 4):
        return False
    return True


def decode_ea(mode, reg, sz, r, tmp):
    """Vrati EA; `tmp` je generator jmen pomocnych promennych."""
    if mode == 0:
        return EA('d', reg=reg, text='d%d' % reg)
    if mode == 1:
        return EA('a', reg=reg, text='a%d' % reg)
    if mode == 2:
        return EA('mem', addr='m->a[%d]' % reg, text='(a%d)' % reg, mode=2, areg=reg, disp=0)
    if mode == 3:                                   # (An)+
        t = tmp()
        n = 2 if (sz == SZ_W) else (4 if sz == SZ_L else (2 if reg == 7 else 1))
        return EA('mem', addr=t, pre=['uint32_t %s = m->a[%d]; m->a[%d] += %d;'
                                      % (t, reg, reg, n)], text='(a%d)+' % reg)
    if mode == 4:                                   # -(An)
        t = tmp()
        n = 2 if (sz == SZ_W) else (4 if sz == SZ_L else (2 if reg == 7 else 1))
        return EA('mem', addr=t, pre=['m->a[%d] -= %d; uint32_t %s = m->a[%d];'
                                      % (reg, n, t, reg)], text='-(a%d)' % reg)
    if mode == 5:                                   # (d16,An)
        d = r.w()
        d = d - 0x10000 if d & 0x8000 else d
        return EA('mem', addr='(uint32_t)(m->a[%d] + (%d))' % (reg, d),
                  text='(%d,a%d)' % (d, reg), mode=5, areg=reg, disp=d)
    if mode == 6:                                   # (d8,An,Xn)
        ext = r.w()
        d8 = ext & 0xff
        d8 = d8 - 0x100 if d8 & 0x80 else d8
        xr, xa, xl = (ext >> 12) & 7, (ext >> 15) & 1, (ext >> 11) & 1
        x = ('m->a[%d]' if xa else 'm->d[%d]') % xr
        x = x if xl else '(uint32_t)(int32_t)(int16_t)%s' % x
        e = EA('mem', addr='(uint32_t)(m->a[%d] + %s + (%d))' % (reg, x, d8),
               text='(%d,a%d,%s%d)' % (d8, reg, 'a' if xa else 'd', xr),
               mode=6, areg=reg, disp=d8)
        e.xr, e.xa, e.xl = xr, xa, xl
        return e
    if mode == 7:
        if reg == 0:                                # abs.w
            a = r.w()
            a = a - 0x10000 if a & 0x8000 else a
            return EA('mem', addr='0x%xu' % (a & 0xffffffff), text='$%x.w' % (a & 0xffff),
                      mode=70, absval=a & 0xffffff)
        if reg == 1:                                # abs.l
            a = r.l()
            return EA('mem', addr='0x%xu' % a, text='$%x.l' % a, mode=71, absval=a & 0xffffff)
        if reg == 2:                                # (d16,PC)
            pc = r.pc
            d = r.w()
            d = d - 0x10000 if d & 0x8000 else d
            return EA('mem', addr='0x%xu' % ((pc + d) & 0xffffffff),
                      text='$%x(pc)' % (pc + d), mode=72, absval=(pc + d) & 0xffffff)
        if reg == 3:                                # (d8,PC,Xn)
            pc = r.pc
            ext = r.w()
            d8 = ext & 0xff
            d8 = d8 - 0x100 if d8 & 0x80 else d8
            xr, xa, xl = (ext >> 12) & 7, (ext >> 15) & 1, (ext >> 11) & 1
            x = ('m->a[%d]' if xa else 'm->d[%d]') % xr
            x = x if xl else '(uint32_t)(int32_t)(int16_t)%s' % x
            e = EA('mem', addr='(uint32_t)(0x%xu + %s)' % ((pc + d8) & 0xffffff, x),
                   text='$%x(pc,%s%d)' % (pc + d8, 'a' if xa else 'd', xr),
                   mode=73, areg=None, disp=0)
            e.xr, e.xa, e.xl, e.pcbase = xr, xa, xl, (pc + d8) & 0xffffff
            return e
        if reg == 4:                                # #imm
            v = r.w() if sz != SZ_L else r.l()
            if sz == SZ_B:
                v &= 0xff
            return EA('imm', imm=v, text='#%d' % v)
    raise Unsupported('adresni rezim %d/%d' % (mode, reg))


class Insn:
    def __init__(self, addr, end, kind, **kw):
        self.addr, self.end, self.kind = addr, end, kind
        self.__dict__.update(kw)
        self.text = kw.get('text', kind)


def decode(data, base, addr):
    """Dekoduje jednu instrukci; vraci Insn nebo vyhodi Unsupported."""
    r = Reader(data, base, addr)
    op = r.w()
    n = [0]

    def tmp():
        n[0] += 1
        return 't%d_%x' % (n[0], addr)

    hi = op >> 12
    sz2 = (op >> 6) & 3
    mode, reg = (op >> 3) & 7, op & 7
    dreg = (op >> 9) & 7

    def ea(sz, m=mode, rg=reg, need=''):
        if need and not ea_allowed(m, rg, need):
            raise Unsupported('%04x: addressing mode %d/%d not allowed here @%x' % (op, m, rg, addr))
        return decode_ea(m, rg, sz, r, tmp)

    def branch(target):
        if target & 1:
            raise Unsupported('%04x: branch to an odd address @%x' % (op, addr))
        return target

    # --- 0000: immediate a bitove operace
    if hi == 0:
        if (op & 0xf9c0) == 0x00c0:
            raise Unsupported('CMP2/CHK2/CAS @%x' % addr)
        if (op & 0x0100) == 0x0100 or (op & 0xff00) == 0x0800:   # BTST/BCHG/BCLR/BSET
            dyn = bool(op & 0x0100)
            if dyn and mode == 1:
                raise Unsupported('movep @%x' % addr)
            bitop = (op >> 6) & 3
            if dyn:
                src = 'm->d[%d]' % dreg
            else:
                src = '0x%xu' % r.w()
            # btst Dn: any data operand (even #imm); btst #: data but not #imm; the others: data alterable
            need = ('d' if dyn else 'd' if (mode, reg) != (7, 4) else 'da') if bitop == 0 else 'da'
            e = ea(SZ_B if mode != 0 else SZ_L, need=need)
            return Insn(addr, r.pc, 'bit', bitop=bitop, src=src, ea=e,
                        text=['btst', 'bchg', 'bclr', 'bset'][bitop])
        family = (op >> 9) & 7
        name = ['ori', 'andi', 'subi', 'addi', '?', 'eori', 'cmpi', '?'][family]
        if name == '?' or sz2 == 3:
            raise Unsupported('0000 op %04x @%x' % (op, addr))
        sz = sz2
        to_sr = (mode, reg) == (7, 4)                 # ori/andi/eori #,ccr (.b) / #,sr (.w)
        if to_sr and (name not in ('ori', 'andi', 'eori') or sz == SZ_L):
            raise Unsupported('%04x: %s to ccr/sr not allowed @%x' % (op, name, addr))
        imm = r.w() if sz != SZ_L else r.l()
        if sz == SZ_B:
            imm &= 0xff
        e = ea(sz, need='' if to_sr else 'da')
        return Insn(addr, r.pc, 'alui', name=name, sz=sz, imm=imm, ea=e,
                    text='%s.%s #%d,%s' % (name, SZNAME[sz], imm, e.text))
    # --- 0001/0010/0011: MOVE / MOVEA
    if hi in (1, 2, 3):
        sz = {1: SZ_B, 3: SZ_W, 2: SZ_L}[hi]
        dmode, drg = (op >> 6) & 7, dreg
        if sz == SZ_B and (mode == 1 or dmode == 1):
            raise Unsupported('%04x: byte move with an address register @%x' % (op, addr))
        src = ea(sz, need='-')
        dst = ea(sz, dmode, drg, need='a' if dmode == 1 else 'da')
        return Insn(addr, r.pc, 'move', sz=sz, src=src, dst=dst,
                    movea=(dmode == 1),
                    text='move%s.%s %s,%s' % ('a' if dmode == 1 else '',
                                              SZNAME[sz], src.text, dst.text))
    # --- 0100: ruzne
    if hi == 4:
        if op == 0x4e75:
            return Insn(addr, r.pc, 'rts', text='rts')
        if op == 0x4e71:
            return Insn(addr, r.pc, 'nop', text='nop')
        if (op & 0xffc0) == 0x4e80 or (op & 0xffc0) == 0x4ec0:
            e = ea(SZ_L, need='c')
            return Insn(addr, r.pc, 'jsr' if (op & 0x40) == 0 else 'jmp', ea=e,
                        text=('jsr ' if (op & 0x40) == 0 else 'jmp ') + e.text)
        if (op & 0xf1c0) == 0x41c0:                 # LEA
            e = ea(SZ_L, need='c')
            if e.kind != 'mem':
                raise Unsupported('lea z %s @%x' % (e.kind, addr))
            return Insn(addr, r.pc, 'lea', an=dreg, ea=e,
                        text='lea %s,a%d' % (e.text, dreg))
        if (op & 0xfb80) == 0x4880 and mode >= 2:   # MOVEM (rezim 0/1 = EXT)
            sz = SZ_L if (op & 0x40) else SZ_W
            to_mem = (op & 0x0400) == 0
            ok = (mode == 4 or ea_allowed(mode, reg, 'ca')) if to_mem else (mode == 3 or ea_allowed(mode, reg, 'c'))
            if not ok:
                raise Unsupported('%04x: movem addressing mode not allowed @%x' % (op, addr))
            mask = r.w()
            e = ea(sz)
            return Insn(addr, r.pc, 'movem', sz=sz, mask=mask, to_mem=to_mem,
                        ea=e, mode=mode, reg=reg,
                        text='movem.%s %s' % (SZNAME[sz], e.text))
        if (op & 0xffb8) == 0x4880:                 # EXT
            return Insn(addr, r.pc, 'ext', sz=SZ_W if (op & 0x40) == 0 else SZ_L,
                        reg=reg, text='ext')
        if (op & 0xfff8) == 0x4840:
            return Insn(addr, r.pc, 'swap', reg=reg, text='swap')
        if (op & 0xff00) == 0x4a00 and sz2 != 3:    # TST
            e = ea(sz2, need='da')
            return Insn(addr, r.pc, 'tst', sz=sz2, ea=e, text='tst.%s %s' % (SZNAME[sz2], e.text))
        if op == 0x4e73:
            return Insn(addr, r.pc, 'rte', text='rte')
        if (op & 0xffc0) in (0x40c0, 0x44c0, 0x46c0):       # MOVE SR/CCR
            e = ea(SZ_W)
            which = {0x40c0: 'from_sr', 0x44c0: 'to_ccr', 0x46c0: 'to_sr'}[op & 0xffc0]
            if not ea_allowed(mode, reg, 'da' if which == 'from_sr' else 'd'):
                raise Unsupported('%04x: move sr/ccr addressing mode not allowed @%x' % (op, addr))
            return Insn(addr, r.pc, 'sr', which=which, ea=e,
                        text='move %s (%s)' % (e.text, which))
        if (op & 0xff00) in (0x4200, 0x4400, 0x4600, 0x4000) and sz2 != 3:
            name = {0x4200: 'clr', 0x4400: 'neg', 0x4600: 'not', 0x4000: 'negx'}[op & 0xff00]
            e = ea(sz2, need='da')
            return Insn(addr, r.pc, name, sz=sz2, ea=e, text='%s.%s %s' % (name, SZNAME[sz2], e.text))
        if (op & 0xfff8) == 0x4e50:                 # LINK An,#d16
            d = r.w()
            d = d - 0x10000 if d & 0x8000 else d
            return Insn(addr, r.pc, 'link', an=reg, disp=d, text='link a%d,#%d' % (reg, d))
        if (op & 0xfff8) == 0x4e58:                 # UNLK An
            return Insn(addr, r.pc, 'unlk', an=reg, text='unlk a%d' % reg)
        if (op & 0xffc0) == 0x4840 and (mode in (2, 5, 6) or (mode == 7 and reg <= 3)):   # PEA <control ea>
            e = ea(SZ_L)
            return Insn(addr, r.pc, 'pea', ea=e, text='pea %s' % e.text)
        raise Unsupported('0100 op %04x @%x' % (op, addr))
    # --- 0101: ADDQ/SUBQ/Scc/DBcc
    if hi == 5:
        if sz2 == 3:
            cond = (op >> 8) & 15
            if mode == 1:                            # DBcc
                d = r.w()
                d = d - 0x10000 if d & 0x8000 else d
                return Insn(addr, r.pc, 'dbcc', cond=cond, reg=reg,
                            target=branch(addr + 2 + d), text='db%s d%d' % (CC[cond], reg))
            e = ea(SZ_B, need='da')
            return Insn(addr, r.pc, 'scc', cond=cond, ea=e,
                        text='s%s %s' % (CC[cond], e.text))
        data = dreg or 8
        if sz2 == SZ_B and mode == 1:
            raise Unsupported('%04x: addq/subq.b to an address register @%x' % (op, addr))
        e = ea(sz2, need='a')
        sub = bool(op & 0x0100)
        return Insn(addr, r.pc, 'addq', sz=sz2, imm=data, sub=sub, ea=e,
                    text='%sq.%s #%d,%s' % ('sub' if sub else 'add', SZNAME[sz2], data, e.text))
    # --- 0110: Bcc/BRA/BSR
    if hi == 6:
        cond = (op >> 8) & 15
        d = op & 0xff
        if d == 0:
            d = r.w()
            d = d - 0x10000 if d & 0x8000 else d
        elif d == 0xff:
            raise Unsupported('%04x: 32-bit branch displacement (68020) @%x' % (op, addr))
        else:
            d = d - 0x100 if d & 0x80 else d
        target = branch(addr + 2 + d)
        kind = 'bsr' if cond == 1 else ('bra' if cond == 0 else 'bcc')
        return Insn(addr, r.pc, kind, cond=cond, target=target,
                    text='%s $%x' % ({'bsr': 'bsr', 'bra': 'bra'}.get(kind, 'b' + CC[cond]), target))
    # --- 0111: MOVEQ
    if hi == 7:
        if op & 0x0100:
            raise Unsupported('%04x: not moveq (bit 8 set) @%x' % (op, addr))
        v = op & 0xff
        v = v - 0x100 if v & 0x80 else v
        return Insn(addr, r.pc, 'moveq', reg=dreg, imm=v & 0xffffffff,
                    text='moveq #%d,d%d' % (v, dreg))
    # --- 1000/1001/1011/1100/1101: OR/SUB/CMP/AND/ADD (+ADDA/SUBA/CMPA/MUL/DIV)
    if hi in (8, 9, 0xb, 0xc, 0xd):
        name = {8: 'or', 9: 'sub', 0xb: 'cmp', 0xc: 'and', 0xd: 'add'}[hi]
        opmode = (op >> 6) & 7
        if hi in (9, 0xd, 0xb) and opmode in (3, 7):
            # Bit 8 distinguishes .w and .l. Masking just two size bits
            # decoded both as .w, then treated a long immediate as opcodes.
            size = SZ_W if opmode == 3 else SZ_L
            e = ea(size)
            return Insn(addr, r.pc, name + 'a', sz=size, an=dreg, ea=e,
                        text='%sa.%s %s,a%d' % (name, SZNAME[size], e.text, dreg))
        if opmode == 3 and hi in (8, 0xc) and mode == 1:   # MULU/DIVU: data addressing only
            raise Unsupported('%s a%d @%x' % ('divu' if hi == 8 else 'mulu', reg, addr))
        if opmode == 3:                              # unsigned multiply / divide
            if hi == 0xc:                            # MULU
                e = ea(SZ_W, need='d')
                return Insn(addr, r.pc, 'mulu', reg=dreg, ea=e,
                            text='mulu %s,d%d' % (e.text, dreg))
            if hi == 8:                              # DIVU
                e = ea(SZ_W, need='d')
                return Insn(addr, r.pc, 'divu', reg=dreg, ea=e,
                            text='divu %s,d%d' % (e.text, dreg))
        if opmode == 7 and hi in (8, 0xc):           # signed multiply / divide
            name = 'divs' if hi == 8 else 'muls'
            if mode == 1:                            # data addressing only: no An source
                raise Unsupported('%s a%d @%x' % (name, reg, addr))
            e = ea(SZ_W, need='d')
            return Insn(addr, r.pc, name, reg=dreg, ea=e,
                        text='%s %s,d%d' % (name, e.text, dreg))
        direction = (op >> 8) & 1
        if hi == 0xb and direction:                  # EOR (nebo CMPM)
            if mode == 1:                            # CMPM (Ay)+,(Ax)+
                src, dst = ea(sz2, 3, reg), ea(sz2, 3, dreg)
                return Insn(addr, r.pc, 'cmpm', sz=sz2, src=src, dst=dst,
                            text='cmpm.%s %s,%s' % (SZNAME[sz2], src.text, dst.text))
            e = ea(sz2, need='da')
            return Insn(addr, r.pc, 'eor', sz=sz2, reg=dreg, ea=e,
                        text='eor.%s d%d,%s' % (SZNAME[sz2], dreg, e.text))
        if hi in (8, 0xc) and direction and mode in (0, 1):
            if sz2 == 0:                             # ABCD / SBCD  Dy,Dx  or  -(Ay),-(Ax)
                nm = 'abcd' if hi == 0xc else 'sbcd'
                txt = ('-(a%d),-(a%d)' if mode else 'd%d,d%d') % (reg, dreg)
                return Insn(addr, r.pc, 'bcd', sub=(hi == 8), rx=dreg, ry=reg, mem=bool(mode),
                            text='%s %s' % (nm, txt))
            om = (op >> 3) & 0x1f
            if hi == 0xc and om in (0x08, 0x09, 0x11):   # EXG Dx,Dy / Ax,Ay / Dx,Ay
                kx, ky = {0x08: ('d', 'd'), 0x09: ('a', 'a'), 0x11: ('d', 'a')}[om]
                return Insn(addr, r.pc, 'exg', rx=dreg, ry=reg, kx=kx, ky=ky,
                            text='exg %s%d,%s%d' % (kx, dreg, ky, reg))
            raise Unsupported('%s @%x' % ('pack/unpk (68020)' if hi == 8 else 'exg %04x' % op, addr))
        if hi in (9, 0xd) and direction and mode in (0, 1) and sz2 != 3:
            return Insn(addr, r.pc, 'addx', sz=sz2, sub=(hi == 9), rx=dreg, ry=reg,
                        mem=(mode == 1),
                        text='%sx.%s %s%d,%s%d' % ('sub' if hi == 9 else 'add', SZNAME[sz2],
                                                   '-(a' if mode == 1 else 'd', reg,
                                                   '-(a' if mode == 1 else 'd', dreg))
        if direction and hi != 0xb:                  # Dn,<ea>: memory alterable
            need = 'ma'
        elif name in ('or', 'and'):                  # <ea>,Dn: data
            need = 'd'
        else:                                        # add/sub/cmp <ea>,Dn: any, but no byte An
            need = 'd' if sz2 == SZ_B else '-'
        e = ea(sz2, need=need)
        return Insn(addr, r.pc, 'alu', name=name, sz=sz2, reg=dreg, ea=e,
                    to_ea=bool(direction) and hi != 0xb,
                    text='%s.%s %s' % (name, SZNAME[sz2],
                                       ('d%d,%s' % (dreg, e.text)) if direction
                                       else ('%s,d%d' % (e.text, dreg))))
    # --- 1110: posuny a rotace
    if hi == 0xe:
        if sz2 == 3:                                 # memory form: <ea> by one bit, word
            if op & 0x0800:
                raise Unsupported('bit field (68020) %04x @%x' % (op, addr))
            if mode < 2 or (mode == 7 and reg > 1):
                raise Unsupported('memory shift needs a memory alterable ea %04x @%x' % (op, addr))
            typ = (op >> 9) & 3
            left = bool(op & 0x0100)
            name = ['as', 'ls', 'rox', 'ro'][typ] + ('l' if left else 'r')
            e = ea(SZ_W)
            return Insn(addr, r.pc, 'shift', name=name, sz=SZ_W, mem=True, ea=e, cnt='1',
                        text='%s.w %s' % (name, e.text))
        typ = (op >> 3) & 3
        left = bool(op & 0x0100)
        name = ['as', 'ls', 'rox', 'ro'][typ] + ('l' if left else 'r')
        if op & 0x20:
            cnt = 'm->d[%d] & 63' % dreg
        else:
            cnt = '%d' % (dreg or 8)
        return Insn(addr, r.pc, 'shift', name=name, sz=sz2, reg=reg, cnt=cnt,
                    text='%s.%s %s,d%d' % (name, SZNAME[sz2], cnt, reg))
    raise Unsupported('op %04x @%x' % (op, addr))


# EA modes whose target is known at translation time: abs.w (70), abs.l (71), (d16,PC) (72)
FLOW_MODES = (70, 71, 72)


def successors(i):
    """Adresy, kam muze bezet vypocet po instrukci i."""
    k = i.kind
    if k == 'rts':
        return []
    if k == 'bra':
        return [i.target]
    if k in ('bcc', 'dbcc'):
        return [i.target, i.end]
    if k == 'bsr':
        return [i.end]
    if k == 'jmp':
        return [i.ea.absval] if getattr(i.ea, 'mode', None) in FLOW_MODES else []
    return [i.end]


# (registr, posun) -> jmeno stubu; plni se z CLI (--stub) nebo z API
STUBS = {}


class Flow:
    """What the translator is told about control flow it cannot see in the bytes.

    stops     addresses never translated (a branch into data): reaching one is unknown_call
    rets      addresses where translation ends with a return (a loop body becomes a function)
    exits     routines whose call ends the run (``exit_point``)
    externs   {address: C name} - the routine is replaced by an external ``name(M68 *m)``
    jtabs     {site: JumpTable} - ``jsr/jmp (d8,An,Dn)`` into a table of bra.w slots or pointers
    indirect  {site: [targets]} - the possible targets of ``jsr/jmp (An)``, or of a ``jmp abs``
              whose operand the program rewrites
    prefix    (name, lo, hi) - functions in [lo, hi) are called f_<name><addr> (an overlay
              module loaded at addresses another module also uses)
    lib       translate only the functions; the runtime comes from another translation
    """

    def __init__(self, stops=(), rets=(), exits=(), externs=None, jtabs=None, indirect=None,
                 prefix=None, lib=False):
        self.stops, self.rets, self.exits = set(stops), set(rets), set(exits)
        self.externs = dict(externs or {})
        self.jtabs = dict(jtabs or {})
        self.indirect = {a: list(t) for a, t in (indirect or {}).items()}
        self.prefix = prefix or ('', 0, 0)
        self.lib = lib

    def fname(self, addr):
        name, lo, hi = self.prefix
        return 'f_%s%06x' % (name if lo <= addr < hi else '', addr)

    def in_module(self, addr):
        return self.prefix[1] <= addr < self.prefix[2]

    def boundary(self, addr):
        """Translation does not continue into this address."""
        return addr in self.stops or addr in self.rets or addr in self.exits or addr in self.externs


NOFLOW = Flow()


class JumpTable:
    """``targets`` per slot (None = an rts slot), ``stride`` bytes per slot, ``table`` its
    address and ``origin`` the value of An at the jump (when the table starts below it)."""

    def __init__(self, targets, stride, table, origin=None):
        self.targets, self.stride, self.table = list(targets), stride, table
        self.origin = table if origin is None else origin


def jtab_targets(data, base, table, count, stride, kind):
    """Read ``count`` slots of a jump table: ``bra`` slots (bra.w/bra.s or rts) or ``ptr`` longs."""
    out = []
    for k in range(count):
        o = table + k * stride - base
        if kind == 'bra':
            w = struct.unpack_from('>H', data, o)[0]
            if w == 0x6000:
                out.append(table + k * stride + 2 + struct.unpack_from('>h', data, o + 2)[0])
            elif (w & 0xff00) == 0x6000:
                d = w & 0xff
                out.append(table + k * stride + 2 + (d - 0x100 if d & 0x80 else d))
            elif w == 0x4e75:
                out.append(None)
            else:
                raise Unsupported('slot %d of table $%x is not a bra: %04x' % (k, table, w))
        elif kind == 'ptr':
            out.append(struct.unpack_from('>I', data, o)[0] & 0xffffff)
        else:
            raise ValueError('jump table kind is bra or ptr, not %r' % kind)
    return out


def stub_for(ea):
    if getattr(ea, 'mode', None) in (2, 5) and getattr(ea, 'areg', None) is not None:
        return STUBS.get((ea.areg, ea.disp or 0))
    return None


def walk(data, base, start, lo, hi, flow=NOFLOW):
    """Instructions reachable from ``start`` plus the routines it calls. The
    flow graph is followed (branches, falls through, bsr/jsr targets), so data
    stored between code is never read as instructions.

    Returns ``(ins, calls, bad, indirect)``: decoded instructions by address,
    direct call targets, undecodable words and indirect jumps (both as
    ``(addr, why)`` - the frontiers that stay explicit)."""
    ins, calls, bad, indirect = {}, set(), [], []
    seen, work = set(), [start]
    while work:
        a = work.pop()
        if a in seen or not (lo <= a < hi) or flow.boundary(a):
            continue
        seen.add(a)
        try:
            i = decode(data, base, a)
        except Unsupported as e:
            bad.append((a, str(e).split(' @')[0]))
            continue
        ins[a] = i
        mode = getattr(getattr(i, 'ea', None), 'mode', None)
        if i.kind == 'bsr':
            calls.add(i.target)
        elif i.kind == 'jsr':
            if mode in FLOW_MODES:
                calls.add(i.ea.absval)
            elif a in flow.jtabs:
                calls.update(t for t in flow.jtabs[a].targets if t is not None)
            elif a in flow.indirect:
                calls.update(flow.indirect[a])
            elif not stub_for(i.ea):
                indirect.append((a, 'jsr ' + i.ea.text))
        elif i.kind == 'jmp' and mode in FLOW_MODES and a in flow.indirect:   # rewritten operand
            work.extend(flow.indirect[a])
            calls.update(flow.indirect[a])
            continue
        elif i.kind == 'jmp' and mode not in FLOW_MODES:
            if a in flow.jtabs:
                calls.update(t for t in flow.jtabs[a].targets if t is not None)
            elif a in flow.indirect:
                work.extend(flow.indirect[a])
                calls.update(flow.indirect[a])
            elif not stub_for(i.ea):
                indirect.append((a, 'jmp ' + i.ea.text))
        work.extend(successors(i))
    return ins, calls, bad, indirect


def call_tree(data, base, roots, lo, hi, flow=NOFLOW):
    """Entry address -> ``walk`` result, transitively over the whole call tree."""
    out, work = {}, list(roots)
    while work:
        s = work.pop()
        if s in out or not (lo <= s < hi) or s in flow.exits or s in flow.externs:
            continue
        ins, calls, bad, ind = walk(data, base, s, lo, hi, flow)
        out[s] = (ins, calls, bad, ind)
        work.extend(calls)
    return out

