# The method

Three Amiga games went through this pipeline (S.W.I.V., Turrican II,
Superfrog). The order matters more than any single tool: each step produces a
*measurement* the next step is checked against, and nothing downstream is
allowed to rest on a guess.

## 0. Inventory the original

`arek adf info` → size, SHA-256, boot block type and checksum. Write the hash
into your docs: every claim you make later refers to *this* image. Cracked
images differ from each other in offsets and sometimes in behaviour (SWIV's
starting weapon differs between SWIVFIX and a clean dump).

## 1. Look before reading: the entropy map

`arek adf map` draws the disk, one character per 512-byte sector:

```
trk   0  c#######......----ccccc
trk   2  ####dddddddddddddddddd
```

Code is `c` (5.5–6.8 bits), packed data is `#`, graphics are `d`, tables
and text are `-`, unused sectors `.`. `arek adf regions` turns the picture
into ranges with track numbers. This is where the loader lives, where the
big packed blob is, how many files there probably are — before a single
instruction is decoded.

## 2. Boot chain and packers

The boot block (first two sectors) is code; `arek dis disk.adf --base 0
--walk 0xc` lists what is reachable from its entry. Follow the trackloader
reads (`trackdisk` `DoIO`, or a custom MFM reader writing `DSKPT/DSKLEN`) to
the next stage, dump it with `arek adf track`, repeat.

If the boot block is `DOS` and the signatures sit 24 bytes into their
sectors, the game keeps AmigaDOS files (OFS data blocks): `arek adf ls` lists
them, `arek adf cat` reassembles one with every block verified, and only the
reassembled file is a packer's input.

`arek scan` finds packers. A *signature* (PP20, RNC, ATN!, IMP!, …) is a hint;
a *verified* Bytekiller block (header plausible - the 8-byte B or the classic 12-byte BK layout - XOR checksum zero, full
unpack succeeds) is evidence. When neither fires, the game has its own
packer — read the decrunch routine (it is always short, always near the
loader) and re-implement it. `arek.packers` holds four such
re-implementations; the Bytekiller one is worth reading as a template:
backwards bit stream, sentinel bit, checksum — thirty lines.

Verify every unpacker against the emulator: `arek bpstate` right after the
original's decruncher returns, then `arek diff` your output against the RAM
dump. Byte-exact or it is not done.

## 3. Find the catalogue through the code

Games with many files have a catalogue (name/offset/length table). Do not
reconstruct it from patterns in the image — find the loader routine that
walks it (`arek walk` from the loader entry, `arek xref` for who calls the
disk routine) and read the table exactly the way the game does. Data formats
have many plausible readings; code has one.

## 4. The hardware boundary

Before translating anything, measure what the code touches:

```
arek hwscan main.bin --base 0x20700 --roots 0x20700 --abase a5=0xdff000
```

The report splits routines into pure-RAM (translatable as-is), hardware
(custom chips, CIA, ROM — need a model or a re-implementation) and
*unknown base* (reads through an address register whose value the static
scan cannot know; give it with `--abase` once you have measured it with a
capture). The percentages tell you how much of the game is "just
computation" — usually most of it — and which routines are the few that
really drive Agnus, Denise and Paula.

## 5. Static recompilation, routine by routine

`arek recomp` turns 68k routines into C that operates on a `MEM[]` array and
a register struct, logging every write. The decoder raises on anything it
does not model (`divs`, `chk`, …): the output never contains a silently
wrong instruction. Jump tables and library calls become named stubs
(`--stub a6:-198:OpenLibrary`) you implement.

