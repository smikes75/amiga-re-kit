"""arek host boot (kit 1.0.82): the start from the disks without a Kickstart, measured instead of written by hand.

The five rebuilds each wrote the same thing by hand: what the original's boot chain leaves in memory at the main
program's entry - the loader copied from the disk, a memory list, the crack's fixes, the words of low memory and of
ExecBase that the game reads through null pointers (Superfrog: 722 runs and a poison test to find 5 longs; Xenon 2: one
word at $0008). The kit measures it: a run of the translation from the original's state at the entry, built with
-DAREK_FIRSTREAD, writes every byte it read before it wrote it ($AREK_FIRSTREAD: "lo hi kinds", c the CPU, b the
blitter, d DMA - Copper, sprites, Paula); the union of such logs over the game's scenarios is what a start must provide.
`arek host boot STATE OUT --reads LOG... --disk ADF...` then takes, of those bytes, the ones the state does not hold as
zero, finds them on the disk images (a copy rule: disk, offset, length, address, an FNV-1a of the bytes - another
version of the disk is refused, not run) and lists the rest as the residue (bytes in the build: Kickstart's leftovers,
a memory list, the crack's fixes - and, when it is large, data the boot chain unpacked: take the entry earlier or port
the unpacker). It writes OUT/state (the state with zero chip and slow RAM: registers, custom registers, CIAs, drive,
audio as the original had them) and OUT/arek_boot.h (arek_boot_mem(), arek_boot_check(), and with -DAREK_BOOT_GO=f_xxx
the HOST_ENTRY routine arek_boot). No game data in the kit: the tables are the project's, made from its own disks.
"""
import os
import shutil
from pathlib import Path

CHIP, SLOWLEN = 0x80000, 0x80000
KINDS = {'c': 1, 'b': 2, 'd': 4}
NAMES = ((1, 'CPU'), (2, 'blitter'), (4, 'DMA'))


def fnv(b):
    h = 0x811c9dc5
    for x in b:
        h = ((h ^ x) * 0x01000193) & 0xffffffff
    return h


class Space:
    """Chip RAM at 0 and slow RAM at ``slow_base``, as one index: i < CHIP chip, else slow."""

    def __init__(self, chip, slow, slow_base=0xc00000):
        self.chip = bytes(chip[:CHIP]).ljust(CHIP, b'\0')
        self.slow = bytes(slow[:SLOWLEN]).ljust(SLOWLEN, b'\0')
        self.base = slow_base
        self.mem = self.chip + self.slow

    def index(self, addr):
        if addr < CHIP:
            return addr
        if self.base <= addr < self.base + SLOWLEN:
            return CHIP + addr - self.base
        raise ValueError('address %06x is neither chip RAM nor slow RAM at %06x' % (addr, self.base))

    def addr(self, i):
        return i if i < CHIP else self.base + i - CHIP

    def region_end(self, i):
        return CHIP if i < CHIP else CHIP + SLOWLEN


def read_logs(paths, space):
    """The union of AREK_FIRSTREAD logs: a bytearray over the space, per byte the readers' bits."""
    r = bytearray(CHIP + SLOWLEN)
    for p in paths:
        for line in Path(p).read_text().splitlines():
            w = line.split('#')[0].split()
            if not w:
                continue
            lo, hi = int(w[0], 16), int(w[1], 16)
            k = 0
            for ch in (w[2] if len(w) > 2 else 'c'):
                k |= KINDS.get(ch, 0)
            i, j = space.index(lo), space.index(hi - 1) + 1
            for x in range(i, j):
                r[x] |= k
    return r


def _disk_index(img, step=4, k=8):
    idx = {}
    for o in range(0, len(img) - k + 1, step):
        key = img[o:o + k]
        if key.count(key[0]) == k:          # a fill pattern matches everything
            continue
        lst = idx.get(key)
        if lst is None:
            idx[key] = [o]
        elif len(lst) < 4:
            lst.append(o)
    return idx


