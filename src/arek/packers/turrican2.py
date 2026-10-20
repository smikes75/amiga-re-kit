"""Turrican II three-stage decruncher (routine 0xdcc of MAIN; from ``depack_t2.py``).

Prepis tri stupnu z work/prog.txt (adresy v komentarich):
  1. 0xe2c  Huffman (kanonicke kody, tabulka v hlavicce) -> mezistupen H (delka L3)
  2. 0xf48  LZ pozpatku s dispatch tabulkou 27 escape bajtu       -> mezistupen Z (delka L2)
  3. 0x11be RLE dopredu se 3 escape bajty                        -> vystup (delka L1)

Hlavicka souboru: L1 (vysledna delka), L2 (delka po LZ), L3 (delka po
Huffmanu) jako 3 longy, pak data Huffmanu. LZ cte mezistupen H od konce,
RLE cte Z od zacatku. Overeno bajtove proti dumpum RAM z emulatoru
(build/dumps/bp_df8/e0e/e12.bin, soubor INTR), viz docs/LOADER.md.
"""
import struct


def be16(b, i):
    return (b[i] << 8) | b[i + 1]


def huffman(src, pos, count):
    """Stupen 1 (0xe2c). src: bajty, pos: index za tremi longy hlavicky.
    Vraci (vystup, pos za spotrebovanymi daty)."""
    d4 = be16(src, pos); pos += 2                 # 0xe50 maska
    d6x = src[pos]; pos += 1                      # 0xe54 sirka rychleho kodu
    n = src[pos]; pos += 1                        # 0xe66 pocet delek kodu
    col0 = [0] * n; col1 = [0] * n; col2 = [0] * n; col3 = [0] * n
    sym_extra = 0
    d5 = 2; d6 = 256; d7 = 0
    for i in range(n):                            # 0xe72
        d2 = src[pos]; d4b = src[pos + 1]; pos += 2
        sym_extra += 2 * d4b                      # 0xe7a self-modifying #255
        d4b += d2                                 # 0xe7e
        col0[i] = d2 & 0xffff
        col1[i] = d4b & 0xffff
        col2[i] = (d6 - 2 * d2) & 0xffff          # 0xe88-0xe8c
        col3[i] = (d7 - d4b) & 0xffff             # 0xe92-0xe94
        d3 = (d5 - d4b) & 0xffffffff              # 0xe9e
        d7 = (d7 + d3) & 0xffffffff
        d4b = (d4b - d2) & 0xffffffff             # 0xea4 (d4 -= d2)
        d6 = (d6 + 2 * d4b) & 0xffffffff
        d5 = (2 * d2) & 0xffffffff                # 0xeaa-0xeac
    nsym = 255 + sym_extra + 1                    # 0xed2 dbf: pocet bajtu
    symbols = src[pos:pos + nsym]; pos += nsym
    out = bytearray()
    d3 = (count - 1) & 0xffff                     # dolni slovo citace
    d5 = ((count - 1) >> 16) & 0xffff             # horni slovo citace
    d0 = 0; d1 = 0; d2 = 0
    while True:                                   # 0xeea
        if (d1 & 0xffff) < d6x:                   # cmpw d6,d1 ; bcs
            d2 = 0; idx = 0                       # a3 = a2 (col0[0])
            # dbf d1: pokud d1 != 0 -> d1 -= 1 a skok na 0xf06, jinak nacti slovo
            if (d1 & 0xffff) != 0:
                d1 = (d1 - 1) & 0xffff
            else:
                d0 = be16(src, pos); pos += 2; d1 = 15
        else:
            d1 = (d1 - d6x) & 0xffff
            d0 = ((d0 << d6x) | (d0 >> (16 - d6x))) & 0xffff if d6x else d0   # rolw
            d2 = d0 & d4
            idx = d6x - 1                         # a3 = a5 = &col0[d6x-1]
            # skok na 0xf0a bez posunu
            while True:
                c = col0[idx]; idx += 1
                if d2 >= c:                       # carry clear -> 0xf18
                    break
                if d1 == 0:                       # dbcc: d1 vycerpan
                    d1 = 0xffff
                    d0 = be16(src, pos); pos += 2; d1 = 15
                else:
                    d1 = (d1 - 1) & 0xffff
                x = (d0 >> 15) & 1; d0 = (d0 << 1) & 0xffff
                d2 = ((d2 << 1) | x) & 0xffff
            d2, idx, out, d3, d5, done = _emit(col1, col2, col3, symbols, d2, idx, out, d3, d5)
            if done:
                return bytes(out), pos
            continue
        # 0xf06: posun bitu a porovnani
        while True:
            x = (d0 >> 15) & 1; d0 = (d0 << 1) & 0xffff
            d2 = ((d2 << 1) | x) & 0xffff
            c = col0[idx]; idx += 1
            if d2 >= c:
                break
            if d1 == 0:
                d0 = be16(src, pos); pos += 2; d1 = 15
            else:
                d1 = (d1 - 1) & 0xffff
        d2, idx, out, d3, d5, done = _emit(col1, col2, col3, symbols, d2, idx, out, d3, d5)
        if done:
            return bytes(out), pos


