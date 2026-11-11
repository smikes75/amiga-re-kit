# Changelog

One line per release, newest first: the subject of the release's commit. The reasons and the measurements are in
the commit messages (`git show vX.Y.Z`) and in `docs/`. Before 1.0.41 this list did not exist; it is made from the history.

## 1.0.50 (2026-11-11)

- captures (SWIV KIT-GAPS 5): a CIA nobody touches sleeps in vAmiga and `r ciab` prints its counters as they were when
  it fell asleep. `arek bpstate` now also asks `? ciaa` / `? ciab` (sleeping, since which master cycle) and
  `bpstate.cia_regs(chip, clock)` / `arek host state` take the slept E clocks off a running timer. SWIV: printed $D7F,
  at the stop $646 - level-6 interrupts 9270 colour clocks late. Old captures have no sleep data: capture again
- host, OPT-IN `-DHOST_IPL_MODEL=1` (SWIV KIT-GAPS 7): which instruction an interrupt is taken after - the 68000
  samples its IPL pins in the last bus cycle of an instruction and Paula's level reaches them 2 colour clocks after
  the request (VERTB then at colour clock 2 of the frame instead of the fitted 10). Measured on SWIV's boot against
  vAmiga: the instruction after an INTENA write runs before the pending interrupt (was: taken at once), the next
  frame's VBL entry is on the original's slot. Not measured: other sources, instructions that sample earlier. Off by
  default: nothing changes for a host built without the define

## 1.0.49 (2026-11-11)