def plan(space, reads, disks, min_copy=16):
    """Copy rules from the disks and the residue for every byte read before written that the state does not hold as 0."""
    mem = space.mem
    need = bytearray(len(mem))
    for i, k in enumerate(reads):
        if k and mem[i]:
            need[i] = 1
    nneed = sum(need)
    covered = bytearray(len(mem))
    copies = []
    idxs = [(_disk_index(img), img) for img in disks]
    i, n = 0, len(mem)
    while i < n:
        if not need[i] or covered[i]:
            i += 1
            continue
        best = None
        end = space.region_end(i)
        for p in range(max(i - 7, 0 if i < CHIP else CHIP), min(i + 1, end - 7)):
            key = mem[p:p + 8]
            for d, (idx, img) in enumerate(idxs):
                for o in idx.get(key, ()):
                    lo, so = p, o                      # extend backwards and forwards while the bytes agree
                    start = 0 if p < CHIP else CHIP
                    while lo > start and so > 0 and mem[lo - 1] == img[so - 1]:
                        lo -= 1
                        so -= 1
                    hi, eo = p + 8, o + 8
                    while hi < end and eo < len(img) and mem[hi] == img[eo]:
                        hi += 1
                        eo += 1
                    if lo > i or hi <= i:
                        continue
                    gain = sum(1 for x in range(lo, hi) if need[x] and not covered[x])
                    if best is None or gain > best[0]:
                        best = (gain, d, so, lo, hi)
        if best and best[4] - best[3] >= min_copy:
            gain, d, so, lo, hi = best
            copies.append({'disk': d, 'off': so, 'len': hi - lo, 'to': space.addr(lo), 'fnv': fnv(disks[d][so:so + hi - lo])})
            for x in range(lo, hi):
                covered[x] = 1
            i = hi
        else:
            i += 1
    copies.sort(key=lambda c: c['to'])
    # the residue: needed bytes no copy holds, in runs (a gap of up to 4 bytes is taken along - the state's own values)
    runs, i = [], 0
    while i < n:
        if need[i] and not covered[i]:
            j, last = i, i
            end = space.region_end(i)
            while j < end and j - last <= 4:
                if need[j] and not covered[j]:
                    last = j
                j += 1
            runs.append({'to': space.addr(i), 'bytes': bytes(mem[i:last + 1]),
                         'kinds': ''.join(c for c, b in KINDS.items() if any(reads[x] & b for x in range(i, last + 1)))})
            i = last + 1
        else:
            i += 1
    by_kind = {name: sum(1 for x in range(n) if need[x] and reads[x] & b) for b, name in NAMES}
    rest = sum(len(r['bytes']) for r in runs)
    return {'needed': nneed, 'by_kind': by_kind, 'copies': copies, 'from_disk': sum(covered[x] for x in range(n) if need[x]),
            'copied': sum(c['len'] for c in copies), 'residue': runs, 'residue_bytes': rest,
            'low': [r for r in runs if r['to'] < 0x400]}


def write_header(path, p, source, logs, disks):
    out = ['/* arek_boot.h - written by arek host boot (kit 1.0.82); do not edit, measure again. The start from the disks',
           ' * without a Kickstart: every byte the runs of %s read before they wrote it' % os.path.basename(str(source)),
           ' * (%d log(s)) that the state does not hold as zero - %d bytes: %d from the disks in %d copies, %d bytes in the build.' % (
               len(logs), p['needed'], p['from_disk'], len(p['copies']), p['residue_bytes']),
           ' * arek_boot_mem() builds the memory as a state file would (no write log), arek_boot_check() = -1 or the first copy',
           ' * whose disk bytes are not the measured ones (another version of the disk). With -DAREK_BOOT_GO=f_xxxxxx:',
           ' * arek_boot(m), the HOST_ENTRY routine (natively the disks from $AREK_DF0..3 when none is set).',
           ' * Needs before it: the translation (MEM, SLOW) and arek_host_disk.h (AHD_IMG, AHD_LEN). */',
           '#ifndef AREK_BOOT_H', '#define AREK_BOOT_H',
           'static const struct { uint8_t disk; uint32_t off, len, to, fnv; } AREK_BOOT_COPY[] = {']
    for c in p['copies']:
        out.append('    { %d, 0x%06xu, 0x%xu, 0x%06xu, 0x%08xu },' % (c['disk'], c['off'], c['len'], c['to'], c['fnv']))
    if not p['copies']:
        out.append('    { 0, 0, 0, 0, 0 },')
    out.append('};')
    out.append('#define AREK_BOOT_NCOPY %d' % len(p['copies']))
    out.append('static const struct { uint32_t to, len, at; } AREK_BOOT_RUN[] = {')
    at = 0
    for r in p['residue']:
        out.append('    { 0x%06xu, %d, %d },   /* %s */' % (r['to'], len(r['bytes']), at, r['kinds']))
        at += len(r['bytes'])
    if not p['residue']:
        out.append('    { 0, 0, 0 },')
    out.append('};')
    out.append('#define AREK_BOOT_NRUN %d' % len(p['residue']))
    data = b''.join(r['bytes'] for r in p['residue']) or b'\0'
    out.append('static const uint8_t AREK_BOOT_BYTES[%d] = {' % len(data))
    for k in range(0, len(data), 24):
        out.append('    ' + ', '.join('0x%02x' % x for x in data[k:k + 24]) + ',')
    out.append('};')
    out.append(r'''static uint32_t arek_boot_fnv(const uint8_t *b, uint32_t n) { uint32_t h = 0x811c9dc5u; while (n--) { h ^= *b++; h *= 0x01000193u; } return h; }
static int arek_boot_check(void) {
    for (int i = 0; i < AREK_BOOT_NCOPY; i++) {
        uint32_t d = AREK_BOOT_COPY[i].disk, o = AREK_BOOT_COPY[i].off, n = AREK_BOOT_COPY[i].len;
        if (d >= AHD_DISKS || !AHD_IMG[d] || (long)(o + n) > AHD_LEN[d] || arek_boot_fnv(AHD_IMG[d] + o, n) != AREK_BOOT_COPY[i].fnv) return i;
    }
    return -1;
}
static void arek_boot_put(uint32_t a, uint8_t v) {
    if (a < MEMSZ) { MEM[a] = v; return; }
#if SLOWSZ
    if (a - SLOWBASE < SLOWSZ) SLOW[a - SLOWBASE] = v;
#endif
}
static int arek_boot_mem(void) {
    int bad = arek_boot_check();
    if (bad >= 0) return bad + 1;
    memset(MEM, 0, MEMSZ);
#if SLOWSZ
    memset(SLOW, 0, SLOWSZ);
#endif
    for (int i = 0; i < AREK_BOOT_NCOPY; i++)
        for (uint32_t k = 0; k < AREK_BOOT_COPY[i].len; k++) arek_boot_put(AREK_BOOT_COPY[i].to + k, AHD_IMG[AREK_BOOT_COPY[i].disk][AREK_BOOT_COPY[i].off + k]);
    for (int i = 0; i < AREK_BOOT_NRUN; i++)
        for (uint32_t k = 0; k < AREK_BOOT_RUN[i].len; k++) arek_boot_put(AREK_BOOT_RUN[i].to + k, AREK_BOOT_BYTES[AREK_BOOT_RUN[i].at + k]);
    return 0;
}
#ifdef AREK_BOOT_GO
void AREK_BOOT_GO(M68 *m);
void arek_boot(M68 *m) {
#ifndef __EMSCRIPTEN__
    for (int n = 0; n < AHD_DISKS && n < 4; n++) { char e[] = "AREK_DF0"; e[7] = (char)('0' + n); if (!AHD_IMG[n] && getenv(e)) ahd_set_file(n, getenv(e)); }
#endif
    int r = arek_boot_mem();
    if (r) { fprintf(stderr, "arek_boot: copy %d (disk %d, offset %06x): not the measured bytes - another version of the disk, or none\n",
                     r - 1, AREK_BOOT_COPY[r - 1].disk, (unsigned)AREK_BOOT_COPY[r - 1].off); exit(3); }
    AREK_BOOT_GO(m);
}
#endif
#endif''')
    Path(path).write_text('\n'.join(out) + '\n')


