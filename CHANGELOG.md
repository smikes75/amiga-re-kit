# Changelog

One line per release, newest first: the subject of the release's commit. The reasons and the measurements are in
the commit messages (`git show vX.Y.Z`) and in `docs/`. Before 1.0.41 this list did not exist; it is made from the history.

## 1.0.76 (2026-11-13)

- wb-scene 2.15, `objects[].group` (optional, any value): the parts of one thing move as one piece - the first paired
  part of a group leads, every other part (paired or not, on the screen too) takes its shift from its own record's
  position. A part that was not there in the pass before had no pair and stood while the others slid
  - SWIV (the user: "the helicopters split at diagonal motion"): a helicopter is one object per part of its picture,
    a blade part drawn every other pass, another copy in the band below the window. fuzz_23 4100-4400, 60 Hz: 272 splits
    >= 0.5 px in 350 display frames (up to 5.3 px), 578 with objMean; with group = the node: 0, also with the band

## 1.0.75 (2026-11-13)

- wb-scene 2.14, `objMean: { tau, step }`: every object's world position as the mean over its own passes within tau ms
  of the objects' time (`rec.next` included) - `camMean` for each object, off unless set. Only an unbroken row of the
  object's passes counts: it ends where the id is missing, where it jumps farther than `jumpMax` and where its new
  optional `run` changes. Ground targets stand; screen-anchored axes, `screen` and `steady` objects are not touched
  - SWIV (the user saw the helicopters knock with passTime + next): the game moves them by whole pixels a pass,
    unevenly. 60 Hz, latency 40 ms, tau 50: world-anchored objects y / x 0.198 / 0.102 -> 0.133 / 0.059 (frames
    4100-4400) and 0.258 / 0.128 -> 0.212 / 0.087 (4200-5200), the helicopter of set 4 0.215 / 0.134 -> 0.158 / 0.083;
    the player unchanged. A line fitted through the passes was measured too (better on the short stretch, worse on the
    long one) and is not offered

## 1.0.74 (2026-11-13)

- `arek adf build OUT.adf --payload FILE --load ADDR [--entry] [--stack] [--memtop]` (`adf.build_boot`): a bootable
  880 KB disk that loads one absolute memory image and jumps to it - the boot block asks the trackdisk device for the
  image (from disk offset 1024) into a temporary chip RAM buffer, switches the motor off, takes the machine over
  (supervisor mode, SR $2700, INTENA / INTREQ / DMACON $7FFF), moves the image to its address (a mover run from
  $100, either direction, so buffer and image may overlap) and jumps with a6 = $DFF000 and a7 as asked. No memory
  or a read error: a red screen. The disk has no file system. Asked for by the Atari 8-bit port (part 3 of its
  brief: Dan Strikes Back on the A500)
  - measured in the emulator (Kickstart 1.3): images of 1 000 bytes, 300 KB at $1000 and at $35000, 400-460 KB at
    $400 - loaded byte for byte, the padding zero, SR $2700, a6 / a7 right; on 512 KB chip + 512 KB slow and on
    512 KB chip alone. 470 KB on 512 KB alone does not fit the temporary buffer (the red screen)
  - the source is `headless/adf_boot.s`; a test checks that it assembles to the bytes the kit writes

## 1.0.73 (2026-11-13)

