# The host of a translation (`arek.host`, kit 0.7.0)

Path B of the kit translates the game's 68000 code to C (`arek recomp`). The translation is only
the CPU's work: it reads and writes RAM and the custom registers, counts clocks, and calls hooks.
Everything the chipset does around it - when the bus is free, when a frame ends, when an
interrupt lands, what the CIAs answer, what Paula fetches and outputs, what Denise shows - is the
*host*. Every project wrote its own; `arek host copy DIR` gives the one the Alien Breed II project
measured against the original per instruction, with the kit's models behind it:

| file | what |
|---|---|
| `arek_host_pre.h` | the macros before the translation: `TICK_HOOK`, `BUS_HOOK`, `HW_HOOK`, `CIA_HOOK`, `AREK_GLUE_NO_TICK`, `main` renamed |
| `arek_host.h` | time from the bus model (`arek_bus_glue.h`), the beam (VPOSR/VHPOSR), INTREQ and the interrupt levels 1-6 (entry cost 44 clocks / 7 accesses after the E-clock phase), CIA-A (PRA/SDR/ICR/DDRA, the LED bit, the E-clock cost of every access), Paula (`arek_bus_paula.h`) and the sound (`arek_audio.h`), the picture (`arek_display.h`), the next frame's map behind the current one, shots |
| `arek_display.h` | `arek.display` in C, line by line as the beam passes, with CPU writes in mid-frame; the DDFSTRT delay and the sprite slot rule (below); `arek selftest display --c`: 0 of 204 060 pixels differ |
| `arek_host_disk.h` | the game's disk reads from images given at run time (`AHD_EXTERN`, below) |
| `arek_host_engine.c` | the engine of a web page: Emscripten ASYNCIFY, frames on demand, picture / sound / inputs / disks through its API; natively the check line (below) |
| `arek_host_engine_check.js` | the wasm engine in Node, printing the check line of the native build |
| `arek_audio.h` | the four channels' bytes as 48 kHz stereo int16 (left 0 + 3, right 1 + 2) |
| `arek_host_trace.c` | the driver: the game from a state of the original with inputs per frame, records in the trace format, `--pclog`, `--own`, `--reglog`, `--audlog`, `--shots` |
| `arek_display_render.c` | one frame from a RAM image with the C renderer (the tests and the self-test) |

## Building a host

```
arek recomp image.bin --base 0 --auto ROOTS... --timing --bus-table --slow c00000:80000 -o game.c
arek bus copy lib && arek host copy lib
cc -O2 -I lib -DGAME_SRC='"game.c"' -DTICK_PC=0xc01c72u -DHOST_ENTRY=f_c01c72 -DHOST_L3=f_c13e1c \
   lib/arek_host_trace.c lib/arek_bus.c lib/arek_bus_vamiga.c -lm -o host_trace
```

`HOST_L3` is the translated level-3 handler (the vector at $6C, measured with `arek bpstate`);
`HOST_L1`, `HOST_L2`, `HOST_L4`, `HOST_L5`, `HOST_L6` likewise when the game enables those levels
(a level without a handler stays pending; level 4 comes from the Paula model's interrupt requests - the first
word after DMA on and the end of every block - as a sound driver that chains blocks through AUDxINT needs).
The host calls a handler directly (`H_ENTER`), never through a pointer, so a browser build with
`ASYNCIFY_IGNORE_INDIRECT` can sleep in a wait loop inside the handler (Alien Breed II, G37).
`HOST_ACK_HANDLER(name, bits)` makes a handler that only acknowledges INTREQ bits, for a level the
game leaves to Kickstart (`-DHOST_L4=host_ack_audio` is predefined for the audio requests the Paula
model raises); without it the request would be taken again and again.

The CIAs: CIA-A PRA / DDRA / SDR / ICR as before, and both CIAs' timers A and B (the latch, one-shot
or continuous, START, FORCE LOAD, the ICR status and mask; an E tick = 5 CCK; CIA-A raises PORTS,
CIA-B EXTER), which a loader waiting on CIA-B timer A needs (G38). Other CIA registers answer $FF
and count in `H_IO_UNKNOWN` unless the host defines `HOST_CIA_READ(a, &v)` / `HOST_CIA_WRITE(a, v)`
(return 1 when handled). POTGO's output bits read back in POTGOR (G40), and LACE is taken from the
renderer's registers, so the Copper's BPLCON0 alternates the fields too (G39). `TICK_PC` is the pc of the game's tick (the main loop's
head, where the records are taken) and `HOST_ENTRY` the translated routine the run starts in. A
game that uses no slow RAM leaves `--slow` out; the driver follows `SLOWSZ`.

The state the driver starts from comes from a capture of the original:

```
arek bpstate --address 0xc01c72 --set-at 293 --end 300 --ram-len 0x80000 --region 0xc00000:0x80000 ... --out cap/s0
arek host state cap/s0 state0            # chip.bin, slow.bin, creg.bin, state.txt (SR, beam time, INTREQ, CIA, frame)
./host_trace state0 run.vtr 1490 inputs.txt --skip-stack 0xfa0
arek trace compare orig.vtr run.vtr      # or arek parity suite.json
```

