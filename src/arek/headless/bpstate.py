"""Capture CPU registers, beam position and RAM at a breakpoint.

This is the measuring instrument of the whole method: run the original in
the headless vAmiga, stop at an address (the N-th time it is hit), dump the
registers, Agnus clock and chip RAM (plus optional extra regions). Two such
captures - before and after a routine - give the exact effect of that routine
on memory, which is what a recompiled or re-implemented version is compared
against (``arek.contract``).

Requires the patched VAHeadless (``patches/vamiga-headless-<commit>.patch``): the
``VAHL_ONSTOP`` environment variable names a RetroShell script that runs when
the emulator stops on a breakpoint.
"""
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from . import config, shot

# chips whose registers ``r <chip>`` prints at the stop (cpu.json "chips")
CHIPS = ('agnus', 'copper', 'denise', 'paula', 'blitter')


def state(conf, events, addr, npass, t_end, t_set=0, ram_len=524288, keep=None,
          setup=(), after_break=(), ram_regions=(), screenshot=False, adf=None, timeout=900):
    """Run to breakpoint ``addr`` (skipping ``npass`` hits) and capture.

    Returns ``(state_dict or None, log_text)``. ``state_dict`` has ``d``,
    ``a``, ``pc``, ``ccr``, ``beam``, ``ram`` (bytes from 0), ``regions``.
    """
    adf = shot.check_disk(conf, adf or conf.get('ADF1'))
    config.require(conf, 'ROM', 'VAHL')
    tmp = keep or tempfile.mkdtemp(prefix='arek-bp')
    os.makedirs(tmp, exist_ok=True)
    dump = os.path.join(tmp, 'ram_%x_%d.bin' % (addr, npass))
    onstop = os.path.join(tmp, 'onstop_%x_%d.retrosh' % (addr, npass))
    lines = ['try debugger', 'r cpu', '? agnus', '? agnus beam']
    lines += ['try r %s' % chip for chip in CHIPS]
    lines += ['commander', 'mem save bin %s 0 %d' % (dump, ram_len)]
    regions = []
    for base, length in ram_regions:
        filename = os.path.join(tmp, 'ram_%x_%d_%x.bin' % (addr, npass, base))
        lines.append('mem save bin %s $%x %d' % (filename, base, length))
        regions.append({'base': base, 'length': length, 'file': filename})
    lines.append('screenshot save ' + os.path.join(tmp, 'stable.png') if screenshot else 'shutdown')
    Path(onstop).write_text('\n'.join(lines) + '\n')
    ev = list(events) + [(t_set, 'debugger'),
                         (t_set, 'break at $%x %d' % (addr, npass)),
                         (t_set, 'commander')]
    ev += [(t_set, command) for command in after_break]
    script = shot.build_script(conf, adf, ev, t_end, os.path.join(tmp, 'unused.png'), setup)
    Path(tmp, 'capture_%x_%d.retrosh' % (addr, npass)).write_text(script)
    if os.path.exists(dump):
        os.unlink(dump)
    out = shot.run_script(conf, script, capture=True, env={'VAHL_ONSTOP': onstop}, timeout=timeout)
    if not os.path.exists(dump):
        return None, out
    st = parse_regs(out)
    st['beam'] = parse_beam(out)
    st['chips'] = parse_chips(out)
    st['ram'] = Path(dump).read_bytes()
    st['regions'] = regions
    return st, out


def parse_regs(out):
    """D0-D7, A0-A7, PC and CCR from ``r cpu`` (vAmiga 5.0 format)::

        D0 - D3 : 0x00000001 0x00000027 ...
        Flags   : ttSm-<0>---Xnzvc      (upper case = set)
    """
    st = {'d': [None] * 8, 'a': [None] * 8, 'pc': None, 'ccr': None}
    for kind in ('D', 'A'):
        for m in re.finditer(kind + r'(\d) - ' + kind + r'(\d)\s*:\s*((?:0x[0-9A-Fa-f]{8}\s*)+)', out):
            vals = re.findall(r'0x([0-9A-Fa-f]{8})', m.group(3))
            for i, v in enumerate(vals):
                st['d' if kind == 'D' else 'a'][int(m.group(1)) + i] = int(v, 16)
    m = re.search(r'(?<![A-Z])PC\s*:\s*0x([0-9A-Fa-f]{8})', out)
    if m:
        st['pc'] = int(m.group(1), 16)
    m = re.search(r'Flags\s*:\s*(\S+)', out)
    if m:
        f = m.group(1)[-5:]
        st['ccr'] = {k.lower(): int(c.isupper()) for k, c in zip('XNZVC', f)}
    return st


