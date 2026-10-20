"""Static recompilation of 68000 code to C (prototype, "M7" in the game docs).

One 68k routine becomes one C function; registers live in an ``M68`` context,
memory in ``MEM[]`` with a write log (``WRLOG``) so that a run can be compared
address by address against a RAM dump taken from the emulator. The embedded
runtime models only what the games used of the custom chips (DMACON,
BLTSIZE and an area-mode blitter); everything else is logged as
``HW_UNMODELLED`` rather than silently faked.

Verification recipe (see docs/RECOMP.md of the Turrican II project):
capture RAM + registers at the routine's call and at its return with
``arek.headless.bpstate``, run the recompiled function over the first
state and diff registers, CCR and every written address against the second.
"""
from . import decoder
from .decoder import SZ_B, SZ_W, SZ_L, SZNAME, Unsupported, decode, successors, call_tree

# ---------------------------------------------------------------- generator

RUNTIME = r'''
/* Vygenerovano tools/recomp.py - neupravovat rucne. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MEMSZ 0x80000u
uint8_t MEM[MEMSZ];
uint8_t WRLOG[MEMSZ];

typedef struct { uint32_t d[8], a[8]; int x, n, z, v, c; uint32_t srhi; } M68;

static void oob(uint32_t a) { fprintf(stderr, "pristup mimo chip RAM: %08x\n", a); exit(3); }

/* --- model hardwaru: jen to, co hra pouziva (docs/RECOMP.md 8) ------------ */
#define CUSTOM(a) (((a) & 0xfff000u) == 0xdff000u)
static uint16_t CREG[0x100];            /* $dff000-$dff1fe po slovech */
static uint8_t  HW_UNMODELLED[0x100];   /* registry, ktere jsme jen predstirali */
static char HW_NOTE[16][80];
static int HW_NOTES = 0, BZERO = 1;
static long BLITS = 0;

static void hw_note(const char *s) {
    for (int i = 0; i < HW_NOTES; i++) if (!strcmp(HW_NOTE[i], s)) return;
    if (HW_NOTES < 16) snprintf(HW_NOTE[HW_NOTES++], 80, "%s", s);
}
static uint32_t rd16(uint32_t a);
static void wr16(uint32_t a, uint32_t v);
static void run_blit(void);

static uint32_t hw_read(uint32_t off) {
    switch (off) {
    case 0x002:                          /* DMACONR: blitter u nas dobehne hned */
        return (CREG[0x096 >> 1] & 0x1fff) | (BZERO ? 0x2000 : 0);
    default:
        HW_UNMODELLED[off >> 1] = 1;
        return CREG[off >> 1];
    }
}
static void hw_write(uint32_t off, uint32_t v) {
    v &= 0xffff;
    switch (off) {
    case 0x096:                          /* DMACON: bit 15 = nastav/smaz */
        if (v & 0x8000) CREG[0x096 >> 1] |= v & 0x7fff;
        else CREG[0x096 >> 1] &= ~(v & 0x7fff);
        return;
    case 0x058:                          /* BLTSIZE: zapis spousti blit */
        CREG[off >> 1] = v;
        run_blit();
        return;
    default:
        if (off < 0x040 || off > 0x077) HW_UNMODELLED[off >> 1] = 1;
        CREG[off >> 1] = v;
        return;
    }
}
static uint32_t rd8(uint32_t a) {
    if (CUSTOM(a)) { uint32_t w = hw_read(a & 0x1fe); return (a & 1) ? (w & 0xff) : (w >> 8); }
    if (a >= MEMSZ) oob(a);
    return MEM[a];
}
static uint32_t rd16(uint32_t a) {
    if (CUSTOM(a)) return hw_read(a & 0x1fe);
    if (a + 1 >= MEMSZ) oob(a);
    return (MEM[a] << 8) | MEM[a + 1];
}
static uint32_t rd32(uint32_t a) { return (rd16(a) << 16) | rd16(a + 2); }
static void wr8(uint32_t a, uint32_t v) {
    if (CUSTOM(a)) { hw_note("bajtovy zapis do custom registru"); return; }
    if (a >= MEMSZ) oob(a);
    MEM[a] = v; WRLOG[a] = 1;
}
static void wr16(uint32_t a, uint32_t v) {
    if (CUSTOM(a)) { hw_write(a & 0x1fe, v); return; }
    wr8(a, v >> 8); wr8(a + 1, v);
}
static void wr32(uint32_t a, uint32_t v) { wr16(a, v >> 16); wr16(a + 2, v); }

/* Blitter v rezimu oblasti: A/B/C -> D podle minterm tabulky (BLTCON0 bity 7-0),
   posun A o ASH a B o BSH, prvni a posledni slovo radku maskovane AFWM/ALWM,
   po kazdem radku se k ukazatelum pricte modulo. Tri rezimy, ktere hra pouziva
   (kopie $09f0, vypln $01f0, cookie cut $0fca), jsou jen ruzne mintermy. */
static uint16_t minterm(int lf, uint32_t a, uint32_t b, uint32_t c) {
    uint32_t d = 0;
    if (lf & 0x01) d |= ~a & ~b & ~c;
    if (lf & 0x02) d |= ~a & ~b &  c;
    if (lf & 0x04) d |= ~a &  b & ~c;
    if (lf & 0x08) d |= ~a &  b &  c;
    if (lf & 0x10) d |=  a & ~b & ~c;
    if (lf & 0x20) d |=  a & ~b &  c;
    if (lf & 0x40) d |=  a &  b & ~c;
    if (lf & 0x80) d |=  a &  b &  c;
    return d & 0xffff;
}
static uint32_t bltptr(int off) {
    return (((uint32_t)CREG[off >> 1] << 16) | CREG[(off + 2) >> 1]) & 0x7ffffu;
}
static void set_bltptr(int off, uint32_t v) {
    CREG[off >> 1] = (v >> 16) & 0xffff; CREG[(off + 2) >> 1] = v & 0xffff;
}
static void run_blit(void) {
    uint16_t con0 = CREG[0x040 >> 1], con1 = CREG[0x042 >> 1];
    int ash = con0 >> 12, bsh = con1 >> 12, lf = con0 & 0xff;
    int usea = (con0 >> 11) & 1, useb = (con0 >> 10) & 1;
    int usec = (con0 >> 9) & 1, used = (con0 >> 8) & 1;
    int desc = (con1 >> 1) & 1;
    if (con1 & 1) { hw_note("blitter: rezim LINE (nemodelovano)"); return; }
    if (con1 & 0x1c) hw_note("blitter: vyplnovy rezim (nemodelovano)");
    uint16_t size = CREG[0x058 >> 1];
    int h = size >> 6, w = size & 0x3f;
    if (!h) h = 1024;
    if (!w) w = 64;
    uint32_t apt = bltptr(0x050), bpt = bltptr(0x04c);
    uint32_t cpt = bltptr(0x048), dpt = bltptr(0x054);
    int16_t amod = CREG[0x064 >> 1], bmod = CREG[0x062 >> 1];
    int16_t cmod = CREG[0x060 >> 1], dmod = CREG[0x066 >> 1];
    uint16_t afwm = CREG[0x044 >> 1], alwm = CREG[0x046 >> 1];
    int step = desc ? -2 : 2;
    BZERO = 1;
    BLITS++;
    for (int y = 0; y < h; y++) {
        uint32_t aold = 0, bold = 0;
        for (int x = 0; x < w; x++) {
            uint32_t adat = usea ? rd16(apt) : CREG[0x074 >> 1];
            uint32_t bdat = useb ? rd16(bpt) : CREG[0x072 >> 1];
            uint32_t cdat = usec ? rd16(cpt) : CREG[0x070 >> 1];
            if (x == 0) adat &= afwm;
            if (x == w - 1) adat &= alwm;
            uint32_t as, bs;
            if (!desc) {
                as = ((aold << 16) | adat) >> ash;
                bs = ((bold << 16) | bdat) >> bsh;
            } else {
                as = (((adat << 16) | aold) << ash) >> 16;
                bs = (((bdat << 16) | bold) << bsh) >> 16;
            }
            aold = adat; bold = bdat;
            uint16_t d = minterm(lf, as & 0xffff, bs & 0xffff, cdat);
            if (d) BZERO = 0;
            if (used) wr16(dpt, d);
            if (usea) apt += step;
            if (useb) bpt += step;
            if (usec) cpt += step;
            if (used) dpt += step;
        }
        if (usea) apt += amod;
        if (useb) bpt += bmod;
        if (usec) cpt += cmod;
        if (used) dpt += dmod;
    }
    set_bltptr(0x050, apt); set_bltptr(0x04c, bpt);
    set_bltptr(0x048, cpt); set_bltptr(0x054, dpt);
}

static const uint32_t MASK[3] = { 0xffu, 0xffffu, 0xffffffffu };
static const int BITS[3] = { 8, 16, 32 };

static void setd(M68 *m, int r, int sz, uint32_t v) {
    m->d[r] = (m->d[r] & ~MASK[sz]) | (v & MASK[sz]);
}
static void seta(M68 *m, int r, int sz, uint32_t v) {
    m->a[r] = (sz == 2) ? v : (uint32_t)(int32_t)(int16_t)v;   /* .w se rozsiruje znamenkem */
}
static int msb(uint32_t v, int sz) { return (v >> (BITS[sz] - 1)) & 1; }

static uint32_t sr_get(M68 *m) {
    return m->srhi | (m->x << 4) | (m->n << 3) | (m->z << 2) | (m->v << 1) | m->c;
}
static void sr_set(M68 *m, uint32_t v, int with_hi) {
    if (with_hi) m->srhi = v & 0xff00;       /* T/S/maska preruseni jen ulozime */
    m->x = (v >> 4) & 1; m->n = (v >> 3) & 1;
    m->z = (v >> 2) & 1; m->v = (v >> 1) & 1; m->c = v & 1;
}

static uint32_t f_logic(M68 *m, uint32_t r, int sz) {
    r &= MASK[sz];
    m->n = msb(r, sz); m->z = (r == 0); m->v = 0; m->c = 0;
    return r;
}
static uint32_t f_add(M68 *m, uint32_t s, uint32_t d, int sz) {
    uint32_t r = (s + d) & MASK[sz];
    int sm = msb(s, sz), dm = msb(d, sz), rm = msb(r, sz);
    m->n = rm; m->z = (r == 0);
    m->v = (sm == dm) && (rm != dm);
    m->c = (sm && dm) || (!rm && (sm || dm));
    m->x = m->c;
    return r;
}
static uint32_t f_sub(M68 *m, uint32_t s, uint32_t d, int sz) {   /* d - s */
    uint32_t r = (d - s) & MASK[sz];
    int sm = msb(s, sz), dm = msb(d, sz), rm = msb(r, sz);
    m->n = rm; m->z = (r == 0);
    m->v = (sm != dm) && (rm != dm);
    m->c = (sm && !dm) || (rm && (!dm || sm));
    m->x = m->c;
    return r;
}
static void f_cmp(M68 *m, uint32_t s, uint32_t d, int sz) {       /* jako sub, bez X */
    int x = m->x; f_sub(m, s, d, sz); m->x = x;
}
static uint32_t f_addx(M68 *m, uint32_t s, uint32_t d, int sz) {
    int z0 = m->z, x = m->x;
    uint32_t r = f_add(m, s, d, sz);
    int c1 = m->c, v1 = m->v;
    if (x) { r = f_add(m, 1, r, sz); m->c = m->c || c1; m->v = m->v || v1; }
    m->z = z0 && (r == 0);                   /* Z se jen nuluje */
    return r;
}
static uint32_t f_subx(M68 *m, uint32_t s, uint32_t d, int sz) {
    int z0 = m->z, x = m->x;
    uint32_t r = f_sub(m, s, d, sz);
    int c1 = m->c, v1 = m->v;
    if (x) { r = f_sub(m, 1, r, sz); m->c = m->c || c1; m->v = m->v || v1; }
    m->z = z0 && (r == 0);
    return r;
}
static uint32_t f_negx(M68 *m, uint32_t d, int sz) {
    uint32_t s = m->x;                       /* 0 - d - X */
    uint32_t r = f_sub(m, d, 0, sz);
    int z0 = m->z;
    r = f_sub(m, s, r, sz);
    m->z = z0 && m->z;                       /* Z se jen nuluje, nikdy nenastavuje */
    return r;
}
static void do_divu(M68 *m, int reg, uint32_t src) {
    src &= 0xffff;
    if (src == 0) { fprintf(stderr, "deleni nulou\n"); exit(5); }
    uint32_t q = m->d[reg] / src, r = m->d[reg] % src;
    if (q > 0xffff) { m->v = 1; return; }    /* pretecni: registr zustava */
    m->d[reg] = (r << 16) | (q & 0xffff);
    m->n = (q >> 15) & 1; m->z = (q == 0); m->v = 0; m->c = 0;
}
static uint32_t f_neg(M68 *m, uint32_t d, int sz) {
    uint32_t r = f_sub(m, d, 0, sz); return r;
}
static uint32_t f_shift(M68 *m, const char *k, uint32_t v, int cnt, int sz) {
    int b = BITS[sz]; uint32_t r = v & MASK[sz]; int last = 0;
    cnt &= 63;
    if (k[0] == 'l' || k[0] == 'a') {              /* lsl/lsr/asl/asr */
        int left = (k[2] == 'l');
        for (int i = 0; i < cnt; i++) {
            if (left) { last = msb(r, sz); r = (r << 1) & MASK[sz]; }
            else {
                last = r & 1;
                if (k[0] == 'a') r = (uint32_t)(((int32_t)(r << (32 - b)) >> (32 - b)) >> 1) & MASK[sz];
                else r = (r >> 1) & MASK[sz];
            }
        }
    } else {                                        /* rol/ror */
        int left = (k[2] == 'l' || k[1] == 'o');
        left = (k[strlen(k) - 1] == 'l');
        for (int i = 0; i < cnt; i++) {
            if (left) { last = msb(r, sz); r = ((r << 1) | last) & MASK[sz]; }
            else { last = r & 1; r = ((r >> 1) | ((uint32_t)last << (b - 1))) & MASK[sz]; }
        }
    }
    m->n = msb(r, sz); m->z = (r == 0); m->v = 0;
    m->c = cnt ? last : 0;
    if (cnt && (k[0] == 'l' || k[0] == 'a')) m->x = last;
    return r;
}
static int cond(M68 *m, int c) {
    switch (c) {
    case 0: return 1;                 case 1: return 0;
    case 2: return !m->c && !m->z;    case 3: return m->c || m->z;
    case 4: return !m->c;             case 5: return m->c;
    case 6: return !m->z;             case 7: return m->z;
    case 8: return !m->v;             case 9: return m->v;
    case 10: return !m->n;            case 11: return m->n;
    case 12: return m->n == m->v;     case 13: return m->n != m->v;
    case 14: return !m->z && (m->n == m->v);
    default: return m->z || (m->n != m->v);
    }
}
static void push32(M68 *m, uint32_t v) { m->a[7] -= 4; wr32(m->a[7], v); }
static void unknown_call(uint32_t a) { fprintf(stderr, "unknown routine %06x\n", a); exit(4); }
'''


