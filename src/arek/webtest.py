"""Display contract tests (WB-OBRAZ-CRT.md §5) in Chromium, for any page with the test hooks.

The page provides ``window.wbObrazTest.set(mode, cfg) -> info`` (cfg: zoom, crtDetail,
crtShape, crt, blur, par; info: scale, W, H, P, D, par, origin, backing, content, crtLayer, crtOrigin) and
``window.wbObrazTest.fill(kind)`` ('grey', 'rows' - see wb-obraz.js ``testPattern``).
``arek web demo`` serves a page that does, built on the reference ``wb-obraz.js``.

    run('http://localhost:8920/demo.html')        # needs the optional playwright package

Checks: §5.1-5.3 per dpr x window width x mode x detail x zoom (S whole, backing = W·S,
CSS size x dpr = backing, content and CRT layer on whole device pixels, P and D);
§5.4 grey picture with CRT - row brightness exactly periodic with P, columns with 3;
§5.4b (1.3) a different grey per game row, CRT off - every game row exactly S device rows,
and every game column exactly S device columns; 1.4: the same layouts with a pixel aspect
(``par``, PAL lores) - content round(W*S*par) wide, rows still exact, columns not checked.
Tolerances: Chromium keeps layout in 1/64 CSS px, so positions within 0.05 and sizes within
0.025 device pixels.
"""
import itertools
import struct
import zlib

DPRS = (1, 1.25, 1.5, 2)
WIDTHS = (1280, 1001, 760)               # 1001: centring lands on half CSS pixels
MODES = ('original', 'enhanced')
DETAILS = ('fine', 'standard', 'strong')
ZOOMS = (1, 1.5, 2, 2.5, 3, 4, 6, 0)
TOL_POS, TOL_SIZE = 0.05, 0.025
SCREEN = {'fine': 2, 'standard': 3, 'strong': 4}
PAR = 1.04                                # PAL lores (14.75 / 14.1875 MHz): the 1.4 aspect the tests use; any value is allowed (NTSC lores 0.857)


