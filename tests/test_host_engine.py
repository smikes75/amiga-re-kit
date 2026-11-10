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


def test_threaded_engine_native_and_wasm(tmp_path):
    """--thread: the game in its own thread waits for each permit (a condition natively, a futex in wasm); the line equals
    the coroutine build's, and the Node check drives the wasm thread the same way."""
    if not bus.compiler():
        pytest.skip('no C compiler')
    build_state(tmp_path)
    kw = dict(src=str(tmp_path / 'externs.c'), defines=['HOST_L4=f_001180'])
    host.engine_build(str(tmp_path / 'n'), str(tmp_path / 'game.c'), 'f_001100', 'f_001000', native=True, **kw)
    host.engine_build(str(tmp_path / 't'), str(tmp_path / 'game.c'), 'f_001100', 'f_001000', native=True, thread=True, **kw)
    args = [str(tmp_path / 'state.bin'), '30', '--disk', '0', str(tmp_path / 'disk.adf')]
    want = subprocess.run([str(tmp_path / 'n' / 'arek_host_engine')] + args, capture_output=True, text=True, check=True, timeout=60).stdout.strip()
    got = subprocess.run([str(tmp_path / 't' / 'arek_host_engine_mt')] + args, capture_output=True, text=True, timeout=60)
    assert got.returncode == 0, got.stderr
    assert want.startswith('frames 30 ') and got.stdout.strip() == want
    cmd = host.engine_command(str(tmp_path / 'w'), str(tmp_path / 'game.c'), 'f_001100', 'f_001000', thread=True, **kw)
    assert '-pthread' in cmd and '-DENGINE_THREAD=1' in cmd and not any('ASYNCIFY' in x for x in cmd) and cmd[cmd.index('-o') + 1].endswith('engine_mt.js')
    if not (shutil.which('emcc') and shutil.which('node')):
        return
    host.engine_build(str(tmp_path / 'w'), str(tmp_path / 'game.c'), 'f_001100', 'f_001000', thread=True, **kw)
    r = subprocess.run(['node', os.path.join(HOST, 'arek_host_engine_check.js'), str(tmp_path / 'w'), str(tmp_path / 'state.bin'), '30',
                        str(tmp_path / 'disk.adf')], capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip().splitlines()[-1] == want


def test_threaded_engine_restart_starts_the_sound_count_again(tmp_path):
    """Xenon 2 KIT-GAP 16: the worklet turns the count of samples written into a place in the ring (count % n), so a restart
    (engine_stop, engine_init, engine_run) has to take the count back with the write position; the count read stays
    'none' until the worklet reads again, or the thread would see an old reserve."""
    if not (shutil.which('emcc') and shutil.which('node')):
        pytest.skip('no emcc + node')
    build_state(tmp_path)
    host.engine_build(str(tmp_path / 'w'), str(tmp_path / 'game.c'), 'f_001100', 'f_001000', thread=True, src=str(tmp_path / 'externs.c'), defines=['HOST_L4=f_001180'])
    script = tmp_path / 'drive.js'
    script.write_text('''
const fs = require('fs');
(async () => {
  const M = await require(%s)({ wasmBinary: fs.readFileSync(%s) });
  const st = fs.readFileSync(%s), p = M._engine_alloc(st.length); M.HEAPU8.set(st, p);
  const disk = fs.readFileSync(%s), q = M._engine_alloc(disk.length); M.HEAPU8.set(disk, q);
  const until = async (f) => { const t0 = Date.now(); while (!f() && Date.now() - t0 < 20000) await new Promise((r) => setTimeout(r, 1)); if (!f()) throw new Error('hung'); };
  const go = async (n) => { M._engine_set_disk(0, q, disk.length); M._engine_allow(0); if (M._engine_run()) throw new Error('run'); for (let f = 1; f <= n; f++) { M._engine_allow(f); await until(() => M._engine_done() >= f); } };
  const W = M._engine_aud_written() >> 2, R = M._engine_aud_read() >> 2;
  if (M._engine_init(p, st.length)) throw new Error('init');
  await go(40);
  const first = Atomics.load(M.HEAP32, W);
  Atomics.store(M.HEAP32, R, first - 720);                // the worklet's place when the page restarts
  M._engine_stop(); await until(() => M._engine_parked());
  if (M._engine_init(p, st.length)) throw new Error('init');
  console.log(Atomics.load(M.HEAP32, W), Atomics.load(M.HEAP32, R));
  await go(30);
  const n = M._engine_done(), last = n - 1, size = M._engine_aud_size();
  console.log(n, first, Atomics.load(M.HEAP32, W), size, (M._engine_fr_aud0(last) + M._engine_fr_naud(last)) %% size);
  process.exit(0);
})().catch((e) => { console.error(e); process.exit(1); });
''' % tuple(repr(str(x)) for x in (tmp_path / 'w' / 'engine_mt.js', tmp_path / 'w' / 'engine_mt.wasm', tmp_path / 'state.bin', tmp_path / 'disk.adf')))
    r = subprocess.run(['node', str(script)], capture_output=True, text=True, timeout=240)
    assert r.returncode == 0, r.stderr
    after, read = map(int, r.stdout.splitlines()[0].split())
    n, first, written, size, end = map(int, r.stdout.splitlines()[1].split())
    assert n == 30 and first > 0 and (after, read) == (0, -1)
    assert written % size == end and 0 < written < first


CIA_PROG = {
    MAIN: '4df900dff000'          # lea $dff000,a6
          '3d7cc020009a'          # move.w #$c020,$9a(a6)    INTENA: master + VERTB
          '13fc003200bfd400'      # loop: move.b #50,$bfd400  CIA-B TALO
          '13fc000000bfd500'      #       move.b #0,$bfd500   TAHI
          '13fc001900bfde00'      #       move.b #$19,$bfde00 CRA: START, ONESHOT, FORCE LOAD
          '0839000000bfdd00'      # w:    btst #0,$bfdd00     ICR: underflow?
          '67f6'                  #       beq.s w
          '52784000'              #       addq.w #1,$4000     counts the timer's rounds
          '60d8',                 #       bra.s loop
    L3: PROG[L3],
}


def test_cia_timers_past_2_31_e_ticks_in_wasm(tmp_path):
    """G47 (Alien Breed II): the E-tick count of the CIA timers passes 2^31 after ~151 000 frames; in wasm32 a `long`
    stopped the timers there. A state at frame 151 100 runs a game that waits on CIA-B timer A in a loop: the wasm build
    must give the native line (the hash covers the round counter)."""
    if not (shutil.which('emcc') and shutil.which('node') and bus.compiler()):
        pytest.skip('no emcc + node')
    img = bytearray(0x2000)
    for at, hx in CIA_PROG.items():
        img[at:at + len(hx) // 2] = bytes.fromhex(hx)
    src, _, _ = recomp.generate(bytes(img), 0, auto=[MAIN, L3], timing=True, bus_table=True)
    (tmp_path / 'game.c').write_text(src)
    st = tmp_path / 'state'
    st.mkdir()
    ram = bytearray(0x80000)
    ram[:len(img)] = img
    (st / 'chip.bin').write_bytes(ram)
    creg = bytearray(512)
    creg[0x96:0x98] = struct.pack('>H', 0x0200)
    (st / 'creg.bin').write_bytes(creg)
    (st / 'state.txt').write_text('0 0 0 0 0 0 0 0\n0 0 0 0 0 0 0 7f000\n2000 0 0 1000\nfe 0 0 0 0 5500\n151100\n')
    host.pack(str(st), str(tmp_path / 'state.bin'))
    host.engine_build(str(tmp_path / 'n'), str(tmp_path / 'game.c'), 'f_001100', 'f_001000', native=True)
    host.engine_build(str(tmp_path / 'w'), str(tmp_path / 'game.c'), 'f_001100', 'f_001000')
    want = subprocess.run([str(tmp_path / 'n' / 'arek_host_engine'), str(tmp_path / 'state.bin'), '60', '--dump', str(tmp_path / 'chip.bin')],
                          capture_output=True, text=True, check=True, timeout=60).stdout.strip()
    rounds = struct.unpack('>H', (tmp_path / 'chip.bin').read_bytes()[0x4000:0x4002])[0]
    assert want.startswith('frames 60 frame 151159') and rounds > 60 * 50                 # the timer runs: many rounds per frame
    r = subprocess.run(['node', os.path.join(HOST, 'arek_host_engine_check.js'), str(tmp_path / 'w'), str(tmp_path / 'state.bin'), '60'],
                       capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip().splitlines()[-1] == want


def test_engine_frame_record_hook(tmp_path):
    """1.0.16 (Turrican II M9): ENGINE_FRAME_RECORD(n) - the project's function runs once per finished frame, before the
    frame is published, so a scene record of frame n is complete when the page sees engine_done() > n."""
    if not bus.compiler():
        pytest.skip('no C compiler')
    build_state(tmp_path)
    (tmp_path / 'externs.c').write_text(EXTERNS + """
static int REC_N = 0, REC_LAST = -1, REC_ORDER_OK = 1;
static void my_record(int n) { if (n != REC_LAST + 1) REC_ORDER_OK = 0; REC_LAST = n; REC_N++;
    wr16_raw(0x4100, (uint16_t)REC_N); wr16_raw(0x4102, (uint16_t)REC_ORDER_OK); }
""")
    out = tmp_path / 'native'
    host.engine_build(str(out), str(tmp_path / 'game.c'), 'f_001100', 'f_001000', native=True, src=str(tmp_path / 'externs.c'),
                      defines=['HOST_L4=f_001180', 'ENGINE_FRAME_RECORD=my_record'])
    r = subprocess.run([str(out / 'arek_host_engine'), str(tmp_path / 'state.bin'), '5', '--dump', str(tmp_path / 'chip.bin')],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    chip = (tmp_path / 'chip.bin').read_bytes()
    assert struct.unpack('>HH', chip[0x4100:0x4104]) == (5, 1)       # five frames, each recorded in order before publishing


def test_node_harness_drives_both_wasm_builds(tmp_path):
    """arek_host_engine_node.js (1.0.20): the harness opens the coroutine build and the threaded build, schedules the
    check's keys as events at exact frames and prints the native build's check line; its synthState() writes the very
    bytes `arek host pack` writes."""
    if not (shutil.which('emcc') and shutil.which('node') and bus.compiler()):
        pytest.skip('no emcc + node')
    build_state(tmp_path)
    kw = dict(src=str(tmp_path / 'externs.c'), defines=['HOST_L4=f_001180'])
    host.engine_build(str(tmp_path / 'n'), str(tmp_path / 'game.c'), 'f_001100', 'f_001000', native=True, **kw)
    want = subprocess.run([str(tmp_path / 'n' / 'arek_host_engine'), str(tmp_path / 'state.bin'), '30', '--disk', '0', str(tmp_path / 'disk.adf')],
                          capture_output=True, text=True, check=True, timeout=60).stdout.strip()
    host.engine_build(str(tmp_path / 'wa'), str(tmp_path / 'game.c'), 'f_001100', 'f_001000', **kw)
    host.engine_build(str(tmp_path / 'wt'), str(tmp_path / 'game.c'), 'f_001100', 'f_001000', thread=True, **kw)
    script = tmp_path / 'drive.js'
    script.write_text('''
const fs = require('fs'); const H = require(%s);
(async () => {
  for (const dir of [%s, %s]) {
    const eng = await H.open(dir, { state: %s, disks: [%s], hash: true });
    for (let f = 0; f < 30; f++) eng.at(f, () => eng.keys(((f / 40) | 0) %% 2 ? 4 : 1));
    let seen = 0; const n = await eng.run(30, (f) => { seen = f; });
    console.log('frames ' + n + ' frame ' + eng.frameNo(n - 1) + ' hash ' + eng.hash());
    console.log('seen ' + seen + ' threaded ' + eng.threaded + ' cnt ' + eng.peek16(0x4000) + ' pix ' + eng.pix().w + 'x' + eng.pix().h);
  }
  fs.writeFileSync(%s, H.synthState({ chip: fs.readFileSync(%s), creg: fs.readFileSync(%s), a: [0, 0, 0, 0, 0, 0, 0, 0x7f000], sr: 0x2000, entry: 0x1000, frame: 100 }));
})();
''' % tuple(repr(str(x)) for x in (os.path.join(HOST, 'arek_host_engine_node.js'), tmp_path / 'wa', tmp_path / 'wt', tmp_path / 'state.bin', tmp_path / 'disk.adf',
                                   tmp_path / 'synth.bin', tmp_path / 'state' / 'chip.bin', tmp_path / 'state' / 'creg.bin')))
    r = subprocess.run(['node', str(script)], capture_output=True, text=True, timeout=240)
    assert r.returncode == 0, r.stderr
    lines = r.stdout.strip().splitlines()
    assert want.startswith('frames 30 ') and lines[0] == want and lines[2] == want, lines
    assert lines[1].startswith('seen 30 threaded false cnt ') and lines[3].startswith('seen 30 threaded true cnt ') and lines[1].endswith('pix ' + lines[1].split('pix ')[1])
    assert (tmp_path / 'synth.bin').read_bytes() == (tmp_path / 'state.bin').read_bytes()


TASKS = {
    MAIN: '4df900dff000'          # lea $dff000,a6
          '3d7cc020009a'          # move.w #$c020,$9a(a6)    INTENA: master + VERTB
          '52b84000'              # 100c: addq.l #1,$4000
          '60fa',                 # bra.s 100c
    0x1040: '52b84004'            # the other task: addq.l #1,$4004
            '60fa',               # bra.s 1040
    L3: '33fc002000dff09c'        # move.w #$20,$dff09c       clear VERTB
        '2b4f000e'                # move.l a7,14(a5)
        '2a55'                    # movea.l (a5),a5           the next task
        '2e6d000e'                # movea.l 14(a5),a7
        '4e73',                   # rte
    0x3000: '00003100',           # +0 next
    0x3100: '00003000',
    0x310e: '00004ffa',           # +14 saved a7: the start frame of the task not run yet
    0x4ffa: '200000001040',
}


def test_tasks_through_the_threaded_engine(tmp_path):
    """1.0.26 --resume in the build the pages use: a level-3 handler rte's into the other task, frame after frame. The
    C frames dropped are the game thread's; the Node check of the wasm thread must print the native line."""
    if not bus.compiler():
        pytest.skip('no C compiler')
    img = bytearray(0x5000)
    for at, hx in TASKS.items():
        img[at:at + len(hx) // 2] = bytes.fromhex(hx)
    src, _, _ = recomp.generate(bytes(img), 0, auto=[MAIN, 0x1040, L3], timing=True, bus_table=True, resume=True)
    (tmp_path / 'game.c').write_text(src)
    st = tmp_path / 'state'
    st.mkdir()
    ram = bytearray(0x80000)
    ram[:len(img)] = img
    (st / 'chip.bin').write_bytes(ram)
    creg = bytearray(512)
    creg[0x96:0x98] = struct.pack('>H', 0x0200)
    (st / 'creg.bin').write_bytes(creg)
    (st / 'state.txt').write_text('0 0 0 0 0 0 0 0\n0 0 0 0 0 3000 0 7f000\n2000 0 0 1000\nfe 0 0 0 0 5500\n100\n')
    host.pack(str(st), str(tmp_path / 'state.bin'))
    host.engine_build(str(tmp_path / 't'), str(tmp_path / 'game.c'), 'f_001100', 'f_001000', native=True, thread=True)
    dump = tmp_path / 'chip.bin'
    got = subprocess.run([str(tmp_path / 't' / 'arek_host_engine_mt'), str(tmp_path / 'state.bin'), '30', '--dump', str(dump)],
                         capture_output=True, text=True, timeout=60)
    assert got.returncode == 0, got.stderr
    assert got.stdout.strip().startswith('frames 30 ')
    mem = dump.read_bytes()
    assert int.from_bytes(mem[0x4000:0x4004], 'big') > 1000 and int.from_bytes(mem[0x4004:0x4008], 'big') > 1000
    if not (shutil.which('emcc') and shutil.which('node')):
        return
    host.engine_build(str(tmp_path / 'w'), str(tmp_path / 'game.c'), 'f_001100', 'f_001000', thread=True)
    r = subprocess.run(['node', os.path.join(HOST, 'arek_host_engine_check.js'), str(tmp_path / 'w'), str(tmp_path / 'state.bin'), '30'],
                       capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip().splitlines()[-1] == got.stdout.strip()


def _wasm(*sizes):
    def leb(v):
        out = bytearray()
        while True:
            c = v & 0x7f
            v >>= 7
            out.append(c | (0x80 if v else 0))
            if not v:
                return bytes(out)
    body = leb(len(sizes)) + b''.join(leb(n) + bytes(min(n, 8)) for n in sizes)
    return b'\0asm\1\0\0\0' + b'\x01' + leb(3) + bytes(3) + b'\x0a' + leb(len(body)) + body


def test_wasm_largest_function_and_the_second_build(tmp_path, monkeypatch):
    """1.0.26 (Xenon 2 KIT-GAP 5): one wasm function above V8's limit is built again without the inlining, once."""
    p = tmp_path / 'a.wasm'
    p.write_bytes(_wasm(5, 9, 3))
    assert host.wasm_largest_function(str(p)) == 9
    p.write_bytes(b'\0asm\1\0\0\0')
    assert host.wasm_largest_function(str(p)) == 0
    calls = []

    def fake(cmd, check=True):
        calls.append(cmd)
        out = cmd[cmd.index('-o') + 1]
        size = 5 if '-fno-inline-functions' in cmd else host.WASM_FUNCTION_LIMIT + 1
        (tmp_path / 'w' / os.path.basename(out.replace('.js', '.wasm'))).write_bytes(_wasm(size))
    monkeypatch.setattr(host.subprocess, 'run', fake)
    cmd = host.engine_build(str(tmp_path / 'w'), 'game.c', 'f_1', 'f_2')
    assert len(calls) == 2 and '-fno-inline-functions' in cmd and '-fno-inline-functions' not in calls[0]