class Gen:
    # (registr, posun) -> jmeno stubu: sdileno s decoder.STUBS
    @property
    def STUBS(self):
        return decoder.STUBS

    def __init__(self, data, base, funcs, cfg=None):
        self.data, self.base = data, base
        self.funcs = funcs                  # [(start, end, entry)] - linearni useky
        self.cfg = cfg or {}                # entry -> {adresa: Insn} z grafu toku
        self.entries = {e: (s, en) for s, en, e in funcs}
        for e in self.cfg:
            self.entries.setdefault(e, None)
        self.out = []
        self.stats = {}

    def emit(self, s=''):
        self.out.append(s)

    def gen(self):
        self.emit(RUNTIME)
        for entry in self.all_entries():
            self.emit('void f_%06x(M68 *m);' % entry)
        self.emit()
        for s, e, entry in self.funcs:
            self.gen_func(s, e, entry)
        for entry in sorted(self.cfg):
            self.gen_cfg_func(entry)
        return '\n'.join(self.out)

    def all_entries(self):
        return [e for _, _, e in self.funcs] + sorted(self.cfg)

    def gen_cfg_func(self, entry):
        """Telo z grafu toku: emituji se jen dosazitelne instrukce, propad na
        dalsi adresu se v poradi hlida a jinak se doplni `goto`."""
        ins = self.cfg[entry]
        order = sorted(ins)
        idx = {a: k for k, a in enumerate(order)}
        self.emit('/* vstup $%06x, %d instrukci z grafu toku */' % (entry, len(ins)))
        self.emit('void f_%06x(M68 *m) {' % entry)
        if order and order[0] != entry:
            self.emit('    goto L%06x;' % entry)
        for k, a in enumerate(order):
            i = ins[a]
            self.stats[i.kind] = self.stats.get(i.kind, 0) + 1
            self.emit('L%06x: ; /* %s */' % (a, i.text))
            for line in self.body(i, None, None, ins):
                self.emit('    ' + line)
            nxt = successors(i)
            if i.end in nxt and (k + 1 >= len(order) or order[k + 1] != i.end):
                self.emit('    goto L%06x;' % i.end)
        self.emit('    return;')
        self.emit('}')
        self.emit()

    def gen_func(self, start, end, entry):
        self.emit('/* $%06x - $%06x, vstup $%06x */' % (start, end, entry))
        self.emit('void f_%06x(M68 *m) {' % entry)
        if entry != start:
            self.emit('    goto L%06x;' % entry)
        addr = start
        while addr < end:
            ins = decode(self.data, self.base, addr)
            self.stats[ins.kind] = self.stats.get(ins.kind, 0) + 1
            self.emit('L%06x: ; /* %s */' % (addr, ins.text))
            for line in self.body(ins, start, end):
                self.emit('    ' + line)
            addr = ins.end
        self.emit('    return;')
        self.emit('}')
        self.emit()

    def br(self, target, start, end, ins=None):
        if ins is not None:
            if target in ins:
                return 'goto L%06x;' % target
        elif start <= target < end:
            return 'goto L%06x;' % target
        if target in self.entries:
            return 'f_%06x(m); return;' % target
        raise Unsupported('skok mimo funkci na $%x' % target)

    def body(self, i, start, end, ins=None):
        k = i.kind
        L = []

        def pre(*eas):
            for e in eas:
                L.extend(e.pre)

        if k == 'rts':
            L.append('m->a[7] += 4;')          # navratova adresa ulozena pri bsr/jsr
            L.append('return;')
        elif k == 'nop':
            L.append(';')
        elif k == 'move':
            pre(i.src, i.dst)
            t = 'v%06x' % i.addr
            L.append('uint32_t %s = %s;' % (t, i.src.read(i.sz)))
            if not i.movea:
                L.append('%s = f_logic(m, %s, %d);' % (t, t, i.sz))
            L.append(i.dst.write(i.sz, t))
        elif k == 'moveq':
            L.append('m->d[%d] = 0x%xu;' % (i.reg, i.imm))
            L.append('f_logic(m, 0x%xu, 2);' % i.imm)
        elif k == 'lea':
            L.append('m->a[%d] = %s;' % (i.an, i.ea.addr))
        elif k == 'tst':
            pre(i.ea)
            L.append('f_logic(m, %s, %d);' % (i.ea.read(i.sz), i.sz))
        elif k == 'clr':
            pre(i.ea)
            L.append(i.ea.write(i.sz, '0'))
            L.append('m->n = 0; m->z = 1; m->v = 0; m->c = 0;')
        elif k in ('neg', 'not', 'negx'):
            pre(i.ea)
            if k == 'neg':
                L.append(i.ea.write(i.sz, 'f_neg(m, %s, %d)' % (i.ea.read(i.sz), i.sz)))
            elif k == 'not':
                L.append(i.ea.write(i.sz, 'f_logic(m, ~%s, %d)' % (i.ea.read(i.sz), i.sz)))
            else:
                L.append(i.ea.write(i.sz, 'f_negx(m, %s, %d)' % (i.ea.read(i.sz), i.sz)))
        elif k == 'scc':
            pre(i.ea)
            L.append(i.ea.write(SZ_B, 'cond(m, %d) ? 0xff : 0x00' % i.cond))
        elif k == 'addq':
            pre(i.ea)
            if i.ea.kind == 'a':                     # adresovy registr: bez priznaku, 32 bitu
                L.append('m->a[%d] %s= %d;' % (i.ea.reg, '-' if i.sub else '+', i.imm))
            else:
                f = 'f_sub' if i.sub else 'f_add'
                L.append(i.ea.write(i.sz, '%s(m, %du, %s, %d)' % (f, i.imm, i.ea.read(i.sz), i.sz)))
        elif k == 'alui':
            pre(i.ea)
            nm = i.name
            if nm == 'cmpi':
                L.append('f_cmp(m, 0x%xu, %s, %d);' % (i.imm, i.ea.read(i.sz), i.sz))
            elif nm in ('addi', 'subi'):
                f = 'f_add' if nm == 'addi' else 'f_sub'
                L.append(i.ea.write(i.sz, '%s(m, 0x%xu, %s, %d)' % (f, i.imm, i.ea.read(i.sz), i.sz)))
            else:
                opc = {'ori': '|', 'andi': '&', 'eori': '^'}[nm]
                L.append(i.ea.write(i.sz, 'f_logic(m, %s %s 0x%xu, %d)'
                                    % (i.ea.read(i.sz), opc, i.imm, i.sz)))
        elif k == 'alu':
            pre(i.ea)
            nm, sz = i.name, i.sz
            dn = 'm->d[%d]' % i.reg
            dnr = {SZ_B: '(uint8_t)' + dn, SZ_W: '(uint16_t)' + dn, SZ_L: dn}[sz]
            if nm == 'cmp':
                L.append('f_cmp(m, %s, %s, %d);' % (i.ea.read(sz), dnr, sz))
            elif nm in ('add', 'sub'):
                f = 'f_add' if nm == 'add' else 'f_sub'
                if i.to_ea:
                    L.append(i.ea.write(sz, '%s(m, %s, %s, %d)' % (f, dnr, i.ea.read(sz), sz)))
                else:
                    L.append('setd(m, %d, %d, %s(m, %s, %s, %d));'
                             % (i.reg, sz, f, i.ea.read(sz), dnr, sz))
            else:
                opc = {'or': '|', 'and': '&'}[nm]
                if i.to_ea:
                    L.append(i.ea.write(sz, 'f_logic(m, %s %s %s, %d)' % (i.ea.read(sz), opc, dnr, sz)))
                else:
                    L.append('setd(m, %d, %d, f_logic(m, %s %s %s, %d));'
                             % (i.reg, sz, i.ea.read(sz), opc, dnr, sz))
        elif k in ('adda', 'suba', 'cmpa'):
            pre(i.ea)
            src = i.ea.read(i.sz)
            if i.sz == SZ_W:
                src = '(uint32_t)(int32_t)(int16_t)(%s)' % src
            if k == 'cmpa':
                L.append('f_cmp(m, %s, m->a[%d], 2);' % (src, i.an))
            else:
                L.append('m->a[%d] = m->a[%d] %s %s;'
                         % (i.an, i.an, '+' if k == 'adda' else '-', src))
        elif k == 'eor':
            pre(i.ea)
            L.append(i.ea.write(i.sz, 'f_logic(m, %s ^ m->d[%d], %d)' % (i.ea.read(i.sz), i.reg, i.sz)))
        elif k == 'shift':
            L.append('setd(m, %d, %d, f_shift(m, "%s", m->d[%d], %s, %d));'
                     % (i.reg, i.sz, i.name, i.reg, i.cnt, i.sz))
        elif k == 'swap':
            L.append('m->d[%d] = (m->d[%d] >> 16) | (m->d[%d] << 16);' % ((i.reg,) * 3))
            L.append('f_logic(m, m->d[%d], 2);' % i.reg)
        elif k == 'ext':
            if i.sz == SZ_W:
                L.append('setd(m, %d, 1, (uint32_t)(int32_t)(int8_t)m->d[%d]);' % (i.reg, i.reg))
                L.append('f_logic(m, (uint16_t)m->d[%d], 1);' % i.reg)
            else:
                L.append('m->d[%d] = (uint32_t)(int32_t)(int16_t)m->d[%d];' % (i.reg, i.reg))
                L.append('f_logic(m, m->d[%d], 2);' % i.reg)
        elif k == 'bit':
            pre(i.ea)
            sz = SZ_L if i.ea.kind == 'd' else SZ_B
            bits = 32 if sz == SZ_L else 8
            L.append('uint32_t b%06x = (%s) %% %d;' % (i.addr, i.src, bits))
            L.append('uint32_t o%06x = %s;' % (i.addr, i.ea.read(sz)))
            L.append('m->z = ((o%06x >> b%06x) & 1) == 0;' % (i.addr, i.addr))
            if i.bitop != 0:
                op = {1: '^', 2: '& ~', 3: '|'}[i.bitop]
                expr = ('o%06x %s (1u << b%06x)' % (i.addr, op, i.addr)) if i.bitop != 2 else \
                       ('o%06x & ~(1u << b%06x)' % (i.addr, i.addr))
                L.append(i.ea.write(sz, expr))
        elif k == 'movem':
            step = 2 if i.sz == SZ_W else 4
            if i.mode == 4:          # -(An): poradi A7..A0, D7..D0, adresa se snizuje pred zapisem
                names = [('a', r) for r in range(7, -1, -1)] + [('d', r) for r in range(7, -1, -1)]
            else:
                names = [('d', r) for r in range(8)] + [('a', r) for r in range(8)]
            in_list = any((i.mask >> b) & 1 and names[b] == ('a', i.reg) for b in range(16))
            if i.mode in (3, 4):     # (An)+ / -(An): vlastni ukazatel, ne pre z decode_ea
                L.append('uint32_t ma%06x = m->a[%d];' % (i.addr, i.reg))
                for bit, (kind, rg) in enumerate(names):
                    if not (i.mask >> bit) & 1:
                        continue
                    tgt = 'm->%s[%d]' % (kind, rg)
                    if i.mode == 4:
                        L.append('ma%06x -= %d;' % (i.addr, step))
                        L.append(('wr16(ma%06x, %s);' if i.sz == SZ_W else 'wr32(ma%06x, %s);')
                                 % (i.addr, tgt))
                    else:
                        if i.sz == SZ_W:
                            L.append('%s = (uint32_t)(int32_t)(int16_t)rd16(ma%06x);' % (tgt, i.addr))
                        else:
                            L.append('%s = rd32(ma%06x);' % (tgt, i.addr))
                        L.append('ma%06x += %d;' % (i.addr, step))
                if not in_list:      # kdyz je bazovy registr v seznamu, plati nactena hodnota
                    L.append('m->a[%d] = ma%06x;' % (i.reg, i.addr))
            else:
                pre(i.ea)
                L.append('uint32_t ma%06x = %s;' % (i.addr, i.ea.addr))
                off = 0
                for bit, (kind, rg) in enumerate(names):
                    if not (i.mask >> bit) & 1:
                        continue
                    tgt = 'm->%s[%d]' % (kind, rg)
                    if i.to_mem:
                        L.append((('wr16(ma%06x + %d, %s);' if i.sz == SZ_W
                                   else 'wr32(ma%06x + %d, %s);')) % (i.addr, off, tgt))
                    elif i.sz == SZ_W:   # cteni .w se vzdy rozsiruje znamenkem do 32 bitu
                        L.append('%s = (uint32_t)(int32_t)(int16_t)rd16(ma%06x + %d);'
                                 % (tgt, i.addr, off))
                    else:
                        L.append('%s = rd32(ma%06x + %d);' % (tgt, i.addr, off))
                    off += step
        elif k == 'rte':
            L.append('{ uint32_t sp = m->a[7]; uint32_t sr = rd16(sp);')
            L.append('  m->srhi = sr & 0xff00; m->x = (sr >> 4) & 1; m->n = (sr >> 3) & 1;')
            L.append('  m->z = (sr >> 2) & 1; m->v = (sr >> 1) & 1; m->c = sr & 1;')
            L.append('  m->a[7] = sp + 6; }')
            L.append('return;')
        elif k == 'sr':
            pre(i.ea)
            if i.which == 'from_sr':
                L.append(i.ea.write(SZ_W, 'sr_get(m)'))
            elif i.which == 'to_sr':
                L.append('sr_set(m, %s, 1);' % i.ea.read(SZ_W))
            else:
                L.append('sr_set(m, %s, 0);' % i.ea.read(SZ_W))
        elif k == 'addx':
            f = 'f_subx' if i.sub else 'f_addx'
            if i.mem:
                n = 2 if i.sz == SZ_W else (4 if i.sz == SZ_L else 1)
                L.append('m->a[%d] -= %d; m->a[%d] -= %d;' % (i.ry, n, i.rx, n))
                rd = {SZ_B: 'rd8', SZ_W: 'rd16', SZ_L: 'rd32'}[i.sz]
                wr = {SZ_B: 'wr8', SZ_W: 'wr16', SZ_L: 'wr32'}[i.sz]
                L.append('%s(m->a[%d], %s(m, %s(m->a[%d]), %s(m->a[%d]), %d));'
                         % (wr, i.rx, f, rd, i.ry, rd, i.rx, i.sz))
            else:
                dn = {SZ_B: '(uint8_t)m->d[%d]', SZ_W: '(uint16_t)m->d[%d]',
                      SZ_L: 'm->d[%d]'}[i.sz]
                L.append('setd(m, %d, %d, %s(m, %s, %s, %d));'
                         % (i.rx, i.sz, f, dn % i.ry, dn % i.rx, i.sz))
        elif k == 'bra':
            L.append(self.br(i.target, start, end, ins))
        elif k == 'bcc':
            L.append('if (cond(m, %d)) { %s }' % (i.cond, self.br(i.target, start, end, ins)))
        elif k == 'dbcc':
            L.append('if (!cond(m, %d)) { setd(m, %d, 1, (uint16_t)m->d[%d] - 1);'
                     % (i.cond, i.reg, i.reg))
            L.append('    if ((uint16_t)m->d[%d] != 0xffff) { %s } }'
                     % (i.reg, self.br(i.target, start, end, ins)))
        elif k == 'bsr':
            L.append('push32(m, 0x%xu);' % i.end)
            L.append(self.call(i.target))
        elif k == 'jsr':
            nm = self.stub_name(i.ea)
            if nm:
                L.append('%s(m);' % nm)
                return L
            L.append('push32(m, 0x%xu);' % i.end)
            if i.ea.kind != 'mem':
                raise Unsupported('jsr %s' % i.ea.kind)
            try:
                t = int(i.ea.addr, 0)
                L.append(self.call(t))
            except ValueError:
                L.append('unknown_call(%s);' % i.ea.addr)
        elif k == 'jmp':
            nm = self.stub_name(i.ea)
            if nm:
                L.append('%s(m); return;' % nm)
                return L
            try:
                t = int(i.ea.addr, 0)
                L.append(self.br(t, start, end, ins))
            except ValueError:
                raise Unsupported('neprimy jmp @%x' % i.addr)
        elif k in ('mulu', 'divu'):
            pre(i.ea)
            if k == 'mulu':
                L.append('m->d[%d] = (uint32_t)((uint16_t)m->d[%d] * (uint16_t)(%s));'
                         % (i.reg, i.reg, i.ea.read(SZ_W)))
                L.append('f_logic(m, m->d[%d], 2);' % i.reg)
            else:
                L.append('do_divu(m, %d, %s);' % (i.reg, i.ea.read(SZ_W)))
        else:
            raise Unsupported('generator neumi %s @%x' % (k, i.addr))
        return L

    def stub_name(self, ea):
        """Neprime volani pres pevnou bazi registru (skokova tabulka zavadece):
        prelozi se na volani stubu, ktery se doplni zvenci."""
        if getattr(ea, 'mode', None) in (2, 5) and ea.areg is not None:
            return decoder.STUBS.get((ea.areg, ea.disp or 0))
        return None

    def call(self, target):
        if target in self.entries:
            return 'f_%06x(m);' % target
        return 'unknown_call(0x%xu);' % target