def _emit(col1, col2, col3, symbols, d2, idx, out, d3, d5):
    i = idx - 1                                   # a3@(-2) = polozka i
    if d2 < col1[i]:                              # 0xf18 bcs -> 0xf30
        d2 = (2 * d2 + col2[i]) & 0xffff
        out.append(symbols[d2]); out.append(symbols[d2 + 1])
        d3 = d3 - 2
        if d3 >= 0:                               # bcc 0xeea
            return d2, idx, out, d3 & 0xffff, d5, False
        d3 &= 0xffff
        if d5 == 0:
            return d2, idx, out, d3, d5, True
        return d2, idx, out, d3, (d5 - 1) & 0xffff, False
    d2 = (d2 + col3[i]) & 0xffff                  # 0xf1e
    out.append(symbols[d2])
    if d3 != 0:                                   # dbf d3
        return d2, idx, out, (d3 - 1) & 0xffff, d5, False
    d3 = 0xffff
    if d5 == 0:                                   # dbf d5
        return d2, idx, out, d3, d5, True
    return d2, idx, out, d3, (d5 - 1) & 0xffff, False


# --- stupen 2: LZ pozpatku (0xf48) ---------------------------------------
_T11A8 = [0x006c, 0x0086, 0x00a2, 0x00c4, 0x0138, 0x010a, 0x0150, 0x014a, 0x0144, 0x013e]
_T11A0 = [-128, 0, 0x100, 0x200]


