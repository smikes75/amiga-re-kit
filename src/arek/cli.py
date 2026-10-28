"""``arek`` command line: one entry point for every tool in the kit.

    arek adf info|map|regions|track|sector  IMAGE ...
    arek adf ls|cat|extract  IMAGE [-p PATH] [-o OUT] [--lenient]   (AmigaDOS OFS/FFS)
    arek scan        FILE [--deep]
    arek pp20        FILE -o OUT
    arek bytekiller  FILE -o OUT [--format b|a] [--offset N]
    arek t2          FILE -o OUT
    arek atn         FILE -o OUT [--offset N]
    arek hunk        info|load|split  FILE ... [--chip FILE2]
    arek dis         FILE --base B [--lo --hi | --walk START] [--syms J] [--dcw] [--cycles]
    arek walk        FILE --base B --start S [--lo --hi] [--inline R:SPEC]
    arek hwscan      FILE --base B --roots A.. [--abase An=ADDR] [--chip SIZE] [--inline R:SPEC] [--json]
    arek audit       PROFILE.json [--root DIR]
    arek xref        PROG.txt [--syms J] [--callers A] [--callees LO HI] [--range LO HI]
    arek recomp      FILE --base B [--func S:E[:ENTRY]] [--auto A] [--stub An:D:NAME] -o OUT.c
    arek copper      FILE [--base B]
    arek shot        PREFIX T.. [--at T CMD] [--adf N]
    arek bpstate     --address A --end T --out DIR [--pass N] [--at T CMD] [--region B:L]
    arek trace       run OUT --arm T --end T --break A.. [--watch A..] [--range S:L..] [--at T CMD]
    arek trace       show TRACE [--field NAME=ADDR:FMT ..] [--every N] [--json]
    arek trace       regs REGLOG [--reg NAME..] | audio AUDLOG | pack IN OUT | bus BUSLOG [--frame F]
                     (run: --poke F<frame>:ADDR=HEX | PC:ADDR=HEX|@FILE  writes into the machine and goes on)
    arek trace       compare ORIGINAL REBUILD [--range S:L..] [--ignore S:L..] [--shift N | --best-shift N] [--regs]
                     (run: --inputs FILE --reglog F --audlog F --skip N --from-frame F)
    arek diff        DIR_A DIR_B [--range LO HI]
    arek render      CAPTURE [--ram F --cop A] [--png OUT] [--compare RAW]
    arek selftest    inputs|display|bus|audio [--vahl BINARY]   (needs only the Kickstart ROM)
    arek profile     PROFILE [--by clocks|calls|bytes] [--top N] [--frame F]
    arek cover       RUN.cov [RUN2.cov ...] OUT.cover.json [--top N]  (recomp --cover: what the runs never executed)
    arek host        copy DIR | state CAPTURE OUT [--trace T.vtr]   (the host of a translation, docs/HOST.md)
    arek bus         copy DIR                                        (the bus model per DMA slot: C sources for a rebuild)
    arek fuzz        --seed N --frames N [--hold 3:22] [--start N] [--out FILE]   (random input for both sides)
    arek parity      SUITE.json [--json] [--no-run]                   (scenarios: state, picture, sound)
    arek web         copy DIR [--force] | demo [--port N] | test URL [--quick]   (display contract)
    arek web         seal FILE... --set D1.adf[,D2.adf] [--payload FILE] [--label TEXT] [--gzip] --out DIR   (derived code, opened by the disk or by the game's content)
    arek web         check DIR                                          (a presentation bundle: no game data, derived = sealed)
    arek init        [DIR]

All addresses accept ``0x`` or ``$`` hex, or decimal; the flow specs of ``recomp``
(``--func``, ``--jtab`` ... ``--inline``) are hex with ``0x`` optional. No command needs a game to run
the kit's own tests; the ones that drive the emulator need ``local.conf``.
"""
import argparse
import json
import shlex
import os
import sys
from pathlib import Path


def A(s):
    """A number or address: 0x... or $... hex, otherwise decimal."""
    s = s.strip()
    try:
        return int(s[1:], 16) if s.startswith('$') else int(s, 0)
    except ValueError:
        raise argparse.ArgumentTypeError('%r: write hex as 0x%s or $%s' % (s, s, s)) from None


def _hex(s):
    return int(s.strip().lstrip('$'), 16)


def AH(s):
    """An address where flow specs next to it are bare hex: decimal still works, but a bare
    number that also reads as hex gets a warning."""
    v = A(s)
    if v > 9 and s.strip().isdigit():
        print('arek: %s read as decimal (0x%x); write 0x%s for hex' % (s, v, s), file=sys.stderr)
    return v


def rd(p):
    return Path(p).read_bytes()


def wr(p, b):
    Path(p).write_bytes(b)
    print('%s: %d bytes' % (p, len(b)))


# ----------------------------------------------------------------- adf
def cmd_adf(a):
    from . import adf
    data = rd(a.image)
    if a.what == 'info':
        print(json.dumps(adf.inventory(data, Path(a.image).name), indent=2))
    elif a.what == 'map':
        adf.check_size(data)
        print(adf.ascii_map(data))
        print('legend: . empty  - sparse  c code/data  d dense  # packed (per 512 B sector, 2 tracks per line)')
    elif a.what == 'regions':
        for r in adf.regions(data):
            print('%07x-%07x  trk %3d-%3d  %-9s  %5.2f bits  (%d sectors)' %
                  (r['start'], r['end'], r['track_start'], r['track_end'], r['class'], r['entropy'], r['n']))
    elif a.what == 'track':
        wr(a.out, adf.track(data, a.n))
    elif a.what == 'sector':
        wr(a.out, adf.sector(data, a.n))
    elif a.what == 'ls':
        from . import amigados
        print(amigados.format_listing(data, amigados.listing(data, strict=not a.lenient)))
    elif a.what == 'cat':
        from . import amigados
        if not a.path:
            sys.exit('arek adf cat: -p PATH is required')
        e = amigados.find(data, a.path, strict=not a.lenient)
        if e is None:
            sys.exit('no such file: ' + a.path)
        warn = []
        wr(a.out, amigados.read_file(data, e, strict=not a.lenient, warnings=warn))
        for w in warn:
            print('warning: %s: %s' % (e['path'], w), file=sys.stderr)
    elif a.what == 'extract':
        from . import amigados
        root = Path(a.out if a.out != 'out.bin' else 'files').resolve()
        root.mkdir(parents=True, exist_ok=True)
        for e in amigados.walk(data, strict=not a.lenient):
            if e['type'] != 'file':
                continue
            # names come from the image: confine every destination to ``root``
            parts = e['path'].split('/')
            if any(x in ('', '.', '..') or set(x) & set('\\:\0') for x in parts):
                print('skipping unsafe name %r (header block %d)' % (e['path'], e['block']), file=sys.stderr)
                continue
            dst = root.joinpath(*parts)
            if not dst.resolve().is_relative_to(root):
                print('skipping %r: outside the output directory' % e['path'], file=sys.stderr)
                continue
            warn = []
            body = amigados.read_file(data, e, strict=not a.lenient, warnings=warn)
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(body)
            print('%7d  %s%s' % (len(body), dst, ('  WARNING: ' + '; '.join(warn)) if warn else ''))


# ----------------------------------------------------------------- packers
def cmd_scan(a):
    from .packers import scan
    rep = scan.scan(rd(a.file), deep=a.deep)
    print(json.dumps(rep, indent=2) if a.json else scan.format_report(rep))


def cmd_pp20(a):
    from .packers import pp20
    wr(a.out, pp20.unpack(rd(a.file)))


def cmd_bytekiller(a):
    from .packers import bytekiller
    data = rd(a.file)
    if a.format == 'b':
        out, ok = bytekiller.unpack_b(data, a.offset)
        if not ok:
            print('warning: checksum mismatch', file=sys.stderr)
    else:
        out, _ = bytekiller.unpack_a(data, a.offset)
    wr(a.out, out)


def cmd_t2(a):
    from .packers import turrican2
    wr(a.out, turrican2.unpack_t2(rd(a.file)))


def cmd_atn(a):
    from .packers import atomik
    wr(a.out, atomik.unpack(rd(a.file)[a.offset:]))


# ----------------------------------------------------------------- hunk
def cmd_hunk(a):
    from . import hunk
    data = rd(a.file)
    if a.what == 'info':
        print(json.dumps(hunk.info(data), indent=2))
    elif a.what == 'split':
        if not a.chip or len(a.base) != 2:
            raise ValueError('hunk split needs --chip FILE and --base SLOW_BASE CHIP_BASE')
        for i, (b, body) in enumerate(hunk.split(data, rd(a.chip), a.base[0], a.base[1], a.n_slow)):
            wr('%s_%d_%06x.bin' % (a.out, i, b), body)
    else:
        bases = a.base if len(a.base) > 1 else a.base[0]
        for i, (b, body) in enumerate(hunk.load(data, bases)):
            p = '%s_%d_%06x.bin' % (a.out, i, b)
            wr(p, body)


