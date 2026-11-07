# REBUILD-PLAYBOOK - a whole game in the browser, the method the rebuilds settled on (kit 1.0.20)

`docs/METHOD.md` says how to read a disk and translate a routine; `docs/HOST.md` describes the host and the engine;
`docs/WB-RECIPE.md` the display and sound stack. This page is the path BETWEEN them: the order of the milestones, what
each one needs from the kit, and the lessons three rebuilds paid for - Alien Breed II (Opus, 2026-10), Superfrog
(Sonnet, 2026-10) and Turrican II (Sonnet to M5, Opus from M6, 2026-11; 29 kit gaps, all fixed by 1.0.19). Every lesson
here was measured in one of them; nothing in this page is game data, and every address a new game needs is measured
again. An agent starting a new game reads this page after `arek-agent.md` and before writing its own plan.

## The knowledge base (kit 1.0.25)

When a knowledge base is set up (`AREK_KB`: `arek kb search`, `get`, `add`; the same as the MCP tools `kb_search`, `kb_get`,
`kb_add`), it is part of the method:

- **before working around a problem**, `arek kb search` with the words of what you see (the log line, the divergence, the
  address); a record of another game that matches is a lead - its fact is a hypothesis for your game, re-measure it;
- **after every milestone**, `arek kb add` what you learned that the next game can use: a problem and how it was found and
  solved, a game or engine fact with its measurement, a procedure. One lesson per record, English, short, no game data;
- **a kit gap** goes to `docs/KIT-GAPS.md` and to the kit session as before; when the kit fixes it, its record says the
  version (`status: fixed`, `fixed_in`).

Proposals land in the base's inbox and become records after review. A brief that measures a model on a clean start
(no knowledge of other games) leaves `AREK_KB` unset.

## Tasks with stacks of their own, and the CPU itself (kit 1.0.26)

A game that switches tasks by loading another a7 and doing `rte` or `rts` (a scheduler with a ring of task records) needs
`arek recomp --resume`; without it the stacked PC of a sleeping task is not an entry and the run stops at `unknown
routine`. TRAP handlers are found through their vectors at run time: make them roots. When the translation and the
original differ in a way no routine explains, `arek difftest` tells whether the kit's 68000 is at fault before anyone
reads the game's code.

## The milestones

| | milestone | done when | the trap the rebuilds met |
|---|---|---|---|
| M0 | inventory | hashes, boot block, `arek adf map/regions`, the crack's layers, the input sequence that leaves the intro | `arek shot` / `bpstate` times are seconds, not frames; a crack shows several screens each waiting for a mouse click |
| M1 | packers and the boot chain | every stage unpacked and equal to RAM byte for byte (`arek bpstate` + `arek diff`); the catalogue, the main file, its address | an unknown packer is a decrunch routine to read, not a format to guess; a stage that is not a plain decrunch (a loader jumping through a table) |
| M2 | code | `arek walk`, `hwscan`, `xref`, `arek roots`: entry, main loop, VBL, interrupts, frontiers listed; the loop and the VBL confirmed with breakpoints at run time | the crack's trainer hook crashes the game after the intro (NOP it in measurements, replace it with an extern in the build) |
| M3 | translation | `arek recomp --timing --bus-table --auto-soft` of the resident code, `arek host copy`, host_trace equal to the original's trace with and without input (`arek trace run --inputs` + `arek fuzz`); `--cover` | overlays: one module per area at a time, two simultaneous modules = two `--overlay` areas; an audio interrupt the game needs from frame 11 on |
| M4 | the chipset from the kit | `arek selftest bus/audio/display` 0 disagreements, `arek render --compare` 0 px, the host's picture = the emulator's shots | a frame-exact input shifts the frame numbering by one against the recording |
| M5 | parity of the first level | `arek parity suite.json`: state 100 % tick by tick, picture and sound measured and the differences explained; AND a boot from the disks compared with the original's RAM at the first passes of the main loop | the original with `--inputs` needs a breakpoint with a small v (a spin loop records 800 000 passes); VAHL_REGLOG logs from the run's start (cut it); **a parity scenario that starts from a captured state never runs the game's initialisation** - Turrican II built a table wrong at start (kit 1.0.23's `move.l (-16,a4),(a4)+`) and every scenario passed, because the captured state already held the original's table |
| M6 | the whole game natively | every level and transition natively from the disks through the host's disk extern; the game's own unpacker as an extern; module discovery (below) | a self-modifying unpacker (a C port verified against `arek t2` byte for byte); the module registry built from the base of the overlay, not from the entry address |
| M7 | web | `arek host engine --thread`, native = wasm (chip RAM hash after thousands of frames), the page by `WB-RECIPE.md`, the disks chosen by the visitor, `arek web seal`, `arek web test/replay/smooth` | timing: interrupts, a blit over the frame's end, the disk's load times (below); module coverage (random input never reaches bosses, ends, the story) |
| M8 | the public build | two builds from one commit (public and test with Debug), English only, no comments, no name, no support block, `arek web check`, deployed to the test area first | see the checklist at the end - Turrican II reached M9 with none of it in its build script |
| M9 | Enhanced | the scene record from the engine, smooth motion at any display rate; the wider view and the earlier enemies only when the owner asks | see "Smooth only" and "Margins" below |