Three rules of the emulator the models did not have, found on one pass of Turrican II's level 3-3 that took two
frames in the host and one in the original (a blit across the frame's end, the game waiting for it):

- bus model and both renderers: a Copper MOVE to COPJMP1 / COPJMP2 takes two more steps before the new list's first
  fetch - one that holds the bus without using it, one that waits for a free cycle (4 colour clocks; the models
  fetched from the new list at once)
  - the emulator's register log, a jump behind a WAIT at 12 positions with 4, 5 and 6 planes, the cycle of the MOVE
    behind it: 0 of 36 equal before (4 clocks early), 36 now
- bus model: sprite slots in the vertical blank behind a DMACON write. Lines 0-24 and the last line have none, but
  a write that changes SPREN (or DSKEN) puts the new bits into the rest of THAT line's slots: a Copper list that
  switches sprite DMA on at the top of line 0 gives every sprite whose VSTOP is that line (0 behind a list's end)
  its two control-word fetches there. The model keeps every sprite's VSTOP across frames for it
- arek_bus_glue.h: DMACONR read by a bus cycle that found no slot before the frame's end is answered for the slot
  the cycle gets in the next frame (the roll and the carry played on a copy of the model). BBUSY was taken at the
  cap, a line past the frame's end: still set although the blit ends before the cycle is served - a `btst` / `bne`
  wait went round once more
  (an engine without a thread no longer gets a wait-loop round there to hand the frame over - any other wait loop does)
- Turrican II, level 3-3 from the start with its route, 1 043 passes, host with `-DHOST_IPL_MODEL=1`: every pass in
  the original's frame (pass 670 and all behind it were a frame late); passes that begin on the original's colour
  clock 614 of the first 670 -> 1 001 of 1 043, within 10 clocks 1 040. Level 3-3 from another place, 654 passes:
  600 -> 623 on the clock, the Copper handler's entry 660 -> 686 of 719 frames

## 1.0.72 (2026-11-13)

- `arek recomp --bus-table` for an overlay module or a library (`--lib`): the module carries its own bus table
  (rows and patterns under its name) and registers it (`bus_rows_register`); the main translation's `bus_tab_row`
  gives a pc outside its own table the row of the module `overlay_call` entered last. The switch was ignored for
  `--lib`: a module's instructions had no row, so the bus model gave each ONE bus access and no pattern, and level
  code ran too fast wherever display DMA or the blitter takes slots. Main translation and modules must be
  regenerated together (a module made by 1.0.72 does not link with an older main)
  - found on Turrican II (a pass of level 3-3 took one frame in the host and two in the original): the host's slot
    map against the original's bus log - 38 lines equal, then `lea d16(pc),a2` in the level's module with one access
    instead of two. That run, 654 passes, host with `-DHOST_IPL_MODEL=1`: every pass in the original's frame (one was
    not), a pass begins on the original's colour clock 400 -> 600 times, the Copper handler is entered on it in 453 ->
    660 frames of 719 and ends on it in 508 -> 675
  - arek_bus_glue.h takes the pattern tables of the row it got (`BUS_ROWSRC`; an older translation still builds)

## 1.0.71 (2026-11-13)

- `arek recomp --timing`: a jump into a table of `bra` slots (`--jtab ...:bra`) counts the slot's own instruction -
  the bra (10 clocks, two prefetches) or the rts (16) the 68000 runs between the jump and its target. The
  translation went from the jump straight to the target and the slot's clocks and bus cycles were missing. A
  translation must be regenerated to get them; nothing changes without `--timing`
  - found on Turrican II (the rest of KIT-GAP 37): its music player dispatches every command through such a table,
    so the Copper handler that calls it ended 4-38 colour clocks early. Level 4-1, 26 frames, host with
    `-DHOST_IPL_MODEL=1`: the handler's end on the original's colour clock in 21 frames of 26 (1 before), its entry
    in 20 (18), the main loop's next pass in 18 (1); without the switch the end is within -20 .. 0 (-48 .. -4)
  - `decoder.JumpTable(..., slots=True)` for the class's users; the command line sets it for `bra` tables

## 1.0.70 (2026-11-13)

- renderers (C and Python): a Copper write to a sprite's registers behind the line's sprite slots counts from its
  pixel on, as Denise takes it - SPRxDATA / SPRxDATB from lowres pixel 2c + 2 (c = the write's cycle), SPRxPOS /
  SPRxCTL from 2c + 3. A sprite that starts before that pixel keeps the line's picture, one that starts at or behind
  it shows the new words (or nothing), a start moved right behind a loaded picture draws the sprite twice. The
  line's sprites were taken once, in cycle $34: a Copper that zeroes SPRxDATA in mid-line left the sprite on that line
  - Turrican II level 1-2, the first line of the status bar (the rest of KIT-GAP 36): 12 frames had 10-54 pixels of
    a sprite there; now 561 of 563 pictures equal the original's (549 before; the other 2 are the run's first frames)
- renderers: inside the bitplane fetch the Copper gets every even slot no plane takes - slot 4 of a fetch group too.
  It counted as taken below 6 planes, so a MOVE behind a WAIT inside the fetch came 2 cycles late at 18 of 24
  positions with 1-4 planes and 2-6 cycles late at all 24 with 5
  - measured on the emulator's register log: WAIT at $41-$6F, 1-6 planes, 144 positions - all equal now
- host with `-DHOST_IPL_MODEL=1`: a running CIA timer's counter reads as the emulator's - two higher than the model's
  count (the model counts from the write that starts a timer, the 8520 two E cycles later), never 0 (the latch is
  there for two cycles: 2 1 20 20 19), the latch while a timer just started or loaded does not count yet. The
  interrupt's time was right, a read was two low
  - measured against the emulator with a boot program: 176 reads of CIA-A timer A (continuous with and without FORCE
    LOAD, one-shot, stopped, beside ICR reads) - 57 equal before, 176 now
  - Turrican II (KIT-GAP 37; it reads the timer's low byte in its Copper handler as the random number of the
    screen's shake), level 4-1, 26 frames: without the switch the handler is entered 2-10 colour clocks early (an
    interrupt is taken at the first instruction end; the original's wait loop had sampled the level before a bus
    cycle that stood 89 slots behind the Copper and the bitplanes) and 10 of 26 shake values are the original's; with
    the switch and this release 18 entries of 26 fall on the original's colour clock (the rest within -2 .. +6), the
    instruction after the read on 19 of 20, and 25 of 26 values are equal
- host with the switch: the Copper's INTREQ write is Paula's request a colour clock after its slot, as a CPU write
  is (the emulator runs the same code for both; not measured separately) - the request had the time of the
  instruction end that noticed it. `HOST_COP_LAT` in the environment tries other values
- `arek selftest display`: sprite 5's registers written in mid-line on three lines (SPR5DATA at the sprite's first
  pixel and 4 pixels behind it, SPR5CTL one pixel behind it): 32 of 204 060 pixels differed, now 0 in both renderers

