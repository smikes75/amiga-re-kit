"""MCP server exposing the kit to an AI assistant (Claude Code, Claude Desktop,
any MCP client). Run with ``arek-mcp`` (stdio transport).

The server is stateless apart from a cache of files it has loaded; every
tool takes paths on the local machine. It never fetches anything from the
network and it never writes outside the paths you give it. Copyrighted
material (ADF, ROM) stays on your disk - the assistant only sees the
measurements the tools return.

Claude Code configuration (``.mcp.json`` in a project or ``claude mcp add``)::

    {"mcpServers": {"arek": {"command": "arek-mcp"}}}
"""
import json
import os
from pathlib import Path

try:                                           # mcp >= 2.0
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:                            # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server

mcp = _Server('arek', instructions=(
    'Amiga reverse-engineering kit. Workflow: adf_info / adf_map on the disk image -> '
    'scan_packed to find packed blocks -> unpack -> disassemble / walk from the boot '
    'code -> hwscan to find the hardware boundary -> recomp to C -> verify against '
    'headless-emulator captures (shot, bpstate, diff). Every result is a measurement '
    'of the given bytes; nothing is inferred from game names.'))

_cache = {}


def _bytes(path):
    p = Path(path).expanduser()
    key = (str(p), p.stat().st_mtime_ns)
    if key not in _cache:
        _cache.clear()
        _cache[key] = p.read_bytes()
    return _cache[key]


def _addr(x):
    return int(x, 0) if isinstance(x, str) else int(x)


# ------------------------------------------------------------------ kit
@mcp.tool()
def kit_info() -> dict:
    """Version of the kit and SHA-256 of its decoder and recompiler sources -
    record it with every measurement (an editable install can carry
    unreleased changes)."""
    from . import identity
    return identity()


# ------------------------------------------------------------------ disk
@mcp.tool()
def adf_info(path: str) -> dict:
    """Inventory of an ADF image: size, sha256, boot block (DOS type, checksum,
    bootable), mean entropy, empty sector count."""
    from . import adf
    return adf.inventory(_bytes(path), Path(path).name)


@mcp.tool()
def adf_map(path: str) -> str:
    """ASCII entropy map of the disk, one char per sector (. empty, - sparse,
    c code/data, d dense, # packed). The first picture to look at."""
    from . import adf
    data = _bytes(path)
    adf.check_size(data)
    return adf.ascii_map(data)


@mcp.tool()
def adf_regions(path: str) -> list:
    """Contiguous regions of the disk by entropy class with track numbers."""
    from . import adf
    return adf.regions(_bytes(path))


@mcp.tool()
def adf_ls(path: str, lenient: bool = False) -> dict:
    """Files of an AmigaDOS (OFS/FFS) disk image: path, size, header block,
    checksum state. Fails with a precise reason when the disk is not AmigaDOS
    (most games boot their own trackloader instead)."""
    from . import amigados
    data = _bytes(path)
    dt = amigados.dostype(data)
    if dt is None:
        raise ValueError('no DOS boot block: not an AmigaDOS disk')
    r = amigados.root(data, strict=not lenient)
    return {'filesystem': dt['fs'], 'intl': dt['intl'], 'volume': r['name'], 'root_block': r['block'],
            'root_checksum_ok': r['checksum_ok'], 'entries': amigados.listing(data, strict=not lenient)}


@mcp.tool()
def adf_file(path: str, name: str, out: str, lenient: bool = False) -> dict:
    """Reassemble one AmigaDOS file (``name`` = path inside the volume,
    case-insensitive) and write it to ``out``. Data blocks are verified
    (type, owner, sequence, checksum); ``lenient`` reports problems in
    ``warnings`` instead of failing and takes raw sectors as they are."""
    from . import amigados
    data = _bytes(path)
    e = amigados.find(data, name, strict=not lenient)
    if e is None:
        raise ValueError('no such file: ' + name)
    warn = []
    body = amigados.read_file(data, e, strict=not lenient, warnings=warn)
    Path(out).write_bytes(body)
    return {'out': out, 'bytes': len(body), 'header_block': e['block'], 'warnings': warn}