A `bsr`/`jsr` is a C call that pushes the return address; `rts` is a C return. The 68000's `rts` jumps to the
long at (a7), so the translation checks the stack against the routine's entry (1.0.24): a routine that pushed a
target (`pea X` / `move.l X,-(a7)`, then `rts`) or replaced its return address runs that target through
`call_addr`, and the chain goes on until the routine's own return address is popped; a routine that popped more
(`addq.l #4,a7; rts`, a return to the caller's caller) makes its caller return too. A call whose target is unknown and whose
hook returns (`UNKNOWN_HOOK`, `OVERLAY_HOOK`) leaves no return address behind: the run goes on as if the target
were an empty routine. The source of every two-operand
instruction is read before the destination's `(An)+` / `-(An)` moves the register (1.0.23). A static target of such a
jump is a root (`arek roots` lists `pea` and immediate addresses); a run-time one reaches `unknown_call`.

Exceptions the same way (1.0.26). `TRAP #n` writes the 68000's frame (PC behind it, SR), sets S and calls the routine whose
address is in the vector at `$80 + 4n` at run time; the handler is a root like any other. `rte` reads SR and the stacked
PC: a frame at the routine's entry with its PC unchanged is a plain C return to whoever entered the exception (the host's
interrupt, a TRAP); a frame the routine pushed, or a PC it replaced, is a jump there, chained as for `rts`.

A game whose tasks have stacks of their own (S.W.I.V.: a ring of task records, the yield saves a7 in one and takes the
next one's, then `rte`) cannot keep its run on the C stack: each switch would leave the C frames of a task that is now
asleep. `arek recomp --resume` makes every translated instruction a target of `call_addr` (a routine goes on at the label
`RESUME_PC` names), so all the run needs is on the 68000's own stacks; a jump onto another stack (`rte` or `rts` that does
not return to the caller) drops the C frames and goes on at the target through `TASK_RUN`, which the kit's hosts and the
driver wrap around their first call. Pre-emptive switches from an interrupt handler work too: the stacked PC can be any
instruction, and the host's interrupt depth is reset. The cost is code size (a `switch` per routine) and a `longjmp` per
switch; a run that switched ends at an exit or the host's stop, as there is no C caller left to return to.

### Checking the translation against the 68000

`arek difftest --moira DIR` builds Moira, the CPU of vAmiga (from its source, MIT), and runs every opcode the decoder
accepts on both: the same registers, SR and RAM, one instruction (the branches, calls, `rts`, `rte` and `TRAP` with a
place to go), then registers, flags, memory, where it ended and the clock count must agree. Cases where Moira takes an
exception other than TRAP, touches anything above the mirrored chip RAM or writes into the instruction itself are not
compared: the translation has no such exceptions by design. About 120 000 cases run in half a minute. The first run
found five slips that games had not shown: `negx` lost the carry of its first half, `divu`/`divs` overflow left N and Z,
ABCD/SBCD with digits above 9 and their V flag, `movem` to `-(An)` with An in the list, and SR bits a 68000 does not
have; `link a7` now pushes a7 as Moira does. It also lists the legal 68000 instructions the decoder still refuses
(`chk`, `movep`, `nbcd`, `tas`, `move usp`, `rtr`, `trapv`, `stop`, `reset`). `--record FILE` keeps a sample with
Moira's results; `--corpus FILE` replays one with a C compiler alone, which is what the kit's tests do.

With `--main` the C file gets a driver: *RAM dump + registers in → routine →
RAM dump + write log out*. That is the verification loop:

1. `arek bpstate --address ENTRY --out cap/in` — the original, stopped at
   the routine entry (registers, beam position, chip RAM).
2. `arek bpstate --address RTS_ADDR --out cap/out` — same run, stopped at
   its return.
3. Run the recompiled routine on `cap/in` (the driver), `arek diff` the
   result against `cap/out`, restricted to the ranges the routine owns.
4. `arek.contract.untouched` for the ranges it must *not* write.

The driver takes the capture's custom registers from `$AREK_CREG` (`creg.bin`
of the capture), so a routine that reads INTENAR or DMACONR sees the original's
values. What the runtime does not model, the host answers: compile with
`-DHW_HOOK` (`hw_read_hook` for VPOSR, VHPOSR, INTREQR, JOYxDAT..., `hw_write_hook`
to observe every register write) and `-DCIA_HOOK` (every byte access to `$bfxxxx`).

Nothing "looks right"; it is equal or it is not.

