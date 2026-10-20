"""amiga-re-kit (``arek``) - tools for *measured* reverse engineering of Amiga games.

The package grew out of three game projects (S.W.I.V., Turrican II, Superfrog)
where the same scripts kept being copied around. Everything here is game
agnostic; game knowledge (addresses, catalogue layouts, packer variants)
lives in the per-game projects or in a *profile* JSON passed at run time.

Modules
-------
adf          ADF floppy images: bootblock checksum, DOS type, tracks, entropy map,
             packer signature scan
hunk         strict Amiga HUNK executable loader (fails on anything unknown)
packers      PowerPacker 2.0, Bytekiller (+ the SWIV "A" variant), Turrican II
             three-stage packer, brute-force scan for packed blocks
m68k         strict 68000 decoder, flow-graph walker, hardware-boundary scan,
             static recompiler to C, objdump cross references, reachability audit
copper       Copper list disassembler
headless     scripted headless vAmiga (screenshots, RAM + register capture at a
             breakpoint), plus the patches the headless build needs
contract     tiny framework for "verification contract" scripts
cli          ``arek`` command line
mcp_server   ``arek-mcp`` Model Context Protocol server
"""

__version__ = "0.2.1"