MAIN_C = r'''
/* --- driver for verification against the emulator --------------------------------- */
int main(int argc, char **argv) {
    if (argc < 5) { fprintf(stderr, "recomp RAM.bin regs.txt out.bin wrlog.txt\n"); return 1; }
    FILE *f = fopen(argv[1], "rb");
    if (!f || fread(MEM, 1, MEMSZ, f) != MEMSZ) { fprintf(stderr, "RAM?\n"); return 1; }
    fclose(f);
    M68 m; memset(&m, 0, sizeof m);
    f = fopen(argv[2], "r");
    for (int i = 0; i < 8; i++) if (fscanf(f, "%x", &m.d[i]) != 1) return 1;
    for (int i = 0; i < 8; i++) if (fscanf(f, "%x", &m.a[i]) != 1) return 1;
    if (fscanf(f, "%d %d %d %d %d", &m.x, &m.n, &m.z, &m.v, &m.c) != 5) return 1;
    char name[64];
    uint32_t ret = 0;
    if (fscanf(f, "%63s", name) != 1) return 1;
    if (fscanf(f, "%x", &ret) == 1) push32(&m, ret);   /* jako bsr od volajiciho */
    fclose(f);
    ENTRY(name, &m);
    f = fopen(argv[3], "wb"); fwrite(MEM, 1, MEMSZ, f); fclose(f);
    f = fopen(argv[4], "w");
    for (int i = 0; i < 8; i++) fprintf(f, "%08x\n", m.d[i]);
    for (int i = 0; i < 8; i++) fprintf(f, "%08x\n", m.a[i]);
    fprintf(f, "%d %d %d %d %d\n", m.x, m.n, m.z, m.v, m.c);
    fprintf(f, "blits %ld\n", BLITS);
    for (int i = 0; i < HW_NOTES; i++) fprintf(f, "note %s\n", HW_NOTE[i]);
    for (int i = 0; i < 0x100; i++)
        if (HW_UNMODELLED[i]) fprintf(f, "hwreg %03x\n", i * 2);
    for (uint32_t a = 0; a < MEMSZ; a++) if (WRLOG[a]) fprintf(f, "w %x\n", a);
    fclose(f);
    return 0;
}
'''