@mcp.tool()
def adf_extract(path: str, offset: str, length: str, out: str) -> str:
    """Copy ``length`` bytes from ``offset`` of the image to file ``out``."""
    data = _bytes(path)
    o, n = _addr(offset), _addr(length)
    Path(out).write_bytes(data[o:o + n])
    return '%s: %d bytes from %#x' % (out, n, o)


# ------------------------------------------------------------------ packers
@mcp.tool()
def scan_packed(path: str, deep: bool = False) -> dict:
    """Find packer signatures (PP20, RNC, ATN!, IMP!, ...) and verified
    Atomik and Bytekiller blocks in a file or image. ``deep`` also tries the SWIV
    word-stream variant (slow)."""
    from .packers import scan
    return scan.scan(_bytes(path), deep=deep)


@mcp.tool()
def unpack(path: str, out: str, kind: str = 'auto', offset: str = '0') -> dict:
    """Unpack a block to ``out``. kind: auto | pp20 | atn | bytekiller | bytekiller_a | t2."""
    from .packers import atomik, bytekiller, pp20, turrican2
    data = _bytes(path)
    off = _addr(offset)
    if kind == 'auto':
        magic = data[off:off + 4]
        kind = 'pp20' if magic == b'PP20' else 'atn' if magic == b'ATN!' else 'bytekiller'
    if kind == 'pp20':
        res, ok = pp20.unpack(data[off:]), True
    elif kind == 'atn':
        res, ok = atomik.unpack(data[off:]), True
    elif kind == 'bytekiller':
        res, ok = bytekiller.unpack_b(data, off)
    elif kind == 'bytekiller_a':
        res, ok = bytekiller.unpack_a(data, off)
    elif kind == 't2':
        res, ok = turrican2.unpack_t2(data[off:]), True
    else:
        raise ValueError('unknown kind ' + kind)
    Path(out).write_bytes(res)
    return {'out': out, 'bytes': len(res), 'checksum_ok': ok, 'kind': kind}


# ------------------------------------------------------------------ hunk
@mcp.tool()
def hunk_info(path: str) -> dict:
    """Hunk table (kind, size) of an AmigaDOS executable without relocating."""
    from . import hunk
    return hunk.info(_bytes(path))


@mcp.tool()
def hunk_load(path: str, base: str, out_prefix: str) -> list:
    """Relocate all hunks contiguously from ``base`` and write
    ``<out_prefix>_<i>_<addr>.bin`` files."""
    from . import hunk
    res = []
    for i, (b, body) in enumerate(hunk.load(_bytes(path), _addr(base))):
        p = '%s_%d_%06x.bin' % (out_prefix, i, b)
        Path(p).write_bytes(body)
        res.append({'file': p, 'base': b, 'bytes': len(body)})
    return res


# ------------------------------------------------------------------ 68k
@mcp.tool()
def disassemble(path: str, base: str, lo: str = None, hi: str = None,
                limit: int = 400, cycles: bool = False) -> str:
    """Linear disassembly of [lo, hi) of a binary loaded at ``base``. Undecodable
    words are marked ``??`` - use ``walk`` for code with data in between.
    ``cycles`` appends each instruction's 68000 clock count."""
    from .m68k import disasm
    data = _bytes(path)
    b = _addr(base)
    rows = disasm.listing(data, b, _addr(lo) if lo else b, _addr(hi) if hi else b + len(data), limit,
                          cycles=cycles)
    return disasm.format_listing(rows)


@mcp.tool()
def walk(path: str, base: str, start: str, lo: str = None, hi: str = None,
         inline: list = None) -> dict:
    """Follow the flow graph from ``start``: reachable instructions per routine
    (listing) plus explicit frontiers (undecodable words, indirect jumps, data after a
    call). ``inline``: 'ROUTINE[,..]:until=HHHH|words=N|longs=N|string' for routines that
    read data stored after their call and return behind it."""
    from .m68k import disasm, recomp as rc
    data = _bytes(path)
    b = _addr(base)
    rows, fr = disasm.listing_walk(data, b, _addr(start), _addr(lo) if lo else b,
                                   _addr(hi) if hi else b + len(data),
                                   flow=rc.flow_from_specs(data, b, inline=inline or []))
    return {'listing': disasm.format_listing(rows), 'instructions': len(rows),
            'frontiers': [{'addr': '%06x' % a, 'why': w} for a, w in fr]}