- a captured state keeps its CIAs (SWIV): `arek host state` writes the timers (latch, counter, control register), the
  interrupt masks and the ICRs of both CIAs as a last line of state.txt when the capture has them (`r ciaa` / `r ciab`
  of the emulator; `bpstate.cia_regs` names what `parse_chips` stores as A, B, A#2 ...), `host_trace` and the engine
  load it (`host_cia_state`). Before, a state from the middle of a game started with the CIAs at reset: no level-6
  interrupts until the game set the timer up again. The emulator's start delay of a few E ticks is not modelled
- bus model (SWIV KIT-GAPS 6): a register the Copper wrote keeps its value until the CPU writes it - also in frames
  whose list no longer writes it. The model kept it for one frame and fell back to the CPU's value: after a list with
  BPLCON0 was replaced by an empty one the bitplane slots left the map (SWIV: 5120 a frame in the original, 0 in the
  host, the CPU ~4 % faster)
- docs: with `host_jmp_lN` a tick at the handler's entry needs `-DHOST_L3_PC` (TICK_PC inside an interrupt is skipped)

## 1.0.48 (2026-11-11)

- wasm (SWIV KIT-GAPS 3): a `switch` whose values span more than a WebAssembly br_table holds (65 520 targets) comes
  out of emcc 6.0.12 wrong - a value that has a case reaches the default, or the module does not load, or the build
  fails; natively it is right. The dispatchers of a translation (`call_addr`, an overlay module's, the `--resume` way
  into a routine) are emitted by 4 KB blocks when their values span $4000 or more (`Gen.emit_switch`). SWIV, 11 684
  cases: wasm stopped at "unknown routine" for an address that has a case; by blocks 3000 frames, native = wasm

- host, `--resume` (SWIV KIT-GAPS 4): `HOST_VECTOR_JUMP` / `host_jmp_l1..l6` enter the game's handler by a jump, as the
  68000 does - no C frame waits for its rte. For handlers that leave on another stack by other means than their own
  rte (a scheduler ending in rts, a7 moved from channel to channel): called from C (`host_vec_lN`) such an rts reads as
  a plain return and the interrupted routine goes on with a foreign stack. `H_IN_IRQ` (the trace's tick records)
  follows such handlers by their level

## 1.0.47 (2026-11-11)

- Copper (SWIV KIT-GAP 1): a MOVE to a register below $40 stops the Copper until the next frame, one to $40-$7E does
  unless the CPU set CDANG (COPCON not written in the run: let through) - bus model, `arek.display` and
  `arek_display.h`; a list of zeros took every other free slot of the frame (18 407 slots against the original's 3)

- CPU bus slots (SWIV KIT-GAP 2; Moira's order): move to SR / CCR reads two words AFTER its 4 internal clocks (and
  one read more than was counted), andi/ori/eori to SR / CCR after 8, lea d8(An,Xn) its last word after 2 - the bus
  table carries the count in bits 5-6, the model makes those reads at the instruction's end. Clock counts unchanged;
  beside bitplane DMA the CPU's slots now equal the original's (SWIV: 35 slots of three lines elsewhere, 0 after).
  Translations must be regenerated (`arek recomp --bus-table`) to get the new table

## 1.0.46 (2026-11-11)

- inputs per frame on both sides in the same frames (Turrican II): `host_trace --inputs-first FRAME`, `arek trace
  inputs-frame ORIG.vtr` (`trace.inputs_first_frame`) - a state captured below the input window ran every line a
  frame early; host_trace says so when it sees that case

## 1.0.45 (2026-11-10)

- web: `wb-bytekiller.js` - the Bytekiller TAIL decruncher for a page (both code tables, a port of `unpack_tail` /
  `unpack_tail_any`; asked by Xenon 2 for the BS1 disk)
- `bytekiller.pack_tail_c` looks for matches through an index of byte pairs (the tests of 1.0.44 took four minutes)

## 1.0.44 (2026-11-10)

- Bytekiller TAIL, the second code table (Xenon 2 KIT-GAP 17: 1.0.43's table did not decode that block): counted
  literal runs followed by one match - `unpack_tail(..., code='c')`, `unpack_tail_any` (the one table that uses the
  stream up exactly), `pack_tail_c` for round trips, `arek bytekiller --format tail --code auto|b|c`, MCP
  `bytekiller_tail` (finds the table), `bytekiller_tail_b`, `bytekiller_tail_c`
- wb-scene 2.12 (Turrican II KIT-GAP 33): camMean's window carried past the newest frame (2.9) stops at that frame's
  value - a camera that stopped or turned ran on and came back by 0.2-0.8 px
- parity sound (Alien Breed II G61): the original's Paula frames after the end of the rebuild's register log are counted
  (`short`) and are a PROBLEM of the suite, as a short trace is
- parity / trace compare (Turrican II KIT-GAPS 31, 32): a range the original hashed is checked against the bytes the
  rebuild captured wherever its range starts (a full capture against hashed ranges compared nothing before 1.0.39 and
  read "missing hash" since); records that differ in a few bytes are diffed by 4 KB blocks (minutes per trace, not hours)

## 1.0.43 (2026-11-10)

- Bytekiller format TAIL (Xenon 2 KIT-GAP 17): the unpacked length and the first bit word at the END of the block, as a
  crunched executable has them - `bytekiller.unpack_tail`, `arek bytekiller --format tail --offset --end`, MCP
  `bytekiller_tail`; a run or a match that leaves the output is an error (it wrote over the end of the output)
- recomp: an unknown jump ends the routine also when the hook returns - a jump-table offset outside the table no longer
  runs slot off / stride, a jmp no longer goes on behind itself, an unresolved jsr takes its return address off again
- host: a start is a clean start (`host_reset`, `ard_reset`): a restart in the same process is the first run again; raw
  keys wait in a ring of 32, one per frame (two events inside a frame lost the first); Paula runs up to an INTREQ write
  before the write clears the bit; the native engine takes `--key HEX:DOWN` and `--twice`
- bus: a blit crossing the frame end is still busy in the frame's first colour clock (slot -1 as an unsigned number)
- headless: a script time with a fraction is refused (it was cut to the whole second); inputs without a breakpoint are
  refused (no line of the file was applied)
- packers: RNC `max_output` (16 MB), the Turrican II lengths capped and its stream errors as ValueError

## 1.0.42 (2026-11-10)

- the first CI run on Linux: the Paula check program links libm (`arek selftest audio` did not build there), two trace
  tests no longer take /bin/true for an emulator, setuptools in the CI environment; CHANGELOG.md in the sdist.
  1.0.41 was tagged but never uploaded: 1.0.42 is that release.

## 1.0.41 (2026-11-10)

- wb-obraz 1.9: a lost WebGL context is asked back and everything rebuilt (`onLost` / `onRestore`, `.lost`); the 2D path
  takes pixels in shared memory; `Screen.info().box` and the check of it in `arek web test`
- wb-scene 2.11: attaches again after a restored context; a sprite paired with an older frame keeps that frame's camera
- wb-takt 1.5: `keyboard()` leaves keys with Cmd / Ctrl / Alt to the browser and releases every key on Meta up, window
  blur and a hidden page; `lifecycle({ onHide, onShow })`
- wb-zvuk-out 1.1: `push()` copies a view that is not the whole of a plain buffer (the engine's memory, a part of a buffer)
- wb.css: no border on the game canvas (it resized the picture by 2 px); the frame is a box-shadow
- `arek web copy` writes `wb-kit.json`, keeps a kit file edited since it was copied, `--check` says what a folder holds
- tests: markers `browser` and `timing` (`pytest -m "not browser"`), `AREK_REQUIRE_TOOLS=1` fails instead of skipping
  without a C compiler or node; a CI workflow; git tags for 0.9.6-1.0.38; this file

## 1.0.40 (2026-11-10)

- silent errors of the translation and the host found by the audit of 2026-11-10

## 1.0.39 (2026-11-10)

- equal means covered - the comparisons no longer pass on what they did not compare

## 1.0.38 (2026-11-10)

- a restart starts the sound count again (Xenon 2 KIT-GAP 16)

## 1.0.37 (2026-11-09)

- wb-scene 2.10, objects[].scale and anchor (Xenon 2 KIT-GAP 15)

## 1.0.36 (2026-11-09)

- headless - the input line window and a list of shot frames (vamiga-frames-899da5d.patch)

## 1.0.35 (2026-11-09)

- wb-scene 2.9 - camMean past the newest frame, a new history when time goes back

## 1.0.34 (2026-11-09)

- wb-scene 2.8 - objects[].alpha

## 1.0.33 (2026-11-08)

- wb-scene 2.7 - an object on the screen stands still

## 1.0.32 (2026-11-08)

- wb-obraz 1.8 - the Original CRT in Enhanced for a game whose Enhanced only smooths the motion

## 1.0.31 (2026-11-08)

- arek web smooth - a camera jump ends a moving stretch

## 1.0.30 (2026-11-08)

- wb-scene 2.6 - camMean never averages across a camera jump; camMean.step passed on

## 1.0.29 (2026-11-08)

- arek web smooth judges what the page adds to the game's own key delay

## 1.0.28 (2026-11-08)

- wb-scene 2.5 - a back layer with a camera of its own (parallax), window.or

## 1.0.27 (2026-11-07)

- run-time jump targets on 24 bits, arek web smooth for vertical scrollers

## 1.0.26 (2026-11-07)

- TRAP, rte through the stacked PC, recomp --resume for tasks with their own stacks, arek difftest against Moira

## 1.0.25 (2026-11-07)

- arek kb - the knowledge base of the rebuilds

## 1.0.24 (2026-11-07)

- rts is a jump through the stack when the routine changed it (Xenon 2 KIT-GAP 4)

## 1.0.23 (2026-11-07)

- recomp reads the source before the destination moves the same register (Xenon 2 KIT-GAP 3)

## 1.0.22 (2026-11-07)

- the mouse in the headless emulator (Xenon 2 KIT-GAP 2)

## 1.0.21 (2026-11-07)

- arek rnc - Rob Northen Compression method 1 (Xenon 2 KIT-GAP 1)

## 1.0.20 (2026-11-07)

- REBUILD-PLAYBOOK and the Node harness of the engine

## 1.0.19 (2026-11-06)

- wb-scene 2.4 - the anchor per pair for sprites and objects (KIT-GAP 29)

## 1.0.18 (2026-11-06)

- dev server backlog 128, wb-scene 2.3 palAnchor and objects with the ground (KIT-GAPS 26-28)

## 1.0.17 (2026-11-06)

- wb-scene 2.2 window.palTop, the Workbench bar in the kit (KIT-GAPS 24, 25)

## 1.0.16 (2026-11-05)

- ENGINE_FRAME_RECORD - a scene record of each frame from the kit's engine (Turrican II M9)

## 1.0.15 (2026-11-04)

- overlay_call finds a loaded module by its extent (Turrican II KIT-GAPS 23)

## 1.0.14 (2026-11-04)

- a branch nowhere is a frontier; the pointer scan tries every start position (Turrican II KIT-GAPS 21, 22)

## 1.0.13 (2026-11-04)

- only a fall-through off the image end is a frontier (Turrican II KIT-GAPS 20, a 1.0.12 regression)

## 1.0.12 (2026-11-04)

- roots that decode, a flow leaving the image is a frontier, level 1/2/6 vector handlers and the key's PORTS (Turrican II KIT-GAPS 17, 18, 19)

## 1.0.11 (2026-11-04)

- a module's own direct calls are translated; --auto-soft drops a root whose call tree reaches data (Turrican II KIT-GAPS 15, 16)

## 1.0.10 (2026-11-04)

- ORI/ANDI/EORI #imm,CCR|SR decoded as 4 bytes and translated (Turrican II KIT-GAPS 14)

## 1.0.9 (2026-11-04)

- the runtime's area blitter ignores bit 0 of a modulo and subtracts it in descending mode (Turrican II KIT-GAPS 13)

## 1.0.8 (2026-11-04)

- host_spend() - an --extern spends the original's elapsed time with interrupts served; host_trace --reglog-regs (Turrican II KIT-GAPS 11, 12)

## 1.0.7 (2026-11-04)

- COPJMP2 in the frame map, the overlay fingerprint as a raw read, a CPU slot wait stops at the frame end (Turrican II KIT-GAPS 8, 9, 10)

## 1.0.6 (2026-11-04)

- the Copper's INTREQ writes of any bit raised at their times, HOST_VECTOR_HANDLER, --adf number or path (Turrican II KIT-GAPS 6, 7)

## 1.0.5 (2026-11-03)

- host - no second COPER after a mid-frame start, INTREQ BLIT when a CPU-started blit ends (Turrican II KIT-GAPS 2, 3)

## 1.0.4 (2026-11-03)

- Bytekiller format BK (the classic 12-byte header) - Turrican II's cracktro layer (Turrican-recomp KIT-GAPS 1)

## 1.0.3 (2026-11-02)

- wb-obraz 1.7 present({source | pixels + size, rect, smooth}) (Alien Breed SE92 G3), wb-scene 2.1.1 view.hudY

## 1.0.2 (2026-11-02)

- wb-scene 2.1 - the 0.9.15 transition and the 0.9.16 freshSprites removed (G60: counterproductive in every game)

## 1.0.1 (2026-11-02)

- whole-number sampling on both paths (Alien Breed II G59, WebKit), the HUD narrowed at its splits (Superfrog KIT-GAPS 52), player() with the sprite's image (53), the recipe revised by Alien Breed SE92's notes

## 1.0.0 (2026-11-02)

- the display layer's contract frozen - WB-RECIPE.md (one page a game writes from), wb-scene 2.0 without softClamp / smoothY

## 0.9.16 (2026-11-02)

- wb-scene 1.9 freshSprites (a tracked player answers a key one display delay sooner), arek web smooth key -> player

## 0.9.15 (2026-11-02)

- wb-scene 1.8 - the mode transition from the kit, any scale (GPU = reference at a fractional S), the one-canvas rule

## 0.9.14 (2026-11-01)

- wb-obraz 1.5.2 - the CRT layer kept above the game canvas (Superfrog), arek web test §5.5, the canon's measurements

## 0.9.13 (2026-11-01)

- wb-takt 1.4 - the grant horizon (Alien Breed II G57), takt.timeOf (Superfrog KIT-GAPS 51), replay reads done + state in one call

## 0.9.12 (2026-11-01)

- the inventory's clean-up - wb-scene 1.7 extrapolateObjects + HUD cache, wb-takt 1.3 fixed latencies, INVENTURA.md

## 0.9.10 (2026-11-01)

- wb-scene 1.6 - the objects move with the ground under subpixel (objects[].steady for a tracked player), unexplained() for window.over

## 0.9.9 (2026-11-01)

- arek host copy takes every source of the host (Alien Breed II G55), AHDD_INSERTED, the subpixel texture on its own unit (Superfrog KIT-GAPS 50)

## 0.9.8 (2026-11-01)

- wb-scene 1.5 - subpixel: the playfield moved by fractions of a device pixel (even motion on a 60 / 144 Hz display)

## 0.9.7 (2026-11-01)

- a data disk the game writes (arek_host_datadisk.h + wb-datadisk.js) - the Team17 "custom datadisk" in the browser

## 0.9.6 (2026-11-01)

- arek web replay (module H) + a fall-through or branch into an --extern routine is the host call (Alien Breed II G54)

## 0.9.5 (2026-10-31)

- a write to CIA-A SDR is stored (Alien Breed II G53 - a held key repeated)

## 0.9.4 (2026-10-31)

- wb-scene 1.4 - the sprites above the HUD rows (hud.under), the sprites' anchor in the contract

## 0.9.3 (2026-10-31)

- wb-scene 1.3 - objects[].ox/oy, the drawing's offset from the object's logical position

## 0.9.2 (2026-10-31)

- wb-scene 1.2 after Superfrog's measurements on 1.1 (its KIT-GAPS 44-46)

## 0.9.1 (2026-10-31)

- wb-scene 1.1 after Superfrog's switch (its KIT-GAPS 40-43)

## 0.9.0 (2026-10-30)

- the scene - the wider, smoother view composed on the GPU for every rebuild (wb-scene.js 1.0, module G)

## 0.8.6 (2026-10-30)

- a stereo gain matrix with ramps in arek_audio.h, strip with HTML markers (Alien Breed II G51, G52)

## 0.8.5 (2026-10-30)

- the kit's documents in the wheel, smooth 1.4 for a mode without interpolation (Superfrog KIT-GAPS 37, 38)

## 0.8.4 (2026-10-29)

- fixes from Alien Breed II's full-game runs (G47, G48, G50)

## 0.8.3 (2026-10-29)

- wb-obraz 1.5.1 (no blank canvas after a resize), smooth 1.3 (G44, G45, ready() gating), wb-takt 1.2

## 0.8.2 (2026-10-28)

- smooth 1.1 after Alien Breed II's baseline (G41-G43), wb-takt 1.1

## 0.8.1 (2026-10-28)

- the canon of a smooth picture and sound (modules C, D, E, F, docs/WB-PLYNULOST.md)

## 0.8.0 (2026-10-28)

- display contract 1.5 - the presenter (WebGL2 or 2D, one canvas, one API)

## 0.7.2 (2026-10-28)

- the host and the renderers after Alien Breed II's switch (G35-G40, G37)

## 0.7.1 (2026-10-27)

- whole-game translation, display gaps, the web engine, Paula's state machine with interrupts

## 0.7.0 (2026-10-26)

- the Alien Breed II tool pass - host of a translation, Paula DMA model, bus and display fixes, trace tools, content key

## 0.6.4 (2026-10-26)

- menu 1.2 (Superfrog KIT-GAPS 32-36), recomp -DCIA_HOOK, METHOD.md on CIA seeds

## 0.6.3 (2026-10-26)

- an exact snapped zoom survives a reload (Alien Breed K2 KIT-GAP)

## 0.6.2 (2026-10-26)

- ship wb-nastaveni.js in the wheel (0.6.1's package-data still named wb-menu.js); test pins the list

## 0.6.1 (2026-10-26)

- sound contract 1.1 and menu 1.1 (wb-nastaveni.js), web copy keeps foreign files

## 0.6.0 (2026-10-26)

- the shared Display / Sound menu and the sound contract 1.0 (MENU-ZVUK.md)

## 0.5.19 (2026-10-26)

- the PAL pixel aspect is 1.04 (14.75 / 14.1875 MHz), any par value allowed; where a 312-line frame comes from

## 0.5.18 (2026-10-26)

- movem.w and rte read and write through the hooks again (Superfrog KIT-GAPS 29)

## 0.5.17 (2026-10-26)

- the runtime's blitter moves its words raw, not as CPU bus accesses (Superfrog KIT-GAPS 28)

## 0.5.16 (2026-10-26)

- display contract 1.4 - the pixel aspect inside the backing (Superfrog KIT-GAPS 27)

## 0.5.15 (2026-10-26)

- the Amiga bus per DMA slot (arek.bus), from the Alien Breed project

## 0.5.14 (2026-10-25)

- Superfrog's KIT-GAPS 21-26 on the 0.5.13 tools

## 0.5.13 (2026-10-25)

- coverage, random input, bus cycles, a parity suite, reads outside RAM

## 0.5.12 (2026-10-24)

- payload keys - the game's own content opens the sealed files, whichever disk version it came from

## 0.5.11 (2026-10-24)

- write into the running machine (--poke), jump tables with a run-time base

## 0.5.10 (2026-10-23)

- arek web seal --gzip/--label, arek web check for presentation bundles

## 0.5.9 (2026-10-23)

- recomp --profile - calls, clocks and written pages per routine

## 0.5.8 (2026-10-23)

- version, README and THIRD-PARTY for arek web seal (the previous commit missed them)

## 0.5.7 (2026-10-23)

- wb-obraz.js reachable from ES modules, test hooks documented in the file

## 0.5.6 (2026-10-22)

- display contract - whole CSS pixels, column check, content outside the viewport

## 0.5.5 (2026-10-22)

- consecutive pictures in one run, register log for chosen registers

## 0.5.4 (2026-10-22)

- overlays recognised by fingerprint, run-time targets

## 0.5.3 (2026-10-22)

- chip bus log - who had the bus in every slot, CPU waits, blits

## 0.5.2 (2026-10-22)

- reference wb-obraz.js (display contract 1.3), demo page, arek web test

## 0.5.1 (2026-10-22)

- long parity - arek trace compare, trace pack

## 0.5.0 (2026-10-22)

- arek.display - the frame chip RAM shows, pixel exact against vAmiga

## 0.4.6 (2026-10-22)

- refusals as data - every frontier at once (routine, site, kind, operand)

## 0.4.5 (2026-10-22)

- input frame by frame in the emulator, register/audio logs, selftest

## 0.4.4 (2026-10-22)

- slow RAM in the generated C, PNG without Pillow, chip registers in bpstate

## 0.4.3 (2026-10-22)

- findings of the Superfrog Sonnet run (input spellings, hunk streams, timeouts)

## 0.4.2 (2026-10-22)

- wait-loop hook, rte ends a path, --lib --timing helpers, address spellings

## 0.4.1 (2026-10-22)

- data stored after a call (Flow.inline, --inline)

## 0.4.0 (2026-10-22)

- recomp flow options and correctness fixes, 68000 clock counts, strict decoder

## 0.3.0 (2026-10-21)

- decoder LINK/UNLK/PEA/EXG/CMPM/ABCD/SBCD + memory shifts, continuous trace, kit identity

## 0.2.1 (2026-10-20)

- version single-sourced, python -m arek, hwscan chip size, xref --callees

## 0.2.0 (2026-10-20)

- Atomik (ATN!) unpacker, AmigaDOS OFS/FFS reader, audit graph tests
