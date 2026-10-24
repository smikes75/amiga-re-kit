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

**Which build do I have?** Both commits print `vAmiga Headless v5.0b2`; only
the build date in the banner differs. Measure it instead: break right after
the game's own loader returns (`arek bpstate --address <return>`) and compare
the loaded bytes with the sectors of the ADF. A c59425d build shows sector 0
of each track as zeros (measured again in the Superfrog Sonnet project: 10 of
11 sectors, the 899da5d build 11 of 11). Record the sha256 of the binary
(`cpu.json` → `assets.VAHL`) next to the result.

A run that hangs ends after `--timeout` seconds of wall time (`shot` 600,
`bpstate` 900, `trace run` 1200) with an error naming the binary.

Optional patches on top of the headless one:

| patch | base | adds |
|---|---|---|
| `vamiga-trace.patch` | c59425d | `VAHL_TRACE`: every breakpoint hit writes a VTR1 record (registers, beam, chip RAM) and the run continues |
| `vamiga-trace-ranges-899da5d.patch` | 899da5d | the same, plus `VAHL_TRACE_RANGES=start:len,...` (VTR2: only chosen ranges, incl. slow RAM, custom registers, CIA) and watchpoints (VTW2: + PC of the accessing instruction) |
| `vamiga-shots-regset-899da5d.patch` | 899da5d + the four above | `VAHL_SHOTS` + `VAHL_SHOTS_FRAMES`: the picture of every frame in a window, the run goes on; `VAHL_REGLOG_REGS`: which registers `VAHL_REGLOG` records (from the Alien Breed project's requests) |
| `vamiga-poke-899da5d.patch` | 899da5d + the five above | `VAHL_POKE`: write into the machine's memory when a frame begins or at the first breakpoint hit at a PC, then go on (`arek trace run --poke`); also fixes the frame number of `VAHL_SHOTS` pictures (they were labelled one too high) and makes `VAHL_REGLOG` see the Copper's colour writes |
| `vamiga-buslog-899da5d.patch` | 899da5d + headless + trace-ranges + inputs-reglog | `VAHL_BUSLOG` (+ `VAHL_BUSLOG_FRAMES=first:last`): the owner of every DMA slot of every line, CPU waits with their PC, every blit with its registers and end (`arek trace bus`) |
| `vamiga-inputs-reglog-899da5d.patch` | 899da5d + headless + trace-ranges | `VAHL_INPUTS` (input per frame, frame exact), `VAHL_REGLOG` (DMACON/INTENA/INTREQ/ADKCON/AUDx writes), `VAHL_AUDLOG` (Paula output samples), `VAHL_TRACE_SKIP`, `VAHL_TRACE_FROM_FRAME`, hashed ranges `start:lenh` (from the Alien Breed project) |
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
- Input (measured on 5.0b2; the kit refuses the spaced forms before the run):

  | command | does |
  |---|---|
  | `joystick2 press 1` / `joystick2 unpress 1` | fire button down / up (button number; port 2 = the game port, port 1 = the mouse port) |
  | `joystick2 pull left\|right\|up\|down` / `joystick2 release x\|y` | push / centre an axis |
  | `mouse1 press left\|right` | a mouse button |
  | `keyboard press 64` | a raw Amiga keycode (`$40` = space) |

  `joystick 1 press fire` is a syntax error, `joystick2 press fire` "not a
  number"; `mouse1` and `keyboard` take no `release`. After an error the
  script stops (see the first point).
- In warp mode Denise swaps its frame buffer only every 17th frame
  (`DENISE_FRAME_SKIPPING = 16`); a screenshot could be 16 frames older than
  the RAM dump. The kit always sets `denise set FRAME_SKIPPING 0`.
- `-v` mirrors the shell output on stdout (the kit uses it for `bpstate`),
  `-m` prints emulator messages. Output is buffered — end scripts with
  `shutdown`, do not kill the process.

## A capture, step by step

```
arek bpstate --address 0x21234 --pass 0 --end 20 --out cap/draw_in \
             --at 3 "joystick2 press 1" --region 0xc00000:0x80000
```

writes `cap/draw_in/capture_21234_0.retrosh` (the script), `onstop_*.retrosh`
(what ran at the stop), `capture.log` (shell output), `ram_21234_0.bin`
(chip RAM from 0), `ram_21234_0_c00000.bin` (the extra region) and
`cpu.json`:

```json
{"d": [...], "a": [...], "pc": 136756, "ccr": {"x":0,"n":1,"z":0,"v":0,"c":0},
 "beam": {"clock": 123456789, "frame": 1003, "position": [100, 20]},
 "machine": "A500_OCS_1MB", "events": [[3, "joystick2 press 1"]],
 "breakpoint": 136756, "skip": 0, "ram_sha256": "...", "assets": {"ROM": "...", "ADF": "..."},
 "chips": {"agnus": {"DMACON": 720, "BPL0PT": ..., ...}, "copper": {"COP1LC": 1056, ...},
           "denise": {...}, "paula": {"INTENA": ...}, "blitter": {...}}}
```

`chips` are the emulator's custom registers at the stop (`r agnus`, `r copper`,
`r denise`, `r paula`, `r blitter`), write-only ones included - the Copper list
address, DMACON, bitplane and sprite pointers are there without reading the
game's code. vAmiga 5.0b2 labels two lines COP1LC and two BPL6PT; the repeated
name is stored as `NAME#2`.

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