@mcp.tool()
def hwscan(path: str, base: str, roots: list, lo: str = None, hi: str = None,
           abase: dict = None, chip: str = None, inline: list = None) -> dict:
    """Which routines reachable from ``roots`` are pure RAM and which touch
    custom chips / CIA / ROM - the hardware boundary. ``abase`` maps address
    registers known at entry to addresses, e.g. {"a5": "0xdff000"}. ``chip`` =
    chip RAM size of the machine (default 2 MB). ``inline`` as in ``walk``."""
    from .m68k import hwscan as hs, recomp as rc
    data = _bytes(path)
    b = _addr(base)
    ab = {int(k.lower().lstrip('a')): _addr(v) for k, v in (abase or {}).items()}
    routines = hs.scan(data, b, [_addr(r) for r in roots], _addr(lo) if lo else b,
                       _addr(hi) if hi else b + len(data), abase=ab,
                       chip=_addr(chip) if chip else hs.CHIP_MAX,
                       flow=rc.flow_from_specs(data, b, inline=inline or []))
    ok = hs.closure(routines)
    rep = hs.report(routines, ok)
    rep['text'] = hs.format_report(rep)
    return rep


@mcp.tool()
def recomp(path: str, base: str, out_c: str, auto: list = None, funcs: list = None,
           stubs: list = None, with_main: bool = False, flow: dict = None, timing: bool = False,
           memsz: str = None, slow: str = None) -> dict:
    """Statically recompile 68k routines to C. ``auto``: entry addresses whose
    bodies are discovered by walking; ``funcs``: 'START:END[:ENTRY]' linear
    ranges; ``stubs``: 'An:DISP:NAME' for jsr through jump tables. ``flow``: what
    the bytes do not say, as lists of the CLI spellings under the keys jtab,
    indirect, stop, exitat, extern, ret, inline, plus prefix 'NAME:LO:HI' and lib (bool).
    ``timing`` counts 68000 clocks per instruction into CYCLES (or the host's tick_hook).
    ``memsz``: chip RAM bytes (default "0x80000"); ``slow``: slow RAM "BASE:SIZE" in hex,
    e.g. "c00000:80000" (the driver then takes SLOW.bin SLOWOUT.bin as arguments 5 and 6).
    Anything the decoder does not support is refused, never skipped: the result is then
    {"refused": {"message", "frontiers": [{routine, site, kind, insn, operand, target, why}]}}
    with every place that needs a ``flow`` entry (addresses as hex strings)."""
    from .m68k import recomp as rc
    for s in stubs or []:
        rc.add_stub(s)
    fs = [rc.parse_func_spec(s) for s in funcs or []]
    data, b = _bytes(path), _addr(base)
    f = flow or {}
    fl = rc.flow_from_specs(data, b, f.get('jtab', []), f.get('indirect', []), f.get('stop', []),
                            f.get('exitat', []), f.get('extern', []), f.get('ret', []),
                            f.get('prefix'), bool(f.get('lib')), f.get('inline', []))
    try:
        src, stats, entries = rc.generate(data, b, fs, [_addr(a) for a in auto or []],
                                          with_main=with_main, flow=fl, timing=timing,
                                          memsz=_addr(memsz) if memsz else None,
                                          slow=tuple(int(x, 16) for x in slow.split(':')) if slow else None)
    except rc.Unsupported as e:
        return {'refused': rc.refusal_json(e)}
    Path(out_c).write_text(src)
    return {'out': out_c, 'entries': ['%06x' % e for e in entries], 'stats': stats}