## 1.0.69 (2026-11-13)

- host: a Copper interrupt requested while the CPU stands behind a blit across the frame's end is served. The
  requests of the Copper's INTREQ writes were raised at instruction boundaries; with no boundary between the write
  and the frame's end the roll forgot them
  - Turrican II, the restart of a level after the player's death (three blits of 512 x 48 words, the CPU waiting
    with btst / bne from line 235 into the next frame): the handler ran 4 times where the original's ran 6 and the
    music was 2 frames late from then on. Now 6 entries on the original's frames and lines (10858/42, 10859/47,
    10860/248 among them), and the 253 audio register writes of the 22 frames after it equal the original's
- renderers (C and Python): a write to SPRxDATA arms the sprite with that word, SPRxDATB sets the other word - the
  two registers were not known. A Copper list that switches sprite DMA off at the edge of a status bar and zeroes
  them left the sprite's last line in the bar as a stripe
  - `arek selftest display` has the case now (a sprite's data zeroed by the Copper, a sprite armed by a write
    without DMA, disarmed by SPRxCTL): 200 of 204 060 pixels differed from the emulator, now 0 in both renderers
  - Turrican II level 1-2: the bar is plain in the 12 frames that had the stripe, no other pixel of 225 frames changed
- host: PORTS and EXTER in INTREQ follow the CIAs' interrupt lines as Paula has them - a bit cleared while its CIA
  still asks (the ICR not read) is set again at once. A handler that clears INTREQ before it reads the ICR is
  entered again, as in the original
  - Turrican II: the handler's INTREQ write has the original's values ($2070, $21f0); frames of level 1-1 whose
    every CPU register write equals the original's in register, value and pc: 955 of 1 282 (1 before)

## 1.0.68 (2026-11-12)

- wb-scene 2.13, `passTime` and `rec.next`: the objects' passes on the time the game COMPUTED them, and the pass it
  has computed but not shown yet as one more pass (the last pass's pictures at next's positions). A game that
  computes a pass every 2 frames and swaps its buffers after 3, 1, 3, 1 frames had its even steps drawn as a double
  step and a stand; off unless the page sets it, the camera, the window and the sprites stay on `rec.t`
  - SWIV (60 Hz, latency 40 ms; all objects / the player / one helicopter): frames 4100-4400 0.218 / 0.072 / 0.324
    -> 0.176 / 0.087 / 0.215, frames 4200-5200 0.284 / 0.499 / 0.361 -> 0.270 / 0.484 / 0.323 with the pass times
    30 ms after the loop's start (with 0 the scene guesses past the newest pass and the player is twice as shaky);
    ground targets 0.000 px against the background throughout. `next` must be read where the logic is done: at the
    end of the frame 1.9 % of the positions were the pass before