## Long parity: `arek trace compare`, `arek trace pack`

Run the original with `arek trace run --inputs` and let the rebuild's engine write the
same records for the same input, then compare record k with record k (+ shift):

```sh
arek trace compare build/orig.vtr build/native.vtr --range c01776:300 --ignore c0197a:2
arek trace compare build/orig.vtr build/native.vtr --best-shift 3      # out of phase?
arek trace pack build/orig.vtr build/orig.vtp                          # XOR + zlib, read as before
```

The report names the first record that differs (hit and frame on both sides) with its
words, the records that differ and the addresses that differ most often; `--regs` adds
D0-D7/A0-A7/SR, hashed ranges (`start:lenh`) are compared by hash (or against the bytes the
other side captured). `arek.parity` is the API, MCP `trace_compare` the tool.

A rebuild writes VTR2 records (little endian) - in C:

```c
/* one record per breakpoint-equivalent point, e.g. at the VBL handler */
uint32_t h[24] = { 0x32525456 /* VTR2 */, pc, hit, frame, v, hpos, sr,
                   d0, d1, d2, d3, d4, d5, d6, d7, a0, a1, a2, a3, a4, a5, a6, a7,
                   1 /* ranges */ };
uint32_t r[2] = { start, length };
fwrite(h, 4, 24, f); fwrite(r, 4, 2, f); fwrite(ram + start, 1, length, f);  /* bytes as in RAM */
```

(`trace.encode` writes the same from Python.) Registers the engine does not keep can be 0;
compare without `--regs` then.

## The chip bus: `--buslog`, `arek trace bus`

A rebuild that runs every frame in time needs to know what the 68000 really waited for.
`vamiga-buslog-899da5d.patch` records it; the run needs no breakpoint that is ever hit:

```sh
arek trace run build/b.vtr --arm 3 --end 176 --break 0xfffff0 --buslog build/bus.bin --bus-frames 8600:8601 \
    --at 30 "mouse1 press left" ...
arek trace bus build/bus.bin                     # per frame: slots by owner, CPU waits, blits
arek trace bus build/bus.bin --frame 8600        # the slot map, one raster line per row
```

The slot map uses `.` free, `C` CPU, `R` refresh, `D` disk, `A` audio, `1`-`8` bitplanes, `S`
sprites, `c` Copper, `b` blitter. A lowres line with 6 planes reads `462C351C` per fetch group,
4 planes in dual playfield `4C2.3C1.` (synthetic display disk). Measured on a game level
(Superfrog, frame 8600): 95 blits, 9 940 blitter slots, the CPU waited 29 557 slots - against
12 663 in the next frame without blits. `trace.read_buslog`, `bus_summary`, `bus_line`; MCP
`trace_bus`. The patch only records; the run is the same as without it.

## Writing into the running machine: `--poke`

To put the original into a later state without playing there (a game's own password or level
bytes, a counter), `vamiga-poke-899da5d.patch` writes into memory at a chosen moment and the
run goes on - RetroShell could only do that stopped, and its `wait` is not frame exact:

```sh
arek trace run build/w2.vtr --arm 3 --end 200 --break 0xc01b06 --poke c01b06:c00faa=00000002 \
    F8600:c00ffc=0002 --shots build/w2 --shot-frames 8600:8603
```

`F<frame>:ADDR=HEX` writes when that frame (decimal) begins; `PC:ADDR=HEX` at the first
breakpoint hit at PC (hex; give the PC with `--break`); `=@FILE` writes a file's bytes. The
writes go through `Memory::patch` (no bus cycles) and each applies once; the log says
`vahl poke ...` for each. Checked on the synthetic display disk: a COLOR00 word poked when
frame 300 begins is written by the Copper in frame 300 (`--reglog`) and picture 300 shows it.
Builds with the shots patch alone label a picture one frame too high; with the poke patch the
label is the frame that was drawn. Copper colour writes (COLOR00-31) reach the register log
only with the poke patch (vAmiga writes them past `pokeCustom16`).