# ----------------------------------------------------------------- 68k
def _syms(path):
    from .m68k import xref
    return xref.load_syms(path) if path else {}


def cmd_dis(a):
    from .m68k import disasm
    data = rd(a.file)
    syms = _syms(a.syms)
    if a.walk is not None:
        rows, fr = disasm.listing_walk(data, a.base, a.walk, a.lo or a.base, a.hi or a.base + len(data),
                                       cycles=a.cycles, flow=_inline_flow(a))
        print(disasm.format_listing(rows, syms))
        for addr, why in fr:
            print('; frontier %06x: %s' % (addr, why))
    else:
        rows = disasm.listing(data, a.base, a.lo or a.base, a.hi or a.base + len(data), a.limit, dcw=a.dcw,
                              cycles=a.cycles)
        print(disasm.format_listing(rows, syms))


def _inline_flow(a):
    """decoder.Flow with only the --inline descriptions (dis --walk, walk, hwscan)."""
    from .m68k import recomp
    return recomp.flow_from_specs(b'', 0, inline=a.inline or [])


def cmd_walk(a):
    from .m68k import decoder
    data = rd(a.file)
    lo, hi = a.lo or a.base, a.hi or a.base + len(data)
    tree = decoder.call_tree(data, a.base, [a.start], lo, hi, _inline_flow(a))
    for e, (ins, calls, bad, ind) in sorted(tree.items()):
        print('routine %06x: %d instructions, calls %s' % (e, len(ins), ', '.join('%06x' % c for c in sorted(calls))))
        for addr, why in bad:
            print('  undecodable @%06x: %s' % (addr, why))
        for addr, why in ind:
            print('  indirect    @%06x: %s' % (addr, why))


def cmd_hwscan(a):
    from .m68k import hwscan
    data = rd(a.file)
    lo, hi = a.lo or a.base, a.hi or a.base + len(data)
    abase = {}
    for s in a.abase or []:
        reg, val = s.split('=')
        abase[int(reg.lower().lstrip('a'))] = A(val)
    routines = hwscan.scan(data, a.base, a.roots, lo, hi, abase=abase, chip=a.chip, flow=_inline_flow(a))
    ok = hwscan.closure(routines)
    rep = hwscan.report(routines, ok, per_frame=a.per_frame or ())
    print(json.dumps(rep, indent=2) if a.json else hwscan.format_report(rep))


def cmd_audit(a):
    from .m68k import audit
    profile = json.loads(Path(a.profile).read_text())
    print(json.dumps(audit.audit(profile, a.root), indent=2))


def cmd_xref(a):
    from .m68k import xref
    x = xref.Xref.from_file(a.prog, a.syms)
    if a.callers is not None:
        for c in x.callers(a.callers):
            print('%06x' % c)
    elif a.callees:
        for src, t in x.callees_in(a.callees[0], a.callees[1]):
            print('%06x -> %06x %s' % (src, t, x.nm(t)))
    elif a.range:
        for line in xref.disrange(Path(a.prog).read_text(), a.range[0], a.range[1]):
            print(line)
    else:
        print(x.summary(a.top))


def cmd_roots(a):
    from .m68k import roots
    data = rd(a.file)
    r = roots.scan(data, a.base, a.lo, a.hi, min_slots=a.min_slots, min_run=a.min_run, kinds=tuple(a.kinds or ('slots', 'ptr', 'lea', 'imm')))
    print(roots.format_roots(r))
    if a.json:
        with open(a.json, 'w') as f:
            json.dump({'%x' % k: sorted(v) for k, v in sorted(r.items())}, f, indent=1)
    print('%d roots (%s)' % (len(r), ', '.join('%s %d' % (k, sum(1 for v in r.values() if k in v)) for k in ('slots', 'ptr', 'lea', 'imm'))), file=sys.stderr)


def cmd_recomp(a):
    from .m68k import recomp
    data = rd(a.file)
    for s in a.stub or []:
        recomp.add_stub(s)
    funcs = [recomp.parse_func_spec(s) for s in a.func or []]
    flow = recomp.flow_from_specs(data, a.base, a.jtab or [], a.indirect or [], a.stop or [],
                                  a.exitat or [], a.extern or [], a.ret or [], a.prefix, a.lib,
                                  a.inline or [], a.overlay or [], a.dynamic or [], a.overlay_module)
    impl = None
    if a.stub_impl:
        impl = 'notes' if a.stub_impl == 'notes' else Path(a.stub_impl).read_text()
    if a.refusals and os.path.exists(a.refusals):
        os.unlink(a.refusals)
    cover = {} if a.cover else None
    auto = list(a.auto or [])
    for f in a.auto_file or []:
        for line in Path(f).read_text().splitlines():
            tok = line.split('#')[0].split()
            if tok:
                auto.append(int(tok[0], 16))
    report = {}
    try:
        src, stats, entries = recomp.generate(
            data, a.base, funcs, auto, a.lo or a.base, a.hi, with_main=a.main, flow=flow,
            stub_impl=impl, timing=a.timing, memsz=a.memsz,
            slow=tuple(_hex(x) for x in a.slow.split(':')) if a.slow else None, profile=a.profile,
            cover=cover, oob=a.oob, cover_in_tick=a.cover_in_tick, bus_table=a.bus_table,
            auto_soft=a.auto_soft, report=report)
    except recomp.Unsupported as e:
        if a.refusals:
            Path(a.refusals).write_text(json.dumps(recomp.refusal_json(e), indent=1) + '\n')
        if len(e.frontiers) > 1:
            print('arek recomp: %d frontiers%s' % (len(e.frontiers), ' (all in %s)' % a.refusals if a.refusals
                                                   else '; --refusals FILE lists them as JSON'), file=sys.stderr)
        raise
    Path(a.out).write_text(src)
    for root, why in report.get('dropped', []):
        print('arek recomp: root %06x dropped (leads into data: %s)' % (root, why), file=sys.stderr)
    if cover is not None:
        Path(a.out + '.cover.json').write_text(json.dumps(cover) + '\n')
    print('%s: %d entries (%s), %d instruction kinds, %d instructions' %
          (a.out, len(entries), ', '.join('%06x' % e for e in entries), len(stats), sum(stats.values())))
    if a.stats:
        for k, v in sorted(stats.items(), key=lambda kv: -kv[1]):
            print('  %-10s %d' % (k, v))



def cmd_copper(a):
    from . import copper
    print(copper.format_listing(copper.disassemble(rd(a.file), a.base, a.limit)))


# ----------------------------------------------------------------- headless
def _conf(a):
    from .headless import config
    return config.load(a.conf)


def cmd_shot(a):
    from .headless import shot
    conf = _conf(a)
    events = [(int(t), cmd) for t, cmd in a.at or []]
    adf = conf.get('ADF%d' % a.adf)
    for t in a.times:
        print(shot.shot(conf, a.prefix, t, events, adf, timeout=a.timeout))


def cmd_bpstate(a):
    from .headless import bpstate
    conf = _conf(a)
    events = [(int(t), cmd) for t, cmd in a.at or []]
    regions = [tuple(A(x) for x in r.split(':')) for r in a.region or []]
    meta = bpstate.capture(conf, a.out, a.address, a.npass, a.end, events=events,
                           t_set=a.set_at, ram_len=a.ram_len, regions=regions,
                           adf=conf.get('ADF%d' % a.adf), timeout=a.timeout, screenshot=a.screenshot)
    print('%s/cpu.json  pc=%06x  frame=%s' % (a.out, meta['pc'], meta['beam']['frame']))


def cmd_diff(a):
    from . import contract
    x, y = contract.load(a.a), contract.load(a.b)
    ranges = [tuple(a.range)] if a.range else None
    print(contract.format_runs(contract.compare(x['ram'], y['ram'], ranges)))
    regs = contract.diff_regs(x, y)
    if regs:
        print('registers: ' + ', '.join('%s %08x->%08x' % (k, v[0], v[1]) for k, v in sorted(regs.items())))


def cmd_init(a):
    from .headless import config
    root = Path(a.dir)
    root.mkdir(parents=True, exist_ok=True)
    for d in ('roms', 'disks', 'bin', 'build'):
        (root / d).mkdir(exist_ok=True)
    conf = root / 'local.conf'
    if not conf.exists():
        conf.write_text(config.TEMPLATE)
    gi = root / '.gitignore'
    if not gi.exists():
        gi.write_text(GITIGNORE)
    print('project skeleton in %s - edit local.conf (ROM, ADF1, VAHL)' % root)


