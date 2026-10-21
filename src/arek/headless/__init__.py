"""Driving the patched headless vAmiga: config, screenshots, breakpoint captures.

The emulator is the measuring instrument; everything here only writes
RetroShell scripts and reads the results back. Nothing in this package knows
any game.
"""
from . import config, shot, bpstate, trace  # noqa: F401
