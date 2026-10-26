# amiga-re-kit

Tools for reverse-engineering Commodore Amiga games from a disk image —
extracted from three complete game projects
([S.W.I.V.](https://github.com/smikes75/swiv-amiga-re),
[Turrican II](https://github.com/smikes75/turrican2-amiga-re-claude),
[Superfrog](https://github.com/smikes75/superfrog-amiga-re)) and made
game-agnostic. One Python package (`arek`), one command line (`arek`), and an
**MCP server** (`arek-mcp`) so an AI assistant can drive the same instruments
you do.

The method is the point: **first a complete, *measured* description of the
original — only then anything else.** Nothing here guesses. The decoder
refuses instructions it does not model, the walker reports every indirect
jump it cannot follow, the packers verify with the checksums the originals
carry, and the emulator captures are compared byte for byte.

**No game data is included or needed to run the kit.** The tests use a
hand-assembled 20-byte program and random buffers. Your disk image and
Kickstart ROM stay on your machine, referenced from a git-ignored
`local.conf`.

## Install

```sh
pip install -e ".[mcp,dev]"         # or without extras: pip install -e .
python -m pytest                    # 2376 tests: synthetic data + CPU timings measured on Moira
arek --help
```

Optional: a patched headless [vAmiga](https://github.com/dirkwhoffmann/vAmiga)
for anything that runs the original (`arek shot`, `arek bpstate`) — see
[docs/HEADLESS.md](docs/HEADLESS.md). Optional: `m68k-elf-objdump` for
`arek xref`.

## The workflow in commands

```sh
arek init myproject && cd myproject    # skeleton + local.conf (edit the paths)

# 1. measure the disk
arek adf info  disk.adf                # size, sha256, boot block, checksum
arek adf map   disk.adf                # entropy picture, one char per sector
arek adf regions disk.adf              # where code / data / packed blocks sit
arek scan      disk.adf                # packer signatures, verified Bytekiller blocks

# 2. unpack what the loader unpacks
arek adf track  disk.adf -n 1 -o trk1.bin
arek adf ls     disk.adf                              # AmigaDOS files, if the disk has a filesystem
arek adf cat    disk.adf -p LEVELS/L1 -o l1.atn       # one file, data blocks verified
arek pp20       file.pp -o file.bin    # PowerPacker 2.0
arek bytekiller trk1.bin --offset 0x200 -o main.bin
arek t2         INTR -o intr.bin       # Turrican II three-stage
arek atn        BLOCK -o out.bin --offset 0x1234   # Atomik (ATN!), block inside an image
arek hunk info  prog && arek hunk load prog --base 0x20000 -o h   # AmigaDOS executables
arek hunk split prog --chip prog2 --base 0xc00000 0x20000 -o h    # records split over two files

# 3. read the code - flow graph, not linear
arek dis    main.bin --base 0x20700 --walk 0x20700     # only reachable code
arek walk   main.bin --base 0x20700 --start 0x20700    # call tree + frontiers
arek walk   main.bin --base 0x20700 --start 0x20700 --inline 21800:until=8000  # data stored after bsr
arek hwscan main.bin --base 0x20700 --roots 0x20700    # the hardware boundary
arek copper ram.bin --base 0x0 --limit 200             # a copper list from a RAM dump
arek bpstate --address 0x21234 --end 20 --out cap/f --screenshot   # RAM, chip registers and the picture
arek render  cap/f                                     # the frame RAM shows, compared with the picture
arek xref   prog.txt --syms syms.json                  # from an objdump listing
arek dis    main.bin --base 0x20700 --dcw              # linear, undecodable words as dc.w
arek dis    main.bin --base 0x20700 --walk 0x21234 --cycles   # 68000 clock count per instruction

# 4. translate and verify
arek recomp  main.bin --base 0x20700 --auto 0x21234 --main -o draw.c
arek recomp  main.bin --base 0x20700 --auto 0x20700 --refusals ref.json -o game.c   # every frontier as JSON
arek recomp  main.bin --base 0x20700 --auto 0x20700 --overlay 41d5c:b000 --dynamic 21350 -o game.c
arek recomp  intro.bin --base 0x41d5c --auto 0x41d5c --lib --prefix in_:41d5c:4cd5c --overlay-module 41d5c -o intro.c
arek recomp  main.bin --base 0x20700 --auto 0x20700 --timing --profile --main -o game.c   # then AREK_PROFILE=p.txt ./game ...
arek profile p.txt --by clocks                         # which routines to rewrite or replace (--extern) first
arek recomp  main.bin --base c00000 --auto c00000 --cover --oob zero --out game.c   # coverage bitmap; reads outside RAM give 0
arek cover   run1.cov run2.cov game.c.cover.json       # what the runs never executed (union of seeds; routines least covered first)
arek fuzz    --seed 3 --frames 30000 --start 320 --out build/in3.txt   # random input: the emulator (--inputs) and the rebuild alike
arek recomp  main.bin --base 0x20700 --auto 0x21234 --timing \
             --jtab 21300:21400:12:4:bra --indirect 21350=21500,21600 --extern 21700=load_file -o game.c
arek bpstate --address 0x21234 --end 20 --out cap/before
arek bpstate --address 0x21300 --end 20 --out cap/after
arek diff    cap/before cap/after --range 0x60000 0x70000
arek shot    build/shots/title 5 10 --at 3 "joystick2 press 1"
arek trace   run build/l1.vtr --arm 196 --end 199 --break 0xc01106 --range 0:80000 c00000:80000
arek trace   show build/l1.vtr --field px=0xc0599e:h  # one row per hit, emulation never stopped
arek trace   run build/l1.vtr --arm 3 --end 60 --break 0xc01106 --inputs l1.txt --reglog regs.bin  # input per frame
arek trace   compare build/orig.vtr build/native.vtr --best-shift 3   # long parity: where the rebuild leaves the original
arek trace   bus build/bus.bin --frame 8600            # who had the chip bus in every slot (buslog patch)
arek trace   run build/s.vtr --arm 3 --end 176 --shots build/f --shot-frames 8600:8619   # 20 frames, one run
arek trace   run build/w.vtr --arm 3 --end 200 --break 0xc01b06 --poke c01b06:c00faa=00000002  # write into the machine, go on
arek selftest inputs                                   # is this VAHeadless frame exact? (synthetic disk)

# 4b. many scenarios at once (arek.parity.suite): state (traces), picture (--shots), sound (--reglog)
# 5. the web page: display contract wb-shell obraz 1.4 (WB-OBRAZ-CRT.md)
arek web copy web/                                     # the reference wb-obraz.js into the game's page
arek web demo                                          # a page built on it (http://127.0.0.1:8920/demo.html)
arek web test http://localhost:8911/?test=1            # §5.1-5.4b in Chromium (needs playwright)
arek web seal build/present/engine.wasm --set disk1.adf --label "disk 1, retail" --gzip --out build/present/sealed
arek web seal build/present/engine.wasm --payload build/payload.bin --payload-label "the game files" --out build/present/sealed  # any disk version with the same game data opens it
arek web check build/present                           # a bundle: no game data, derived files sealed, manifest right
arek parity  suite.json                                # scenarios against the original: state, picture, sound per tick
arek web copy web/                                     # also wb-nastaveni.js (the shared Display / Sound menu; never overwrites a file that is not from the kit) and wb-zvuk.js (sound contract 1.1)
arek web test http://localhost:8911/?test=1            # ... and §6: the menu and the sound contract, when the page has the hooks

# 6. time inside the frame: the bus model per DMA slot (docs/BUS.md)
arek bus     copy lib/                                 # the model's C sources into a rebuild (arek_bus_glue.h behind the translation's hooks)
arek recomp  main.bin --base c00000 --auto c00000 --timing --bus-table --out game.c   # BUS_TAB: words, extra accesses, flags per instruction
arek selftest bus                                      # the model against this VAHeadless's bus log (synthetic program, BLTPRI blits)
arek --version                                         # version + decoder/recompiler hashes
```

Every command prints what it measured and nothing else. `arek audit
profile.json` produces the JSON inventory + reachability record the method
asks for (see `examples/profile.example.json`).

## What is inside

| module | what it does | origin |
|---|---|---|
| `arek.adf` | geometry, boot block checksum, entropy map / regions, inventory | new |
| `arek.amigados` | AmigaDOS OFS/FFS reader (directories, files, extension blocks, checksums) + synthetic image builder for tests | new |
| `arek.packers.pp20` | PowerPacker 2.0 decruncher (+ literal-only encoder for tests) | Turrican II / Superfrog |
| `arek.packers.bytekiller` | Bytekiller format B (XOR checksum) and the SWIV word-stream format A | S.W.I.V. |
| `arek.packers.turrican2` | Huffman → backwards LZ → RLE three-stage decruncher | Turrican II |
| `arek.packers.atomik` | Atomik (`ATN!`) decruncher with exact block extent (+ greedy LZ test encoder) | Superfrog |
| `arek.packers.scan` | brute-force scan: signatures (PP20, RNC, ATN!, IMP!, …) + verified blocks | S.W.I.V. |
| `arek.hunk` | bounded HUNK reader: CODE/DATA/BSS, RELOC32, split streams; `build()` for probes | Superfrog |
| `arek.copper` | copper list disassembler with custom register names | S.W.I.V. |
| `arek.webtest`, `web/wb-obraz.js` | display contract 1.4: reference module (whole device pixels, CRT canvas, layout quantum of Chromium's 1/64 px), demo page, Chromium tests incl. the row test | Turrican II, Alien Breed, Superfrog (Sonnet) |
| `arek.m68k.cover`, `arek.fuzz` | coverage of a translation run (`recomp --cover`: one bit per translated instruction, `arek cover` lists what never ran) and deterministic random joystick input (`arek fuzz`, one file for `trace run --inputs` and the rebuild) - where a long random run stalls, a bug hides | Superfrog |
| `arek.bus` (`src/arek/bus/*.c`) | the Amiga bus per DMA slot: who owns each slot, the blitter cycle by cycle, the CPU by the accesses of its instructions - on which instruction an interrupt lands, when a blit ends, whether the original overran the frame; `arek_bus_vamiga.c` is MPL-2.0 (derived from vAmiga) | Alien Breed |
| `arek.m68k.timing.bus` | bus cycles n(r/w) of every instruction, opcode and extension words included - what a model of the Amiga bus per DMA slot needs beyond the clock count | Alien Breed |
| `web/wb-nastaveni.js`, `web/wb-zvuk.js` | the shared Display / Sound menu of the rebuilds (same ids, ranges, defaults per mode, storage, optional zoom snapping to the whole-device-pixel zooms; the game adds its items and texts) and the sound contract 1.1: one stereo-width rule, 20 ms gain ramps, the Amiga 500's filters from the schematic in prescribed digital forms, test hooks for `arek web test` §6 | Alien Breed, Superfrog |
| `arek.seal`, `web/wb-seal.js` | code derived from a game on a public page, encrypted (AES-GCM) under a key computed from the contents of the original disk, or from the game's own content as the page's loader rebuilds it (a payload key: every disk version with the same game files opens it); opened in the browser with WebCrypto | presentation pages |
| `arek.parity` | long parity: record by record against the original's trace (first difference, addresses, phase shift); traces packed as XOR + zlib | Alien Breed, Turrican II, Superfrog (Sonnet) |
| `arek.display` | the frame chip RAM shows: Copper timing, bitplanes, dual playfield, EHB, sprites; vAmiga's colours; 0 differing pixels on vAmiga screenshots (`arek selftest display`) | Superfrog (Sonnet), Alien Breed, Turrican II |
| `arek.m68k.decoder` | strict 68000 decoder: raises `Unsupported` instead of guessing; accepts only addressing modes the 68000 accepts (checked opcode by opcode against Moira) | Superfrog (fixed ADDA/SUBA/CMPA); LINK/UNLK/PEA/EXG from Alien Breed; memory shifts, CMPM, ABCD/SBCD, MULS/DIVS new |
| `arek.m68k.disasm` | linear and flow-walk listings straight from the decoder | new |
| `arek.m68k.hwscan` | which routines are pure RAM and which touch custom chips / CIA / ROM | Turrican II |
| `arek.m68k.recomp` | static 68k → C recompiler with a verification driver (`MEM[]`, write log, blitter incl. line and fill modes); jump tables (also with a base register known only at run time), indirect targets, external routines, overlay modules recognised at run time by fingerprint, run-time targets (`--dynamic`), data stored after a call (`Flow`); optional clock counting; a `WAIT_LOOP(m, pc, addr)` hook in loops that poll memory or hardware; chip RAM size and slow RAM (`--memsz`, `--slow c00000:80000`); a routine profile (`--profile`: calls, clocks, written pages per routine - the map for rewriting a recompiled game routine by routine) | Superfrog; extensions from Alien Breed |
| `arek.m68k.timing` | 68000 clock counts per instruction, data-dependent ones included (MUL/DIV operands, shift counts, branch outcome); matches Moira on all 42 247 decodable opcodes | new |
| `arek.m68k.xref` | call / data cross references from `m68k-elf-objdump` text | Superfrog |
| `arek.m68k.audit` | profile-driven inventory + conservative reachability, JSON in / JSON out | Superfrog |
| `arek.headless` | `local.conf`, RetroShell scripts, screenshots, breakpoint captures | Turrican II / Superfrog |
| `arek.headless.trace` | continuous trace reader/driver: VTR1 (chip RAM), VTR2 (chosen ranges), VTW2 (watchpoint + PC) | Turrican II / Alien Breed |
| `arek.contract` | byte-level comparison of captures, register diffs, "untouched" assertions | Superfrog |
| `arek.cli` / `arek.mcp_server` | the command line and the MCP server | new |

Each module's docstring explains the format or the measurement it
implements; [docs/METHOD.md](docs/METHOD.md) explains how they fit together.

## MCP: let an assistant hold the instruments

```sh
pip install -e ".[mcp]"
```

Claude Code (`.mcp.json` in your project, or `claude mcp add arek -- arek-mcp`):

```json
{"mcpServers": {"arek": {"command": "arek-mcp"}}}
```

The server exposes 26 tools (`kit_info`, `adf_info`, `adf_map`, `adf_ls`, `adf_file`, `scan_packed`, `unpack`,
`hunk_load`, `disassemble`, `walk`, `hwscan`, `recomp`, `xref`, `copper`,
`headless_shot`, `headless_bpstate`, `trace_records`, `diff_captures`, `ram_at`, …).
`kit_info` returns the version and the SHA-256 of the decoder and recompiler;
record it with every measurement. All of them
take paths on the local machine; the server never fetches anything, never
writes outside the paths it is given, and only returns measurements — the
assistant sees entropy maps, listings and diffs, not your disk image.

A working session looks like: *"map the disk" → "scan for packed blocks" →
"unpack the block at 0x1f40 and walk it from its entry" → "which of these
routines touch hardware?" → "recompile 0x21234 and compare its RAM writes with
a capture of the original"*. Every answer is backed by a tool result.

## Legal

The kit is MIT (see [LICENSE](LICENSE)). It ships no game data, no ROM, and
no game-specific knowledge — the "engine without data" model: you supply the
image you own. The vAmiga patches are modifications of MPL-2.0 sources and
are published as required; see [THIRD-PARTY.md](THIRD-PARTY.md).

Code comments inside the transplanted modules are partly in Czech (the
projects' working language); public docstrings, the CLI and the docs are
English.