def parse_func_spec(spec):
    """'START:END[:ENTRY]' (hex) -> (start, end, entry)."""
    p = spec.split(':')
    s, e = int(p[0], 16), int(p[1], 16)
    return s, e, int(p[2], 16) if len(p) > 2 else s


def add_stub(spec):
    """'An:DISP:NAME' - indirect calls through a fixed base register become calls to NAME."""
    reg, disp, name = spec.split(':')
    decoder.STUBS[(int(reg.lstrip('aA')), int(disp))] = name


def generate(data, base, funcs=(), auto=(), lo=0, hi=None, with_main=False):
    """Return (c_source, stats). ``funcs`` are (start, end, entry) linear ranges,
    ``auto`` are entry addresses whose bodies are discovered by walking the
    flow graph (transitively over bsr/jsr). Raises Unsupported / SystemExit-free."""
    hi = hi if hi is not None else base + len(data)
    cfg = {}
    if auto:
        tree = call_tree(data, base, list(auto), lo, hi)
        for e, (ins, calls, bad, ind) in tree.items():
            if bad:
                raise Unsupported('routine $%x, %s @%x' % (e, bad[0][1], bad[0][0]))
            if ind:
                raise Unsupported('routine $%x, indirect jump: %s @%x' % (e, ind[0][1], ind[0][0]))
            cfg[e] = ins
    g = Gen(data, base, list(funcs), cfg)
    src = g.gen()
    if with_main:
        disp = '\n'.join('    if (!strcmp(n, "f_%06x")) { f_%06x(m); return; }' % (e, e)
                         for e in g.all_entries())
        src += ('\nstatic void ENTRY(const char *n, M68 *m) {\n%s\n'
                '    fprintf(stderr, "unknown entry %%s\\n", n); exit(2);\n}\n' % disp)
        src += MAIN_C
    return src, dict(g.stats), g.all_entries()
