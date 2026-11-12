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
| `arek_host.h` | time from the bus model (`arek_bus_glue.h`), the beam (VPOSR/VHPOSR), INTREQ and the interrupt levels 1-6 (entry cost 44 clocks / 7 accesses after the E-clock phase), CIA-A (PRA/SDR/ICR/DDRA, the LED bit, the E-clock cost of every access), Paula (`arek_bus_paula.h`) and the sound (`arek_audio.h`), the picture (`arek_display.h`), the next frame's map behind the current one, shots; a write to CIA-A SDR ($BFEC01) is stored (the keyboard handshake writes $FF and reads it back - G53, kit 0.9.5) |
| `arek_display.h` | `arek.display` in C, line by line as the beam passes, with CPU writes in mid-frame; the DDFSTRT delay and the sprite slot rule (below); `arek selftest display --c`: 0 of 204 060 pixels differ |
| `arek_host_disk.h` | the game's disk reads from images given at run time (`AHD_EXTERN`, below) |
| `arek_host_engine.c` | the engine of a web page: Emscripten ASYNCIFY, frames on demand, picture / sound / inputs / disks through its API; natively the check line (below) |
| `arek_host_engine_check.js` | the wasm engine in Node, printing the check line of the native build |
| `arek_host_engine_node.js` | the harness (1.0.20): the wasm engine in Node for a project's measurements - loader, synthetic start state, keys and events at exact frames, hang guard |
| `arek_audio.h` | the four channels' bytes as 48 kHz stereo int16 (left 0 + 3, right 1 + 2); 0.8.6: `ARA_GAIN[ch][side]`, `ara_gain(ch, l, r)` at once or `ara_gain_to(ch, l, r)` ramped across the next `ara_until()` - an effect fading a channel or moving it across the stereo picture (Alien Breed II G52); the default matrix keeps the old integer mix bit for bit |
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
`host_spend(m, cck, access_every)` (1.0.8): an `--extern` routine that replaces a loader or a decruncher in C spends
the ELAPSED time the original took from entry to return (measured: clocks per decrunched byte, frames per track),
including the interrupt handlers taken meanwhile - the spend ends when the host's clock reaches entry + cck; time moves
in steps, the frame's events run and interrupts are taken inside, as in a WAIT_LOOP (`host_elapsed()` = the clock in CCK); `access_every` > 0 adds one CPU access to the slot map
every so many CCK (the original's loop took slots; the blitter beside it slows down). The routine's own memory effect
goes before or after the call. `host_trace --reglog-regs 040-076,09c` chooses the registers the host's reglog records
(the default: DMACON, INTENA, INTREQ, ADKCON, AUDx), the syntax of `trace run --reglog-regs`.

`HOST_VECTOR_HANDLER(name, vec)` makes a handler that jumps through the game's own vector in RAM
(`host_vec_l1/l2/l3/l4/l5/l6` for $64-$78 are ready: `-DHOST_L2=host_vec_l2` for the keyboard's CIA-A, 1.0.12) - for a game that changes its
handlers at run time, an intro and a level (1.0.6, Turrican II). With `recomp --resume`, `host_jmp_l1..l6` (`HOST_VECTOR_JUMP(name, vec)`, 1.0.48) enter the
handler by a JUMP, as the 68000 does: no C frame waits for its `rte`. Use them when a handler leaves on another stack by
other means than its own `rte` - a scheduler called by `jsr` that ends in `rts` on the next task's stack, a sound handler
that moves a7 from channel to channel (S.W.I.V.). Called from C (`host_vec_lN`), such an `rts` onto a higher stack reads as a plain
return, the handler's C frame returns and the interrupted routine goes on with a foreign stack (`unknown routine`,
accesses outside RAM some frames later). Not for a host whose own C routine takes interrupts and must go on afterwards
(`host_spend` in an extern): its frame is dropped as well and the interrupted instruction runs again - the routine has to
remember where it was. The trace's tick records skip such a handler by its level (`H_IN_IRQ`). A game whose tick IS the handler's entry (one record per VBL) passes it as
`-DHOST_L3_PC=0x...` - as `TICK_PC` alone it is inside the interrupt and only the first record is written. Overlays: inside a module (`--lib --prefix NAME:LO:HI --overlay-module`), a direct bsr / jsr to its own range is an
ordinary call - walked and translated (1.0.11); only targets outside it in an overlay area go through `overlay_call`.
The module fingerprint (`overlay_fp`, 256 bytes of RAM) is a raw read of the host, not a CPU access - until
1.0.6 it was bus-counted and every `overlay_call` cost emulated time (Turrican II: 7 modules = 9 lines of the frame,
seen as a loop 2-8 lines slower than the original). Overlays (1.0.15): `overlay_call` first takes a loaded module whose EXTENT (its image, cut by --prefix) covers the
address and whose fingerprint matches - of several, the nearest base - so a level module whose code runs past its
area is reached through pointers too (Turrican II); otherwise, as before, one area holds ONE module at a time -
`overlay_call` takes the first registered module whose base lies in the area and whose fingerprint matches, for any
address of the area; two modules loaded at once (an intro and a music block) need two areas (`--overlay A:n B:m`).
`HOST_ACK_HANDLER(name, bits)` makes a handler that only acknowledges INTREQ bits, for a level the
game leaves to Kickstart (`-DHOST_L4=host_ack_audio` is predefined for the audio requests the Paula
model raises); without it the request would be taken again and again.

The CIAs: CIA-A PRA / DDRA / SDR / ICR as before, and both CIAs' timers A and B (the latch, one-shot
or continuous, START, FORCE LOAD, the ICR status and mask; an E tick = 5 CCK; CIA-A raises PORTS,
CIA-B EXTER), which a loader waiting on CIA-B timer A needs (G38). 1.0.40: a running timer whose ICR mask bit
is set raises its interrupt when it runs out (`H_CIA_DUE`, checked with the other events at every
instruction) - before, the timers were only counted when the game touched a CIA register, so a timer waited
for by its interrupt alone (a music routine on CIA-B) never fired; a timer the game polls is still counted
lazily. The delay between the underflow and the interrupt is not measured against the emulator. Other CIA registers answer $FF
and count in `H_IO_UNKNOWN` unless the host defines `HOST_CIA_READ(a, &v)` / `HOST_CIA_WRITE(a, v)`
(return 1 when handled). POTGO's output bits read back in POTGOR (G40), and LACE is taken from the
renderer's registers, so the Copper's BPLCON0 alternates the fields too (G39). `TICK_PC` is the pc of the game's tick (the main loop's
head, where the records are taken) and `HOST_ENTRY` the translated routine the run starts in. A
game that uses no slow RAM leaves `--slow` out; the driver follows `SLOWSZ`.