- wb-nastaveni 1.3, `spec.omit = { sound: [...], display: [...] }`: rows a page leaves out (the Amiga's filters on a
  machine that has none - the Atari 8-bit page's request). Such a row is not built, cannot be set, and its value is
  fixed: the filters off whatever is stored, any other item the mode's default. `arek web test` section 6 asks for
  the rows the menu says it has and fails on a row left out that is in the document
- `arek web check`: `.xex .atr .atx .xfd .car .cas` are game data in a bundle too

## 1.0.67 (2026-11-12)

- `arek recomp --live ADDR` (Flow.live): an instruction whose IMMEDIATE operand the program rewrites (a trainer
  writes the number of missiles into `move.w #n,(100,a4)`) reads the operand from RAM when it runs - byte, word or
  long, the extension word raw as a prefetch; clocks and bus row are the instruction's own. An instruction without
  an immediate in an extension word (moveq, addq) is refused
  - SWIV: the crack's hook at $0008 had become an extern that read the operands itself. An extern's TICKs have no
    rows in the bus table and no way in for a resume: with 1.0.66 the host stopped in landscape 1 (`unknown routine
    00001a`, an interrupt inside the hook) and left the original in landscapes 3 and 4 (frames 8375 and 14151; the
    first register write 4 colour clocks early inside the hook). The hook translated with `--live e 14 1a`:
    landscapes 3, 4 and 1 with the trainer's options, 9 202 / 14 207 / 14 210 records equal in both memory hashes
    and every CPU register write, to the runs' ends (frames 9989 and 14989)

## 1.0.66 (2026-11-12)

- bus model, sprite DMA: the switch as Agnus has it (vAmiga `updateSpriteDMA`) - on in the line that EQUALS VSTART,
  off in the line that equals VSTOP. The map asked for VSTART <= line < VSTOP: control words with VSTOP above VSTART
  (data words read as control words behind a sprite of the list whose VSTART had passed) got no slot, in the original
  the DMA ran from VSTART to the frame's last line and the CPU waited for its slots. A Copper write to SPRxPOS / CTL
  compares at once too
  - SWIV, sci-fi landscape with the trainer's spread and five missiles (sprite 7 on lines 224-311 from frame 6200):
    the first differing register write was in frame 6201 (the VBL's 126 colour clocks early); now 5 960 records of
    5 960 equal in both memory hashes and every CPU register write up to frame 6748, where the run ended
- `arek recomp --smc ADDR=WORDS[,WORDS]` (Flow.smc): an instruction the program REWRITES (a crack's trainer turns an
  `add` into a `tst`, a `divu` into a `bra.s`). The translation holds every content - the words given are decoded with
  the image's bytes behind them, several instructions if they hold several - and takes the one whose words are in RAM
  when the place runs, each with its own clocks and bus-table row (bit 7 of the image row's flags sends `bus_tab_row`
  to `bus_smc_row`); words nobody named are `unknown_call`. A call or a jump as the other content is refused. Without
  the option the output is byte for byte as before
  - SWIV (three places, the options F1 F2 F3): 9 000 frames of random play - with the options on the trace equals the
    translation of the patched image byte for byte, with them off the unpatched one's; the two differ from each other
- the page engine, colours: `engine_dac(1)` gives `engine_rgb` the Amiga's converter (a component * 17, half-bright
  on the 4 bits; `ard_pal_dac`) instead of vAmiga's monitor, which stays the default for comparisons with screenshots
  ($FFF 236, $888 106: darker by 25 of 255 on average). Node: `open(dir, { dac: true })`, `eng.dac()`
  - SWIV, 13 frames up to 3000: byte for byte the picture its own rewrite of the table gave, the same hashes
- the page engine, raw keys: `engine_keyboard(1)` (natively `--keyboard`, Node `{ keyboard: true }`) sends
  `engine_key`'s events through the host's keyboard of 1.0.65 (the serial port, the handshake), all that wait at the
  frame's start; the default stays one event a frame straight into SDR
- wb-takt 1.6: a modifier key the map names is the game's (`ControlLeft` = fire) - its own keydown carries its flag
  and was dropped as the browser's since 1.0.41, so fire by Ctrl never went down; the mapped keys pressed while it is
  held are the game's too
- wb.css: no frame around the game canvas (the 1 px box-shadow; SWIV, Xenon 2 and Turrican II each switched it off)

## 1.0.65 (2026-11-12)

- raw keys in the input lines, the same on both sides: `K<hh>` a key pressed, `k<hh>` released (the raw code in two
  lower-case hex digits; an event of that frame, several in a line in their order)
  - the original: `vamiga-keys-899da5d.patch`, the eleventh (**a new emulator build**, `VAHeadless-899da5d-kit-keys`);
    `arek trace run --inputs` accepts the tokens and asks for the patch
  - the rebuild: `host_trace`'s lines take them (and `S`, space held) and send them through a keyboard in
    `arek_host.h` written after vAmiga's - the code in CIA-A's SDR 1610 colour clocks after the event plus the CIA's
    cycles, ICR's SP bit, PORTS with the mask, the next code after the game's handshake (CRA bit 6), the resync after
    143 ms without one; `host_key(code, down, t)` for a host of its own
  - SWIV (the second player joins with left shift and steers with the cursor keys; its VBL routine polls the CIA once
    a frame): the original and the host with the same lines, 5 619 records of 5 619 equal in registers and both
    memory hashes; the host without the keys differs from the frame after the first one

## 1.0.64 (2026-11-12)

- Paula model, audio DMA requests in two stages as the emulator holds them: in Paula from the moment a request is
  raised to the end of that line, then in Agnus until the channel's slot. A request raised after the line's end and
  before that slot is a second one, served a line later; the model had one stage and dropped it. With a period below
  114 (a word shorter than a line) one line in about 32 had no slot for the channel, a blit beside it took the slot and
  ended early, and the channel played a word twice. SWIV, landscape 3 (AUD0PER $6E, AUD1PER $6C from frame 19642 on:
  the level 6 interrupt 3 colour clocks late in frame 19643, the game's seed another way from 19644)
- captures of a playing channel (**rebuild the emulator with the current `vamiga-audstate-899da5d.patch`**: the build
  `VAHeadless-899da5d-kit-audio` is now sha256 151ee455...): the audio state dump prints Paula's own request latch
  (`audDR`) too; `arek host state` writes a request that is only in Paula yet, and a second request as the `@audio`
  line's 19th field (the host reads lines with 18 fields as before). A capture between a request and its line's end
  lost the request: SWIV at the VBL routine of frame 15003, channel 0 one word late for 1 721 samples
- host with the timing model: before every CPU access Paula fetches the audio words whose slots lie before it
  (`AREK_GLUE_ACCESS_CB`, new in `arek_bus_glue.h`) - a word is read before a store that comes later in the same
  instruction. SWIV rewrites a wave table while a channel loops over it: two samples wrong at some 60 places in 4.4
  million
- measured on SWIV (the trainer translation, frames 790-19706, records at the VBL routine): all six landscapes equal
  in registers and both memory hashes (18 931, 18 931, 18 929, 18 924, 18 924, 18 932 records); landscape 3's output,
  4.45 million samples of the four channels, equal in time and value but for three samples of channel 1 (frames 1200
  and 18597, open); from a state captured in the game (frame 15003) 1 256 records and 196 840 samples equal

## 1.0.63 (2026-11-12)

- host with the timing model and bus model: a CPU write to a DMA or display register that lands behind the frame's end
  (the instruction began before it, or its cycles are carried over beside a blit) is the NEXT frame's write. The host
  stored it before it rolled the frame, so the next frame started from it: a Copper list set with
  `move.l d0,$dff080` in clocks 15 and 17 of a frame ran in that frame, while the original's Copper had taken COP1LC
  in clock 0 and ran the old list once more. Now the bus model keeps such a write with the value the register had
  (`arek_bus_cpu_reg` with a time at or behind the frame's length), starts the next frame's map from that and brings
  the write at its clock through the journal; the host's picture takes the display registers written there after the
  new frame's Copper has started and the field's length is decided. SWIV, landscape 4 (frame 6721: the old sprite
  lists one more frame - other sprite slots from line 47 on, the level 6 interrupt 4 colour clocks late, 70 836 pixels
  of the picture): the VBL routine's time and registers equal in 18 924 records of 18 924 (frames 790-19706),
  pictures 6700-6760 equal; landscapes 1, 5 and 6 unchanged at 18 931, 18 924 and 18 932

## 1.0.62 (2026-11-12)

- `recomp --resume` runtime (**regenerate the translation**): TASK_RUN took a routine it had resumed from the stack for
  an empty one whenever the stack stood where it was afterwards - also when the routine had pushed a continuation
  (pea X(pc)), jumped on through a register and the rts there popped X. The continuation was skipped and the next long
  on the stack called. Now the last plain rts decides (RET_PC at that stack height): the run goes on at X. SWIV,
  landscapes 2-4: "unknown routine 640001" in the frame in which an interrupt had dropped the C frames inside such a
  routine; with the fix all three run on with the original's VBL times to their next unknown root (17 390, 5 953 and
  5 560 frames)
- bus model, sprite DMA after vAmiga's Agnus: a sprite's control words are fetched in the line of its VSTOP whatever
  the sprite did - also when its VSTART had passed before they came - and a VSTART equal to the line of that fetch
  starts the data in the next line. A list whose second sprite starts on (or before) the first one's last line had
  no slots for it; a blit beside them took the slots and ended two early. SWIV, landscape 5 (frames 12621 and 18482,
  first seen as a random seed two off): the VBL routine's time equal in 18 727 frames of 18 727; the desert and the
  final landscape unchanged at 18 734 and 18 735

## 1.0.61 (2026-11-12)

- bus model, accesses carried over a frame's end beside a blit (1.0.56 / 1.0.58), three more things the game's
  landscapes met:
  - the idle clocks between the carried accesses and behind the last one are kept - an interrupt entry that waits for
    a blit across the frame's end has 4 and 1 colour clocks between its seven cycles, they were run back to back
    (5 colour clocks short; SWIV frame 18009), and an instruction's clocks behind its carried access were lost
  - the cycle in which the instruction samples the interrupt level, when it is carried (and not the first carried
    one), samples in the new frame, behind the wait: an interrupt that came during a 400-clock wait was missed at the
    instruction's end and an older, lower one taken first (level 3 before level 6; SWIV frame 6690)
- `host_trace --inputs-v LO:HI`: the next input line at the first pass of the tick's pc in a frame on lines LO..HI -
  the emulator's own rule (`VAHL_INPUTS_V`, 0:99 by default). By frame number (the default, unchanged) the two sides
  agree only while the original's breakpoint is hit in that window in every frame; in a frame whose VBL handler
  starts lower (SWIV frame 16337: line 107, behind a long blit) the original takes no line and is one line behind
  from then on
- measured on SWIV against vAmiga, from the boot's capture through the title into the desert landscape (the trainer
  on, its three code patches translated): the VBL routine's time equal in 18 733 frames of 18 733, frame 790 to
  19508 (1.0.60: 5 904 in a row); the earlier scenario without the trainer still 5 865 of 5 865

## 1.0.60 (2026-11-12)

- a capture in the middle of a game carries Paula's audio channels: `? paula channels` of an emulator build with the
  new `vamiga-audstate-899da5d.patch` (state, counters, latches, data, the pending request, the next period event),
  `arek bpstate` / `arek trace run --capture-at` put it into cpu.json ("audio"), `arek host state` writes `@audio`
  lines and both hosts start their Paula from them (`host_audio_state`). Without the patch nothing changes, and
  `arek host state` warns when a channel is playing at the capture. SWIV, a capture in the desert at frame 15000:
  channel 1 was in the middle of a sample - 34 audio slots a frame in the original, none in the host, the first
  instruction 2 colour clocks early 33 lines after the capture
- with the timing model Paula takes a CPU write to DMACON two colour clocks after the write's slot and one to INTREQ
  one after (vAmiga recordRegisterChange; the AUDx registers at once): a channel switched on in slot 225 of a line
  started a line early and the blit beside it ended two slots late (SWIV, frame 15193). The Paula check
  (`arek selftest audio`) feeds the original's writes the same way - its numbers are unchanged
- measured on SWIV against vAmiga from that capture (made in the scratchpad with the new build; registers and RAM
  equal to the old build's capture): 93 978 instruction times in a row at 20 addresses, frames 15000-15335 (before:
  68). The next difference is not the kit's: the game's trainer patches code the translation was made from

## 1.0.59 (2026-11-12)

- display (arek.display and arek_display.h): with BPLCON2's PF2P above 4 - not a priority - OCS Denise ignores planes
  1-4 wherever plane 5 is set: the pixel is colour 16 (16 half-bright with plane 6), except in HAM (vAmiga
  translateSPF). SWIV's score line (BPLCON2 $003F, five planes for seven lines, the text in plane 5): 880-920 pixels
  a frame in lines 26-32 had the colours of what lies under the text; 21 pictures of 21 equal to the original's now
- the first release uploaded by the tag itself (`.github/workflows/release.yml`, PyPI Trusted Publishing)

## 1.0.58 (2026-11-12)

- bus model, an instruction beside a blit across the frame's end, again (1.0.56 had it for a lea): the blitter is
  not moved to the cap behind the frame's end or past it, and from there on it and ALL the instruction's remaining
  accesses compete in the new frame's map, slot by slot as anywhere else. 1.0.56 let the blit run on behind the
  premapped rows and guessed where the first carried access may stand - a movem that waited with 15 registers to go
  was 10 colour clocks late (SWIV, frame 5179)
- host: the next frame's first lines are premapped from the bus model's hook too - an instruction that began before
  the last two lines and waited through them (a lea beside a blit from line 310 on) found no Copper and no refresh
  behind the frame's end (frame 5300, 8 colour clocks early). The hook is installed for every host, not only with
  the floppy model
- measured on SWIV against vAmiga: from the boot's capture at frame 790 through the title into random play, the VBL
  routine's time equal in 5 865 frames of 5 865 (to frame 6652; 1.0.57: 4 390 in a row); in the game 260 762
  instruction times of 260 762 at 17 addresses over frames 5176-6308

## 1.0.57 (2026-11-12)

- blitter (the translation's runtime; **regenerate the translation**): the barrel shifters keep the previous word
  across rows - the bits shifted out of a row's last word come in at the next row's first word; only a blit's start
  clears them. The model cleared them at every row. Found by SWIV in the game (frame 4236: A = $FFFF shifted by 8 with
  ALWM $FFFF wrote $00FF at the start of every row, the original only in the first; times and registers of all blits
  equal, the state different one frame later)
- `arek parity`, sound: a rebuild started from a state in the middle of a frame, and a log that ends in the middle of
  its last frame - in the frame of a log's first record the other side's writes before that record are left out, in
  the frame of its last record those after it (when the log has beam positions; the result's `edge` counts them).
  Whole frames only one side has stay unequal
- `arek trace run --from-frame F` holds for the register log too (the build logs from power-on: the Kickstart's
  writes were frames only the original has). SWIV's boot: sound 832 / 845 was these edges and 11 Kickstart frames,
  no write differs - 833 / 833 with both

## 1.0.56 (2026-11-11)

- with the timing model, host_trace `--reglog` stamps a CPU register write with the write's own slot, as the
  emulator's VAHL_REGLOG does, and the Paula model gets an audio register write at that slot - the model's time is
  already behind the bus cycle. SWIV's boot: instruction times equal, every write in the host's log one colour clock
  later than the original's
- a captured state with a running CIA timer (with the timing model): the emulator's counter is two E cycles ahead
  of the model's own - the first interrupt after the capture came two E cycles late
- bus model, an instruction that crosses the frame's end:
  - an access that finds no slot up to one line past the end (a blit with BLTPRI holds the bus) was counted as served
    there and forgotten; it now waits on in the new frame (`arek_bus_frame_carry`, `arek_glue_frame_carry()` - the
    host calls it after it has planned its own DMA in the new map)
  - the audio slots are planned one line past the frame's end too (the next frame's line 0)
  - a CPU write that re-maps the frame (DMACON ... in its last two lines) cleared the premapped first lines of the
    next frame: the host premaps them again
- while a CPU access waits, the bus model asks the host for its DMA slots (`ArekBus.ahead`): the disk's slots were
  marked 160 colour clocks ahead of an instruction's start, and a blit the CPU waited for longer took them
- measured on SWIV against vAmiga with random play (a capture at frame 4000 made with `--capture-at`; loading, blits
  and music at once): 172 440 instruction times of 172 440 equal at 16 addresses over 1 100 frames (1.0.55: the
  first level 6 entry already 2 colour clocks late). From the boot's capture at frame 790 through the title into the
  game: the VBL routine's time equal in 4 390 frames in a row, to frame 5178 (1.0.55: 2 142, to frame 2930). Open:
  the next difference at frame 5179; the interrupts of the blitter, the audio channels and the Copper are not measured

## 1.0.55 (2026-11-11)

- floppy model: the byte clock needs no measured phase - vAmiga starts it at power-on and serves a byte in every
  56th colour clock, so in absolute colour clocks (frame x 313 x 227 + line x 227 + slot) a byte is served at 1 modulo
  56 in every run. The host takes it from its absolute time, i.e. from state.txt's frame number, which must be the
  frame of the run it is compared with (SWIV's capture was made at frame 789 of its own run and carried the trace's
  790: 71 051 mod 56 = 43, the "15 colour clocks between runs" of 1.0.54). `@drive`'s due field is ignored;
  HOST_FLOPPY_PHASE stays as an offset for a state without the original's frame number. In one colour clock the
  disk's DMA slot is served before the byte (vAmiga's order). SWIV: the same 110 451 instruction times in a row and
  an empty `arek bus diff`, now without any setting

- the bus pattern of every instruction, measured on Moira (`arek.m68k.buspat`, `buspat.json`: 1314 shapes + 28 of
  movem): its clocks without the bus and its bus cycles in the order the processor makes them (program reads, data
  accesses, the clocks that depend on the data), and the place where it samples the interrupt level. Until now a host's
  model made the prefetches first, then the data accesses, then the idle clocks, with the rules of 1.0.53 for the last
  prefetch and the sample - the right length on a free bus, but beside DMA every access waits for ITS slot, so the
  order decides where the instruction ends. `arek recomp --bus-table` writes rows of six bytes (the pattern's index;
  `BUS_PAT`, `BUS_VAR`, one variant per clock count for a branch taken or not, dbcc, scc) and the bus model plays the
  pattern (`arek_bus_pat_begin`); used with `-DHOST_IPL_MODEL=1` only, **translations must be regenerated**, a row
  without a pattern and an older translation go the old way. `HOST_BUS_PAT=0` in the environment of host_trace / the
  native engine switches the patterns off for a comparison. The clocks that depend on the data are the whole gap (the
  instruction's count minus everything else), not the smallest gap Moira's random operands showed plus a rest: mulu by
  a word with one 1 bit was a colour clock too long
- the timing model's request times are vAmiga's own now, nothing fitted: Paula's level reaches the 68000 three colour
  clocks after INTREQ / INTENA change, VERTB is requested at colour clock 0 of the frame, a CIA's interrupt in the E
  cycle in which its counter reaches 0 (1.0.50-1.0.54 had 2 + 2 and 6 + 2: VERTB one clock late - an instruction that
  starts on clock 2 of a frame meets it). A CIA timer started by a write that also loads it (the high byte in one-shot
  mode, the control register with FORCE LOAD) counts one E cycle later than one started by its control register alone;
  a forced load of a running timer skips a count
- with the timing model VHPOSR / VPOSR are read as Agnus reports them: the position of the access's own slot plus five
  colour clocks, in the first two clocks of a line still with the old line number (a game that seeds its random
  numbers from VHPOSR in an interrupt handler: SWIV)
- floppy model: a CPU read of INTREQR / DSKBYTR and a write to the disk registers see the disk up to the access's own
  slot - the DMA word in the next slot (7, 9, 11) that raises DSKBLK is not there yet (a poll loop left a read one
  pass early, once in 31 reads)
- measured on SWIV's whole boot against vAmiga, from the capture at frame 790 to the title at frame 2613 (45 disk
  reads, the decompressor beside five bitplanes, 5 200 level 6 entries of the music routine, the VBL handler, the
  random numbers): 22 780 instruction times of 22 780 equal at 14 addresses, and 1 687 863 of 1 687 863 at 28
  addresses over the first 600 frames (1.0.54: 111 441 in a row)
- `arek difftest --moira DIR --bus-patterns FILE` measures the table again (30 s); the harness logs every bus cycle
  and sync of an instruction and the position of the interrupt sample. `tests/data/buspat_corpus.json` keeps Moira's
  events for every shape: the table and the C executor are tested without Moira

- `arek trace run --capture-at FRAME --capture-dir DIR [--capture-addr A] [--capture-region BASE:LEN]`: a traced run
  (with its `--inputs` file) stops at the first breakpoint hit in that frame or later and dumps the machine as
  `arek bpstate` does - a state and a trace of one run. Needs the emulator built with the new
  `vamiga-stop-899da5d.patch` (`VAHL_STOP_FRAME`, `VAHL_STOP_ADDR`); the stop script and the capture writer are shared
  with bpstate (`bpstate.stop_script`, `parse_stop`, `write_capture`)

## 1.0.54 (2026-11-11)

- floppy model, measured on SWIV's first read against vAmiga (per-instruction times and the bus log): a byte passes
  every 56 colour clocks (vAmiga schedules the next byte relative to the colour clock that served this one: 442
  master cycles later is the 56th), not every 55.26 - the first sync came 305 bytes late; the disk's slots are marked
  across a frame's end too. With the byte clock's phase of the trace run (`HOST_FLOPPY_PHASE`: a capture and a trace
  of the same disk are different emulator runs - 15 colour clocks apart here; the period is 56 in both): 110 451
  instruction times in a row equal to the original's - the motor's /RDY, the seek, the whole first read (55 000
  passes of the loader's poll loop beside the disk's DMA), its decoder and the return; `arek bus diff` empty
- host_trace inputs: `M` / `m` in a line press / release port 0's button (the left mouse button; CIA-A PRA bit 6) -
  SWIV's original releases it at frame 815 and its VBL handler then takes another branch

## 1.0.53 (2026-11-11)

With `-DHOST_IPL_MODEL=1` only; translations must be regenerated (`arek recomp --bus-table`: the table's rows have a fourth byte):

- the bus table's fourth byte (`timing.bus_order`, `timing.bus_poll`): where an instruction's last prefetch falls among
  its data accesses (after the operand reads; between the reads and the writes of an instruction that does both) and in
  which bus cycle it samples the interrupt level (a long move from a register to memory: between its two write words;
  addq / add Dn / bclr / neg / memory shifts / andi: at the prefetch before the write). The model made every prefetch
  first and sampled in the last access. SWIV's boot against vAmiga: 102 VBL entries in a row on the original's slot
  and instruction (25 before) - up to its first disk read, which is an extern
- host: drive DF0 and the disk controller, `-DHOST_FLOPPY=1` (`arek_host_floppy.h`, after vAmiga's DiskController /
  FloppyDrive / AmigaEncoder) for a game that reads the disk with its OWN loader - the read routine is translated, no
  extern and no table of read times: the MFM track from the ADF (11 AmigaDOS sectors + gap, 12 668 bytes) passes the
  head at the disk's speed, DSKSYNC / WORDSYNC, DSKLEN (two writes), a word per disk slot ($07 $09 $0B) to (DSKPT)+
  with the slot taken from the CPU, DSKBLK and DSKSYN, DSKBYTR; motor (380 ms to /RDY), select, side, step, /TK0,
  /CHNG on CIA-B PRB / CIA-A PRA. Reading only, DF0 only; the image is `AHD_IMG[0]` (`HOST_ADF0` natively). A capture
  now carries the drive (`? df0`, `? paula dc`, `? agnus events` -> cpu.json "drive"; `arek host state` writes
  `@drive CYL BYTE DUE MOTOR PRB`): the head starts where the original's stood. Synthetic test: a loader of forty
  instructions reads a track of a random disk. NOT yet measured against the original's read times
- host: interrupts are taken inside `host_spend` again with the model (the sample point of the last instruction was
  used for the whole spend: none was taken); `host_spend` ends on a whole colour clock

## 1.0.52 (2026-11-11)

With `-DHOST_IPL_MODEL=1` only (the timing model measured on SWIV against vAmiga; without the define a host behaves as 1.0.49):

- bus model (SWIV KIT-GAPS 9): CPU writes to DMACON, DIWSTRT/STOP, DDFSTRT/STOP, BPLCON0 and COPJMP take effect in the
  SAME frame from their slot on (`arek_bus_cpu_reg`: the rest of the frame's map is worked out again); a COP1LC written
  while the Copper has not run in the frame is where it starts (vAmiga pokeCOP1LC). SWIV's loader switches the Copper
  and the bitplanes on in line 215: per-instruction times of frames 790-792 against the original 1262 of 1263 equal
  (before: 13, the rest 12 to 26 colour clocks early)
- host: a CIA write lands AFTER its wait for the E clock (a timer it starts, starts then); the CIA's interrupt reaches
  the pins one E cycle after the underflow. SWIV, a one-shot timer restarted by its handler: level-6 entries within
  10 colour clocks of the original over two frames, no drift (before: 10 to 60 early and growing)
- host: the interrupt entry spends its 44 clocks in the 68000's order (6 idle, a write, 8 idle, two writes, the
  vector, a prefetch, 2 idle, a prefetch) - beside the Copper's slots at a frame's start the accesses wait where the
  original's do. SWIV's boot: 25 VBL entries in a row on the original's slot and instruction (before: 2)

## 1.0.51 (2026-11-11)

- host, with `-DHOST_IPL_MODEL=1` (SWIV KIT-GAPS 7): CIA accesses wait for the E clock as vAmiga does
  (Agnus::syncWithEClock: position 2, the next cycle's when less than 6 clocks away - 6 to 15 clocks, worked out 2
  clocks into the bus cycle), at the place the 68000 makes them (before the instruction's last prefetch; the write of
  a read-modify-write after it: `arek_bus_undo_last`), and no longer counted a second time as a chip-bus access.
  SWIV's VBL handler against vAmiga: 56 of 56 times equal over two frames (before -3 / -2 colour clocks per CIA
  instruction, -5 to -10 a frame); the second VBL entry is now on the original's slot AND instruction. Without the
  define nothing changes (the rule fitted on three instructions stays)

- host (Turrican II KIT-GAPS 34): a faster CPU - `engine_cpu_speed(n)` (from the next frame's start; the page calls it
  between frames, as a key) and `HOST_CPU_SPEED=n` for host_trace: n sixteenths of the 68000's time per instruction
  (16 = the original, to the byte; 8 = twice the instructions a frame). The frame, Copper, blitter, CIAs and Paula
  keep their times; `host_spend` is not scaled. For a game mode that asks more of the CPU than the original did
- note: the native engine without `--thread` leaves a frame only in a wait loop the translation knows (WAIT_LOOP); a
  game spinning in a plain loop needs the threaded engine (a test with `nop; bra` timed out for this reason)

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
