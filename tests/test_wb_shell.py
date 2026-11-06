"""wb-menu.js + wb.css (kit 1.0.17, Turrican II KIT-GAP 25): the Workbench bar of a rebuild's page, the one Alien Breed II
and Superfrog wrote - shipped by `arek web copy`, which keeps a page's own bar without an error; in Chromium a synthetic
bar: an open menu suspends, Esc and a click outside restore, the arrows walk the bar, a requester traps Tab, message()
shows the notice. No game data."""
from pathlib import Path

import pytest

from arek import cli, web

WEB = Path(web.__file__).parent

PAGE = """<!doctype html><html><head><meta charset="utf-8"><style>%s</style></head><body>
<main id="shell"><nav id="wbbar" aria-label="Main menu"><span class="wbname">Synthetic</span>
<div class="wbmenu"><button id="menu-project" class="wbtitle" type="button" aria-expanded="false">Project</button>
<div id="project-panel" class="wbpanel" hidden><button id="about-open" type="button" class="wbitem">About</button><button id="go" type="button" class="wbitem" data-close-menu>Start</button></div></div>
<div class="wbmenu"><button id="menu-display" class="wbtitle" type="button" aria-expanded="false">Display</button>
<div id="display-panel" class="wbpanel" hidden><button id="d1" type="button" class="wbitem">One</button><button id="d2" type="button" class="wbitem">Two</button></div></div>
<div id="wbstatus"><output id="status">Ready</output><output id="wbnotice" hidden></output></div></nav>
<div id="stage"><div class="game"><canvas id="screen" tabindex="0" width="320" height="200"></canvas></div></div>
<div id="about-shade" class="requester-shade" hidden><section class="wbwin requester"><div class="wbwtitle"><h2>About</h2><button id="x" type="button" data-close-dialog>x</button></div>
<p><button id="ok" type="button" data-close-dialog>OK</button></p></section></div></main>
<script>%s</script><script>
const log = []; const shell = new WbMenu.Shell(document.getElementById('shell'), { suspend: () => log.push('s'), restore: () => log.push('r') });
document.getElementById('about-open').onclick = () => shell.openDialog('about-shade');
</script></body></html>"""


def test_shipped_and_copied(tmp_path, capsys):
    assert 'wb-menu.js' in web.FILES and 'wb.css' in web.FILES and web.SHELL == ('wb-menu.js', 'wb.css')
    for name in web.SHELL:
        text = (WEB / name).read_text()
        assert 'amiga-re-kit' in text[:4096] and not any(c in text for c in 'ěščřžůň')   # the kit's mark: copy updates it later
    assert 'class Shell' in (WEB / 'wb-menu.js').read_text() and '#wbbar' in (WEB / 'wb.css').read_text()
    assert cli.main(['web', 'copy', str(tmp_path)]) == 0 and (tmp_path / 'wb-menu.js').exists() and (tmp_path / 'wb.css').exists()
    # a page with its own bar (Alien Breed II, Superfrog): kept, and copy still succeeds
    own = tmp_path / 'wb.css'
    own.write_text('/* the page\'s own bar */\n')
    capsys.readouterr()
    assert cli.main(['web', 'copy', str(tmp_path)]) == 0 and own.read_text().startswith("/* the page's own")
    out = capsys.readouterr().out
    assert "kept the page's own Workbench bar" in out and 'kept, not a kit file' not in out
    assert cli.main(['web', 'copy', str(tmp_path), '--force']) == 0 and '#wbbar' in own.read_text()


def test_bar_in_chromium():
    pytest.importorskip('playwright')
    from playwright.sync_api import sync_playwright
    html = PAGE % ((WEB / 'wb.css').read_text(), (WEB / 'wb-menu.js').read_text())
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            try:
                p = b.new_page(viewport={'width': 900, 'height': 600})
                p.set_content(html)
                st = lambda: p.evaluate("[log.join(''), shell.busy, document.activeElement.id, !document.getElementById('project-panel').hidden, !document.getElementById('display-panel').hidden]")
                bar = p.evaluate("getComputedStyle(document.getElementById('wbbar')).position")
                p.click('#menu-project')
                a = st()
                p.keyboard.press('ArrowRight')                      # the bar: the next menu opens while one is open
                b2 = st()
                p.keyboard.press('ArrowDown')                       # into the panel
                c = st()
                p.keyboard.press('Escape')
                d = st()
                p.click('#menu-project'); p.click('#about-open')    # a requester from a menu item
                e = st()
                p.keyboard.press('Tab'); f1 = p.evaluate('document.activeElement.id')
                p.keyboard.press('Tab'); f2 = p.evaluate('document.activeElement.id')
                p.keyboard.press('Tab'); f3 = p.evaluate('document.activeElement.id')
                p.click('#ok')
                g = st()
                p.click('#menu-display'); p.mouse.click(400, 400)  # a click outside closes
                h = st()
                p.evaluate("shell.message('Saved')")
                notice = p.evaluate("[document.getElementById('wbnotice').hidden, document.getElementById('wbnotice').textContent, WbMenu.editable(document.createElement('input'))]")
            finally:
                b.close()
    except Exception as ex:
        if 'Executable doesn' in str(ex):
            pytest.skip('no Chromium for playwright')
        raise
    assert bar == 'fixed'
    assert a == ['s', True, 'menu-project', True, False]
    assert b2[1:] == [True, 'menu-display', False, True] and b2[0].startswith('s')
    assert c[2] == 'd1' and c[1]
    assert d[0].endswith('r') and d[1:] == [False, d[2], False, False]
    assert e[1] and not e[3]                                          # the requester replaced the menu, still suspended
    assert [f1, f2, f3] == ['ok', 'x', 'ok']                           # Tab cycles inside the requester
    assert g[0].endswith('r') and not g[1]
    assert h[0].endswith('sr') and not h[1] and not h[4]
    assert notice == [False, 'Saved', True]