GITIGNORE = '''# never commit copyrighted material (both cases: git can be case-sensitive)
*.adf
*.ADF
*.adz
*.ADZ
*.dms
*.DMS
*.ipf
*.IPF
*.rom
*.ROM
roms/
disks/
bin/
build/
local.conf
.venv/
'''


def cmd_render(a):
    from . import display
    from .headless import shot
    folder = Path(a.capture) if a.capture else None
    meta = json.loads((folder / 'cpu.json').read_text()) if folder and (folder / 'cpu.json').exists() else {}
    ram_path = a.ram or (folder / meta['ram_file'] if 'ram_file' in meta else None)
    if ram_path is None and folder:
        found = sorted(folder.glob('ram_*_*.bin'))
        ram_path = next((p for p in found if p.name.count('_') == 2), None)
    if ram_path is None:
        raise ValueError('no chip RAM: give a bpstate capture folder or --ram FILE')
    frame = display.render(rd(ram_path), a.cop, chips=meta.get('chips'))
    rgb = display.to_screenshot(frame, display.plain_rgb if a.plain else display.vamiga_rgb)
    out = a.png or (str(folder / 'render.png') if folder else 'render.png')
    shot.write_png(out, display.SHOT_W, display.SHOT_H, rgb)
    print('%s: %d copper writes' % (out, len(frame.writes)))
    ref = a.compare or (folder / 'stable.raw' if folder and (folder / 'stable.raw').exists() else None)
    if ref:
        d = display.diff(rgb, rd(ref))
        print('against %s: %d of %d pixels differ%s' % (ref, d['pixels'], d['total'],
                                                       ', box %s, rows %d' % (d['box'], len(d['rows'])) if d['pixels'] else ''))
        if d['pixels'] and a.fail:
            raise RuntimeError('the render differs from the screenshot')


def cmd_bus(a):
    from . import bus
    if a.what == 'copy':
        for f in bus.copy(a.target):
            print(f)
        return
    if a.what == 'diff':
        from .headless import trace
        if not a.own or a.frame0 is None:
            raise ValueError('arek bus diff BUSLOG OWN.bin --frame0 F [--lines N]')
        log = trace.read_buslog(a.target)
        rows = bus.own_compare(log, bus.own_frames(a.own, a.frame0, lines=a.lines), lines=a.lines)
        print(bus.format_own_compare(rows))
        return
    raise ValueError('arek bus copy DIR | diff BUSLOG OWN.bin --frame0 F')


def cmd_verify(a):
    from .m68k import verify
    from .headless import trace
    if a.what != 'calls':
        raise ValueError('arek verify calls TRACE DRIVER IMAGE --base B')
    image = rd(a.image)
    res = verify.calls(trace.records(a.trace), a.driver, image, a.base, a.vbl, a.max)
    print(verify.format_calls(res))
    if a.json:
        verify.write_json(res, a.json)


def cmd_host(a):
    from . import host
    if a.what == 'copy':
        for f in host.copy(a.target):
            print(f)
        return
    if a.what == 'state':
        if not a.out:
            raise ValueError('arek host state CAPTURE OUT [--trace T.vtr]')
        r = host.state(a.target, a.out, trace=a.trace)
        print('%s: sr %04x frame %d time %d pc %06x' % (r['dir'], r['sr'], r['frame'], r['time'], r['pc']))
        return
    if a.what == 'pack':
        if not a.out:
            raise ValueError('arek host pack STATE_DIR OUT.bin')
        print('%s: %d bytes' % (a.out, host.pack(a.target, a.out)))
        return
    if a.what == 'engine':
        if not (a.game and a.l3 and a.entry):
            raise ValueError('arek host engine OUT_DIR --game game.c --l3 f_xxxxxx --entry f_xxxxxx [--native] [--dynamic] [--ovl F] [--src F] [--run]')
        kw = dict(cc=a.cc, native=a.native, dynamic=a.dynamic, ovl=a.ovl, src=a.src, includes=a.include or (), defines=a.define or (),
                  export=a.export, extra=a.extra or (), thread=a.thread)
        if a.run:
            cmd = host.engine_build(a.target, a.game, a.l3, a.entry, **kw)
            print('built: ' + os.path.join(a.target, ('arek_host_engine_mt' if a.thread else 'arek_host_engine') if a.native else ('engine_mt.js' if a.thread else 'engine.js')))
        else:
            cmd = host.engine_command(a.target, a.game, a.l3, a.entry, **kw)
        print(' '.join(shlex.quote(x) for x in cmd))
        return
    raise ValueError('arek host copy DIR | state CAPTURE OUT | pack STATE OUT.bin | engine OUT_DIR --game ... --l3 ... --entry ...')


def cmd_cover(a):
    from .m68k import cover
    files = list(a.file)
    sidecar = a.sidecar or next((f for f in files if f.endswith('.json')), None)
    if not sidecar:
        raise ValueError('arek cover RUN.cov [RUN2.cov ...] OUT.cover.json')
    dumps = [f for f in files if f != sidecar]
    r = cover.report(cover.read(dumps), sidecar, a.top)
    if a.json:
        print(json.dumps(r, indent=1))
    else:
        print(cover.format_report(r))


def cmd_fuzz(a):
    from . import fuzz
    lo, _, hi = a.hold.partition(':')
    lines = fuzz.inputs(a.seed, a.frames, (int(lo), int(hi or lo)), a.start, a.rest, keys=a.keys)
    if a.out:
        fuzz.write(a.out, lines)
        print('%s: %d frames, seed %d' % (a.out, len(lines), a.seed))
    else:
        print('\n'.join(lines))


def cmd_parity(a):
    from . import parity
    rows = parity.suite(a.suite, a.base, not a.no_run)
    if a.json:
        print(json.dumps(rows, indent=1))
    else:
        print(parity.format_suite(rows))


def cmd_shots(a):
    from . import parity
    r = parity.compare_shots(a.orig, a.rebuild, a.tolerance, a.shift, a.align)
    if a.json:
        print(json.dumps(r, indent=1))
    else:
        print(parity.format_shots(r, a.all))
    return 0 if r['pairs'] and r['equal'] == r['pairs'] else 1


def cmd_profile(a):
    from .m68k import profile
    rows = profile.read(a.file)
    out = profile.summary(rows, a.by, a.top, a.frame)
    if a.json:
        print(json.dumps(out, indent=1))
    else:
        print(profile.format_summary(out, a.by))