def png_rgb(data):
    """Decode an 8-bit RGB/RGBA PNG (as Chromium writes it) -> (width, height, rows of (r, g, b))."""
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('not a PNG')
    pos, idat, w = 8, b'', None
    while pos < len(data):
        n, kind = struct.unpack('>I4s', data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + n]
        if kind == b'IHDR':
            w, h, depth, ctype = struct.unpack('>IIBB', body[:10])
            if depth != 8 or ctype not in (2, 6) or body[12]:
                raise ValueError('PNG: only 8-bit RGB/RGBA, not interlaced')
            bpp = 3 if ctype == 2 else 4
        elif kind == b'IDAT':
            idat += body
        pos += 12 + n
    raw, stride, rows, prev = zlib.decompress(idat), w * bpp, [], bytearray(w * bpp)
    for y in range(h):
        f, line = raw[y * (stride + 1)], bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            b, c = prev[i], prev[i - bpp] if i >= bpp else 0
            if f == 1:
                line[i] = (line[i] + a) & 255
            elif f == 2:
                line[i] = (line[i] + b) & 255
            elif f == 3:
                line[i] = (line[i] + (a + b) // 2) & 255
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        rows.append([tuple(line[x * bpp:x * bpp + 3]) for x in range(w)])
        prev = line
    return w, h, rows


def quantum(dpr):
    """Layout quantum (wb-obraz.js): the fewest device pixels that are a whole number of CSS px."""
    for q in range(1, 65):
        u = q / dpr
        if abs(u - round(u)) < 1e-6:
            return q
    return 1


def _inside(info, w, h, tag, fails):
    x0, y0 = round(info['origin'][0]), round(info['origin'][1])
    cw, ch = info.get('content', info['backing'])
    if x0 < 0 or y0 < 0 or x0 + cw > w or y0 + ch > h:
        fails.append('%s: content %dx%d at %d,%d outside the screenshot %dx%d (does fit use the height?)'
                     % (tag, cw, ch, x0, y0, w, h))
        return False
    return True


def _runs(values):
    """Lengths of the runs of equal values."""
    runs, n = [], 1
    for a, b in zip(values, values[1:]):
        if a == b:
            n += 1
        else:
            runs.append(n)
            n = 1
    runs.append(n)
    return runs


def _crop(rows, x0, y0, w, h):
    return [r[x0:x0 + w] for r in rows[y0:y0 + h]]


def check_layout(info, mode, detail, dpr, fails, tag):
    S, W, H = info['scale'], info['W'], info['H']
    par = info.get('par', 1) or 1
    cw, ch = round(W * S * par), H * S
    ok = lambda cond, what: cond or fails.append('%s: %s' % (tag, what))
    ok(S == int(S) and S >= 1, 'S %s not whole' % S)
    q = quantum(dpr)
    ok(info.get('content', info['backing']) == [cw, ch], 'content %s != %dx%d (par %s)' % (info.get('content'), cw, ch, par))
    ok(all(b >= c and b % q == 0 for b, c in zip(info['backing'], (cw, ch))),
       'backing %s not the content rounded up to the layout quantum %d' % (info['backing'], q))
    ok(all(abs(v - round(v)) < TOL_POS and round(v) % q == 0 for v in info['origin']),
       'origin %s not on a multiple of %d device pixels' % (info['origin'], q))
    ok(info['crtLayer'] == info['backing'], 'CRT layer %s != backing' % info['crtLayer'])
    ok(all(abs(a - b) < TOL_POS for a, b in zip(info['crtOrigin'], info['origin'])), 'CRT layer not over the content')
    P, D = info['P'], info['D']
    if mode == 'original':
        ok(P == max(2, S), 'P %d != max(2, S)' % P)
    else:
        ok(P == SCREEN[detail] and D == 1, 'P %d D %d' % (P, D))


def run(url, quick=False, log=print):
    """Run the checks; returns {'checks': n, 'fails': [...]} (raises ImportError without playwright)."""
    from playwright.sync_api import sync_playwright
    fails, checks = [], 0
    zooms = (2, 0) if quick else ZOOMS
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        for dpr in DPRS:
            for width in (WIDTHS[:1] if quick else WIDTHS):
                ctx = br.new_context(device_scale_factor=dpr, viewport={'width': width, 'height': 900})
                page = ctx.new_page()
                page.goto(url)
                page.wait_for_function('window.wbObrazTest')
                for mode, detail, zoom, par in itertools.product(MODES, DETAILS, zooms, (1, PAR)):
                    if par != 1 and zoom not in (2, 0):
                        continue
                    info = page.evaluate('([m, d, z, p]) => wbObrazTest.set(m, {zoom: z, crtDetail: d, crt: true, blur: 0, par: p})',
                                         [mode, detail, zoom, par])
                    check_layout(info, mode, detail, dpr, fails, 'dpr %s w%d %s/%s zoom %s par %s' % (dpr, width, mode, detail, zoom, par))
                    checks += 1
                ctx.close()
        log('§5.1-5.3: %d layouts, %d failures' % (checks, len(fails)))
        for dpr, (vw, vh) in itertools.product(DPRS, ((1280, 1000), (1001, 999)) if not quick else ((1001, 999),)):
            ctx = br.new_context(device_scale_factor=dpr, viewport={'width': vw, 'height': vh})
            page = ctx.new_page()
            page.goto(url)
            page.wait_for_function('window.wbObrazTest')
            cases = [(m, d, z, 1) for m, d, z in itertools.product(MODES, DETAILS, (2, 3, 0) if not quick else (2,))]
            cases += [('enhanced', 'fine', 2, PAR), ('original', 'strong', 0, PAR)]          # 1.4: with an aspect
            for mode, detail, zoom, par in cases:
                info = page.evaluate('([m, d, z, p]) => wbObrazTest.set(m, {zoom: z, crtDetail: d, crt: true, blur: 0, par: p})',
                                     [mode, detail, zoom, par])
                page.evaluate("wbObrazTest.fill('grey')")
                page.wait_for_timeout(450)
                sw, sh, rows = png_rgb(page.screenshot())
                P, tag = info['P'], 'dpr %s %dx%d %s/%s zoom %s par %s S %d' % (dpr, vw, vh, mode, detail, zoom, par, info['scale'])
                checks += 1
                if not _inside(info, sw, sh, '§5.4 ' + tag, fails):
                    continue
                x0, y0 = round(info['origin'][0]), round(info['origin'][1])
                bw, bh = info.get('content', info['backing'])
                im = _crop(rows, x0, y0, bw, bh)
                edge = int(48 * dpr) + 3                    # the vignette (inset 42 CSS px)
                col = [sum(r[bw // 2 + 1]) / 3 for r in im]
                lo, hi = edge, bh - edge
                bad = [y for y in range(lo, hi - P) if abs(col[y] - col[y + P]) > 1.01]
                yr = lo + 1 if (lo + 1) % P != P - 1 else lo
                badc = [x for x in range(edge, bw - edge - 3)
                        if max(abs(im[yr][x][k] - im[yr][x + 3][k]) for k in range(3)) > 1]
                if bad or badc:
                    fails.append('§5.4 %s: %d rows, %d columns off the period' % (tag, len(bad), len(badc)))
                # §5.4b: CRT off, a grey per game row - each game row exactly S device rows
                info = page.evaluate('([m, d, z, p]) => wbObrazTest.set(m, {zoom: z, crtDetail: d, crt: false, blur: 0, par: p})',
                                     [mode, detail, zoom, par])
                page.evaluate("wbObrazTest.fill('rows')")
                page.wait_for_timeout(450)
                sw, sh, rows = png_rgb(page.screenshot())
                checks += 1
                if not _inside(info, sw, sh, '§5.4b ' + tag, fails):
                    continue
                x0, y0 = round(info['origin'][0]), round(info['origin'][1])
                bw, bh = info.get('content', info['backing'])
                lum = [rows[y][x0 + bw // 2][0] for y in range(y0, y0 + bh)]
                runs = _runs(lum)
                S = info['scale']
                if any(r != S for r in runs) or len(runs) != info['H']:
                    odd = [(i, r) for i, r in enumerate(runs) if r != S][:4]
                    fails.append('§5.4b %s: %d game rows seen, rows of other height %s' % (tag, len(runs), odd))
                # and every game column exactly S device columns (a resampled width shows here); not with an aspect (1.4)
                if par != 1:
                    continue
                page.evaluate("wbObrazTest.fill('cols')")
                page.wait_for_timeout(100)
                sw, sh, rows = png_rgb(page.screenshot())
                lumx = [rows[y0 + bh // 2][x][0] for x in range(x0, x0 + bw)]
                runs = _runs(lumx)
                if any(r != S for r in runs) or len(runs) != info['W']:
                    odd = [(i, r) for i, r in enumerate(runs) if r != S][:4]
                    fails.append('§5.4b %s: %d game columns seen, columns of other width %s' % (tag, len(runs), odd))
            ctx.close()
        br.close()
    log('§5.4/5.4b done: %d checks, %d failures' % (checks, len(fails)))
    return {'checks': checks, 'fails': fails}
