# The bus model per DMA slot (`arek.bus`, kit 0.5.15)

A recompiled game (path B) runs its logic from its own 68000 code, but *when* things happen inside a
frame - on which instruction the VBL interrupt lands, when a blit ends, whether the original ran over
the frame - depends on the Amiga's bus: every DMA slot of every line belongs to refresh, audio,
bitplanes, sprites, the copper, the blitter or the CPU. `src/arek/bus/` is a model of that bus, slot by
slot, extracted from the Alien Breed project (`docs/NATIVE.md` 5m there) where it took the rebuild's
logic on a long route from "mostly right" to 100 % of frames equal to the original.

| file | what | licence |
|---|---|---|
| `arek_bus.h`, `arek_bus.c` | API, state, the CPU (accesses into free slots), the current instruction, BLTSIZE / BBUSY, the start of a frame | MIT (the kit) |
| `arek_bus_vamiga.c` | the DMA map of a frame (refresh, sprites, bitplane order, the copper's state machine) and the blitter's microprograms (SlowBlitter) | **MPL-2.0, derived from vAmiga (Dirk W. Hoffmann)**, see THIRD-PARTY.md |
| `arek_bus_glue.h` | the model behind a kit translation's hooks (`-DTICK_HOOK -DBUS_HOOK`, `recomp --bus-table`) | MIT |
| `arek_bus_replay.c`, `arek_bus_check.c` | the blitter and the fixed DMA map against a recorded bus log (`arek selftest bus`) | MIT |

`arek bus copy DIR` puts them into a project. Nothing in them is from a game.

## What it does and does not

Input: the game's custom registers (the host's array; the model reads DMACON, BPLCON0, DDFSTRT/STOP,
DIWSTRT/STOP, SPRxPT, COP1LC, BLTxxx and writes the copper's DMACON writes back), the copper list in
chip RAM (through a read callback), and the CPU's instruction stream: per instruction its clocks, the
bus accesses it makes at once (prefetch) and the internal cycles before them; per operand access one
call. Output: `own[line * hpos + slot]` with the owner of every slot (codes as `VAHL_BUSLOG`), the
CPU's time after each call, `cop_int` (the slot of the copper's INTREQ write), BBUSY at a given
slot, counts of CPU accesses and waits.

Done: refresh (1/3/5/226), sprites (DMA from line 25, slots 0x15 + 4n), lores and hires bitplane
order within the 8-slot group from DDFSTRT to DDFSTOP for the lines of the display window, the
copper (reads on even free slots, WAIT with the comparator at h + 2, the blocked slot 0xE0,
registers it wrote last frame apply from the next), the blitter cycle by cycle for all 16 channel
combinations (STRT1/STRT2 wait for a free slot, the first D write is locked, BBUSY clears at the
last REPEAT), BLTPRI and the yield after two CPU waits (BLS), the CPU taking its slot after the
Agnus events of the cycle.

Not done: disk DMA, NTSC (227/228 alternating, 262/263 lines), DMA registers changed by the CPU in
the middle of a frame (the map is built at the frame's start; audio slots are the host's, see
`arek_bus_mark`), copper SKIP, the line and fill modes of the blitter (time only estimated), ECS/AGA.

## Geometry

Explicit, never a constant: `hpos` (PAL 227 slots - the bus log's arrays have 228 entries, entry 227
is never used), `lines` per frame (313 for a long frame, LOF = 1, which is what a cold VAHeadless
starts with - `arek selftest bus` sees 313; 312 after LOF was cleared - the Alien Breed and Superfrog
logs have 312), `maxlines` (capacity; lines past the frame hold the accesses that ran over),
`chipmask`. The host passes `lines` to `arek_bus_frame` every frame. Where the 312 comes from (Alien
Breed, measured from a cold start with `VAHL_REGLOG_POS`): the Kickstart writes VPOSW $8001 (LOF 1);
the game's loader then runs a copper list with BPLCON0 $C204 (hires, LACE) for exactly 205 frames, and
with LACE the emulator toggles LOF at the end of every frame - 205 is odd, so the game inherits LOF 0.
The length of a frame is a legacy of what ran before: take it from the record, never assume 313.

## API

```c
void   arek_bus_init(ArekBus *b, int hpos, int lines, int maxlines, uint8_t *own, uint16_t *regs, arek_bus_rd16_fn rd16, void *ctx);
void   arek_bus_frame(ArekBus *b, int lines);                       /* start of a frame: finish the blitter, build the DMA map */
double arek_bus_insn(ArekBus *b, double t, uint32_t cycles, uint32_t accesses, uint32_t pre);   /* an instruction starts */
double arek_bus_data(ArekBus *b, double t);                        /* one operand access to the chip bus */
double arek_bus_slow(ArekBus *b, double t, double cck);            /* an access off the chip bus (CIA, E clock) */
double arek_bus_insn_end(ArekBus *b, double t);                    /* the instruction's remaining internal cycles */
double arek_bus_blit(ArekBus *b, double t, uint16_t con0, uint16_t con1, uint16_t size);   /* BLTSIZE written */
int    arek_bus_bbusy(ArekBus *b, double t);
void   arek_bus_mark(ArekBus *b, uint32_t k, uint8_t who);         /* a slot of the host's own DMA model (audio) */
```