For the whole game rather than one routine, put the translation into the kit's host
(`arek host copy`, `docs/HOST.md`): the bus model gives it the time, the host the frames, the
interrupts, the CIAs, Paula and the picture, and its driver writes the same records as the
original's trace. For a whole frame step rather than one routine, record the original with
`arek trace run` (one record per frame boundary, the chosen RAM ranges in
each), feed record *N* to the recompiled step and compare its RAM with record
*N + 1*, frame after frame. A step that matches for hundreds of frames, from
the trace's first record and in free run, is the evidence that the
translation is the game (the Alien Breed project does exactly this). Generated
C carries the kit version and the decoder/recompiler hashes in its first
line; `arek --version` and the MCP `kit_info` tool print them for the record.

**CIA reads are often the random seed.** A game that seeds its random numbers from a CIA counter (Superfrog reads
CIA-B TOD, `move.l $bfd802,d0`, at start) gives a translation without a CIA model different random timings from the
first frame on, and every later comparison drifts. `hwscan` lists the CIA accesses; compile the generated C with
`-DCIA_HOOK` and the host gets every byte access to `$bfxxxx` (`cia_read_hook(a)`, `cia_write_hook(a, v)`; CIA-A is
selected by A12 low on the odd bytes, CIA-B by A13 low on the even bytes, the register is `(a >> 8) & 15`). Feed the
seed from the capture (`arek bpstate` at the read) or model TOD as the emulator counts it. Without `-DCIA_HOOK` the
runtime is unchanged.

The seed is not the only trap: a generator that also runs in the title or demo loop advances once per pass while the
game waits for fire. To compare a level byte for byte, the harness presses fire at the same distance from the first
pass of that wait loop as the emulator recording did (`arek trace run --inputs`), and the generator state at the start
of the level then matches; check it before blaming the level code.

**A whole game, not one level.** The walker sees calls and branches; a game reaches the rest
through tables and stored addresses. `arek roots image.bin --base B --lo CODE --hi END` lists the
static roots: tables of `bra.w` slots, pointer tables into code, the bases `lea`/`pea` point at,
and `move.l #code,...` (a handler stored into a structure at run time). Give them to
`arek recomp --auto-file roots.txt --auto-soft`: a root that leads into data is dropped with a
note instead of refusing the translation. Then the coverage loop (Alien Breed II, 17 levels):
run the host with random play and level skips; every `unknown routine X` becomes a root and the
translation is rebuilt; an unknown module in an overlay area (`--overlay BASE:SIZE:KEY`) is
dumped from RAM by the host's `overlay_unknown_hook` (`-DOVERLAY_HOOK`) and translated as a
module (`arek recomp --lib --prefix --overlay-module ADDR:KEY`), registered under the fingerprint
of its first bytes at its own address, so modules may lie anywhere in the area. Disk reads go
through the host (`--extern READ_ROUTINE=host_disk_read` with the game's register convention),
so the data comes from the visitor's disk images at run time and never into the translation.

## 6. Reading the interpreters

Level maps, sprite formats, animation scripts: the same rule. Find the
routine that consumes the data (`arek xref --callers` on the data address
from `lea`), walk it, and write the decoder from the code. The three game
repositories hold worked examples (SWIV `.PAM` maps and `.LIN` sprites,
Turrican II level interpreter, Superfrog loader).

## 7. Verify against the real thing, not your eyes

`arek shot` takes deterministic screenshots from the headless emulator
(same script = bit-identical frame). Pixel checkpoints at known times, with
scripted input, catch regressions that no amount of looking will. SWIV ended
with eleven such checkpoints; Superfrog's audit (`arek audit`) records what
is proven and what is *not measured*, explicitly.

## What the kit refuses to do

* decode an instruction it does not model (raises `Unsupported`);
* follow an indirect jump it cannot resolve (reported as a frontier);
* claim a packed block without a passing checksum or full unpack;
* claim semantic parity from static coverage (`audit` reports
  `semantic_parity: not_measured`);
* include a byte of any game.

Those refusals are features: everything the kit says is backed by a
measurement, so a document built from its output can be trusted by someone
who has never seen the game.

The translation runtime's area blitter (run_blit): a modulo is a word quantity, its bit 0 is ignored as on the
hardware (DMOD $21 acts as $20 - Turrican II's intro logo, 1.0.9); in descending mode the pointers run down a row and
the modulo is subtracted at its end (HRM), ascending adds it.