def cmd_web(a):
    import hashlib
    import shutil
    web = Path(__file__).parent / 'web'
    if a.what == 'copy':
        dest = Path(a.target or '.')
        dest.mkdir(parents=True, exist_ok=True)
        kept = []
        from .web import FILES as WEB_FILES
        for name in WEB_FILES:
            out = dest / name
            if out.exists() and not a.force and b'amiga-re-kit' not in out.read_bytes()[:4096]:
                kept.append(out)            # the game's own file under a kit name: never overwrite it
                continue
            shutil.copyfile(web / name, out)
            print('%s  sha256 %s' % (out, hashlib.sha256(out.read_bytes()).hexdigest()))
        print('(wb-obraz %s)' % _wb_version(web))
        if kept:
            print('kept, not a kit file (--force overwrites): %s' % ', '.join(str(k) for k in kept))
            return 1
    elif a.what == 'check':
        from . import seal
        if not a.target:
            raise ValueError('web check DIR (a presentation bundle)')
        r = seal.check_bundle(a.target)
        print('%s: %d files, %.2f MB, sealed: %s' % (a.target, r['files'], r['bytes'] / 1e6, ', '.join(r['sealed']) or 'nothing'))
        for rel, n in r['big']:
            print('large: %s (%.1f MB)' % (rel, n / 1e6))
        for p in r['problems']:
            print('PROBLEM: ' + p)
        if r['problems']:
            raise RuntimeError('%d problems' % len(r['problems']))
    elif a.what == 'seal':
        from . import seal
        files = [f for f in [a.target] + (a.rest or []) if f]
        if not files or not (a.set or a.payload) or not a.out:
            raise ValueError('web seal FILE... --set DISK.adf[,DISK2.adf] [--set ...] [--payload FILE ...] --out DIR [--root DIR]')
        root = Path(a.root or '.')
        plain = {str(Path(f).resolve().relative_to(root.resolve())): rd(f) for f in files}
        sets = [[rd(p) for p in spec.split(',')] for spec in a.set or []]
        payloads = [rd(f) for f in a.payload or []]
        manifest, blobs = seal.seal(plain, sets, labels=a.label or [], compress=a.gzip,
                                    payloads=payloads, payload_labels=a.payload_label or [])
        path = seal.write_dir(a.out, manifest, blobs)
        keys = ['disks ' + ','.join(d[:12] for d in k['disks']) if 'disks' in k else 'payload ' + k['payload'][:12] for k in manifest['keys']]
        print('%s: %d files sealed for %d disk sets and %d payloads (%s)' % (path, len(blobs), len(sets), len(payloads), '; '.join(keys)))
    elif a.what == 'payload':
        from . import web as webmod
        from .headless import config
        if not a.atn or not a.out:
            raise ValueError('web payload --atn DISK:OFFSET... --out PAYLOAD.bin [--content content.json] [--conf local.conf]')
        conf = config.load(a.conf) if os.path.exists(a.conf) else {}
        payload, content = webmod.payload_atn([webmod.parse_block(x) for x in a.atn], conf)
        with open(a.out, 'wb') as f:
            f.write(payload)
        if a.content:
            with open(a.content, 'w') as f:
                json.dump(content, f, indent=1)
        print('%s: %d bytes, %d files%s' % (a.out, len(payload), len(content['files']), ' -> ' + a.content if a.content else ''))
    elif a.what == 'strip':
        from . import web as webmod
        if not a.target or not a.rest:
            raise ValueError('web strip IN OUT --drop TAG [--drop TAG2]')
        with open(a.target, encoding='utf-8') as f:
            text = f.read()
        out = webmod.strip(text, tuple(a.drop or ('FULL',)))
        with open(a.rest[0], 'w', encoding='utf-8') as f:
            f.write(out)
        print('%s: %d -> %d lines (without %s)' % (a.rest[0], text.count('\n') + 1, out.count('\n') + 1, ', '.join(a.drop or ('FULL',))))
    elif a.what == 'longrun':
        from . import web as webmod
        if not a.target:
            raise ValueError('web longrun URL [--minutes M] [--interval S] [--sample S]')
        for row in webmod.longrun(a.target, a.minutes, a.interval, a.sample):
            print(webmod.format_longrun(row), flush=True)
    elif a.what == 'smooth':
        from . import websmooth
        if not a.target:
            raise ValueError('web smooth URL [--seconds S] [--browser chromium|webkit|all] [--stalls N] [--stall-ms M] [--json]')
        browsers = websmooth.BROWSERS if a.browser == 'all' else (a.browser,)
        res = websmooth.run(a.target, a.seconds, browsers, a.stalls, a.stall_ms, log=(lambda *x: None) if a.json else print)
        if a.json:
            print(json.dumps(res, indent=1))
        return 0 if all(r.get('passed') for r in res.values() if 'error' not in r) and any('error' not in r for r in res.values()) else 1
    elif a.what == 'serve':
        from . import web as webmod
        from .headless import config
        conf = config.load(a.conf) if os.path.exists(a.conf) else {}
        srv = webmod.serve(a.target or '.', a.port, conf, isolated=a.isolated)
        print('http://127.0.0.1:%d/  (%s; disks of %s at %s%s; Ctrl+C to stop)' % (a.port, a.target or '.', a.conf, ', '.join(sorted(srv.disks)) or 'none',
                                                                                  '; COOP/COEP' if a.isolated else ''), flush=True)
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass
    elif a.what == 'demo':
        import functools
        import http.server
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(web))
        srv = http.server.ThreadingHTTPServer(('127.0.0.1', a.port), handler)
        print('http://127.0.0.1:%d/demo.html  (wb-obraz %s; Ctrl+C to stop)' % (a.port, _wb_version(web)), flush=True)
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass
    else:
        from . import webtest
        if not a.target:
            raise ValueError('web test URL (a page with window.wbObrazTest; arek web demo serves one)')
        try:
            r = webtest.run(a.target, quick=a.quick)
        except ImportError as e:
            raise RuntimeError('web test needs playwright: pip install amiga-re-kit[web] && python -m playwright install chromium') from e
        for f in r['fails'][:30]:
            print('FAIL', f)
        print('%d checks, %d failures' % (r['checks'], len(r['fails'])))
        if r['fails']:
            raise RuntimeError('the page does not follow the display contract')


def _wb_version(web):
    import re
    m = re.search(r"VERSION = '([\d.]+)'", (web / 'wb-obraz.js').read_text())
    return m.group(1) if m else '?'


