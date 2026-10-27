"""Code loaded at run time: overlay areas, modules recognised by fingerprint, run-time targets."""
import subprocess

import pytest

from arek import cli
from arek.m68k import recomp
from arek.m68k.decoder import Flow, walk

from test_recomp_semantics import run

# main at $1000: jsr $2000.w (the overlay area) ; movea.l #$1010,a0 ; jsr (a0) (dynamic) ; rts ; nop
#                $1010: addq.l #4,d1 ; rts
MAIN = '4eb82000' '207c00001010' '4e90' '4e75' '4e71' '5881' '4e75'
MOD_A, MOD_B, MOD_X = bytes.fromhex('70014e75'), bytes.fromhex('70024e75'), bytes.fromhex('70034e75')
MAIN_FLOW = Flow(overlays=[(0x2000, 0x100, 4)], dynamic={0x100a})


def module(code, name):
    src, _, _ = recomp.generate(code, 0x2000, auto=[0x2000],
                                flow=Flow(prefix=(name, 0x2000, 0x2100), lib=True, module=(0x2000, 4)))
    return src


def test_walk_treats_overlay_calls_and_dynamic_sites_as_known():
    p = bytes.fromhex(MAIN)
    ins, calls, bad, ind = walk(p, 0x1000, 0x1000, 0x1000, 0x1000 + len(p), MAIN_FLOW)
    assert not ind and not bad and calls == set()
    ins, calls, bad, ind = walk(p, 0x1000, 0x1000, 0x1000, 0x1000 + len(p))
    assert ind == [(0x100a, 'jsr (a0)')] and 0x2000 in calls


@pytest.mark.parametrize('loaded, d0', [(MOD_A, 1), (MOD_B, 2)])
def test_the_module_in_the_area_runs(tmp_path, loaded, d0):
    extra = '\n' + module(MOD_A, 'ovA_') + '\n' + module(MOD_B, 'ovB_')
    d, *_ = run(tmp_path, MAIN, {}, auto=(0x1000, 0x1010), flow=MAIN_FLOW, extra_c=extra,
                ram_init={0x2000: loaded})
    assert d[0] == d0 and d[1] == 4                        # the module ran; call_addr reached $1010


def test_an_unknown_module_stops_with_its_fingerprint(tmp_path):
    from arek.headless.trace import fnv1a64
    extra = '\n' + module(MOD_A, 'ovA_')
    with pytest.raises(subprocess.CalledProcessError) as e:
        run(tmp_path, MAIN, {}, auto=(0x1000, 0x1010), flow=MAIN_FLOW, extra_c=extra, ram_init={0x2000: MOD_X})
    assert e.value.returncode == 5
    src = module(MOD_A, 'ovA_')
    assert '0x%016xull' % fnv1a64(MOD_A) in src and 'ovl_ovA__register' in src and ', 0x2000u, 4u); }' in src


def test_module_anywhere_in_a_larger_area_and_the_unknown_hook(tmp_path):
    """The area starts below the module (Alien Breed II: area $40000, module at $4D270): the module is found by the
    fingerprint at its own base; an unknown module goes to overlay_unknown_hook when the host defines OVERLAY_HOOK."""
    big = Flow(overlays=[(0x1f00, 0x400, 4)], dynamic={0x100a})
    extra = '\n' + module(MOD_A, 'ovA_')
    d, *_ = run(tmp_path, MAIN, {}, auto=(0x1000, 0x1010), flow=big, extra_c=extra, ram_init={0x2000: MOD_A})
    assert d[0] == 1
    hook = extra + '\nvoid overlay_unknown_hook(M68 *m, uint32_t base, uint32_t entry, uint64_t fp) { m->d[0] = 0x50 + (base == 0x1f00u) + (entry == 0x2000u) * 2 + (fp != 0) * 4; }\n'
    d, *_ = run(tmp_path, MAIN, {}, auto=(0x1000, 0x1010), flow=big, extra_c=hook, ram_init={0x2000: MOD_X}, pre_c='#define OVERLAY_HOOK 1\n')
    assert d[0] == 0x57 and d[1] == 4                      # the hook saw the area, the entry and a fingerprint; the run went on


def test_flow_specs_and_cli(tmp_path):
    fl = recomp.flow_from_specs(b'', 0, overlay=['2000:100:4', '41d5c:b000'], dynamic=['100a'], module='2000:16')
    assert fl.overlays == [(0x2000, 0x100, 4), (0x41d5c, 0xb000, 256)] and fl.dynamic == {0x100a}
    assert fl.module == (0x2000, 16) and fl.overlay_of(0x2050) == (0x2000, 0x100, 4) and fl.overlay_of(0x1fff) is None
    f = tmp_path / 'm.bin'
    f.write_bytes(bytes.fromhex(MAIN))
    assert cli.main(['recomp', str(f), '--base', '0x1000', '--auto', '0x1000', '0x1010', '--overlay', '2000:100:4',
                     '--dynamic', '100a', '-o', str(tmp_path / 'm.c')]) == 0
    c = (tmp_path / 'm.c').read_text()
    assert 'overlay_call(m, 0x2000u)' in c and 'call_addr(m, t)' in c and 'case 0x1010u: f_001010(m)' in c
    g = tmp_path / 'a.bin'
    g.write_bytes(MOD_A)
    assert cli.main(['recomp', str(g), '--base', '0x2000', '--auto', '0x2000', '--lib', '--prefix', 'ovA_:2000:2100',
                     '--overlay-module', '2000:4', '-o', str(tmp_path / 'a.c')]) == 0
    assert 'overlay_register(0x' in (tmp_path / 'a.c').read_text()
