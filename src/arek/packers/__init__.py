"""Decrunchers for packers met on Amiga game disks, plus a signature scanner.

pp20        PowerPacker 2.0 (``PP20`` magic)
bytekiller  Bytekiller (format B) and the S.W.I.V. variant (format A)
turrican2   Turrican II: Huffman -> backwards LZ -> RLE
scan        brute-force scan of an image for packed blocks
"""
from . import pp20, bytekiller, turrican2, scan  # noqa: F401