Turrican II's wall time: M0-M5 3 h 30 min with Sonnet, M0-M7 30 h 15 min including the kit's releases, M9 two days.
Record the start and end of every milestone, the kit version and the decoder hash, and a model switch with its time.

## Start from the disks without a Kickstart (M6-M7)

The web page must start from the visitor's disks only: no captured RAM, no state of the original in the build.

1. **Measure what the loader hands the main program at its entry**: `arek bpstate --address ENTRY --set-at N` on the
   original - the registers (Turrican II: d0 = the free-memory block chain the boot block built, d1, SR), the stack, the
   Copper list the loader left (the game may append to it and wait for ITS interrupt), what the game reads of ExecBase
   and of low memory `$0-$3FF`. Superfrog's lesson: a game reads low memory through null pointers (an object without an
   animation pointer read `$000006`); log every read below `$400` in the host over all levels and provide ONLY those
   words - never a kilobyte of the emulator's RAM.
2. **A synthetic start state**: zero chip and slow RAM, zero custom registers, supervisor, INTENA = INTREQ = 0, DMACON as
   after the Kickstart (from the reglog), the beam time and the frame counter the original had at the entry
   (`arek_host_engine_node.js` `synthState()`, or `arek host pack` of a folder with an empty `chip.bin`).
3. **An entry routine in the project's externs** (`HOST_ENTRY=game_boot`): read the main file from the disk image by the
   catalogue (`arek_host_disk.h`), build what the loader passed (the memory block, the registers, the Copper list, COP1LC),
   set the stack and call the translated entry. Interrupts through the vectors in RAM (`HOST_L3=host_vec_l3`,
   `HOST_VECTOR_HANDLER`): an intro and a game that rewrite `$6c/$70/$74` at run time need no special case.
4. **The crack's hook as an extern**: the trainer's `jsr` in the main file is translated as it is on the disk and the
   target replaced (`--extern ADDR=game_trainer`) by a routine that writes what the trainer wrote (a level choice, no
   cheats). The page's level choice goes through the same words, set by an event at an exact frame - not by poking the
   game's variables directly (Turrican II: its demo mode drew over the trainer's operands; the words moved to slow RAM
   past the game's memory block).
5. **The disk routine as an extern** (`--extern ADDR=game_read`, `engine_set_disk` images), the game's unpacker as a C
   port when it is self-modifying, and the **load times of the original** for every read and unpack (measured with
   `arek trace`, by arguments, not by a formula): `host_spend(m, cck, 0)` in the extern keeps the main program in the same
   phase against the interrupts as the original - without it the intro's blits came a frame late and the logo broke. A
   fast-load flag (a byte in slow RAM the page sets) skips the spending for the player.

## Module discovery (M6-M7): overlays that the game loads at run time

Levels and the intro are overlay modules loaded into the same area; the translation registers each one by the
fingerprint of its image at the area's base (`--overlay BASE:SIZE`, `--lib --prefix --overlay-module`). The loop that
found every module of Turrican II (its `tools/modules.py`, 160 lines):

1. The host runs with `-DOVERLAY_HOOK -DUNKNOWN_HOOK`; an unknown module or routine dumps the area's image
   (`ovl_<fingerprint>.bin`) and appends `fingerprint base length address` to `unknown.txt`, then exits.