def lz_backward(h, out_len):
    """h = vystup Huffmanu (cte se od konce). Vraci bajty delky out_len."""
    src = h; p = len(h)                           # a0
    out = bytearray(out_len); o = out_len         # a2 (zapis pozpatku)
    table = [0] * 256                             # a5: ofset handleru od 0xfb0
    for i in range(10):                           # 0xf60
        p -= 1; table[src[p]] = (_T11A8[i] - 0x68) & 0xffff
    for i in range(16):                           # 0xf78
        p -= 1; table[src[p]] = 0x116 + 6 * i
    p -= 1; table[src[p]] = 0x1a0                 # 0xf88

    def copy(dist, n):
        nonlocal o
        for _ in range(n):
            o -= 1; out[o] = out[o + dist]

    while o > 0:                                  # 0xf9a: cmpal a1,a2 ; bls
        p -= 1; d0 = src[p]
        h_ = table[d0]
        if h_ == 0:                               # 0xfb0 literal
            o -= 1; out[o] = d0; continue
        if h_ == 0x04:                            # 0xfb4
            p -= 1; d1 = src[p]
            if d1 == 0: o -= 1; out[o] = d0; continue
            copy(d1, 7); continue
        if h_ == 0x1e:                            # 0xfce
            p -= 1; b = src[p]; d1 = b & 0xfc
            if d1 == 0: o -= 1; out[o] = d0; continue
            copy(d1 >> 2, 3 + (b & 3)); continue
        if h_ == 0x3a:                            # 0xfea
            p -= 1; d2 = src[p]
            if d2 == 0: o -= 1; out[o] = d0; continue
            p -= 1; d1 = ((d2 << 8) | src[p]) & 0x3ff
            copy(d1 + 1, (d2 >> 2) + 3); continue
        if h_ in (0x5c, 0xa2):                    # 0x100c / 0x1052
            p -= 1; d1 = src[p]
            if d1 == 0: o -= 1; out[o] = d0; continue
            p -= 1; d1 = (d1 << 8) | src[p]
            d3 = 0x401 if h_ == 0x5c else 0x2c01
            if d1 >= 0xc000:                      # 0x102c / 0x1030
                d1 &= 0x3fff; d2 = d1 & 7; d1 >>= 3
                copy((d1 + d3) & 0xffff, d2 + 4); continue
            if h_ == 0x5c:
                copy(d1, 4); continue
            p -= 1; d2 = src[p]                   # 0x1068
            copy(d1 - 256, d2); continue
        if h_ in (0xd0, 0xe8, 0xe2, 0xdc, 0xd6):  # 0x1080.. -> 0x109c
            d3 = {0xd0: 0xc01, 0xe8: 0x3401, 0xe2: 0x5401, 0xdc: 0x7401, 0xd6: 0x9401}[h_]
            p -= 1; d2 = src[p]
            if d2 == 0: o -= 1; out[o] = d0; continue
            p -= 1; d1 = ((d2 << 8) | src[p]) & 0x1fff
            copy((d1 + d3) & 0xffff, (d2 >> 5) + 4); continue
        if 0x116 <= h_ < 0x116 + 96 and (h_ - 0x116) % 6 == 0:   # 0x10c6+6i
            d3 = 63 + 63 * ((h_ - 0x116) // 6)
            p -= 1; b = src[p]; d1 = b & 0xfc
            if d1 == 0: o -= 1; out[o] = d0; continue
            copy((d1 >> 2) + d3, (b & 3) + 3); continue
        if h_ == 0x1a0:                           # 0x1150 delta longy
            p -= 1; d1 = src[p]
            if d1 == 0: o -= 1; out[o] = d0; continue
            d3 = _T11A0[(d1 >> 6) & 3]; d1 &= 0x3f
            b = [src[p - 1], src[p - 2], src[p - 3], src[p - 4]]; p -= 4
            d4 = (b[3] << 24) | (b[2] << 16) | (b[1] << 8) | b[0]
            for _ in range(d1 + 1):
                for k in range(4):                # zapis pozpatku: nejnizsi bajt na nejvyssi adresu
                    o -= 1; out[o] = (d4 >> (8 * k)) & 0xff
                p -= 1; d5 = src[p] + d3
                d4 = (d4 - d5) & 0xffffffff
            p += 1                                # 0x119a
            continue
        raise ValueError('neznamy handler %x' % h_)
    return bytes(out)


# --- stupen 3: RLE dopredu (0x11be) --------------------------------------
def rle_forward(z, out_len):
    src = z; p = 0
    table = [0] * 256
    table[src[p]] = 4; p += 1
    table[src[p]] = 14; p += 1
    table[src[p]] = 26; p += 1
    out = bytearray()

    def run(d1, d2):
        nonlocal p
        if d2 >= 3:
            out.extend(bytes([d1]) * d2); return
        if d2 == 2:                               # 32bit pocet
            cnt = (src[p] << 24) | (src[p + 1] << 16) | (src[p + 2] << 8) | src[p + 3]; p += 4
        else:                                     # d2 == 1: 16bit pocet
            cnt = (src[p] << 8) | src[p + 1]; p += 2
        out.extend(bytes([d1]) * cnt)

    while len(out) < out_len:                     # 0x11e2
        d0 = src[p]; p += 1
        t = table[d0]
        if t == 0:
            out.append(d0); continue
        if t == 4:                                # 0x11f4 nuly
            d2 = src[p]; p += 1
            if d2 == 0: out.append(d0); continue
            run(0, d2); continue
        if t == 14:                               # 0x11fe trojice
            d1 = src[p]; p += 1
            if d1 == 0: out.append(d0); continue
            out.extend(bytes([d1]) * 3); continue
        d1 = src[p]; p += 1                       # 0x120a
        if d1 == 0: out.append(d0); continue
        d2 = src[p]; p += 1
        run(d1, d2)
    return bytes(out[:out_len])


def unpack_t2(data):
    l1, l2, l3 = struct.unpack('>III', data[:12])
    h, pos = huffman(data, 12, l3)
    if len(h) != l3:
        raise ValueError('Huffman: %d != %d' % (len(h), l3))
    z = lz_backward(h, l2)
    return rle_forward(z, l1)