`cpu.json` gives D/A, PC, the beam, the custom registers (`creg.bin`) and, when the build prints
them, SR (`Flags`) and CIA-A; a trace armed at the same stop supplies SR otherwise (`--trace`).

## What the host does on every instruction (`tick_hook`)

1. finishes the previous instruction's internal cycles, so time events and records see its end;
2. `host_events`: two lines before the end of the frame the next frame's map is laid behind the
   current one (an instruction crossing the frame end sees the refresh and the Copper of line 0:
   measured 18 CCK, not 11); at the end: Paula to the end, the picture, shots, `h_frame_done_cb`,
   the new frame (`arek_glue_frame`, `arek_paula_frame`), VERTB pending, `h_frame_cb` (inputs);
   VERTB becomes visible `H_VBL_LAT` (10) CCK into the frame; COPER when the Copper wrote INTREQ;
3. Paula's events up to now, the picture up to the current line;
4. `h_pc_cb(m, pc)` - the emulator's breakpoint fires here, before an interrupt is accepted, and
   again after the handler's rte;
5. an interrupt if a level above the mask is pending and enabled: the E-clock phase (`H_IRQ_E`),
   44 clocks with 7 accesses on the bus, SR and PC to the stack, the translated handler, its rte;
6. the instruction's own accesses and internal cycles through the bus model (`arek_glue_insn`).

The runtime's hooks the host answers: `hw_read_hook` for VPOSR, VHPOSR, INTREQR, JOY0DAT, JOY1DAT,
POTGOR; `hw_write_hook` for every register write (the picture, INTREQ, Paula, `h_wr_cb`);
`cia_read_hook` / `cia_write_hook` for CIA-A PRA ($BFE001: fire buttons, the LED output bit),
SDR, ICR, DDRA; every other CIA byte reads $FF and is counted (`io_unknown`). A CIA access costs
`H_CIA_A + ((H_CIA_B - phase) mod 10)` CPU clocks, phase = (2 x absolute CCK) mod 10, fitted on
three instructions; `HOST_CIA_A=-1` restores the fixed 7 CCK of the glue.

Environment for calibration: `HOST_VBL_LAT`, `HOST_IRQ_PRE`, `HOST_IRQ_CYC`, `HOST_IRQ_ACC`,
`HOST_IRQ_E`, `HOST_CIA_A`, `HOST_CIA_B`, `HOST_CIA_LOG`, `HOST_LINES` (312 for a short frame),
`HOST_IRQ_DEBUG`.

## The picture (`arek_display.h`)

The same model as `arek.display` (Copper MOVE/WAIT/SKIP, lowres bitplanes 1-6, dual playfield,
EHB, sprites with attached pairs and priorities, vAmiga's colours), drawn line by line when the
host's beam has passed the line, so a CPU write to a display register applies from that line.
The rules the Alien Breed II project and `arek selftest display` measured, in both renderers
(kit 0.7.0, 0.7.1):

- with DDFSTRT not a multiple of 8 the first pixel is delayed by `(scroll + 2 * (DDFSTRT & 7)) & 15`
  (measured for BPLCON1 $88 $FF $99 $77 $33 $11 against `VAHL_SHOTS`);
- the sprites' DMA as vAmiga's Agnus and Denise do it: on line 25 (with sprite DMA on) VSTOP of
  every sprite is forced to 25, so its control words are fetched; VSTART turns the data DMA on,
  VSTOP off; the words are taken in the sprite's slots of the line ($15 + 4n: POS or the first
  data word, $17 + 4n: CTL or the second; lines 25-310) after the Copper's writes before them
  (a DMACON write at the start of the line counts for its slots); a data word arms Denise, a CTL
  word (by DMA or a register write) disarms it;
