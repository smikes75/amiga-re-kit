"""arek_host_engine.c + arek_host_disk.h on a synthetic game: the game reads two sectors through an extern routine
(AHD_EXTERN) and then waits for the frame counter a level-3 handler bumps (the handler itself holds a wait loop, where
an ASYNCIFY build with indirect calls ignored must still be able to sleep - G37); the native build runs N frames and
prints the check line; the Emscripten build (when emcc and node are here) must print the same line from the page's side."""
import os
import shutil
import struct
import subprocess

import pytest

from arek import bus, host
from arek.m68k import recomp

HOST = os.path.dirname(os.path.abspath(host.__file__))
MAIN, READ, L3, L4 = 0x1000, 0x1200, 0x1100, 0x1180
PROG = {
    MAIN: '4df900dff000'          # lea $dff000,a6
          '3d7cc020009a'          # move.w #$c020,$9a(a6)    INTENA: master + VERTB
          '7800'                  # moveq #0,d4              disk 0
          '323c0003'              # move.w #3,d1             sector 3
          '343c0002'              # move.w #2,d2             two sectors
          '41f85000'              # lea $5000.w,a0
          '4eb900001200'          # jsr $1200                the game's read routine (extern)
          '52784000'              # loop: addq.w #1,$4000    no wait loop here: the only one is in the handler
          '60fa',                 #       bra.s loop
    L3: '52784002'                # addq.w #1,$4002
        '33fc002000dff09c'        # move.w #$20,$dff09c       clear VERTB
        '123900dff006'            # move.b $dff006,d1         the game's only wait loop, inside the handler (until the
        'b23900dff006'            # w: cmp.b $dff006,d1       line changes): the engine sleeps here, so the host must
        '67f8'                    #    beq.s w                call the handler directly (ASYNCIFY_IGNORE_INDIRECT, G37)
        '4e73',                   # rte
    L4: '4e73',                   # a second handler (never raised): two call sites keep the entry helper out of line
}
EXTERNS = '''
AHD_EXTERN(game_read, m->d[4], (int16_t)m->d[1], (uint16_t)m->d[2], m->a[0])
'''


