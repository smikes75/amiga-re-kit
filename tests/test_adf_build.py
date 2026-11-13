"""1.0.74: `arek adf build` - a bootable disk from one memory image (the Atari 8-bit port's request). The boot code was
measured in the emulator (VAHeadless 899da5d, Kickstart 1.3, 2026-11-13): images of 1 000 bytes to 460 KB at $400, $1000,
$35000 loaded byte for byte, SR $2700, a6 $DFF000, a7 as asked, on 512 KB + 512 KB and on 512 KB chip RAM alone; 470 KB on
512 KB alone does not fit the temporary buffer - a red screen. Here: the layout, the checks and the source."""
import os
import shutil
import struct
import subprocess

import pytest

from arek import adf, cli


def test_the_disk_layout():
    pay = bytes(range(256)) * 5                                  # 1 280 bytes: three sectors with the padding
    img = adf.build_boot(pay, 0x1000, 0x1100)
    assert len(img) == adf.SIZE and img[:4] == b'DOS\0'
    bb = adf.bootblock(img)
    assert bb['bootable'] and bb['checksum_stored'] == bb['checksum_calc']
    code = img[12:12 + len(adf.BOOT_CODE)]
    assert code == adf.BOOT_CODE
    n, load, entry, stack = struct.unpack_from('>IIII', img, 12 + len(adf.BOOT_CODE))
    assert (n, load, entry, stack) == (1536, 0x1000, 0x1100, 0x1000)
    assert img[1024:1024 + len(pay)] == pay and img[1024 + len(pay):] == bytes(adf.SIZE - 1024 - len(pay))
    assert struct.unpack_from('>I', img, 8)[0] == 880
    # the defaults: entry = load, stack = load, or the memory's end for an image below $1000
    assert struct.unpack_from('>III', adf.build_boot(pay, 0x40000), 12 + len(adf.BOOT_CODE) + 4) == (0x40000, 0x40000, 0x40000)
    assert struct.unpack_from('>I', adf.build_boot(pay, 0x400), 12 + len(adf.BOOT_CODE) + 12)[0] == 0x80000
    assert struct.unpack_from('>I', adf.build_boot(pay, 0x400, memtop=0x40000), 12 + len(adf.BOOT_CODE) + 12)[0] == 0x40000


@pytest.mark.parametrize('kw, why', [
    (dict(payload=b'', load=0x1000), 'empty'),
    (dict(payload=b'x' * 10, load=0x200), 'vectors'),
    (dict(payload=b'x' * 10, load=0x1001), 'even'),
    (dict(payload=b'x' * 0x20000, load=0x70000), 'memory'),
    (dict(payload=b'x' * 10, load=0x1000, entry=0x2000), 'outside the image'),
    (dict(payload=b'x' * (adf.SIZE - 1023), load=0x400, memtop=0x200000), 'a disk holds'),
])
def test_what_it_refuses(kw, why):
    pay = kw.pop('payload')
    with pytest.raises(adf.ADFError, match=why):
        adf.build_boot(pay, **kw)


def test_the_largest_image_fills_the_disk():
    img = adf.build_boot(b'\x60\xfe' * ((adf.SIZE - 1024) // 2), 0x400, memtop=0x200000)
    assert img[-2:] == b'\x60\xfe' and adf.bootblock(img)['bootable']


def test_the_command_line(tmp_path, capsys):
    (tmp_path / 'p.bin').write_bytes(b'\x60\xfe' + bytes(600))
    assert cli.main(['adf', 'build', str(tmp_path / 'o.adf'), '--payload', str(tmp_path / 'p.bin'), '--load', '$2000',
                     '--entry', '0x2000', '--stack', '0x1ff00']) in (0, None)
    img = (tmp_path / 'o.adf').read_bytes()
    assert struct.unpack_from('>IIII', img, 12 + len(adf.BOOT_CODE)) == (1024, 0x2000, 0x2000, 0x1ff00)
    assert 'entry $2000' in capsys.readouterr().out
    with pytest.raises(SystemExit):
        cli.main(['adf', 'build', str(tmp_path / 'x.adf'), '--payload', str(tmp_path / 'p.bin'), '--load', '0x7ff00'])


def test_the_boot_code_is_its_source():
    """BOOT_CODE is headless/adf_boot.s as m68k-elf-as assembles it (when the assembler is there)."""
    asm, objcopy = shutil.which('m68k-elf-as'), shutil.which('m68k-elf-objcopy')
    if not asm or not objcopy:
        pytest.skip('no m68k-elf-as')
    src = os.path.join(os.path.dirname(adf.__file__), 'headless', 'adf_boot.s')
    import tempfile
    d = tempfile.mkdtemp()
    subprocess.run([asm, '-m68000', '-o', os.path.join(d, 'b.o'), src], check=True)
    subprocess.run([objcopy, '-O', 'binary', os.path.join(d, 'b.o'), os.path.join(d, 'b.bin')], check=True)
    b = open(os.path.join(d, 'b.bin'), 'rb').read()
    assert b[:len(adf.BOOT_CODE)] == adf.BOOT_CODE and b[len(adf.BOOT_CODE):] == bytes(16)
