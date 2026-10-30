"""The kit's documents ship with it (Superfrog KIT-GAPS 37: the canon docs/WB-PLYNULOST.md was not in the wheel):
the package list in pyproject.toml, `arek docs`, and a wheel built from the checkout."""
import glob
import io
import os
import subprocess
import sys
import tomllib
import zipfile
from contextlib import redirect_stdout

import pytest
from setuptools import find_packages

from arek import cli

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _pyproject():
    with open(os.path.join(ROOT, 'pyproject.toml'), 'rb') as f:
        return tomllib.load(f)['tool']['setuptools']


def test_every_package_is_listed_and_docs_map_to_docs():
    st = _pyproject()
    assert sorted(st['packages']) == sorted(find_packages(os.path.join(ROOT, 'src')) + ['arek.docs'])
    assert st['package-dir']['arek.docs'] == 'docs' and st['package-data']['arek.docs'] == ['*.md']


def _cli(*argv):
    out = io.StringIO()
    with redirect_stdout(out):
        rc = cli.main(list(argv))
    return rc, out.getvalue()


def test_arek_docs_lists_prints_and_finds_the_path():
    rc, text = _cli('docs')
    assert rc == 0 and 'WB-PLYNULOST' in text and 'METHOD' in text
    rc, text = _cli('docs', 'wb-plynulost.md')
    assert rc == 0 and text.startswith('# WB-PLYNULOST') and 'WBLONGRUN' in text
    rc, text = _cli('docs', 'WB-PLYNULOST', '--path')
    assert rc == 0 and text.strip().endswith(os.path.join('docs', 'WB-PLYNULOST.md')) and os.path.exists(text.strip())
    assert cli.main(['docs', 'NO-SUCH-DOC']) != 0


def test_the_wheel_carries_the_docs(tmp_path):
    """Built as a release is (python -m build: the sdist, then the wheel from it, setuptools>=77 in an isolated
    environment - which pip fetches, so the test is skipped offline)."""
    pytest.importorskip('build')
    r = subprocess.run([sys.executable, '-m', 'build', '--outdir', str(tmp_path), ROOT], capture_output=True, text=True, timeout=600)
    if r.returncode and any(k in r.stdout + r.stderr for k in ('No matching distribution', 'Could not fetch', 'Network is unreachable', 'NewConnectionError')):
        pytest.skip('no network for the isolated build environment')
    assert r.returncode == 0, (r.stdout + r.stderr)[-2000:]
    whl = glob.glob(str(tmp_path / '*.whl'))[0]
    names = zipfile.ZipFile(whl).namelist()
    want = {'arek/docs/%s' % os.path.basename(p) for p in glob.glob(os.path.join(ROOT, 'docs', '*.md'))}
    assert 'arek/docs/WB-PLYNULOST.md' in want and want <= set(names)
    assert not [n for n in names if n.startswith('arek/docs/') and not n.endswith('.md')]   # no pages, no screenshots
    assert 'arek/web/smooth-demo.html' in names and 'arek/host/arek_host.h' in names
