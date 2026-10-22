"""``arek`` command line: one entry point for every tool in the kit.

    arek adf info|map|regions|track|sector  IMAGE ...
    arek adf ls|cat|extract  IMAGE [-p PATH] [-o OUT] [--lenient]   (AmigaDOS OFS/FFS)
    arek scan        FILE [--deep]
    arek pp20        FILE -o OUT
    arek bytekiller  FILE -o OUT [--format b|a] [--offset N]
    arek t2          FILE -o OUT
    arek atn         FILE -o OUT [--offset N]
    arek hunk        info|load  FILE ...
    arek dis         FILE --base B [--lo --hi | --walk START] [--syms J] [--dcw]
    arek walk        FILE --base B --start S [--lo --hi]
    arek hwscan      FILE --base B --roots A.. [--abase An=ADDR] [--chip SIZE] [--json]
    arek audit       PROFILE.json [--root DIR]
    arek xref        PROG.txt [--syms J] [--callers A] [--callees LO HI] [--range LO HI]
    arek recomp      FILE --base B [--func S:E[:ENTRY]] [--auto A] [--stub An:D:NAME] -o OUT.c
    arek copper      FILE [--base B]
    arek shot        PREFIX T.. [--at T CMD] [--adf N]
    arek bpstate     --address A --end T --out DIR [--pass N] [--at T CMD] [--region B:L]
    arek trace       run OUT --arm T --end T --break A.. [--watch A..] [--range S:L..] [--at T CMD]
    arek trace       show TRACE [--field NAME=ADDR:FMT ..] [--every N] [--json]
    arek diff        DIR_A DIR_B [--range LO HI]
    arek init        [DIR]

All addresses accept ``0x`` hex or decimal. No command needs a game to run
the kit's own tests; the ones that drive the emulator need ``local.conf``.
"""
import argparse
import json
import sys
from pathlib import Path


def A(s):
    return int(s, 0)


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
                                       cycles=a.cycles)
        print(disasm.format_listing(rows, syms))
        for addr, why in fr:
            print('; frontier %06x: %s' % (addr, why))
    else:
        rows = disasm.listing(data, a.base, a.lo or a.base, a.hi or a.base + len(data), a.limit, dcw=a.dcw,
                              cycles=a.cycles)
        print(disasm.format_listing(rows, syms))


def cmd_walk(a):
    from .m68k import decoder
    data = rd(a.file)
    lo, hi = a.lo or a.base, a.hi or a.base + len(data)
    tree = decoder.call_tree(data, a.base, [a.start], lo, hi)
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
    routines = hwscan.scan(data, a.base, a.roots, lo, hi, abase=abase, chip=a.chip)
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


def cmd_recomp(a):
    from .m68k import recomp
    data = rd(a.file)
    for s in a.stub or []:
        recomp.add_stub(s)
    funcs = [recomp.parse_func_spec(s) for s in a.func or []]
    flow = recomp.flow_from_specs(data, a.base, a.jtab or [], a.indirect or [], a.stop or [],
                                  a.exitat or [], a.extern or [], a.ret or [], a.prefix, a.lib)
    impl = None
    if a.stub_impl:
        impl = 'notes' if a.stub_impl == 'notes' else Path(a.stub_impl).read_text()
    src, stats, entries = recomp.generate(data, a.base, funcs, a.auto or [],
                                          a.lo or a.base, a.hi, with_main=a.main, flow=flow,
                                          stub_impl=impl, timing=a.timing)
    Path(a.out).write_text(src)
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
        print(shot.shot(conf, a.prefix, t, events, adf))


def cmd_bpstate(a):
    from .headless import bpstate
    conf = _conf(a)
    events = [(int(t), cmd) for t, cmd in a.at or []]
    regions = [tuple(A(x) for x in r.split(':')) for r in a.region or []]
    meta = bpstate.capture(conf, a.out, a.address, a.npass, a.end, events=events,
                           t_set=a.set_at, ram_len=a.ram_len, regions=regions,
                           adf=conf.get('ADF%d' % a.adf))
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
        gi.write_text('# never commit copyrighted material\n*.adf\n*.rom\nroms/\ndisks/\nbin/\nbuild/\nlocal.conf\n')
    print('project skeleton in %s - edit local.conf (ROM, ADF1, VAHL)' % root)


