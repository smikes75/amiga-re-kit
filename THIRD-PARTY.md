# Third-party components and legal notes

The kit's own code (`src/arek`, `tests`, `docs`) is MIT (see `LICENSE`).

| component | licence | how it is used |
|---|---|---|
| [vAmiga](https://github.com/dirkwhoffmann/vAmiga) emulator core (`Core/`), Dirk W. Hoffmann | MPL-2.0 | **not included**. `src/arek/headless/patches/*.patch` are modifications of its source files; MPL-2.0 requires the modified sources to be made available, which these patch files do. You build `VAHeadless` yourself (see `docs/HEADLESS.md`). |
| vAmiga CPU core Moira (`Core/CPU/Moira`), Dirk W. Hoffmann | MIT | not included. `arek.m68k.timing` follows the form of its `cyclesDiv` for DIVU/DIVS (after Jorge Cwik's analysis of the 68000 microcode); `tests/data/moira68000_cycles.tsv` holds clock counts measured by running Moira |
| vAmiga macOS application | GPL-3.0 | not used |
| [mcp](https://pypi.org/project/mcp/) Python SDK | MIT | optional dependency (`arek-mcp`) |
| Pillow | MIT-CMU | optional dependency (PNG screenshots) |

## What is deliberately absent

* No disk image, no Kickstart ROM, no byte of any game. The tests run on
  synthetic data only (hand-assembled programs, random buffers, generated
  boot blocks and disk images) and on CPU timings measured with Moira.
* No game-specific knowledge: addresses, catalogue layouts, level formats
  live in the per-game projects, not here. The decoder, packers and
  emulator driver are generic.
* The packers implemented (PowerPacker 2.0, Bytekiller family, Turrican II
  three-stage, Atomik) are documented formats re-implemented from the decrunch
  routines; the compressors are not included and not needed.

Paths to copyrighted material go into `local.conf`, which `.gitignore`
excludes. Keep it that way in every project built on the kit.