def boot(state, out, logs, disk_paths, min_copy=16, slow_base=0xc00000):
    """``state``: a state folder (arek host state) or a capture folder (cpu.json: converted first). Writes OUT/state and
    OUT/arek_boot.h; returns the plan (``copies``, ``residue``, counts)."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    state = Path(state)
    if (state / 'cpu.json').exists():
        from . import host
        host.state(str(state), str(out / 'full'))
        state = out / 'full'
    space = Space((state / 'chip.bin').read_bytes(), (state / 'slow.bin').read_bytes() if (state / 'slow.bin').exists() else b'', slow_base)
    reads = read_logs(logs, space)
    disks = [Path(d).read_bytes() for d in disk_paths]
    p = plan(space, reads, disks, min_copy=min_copy)
    st = out / 'state'
    st.mkdir(exist_ok=True)
    (st / 'chip.bin').write_bytes(bytes(CHIP))
    (st / 'slow.bin').write_bytes(bytes(SLOWLEN))
    for f in ('creg.bin', 'state.txt'):
        shutil.copyfile(state / f, st / f)
    write_header(out / 'arek_boot.h', p, state, logs, disk_paths)
    return p


def format_report(p, limit=12):
    lines = ['%d bytes read before written and not zero in the state (%s)' % (
        p['needed'], ', '.join('%s %d' % (k, v) for k, v in p['by_kind'].items() if v)),
        'from the disks: %d of them in %d copies (%d bytes copied)' % (p['from_disk'], len(p['copies']), p['copied'])]
    for c in p['copies'][:limit]:
        lines.append('  disk %d offset %06x, %d bytes -> %06x' % (c['disk'], c['off'], c['len'], c['to']))
    if len(p['copies']) > limit:
        lines.append('  ... %d more' % (len(p['copies']) - limit))
    lines.append('in the build: %d bytes in %d runs (%d of them below $400)' % (p['residue_bytes'], len(p['residue']), sum(len(r['bytes']) for r in p['low'])))
    for r in sorted(p['residue'], key=lambda r: -len(r['bytes']))[:limit]:
        lines.append('  %06x %d bytes (%s)' % (r['to'], len(r['bytes']), r['kinds']))
    if p['residue_bytes'] > 4096:
        lines.append('note: more than 4 KB is not on the disks as it is - data the boot chain unpacked or built: take the entry '
                     'earlier (before the unpacker) or port the unpacker, then measure again')
    return '\n'.join(lines)