2. A registry (`mods.json`) keeps per module: name, base, roots, `dynamic` sites, `indirect` tables, `jtab` tables,
   `bad` roots. `sync_registry()` turns every new line of `unknown.txt` into a root (a resident address below the
   overlay area goes into the main translation's roots instead).
3. `arek roots IMAGE --base B --json` once per module gives the static candidates (pointer tables, `lea`/`pea` bases,
   immediates, `bra.w` slot tables); `arek recomp --auto-soft --refusals ref.json` drops the ones that lead into data.
4. A refusal's frontiers decide the next try: `jmp $T(pc,dN)` with `bra.w` slots at T → `--jtab`; the same with inline
   code after the slots → `--indirect SITE=T,T+4,...` (one `--indirect` with all tables - a repeated switch replaced the
   previous one); `jsr/jmp (aN)` or `(d,aN,dN)` → `--dynamic SITE`; a table whose slot 0 is unused (`jmp $T(pc,d0)` with
   d0 >= 4) → the slots from T + 4; a routine that still refuses → `bad`.
5. The host is linked; an undefined `_f_XXXXXX` is a resident routine a module calls that the main translation lacks →
   a root of the main translation, rebuilt, linked again (a loop of at most a few rounds).
6. Coverage runs: random input (`arek fuzz`), a walk to the right with jumps and fire, every level started from the
   disks, every level finished at once (a "level complete" flag poked at the start) so the transitions, the bosses'
   screens and the end run, the intro and the story for tens of thousands of frames. Coverage is not proof - say which
   paths no input reached.
7. Native = wasm: `arek_host_engine_mt ... --dump` against the harness after 1 500 / 3 000 / 6 000 frames, chip RAM
   identical; a native build without `--thread` runs tens of frames further for the same N (no marked wait loops), so the
   check line is always the threaded one.

Levels that use data an earlier level left in memory (Turrican II 3-3 drew the pattern 3-2 loaded) start from the
world's first level and finish it at once until the chosen level is loaded - the page's "chain" event.

## The page (M7): events at exact game frames

The engine in its thread is held at the frame of the next event (`engine_allow(min(n, event.f))`); the event (keys, a
poke, a mode switch) is applied while the engine waits at that frame, then the permit continues. The same game at 50, 60,
120 and 144 Hz (`arek web replay`), and the same game in a Node measurement (`arek_host_engine_node.js` uses the rule:
an event at f runs after frame f is done, before frame f + 1). Rules the rebuilds learned:

- an event may be passed by frames already permitted: take it at `done >= f`, never only at `==` (the game waited for
  ever);
- `engine_aud_low` (the thread computes on under 15 ms of sound reserve without a permit) only while no event is pending;
- `takt.stamp(n)` is the time of the frame the clock counted as done: a record of frame n made at the end of frame n is
  `stamp(n + 1)` - Turrican II gave every record the previous frame's time and lost 50-90 % of its pairs;
- read the engine's picture BEFORE `takt.tick` grants new frames, and never from a resize or menu handler while the
  thread runs; without smooth motion the page must still draw every game frame (one grant, one read, one present);
- `prepare()` for `arek web replay` drives the engine directly to a fixed game frame (not through the display's clock);
  `done()`/`inputs()` count from that frame;
- the first key leaves the intro at a measured frame; "reached levels" are read from the game's own level words after
  the disk reads of a level start, kept in localStorage; every storage access in try/catch, IndexedDB with error handlers.

## The scene record (M9): what the engine gives wb-scene

`-DENGINE_FRAME_RECORD=game_record` (HOST.md): once per finished frame, before it is published. What Turrican II had to
find in RAM, and where the lessons are:

- **the camera** in pixels (tile column/row words plus the fine scroll), measured against the picture with
  `arek bpstate` dumps of consecutive frames; the picture of frame n may show the camera of frame n - 2 (a ring of
  buffers drawn ahead) - measure the delay, do not assume it;
- **the clean window**: the buffer the game restores objects from (a clean copy, `+$c000` in Turrican II) found through
  the Copper's bitplane pointers; the Copper simulated from COP1LC (the chain of COP1LC/COP2LC and the strobes) gives the
  palette per row and the sprites per row as the beam would see them; BPLCON1 the odd/even delays;
- **objects** by a pc hook on the draw routine (the object list node address is the id; the image from the descriptor,
  the mask and BLTSIZE), the HUD as screen-fixed objects, the player's shots too (they were in `over` first, without
  interpolation); **the pass** = the draw set shown in the frame, objects interpolate between passes
  (Turrican II draws 0.95-1.00 passes per frame - measure yours: a draw rate of 25 Hz halves the pairs);
- **sprites** per line from the Copper's and the CPU's writes, only occurrences the hardware would show (a beam parked
  beyond the display window stays out - the kit does not clip to the DIW);
- **the map** by columns or rows as the game stores it, tiles decoded into the atlas (4 slots of 16 x 16 per 32 x 32
  tile, 1 024 slots), cell changes recorded per frame; tiles the game recomputes (parallax, water) go through the draw
  set and are applied when their buffer is shown; a per-row colour (the sky) found in RAM as consecutive words gives
  `window.palTop` rows for the margins;
- **`valid`** must look at the hardware's DIW and the game's screen, not only the Copper list: the high-score table, the
  grid transition, the black screen with the score after a death all keep the level's Copper list;
- the ring of records: read at most 24 frames back (the slot 31 back is the one the engine writes next);
- the check: `WBSCENE.reference(compose(record))` against the engine's picture in the window, 0 px over tens of frames
  of every level, and the map drawn from the atlas against the clean window (0 px except the game's own animated
  cells); `arek web replay` EQUAL; `arek web smooth --gpu` 0 dropped, camera jitter 0.000 px, 0 % missing pairs.

### Smooth only (no wider view)

The owner may want only the motion (Xenon 2's brief): `extX = extY = 0`, the Original picture, interpolated. The scene
still needs the map record: between two game frames the view's camera sits between the two cameras and the rows (or
columns) the game has not drawn yet come from the map - without a map they are black for a frame. Objects by passes,
sprites by pairs (wb-scene 2.4 anchors each per pair: a sprite standing in the world goes with the ground, one holding
its screen position stays), `palAnchor: 'screen'` when the Copper colours belong to screen rows. Keep the game's own
choices behind Debug switches until the owner decides: `subpixel`, `camMean`, `latC / latO`, `lock`.

### Margins and earlier enemies (only when asked)

The wider view draws the margins from the map and keeps the enemies alive there; Turrican II's method (the generated C
patched with "constant + f(n)" where n = 0 is the original, every substitution checked by its occurrence count) and its
audit lessons: an object kept past its removal check stops dead at the window's edge (keep only what still moves or
animates); removal paths that do not go through the common "remove" routine let objects vanish inside the margin
(widen every bound, measured per type); a vertical band of 0 leaves pop-ins above and below; objects drawn over the ring
buffer's edge leave noise - draw them through the scene only; the death and transition screens need their own `valid`.
Everything measured: "enemy should be in the view and has no object" per level and region, Original hash equal to the
build without patches, replay EQUAL with a different hash per mode.

