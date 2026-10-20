"""``local.conf`` - the only place where paths to copyrighted material live.

The file is a flat ``KEY = value`` list (quotes optional, ``#`` comments) and
is git-ignored in every project. Keys the kit understands::

    MACHINE = A500_OCS_1MB        # vAmiga regression setup name
    ROM     = roms/kick13.rom     # Kickstart image (never in a repo)
    ADF1    = disks/game.adf      # disk images, ADF1.. ADFn
    VAHL    = bin/VAHeadless      # patched headless vAmiga binary
    OBJDUMP = m68k-elf-objdump    # optional, for xref/disrange listings

Relative paths resolve against the directory of the conf file.
"""
import os
from pathlib import Path


class ConfigError(RuntimeError):
    pass


PATH_KEYS = ('VAHL', 'ROM', 'OBJDUMP')


def load(path='local.conf', root=None):
    path = Path(path)
    if not path.is_file():
        raise ConfigError('missing %s - run `arek init` and fill in the paths' % path)
    root = Path(root) if root else path.resolve().parent
    conf = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        conf[k.strip()] = v.strip().strip('"').strip("'")
    for key in list(conf):
        if (key in PATH_KEYS or key.startswith('ADF')) and conf[key] and not os.path.isabs(conf[key]):
            if key == 'OBJDUMP' and os.sep not in conf[key]:
                continue                       # a bare command name, on PATH
            conf[key] = str(root / conf[key])
    return conf


def require(conf, *keys):
    missing = [k for k in keys if not conf.get(k)]
    if missing:
        raise ConfigError('local.conf lacks: ' + ', '.join(missing))
    for k in keys:
        if k in PATH_KEYS + ('ADF1',) or k.startswith('ADF'):
            if k == 'OBJDUMP':
                continue
            if not Path(conf[k]).is_file():
                raise ConfigError('%s does not exist: %s' % (k, conf[k]))
    return conf


TEMPLATE = """# amiga-re-kit local configuration - NOT for git (contains paths to
# copyrighted material: Kickstart ROM and game disks stay on your machine).
MACHINE = A500_OCS_1MB
ROM     = roms/kick13.rom
ADF1    = disks/game.adf
VAHL    = bin/VAHeadless
# OBJDUMP = m68k-elf-objdump
"""
