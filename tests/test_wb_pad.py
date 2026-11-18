"""wb-pad.js 1.1 (kit 1.0.90): gamepads and joysticks read into the page's joystick bits - the games' own pad.js (Alien
Breed II: two players, Superfrog: a jump button) made general. Fake navigator.getGamepads in Node. 1.1: 'auto' by use
(not the first listed device), one controller listed twice, a page's own buttons."""
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
// two players: auto gives player 1 the pad used first, player 2 the next one used; a choice takes its pad and auto skips it
now = [std(0, [15]), std(2)];
const two = P.create({ players: 2, read: () => now });
out.twoFirst = two.poll();
now = [std(0, [15]), std(2, [14, 0])];
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
// 1.1: a device that is not the controller listed first (a receiver resting with an axis at -1, a quiet virtual pad):
// auto gives nobody a device until it is used, then the one used
const phantom = (index, mapping, axes) => ({ index, id: 'USB Receiver (Vendor: 046d)', mapping: mapping || '', connected: true, buttons: btn(17, []), axes: axes || [-1, 0, 0, 0] });
now = [phantom(0), std(1)];
const ph = P.create({ read: () => now });
out.phantomIdle = [ph.poll()[0], ph.status()];
now = [phantom(0), std(1, [0])]; out.phantomFire = ph.poll()[0];
now = [phantom(0, 'standard', [0, 0, 0, 0]), std(1)];
const ph2 = P.create({ read: () => now });
out.phantomStd = [ph2.poll()[0], ph2.status()];
now = [phantom(0, 'standard', [0, 0, 0, 0]), std(1, [], [1, 0, 0, 0])]; out.phantomStdUsed = [ph2.poll()[0], ph2.status()];
now = [phantom(0), std(1, [0])]; out.phantom2 = P.create({ players: 2, read: () => now }).poll();
// one controller listed twice (standard + raw, both used in the same poll): player 1 the standard one, player 2 not its twin
const tw = P.create({ players: 2, read: () => now });
out.twins = [];
for (let k = 0; k < 20; k++) { now = [std(0, [0], [1, 0, 0, 0]), joy(1, [1], [1, 0, 0, 0, 0, 0, 0, 0, 0, 3.2857])]; out.twins.push(tw.poll()); }
out.twinsStatus = tw.status();
// two players who pressed in the same poll: once they have differed for 10 polls in a row, player 2 gets the second pad
const ap = P.create({ players: 2, read: () => now });
now = [std(0, [0]), std(1, [0])]; out.apart = [ap.poll()];
for (let k = 0; k < 11; k++) { now = [std(0, [15]), std(1, [], [0, -1, 0, 0])]; out.apart.push(ap.poll()); }
// the page's own buttons: reserve [1] (Turrican: B = Space) no longer fires, button() reads it; a chosen fire button does
// nothing else
now = [std(0, [1])];
const rs = P.create({ read: () => now, reserve: [1] });
out.reserve = [rs.poll()[0], rs.button(0, 1), rs.button(0, 3)];
now = [std(0, [0])]; out.reserveA = rs.poll()[0];
rs.set(0, { fire: '1' }); now = [std(0, [1])]; out.reserveChosen = [rs.poll()[0], rs.button(0, 1)];
now = [std(0, [12])]; out.fireDpad = one(now, { fire: '12' });
now = [std(0, [0])]; out.fireUp = one(now, { fire: '0', up: '0' });
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
    assert o['version'] == ['1.1', {'right': 1, 'left': 2, 'up': 4, 'down': 8, 'fire': 16}]
    assert o['dpadUpA'] == 4 | 16
    assert o['stick'] == [1, 0, 4]                              # past 0.4 only
    assert o['hat'] == [4, 1 | 8, 16]                           # hat up, hat down-right, button 4 of a joystick fires
    assert o['fire5'] == [0, 16]                                # a chosen fire button fires alone
    assert o['upA'] == 4 and o['upAfire'] == 4 | 16             # an up button pushes up, B still fires
    assert o['gone'] == 0 and o['disconnected'] == 0 and o['numbers'] == 8 | 16   # buttons given as numbers: 0 fires, 13 is the d-pad's down
    assert o['twoFirst'] == [1, 0]                              # player 2's pad not used yet: auto still gives it to them
    assert o['two'] == [1, 2 | 16] and o['twoStatus'] == 'Player 1: Pad 0 (Controller 1) · Player 2: Pad 2 (Controller 3)'
    assert o['twoSwapped'] == [2 | 16, 1] and o['twoCs'] == 'Hráč 1: Pad 2 (Ovladač 3) · Hráč 2: Pad 0 (Ovladač 1)'
    assert o['none'] == [0, 0] and 'no controller' in o['noneStatus']
    assert o['order'] == 1 | 8
    # 1.1: a receiver listed first (1.0: player 1 read it - left held, the controller unused)
    assert o['phantomIdle'] == [0, 'press a button on the controller · found: USB Receiver (Controller 1), Pad 1 (Controller 2)']
    assert o['phantomFire'] == 16                               # taken in the poll it is first used
    assert o['phantomStd'] == [0, 'press a button on the controller · found: USB Receiver (Controller 1), Pad 1 (Controller 2)']
    assert o['phantom2'] == [16, 0]                             # two players: the receiver nobody used is not player 2's
    assert o['phantomStdUsed'] == [1, 'Pad 1 (Controller 2) · not used: USB Receiver (Controller 1)']   # the stick moved: that one
    assert o['twins'] == [[1 | 16, 0]] * 20                     # 1.0: player 2 mirrored player 1
    assert o['twinsStatus'] == 'Player 1: Pad 0 (Controller 1) · Player 2: none · not used: Stick 1 (Controller 2)'
    assert o['apart'][:10] == [[16, 0]] + [[1, 0]] * 9 and o['apart'][10:] == [[1, 4]] * 2
    assert o['reserve'] == [0, True, False] and o['reserveA'] == 16 and o['reserveChosen'] == [16, False]
    assert o['fireDpad'] == 16 and o['fireUp'] == 16
    assert o['rows'] == [['pad1', 'select', 'controls', False, 5, 'auto'], ['pad1-fire', 'select', 'controls', False, 17, 'auto'],
                         ['pad1-up', 'select', 'controls', False, 17, 'none'], ['pad2', 'select', 'controls', False, 5, 'auto'],
                         ['pad2-fire', 'select', 'controls', False, 17, 'auto'], ['pad2-up', 'select', 'controls', False, 17, 'none']]
    assert o['rowsCs'][0] == 'Hráč 1: Ovladač' and len(o['rowsCs']) == 4
    assert o['config'] == [{'pad': 'auto', 'fire': '3', 'up': 'none'}, {'pad': '1', 'fire': 'auto', 'up': 'none'}]
    assert 'wb-pad.js' in web.FILES