Time is the host's: a `double` in CCK slots from the start of the frame (the CPU counts internal
cycles in halves); every function takes the CPU's time and returns the new one, so the host can add
what the model does not know (interrupt entry, instructions without a table entry, disk waits).

## With a kit translation

`arek recomp ... --timing --bus-table` adds `BUS_TAB[(pc - BUS_LO) / 2] = {words, extra, flags}`
for every translated instruction (`arek.m68k.timing.bus_table_entry`): its words (each a prefetch
read), the accesses the 68000 makes that the translation does not (the prefetch after a jump, the
return address rts does not read, the read before clr, movem's extra read ...), and flags the glue
resolves from the clock count at run time (a taken short branch and an expired dbcc read one more
word; jumps spend their internal cycles before their accesses; -(An) and d8(An,Xn) wait 2 cycles;
jsr/bsr push two words after). The runtime always has the hooks `BUS_ACCESS` (every CPU access to
the chip bus, in rd8/rd16/wr8/wr16), `BUS_BLIT` (BLTSIZE) and `BUS_BBUSY` (DMACONR bit 14); they are
empty unless the translation is built with `-DBUS_HOOK`.

```c
/* game.c = arek recomp --timing --bus-table ... ; then once: */
#include "arek_bus_glue.h"
static uint8_t OWN[313 * 227]; static uint16_t REGS[0x100];
arek_glue_init(227, 313, 313, OWN, REGS, my_rd16, ctx);        /* REGS: the custom registers as the host keeps them */
/* per frame */
arek_glue_frame(lines);                                          /* the CPU's time wraps; an overrun carries over */
run_frame(&m);                                                   /* the translated frame routine; the hooks move the time */
if (arek_glue_time() >= lines * 227) /* the original would not have finished this frame */;
```

Build with `cc -DTICK_HOOK -DBUS_HOOK -I lib game.c lib/arek_bus.c lib/arek_bus_vamiga.c`. The
verification driver then reports `bus <time>` in its log. The host decides what an interrupt does
with the time (the VBL is the frame boundary; `cop_int` is the copper's): the entry costs 44 clocks with
7 bus accesses (`arek_glue_interrupt()`: 3 stack writes, 2 vector reads, 2 prefetches compete for slots),
the handler's instructions count like any others. A host with its own
`tick_hook` defines `AREK_GLUE_NO_TICK` and calls `arek_glue_insn(pc, clocks)` from it. The runtime's
blitter (`run_blit`) moves its words raw - they are the blitter's slots in the model, not CPU accesses
(Superfrog found 0.5.15 counting them: KIT-GAPS 28; 0.5.17 then moved movem.w and rte's SR read raw by
mistake, 0.5.18 counts them again: KIT-GAPS 29 - the extension words an indirect jump re-reads stay raw,
they are prefetch and in BUS_TAB). Audio DMA slots come from the host's Paula model (`arek_bus_mark`).

## Measured

- `arek selftest bus` (a synthetic program: 5 lores planes, a sprite, a copper list with waits,
  three blits in a loop with BLTPRI and stack traffic between them; VAHeadless 899da5d with the
  kit's patches): **120 frames, fixed DMA slots 2 560 080 agree / 0 disagree; 2 442 blits all end on
  the slot of the log; blitter slots 3 646 720 agree / 0 disagree.** Without BLTPRI the CPU polling
  BBUSY makes the blitter yield every few slots; the replay frees the CPU's slots and cannot
  reproduce that, so the self-test keeps BLTPRI on, as games do around their blits.
- Alien Breed SE92 (the project the model came from, 2026-10-25): extracted without a change of
  behaviour (24 342 frames of recorded model calls replayed, 0 different); the blitter against the
  bus log of level 2: 47 540 blits end on the same slot, 7 017 630 blitter slots equal; the rebuild's
  logic 100 % of frames on the long2 route, RAM 99.99 %.
- Cost: native ~0.47 ms per frame of a game (8.7 million instructions/s); in WebAssembly inside the
  Alien Breed core ~0.65 ms per frame on an M-series Mac. A rebuild on a slow PC must measure its
  own budget before it makes the model its default.

## Calibration (where the constants come from)

| constant | value | from |
|---|---|---|
| refresh | slots 1, 3, 5, hpos - 1 | vAmiga, bus log |
| sprites | DMA from line 25, slots 0x15 + 4n and 0x17 + 4n | vAmiga, bus log |
| bitplanes lores | planes in the 8-slot group at 7/3/5/1/6/2, DDFSTRT to DDFSTOP | vAmiga SequencerBpl, bus log |
| bitplanes hires | 4/2/3/1 twice per group | vAmiga |
| copper | reads on even free slots, next step 2 slots later, WAIT compares h + 2, slot 0xE0 blocked | vAmiga CopperEvents, bus log |
| blitter | SlowBlitter microprograms for 16 channel sets; STRT1/STRT2 wait for a free slot; first D write locked; BBUSY clears at the last REPEAT | vAmiga, `arek selftest bus`, Alien Breed |
| CPU | its slot 1 cycle after the bus cycle starts (Moira SYNC), an access 2 slots, internal cycles = (clocks - pre - 4 * accesses) / 2 slots | Moira, Alien Breed |
| BLS | after 2 slots of CPU waiting the blitter yields without BLTPRI | vAmiga, Alien Breed |
| the CPU takes its slot after the Agnus events of the cycle | the blitter sees CPU slots as free | Alien Breed (replay: otherwise no match) |
