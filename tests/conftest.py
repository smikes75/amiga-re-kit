import random
import struct

import pytest


@pytest.fixture
def rnd():
    r = random.Random(1234)
    return lambda n: bytes(r.getrandbits(8) for _ in range(n))


# A tiny hand-assembled 68000 program (big endian words). Addresses are
# relative to BASE. No game code anywhere in the tests.
BASE = 0x1000
CODE = bytes.fromhex(
    '7005'          # 1000 moveq  #5,d0
    '4e75'          # 1002 rts
    '41f900002000'  # 1004 lea    $2000.l,a0
    '3080'          # 100a move.w d0,(a0)
    '4e75'          # 100c rts
    '6100fff6'      # 100e bsr    $1006?  -> fixed below
    '4e75'
)
# bsr target: 0x100e+2 + disp; we want 0x1004 => disp = 0x1004-0x1010 = -0xc = 0xfff4
CODE = CODE[:0x0e] + bytes.fromhex('6100fff4') + CODE[0x12:]


@pytest.fixture
def code():
    return BASE, CODE


def be(*words):
    return b''.join(struct.pack('>H', w) for w in words)
