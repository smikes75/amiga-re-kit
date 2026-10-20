"""Copper list disassembler (from the S.W.I.V. project). Game agnostic.

The Copper knows three instructions, two words each::

  MOVE  ($0RR, data)   bit 0 of the first word = 0; RR = custom register offset
  WAIT  (VP/HP, mask)  bit 0 = 1, bit 0 of the second word = 0
  SKIP  (VP/HP, mask)  bit 0 = 1, bit 0 of the second word = 1

The list ends with ``WAIT $FFFF,$FFFE``. Feed it a chunk of chip RAM at the
address COP1LC/COP2LC points to (``arek copper dump.bin --base 0x...``, or the
``mem save`` of a headless run).
"""

REG = {0x002: "DMACONR", 0x004: "VPOSR", 0x006: "VHPOSR", 0x008: "DSKDATR",
       0x00a: "JOY0DAT", 0x00c: "JOY1DAT", 0x00e: "CLXDAT", 0x010: "ADKCONR",
       0x012: "POT0DAT", 0x014: "POT1DAT", 0x016: "POTGOR", 0x018: "SERDATR",
       0x01a: "DSKBYTR", 0x01c: "INTENAR", 0x01e: "INTREQR",
       0x020: "DSKPTH", 0x022: "DSKPTL", 0x024: "DSKLEN", 0x026: "DSKDAT",
       0x028: "REFPTR", 0x02a: "VPOSW", 0x02c: "VHPOSW", 0x02e: "COPCON",
       0x030: "SERDAT", 0x032: "SERPER", 0x034: "POTGO", 0x036: "JOYTEST",
       0x038: "STREQU", 0x03a: "STRVBL", 0x03c: "STRHOR", 0x03e: "STRLONG",
       0x040: "BLTCON0", 0x042: "BLTCON1", 0x044: "BLTAFWM", 0x046: "BLTALWM",
       0x048: "BLTCPTH", 0x04a: "BLTCPTL", 0x04c: "BLTBPTH", 0x04e: "BLTBPTL",
       0x050: "BLTAPTH", 0x052: "BLTAPTL", 0x054: "BLTDPTH", 0x056: "BLTDPTL",
       0x058: "BLTSIZE", 0x05a: "BLTCON0L", 0x05c: "BLTSIZV", 0x05e: "BLTSIZH",
       0x060: "BLTCMOD", 0x062: "BLTBMOD", 0x064: "BLTAMOD", 0x066: "BLTDMOD",
       0x070: "BLTCDAT", 0x072: "BLTBDAT", 0x074: "BLTADAT",
       0x07e: "DSKSYNC", 0x080: "COP1LCH", 0x082: "COP1LCL", 0x084: "COP2LCH",
       0x086: "COP2LCL", 0x088: "COPJMP1", 0x08a: "COPJMP2", 0x08c: "COPINS",
       0x08e: "DIWSTRT", 0x090: "DIWSTOP", 0x092: "DDFSTRT", 0x094: "DDFSTOP",
       0x096: "DMACON", 0x098: "CLXCON", 0x09a: "INTENA", 0x09c: "INTREQ",
       0x09e: "ADKCON", 0x100: "BPLCON0", 0x102: "BPLCON1", 0x104: "BPLCON2",
       0x106: "BPLCON3", 0x108: "BPL1MOD", 0x10a: "BPL2MOD", 0x10c: "BPLCON4",
       0x10e: "CLXCON2", 0x1dc: "BEAMCON0", 0x1e4: "DIWHIGH", 0x1fc: "FMODE",
       0x1fe: "NOOP"}


def regname(r):
    if r in REG:
        return REG[r]
    if 0x0e0 <= r < 0x100:
        return "BPL%dPT%s" % ((r - 0x0e0) // 4 + 1, "HL"[(r >> 1) & 1])
    if 0x110 <= r < 0x120:
        return "BPL%dDAT" % ((r - 0x110) // 2 + 1)
    if 0x120 <= r < 0x140:
        return "SPR%dPT%s" % ((r - 0x120) // 4, "HL"[(r >> 1) & 1])
    if 0x140 <= r < 0x180:
        n, k = (r - 0x140) // 8, ((r - 0x140) // 2) % 4
        return "SPR%d%s" % (n, ["POS", "CTL", "DATA", "DATB"][k])
    if 0x180 <= r < 0x1c0:
        return "COLOR%02d" % ((r - 0x180) // 2)
    if 0x0a0 <= r < 0x0e0:
        return "AUD%d%s" % ((r - 0x0a0) // 16,
                            ["LCH", "LCL", "LEN", "PER", "VOL", "DAT"][((r - 0x0a0) % 16) // 2])
    return "$%03X" % r


def disassemble(data, base=0, limit=4096):
    """Returns a list of (address, text). Stops at WAIT $FFFF,$FFFE."""
    out = []
    for i in range(0, min(len(data) - 3, limit * 4), 4):
        w1 = (data[i] << 8) | data[i + 1]
        w2 = (data[i + 2] << 8) | data[i + 3]
        addr = base + i
        if w1 & 1:
            vp, hp = (w1 >> 8) & 0xff, w1 & 0xfe
            kind = "SKIP" if (w2 & 1) else "WAIT"
            if w1 == 0xffff and w2 == 0xfffe:
                out.append((addr, "END   (WAIT $FFFF,$FFFE)"))
                break
            out.append((addr, "%-5s VP=%3d HP=%3d  mask=$%04X" %
                        (kind, vp, hp, w2 & 0xfffe)))
        else:
            r = w1 & 0x1fe
            out.append((addr, "MOVE  %-9s <- $%04X" % (regname(r), w2)))
    return out


def format_listing(rows):
    return "\n".join("  $%06X  %s" % (addr, text) for addr, text in rows)
