// wb-touch.js 1.0 - touch controls for a rebuild's page (amiga-re-kit): a virtual stick on the left, buttons on the
// right (fire and the page's own keys), shown only on a touch device (pointer: coarse) or with ?touch in the address.
// Extracted from the Alien Breed II page. No game data.
//   WBTOUCH.init(host, { onKey: (amigaKeyCode, down) => {}, buttons: [{ label: 'Map', code: 0x37 }], fire: 'FIRE' })
//     -> true when the controls were built (the host element gets them, with their own styles)
//   WBTOUCH.bits()   -> the joystick bits as the page's keyboard gives them: R 1, L 2, U 4, D 8, F 16
//   WBTOUCH.active() -> the controls are on the page
// The page reads bits() where it reads its keyboard state (and ors them in); onKey gets the buttons' Amiga key codes.
'use strict';
const WBTOUCH = (() => {
  const CSS = '.wb-touch{position:absolute;inset:auto 0 0 0;height:45%;display:flex;justify-content:space-between;align-items:flex-end;padding:12px;pointer-events:none;line-height:normal;touch-action:none;user-select:none;-webkit-user-select:none}'
    + '.wb-touch-stick{pointer-events:auto;width:120px;height:120px;border-radius:50%;background:rgba(255,255,255,.12);border:2px solid rgba(255,255,255,.35);display:flex;align-items:center;justify-content:center;touch-action:none}'
    + '.wb-touch-knob{width:52px;height:52px;border-radius:50%;background:rgba(255,255,255,.4)}'
    + '.wb-touch-btns{pointer-events:auto;display:flex;gap:10px;align-items:flex-end}'
    + '.wb-touch button{touch-action:none;border:2px solid rgba(255,255,255,.4);background:rgba(255,255,255,.14);color:#fff;font:bold 12px sans-serif;border-radius:50%}'
    + '.wb-touch-fire{width:84px;height:84px}.wb-touch-small{width:56px;height:56px;font-size:10px!important}';
  let bits = 0, onKey = null, root = null, stick = null, knob = null, sid = null, sx = 0, sy = 0;
  const want = (force) => force || (typeof matchMedia === 'function' && matchMedia('(pointer: coarse)').matches) || /[?&]touch\b/.test(location.search);
  function el(tag, cls, text) { const e = document.createElement(tag); e.className = cls; if (text) e.textContent = text; return e; }
  function setStick(dx, dy) {
    const r = 40, d = Math.hypot(dx, dy), k = d > r ? r / d : 1;
    knob.style.transform = 'translate(' + dx * k + 'px,' + dy * k + 'px)';
    let b = 0; const t = 14;                                 // a dead zone of 14 px, eight directions
    if (dx > t) b |= 1; if (dx < -t) b |= 2; if (dy < -t) b |= 4; if (dy > t) b |= 8;
    bits = (bits & 16) | b;
  }
  function build(host, opt) {
    if (!document.getElementById('wb-touch-style')) { const st = document.createElement('style'); st.id = 'wb-touch-style'; st.textContent = CSS; document.head.appendChild(st); }
    root = el('div', 'wb-touch'); stick = el('div', 'wb-touch-stick'); knob = el('div', 'wb-touch-knob'); stick.appendChild(knob);
    const btns = el('div', 'wb-touch-btns'), fire = el('button', 'wb-touch-fire', opt.fire || 'FIRE');
    const hold = (b, down, up) => {
      b.addEventListener('pointerdown', (e) => { b.setPointerCapture(e.pointerId); down(); e.preventDefault(); });
      b.addEventListener('pointerup', up); b.addEventListener('pointercancel', up);
    };
    for (const k of opt.buttons || []) {
      const b = el('button', 'wb-touch-small', k.label);
      hold(b, () => onKey && onKey(k.code, 1), () => onKey && onKey(k.code, 0));
      btns.appendChild(b);
    }
    btns.appendChild(fire); root.append(stick, btns); host.appendChild(root);
    stick.addEventListener('pointerdown', (e) => { sid = e.pointerId; stick.setPointerCapture(sid); const r = stick.getBoundingClientRect(); sx = r.left + r.width / 2; sy = r.top + r.height / 2; setStick(e.clientX - sx, e.clientY - sy); e.preventDefault(); });
    stick.addEventListener('pointermove', (e) => { if (e.pointerId === sid) setStick(e.clientX - sx, e.clientY - sy); });
    const end = (e) => { if (e.pointerId === sid) { sid = null; setStick(0, 0); } };
    stick.addEventListener('pointerup', end); stick.addEventListener('pointercancel', end);
    hold(fire, () => { bits |= 16; }, () => { bits &= ~16; });
  }
  return {
    version: '1.0',
    init(host, opt) { opt = opt || {}; onKey = opt.onKey || null; if (!root && want(opt.force)) build(host, opt); return !!root; },
    bits: () => bits,
    active: () => !!root,
    _setStick: (dx, dy) => { if (knob) setStick(dx, dy); },   // tests
  };
})();
if (typeof module !== 'undefined') module.exports = WBTOUCH;