_VALUE = re.compile(r'(\w+)\s*:\s*((?:0x[0-9A-Fa-f]+\s*)+|yes|no|-?\d+)(?=\s|$)')


def parse_chips(out):
    """Custom chip registers from ``r agnus|copper|denise|paula|blitter`` (vAmiga 5.0b2)::

        DMACON : 0x0200            -> {"agnus": {"DMACON": 512, ...}}
        BPL0PT : 0x0  BPL1PT : 0x0 (two per line), SPRxPOS : 0x0 0x0 ... (a list), USEA : no (bool)

    vAmiga 5.0b2 labels two lines COP1LC (the second is presumably COP2LC) and two BPL6PT;
    a repeated name is stored as NAME#2. These are the emulator's view of the registers,
    including write-only ones."""
    chips, cur = {}, None
    for line in out.splitlines():
        s = line.strip()
        m = re.fullmatch(r'(?:try )?r (\w+)', s)
        if m:
            cur = m.group(1) if m.group(1) in CHIPS else None
            if cur:
                chips[cur] = {}
            continue
        if cur is None:
            continue
        if re.match(r'(try |r |\? |commander|mem |screenshot|shutdown)', s):
            cur = None
            continue
        for name, val in _VALUE.findall(s):
            val = val.strip()
            if val in ('yes', 'no'):
                v = val == 'yes'
            elif val.startswith('0x'):
                nums = [int(x, 16) for x in val.split()]
                v = nums[0] if len(nums) == 1 else nums
            else:
                v = int(val)
            key, k = name, 2
            while key in chips[cur]:
                key, k = '%s#%d' % (name, k), k + 1
            chips[cur][key] = v
    return chips


def parse_beam(out):
    patterns = {'clock': r'Clock\s*:\s*(\d+)',
                'frame': r'Frame\s*:\s*(\d+) \((?:PAL|NTSC)\)',
                'position': r'Position\s*:\s*\((\d+),(\d+)\)'}
    result = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, out)
        if not match:
            raise ValueError('Missing Agnus field: ' + key)
        result[key] = [int(v) for v in match.groups()] if key == 'position' else int(match[1])
    return result


def capture(conf, folder, addr, npass, t_end, events=(), t_set=0, ram_len=524288,
            regions=(), setup=(), adf=None, timeout=900):
    """``state`` + write ``cpu.json``, ``capture.log`` and the RAM dumps into
    a fresh ``folder``. Returns the metadata dict."""
    folder = Path(folder).resolve()
    if folder.exists():
        raise FileExistsError('choose a new output directory for each capture: %s' % folder)
    folder.mkdir(parents=True)
    st, log = state(conf, list(events), addr, npass, t_end, t_set=t_set, ram_len=ram_len,
                    keep=str(folder), ram_regions=regions, setup=setup, adf=adf,
                    timeout=timeout)
    (folder / 'capture.log').write_text(log)
    if st is None or st['pc'] != addr:
        raise RuntimeError('breakpoint not captured; see %s' % (folder / 'capture.log'))
    meta = {k: v for k, v in st.items() if k != 'ram'}
    adf = adf or conf.get('ADF1')
    meta.update(machine=conf.get('MACHINE', 'A500_OCS_1MB'), events=list(events),
                breakpoint=addr, skip=npass, set_at=t_set, end=t_end,
                ram_base=0, ram_bytes=len(st['ram']),
                ram_sha256=hashlib.sha256(st['ram']).hexdigest(),
                assets={k: hashlib.sha256(Path(p).read_bytes()).hexdigest()
                        for k, p in (('VAHL', conf['VAHL']), ('ROM', conf['ROM']), ('ADF', adf))})
    for region in meta['regions']:
        p = Path(region['file'])
        region['sha256'] = hashlib.sha256(p.read_bytes()).hexdigest()
        region['file'] = p.name
    (folder / 'cpu.json').write_text(json.dumps(meta, indent=2) + '\n')
    return meta