def cmd_selftest(a):
    from .headless import config, selftest
    conf = config.load(a.conf)
    if a.vahl:
        conf['VAHL'] = os.path.abspath(a.vahl)
    if a.what == 'bus':
        r = selftest.bus(conf, frames=min(a.frames, 120), timeout=a.timeout)
        print('%s: bus model against the bus log of %d frames: fixed DMA slots %d agree / %d disagree; '
              'blits %d, %d end on the same slot, blitter slots %d agree / %d disagree' % (
                  conf['VAHL'], r['frames'], r['fixed_ok'], r['fixed_bad'], r['blits'], r['exact'], r['slots_ok'], r['slots_bad']))
        if r['fixed_bad'] or r['slots_bad'] or r['exact'] != r['blits'] or not r['blits']:
            raise RuntimeError('the bus model and this emulator disagree (files in %s)' % r['dir'])
        return
    if a.what == 'audio':
        r = selftest.audio(conf, frames=min(a.frames, 120), timeout=a.timeout)
        print('%s: Paula model against the logs of %d frames (from frame %d of the window): audio DMA slots %d agree / %d disagree; samples %s' % (
            conf['VAHL'], r['frames'], r['from'] if 'from' in r else 0, r['agree'], r['disagree'],
            ', '.join('ch%d %d/%d exact %d' % (ch, v['model'], v['log'], v['exact']) for ch, v in sorted(r['samples'].items()))))
        q = r.get('irq')
        if q:
            print('interrupt requests: %d detected by the program, %d in the model, %d detections explained (at most %d CCK after the request)%s%s' % (
                q['detected'], q['model'], q['matched'], q['max_delay'],
                '; unexplained detections: %s' % q['unmatched'] if q['unmatched'] else '', '; requests not seen: %s' % q['orphans'] if q['orphans'] else ''))
        # a few detections lag more than the window at the program's own write bursts (line 100 of a setup frame)
        if r['disagree'] or not r['agree'] or (q and q['late'] + q['missing'] > max(2, q['detected'] // 200)):
            raise RuntimeError('the Paula model and this emulator disagree (files in %s)' % r['dir'])
        return
    if a.what == 'display':
        r = selftest.display(conf, timeout=a.timeout, c=a.c)
        print('%s: %s against the screenshot: %d of %d pixels differ' % (conf['VAHL'], 'arek_display.h (C)' if a.c else 'arek.display', r['pixels'], r['total']))
        if r['pixels']:
            raise RuntimeError('the display model and this emulator disagree (files in %s)' % r['dir'])
        return
    r = selftest.inputs(conf, frames=a.frames, timeout=a.timeout)
    print('%s: inputs %d/%d frames exact%s' % (conf['VAHL'], r['match'], r['frames'],
                                               '' if not r['mismatch'] else ', first wrong: %s' % (r['mismatch'][:3],)))
    if r['mismatch'] or not r['frames']:
        raise RuntimeError('VAHL_INPUTS is not frame exact with this build (files in %s)' % r['dir'])


def cmd_trace(a):
    from .headless import trace
    if a.what == 'run':
        from .headless import config
        if a.arm is None or a.end is None or not (a.brk or a.watch or a.buslog or a.reglog or a.audlog or a.shots):
            raise ValueError('trace run needs --arm, --end and --break/--watch (or only --buslog/--reglog/--audlog/--shots)')
        conf = config.load(a.conf)
        ranges = [trace.parse_range(r) for r in a.ranges]
        events = [(float(t), cmd) for t, cmd in a.at]
        n = trace.capture(conf, a.file, events, a.arm, a.end, a.brk, a.watch, ranges or None,
                          timeout=a.timeout, inputs=a.inputs, reglog=a.reglog, audlog=a.audlog,
                          skip=a.skip, from_frame=a.from_frame, buslog=a.buslog,
                          bus_frames=[int(x) for x in a.bus_frames.split(':')] if a.bus_frames else None,
                          reglog_regs=a.reglog_regs, shots=a.shots,
                          shot_frames=[int(x) for x in a.shot_frames.split(':')] if a.shot_frames else None,
                          pokes=a.poke)
        if a.shots:
            print('%d pictures: %s_<frame>.png' % (len(trace.shot_files(a.shots)), a.shots))
        print('%s: %d records' % (a.file, n))
        return
    if a.what == 'bus':
        log = trace.read_buslog(a.file)
        if a.json:
            print(json.dumps({'summary': trace.bus_summary(log), 'waits': log['waits'], 'blits': log['blits']}, indent=1))
            return
        if a.frame is not None:
            for (frame, v), owners in sorted(log['lines'].items()):
                if frame == a.frame:
                    print('%3d %s' % (v, trace.bus_line(owners)))
            return
        for frame, row in trace.bus_summary(log).items():
            slots = ', '.join('%s %d' % kv for kv in sorted(row['slots'].items(), key=lambda kv: -kv[1]))
            print('frame %d: %d lines; %s; CPU waited %d times, %d slots; %d blits'
                  % (frame, row['lines'], slots, row['cpu_waits'], row['cpu_wait_slots'], row['blits']))
        return
    if a.what == 'pack':
        if not a.other:
            raise ValueError('trace pack IN OUT')
        n, before, after = trace.pack(a.file, a.other)
        print('%s: %d records, %d -> %d bytes' % (a.other, n, before, after))
        return
    if a.what == 'compare':
        from . import parity
        if not a.other:
            raise ValueError('trace compare ORIGINAL REBUILD')
        ta, tb = list(trace.records(a.file)), list(trace.records(a.other))
        rng = [trace.parse_range(r)[:2] for r in a.ranges] or None
        ign = [trace.parse_range(r)[:2] for r in a.ignore]
        if a.best_shift:
            for s, eq, n in parity.best_shift(ta, tb, range(-a.best_shift, a.best_shift + 1), rng, ign):
                print('shift %+d: %d of %d pairs equal' % (s, eq, n))
            return
        r = parity.compare(ta, tb, rng, ign, a.shift, a.regs, a.limit)
        if a.json:
            print(json.dumps(r, indent=1, default=str))
        else:
            print(parity.format_compare(r))
        if r['first'] and a.fail:
            raise RuntimeError('the traces differ')
        return
    if a.what == 'targets':
        from .headless import tracetools
        if not a.other:
            raise ValueError('trace targets TRACE IMAGE --base B [--only SITE...] [--out OUT.json]')
        t = tracetools.indirect_targets(trace.records(a.file), rd(a.other), a.base, set(a.only) if a.only else None)
        print(tracetools.format_targets(t))
        if a.out:
            with open(a.out, 'w') as f:
                json.dump({'%x' % s: sorted('%x' % x for x in c) for s, c in t.items()}, f, indent=1)
        return
    if a.what == 'pcs':
        from .headless import tracetools
        if not a.other:
            raise ValueError('trace pcs ORIG.vtr HOST_PC.txt [--tick PC] [--from-frame F] [--image IMG --base B]')
        r = tracetools.pc_compare(trace.records(a.file), tracetools.read_pclog(a.other), a.tick, a.from_frame or 0, a.lines, drift_limit=a.limit)
        print(tracetools.format_pc_compare(r, rd(a.image) if a.image else None, a.base))
        return
    if a.what == 'filter':
        from .headless import tracetools
        if not a.other or not a.pc:
            raise ValueError('trace filter IN.vtr OUT.vtr --pc PC... [--skip N]')
        print('%s: %d records' % (a.other, tracetools.filter_pcs(a.file, a.other, set(a.pc), a.skip or 0)))
        return
    if a.what == 'pairdiff':
        from .headless import tracetools
        if not a.other:
            raise ValueError('trace pairdiff ORIG.vtr HOST.vtr [--from-frame F] [--ignore START:LEN] [--limit N]')
        ign = [trace.parse_range(r)[:2] for r in a.ignore]
        print(tracetools.format_pair_diff(tracetools.pair_diff(list(trace.records(a.file)), list(trace.records(a.other)), a.from_frame or 0, ign, a.limit)))
        return
    if a.what == 'regs':
        rows = [r for r in trace.read_reglog(a.file) if not a.reg or r['name'] in a.reg]
        if a.json:
            print(json.dumps(rows, indent=1))
        else:
            for r in rows:
                print('frame %6d  beam %3d,%3d  %-8s %04x  pc %06x%s' % (
                    r['frame'], r['v'], r['h'], r['name'], r['value'], r['pc'], '  (DMA)' if r['agnus'] else ''))
        return
    if a.what == 'audio':
        per = {}
        for frame, v, h, sample, ch in trace.read_audlog(a.file):
            c = per.setdefault(ch, [0, None, None])
            c[0] += 1
            c[1] = frame if c[1] is None else c[1]
            c[2] = frame
        for ch in sorted(per):
            n, f0, f1 = per[ch]
            print('channel %d: %d samples, frames %d-%d' % (ch, n, f0, f1))
        return
    fields = {}
    for f in a.field:
        name, spec = f.split('=', 1)
        addr, _, fmt = spec.partition(':')
        fields[name] = (A(addr), fmt or 'H')
    rows = trace.summary(a.file, fields)[::max(1, a.every)]
    print(json.dumps(rows, indent=1) if a.json else trace.format_summary(rows, list(fields)))


# ----------------------------------------------------------------- parser
def build_parser():
    p = argparse.ArgumentParser(prog='arek', description='Amiga reverse-engineering kit')
    from . import identity
    ident = identity()
    p.add_argument('--version', action='version', version='arek %s (decoder %s, recomp %s)' % (
        ident['version'], ident['decoder_sha256'][:12], ident['recomp_sha256'][:12]))
    sp = p.add_subparsers(dest='cmd', required=True)

    s = sp.add_parser('adf', help='disk image: info, entropy map, regions, slicing')
    s.add_argument('what', choices=['info', 'map', 'regions', 'track', 'sector', 'ls', 'cat', 'extract'])
    s.add_argument('image')
    s.add_argument('-n', type=int, default=0, help='track / sector number')
    s.add_argument('-o', '--out', default='out.bin', help='output file (cat) or directory (extract)')
    s.add_argument('-p', '--path', help='file path inside the AmigaDOS volume (cat)')
    s.add_argument('--lenient', action='store_true', help='report checksum / header problems instead of failing')
    s.set_defaults(fn=cmd_adf)

    s = sp.add_parser('scan', help='find packed blocks and packer signatures')
    s.add_argument('file')
    s.add_argument('--deep', action='store_true', help='also try Bytekiller format A (slow)')
    s.add_argument('--json', action='store_true')
    s.set_defaults(fn=cmd_scan)

    s = sp.add_parser('pp20', help='unpack a PowerPacker 2.0 file')
    s.add_argument('file')
    s.add_argument('-o', '--out', required=True)
    s.set_defaults(fn=cmd_pp20)

    s = sp.add_parser('bytekiller', help='unpack a Bytekiller block (format B, or A for SWIV)')
    s.add_argument('file')
    s.add_argument('-o', '--out', required=True)
    s.add_argument('--format', choices=['b', 'a'], default='b')
    s.add_argument('--offset', type=A, default=0)
    s.set_defaults(fn=cmd_bytekiller)

    s = sp.add_parser('t2', help='unpack a Turrican II three-stage file')
    s.add_argument('file')
    s.add_argument('-o', '--out', required=True)
    s.set_defaults(fn=cmd_t2)

    s = sp.add_parser('atn', help='unpack an Atomik (ATN!) block')
    s.add_argument('file')
    s.add_argument('-o', '--out', required=True)
    s.add_argument('--offset', type=A, default=0, help='block offset inside an image')
    s.set_defaults(fn=cmd_atn)

    s = sp.add_parser('hunk', help='HUNK executables: info, relocate+dump, or two streams (split)')
    s.add_argument('what', choices=['info', 'load', 'split'])
    s.add_argument('file')
    s.add_argument('--base', type=A, nargs='*', default=[0],
                   help='load: one base (contiguous) or one per hunk; split: SLOW_BASE CHIP_BASE')
    s.add_argument('--chip', help='split: the file with the records of the remaining hunks')
    s.add_argument('--n-slow', type=int, default=2, help='split: hunks whose records are in FILE')
    s.add_argument('-o', '--out', default='hunk')
    s.set_defaults(fn=cmd_hunk)

    s = sp.add_parser('dis', help='disassemble (linear range or flow walk)')
    s.add_argument('file')
    s.add_argument('--base', type=A, required=True)
    s.add_argument('--lo', type=A)
    s.add_argument('--hi', type=A)
    s.add_argument('--walk', type=A, help='entry address: list only reachable code')
    s.add_argument('--dcw', action='store_true', help='linear: write undecodable words as dc.w (reassemblable)')
    s.add_argument('--cycles', action='store_true', help='append the 68000 clock count of each instruction')
    s.add_argument('--limit', type=int)
    s.add_argument('--syms')
    s.add_argument('--inline', nargs='*', metavar='ROUTINE[,..]:until=HHHH|words=N|longs=N|string',
                   help='the routine reads data stored after its call and returns behind it (hex)')
    s.set_defaults(fn=cmd_dis)

    s = sp.add_parser('walk', help='call tree + frontiers from an entry')
    s.add_argument('file')
    s.add_argument('--base', type=A, required=True)
    s.add_argument('--start', type=A, required=True)
    s.add_argument('--lo', type=A)
    s.add_argument('--hi', type=A)
    s.add_argument('--inline', nargs='*', metavar='ROUTINE[,..]:until=HHHH|words=N|longs=N|string',
                   help='the routine reads data stored after its call and returns behind it (hex)')
    s.set_defaults(fn=cmd_walk)

    s = sp.add_parser('hwscan', help='which routines touch hardware vs pure RAM')
    s.add_argument('file')
    s.add_argument('--base', type=A, required=True)
    s.add_argument('--roots', type=A, nargs='+', required=True)
    s.add_argument('--lo', type=A)
    s.add_argument('--hi', type=A)
    s.add_argument('--abase', nargs='*', metavar='An=ADDR', help='known address-register bases at entry')
    s.add_argument('--per-frame', type=A, nargs='*', help='per-frame routines to tag')
    s.add_argument('--chip', type=A, default=0x200000, help='chip RAM size of the machine (default 2 MB); addresses between it and 2 MB count as other')
    s.add_argument('--json', action='store_true')
    s.add_argument('--inline', nargs='*', metavar='ROUTINE[,..]:until=HHHH|words=N|longs=N|string',
                   help='the routine reads data stored after its call and returns behind it (hex)')
    s.set_defaults(fn=cmd_hwscan)

    s = sp.add_parser('audit', help='profile-driven inventory + reachability (JSON)')
    s.add_argument('profile')
    s.add_argument('--root', default='.')
    s.set_defaults(fn=cmd_audit)

    s = sp.add_parser('xref', help='cross references from an objdump listing')
    s.add_argument('prog')
    s.add_argument('--syms')
    s.add_argument('--callers', type=A)
    s.add_argument('--callees', type=A, nargs=2, metavar=('LO', 'HI'), help='what the code in [LO,HI) calls or points at')
    s.add_argument('--range', type=A, nargs=2)
    s.add_argument('--top', type=int, default=40)
    s.set_defaults(fn=cmd_xref)

    s = sp.add_parser('recomp', help='68k -> C static recompilation',
                      description='--base/--lo/--hi/--auto take 0x or $ hex (or decimal, like every '
                                  'address option); --func and the flow specs (--jtab ... --inline) '
                                  'are hex, 0x optional. DISP in --stub is decimal.')
    s.add_argument('file')
    s.add_argument('--base', type=AH, required=True)
    s.add_argument('--func', nargs='*', metavar='START:END[:ENTRY]')
    s.add_argument('--auto', type=AH, nargs='*', metavar='ENTRY')
    s.add_argument('--auto-file', nargs='*', metavar='FILE', help='more --auto entries, one hex address per line (arek roots)')
    s.add_argument('--auto-soft', action='store_true', help='an --auto root that leads into data is dropped with a note '
                   'instead of refusing the translation (static roots from arek roots)')
    s.add_argument('--stub', nargs='*', metavar='An:DISP:NAME')
    s.add_argument('--lo', type=AH)
    s.add_argument('--hi', type=AH)
    s.add_argument('--jtab', nargs='*', metavar='SITE[,..]:TABLE:COUNT:STRIDE:bra|ptr[:AN|an]',
                   help='jsr/jmp (d8,An,Dn) into a table of bra.w slots or pointers; AN = the value of An at the jump, '
                        'an = An known only at run time (slot = (An - TABLE + Dn) / STRIDE)')
    s.add_argument('--indirect', nargs='*', metavar='SITE=T1,T2',
                   help='possible targets of jsr/jmp (An), or of a jmp abs the program rewrites')
    s.add_argument('--stop', nargs='*', metavar='ADDR', help='never translate (a branch into data)')
    s.add_argument('--exitat', nargs='*', metavar='ADDR', help='calling it ends the run (exit_point)')
    s.add_argument('--extern', nargs='*', metavar='ADDR=NAME', help='replace a routine by C NAME(M68 *m)')
    s.add_argument('--ret', nargs='*', metavar='ADDR', help='translation returns here (a loop body as a function)')
    s.add_argument('--prefix', metavar='NAME:LO:HI', help='functions in [LO, HI) are f_NAME<addr> (overlay module)')
    s.add_argument('--lib', action='store_true', help='functions only, sharing the runtime of another translation')
    s.add_argument('--overlay', nargs='*', metavar='BASE:SIZE[:KEY]',
                   help='an area code is loaded into at run time: calls there go to the module whose first '
                        'KEY bytes (default 256) hash the same (overlay_call)')
    s.add_argument('--overlay-module', metavar='BASE[:KEY]',
                   help='this translation (--lib --prefix) is an overlay module; registers under its fingerprint')
    s.add_argument('--dynamic', nargs='*', metavar='SITE',
                   help='jsr/jmp (An) resolved at run time by address over all entries (call_addr)')
    s.add_argument('--stub-impl', metavar='FILE|notes', help='C bodies of the stubs, or "notes" for empty ones')
    s.add_argument('--timing', action='store_true', help='count 68000 clocks per instruction (TICK / CYCLES)')
    s.add_argument('--profile', action='store_true', help='per routine: calls, clocks, written bytes and pages '
                   '(prof_dump; the driver writes $AREK_PROFILE)')
    s.add_argument('--inline', nargs='*', metavar='ROUTINE[,..]:until=HHHH|words=N|longs=N|string',
                   help='the routine reads data stored after its call and returns behind it (hex)')
    s.add_argument('--main', action='store_true', help='append the verification driver main()')
    s.add_argument('--refusals', metavar='FILE', help='on a refusal write every frontier here as JSON '
                   '(routine, site, kind, insn, operand, target, why); removed when the run succeeds')
    s.add_argument('--cover', action='store_true', help='one bit per translated instruction, set when it runs '
                   '(cov_dump / $AREK_COVER); also writes OUT.cover.json for arek cover')
    s.add_argument('--cover-in-tick', action='store_true', help='with --timing: the coverage mark rides in TICK, '
                   'the instruction bodies stay as without --cover')
    s.add_argument('--bus-table', action='store_true', help='the bus table (words, extra accesses, flags per translated instruction, in segments) for the bus model '
                   '(bus/arek_bus_glue.h, build with -DTICK_HOOK -DBUS_HOOK)')
    s.add_argument('--oob', choices=['stop', 'zero'], default='stop',
                   help="an access outside the modelled RAM: stop (exit 3) or zero (reads 0, writes dropped, 'oob N' reported)")
    s.add_argument('--memsz', type=AH, help='chip RAM bytes from 0 (default 0x80000)')
    s.add_argument('--slow', metavar='BASE:SIZE', help='slow RAM, hex, e.g. c00000:80000; the driver '
                   'takes SLOW.bin SLOWOUT.bin as arguments 5 and 6')
    s.add_argument('--stats', action='store_true')
    s.add_argument('-o', '--out', required=True)
    s.set_defaults(fn=cmd_recomp)

    s = sp.add_parser('copper', help='disassemble a copper list')
    s.add_argument('file')
    s.add_argument('--base', type=A, default=0)
    s.add_argument('--limit', type=int, default=4096)
    s.set_defaults(fn=cmd_copper)

    s = sp.add_parser('shot', help='screenshot(s) from the headless emulator')
    s.add_argument('prefix')
    s.add_argument('times', nargs='+', type=int)
    s.add_argument('--at', nargs=2, action='append', metavar=('T', 'CMD'))
    s.add_argument('--adf', type=int, default=1)
    s.add_argument('--conf', default='local.conf')
    s.add_argument('--timeout', type=int, default=600, help='seconds of wall time before giving up')
    s.set_defaults(fn=cmd_shot)

    s = sp.add_parser('bpstate', help='capture CPU + RAM at a breakpoint')
    s.add_argument('--address', type=A, required=True)
    s.add_argument('--pass', dest='npass', type=int, default=0)
    s.add_argument('--set-at', type=int, default=0)
    s.add_argument('--end', type=int, required=True)
    s.add_argument('--at', nargs=2, action='append', metavar=('T', 'CMD'))
    s.add_argument('--ram-len', type=A, default=524288)
    s.add_argument('--region', action='append', metavar='BASE:LENGTH')
    s.add_argument('--adf', type=int, default=1)
    s.add_argument('--conf', default='local.conf')
    s.add_argument('--timeout', type=int, default=900, help='seconds of wall time before giving up')
    s.add_argument('--screenshot', action='store_true', help='also the picture at the stop (stable.raw/png)')
    s.add_argument('--out', required=True)
    s.set_defaults(fn=cmd_bpstate)

    s = sp.add_parser('diff', help='compare two captures')
    s.add_argument('a')
    s.add_argument('b')
    s.add_argument('--range', type=A, nargs=2)
    s.set_defaults(fn=cmd_diff)

    s = sp.add_parser('trace', help='continuous trace of the original (patched VAHeadless)')
    s.add_argument('what', choices=['run', 'show', 'regs', 'audio', 'compare', 'pack', 'bus', 'targets', 'pcs', 'filter', 'pairdiff'])
    s.add_argument('file', help='trace file (written by run, read by show); regs: a reglog, audio: an audlog')
    s.add_argument('other', nargs='?', help='compare/pairdiff: the rebuild trace; pack/filter: the output file; targets: the code image; pcs: the host\'s --pclog file')
    s.add_argument('--base', type=A, default=0, help='targets/pcs: address of the image')
    s.add_argument('--only', type=A, nargs='*', help='targets: only these sites')
    s.add_argument('--out', help='targets: write {site: [targets]} here as JSON')
    s.add_argument('--tick', type=A, help='pcs: start both sides at the first pass of this pc')
    s.add_argument('--image', help='pcs: the code image, to show the instruction before each drift')
    s.add_argument('--lines', type=int, default=313, help='pcs: lines per frame (313)')
    s.add_argument('--pc', type=A, nargs='*', help='filter: the pcs to keep')
    s.add_argument('--ignore', nargs='*', default=[], metavar='START:LEN', help='compare: hex spans to skip')
    s.add_argument('--shift', type=int, default=0, help='compare: record k against record k+SHIFT of the rebuild')
    s.add_argument('--best-shift', type=int, metavar='N', help='compare: try shifts -N..N, report equal pairs')
    s.add_argument('--regs', action='store_true', help='compare: also D0-D7, A0-A7, SR')
    s.add_argument('--limit', type=int, default=20)
    s.add_argument('--fail', action='store_true', help='compare: exit 1 when the traces differ')
    s.add_argument('--arm', type=float, help='second at which breakpoints/watchpoints are set')
    s.add_argument('--end', type=float, help='second at which the run stops')
    s.add_argument('--break', dest='brk', type=A, nargs='*', default=[])
    s.add_argument('--watch', type=A, nargs='*', default=[])
    s.add_argument('--range', dest='ranges', nargs='*', default=[], metavar='START:LEN[h]',
                   help='hex; LENh = only an FNV-1a 64 hash of the range; without it VTR1 = chip RAM. '
                        'compare: only these spans')
    s.add_argument('--inputs', help='run: input per frame (lines of R L U D F S), applied at the first '
                   'breakpoint hit of each frame in the VBL - frame exact')
    s.add_argument('--reglog', help='run: write DMACON/INTENA/INTREQ/ADKCON/AUDx writes here')
    s.add_argument('--audlog', help='run: write every Paula output sample here')
    s.add_argument('--skip', type=int, help='run: no records for the first N hits')
    s.add_argument('--from-frame', type=int, help='run: no records before this frame')
    s.add_argument('--reg', nargs='*', help='regs: only these registers, e.g. DMACON AUD0VOL')
    s.add_argument('--buslog', help='run: chip bus use per line, CPU waits and blits here (buslog patch)')
    s.add_argument('--bus-frames', metavar='FIRST:LAST', help='run: frames the bus log covers (default all)')
    s.add_argument('--frame', type=int, help='bus: the slot map of this frame, one line per raster line')
    s.add_argument('--reglog-regs', metavar='SPEC', help='run: registers --reglog records, hex, e.g. 0e0-0f6,08e,090,180-1be')
    s.add_argument('--shots', metavar='PREFIX', help='run: the picture of every frame in --shot-frames (PREFIX_<frame>.png)')
    s.add_argument('--shot-frames', metavar='FIRST:LAST', help='run: frames --shots covers')
    s.add_argument('--poke', nargs='*', metavar='F<frame>|PC:ADDR=HEX|@FILE',
                   help='run: write into the machine when frame F begins (decimal) or at the first breakpoint hit '
                        'at PC (hex, give it with --break), then go on; e.g. F8600:c00ffc=0002, c01b06:c00faa=@world.bin')
    s.add_argument('--at', nargs=2, action='append', default=[], metavar=('T', 'CMD'), help='input event')
    s.add_argument('--field', nargs='*', default=[], metavar='NAME=ADDR:FMT', help='show: value to read, e.g. px=0xc0599e:h')
    s.add_argument('--every', type=int, default=1)
    s.add_argument('--json', action='store_true')
    s.add_argument('--conf', default='local.conf')
    s.add_argument('--timeout', type=int, default=1200, help='run: seconds of wall time before giving up')
    s.set_defaults(fn=cmd_trace)

    s = sp.add_parser('render', help='the frame chip RAM shows (Copper, bitplanes, sprites) as PNG, vs a screenshot')
    s.add_argument('capture', nargs='?', help='a bpstate folder (cpu.json chips, RAM, stable.raw)')
    s.add_argument('--ram', help='chip RAM dump instead of the capture folder')
    s.add_argument('--cop', type=A, help='Copper list (default: COP1LC from cpu.json)')
    s.add_argument('--png', help='output (default: CAPTURE/render.png)')
    s.add_argument('--compare', help='RGB24 716x285 screenshot (default: CAPTURE/stable.raw)')
    s.add_argument('--plain', action='store_true', help='colours as nibble x 17 instead of the vAmiga monitor')
    s.add_argument('--fail', action='store_true', help='exit 1 when the render differs from the screenshot')
    s.set_defaults(fn=cmd_render)

    s = sp.add_parser('bus', help='the bus model per DMA slot (C sources for a rebuild); diff: a host\'s slot maps against a bus log')
    s.add_argument('what', choices=['copy', 'diff'])
    s.add_argument('target', help='copy: destination folder; diff: the bus log (VAHL_BUSLOG)')
    s.add_argument('own', nargs='?', help='diff: the maps a host wrote with --own')
    s.add_argument('--frame0', type=int, help='diff: the frame number of the host\'s first map')
    s.add_argument('--lines', type=int, default=313, help='diff: lines per frame (313)')
    s.set_defaults(fn=cmd_bus)
    s = sp.add_parser('verify', help='translated routines against the original call by call (docs/HOST.md)')
    s.add_argument('what', choices=['calls'])
    s.add_argument('trace', help='a trace with breakpoints on jsr abs.l sites and the addresses after them')
    s.add_argument('driver', help='the recomp --main driver of the translation')
    s.add_argument('image', help='the code image the trace was taken on')
    s.add_argument('--base', type=A, default=0, help='address of the image')
    s.add_argument('--vbl', type=A, help='the interrupt handler: pairs it fell into are left out')
    s.add_argument('--max', type=int, default=3, help='calls per routine (3)')
    s.add_argument('--json', help='write the results here')
    s.set_defaults(fn=cmd_verify)
    s = sp.add_parser('roots', help='static roots for a whole-game translation: bra.w slot tables, pointer tables, lea/pea table bases, move.l #code (docs/METHOD.md)')
    s.add_argument('file')
    s.add_argument('--base', type=AH, required=True)
    s.add_argument('--lo', type=AH, help='code range start (default: the image)')
    s.add_argument('--hi', type=AH, help='code range end')
    s.add_argument('--min-slots', type=int, default=4, help='bra.w slots in a row that make a table (4)')
    s.add_argument('--min-run', type=int, default=1, help='code pointers in a row that count (1: single pointers too)')
    s.add_argument('--kinds', nargs='*', choices=['slots', 'ptr', 'lea', 'imm'], help='which kinds (default all)')
    s.add_argument('--json', help='write {address: [kinds]} here')
    s.set_defaults(fn=cmd_roots)
    s = sp.add_parser('host', help='the host of a translation (C sources: time, interrupts, CIAs, Paula, picture) and its state')
    s.add_argument('what', choices=['copy', 'state', 'pack', 'engine'])
    s.add_argument('target', help='copy: destination folder; state: a bpstate capture folder; pack: the state folder; engine: the output folder')
    s.add_argument('out', nargs='?', help='state: the state folder to write; pack: the file to write')
    s.add_argument('--trace', help='state: a trace armed at the same stop (its record 0 gives SR when cpu.json has none)')
    s.add_argument('--game', help='engine: the translation (arek recomp --timing --bus-table, no --main)')
    s.add_argument('--l3', help='engine: the translated level-3 handler (HOST_L3)')
    s.add_argument('--entry', help='engine: the translated routine the run starts in (HOST_ENTRY)')
    s.add_argument('--native', action='store_true', help='engine: build with the C compiler (the check line) instead of Emscripten')
    s.add_argument('--dynamic', action='store_true', help='engine: go on at the popped return address when the entry returns (ENGINE_DYNAMIC)')
    s.add_argument('--thread', action='store_true', help='engine: the game in its own thread over shared memory (pthreads, no ASYNCIFY; the page needs COOP/COEP)')
    s.add_argument('--ovl', help='engine: the overlay modules file (OVL_SRC)')
    s.add_argument('--src', help='engine: the project file with its extern routines and hooks (ENGINE_SRC)')
    s.add_argument('--include', action='append', help='engine: an include folder (repeatable)')
    s.add_argument('--define', action='append', help='engine: a NAME=VALUE for the compiler (repeatable)')
    s.add_argument('--cc', help='engine: the compiler (emcc / cc)')
    s.add_argument('--export', default='ArekEngine', help='engine: the module factory name (EXPORT_NAME)')
    s.add_argument('--extra', action='append', help='engine: an extra compiler argument (repeatable)')
    s.add_argument('--run', action='store_true', help='engine: run the command')
    s.set_defaults(fn=cmd_host)
    s = sp.add_parser('cover', help='coverage of a translation run (recomp --cover): what never ran')
    s.add_argument('file', nargs='+', help='dumps the runtime wrote (AREK_COVER or cov_dump; several = their union) '
                   'and OUT.cover.json written by recomp --cover')
    s.add_argument('--sidecar', help='OUT.cover.json when it does not end in .json')
    s.add_argument('--top', type=int, default=20, help='least covered routines to list (0 = all)')
    s.add_argument('--json', action='store_true')
    s.set_defaults(fn=cmd_cover)
    s = sp.add_parser('fuzz', help='random joystick input (R L U D F S per frame) for the emulator and a rebuild alike')
    s.add_argument('--seed', type=int, required=True)
    s.add_argument('--frames', type=int, required=True)
    s.add_argument('--hold', default='3:22', help='frames a press lasts, min:max (default 3:22)')
    s.add_argument('--start', type=int, default=0, help='frames of nothing at the start')
    s.add_argument('--rest', type=float, default=0.25, help='share of spans with nothing held')
    s.add_argument('--keys', default='RLUDFS', help='keys allowed')
    s.add_argument('--out', help='write the file (default: print)')
    s.set_defaults(fn=cmd_fuzz)
    s = sp.add_parser('parity', help='a suite of scenarios against the original: state, picture, sound per tick')
    s.add_argument('suite', help='SUITE.json (see arek.parity.suite)')
    s.add_argument('--base', default='.', help='paths in the suite are relative to this folder')
    s.add_argument('--no-run', action='store_true', help="do not run a scenario's make command for a missing original trace")
    s.add_argument('--json', action='store_true')
    s.set_defaults(fn=cmd_parity)
    s = sp.add_parser('shots', help='the pictures of two runs (PREFIX_<frame>.raw, RGB24) paired by frame, with a screen-shake alignment')
    s.add_argument('orig', help='the original\'s prefix (arek trace run --shots)')
    s.add_argument('rebuild', help='the rebuild\'s prefix (host_trace --shots)')
    s.add_argument('--align', type=int, default=0, help='try shifts up to N pixels per pair and take the best (a shake)')
    s.add_argument('--tolerance', type=int, default=0, help='a channel difference up to this is equal')
    s.add_argument('--shift', type=int, default=0, help='rebuild frame = original frame + N')
    s.add_argument('--all', action='store_true', help='list every pair, not only the differing ones')
    s.add_argument('--json', action='store_true')
    s.set_defaults(fn=cmd_shots)
    s = sp.add_parser('profile', help='routine profile of a translation run (recomp --profile): what to rewrite first')
    s.add_argument('file', help='the profile the runtime wrote (AREK_PROFILE or prof_dump)')
    s.add_argument('--by', choices=['clocks', 'calls', 'bytes'], default='clocks')
    s.add_argument('--top', type=int, default=20)
    s.add_argument('--frame', type=int, help='one frame of a per-frame dump')
    s.add_argument('--json', action='store_true')
    s.set_defaults(fn=cmd_profile)

    s = sp.add_parser('web', help='display contract: reference wb-obraz.js, demo page, Chromium tests (WB-OBRAZ-CRT.md)')
    s.add_argument('what', choices=['copy', 'demo', 'test', 'seal', 'check', 'payload', 'serve', 'strip', 'longrun', 'smooth'])
    s.add_argument('target', nargs='?', help='copy: destination folder (writes wb-obraz.js, wb-seal.js, wb-nastaveni.js, '
                   'wb-zvuk.js, wb-atn.js, wb-content.js, wb-touch.js, wb-takt.js, wb-zvuk-out.js, wb-zvuk-worklet.js); serve: the bundle folder (default .); demo: nothing - it serves the package\'s demo.html on http://127.0.0.1:PORT/demo.html '
                   '(the file itself is arek/web/demo.html in the installed package); test: URL of a page with window.wbObrazTest; '
                   'seal: the first file; check: a presentation bundle folder; strip: the source file; longrun / smooth: the URL of a page with globalThis.WBLONGRUN')
    s.add_argument('rest', nargs='*', help='seal: more files; strip: the output file')
    s.add_argument('--drop', action='append', metavar='TAG', help='strip: the variant to cut out (lines //@TAG, blocks //@TAG{ ... //@}TAG); default FULL')
    s.add_argument('--isolated', action='store_true', help='serve: send the COOP / COEP headers (cross-origin isolation)')
    s.add_argument('--minutes', type=float, default=3.0, help='longrun: how long to play (default 3)')
    s.add_argument('--interval', type=float, default=30.0, help='longrun: seconds between samples (default 30)')
    s.add_argument('--sample', type=float, default=3.0, help='longrun: seconds of frames per sample (default 3)')
    s.add_argument('--seconds', type=float, default=30.0, help='smooth: seconds of scrolling to sample (default 30)')
    s.add_argument('--browser', choices=['chromium', 'webkit', 'all'], default='all', help='smooth: which browsers (default all installed)')
    s.add_argument('--stalls', type=int, default=10, help='smooth: artificial stalls of the main thread (default 10)')
    s.add_argument('--stall-ms', type=int, default=150, help='smooth: length of a stall (default 150 ms)')
    s.add_argument('--json', action='store_true', help='smooth: the metrics as JSON')
    s.add_argument('--set', action='append', metavar='DISK.adf[,DISK2.adf]',
                   help='seal: a disk set that opens the files (repeat for other versions)')
    s.add_argument('--out', help='seal: output folder (seal.json + FILE.sealed)')
    s.add_argument('--root', help='seal: paths in seal.json are relative to this folder (default .)')
    s.add_argument('--label', action='append', metavar='TEXT', help='seal: a name for each --set, in order')
    s.add_argument('--payload', action='append', metavar='FILE',
                   help="seal: the game's content as the page's loader builds it (unpacked files in a fixed order); "
                        'every disk version that yields the same bytes opens the files (repeat for other contents)')
    s.add_argument('--payload-label', action='append', metavar='TEXT', help='seal: a name for each --payload, in order')
    s.add_argument('--gzip', action='store_true', help='seal: gzip the files before sealing (wb-seal.js inflates)')
    s.add_argument('--port', type=int, default=8920, help='demo: port of the local server (Ctrl+C stops it)')
    s.add_argument('--quick', action='store_true', help='test: fewer combinations')
    s.add_argument('--force', action='store_true', help='copy: overwrite a file under a kit name that is not from the kit')
    s.add_argument('--atn', nargs='*', metavar='DISK:OFFSET', help='payload: ATN! blocks in order (DISK = path or a local.conf key, e.g. ADF1:0x57800)')
    s.add_argument('--content', help='payload: write content.json (sizes and hashes, no game data) here for wb-content.js')
    s.add_argument('--conf', default='local.conf', help='payload/serve: the local.conf with the disks')
    s.set_defaults(fn=cmd_web)

    s = sp.add_parser('selftest', help='check a VAHeadless build on a synthetic disk: inputs frame by frame, display model, bus model, Paula model')
    s.add_argument('what', choices=['inputs', 'display', 'bus', 'audio'])
    s.add_argument('--c', action='store_true', help='display: the C renderer (arek_display.h) instead of arek.display')
    s.add_argument('--conf', default='local.conf', help='needs ROM (and VAHL unless --vahl)')
    s.add_argument('--vahl', help='the binary to test instead of VAHL from the conf')
    s.add_argument('--frames', type=int, default=240)
    s.add_argument('--timeout', type=int, default=300)
    s.set_defaults(fn=cmd_selftest)

    s = sp.add_parser('init', help='create a project skeleton with local.conf')
    s.add_argument('dir', nargs='?', default='.')
    s.set_defaults(fn=cmd_init)
    return p


def main(argv=None):
    from .m68k.decoder import Unsupported
    a = build_parser().parse_args(argv)
    try:
        rc = a.fn(a)
    except Unsupported as e:
        print('arek %s: refused: %s' % (a.cmd, e), file=sys.stderr)
        return 2
    except (ValueError, RuntimeError, FileNotFoundError, FileExistsError) as e:
        print('arek: %s' % e, file=sys.stderr)
        return 1
    except BrokenPipeError:                      # arek ... | head
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 0
    return rc if isinstance(rc, int) else 0      # a command's own exit code (web copy kept a file, web check failed)


if __name__ == '__main__':
    raise SystemExit(main())