- a slot is not served without DMACON SPREN and DMAEN (a Copper write to DMACON sets or clears
  its bits) or, on a line with bitplane DMA, from `DDFSTRT - 1` on (DDFSTRT $24: sprite 3 gets
  one word, sprites 4-7 none); the missing word keeps the old register, which the screen shows
  as a striped sprite and a vertical line, as the emulator does, and a sprite whose VSTOP passes
  while its slots are not served keeps showing its last data (to the end of the vertical display
  window; nothing is drawn outside the window). `ARD_SPR_FULL = 1` draws the sprites as if the
  bitplanes took no slot (a rebuild's enhanced mode); `ARD_LAST` is the frame's last line (the
  host sets it from its LOF), where sprite DMA stops;
- HAM6 (bits 4-5 = palette / blue / red / green from the previous pixel, the chain starting at
  COLOR00 on every line), hires (2 words per 8-CCK block, 4 planes, the first pixel at
  `2 * DDFSTRT + 9`, the Copper's slots in 4-CCK blocks), with 6 lowres planes the Copper gets
  both free even slots of a fetch group; the Copper runs the emulator's state machine as the bus
  model does (FETCH, MOVE or WAIT_OR_SKIP, WAIT1, WAIT2, each in a free even cycle two cycles
  after the last, the comparator on the beam two colour clocks ahead of the current line), so a
  WAIT whose words end a line is first compared on the next one: WAIT 255,$DE then WAIT $21,0
  passes on line 289, as Alien Breed II measured (G36, 0.7.2).

`ard_overlay(lo, hi, bytes, on)` lets the renderer read a window of chip RAM from a copy the host
computes (smooth scrolling between the game's ticks without touching the game's RAM);
`ard_line_cb` / `ard_spr_cb` / `ard_spri_cb` hand a rebuild the lines and the sprites (a wider
view, sprites at full DMA).

## Disk images at run time (`arek_host_disk.h`)

A rebuild that ships no game data reads the game's files from disk images the visitor gives
the page (or a file on the command line natively). The game's read routine is replaced with
`arek recomp --extern ADDR=name` by a few lines of the project that call `ahd_read(disk,
sector, count, dest)` - which registers carry the disk, the first sector, the count and the
destination, the disk identities and any sector remapping are the project's, not the kit's:

```c
AHD_EXTERN(game_read, m->d[4] == 0x123111u ? 0 : 1, (int16_t)m->d[1], (uint16_t)m->d[2], m->a[0])
/* = void game_read(M68 *m): the sectors to A0, D0 = 0 (or -1 when the image is missing), rts */
```

`ahd_set(n, bytes, len)` keeps image n (`AHD_DISKS`, 4), `ahd_set_file` natively; `AHD_READS`,
`AHD_FAIL`, `AHD_LAST_*` for the page's diagnostics; `AHD_LOG=1` prints every read (native).

## The engine of a web page (`arek_host_engine.c`)

The translated game on the host, driven frame by frame by the page, which reads every frame's
picture (`engine_rgb`, vAmiga's 716 x 285 screenshot layout; `engine_pix` the 12-bit colours)
and sound (`engine_aud_ring`, 48 kHz stereo, `engine_fr_aud0` / `engine_fr_naud` per frame)
and gives the inputs (`engine_keys` bits R L U D F on port 1, `engine_keys2` port 0,
`engine_key` a raw key code) and the disk images (`engine_set_disk`). Built with Emscripten
ASYNCIFY the game is a coroutine in the page's thread: when it has finished more frames than
`engine_allow(n)` permits, its next wait loop (the translation's `WAIT_LOOP`: the beam, a
counter an interrupt bumps) sleeps in `js_wait()` until the page allows more and calls
`Module.__engineResume()`; meanwhile the page draws. ASYNCIFY instruments only the callers of
`js_wait`, so the game sleeps in wait loops only (as the Superfrog and Alien Breed II rebuilds).
A run-time target the translation does not know (`-DUNKNOWN_HOOK`, an unknown overlay module)
sets `engine_error` and the game sleeps at its next wait loop instead of exiting.

```
arek host state cap/s0 state0 && arek host pack state0 state0.bin      # the state as one file (engine_init)
arek host engine web/eng --game game.c --l3 f_c13e1c --entry f_c01c72 --src externs.c [--ovl overlays.c] [--dynamic] --run
arek host engine out --game game.c --l3 ... --entry ... --native --run  # the same file with cc: the check line
out/arek_host_engine state0.bin 300 --disk 0 disk1.adf                  # frames 300 frame 599 hash ...
node lib/arek_host_engine_check.js web/eng state0.bin 300 disk1.adf     # must print the same line from wasm
```

`--src` is the project's file with its extern routines and hooks (included after the host),
`--ovl` its overlay modules, `--dynamic` goes on at the popped return address when the entry
routine returns (a level loop returning to a dispatcher). The native build runs N frames with
the check's keys and prints the frames done, the last frame's number and the FNV-1a hash of its
picture and chip RAM (`--shot`, `--dump` keep them); the Node script does the same through the
page's API, so the wasm build is held against the native one on every change. The synthetic
test builds both (`tests/test_host_engine.py`, emcc and node when installed).

## Measured

- Alien Breed II (2026-10-26, the project the host comes from): the loop step with this host 745/745
  ticks = the whole RAM as the original (random joystick, seed 1); per-instruction timing exact on
  the first 9 365 passes of 10 148 breakpoints, the pc sequence equal for 50 579 passes; audio DMA
  20 199 / 20 199 slots; 94 of 181 frames pixel-identical before the sprite rule, the rest the one
  sprite the rule explains.
- Kit self-tests on this host's models: `arek selftest bus` 0 disagreements, `arek selftest audio`
  0 disagreements and every sample exact, `arek selftest display --c` 0 pixels.
- Not modelled: NTSC, the blitter's line mode on the bus, Paula's audio interrupts (a host that
  needs AUDx INTREQ bits sets them itself), the CIA timers and TOD (a game that seeds its random
  numbers from CIA-B TOD gets the value from the capture: `docs/METHOD.md` §5), disk DMA.
