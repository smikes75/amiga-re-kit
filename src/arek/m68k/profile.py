"""Routine profile of a translation run (``recomp --profile``): what to rewrite first.

The generated runtime counts per translated routine its calls, 68000 clocks (with ``--timing``)
and the bytes and 1 KB pages it wrote; ``prof_dump`` writes rows, one per routine::

    H <memsz> <slowbase> <slowsz>          (hex)
    R <frame> <addr> <calls> <clocks> <bytes> <page ranges...>

A host calls ``prof_reset()`` / ``prof_dump(f, frame)`` per frame; the verification driver
writes one dump at exit when ``AREK_PROFILE=file`` is set. Pages are 1 KB, chip RAM first,
slow RAM from ``memsz / 1024`` - ``read`` turns them back into address ranges. Writes include
what a routine pushes on the stack (return addresses of its calls, movem), so the stack page
shows up for callers; look at the other pages for what a routine produces.
"""


def read(src):
    """Rows of a profile file: ``{frame, addr, calls, clocks, bytes, pages: [(lo, hi), ...]}``
    with pages as address ranges; ``rows[0]`` is the header ``{'memsz', 'slowbase', 'slowsz'}``."""
    text = src if isinstance(src, str) and '\n' in src else open(src).read()
    hdr, rows = {'memsz': 0x80000, 'slowbase': 0xc00000, 'slowsz': 0}, []
    for line in text.splitlines():
        f = line.split()
        if not f:
            continue
        if f[0] == 'H':
            hdr = {'memsz': int(f[1], 16), 'slowbase': int(f[2], 16), 'slowsz': int(f[3], 16)}
        elif f[0] == 'R':
            pages = []
            chip = hdr['memsz'] // 1024
            for p in f[6:]:
                a, _, b = p.partition('-')
                lo, hi = int(a, 16), int(b or a, 16)
                for q in range(lo, hi + 1):
                    addr = q * 1024 if q < chip else hdr['slowbase'] + (q - chip) * 1024
                    if pages and pages[-1][1] == addr:
                        pages[-1] = (pages[-1][0], addr + 1024)
                    else:
                        pages.append((addr, addr + 1024))
            rows.append({'frame': int(f[1]), 'addr': int(f[2], 16), 'calls': int(f[3]), 'clocks': int(f[4]),
                         'bytes': int(f[5]), 'pages': pages})
    return [hdr] + rows


def summary(rows, by='clocks', top=20, frame=None):
    """The routines that matter most, by ``clocks``, ``calls`` or ``bytes``; summed over frames
    (or one ``frame``). Each gets its share of the total."""
    acc = {}
    for r in rows[1:]:
        if frame is not None and r['frame'] != frame:
            continue
        a = acc.setdefault(r['addr'], {'addr': r['addr'], 'calls': 0, 'clocks': 0, 'bytes': 0, 'pages': set(), 'frames': 0})
        a['calls'] += r['calls']
        a['clocks'] += r['clocks']
        a['bytes'] += r['bytes']
        a['pages'].update(r['pages'])
        a['frames'] += 1
    total = sum(a[by] for a in acc.values()) or 1
    out = sorted(acc.values(), key=lambda a: -a[by])[:top]
    for a in out:
        a['share'] = a[by] / total
        a['pages'] = sorted(a['pages'])
    return out


def format_summary(out, by='clocks'):
    L = ['%-8s %10s %12s %10s %6s  %s' % ('routine', 'calls', 'clocks', 'bytes', by, 'writes to')]
    for a in out:
        pages = ', '.join('%x-%x' % (lo, hi) for lo, hi in a['pages'][:6]) + (' ...' if len(a['pages']) > 6 else '')
        L.append('%06x   %10d %12d %10d %5.1f%%  %s' % (a['addr'], a['calls'], a['clocks'], a['bytes'],
                                                        100 * a['share'], pages))
    return '\n'.join(L)