## Consecutive pictures, chosen registers

`screenshot save` ends the process, so N pictures used to be N runs, and `wait 1
frames` between them is not frame exact. With `vamiga-shots-regset-899da5d.patch`:

```sh
arek trace run build/s.vtr --arm 3 --end 176 --shots build/f --shot-frames 8600:8619 \
    --reglog build/regs.bin --reglog-regs 0e0-0f6,08e,090,100-104,180-1be --at 30 "mouse1 press left" ...
arek trace regs build/regs.bin --reg DIWSTRT DIWSTOP BPL1PTL
```

writes `build/f_008600.png` … one per finished frame (the same cutout as `screenshot
save`) and every CPU or Copper (`(DMA)`) write to the chosen registers with the beam -
the bitplane pointers and display window that `spypeek` cannot read back. A run with
only logs or pictures needs no `--break`.

## The picture: `--screenshot`, `arek render`, `selftest display`

`arek bpstate ... --screenshot` also saves the picture at the stop (`stable.raw`,
RGB24 716 × 285, and `stable.png`; the last frame Denise finished). `arek render
CAPTURE` draws the frame that the captured chip RAM shows with `arek.display` (Copper
from COP1LC in `cpu.json` "chips", bitplanes, sprites, vAmiga's colours) and compares it
with that picture pixel by pixel. `arek selftest display` does the same on a synthetic boot
disk (dual playfield, scroll, EHB, sprites; `src/arek/headless/selftest_display.s`) and
expects 0 differing pixels - a check of both the model and the emulator build.

## Input frame by frame, register and audio logs

RetroShell events are placed by `wait`, and `wait 1 frames` waits 1.4 frames
on average (measured in the Alien Breed project): a recorded input then lands
a frame early or late and a run diverges from the recording within a second.
`vamiga-inputs-reglog-899da5d.patch` applies inputs inside the emulator instead:

```sh
arek trace run build/l1.vtr --arm 3 --end 60 --break 0xc01106 \
    --inputs build/l1_inputs.txt --range c0599e:2 0:80000h \
    --reglog build/l1_regs.bin --audlog build/l1_audio.bin
arek trace regs  build/l1_regs.bin --reg DMACON AUD0PER
arek trace audio build/l1_audio.bin
```

- `--inputs FILE`: one line per frame with the keys held - `R L U D F S`
  (right, left, up, down, fire on joystick 2, space); an empty line holds
  nothing. Line k is applied at the k-th frame in which a breakpoint is hit at
  v < 100, so `--break` must include an address of the VBL handler (the first
  hit of a frame counts; a copper interrupt lower on the screen does not take a
  line). The trace is armed at `--arm`; line 0 is the first VBL after it.
- `--range START:LENh`: an FNV-1a 64 hash of the range instead of its bytes
  (`rec['hashes']`, `trace.fnv1a64`) - long traces that only need to know
  *when* RAM diverges.
- `--reglog FILE`: 16 bytes per write to DMACON, INTENA, INTREQ, ADKCON and
  AUD0-3: frame, beam, register, value, PC, CPU or DMA (`trace.read_reglog`).
- `--audlog FILE`: 12 bytes per sample Paula outputs: frame, beam,
  sample × volume, channel (`trace.read_audlog`).
- `--skip N`, `--from-frame F`: no records for the first N hits / before frame F.
- Line k applies in frame OFF + k, OFF = the frame of the first breakpoint hit (measured in the
  Superfrog Sonnet project); the breakpoint must be hit first in each frame.
- `arek trace compare` on game state: counters the VBL handler bumps every frame differ even when
  the game matches - leave them out with `--ignore START:LEN` (hex), e.g. `--ignore c01978:4`.
- `wait N frames` after `debugger` / `break at` / `commander` prints `std::exception` in
  the log; the wait still happens (Alien Breed project).

`arek trace run` refuses a binary that does not know the variables it needs
(a build without the patch would ignore them, or stop at the first breakpoint
and hang). **`arek selftest inputs`** checks a build without any game: it boots a
synthetic disk whose VBL handler stores JOY1DAT and the fire bit of every frame,
feeds it a pseudo-random input file and compares frame by frame (240 of 240
expected; needs only the Kickstart ROM).

## Known caveat: `mem save bin` and chip bus timing

In the stock memory debugger `mem save bin` reads through `peek8<CPU>`,
which advances Agnus/DMA during the export: a chip RAM dump taken while
the Blitter is mid-operation is not an instantaneous snapshot of that
boundary. Registers and clock are captured *before* the export, so they
are exact; slow RAM dumps and cycle traces are unaffected. The Superfrog
project carries an additional `spypeek`-based probe patch for cycle-exact
mid-blit exports; it is not part of this kit yet.
