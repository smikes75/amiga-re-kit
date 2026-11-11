"""1.0.53: drive DF0 and the disk controller (arek_host_floppy.h, -DHOST_FLOPPY=1) - a game that reads the disk with its
own loader. Synthetic: a random disk image, a loader of forty instructions."""
import os
import random
import struct
import subprocess

import pytest

from arek import bus, host
from arek.headless import trace
from arek.m68k import recomp

HOST = os.path.dirname(host.__file__)
BUS = os.path.dirname(bus.__file__)

LOADER = (
    '4df900dff000'              # 1000 lea $dff000,a6
    '41f900bfd100'              # 1006 lea $bfd100,a0          CIA-B PRB
    '10bc007f'                  # 100c move.b #$7f,(a0)        /MTR low
    '10bc0077'                  # 1010 move.b #$77,(a0)        /SEL0 low: the motor is latched on
    '0839000500bfe001'          # 1014 btst #5,$bfe001         /RDY?
    '66f6'                      # 101c bne.s 1014
    '3d7c4489007e'              # 101e move.w #$4489,$7e(a6)   DSKSYNC
    '3d7c9500009e'              # 1024 move.w #$9500,$9e(a6)   ADKCON: SET MFMPREC WORDSYNC FAST
    '3d7c82100096'              # 102a move.w #$8210,$96(a6)   DMACON: SET DMAEN DSKEN
    '2d7c000100000020'          # 1030 move.l #$10000,$20(a6)  DSKPT
    '3d7c0002009c'              # 1038 move.w #2,$9c(a6)       INTREQ: clear DSKBLK
    '3d7c40000024'              # 103e move.w #$4000,$24(a6)   DSKLEN: off
    '3d7c87000024'              # 1044 move.w #$8700,$24(a6)
    '3d7c87000024'              # 104a move.w #$8700,$24(a6)   twice: the read starts ($700 words)
    '082e0001001f'              # 1050 btst #1,$1f(a6)         INTREQR: DSKBLK?
    '67f8'                      # 1056 beq.s 1050
    '3d7c40000024'              # 1058 move.w #$4000,$24(a6)
    '4e71'                      # 105e nop                     the tick: once
    '52b84010' '60fa'           # 1060 addq.l #1,$4010; bra.s 1060
)


def _mfm_long(buf, at):
    odd, even = struct.unpack('>II', buf[at:at + 8])
    return ((odd & 0x55555555) << 1) | (even & 0x55555555)


def _sectors(buf):
    """{sector: 512 bytes} of the AmigaDOS sectors whole in a buffer of MFM words (after a sync word each)."""
    out, i = {}, 0
    while i + 1088 <= len(buf):
        if buf[i:i + 2] != b'\x44\x89':
            i += 2
            continue
        while buf[i:i + 2] == b'\x44\x89':
            i += 2
        if i + 1080 > len(buf):
            break
        info = _mfm_long(buf, i)
        data = bytearray(512)
        for k in range(0, 512, 4):
            o = struct.unpack('>I', buf[i + 56 + k:i + 60 + k])[0]
            e = struct.unpack('>I', buf[i + 56 + 512 + k:i + 60 + 512 + k])[0]
            data[k:k + 4] = struct.pack('>I', ((o & 0x55555555) << 1) | (e & 0x55555555))
        out[(info >> 8) & 0xff] = (info, bytes(data))
        i += 1080
    return out


def test_a_loader_reads_a_track_through_the_controller(tmp_path):
    cc = bus.compiler()
    if not cc:
        pytest.skip('no C compiler')
    rnd = random.Random(7)
    adf = bytes(rnd.randrange(256) for _ in range(901120))
    (tmp_path / 'disk.adf').write_bytes(adf)
    img = bytearray(0x2000)
    img[0x1000:0x1000 + len(LOADER) // 2] = bytes.fromhex(LOADER)
    img[0x1100:0x1102] = bytes.fromhex('4e73')
    src, _, _ = recomp.generate(bytes(img), 0, auto=[0x1000, 0x1100], timing=True, bus_table=True)
    (tmp_path / 'game.c').write_text(src)
    exe = tmp_path / 'host_trace'
    subprocess.run([cc, '-O1', '-I', BUS, '-I', HOST, '-I', str(tmp_path), '-DGAME_SRC="game.c"', '-DTICK_PC=0x105eu', '-DHOST_IPL_MODEL=1',
                    '-DHOST_FLOPPY=1', '-DHOST_ENTRY=f_001000', '-DHOST_L3=f_001100', os.path.join(HOST, 'arek_host_trace.c'),
                    os.path.join(BUS, 'arek_bus.c'), os.path.join(BUS, 'arek_bus_vamiga.c'), '-lm', '-o', str(exe)], check=True)
    st = tmp_path / 'state'
    st.mkdir()
    ram = bytearray(0x80000)
    ram[:len(img)] = img
    (st / 'chip.bin').write_bytes(ram)
    (st / 'slow.bin').write_bytes(bytes(0x80000))
    (st / 'creg.bin').write_bytes(bytes(512))
    (st / 'state.txt').write_text('0 0 0 0 0 0 0 0\n0 0 0 0 0 0 0 7f000\n2700 0 0 1000\nfe 0 0 0 0 5500\n100\n')
    out = tmp_path / 'o.vtr'
    env = dict(os.environ, HOST_ADF0=str(tmp_path / 'disk.adf'))
    r = subprocess.run([str(exe), str(st), str(out), '40', '--full'], capture_output=True, text=True, timeout=120, env=env)
    assert r.returncode == 0, r.stderr
    recs = [x for x in trace.records(str(out)) if x['pc'] == 0x105e]
    assert len(recs) == 1, (len(recs), r.stderr[-300:])
    rec = recs[0]
    t = (rec['frame'] - 100) * 313 * 227 + rec['v'] * 227 + rec['h']                # colour clocks from the start
    spin = 380e-3 * 28e6 / 8                                                         # the motor: 380 ms
    words = 0x700 * 55.2573 * 2                                                      # $700 words at the disk's speed
    assert spin < t < spin + 12668 * 55.2573 + words + 3000, (t, spin, words)        # at most one turn to the first sync
    buf = rec['ranges'][0][0x10000:0x10000 + 0x700 * 2]
    got = _sectors(buf)
    assert len(got) >= 2, sorted(got)                                                # $E00 bytes hold two or three sectors whole
    for s, (info, data) in got.items():
        assert info >> 24 == 0xff and (info >> 16) & 0xff == 0 and info & 0xff == 11 - s, hex(info)      # track 0, sectors to the gap
        assert data == adf[s * 512:(s + 1) * 512], s
    assert rec['ranges'][0][0x10000 + 0x700 * 2:0x10000 + 0x700 * 2 + 8] == bytes(8)                     # not a word more
