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

`arek scan` finds packers. A *signature* (PP20, RNC, ATN!, IMP!, …) is a hint;
a *verified* Bytekiller block (header plausible, XOR checksum zero, full
unpack succeeds) is evidence. When neither fires, the game has its own
packer — read the decrunch routine (it is always short, always near the
loader) and re-implement it. `arek.packers` holds three such
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

With `--main` the C file gets a driver: *RAM dump + registers in → routine →
RAM dump + write log out*. That is the verification loop:

1. `arek bpstate --address ENTRY --out cap/in` — the original, stopped at
   the routine entry (registers, beam position, chip RAM).
2. `arek bpstate --address RTS_ADDR --out cap/out` — same run, stopped at
   its return.
3. Run the recompiled routine on `cap/in` (the driver), `arek diff` the
   result against `cap/out`, restricted to the ranges the routine owns.
4. `arek.contract.untouched` for the ranges it must *not* write.

Nothing "looks right"; it is equal or it is not.

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