def build_state(tmp_path):
    img = bytearray(0x2000)
    for at, hx in PROG.items():
        img[at:at + len(hx) // 2] = bytes.fromhex(hx)
    flow = recomp.flow_from_specs(bytes(img), 0, extern=['1200=game_read'])
    src, _, _ = recomp.generate(bytes(img), 0, auto=[MAIN, L3, L4], timing=True, bus_table=True, flow=flow)
    assert 'game_read(m)' in src
    (tmp_path / 'game.c').write_text(src)
    (tmp_path / 'externs.c').write_text(EXTERNS)
    st = tmp_path / 'state'
    st.mkdir()
    ram = bytearray(0x80000)
    ram[:len(img)] = img
    (st / 'chip.bin').write_bytes(ram)
    creg = bytearray(512)
    creg[0x96:0x98] = struct.pack('>H', 0x0200)
    (st / 'creg.bin').write_bytes(creg)
    (st / 'state.txt').write_text('0 0 0 0 0 0 0 0\n0 0 0 0 0 0 0 7f000\n2000 0 0 1000\nfe 0 0 0 0 5500\n100\n')
    n = host.pack(str(st), str(tmp_path / 'state.bin'))
    assert n == 11 + 0x100000 + 0x200 + len((st / 'state.txt').read_bytes()) + 1
    adf = bytes(((i * 7) ^ (i >> 9)) & 0xff for i in range(80 * 2 * 11 * 512))
    (tmp_path / 'disk.adf').write_bytes(adf)
    return adf


def test_native_engine_reads_the_disk_and_runs_frames(tmp_path):
    if not bus.compiler():
        pytest.skip('no C compiler')
    adf = build_state(tmp_path)
    out = tmp_path / 'native'
    cmd = host.engine_build(str(out), str(tmp_path / 'game.c'), 'f_001100', 'f_001000', native=True, src=str(tmp_path / 'externs.c'), defines=['HOST_L4=f_001180'])
    assert '-DENGINE_SRC="externs.c"' in cmd and (out / 'arek_host_engine').exists()
    r = subprocess.run([str(out / 'arek_host_engine'), str(tmp_path / 'state.bin'), '5', '--disk', '0', str(tmp_path / 'disk.adf'),
                        '--shot', str(tmp_path / 'shot.raw'), '--dump', str(tmp_path / 'chip.bin')], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    words = r.stdout.split()
    assert words[:4] == ['frames', '5', 'frame', '104'] and words[4] == 'hash' and len(words[5]) == 16
    chip = (tmp_path / 'chip.bin').read_bytes()
    assert chip[0x5000:0x5400] == adf[3 * 512:5 * 512]                 # the two sectors landed at A0
    assert chip[0x5400:0x5410] == bytes(16) and struct.unpack('>H', chip[0x4002:0x4004])[0] == 5   # VERTB from the second frame on; the fifth handler counts before it sleeps
    assert (tmp_path / 'shot.raw').stat().st_size == 716 * 285 * 3
    (tmp_path / 'hash.txt').write_text(r.stdout)
    # the same run without the disk: the read fails (D0 = -1), the game goes on
    r2 = subprocess.run([str(out / 'arek_host_engine'), str(tmp_path / 'state.bin'), '5'], capture_output=True, text=True, timeout=60)
    assert r2.returncode == 0 and r2.stdout.split()[:4] == ['frames', '5', 'frame', '104'] and r2.stdout.split()[5] != words[5]


def test_wasm_engine_prints_the_same_line(tmp_path):
    if not (shutil.which('emcc') and shutil.which('node') and bus.compiler()):
        pytest.skip('no emcc + node')
    build_state(tmp_path)
    native = tmp_path / 'native'
    host.engine_build(str(native), str(tmp_path / 'game.c'), 'f_001100', 'f_001000', native=True, src=str(tmp_path / 'externs.c'), defines=['HOST_L4=f_001180'])
    want = subprocess.run([str(native / 'arek_host_engine'), str(tmp_path / 'state.bin'), '50', '--disk', '0', str(tmp_path / 'disk.adf')],
                          capture_output=True, text=True, check=True, timeout=60).stdout.strip()
    out = tmp_path / 'wasm'
    cmd = host.engine_build(str(out), str(tmp_path / 'game.c'), 'f_001100', 'f_001000', src=str(tmp_path / 'externs.c'), defines=['HOST_L4=f_001180'])
    assert cmd[0] == 'emcc' and (out / 'engine.js').exists() and (out / 'engine.wasm').exists()
    r = subprocess.run(['node', os.path.join(HOST, 'arek_host_engine_check.js'), str(out), str(tmp_path / 'state.bin'), '50',
                        str(tmp_path / 'disk.adf')], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    assert want.startswith('frames 50 frame 149 hash ') and r.stdout.strip().splitlines()[-1] == want


def test_pack_and_cli(tmp_path):
    st = tmp_path / 'st'
    st.mkdir()
    (st / 'chip.bin').write_bytes(b'\x01' * 0x80000)
    (st / 'creg.bin').write_bytes(b'\x02' * 0x200)
    (st / 'state.txt').write_text('0 0 0 0 0 0 0 0\n0 0 0 0 0 0 0 0\n2000 0 0 1000\n')
    from arek import cli
    assert cli.main(['host', 'pack', str(st), str(tmp_path / 's.bin')]) == 0
    b = (tmp_path / 's.bin').read_bytes()
    assert b[:11] == host.STATE_MAGIC and b[11] == 1 and b[11 + 0x80000] == 0 and b[11 + 0x100000] == 2 and b.endswith(b'1000\n\0')
    cmd = host.engine_command(str(tmp_path), 'g/game.c', 'f_1', 'f_2', dynamic=True, ovl='o/ovl.c', defines=['X=1'])
    assert cmd[0] == 'emcc' and '-DENGINE_DYNAMIC=1' in cmd and '-DOVL_SRC="ovl.c"' in cmd and '-DX=1' in cmd and '-DENGINE_ASYNC=1' in cmd
    assert any(x.startswith('EXPORTED_FUNCTIONS=') and '"_engine_run"' in x and '"_malloc"' in x for x in cmd)
    assert cli.main(['host', 'engine', str(tmp_path), '--game', 'g/game.c', '--l3', 'f_1', '--entry', 'f_2', '--native']) == 0
