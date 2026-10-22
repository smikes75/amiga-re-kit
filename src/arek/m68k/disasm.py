"""Text disassembly straight from the strict decoder (no objdump needed).

Two modes: linear (``listing``), which marks every undecodable word and goes
on with the next one (``dcw=True`` writes it as ``dc.w $xxxx ; reason`` so the
listing reassembles), and flow-graph (``listing_walk``) which only lists reachable
instructions - the honest view when data sits between routines.
"""
from . import decoder


def listing(data, base, lo, hi, limit=None, dcw=False, cycles=False):
    """Linear decode of [lo, hi). Returns list of (addr, bytes_hex, text); with ``cycles``
    the text ends with the 68000 clock count (arek.m68k.timing)."""
    out, addr = [], lo
    end = min(hi, base + len(data))
    while addr < end and (limit is None or len(out) < limit):
        try:
            i = decoder.decode(data, base, addr)
        except (decoder.Unsupported, Exception) as e:   # struct.error at image end
            w = data[addr - base:addr - base + 2].hex()
            why = str(e).split(' @')[0]
            out.append((addr, w, ('dc.w $%s ; %s' if dcw else '?? %s (%s)') % (w, why)))
            addr += 2
            continue
        raw = data[addr - base:i.end - base].hex()
        out.append((addr, raw, _clk(i) if cycles else i.text))
        addr = i.end
    return out


def _clk(i):
    from . import timing
    return '%-32s ; %s clk' % (i.text, timing.describe(i))


def listing_walk(data, base, start, lo, hi, cycles=False, flow=decoder.NOFLOW):
    """Reachable instructions from ``start`` (plus directly called routines)."""
    tree = decoder.call_tree(data, base, [start], lo, hi, flow)
    out = {}
    frontiers = []
    for entry, (ins, calls, bad, ind) in tree.items():
        for a, i in ins.items():
            out[a] = (a, data[a - base:i.end - base].hex(), _clk(i) if cycles else i.text)
        frontiers += [(a, 'undecodable: ' + why) for a, why in bad]
        frontiers += [(a, why if why.startswith('data after') else 'indirect: ' + why) for a, why in ind]
    return [out[a] for a in sorted(out)], sorted(frontiers)


def format_listing(rows, syms=None):
    syms = syms or {}
    L = []
    for addr, raw, text in rows:
        label = syms.get(addr)
        if label:
            L.append('%s:' % label)
        L.append('  %06x  %-14s %s' % (addr, raw, text))
    return '\n'.join(L)