The state the driver starts from comes from a capture of the original:

```
arek bpstate --address 0xc01c72 --set-at 293 --end 300 --ram-len 0x80000 --region 0xc00000:0x80000 ... --out cap/s0
arek host state cap/s0 state0            # chip.bin, slow.bin, creg.bin, state.txt (SR, beam time, INTREQ, CIA-A port, frame; 1.0.49: the timers, masks and ICRs of both CIAs when the capture has them)
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
   a run that starts after that write (a state taken mid-frame) does not raise that frame's COPER again
   (1.0.5); BLIT when a blit the CPU started (BLTSIZE) ends as the bus model sees it (1.0.5; a blit the Copper
   starts does not set it yet);
   a blit crossing the frame end keeps running in the next frame (the CPU's slot wait stops one line past the end, 1.0.7);
   the Copper's other INTREQ bits (any `MOVE INTREQ,SET|bits` in its list, e.g. RBF = level 5 as an intro's
   timing interrupt) are raised at their times too (1.0.6; up to 8 writes a frame);
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

The replacement stands for the whole routine, however the game reaches it: a `bsr`/`jsr` calls it, and
a `bra`/`bcc` or a fall-through from the routine above it (code with no `rts` between) becomes the same
call followed by the caller's return - `{ name(m); return; }` - so the replacement must leave the
registers and the stack as the routine's own `rts` would. `--extern` may be repeated.

`ahd_set(n, bytes, len)` keeps image n (`AHD_DISKS`, 4), `ahd_set_file` natively; `AHD_READS`,
`AHD_FAIL`, `AHD_LAST_*` for the page's diagnostics; `AHD_LOG=1` prints every read (native).

## A data disk the game writes (`arek_host_datadisk.h`, `wb-datadisk.js`)

Team17's games save the high-score table by hand: OPTIONS -> HISCORE SAVE / LOAD -> "please insert your
custom datadisk into internal drive and press fire" -> one sector of a disk in DF0 through the game's own
disk routine (unit, sector, count, mode and buffer in registers). A rebuild has no drive, so the original
answers DISK ERROR. The header is the disk: `AHDD_SECTORS` sectors (default 1) in the host, behind the
game's routine replaced with `--extern`; the registers and the result are the project's:

```c
#define AHDD_SECTORS 1
#include "arek_host_datadisk.h"
AHDD_EXTERN(game_dsk_io, m->d[0] & 3, (uint16_t)m->d[1], (uint16_t)m->d[2], m->d[3] & 1, m->a[0])
/* = void game_dsk_io(M68 *m): D0 = 0 when the sectors moved, AHDD_FAIL (30, TDERR_SeekError) otherwise, rts */
```

A game whose one routine also reads its own disks (Superfrog) writes the extern itself: when the data disk
is in the drive (`ahdd_in()`) and the unit is 0, `ahdd_io(sector, count, write, addr)`, otherwise `ahd_read()`
of `arek_host_disk.h`. The disk starts in the drive (`AHDD_INSERTED`, default 1 - right for a dedicated
routine as Alien Breed II's); such a game reads sector 0 of every unit at start, so it compiles with
`-DAHDD_INSERTED=0` (or calls `ahdd_insert(0)` before the game runs) and inserts the disk with
`ahdd_insert(1)` around its "insert datadisk" prompt. An empty drive reads as zeros and still takes a write -
what a blank disk does; the game decides what a sector without its marker means (its own DISK ERROR on LOAD,
a plain SAVE). The disk answers at once where the original took seconds: a menu then reads the fire button
still held from the prompt as the next choice and shows the prompt again - the page or the engine holds the
button as released after the disk call until the real release (Superfrog).

The page keeps the sectors in localStorage with `wb-datadisk.js`: the header exports `ahdd_buf`,
`ahdd_size`, `ahdd_set`, `ahdd_gen` (EMSCRIPTEN_KEEPALIVE on their own, no EXPORTED_FUNCTIONS entry needed),
`WBDATADISK.host(M)` maps them; an engine in a worker gives `open()` its own `host` adapter over the shared
memory instead (the sectors, the generation and the flag - Superfrog). `open({ key, host, label, log })` gives
`load()` (after the engine's init, before the game runs), `poll()` (once per frame: the game wrote, the write
is saved) and `clear()`, plus a two-click clear button. Natively `ahdd_sync(path)` once per frame keeps a file equal to the disk. What the
game does with the table beyond SAVE / LOAD - an automatic save after a name is entered, the table's address
and format - is the project's (Alien Breed II has it in its engine).

## The engine of a web page (`arek_host_engine.c`)

The translated game on the host, driven frame by frame by the page, which reads every frame's
picture (`engine_rgb`, vAmiga's 716 x 285 screenshot layout; `engine_pix` the 12-bit colours;
`engine_dac(1)` (1.0.66) gives `engine_rgb` the colours of the Amiga's converter - a component
times 17, as wb-scene's `x17` - from the next frame on; the default is vAmiga's monitor, which a
screenshot of the emulator holds and which is darker by 25 of 255 on average)
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
- 1.0.40, measured with `arek selftest display` (lines $74-$79 of its disk): without bitplane DMA (DMACON BPLEN
  or DMAEN off) a line fetches nothing, the bitplane pointers stay where they are and the line shows the
  background; sprites show from the line's first bitplane word on, so a line without a fetch (also one with no
  planes) shows none. In a host DMACON = 0 is the machine's state (`ARD_DMACON_KNOWN`), not "unknown": nothing
  is fetched, sprites included. The Copper still runs with COPEN off (not measured yet).
- 1.0.43: `host_init` starts from a clean host (`host_reset`, `ard_reset`): what the state does not carry - the frame
  count, the CIA timers, a pending blit, the field length, the renderer's registers and sprites - is as at the first
  start, so the page's restart repeats the first run (the native engine's `--twice` prints both hashes). Raw keys
  (`engine_key`) wait in a ring of 32 and reach the game one per frame.
- 1.0.40: VPOSR / VHPOSR read past the frame's end inside an instruction (the frame rolls at the instruction's
  boundary) give line 0 on of the next field, not line 313.
- 1.0.64, with the timing model: Paula's events run at instruction boundaries, and before every CPU access whose slot
  lies behind a pending audio fetch (`AREK_GLUE_ACCESS_CB` of `arek_bus_glue.h`): a word is read before a store that
  comes in a later slot of the same instruction (a wave table rewritten while it plays). Not behind the frame's end.
- 1.0.63, with the timing model: a display or DMA register written past the frame's end inside an instruction is
  the next frame's write - the bus model starts that frame from the old value and takes the write at its clock
  (`docs/BUS.md`), the picture gets it after the new frame's Copper has started and the field's length is decided
  (a Copper list flipped in the frame's first clocks shows from the frame after, as in the original).
- Not modelled: NTSC, the blitter's line mode on the bus, the CIA TOD counters (a game that seeds its
  random numbers from CIA-B TOD gets the value from the capture: `docs/METHOD.md` §5; a build
  from the disks answers it through `HOST_CIA_READ`), disk DMA. Paula's audio interrupts (kit 0.7.1) and
  the CIA timers (kit 0.7.2) are modelled, see above.

### The Node harness (1.0.20, `arek_host_engine_node.js`)

A project's measurements (coverage runs, scene checks, pop-in counts) drive the wasm engine from Node; Turrican II's tools
repeated the loader, the synthetic state and the key schedule ten times. The harness in `arek host copy`'s folder does it once:

```js
const H = require('./lib/arek_host_engine_node.js');
const eng = await H.open('build/web/out', { state: H.synthState({ sr: 0x2000, entry: 0x1246, time: 39601, frame: 2645 }), disks: ['d1.adf', 'd2.adf'] });
eng.schedule('300:16,310:0,1000:1').at(1, () => eng.poke8(0xc7fff0, 1));   // keys from a frame on; an event after frame 1
await eng.run(2500, (f) => { if (f % 500 === 0) console.log(f, eng.hash()); });
eng.peek16(0x17e); eng.pix(); eng.dump(0, 0x80000);
```

`open` finds `engine_mt.js` or `engine.js`; `synthState()` writes the bytes of `arek host pack` (zero RAM unless `chip` / `slow` /
`creg` are given); an event at frame f runs after frame f is done, before frame f + 1 is allowed - the page's rule, so a
measurement and a replay see the same game; `run` throws `{ code: 'hung' | 'error' }` instead of waiting for ever. The
synthetic test drives both wasm builds with it and compares the native check line (`tests/test_host_engine.py`).

### A scene record from the threaded engine (1.0.16)

`-DENGINE_FRAME_RECORD=my_record` (with `--define` of `arek host engine`): the project's `void my_record(int n)` in its
`--src` file runs once per finished frame, after the picture and the samples and BEFORE the frame is published - the
page sees `engine_done() > n` only when record n is complete. The project keeps its own ring of `engine_nfr()` (32)
records in the wasm memory (shared with the page in the threaded build), exports its address with a KEEPALIVE
function, and the page reads record `n % engine_nfr()` through `HEAPU8` for every frame it hands to `scene.frame()`.
What a record holds is the wb-scene contract (docs/WB-RECIPE.md): the clean window, its palette rows, the camera and
limits, the map cells and atlas, the objects with ids and pass times, the sprites, the HUD.

## The disk as hardware: `-DHOST_FLOPPY=1` (1.0.53)

A game that reads the disk with its own loader (DSKLEN, DSKSYNC, its own MFM decoder) can keep that loader translated:
`arek_host_floppy.h` models drive DF0 and Paula's disk controller after vAmiga. No `--extern` for the read routine, no
`host_spend`, no measured read times - the time a read takes follows from where the disk stands.

- the image: `AHD_IMG[0]` (`engine_set_disk(0, ...)` in the page, `HOST_ADF0=disk.adf` for `host_trace` and the native engine);
- the registers: DSKPT, DSKLEN, DSKSYNC, ADKCON (WORDSYNC), DMACON (DSKEN), DSKBYTR, INTREQ DSKBLK / DSKSYN; CIA-B PRB
  ($BFD100: /MTR /SEL0 /SIDE DIR /STEP) and CIA-A PRA bits 2-5 ($BFE001: /CHNG /WPRO /TK0 /RDY) - do not serve these two
  addresses in a project's `HOST_CIA_READ` / `HOST_CIA_WRITE` any more;
- the start: `arek bpstate` records the drive (`cpu.json` "drive": cylinder, head, bit offset, motor) and `arek host state`
  writes it as `@drive ...`; a start without a state calls `host_floppy_start(cylinder, byte, 0)`. The byte clock itself needs
  no state (1.0.55): a byte is served when the absolute colour clock (frame x 71 051 + line x 227 + slot) is 1 modulo 56, in
  every run of the emulator - so state.txt's frame number must be the frame of the run you compare with (a capture and a
  trace are two runs and may reach the same instruction in different frames);
- limits: reading only, DF0 only, AmigaDOS tracks made from an ADF (no raw MFM images), bytes read as 0 for 12 ms after a step.

Use it with `-DHOST_IPL_MODEL=1` (the E clock of the CIA accesses and the interrupt timing belong to the same measurement).

## Input lines: by the frame number or as the emulator takes them

`host_trace STATE OUT.vtr N INPUTS.txt` applies line k of the inputs file in frame k of the run (`--inputs-first F`:
line 0 in the frame numbered F). The emulator (`arek trace run --inputs`) takes the next line at the first breakpoint
hit of a frame on lines 0-99 (`--inputs-v` there). The two agree while the breakpoint is hit in that window in every
frame. A game whose VBL handler can start lower - behind a long blit, with interrupts masked - makes the original skip
a line in such a frame and stay one behind: give the host the same rule with `host_trace ... --inputs-v 0:99` (1.0.61;
the tick's pc is the breakpoint). With `--inputs-first F` the count starts as if every frame from F to the state's had
taken one.

Raw keys (1.0.65): a line may hold key events - `K<hh>` a key pressed, `k<hh>` released, hh = its raw code in two
lower-case hex digits (`K60` left shift down, `k4c` cursor up released; `K4eK60` two in one line, in that order) - and
`S` for space held, in the emulator's lines (a build with `vamiga-keys-899da5d.patch`) and in `host_trace`'s alike.
They are events of the frame whose line they stand in, not held states. In the host they go through its keyboard
(`host_key(code, down, t)` in `arek_host.h`), written after vAmiga's: an idle keyboard sends at once, the code rotated
and inverted reaches CIA-A's SDR 1610 colour clocks later (eight bits of 210) plus the CIA's cycles and sets ICR's SP
bit (PORTS with the mask bit); the next event waits for the game's handshake - CRA bit 6 set and cleared - and without
one for 143 ms the keyboard resyncs as the real one does ($FD, $FE after the handshake). A press of a key that is down
and a release of one that is up are dropped; ten events wait at most. Measured on SWIV, whose VBL routine polls ICR
once a frame and holds the handshake for a frame: 5 619 records of 5 619 equal with shift, cursor keys, two events in
a line and a press and release in neighbouring frames. Not measured: the E cycle in which the SP bit appears (taken
from the emulator's source) and PORTS as an interrupt. A captured state starts with an idle keyboard and no key down.
The engine's `engine_key` keeps its simpler path by default (one event a frame, SDR at once); `engine_keyboard(1)`
(1.0.66; natively `--keyboard`, in Node `open(dir, { keyboard: true })`) sends its events through this keyboard instead -
all that wait at the frame's start, in their order - so a recording of the page replays in the original with `K` / `k`
tokens in the same frames. SWIV's engine: left shift and cursor up given in one frame are in the loader's key matrix a
frame later than by the direct path and two frames after that (the game shakes hands once a frame), both releases
likewise; nothing lost.

## A capture in the middle of a game: what state.txt carries

`arek host state CAPTURE OUT` writes, after the registers and the frame number: the CIAs' timers (1.0.49; a running
timer goes on from the emulator's counter), `@drive` for a host with the floppy model (1.0.53), and `@audio` (1.0.60) -
one line per Paula channel: on, state, AUDxIP, the pending request and the next period event in absolute colour
clocks, the pointers, the length / period / volume latches and counters, the data word and the output word, and
(1.0.64) a second request - one raised in the capture's line while the first still waits for its slot; a request
that is only in Paula yet (`audDR`, raised in the capture's line) is written as the pending request. The audio
lines need a capture made with an emulator build that has `vamiga-audstate-899da5d.patch` (docs/HEADLESS.md); without
them a channel that is in the middle of a sample at the capture is silent in the host and takes no DMA slots until the
game starts it again - the bus is then freer than the original's and instruction times drift within the first frame.

## Instruction times equal to the original's: `-DHOST_IPL_MODEL=1` (1.0.50 - 1.0.60)

Without the switch a host is exact in frames and close in lines: an interrupt is taken at the first instruction end
after its event. A game whose behaviour depends on WHERE in a line or in a loop an interrupt lands (a loader's poll
loop, a raster split made by the CPU, a counter read in a handler) needs more, and the switch turns on what was
measured against vAmiga instruction by instruction (`arek trace run --break PC...`, host_trace `--pclog`):

- the interrupt level is sampled in one particular bus cycle of every instruction and reaches the processor three
  colour clocks after INTREQ / INTENA change; the entry takes its 44 clocks in Moira's order of idle clocks and
  accesses; VERTB is requested at colour clock 0 of the frame, a CPU write to INTREQ / INTENA lands a clock after its slot;
- a CIA access waits for the E clock (10 CPU clocks, its position at a frame's start = 2 x frame mod 10) and its
  write lands after the wait; a timer's interrupt is requested in the E cycle its counter reaches 0; a start that also
  loads the timer (the high byte in one-shot mode, FORCE LOAD) counts one E cycle later;
- VHPOSR / VPOSR: the position of the access's slot plus five colour clocks, the line number changing at clock 2;
- Paula takes a CPU write to DMACON two colour clocks after its slot and one to INTREQ after one (a channel switched
  on in the last two slots of a line starts in the next line);
- a CPU write to DMACON, DIWSTRT / DIWSTOP, DDFSTRT / DDFSTOP, BPLCON0 or COPJMP re-plans the rest of the frame's
  slots; an idle Copper takes a new COP1LC;
- every instruction's bus cycles in the processor's own order (the bus patterns of `arek recomp --bus-table`,
  docs/BUS.md) - the translation must be regenerated with the kit that builds the host.

`HOST_BUS_PAT=0` in the environment (host_trace, the native engine) switches the patterns off, to see what they
change. The state a comparison starts from must be the original's at that frame, with its frame number
(`arek trace run --capture-at`, docs/HEADLESS.md), and the inputs of the original's run (`M` / `m` for port 0's
button). Measured on SWIV's boot with `-DHOST_FLOPPY=1`, from the capture to the title (1 824 frames, 45 disk reads,
the music's level 6 interrupts): 22 780 instruction times of 22 780 at 14 addresses, 1 687 863 of 1 687 863 at 28
addresses over the first 600 frames. Not measured: the interrupts of the blitter, the audio channels and the Copper.