## The public build (M8): the checklist the build script enforces

The public bundle and the test bundle come from one commit; the script FAILS on a violation, it does not warn:

1. `arek web strip --drop DEBUG` with the markers `<!--@DEBUG{-->` / `<!--@}DEBUG-->` and `//@DEBUG{` / `//@}DEBUG`
   on lines of their own (a marker on a line with markup is not a marker: the menu stays, dead);
2. no Czech (or any other) diacritics in the HTML, the JS and - the trap - the C strings compiled into the wasm
   (`strings engine_mt.wasm`); comments stripped (terser for comments only, nothing renamed); no personal name, no
   support block, no `?x=` switch the sealed build would honour;
3. `manifest.json` next to the page (what `arek web check` needs: the files, their hashes, the sealed engine) and
   `arek web check` 0 problems; the engine only sealed (`arek web seal --set DISK1,DISK2 --gzip`), never an unsealed wasm
   on the web; `_headers` with COOP / COEP and no-cache;
4. `arek web test --quick`, `arek web replay`, `arek web smooth --gpu` and the scene check as one command with
   thresholds (`tools/check.sh`), run before every deployment; a measurement script without a threshold is not a check;
5. the test area first (password), the public page only after the owner played it; game files never on a host where they
   could become public, not even for ten minutes.

## Reproducibility

- every root list, module registry and patch count lives in the repository or is regenerated by a script in it; a file a
  deleted tool once wrote (Turrican II's `roots_static.txt`) makes a fresh clone build a different C;
- paths to disks only through `local.conf`, never `local/...` in a script; the kit only from PyPI, pinned in `.venv`;
- one engine loader for measurements (`arek_host_engine_node.js`), not a copy in every script; one check script with
  thresholds; the build's intermediate C in one place per variant (a NOPATCH build must not overwrite the patched one);
- traces of parity runs (`.vtr`, gigabytes) deleted after the measurement is written down.