@mcp.tool()
def render(capture: str = None, ram: str = None, cop: str = None, png: str = None,
           compare: str = None) -> dict:
    """The frame chip RAM shows (Copper, bitplanes, dual playfield, EHB, sprites) as a PNG
    like vAmiga's screenshot (716 x 285). ``capture``: a bpstate folder (cpu.json "chips" gives
    COP1LC; its stable.raw is compared when present); or ``ram`` + ``cop``. ``compare``: an
    RGB24 screenshot. Returns the PNG path, Copper writes and the differing pixels."""
    from . import display
    from .headless import shot
    meta, folder = {}, Path(capture) if capture else None
    if folder and (folder / 'cpu.json').exists():
        meta = json.loads((folder / 'cpu.json').read_text())
    path = ram or (str(folder / meta['ram_file']) if 'ram_file' in meta else None)
    if not path:
        raise ValueError('no chip RAM: give a bpstate capture folder or ram')
    frame = display.render(_bytes(path), _addr(cop) if cop else None, chips=meta.get('chips'))
    rgb = display.to_screenshot(frame)
    out = png or (str(folder / 'render.png') if folder else 'render.png')
    shot.write_png(out, display.SHOT_W, display.SHOT_H, rgb)
    res = {'png': out, 'copper_writes': len(frame.writes)}
    ref = compare or (str(folder / 'stable.raw') if folder and (folder / 'stable.raw').exists() else None)
    if ref:
        d = display.diff(rgb, _bytes(ref))
        res['diff'] = {'pixels': d['pixels'], 'total': d['total'], 'box': d['box'], 'rows': len(d['rows'])}
    return res


@mcp.tool()
def xref(prog_txt: str, syms_json: str = None, callers_of: str = None, top: int = 40,
         callees_in: list = None) -> dict:
    """Cross references from an m68k objdump listing: most called routines,
    most referenced data, the callers of one address, or (``callees_in`` =
    [lo, hi]) what the code in that range calls or points at."""
    from .m68k import xref as xr
    x = xr.Xref.from_file(prog_txt, syms_json)
    if callers_of:
        return {'callers': ['%06x' % c for c in x.callers(_addr(callers_of))]}
    if callees_in:
        lo, hi = _addr(callees_in[0]), _addr(callees_in[1])
        return {'callees': [{'from': '%06x' % s, 'to': '%06x' % t, 'name': x.nm(t)} for s, t in x.callees_in(lo, hi)]}
    return {'summary': x.summary(top)}


@mcp.tool()
def copper(path: str, base: str = '0', offset: str = '0', limit: int = 512) -> str:
    """Disassemble a copper list found at ``offset`` of a RAM dump loaded at
    ``base`` (MOVE/WAIT/SKIP with custom register names)."""
    from . import copper as cp
    data = _bytes(path)
    o = _addr(offset)
    return cp.format_listing(cp.disassemble(data[o:], _addr(base) + o, limit))


# ------------------------------------------------------------------ emulator
@mcp.tool()
def headless_shot(conf: str, prefix: str, seconds: int, events: list = None, timeout: int = 600) -> str:
    """Boot the ADF from local.conf in the patched headless vAmiga, run
    ``seconds`` (warp), return the PNG path. ``events``: [[t, "retroshell cmd"]]
    such as [3, "joystick2 press 1"], [4, "joystick2 unpress 1"], [5, "mouse1 press left"].
    ``timeout``: seconds of wall time."""
    from .headless import config, shot
    c = config.load(conf)
    ev = [(int(t), cmd) for t, cmd in events or []]
    return shot.shot(c, prefix, seconds, ev, timeout=timeout)


@mcp.tool()
def headless_bpstate(conf: str, out_dir: str, address: str, end_seconds: int,
                     skip: int = 0, events: list = None, ram_len: int = 524288,
                     timeout: int = 900) -> dict:
    """Run to breakpoint ``address`` (the skip+1-th hit) and capture CPU
    registers, Agnus beam and chip RAM into ``out_dir`` (cpu.json + ram bin).
    ``events`` as in headless_shot; ``timeout``: seconds of wall time."""
    from .headless import config, bpstate
    c = config.load(conf)
    ev = [(int(t), cmd) for t, cmd in events or []]
    meta = bpstate.capture(c, out_dir, _addr(address), skip, end_seconds, events=ev, ram_len=ram_len,
                           timeout=timeout)
    return {k: v for k, v in meta.items() if k not in ('regions',)}


