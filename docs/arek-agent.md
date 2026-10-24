# arek: a brief for an AI agent

You are helping reverse engineer an Amiga floppy game with **amiga-re-kit** (the `arek`
command and the `arek-mcp` server). Read this whole file before touching anything. Put it
in the project folder as `CLAUDE.md` (Claude Code reads it on start), or paste it into the
first message of any coding agent.

## Rules

1. **The original is the only source of truth.** Every claim is a measurement: an address,
   a hash, a diff, a screenshot. Never guess from the game's name, from a video or from
   what you remember about the game.
2. **Game data stays out of the repository.** No `.adf`, no Kickstart ROM, no memory dumps,
   no extracted graphics in git. Paths to them live only in the git-ignored `local.conf`;
   extracted data goes under `build/` (git-ignored).
3. **Never modify the disk image.** Read it; work on copies.
4. **Write down what you measured, with the exact command**, so that someone who has never
   seen the game can repeat it. Record the kit version and the decoder hash (`kit_info`,
   `arek --version`) next to the measurements.
5. **When a tool refuses, stop and report.** The decoder raises on an instruction it does
   not model, an unpacker refuses a block that does not verify: that is a result, not an
   obstacle. Do not work around it with a guess. Note it in `docs/KIT-GAPS.md` with the
   smallest input that reproduces it.

## Setup (once)

- `pip install "amiga-re-kit[mcp]"` (Python 3.11 or newer). `arek --help` lists the
  commands; `arek <command> --help` the options.
- `arek init .` creates `local.conf` and `.gitignore`. Put the path to the disk image
  into `ADF1=` (`ADF2=` for a second disk). Ask the user for it; do not search the disk
  for it.
- MCP: a `.mcp.json` in the project with
  `{ "mcpServers": { "arek": { "command": "arek-mcp" } } }` gives you the same instruments
  as tools (26). Call `kit_info` first.
- Optional, for measurements against the running game: a headless vAmiga build
  (`docs/HEADLESS.md` in the kit) and a Kickstart ROM the user owns; `VAHL=` and `ROM=` in
  `local.conf`. Without them, steps 0 to 4 below still work.

## Workflow, in this order

0. **Inventory.** `arek adf info <adf>`: size, SHA-256, boot block type and checksum. Write
   the hash into `docs/disk.md`; every later claim refers to this exact image. Cracked
   images differ from each other.
1. **Look before reading.** `arek adf map <adf>` and `arek adf regions <adf>`: where code,
   packed data, graphics and empty sectors sit. Describe the disk before decoding one
   instruction.
2. **Boot chain.** `arek dis <adf> --base 0 --walk 0xc` lists what the boot block reaches;
   follow the loader to the next stage (`arek adf track`, `arek adf sector`). An AmigaDOS
   disk: `arek adf ls`, `arek adf cat`, `arek adf extract`.
3. **Packers.** `arek scan <file>` finds known signatures and Bytekiller blocks verified by
   unpacking; `arek pp20`, `arek bytekiller`, `arek atn`, `arek t2` unpack them. An unknown
   packer means reading the decrunch routine next to the loader, not guessing a format.
4. **Code.** `arek walk --base <addr> --start <entry>` follows the flow graph and reports
   its frontiers; `arek hwscan` separates pure-RAM routines from those that drive Agnus,
   Denise and Paula; `arek xref` says who reads and writes what; `arek hunk` reads AmigaDOS
   executables; `arek copper` disassembles copper lists.
5. **Recompile and verify.** `arek recomp --base <addr> --func <start:end>` turns one
   routine into C with a verification driver. Run it on a RAM capture of the original
   (`arek bpstate`) and compare with `arek diff`. Equal, or not done. `arek recomp
   --profile` says which routines matter for performance.
6. **Check against the real thing.** `arek shot` takes deterministic screenshots at known
   frames with scripted input; `arek trace` records registers, inputs and bus activity;
   `arek render` draws a frame from chip RAM so it can be compared pixel for pixel.

## What to deliver

- `docs/disk.md`: inventory, map, regions, packers found, boot chain, each with the command
  and its result.
- `docs/code.md`: routines found, the hardware boundary, what is verified and how.
- `docs/KIT-GAPS.md`: what the kit could not do, with a reproducible input.
- A short list of open questions for the user: which disk version, which ROM, what to
  rebuild first.

Report in the user's language, keep commands and file names exactly as run, and say
clearly what is measured and what is still open.
