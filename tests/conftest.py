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


# --- 1.0.41: markers and required tools --------------------------------------------------------------------------
# browser: the test drives a browser through playwright (minutes for the whole set); timing: it holds wall-clock
# behaviour to a limit (dropped frames, jitter, latency) and can fail on a loaded machine. Both are set from the
# test's own source, so a new test needs no decoration:  pytest -m "not browser"  is the fast suite.
# AREK_REQUIRE_TOOLS=1 (CI): a test skipped for want of a C compiler or node FAILS - a suite that skips its core
# without a word is green for the wrong reason.
import inspect
import os

_REQUIRED = ('no C compiler', 'no node')


def pytest_collection_modifyitems(config, items):
    for item in items:
        try:
            src = inspect.getsource(item.function)
        except (OSError, TypeError, AttributeError):
            continue
        if 'playwright' in src or 'websmooth' in src or 'webreplay' in src or 'webtest.run' in src:
            item.add_marker(pytest.mark.browser)
        if 'websmooth' in src or 'smooth' in item.name or 'latency' in item.name:
            item.add_marker(pytest.mark.timing)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    if rep.skipped and os.environ.get('AREK_REQUIRE_TOOLS') and not hasattr(rep, 'wasxfail'):
        reason = rep.longrepr[2] if isinstance(rep.longrepr, tuple) else str(rep.longrepr)
        if any(r in reason for r in _REQUIRED):
            rep.outcome = 'failed'
            rep.longrepr = 'AREK_REQUIRE_TOOLS: %s' % reason