@mcp.tool()
def diff_captures(dir_a: str, dir_b: str, lo: str = None, hi: str = None) -> dict:
    """Byte-level differences between two bpstate captures (RAM and registers),
    optionally restricted to [lo, hi)."""
    from . import contract
    x, y = contract.load(dir_a), contract.load(dir_b)
    ranges = [(_addr(lo), _addr(hi))] if lo and hi else None
    runs = contract.compare(x['ram'], y['ram'], ranges)
    return {'runs': [{'start': '%06x' % s, 'end': '%06x' % e, 'expected': a, 'got': b}
                     for s, e, a, b in runs],
            'registers': {k: ['%08x' % v[0], '%08x' % v[1]] for k, v in contract.diff_regs(x, y).items()},
            'text': contract.format_runs(runs)}


@mcp.tool()
def ram_at(path: str, offset: str, length: int = 256, base: str = '0') -> str:
    """Hex dump of ``length`` bytes at ``offset`` of a RAM dump / file."""
    data = _bytes(path)
    o, b = _addr(offset), _addr(base)
    L = []
    for i in range(o, min(o + length, len(data)), 16):
        chunk = data[i:i + 16]
        L.append('%06x  %-48s %s' % (b + i, ' '.join('%02x' % c for c in chunk),
                                     ''.join(chr(c) if 32 <= c < 127 else '.' for c in chunk)))
    return '\n'.join(L)


# ------------------------------------------------------------------ trace
@mcp.tool()
def trace_records(path: str, fields: dict = None, start: int = 0, limit: int = 100) -> dict:
    """Records of a continuous trace written by the patched VAHeadless
    (VTR1/VTR2/VTW2, see arek.headless.trace): hit, frame, beam, kind, pc,
    registers, captured ranges, plus ``fields`` = {name: "ADDR:FMT"} read
    big-endian from the captured RAM (fmt: B, b, H, h, I, i)."""
    from .headless import trace
    f = {}
    for name, spec in (fields or {}).items():
        addr, _, fmt = str(spec).partition(':')
        f[name] = (_addr(addr), fmt or 'H')
    rows = trace.summary(path, f)
    return {'total': len(rows), 'start': start, 'records': rows[start:start + limit]}


@mcp.tool()
def trace_compare(original: str, rebuild: str, ranges: list = None, ignore: list = None, shift: int = 0,
                  best_shift: int = 0, regs: bool = False, limit: int = 20) -> dict:
    """Long parity: record k of the original trace against record k+shift of the rebuild's
    (same VTR layout, see arek.headless.trace.encode). ``ranges``/``ignore``: hex "START:LEN".
    Returns the first differing record with its words, the records that differ and the
    addresses that differ most often; with ``best_shift`` N the equal pairs for shifts -N..N."""
    from . import parity
    from .headless import trace
    ta, tb = list(trace.records(original)), list(trace.records(rebuild))
    rng = [trace.parse_range(r)[:2] for r in ranges or []] or None
    ign = [trace.parse_range(r)[:2] for r in ignore or []]
    if best_shift:
        return {'shifts': [{'shift': s, 'equal': e, 'pairs': n}
                           for s, e, n in parity.best_shift(ta, tb, range(-best_shift, best_shift + 1), rng, ign)]}
    r = parity.compare(ta, tb, rng, ign, shift, regs, limit)
    return json.loads(json.dumps(r, default=str))


@mcp.tool()
def trace_bus(path: str, frame: int = None) -> dict:
    """A VAHL_BUSLOG file (vamiga-buslog patch): per frame the DMA slots by owner, CPU waits and
    blits; with ``frame`` its slot map as text, one raster line per row (. free, C CPU, R refresh,
    D disk, A audio, 1-8 bitplanes, S sprites, c Copper, b blitter)."""
    from .headless import trace
    log = trace.read_buslog(path)
    res = {'summary': {str(k): v for k, v in trace.bus_summary(log).items()},
           'waits': log['waits'][:200], 'blits': log['blits'][:200]}
    if frame is not None:
        res['map'] = ['%3d %s' % (v, trace.bus_line(o)) for (f, v), o in sorted(log['lines'].items()) if f == frame]
    return res


def main():
    mcp.run(transport='stdio')


if __name__ == '__main__':
    main()
