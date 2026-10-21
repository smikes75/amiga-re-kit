# VAHeadless — the headless vAmiga as a measuring instrument

Everything that *runs* the original (`arek shot`, `arek bpstate`, the
`headless_*` MCP tools) drives a headless build of
[vAmiga](https://github.com/dirkwhoffmann/vAmiga) through its RetroShell
scripting. The stock `VAHeadless` target is almost enough; three small
changes make it a reliable instrument. They are shipped as patches in
`src/arek/headless/patches/` (vAmiga is MPL-2.0; publishing modified
sources is what the licence asks for).

## Build (macOS, Command Line Tools, cmake)

```sh
git clone https://github.com/dirkwhoffmann/vAmiga.git vamiga-src
cd vamiga-src
git checkout 899da5d                      # or c59425d for the other patch
git apply ../amiga-re-kit/src/arek/headless/patches/vamiga-headless-899da5d.patch
cmake -S Core -B build -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_CXX_FLAGS="-nostdinc++ -isystem /Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/include/c++/v1"
cmake --build build --target VAHeadless -j8      # ~3 min
cp build/VAHeadless /path/to/myproject/bin/
```

The `-nostdinc++ / -isystem` pair works around the truncated libc++ headers
in `/Library/Developer/CommandLineTools/usr/include/c++/v1/`; without it
even `#include <limits>` fails. On Linux a plain `cmake` build works.

Two patch variants are included:

| patch | vAmiga commit | `wait N frames` |
|---|---|---|
| `vamiga-headless-c59425d.patch` | c59425d (5.0b2, Sep 2026) | fixed 313-line PAL frame |
| `vamiga-headless-899da5d.patch` | 899da5d (Oct 2026) | follows the current beam format (`Beam::cyclesPerFrames`) — use this one |

**Do not measure disk loaders with c59425d.** A VAHeadless built from c59425d
loses the first sector of every track on the disk-DMA path a custom
trackloader uses: the MFM burst runs sector 10 straight into sector 1 with
sector 0 and the track gap missing (measured in the Alien Breed project:
the game's own OFS loader fails with error 26 on root block 880, sector 0 of
track 80; reads of sector 1 succeed; the same disk and loader work on
899da5d). The ROM `trackdisk.device` path was not affected in that test.
Which upstream commit between the two fixed it is not known. Use 899da5d.

Optional patches on top of the headless one:

| patch | base | adds |
|---|---|---|
| `vamiga-trace.patch` | c59425d | `VAHL_TRACE`: every breakpoint hit writes a VTR1 record (registers, beam, chip RAM) and the run continues |
| `vamiga-trace-ranges-899da5d.patch` | 899da5d | the same, plus `VAHL_TRACE_RANGES=start:len,...` (VTR2: only chosen ranges, incl. slow RAM, custom registers, CIA) and watchpoints (VTW2: + PC of the accessing instruction) |
| `vamiga-regtrace.patch` | c59425d | ring buffer of every custom register write (WASM builds) |
| `vamiga-wasm.patch` | c59425d | WebAssembly build without the emulation thread |

Other masters may need the three hunks transplanted by hand; they are small.

## What the patch changes (three places)

1. **`Agnus.cpp`, `operator<<(SerResetter)`** — RetroShell wakeups (the
   `wait` command, slots `SLOT_RSH0..2`) survive a *soft reset*. The 68000
   `RESET` instruction triggers one; Kickstart executes it on reboot after a
   Guru Meditation and some games execute it deliberately (Turrican II after
   "press fire"). Without the patch every such reset silently kills the
   script instead of producing a frame.
2. **`Console.cpp`, command `wait`** — unit `frames` (`wait 50 frames`).
   Stock `wait` takes whole seconds only; a second is 28 000 000 master
   cycles = 49.26 PAL frames, not 50.
3. **`Headless.cpp`** — when the emulator stops on a `break` / `watch` /
   `catch` point, the RetroShell script named by the environment variable
   **`VAHL_ONSTOP`** is executed (registers, `mem save bin`, `shutdown`).
   The remaining lines of the main script are discarded first
   (`RetroShellAPI::abortScript`), otherwise a pending `wait` would freeze
   the paused machine. `break at $ADDR N` stops at the (N+1)-th hit.

## RetroShell facts the kit relies on (verified on 5.0b2)

- One command per line; **the script stops at the first error**.
- `screenshot save X.png` always writes **`X.raw`** (RGB24, 716 × 285) and
  terminates the process. **The path must be absolute**; with a relative
  path the file silently does not appear. `arek.headless.shot` handles both.
- The emulator is deterministic: same script → bit-identical `.raw`.
- Numbers: decimal, or `$hex` / `0xhex` / `%bin` (`c00000` is "not a
  number", `$c00000` is fine).
- `mem save bin FILE ADDR COUNT` dumps memory (chip RAM `0 524288`, slow RAM
  `$c00000 524288`).
- `debugger` switches console; inside: `r cpu`, `d [$addr]`, `w.w VALUE ADDR`
  (write RAM, value first), `break at ADDR [N]`, `watch at ADDR`,
  `catch vector N`, `? agnus beam` (clock, frame, beam position).
  `commander` switches back. The ONSTOP script starts with `try debugger`
  so it works from either console.
- `regression setup A500_OCS_1MB "ROM"` = 68000, OCS Agnus and Denise, PAL,
  512 KB chip + 512 KB slow, no turbo. Other profiles: `A1000_OCS_1MB`,
  `A500_ECS_1MB`, `A500_PLUS_1MB`, `A1200_2MB`. Memory can be changed after
  setup (`mem set CHIP_RAM 1024`).
- In warp mode Denise swaps its frame buffer only every 17th frame
  (`DENISE_FRAME_SKIPPING = 16`); a screenshot could be 16 frames older than
  the RAM dump. The kit always sets `denise set FRAME_SKIPPING 0`.
- `-v` mirrors the shell output on stdout (the kit uses it for `bpstate`),
  `-m` prints emulator messages. Output is buffered — end scripts with
  `shutdown`, do not kill the process.

## A capture, step by step

```
arek bpstate --address 0x21234 --pass 0 --end 20 --out cap/draw_in \
             --at 3 "joystick 1 press fire" --region 0xc00000:0x80000
```

writes `cap/draw_in/capture_21234_0.retrosh` (the script), `onstop_*.retrosh`
(what ran at the stop), `capture.log` (shell output), `ram_21234_0.bin`
(chip RAM from 0), `ram_21234_0_c00000.bin` (the extra region) and
`cpu.json`:

```json
{"d": [...], "a": [...], "pc": 136756, "ccr": {"x":0,"n":1,"z":0,"v":0,"c":0},
 "beam": {"clock": 123456789, "frame": 1003, "position": [100, 20]},
 "machine": "A500_OCS_1MB", "events": [[3, "joystick 1 press fire"]],
 "breakpoint": 136756, "skip": 0, "ram_sha256": "...", "assets": {"ROM": "...", "ADF": "..."}}
```

The asset hashes tie the capture to the exact ROM, disk and emulator
binary — a capture made with a different build is a different measurement
and `arek diff` will tell you so by the differences it finds.

## Continuous trace

`bpstate` stops once per run. To follow the original over many frames, build
VAHeadless with a trace patch and let every breakpoint hit write a record
while the emulation runs on (`arek.headless.trace`, `arek trace`, MCP
`trace_records`):

```sh
arek trace run build/l1.vtr --arm 196 --end 199 --break 0xc01106 \
    --range 0:80000 c00000:80000 dff000:200 bfe000:1000 \
    --at 14 "mouse1 press left"
arek trace show build/l1.vtr --field px=0xc0599e:h --field cam=0xc031fc:h
```

`--arm` is the second at which `debugger` / `break at $ADDR 0` / `watch at
$ADDR 0` / `commander` are issued; before that the run is untouched. Without
`--range` each record carries the whole chip RAM (VTR1, `VAHL_TRACE_LEN`
bytes). Records are read-only snapshots (`spypeek`): a trace never changes
the run it records, so its frames line up with a plain `arek shot` of the
same script.

## Known caveat: `mem save bin` and chip bus timing

In the stock memory debugger `mem save bin` reads through `peek8<CPU>`,
which advances Agnus/DMA during the export: a chip RAM dump taken while
the Blitter is mid-operation is not an instantaneous snapshot of that
boundary. Registers and clock are captured *before* the export, so they
are exact; slow RAM dumps and cycle traces are unaffected. The Superfrog
project carries an additional `spypeek`-based probe patch for cycle-exact
mid-blit exports; it is not part of this kit yet.