def cmd_trace(a):
    from .headless import trace
    if a.what == 'run':
        from .headless import config
        if a.arm is None or a.end is None or not (a.brk or a.watch):
            raise ValueError('trace run needs --arm, --end and --break and/or --watch')
        conf = config.load(a.conf)
        ranges = [tuple(int(x, 16) for x in r.split(':')) for r in a.ranges]
        events = [(float(t), cmd) for t, cmd in a.at]
        n = trace.capture(conf, a.file, events, a.arm, a.end, a.brk, a.watch, ranges or None)
        print('%s: %d records' % (a.file, n))
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

    s = sp.add_parser('hunk', help='HUNK executables: info or relocate+dump')
    s.add_argument('what', choices=['info', 'load'])
    s.add_argument('file')
    s.add_argument('--base', type=A, nargs='*', default=[0], help='one base (contiguous) or one per hunk')
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
    s.set_defaults(fn=cmd_dis)

    s = sp.add_parser('walk', help='call tree + frontiers from an entry')
    s.add_argument('file')
    s.add_argument('--base', type=A, required=True)
    s.add_argument('--start', type=A, required=True)
    s.add_argument('--lo', type=A)
    s.add_argument('--hi', type=A)
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

    s = sp.add_parser('recomp', help='68k -> C static recompilation')
    s.add_argument('file')
    s.add_argument('--base', type=A, required=True)
    s.add_argument('--func', nargs='*', metavar='START:END[:ENTRY]')
    s.add_argument('--auto', type=A, nargs='*', metavar='ENTRY')
    s.add_argument('--stub', nargs='*', metavar='An:DISP:NAME')
    s.add_argument('--lo', type=A)
    s.add_argument('--hi', type=A)
    s.add_argument('--jtab', nargs='*', metavar='SITE[,..]:TABLE:COUNT:STRIDE:bra|ptr[:AN]',
                   help='jsr/jmp (d8,An,Dn) into a table of bra.w slots or pointers; '
                        'all flow addresses are hex, as in --func')
    s.add_argument('--indirect', nargs='*', metavar='SITE=T1,T2',
                   help='possible targets of jsr/jmp (An), or of a jmp abs the program rewrites')
    s.add_argument('--stop', nargs='*', metavar='ADDR', help='never translate (a branch into data)')
    s.add_argument('--exitat', nargs='*', metavar='ADDR', help='calling it ends the run (exit_point)')
    s.add_argument('--extern', nargs='*', metavar='ADDR=NAME', help='replace a routine by C NAME(M68 *m)')
    s.add_argument('--ret', nargs='*', metavar='ADDR', help='translation returns here (a loop body as a function)')
    s.add_argument('--prefix', metavar='NAME:LO:HI', help='functions in [LO, HI) are f_NAME<addr> (overlay module)')
    s.add_argument('--lib', action='store_true', help='functions only, sharing the runtime of another translation')
    s.add_argument('--stub-impl', metavar='FILE|notes', help='C bodies of the stubs, or "notes" for empty ones')
    s.add_argument('--timing', action='store_true', help='count 68000 clocks per instruction (TICK / CYCLES)')
    s.add_argument('--main', action='store_true', help='append the verification driver main()')
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
    s.add_argument('--out', required=True)
    s.set_defaults(fn=cmd_bpstate)

    s = sp.add_parser('diff', help='compare two captures')
    s.add_argument('a')
    s.add_argument('b')
    s.add_argument('--range', type=A, nargs=2)
    s.set_defaults(fn=cmd_diff)

    s = sp.add_parser('trace', help='continuous trace of the original (patched VAHeadless)')
    s.add_argument('what', choices=['run', 'show'])
    s.add_argument('file', help='trace file (written by run, read by show)')
    s.add_argument('--arm', type=float, help='second at which breakpoints/watchpoints are set')
    s.add_argument('--end', type=float, help='second at which the run stops')
    s.add_argument('--break', dest='brk', type=A, nargs='*', default=[])
    s.add_argument('--watch', type=A, nargs='*', default=[])
    s.add_argument('--range', dest='ranges', nargs='*', default=[], metavar='START:LEN', help='hex; without it VTR1 = chip RAM')
    s.add_argument('--at', nargs=2, action='append', default=[], metavar=('T', 'CMD'), help='input event')
    s.add_argument('--field', nargs='*', default=[], metavar='NAME=ADDR:FMT', help='show: value to read, e.g. px=0xc0599e:h')
    s.add_argument('--every', type=int, default=1)
    s.add_argument('--json', action='store_true')
    s.add_argument('--conf', default='local.conf')
    s.set_defaults(fn=cmd_trace)

    s = sp.add_parser('init', help='create a project skeleton with local.conf')
    s.add_argument('dir', nargs='?', default='.')
    s.set_defaults(fn=cmd_init)
    return p


def main(argv=None):
    from .m68k.decoder import Unsupported
    a = build_parser().parse_args(argv)
    try:
        a.fn(a)
    except Unsupported as e:
        print('arek %s: refused: %s' % (a.cmd, e), file=sys.stderr)
        return 2
    except (ValueError, RuntimeError, FileNotFoundError, FileExistsError) as e:
        print('arek: %s' % e, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
