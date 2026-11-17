"""wb-pad.js 1.0 (kit 1.0.89): gamepads and joysticks read into the page's joystick bits - the games' own pad.js (Alien
Breed II: two players, Superfrog: a jump button) made general. Fake navigator.getGamepads in Node."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from arek import web

WEB = Path(web.__file__).parent

SCRIPT = r"""
const P = require(%s), N = require(%s);
const btn = (n, on) => { const b = Array.from({ length: 17 }, () => ({ pressed: false, value: 0 })); for (const k of on) b[k] = { pressed: true, value: 1 }; return b; };
const std = (index, on, axes) => ({ index, id: 'Pad ' + index + ' (STANDARD GAMEPAD Vendor: 045e)', mapping: 'standard', connected: true, buttons: btn(17, on || []), axes: axes || [0, 0, 0, 0] });
const joy = (index, on, axes) => ({ index, id: 'Stick ' + index, mapping: '', connected: true, buttons: btn(12, on || []), axes: axes || [0, 0, 0, 0, 0, 0, 0, 0, 0, 3.2857] });
let now = [];
const out = {};
const one = (pads, set) => { now = pads; const p = P.create({ players: 1, read: () => now }); if (set) p.set(0, set); return p.poll()[0]; };
out.dpadUpA = one([std(0, [12, 0])]);                        // up 4 + fire 16
out.stick = [one([std(0, [], [.6, 0, 0, 0])]), one([std(0, [], [.3, 0, 0, 0])]), one([std(0, [], [0, -.9, 0, 0])])];
out.hat = [one([joy(0, [], [0, 0, 0, 0, 0, 0, 0, 0, 0, -1])]), one([joy(0, [], [0, 0, 0, 0, 0, 0, 0, 0, 0, -0.1428])]), one([joy(0, [3])])];
out.fire5 = [one([std(0, [0])], { fire: 5 }), one([std(0, [5])], { fire: '5' })];
out.upA = one([std(0, [0])], { up: '0' });                   // Superfrog: A jumps (up) and no longer fires
out.upAfire = one([std(0, [0, 1])], { up: '0' });
out.gone = one([std(0, [0])], { pad: '2' });                 // a chosen pad that is not connected reads 0
out.disconnected = one([Object.assign(std(0, [0]), { connected: false })]);
out.numbers = one([{ index: 0, id: 'x', mapping: 'standard', buttons: [1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1], axes: [0, 0] }]);   // buttons as numbers
// two players: auto gives player 1 the first pad, player 2 the next; a choice takes its pad and auto skips it
now = [std(0, [15]), std(2, [14, 0])];
const two = P.create({ players: 2, read: () => now });
out.two = two.poll(); out.twoStatus = two.status();
two.set(0, { pad: '2' }); out.twoSwapped = two.poll();
out.twoCs = two.status('cs');
now = []; out.none = two.poll(); out.noneStatus = two.status();
// the page's own bit order (Superfrog: up 1, down 2, left 4, right 8)
now = [std(0, [12, 15])];
out.order = P.create({ read: () => now, bits: { up: 1, down: 2, left: 4, right: 8 } }).poll()[0];
// the rows are wb-nastaveni 1.4 rows, and the menu's values set the players
const rows = two.rows({ section: 'controls', up: true });
out.rows = N.rowsOf(rows).map((r) => [r.id, r.kind, r.section, r.perMode, r.options.length, r.def]);
out.rowsCs = two.rows({ lang: 'cs' }).map((r) => r.label);
two.fromMenu({ pad1: 'auto', 'pad1-fire': '3', 'pad1-up': 'none', pad2: '1', 'pad2-fire': 'auto' });
out.config = two.config();
out.version = [P.VERSION, P.BITS];
console.log(JSON.stringify(out));
"""


def test_wb_pad_reads_the_controllers_into_the_joystick_bits():
    node = shutil.which('node')
    if not node:
        pytest.skip('no node')
    r = subprocess.run([node, '-e', SCRIPT % (json.dumps(str(WEB / 'wb-pad.js')), json.dumps(str(WEB / 'wb-nastaveni.js')))],
                       capture_output=True, text=True, check=True)
    o = json.loads(r.stdout)
    assert o['version'] == ['1.0', {'right': 1, 'left': 2, 'up': 4, 'down': 8, 'fire': 16}]
    assert o['dpadUpA'] == 4 | 16
    assert o['stick'] == [1, 0, 4]                              # past 0.4 only
    assert o['hat'] == [4, 1 | 8, 16]                           # hat up, hat down-right, button 4 of a joystick fires
    assert o['fire5'] == [0, 16]                                # a chosen fire button fires alone
    assert o['upA'] == 4 and o['upAfire'] == 4 | 16             # an up button pushes up, B still fires
    assert o['gone'] == 0 and o['disconnected'] == 0 and o['numbers'] == 8 | 16   # buttons given as numbers: 0 fires, 13 is the d-pad's down
    assert o['two'] == [1, 2 | 16] and o['twoStatus'] == 'Player 1: Pad 0 · Player 2: Pad 2'
    assert o['twoSwapped'] == [2 | 16, 1] and o['twoCs'] == 'Hráč 1: Pad 2 · Hráč 2: Pad 0'
    assert o['none'] == [0, 0] and 'no controller' in o['noneStatus']
    assert o['order'] == 1 | 8
    assert o['rows'] == [['pad1', 'select', 'controls', False, 5, 'auto'], ['pad1-fire', 'select', 'controls', False, 17, 'auto'],
                         ['pad1-up', 'select', 'controls', False, 17, 'none'], ['pad2', 'select', 'controls', False, 5, 'auto'],
                         ['pad2-fire', 'select', 'controls', False, 17, 'auto'], ['pad2-up', 'select', 'controls', False, 17, 'none']]
    assert o['rowsCs'][0] == 'Hráč 1: Ovladač' and len(o['rowsCs']) == 4
    assert o['config'] == [{'pad': 'auto', 'fire': '3', 'up': 'none'}, {'pad': '1', 'fire': 'auto', 'up': 'none'}]
    assert 'wb-pad.js' in web.FILES
