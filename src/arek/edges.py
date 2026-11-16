"""arek edges (kit 1.0.84, SWIV): which constants of the game's code make its screen end where it ends - measured, not read.

A game that shows more than its own screen (a band under the window, a taller picture) behaves as it did inside the band
only when every place that decides by the old edge decides by the new one: the player's limit, the line below which an
object is deleted, where the objects that come from below are made, where an enemy fires. Five rebuilds found such
constants by reading the code one at a time (SWIV: $1853C addi.w #248 the player's limit, $15460 subi.w #256 the deletion
line); each was found after the user saw the band misbehave. This lists them all at once:

1. the translation lists every instruction whose source operand is a constant (``arek recomp --immediates FILE``); the
   candidates are those whose value lies in ``values`` (the screen's height and the margins around it), optionally of
   the mnemonics in ``mn``;
2. every candidate's operand becomes ``(constant + arek_knob(k))`` in one build (``arek recomp --flow-file``): a knob is
   0 unless the run's environment sets it (``AREK_KNOBS="k=v,..."``), and the build counts how often each is read
   (``AREK_KNOBS_OUT``);
3. the project's scenario runs once with every knob at 0 (the baseline: the translation's own run, and which candidates
   the run executes at all), then once per executed candidate with only that knob at ``shift``;
4. the report: per candidate the reads, the range of the register the constant meets (cmp / add / sub #n,Dn: a screen
   coordinate runs from below 0 to past the edge, a ring index or a counter does not), whether the run's outcome changed
   (``outcome``: a regex over the output, default its last line) and the project's metrics (``metrics``: name -> a regex
   with one number) against the baseline.

A candidate that changes nothing in the scenario is no edge there; one that changes the outcome is a place the game
decides by that number - the project then checks what it decides with its own tools and keeps the edges (in its own
flow file, ``operand ADDR=(248 + band())``). The project keeps its build: the driver writes the flow file, runs the
project's commands and reads the immediates file.

    {
      "build": "sh tools/build_edges.sh",        # translate with --flow-file {flow} --immediates {immediates}, compile natively
      "run": "build/edges/host {frames} {inputs}",   # one scenario; {frames} {inputs} {state} {dir} substituted
      "flow": "edges/flow.txt", "immediates": "edges/immediates.json", "dir": "edges/runs",
      "values": [200, 340], "mn": ["cmp", "cmpi", "add", "addi", "sub", "subi", "move"], "exclude": ["1853c"],
      "shift": 64, "jobs": 4, "outcome": "^frames .*$", "metrics": {"deleted_in_band": "deleted (\\\\d+)"},
      "scenario": {"state": "cap/l1", "frames": 4000, "inputs": "rc/fuzz_23.txt", "env": {}}
    }

Paths in the config are relative to the config's folder. No game data.
"""
import json
import os
import re
import shlex
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

KNOBS_ENV, READS_ENV = 'AREK_KNOBS', 'AREK_KNOBS_OUT'
FOLDS = re.compile(r'--operand \$([0-9a-f]+): .*(?:folds its immediate|has no immediate)')


OTHER = re.compile(r'^(cmpi?|cmpa|addi?|adda|subi?|suba)\.([bwl]) #-?\$?[0-9a-f]+,([da])([0-7])$')


def runtime(n):
    """The C every knob needs, as ``declare`` lines (one line each): the values from $AREK_KNOBS ("k=v,k=v"), the reads
    counted and written to $AREK_KNOBS_OUT at exit ("k reads [lo hi]" lines, read knobs only; lo / hi: the range of the
    register the constant meets - cmp / add / sub #n,Dn / An - over the run)."""
    n = max(1, n)
    return [
        '#include <stdio.h>',
        '#include <stdlib.h>',
        'static int32_t arek_knob_v[%d], arek_knob_lo[%d], arek_knob_hi[%d]; static uint32_t arek_knob_n[%d], arek_knob_m[%d];' % (n, n, n, n, n),
        'static inline int32_t arek_knob(int k) { arek_knob_n[k]++; return arek_knob_v[k]; }',
        'static inline int32_t arek_knob_d(int k, int32_t o) { if (!arek_knob_m[k]++ || o < arek_knob_lo[k]) arek_knob_lo[k] = o; '
        'if (arek_knob_m[k] == 1 || o > arek_knob_hi[k]) arek_knob_hi[k] = o; return arek_knob(k); }',
        'static void arek_knob_dump(void) { const char *p = getenv("%s"); FILE *f; int k; if (!p || !(f = fopen(p, "w"))) return; '
        'for (k = 0; k < %d; k++) if (arek_knob_n[k]) { if (arek_knob_m[k]) fprintf(f, "%%d %%u %%d %%d\\n", k, arek_knob_n[k], arek_knob_lo[k], arek_knob_hi[k]); '
        'else fprintf(f, "%%d %%u\\n", k, arek_knob_n[k]); } fclose(f); }' % (READS_ENV, n),
        '__attribute__((constructor)) static void arek_knob_init(void) { const char *e = getenv("%s"); char *q; long k, v; '
        'while (e && *e) { k = strtol(e, &q, 10); if (*q != \'=\') break; v = strtol(q + 1, &q, 0); '
        'if (k >= 0 && k < %d) arek_knob_v[k] = (int32_t)v; if (*q != \',\') break; e = q + 1; } atexit(arek_knob_dump); }' % (KNOBS_ENV, n),
    ]


def candidates(imms, lo, hi, mn=None, exclude=()):
    """The immediates (``arek recomp --immediates``) whose value - unsigned or signed in their size - lies in [lo, hi],
    of the mnemonics ``mn`` (all when None), without the addresses in ``exclude``."""
    ex = {int(str(x), 16) for x in exclude}
    out = []
    for r in imms:
        a = int(r['addr'], 16)
        if a in ex or (mn and r['mn'] not in mn):
            continue
        if lo <= r['imm'] <= hi or lo <= r['simm'] <= hi:
            out.append(dict(r))
    return out


def knob_expr(c, k):
    """A candidate's operand: its constant plus its knob; a constant that meets a register (cmp / add / sub #n,Dn / An)
    also records the register's range, signed in the instruction's size, before the instruction changes it."""
    m = OTHER.match(c['text'])
    if m:
        reg = 'm->%s[%s]' % (m.group(3), m.group(4))
        cast = {'b': 'int8_t', 'w': 'int16_t', 'l': 'int32_t'}[m.group(2)]
        return '(0x%xu + (uint32_t)arek_knob_d(%d, (int32_t)(%s)%s))' % (c['imm'], k, cast, reg)
    return '(0x%xu + (uint32_t)arek_knob(%d))' % (c['imm'], k)


def flow_lines(cands):
    """The flow file: the knobs' runtime, then every candidate's operand as its constant plus its knob."""
    lines = ['# arek edges: every candidate operand + its knob (AREK_KNOBS="k=v"); generated, do not edit']
    lines += ['declare ' + d for d in runtime(len(cands))]
    lines += ['operand %s=%s' % (c['addr'], knob_expr(c, k)) for k, c in enumerate(cands)]
    return '\n'.join(lines) + '\n'


class Project:
    def __init__(self, conf_path):
        self.path = Path(conf_path).resolve()
        self.root = self.path.parent
        c = json.loads(self.path.read_text())
        self.c = c
        self.build_cmd, self.run_cmd = c['build'], c['run']
        p = lambda k, d: self.root / c.get(k, d)
        self.flow, self.imms, self.dir = p('flow', 'edges/flow.txt'), p('immediates', 'edges/immediates.json'), p('dir', 'edges/runs')
        self.values = tuple(c.get('values', (200, 340)))
        self.mn = set(c['mn']) if c.get('mn') else None
        self.exclude = list(c.get('exclude', []))
        self.shift = int(c.get('shift', 64))
        self.jobs = int(c.get('jobs', max(1, (os.cpu_count() or 2) // 2)))
        self.outcome = re.compile(c['outcome'], re.M) if c.get('outcome') else None
        self.metrics = {k: re.compile(v, re.M) for k, v in (c.get('metrics') or {}).items()}
        self.scenario = c.get('scenario', {})

    def sh(self, cmd, env=None, timeout=None):
        e = dict(os.environ)
        e.update({k: str(v) for k, v in (self.scenario.get('env') or {}).items()})
        e.update(env or {})
        return subprocess.run(cmd, shell=True, cwd=str(self.root), env=e, capture_output=True, text=True, timeout=timeout)

    def write_flow(self, cands):
        self.flow.parent.mkdir(parents=True, exist_ok=True)
        self.flow.write_text(flow_lines(cands))

    def build(self, cands, log, rounds=40):
        """Write the flow, build; a candidate the translation refuses to replace (its constant is folded into the code)
        is dropped and the build repeated. Returns the candidates that are in the build."""
        cands = list(cands)
        for _ in range(rounds):
            self.write_flow(cands)
            r = self.sh(self.build_cmd)
            if r.returncode == 0:
                return cands
            out = r.stdout + r.stderr
            bad = {m.group(1).lstrip('0') or '0' for m in FOLDS.finditer(out)}
            if not bad:
                raise RuntimeError('the build failed:\n' + out[-3000:])
            log('edges: %d operand(s) cannot be replaced, dropped: %s' % (len(bad), ', '.join(sorted(bad))))
            cands = [c for c in cands if c['addr'].lstrip('0') not in bad]
        raise RuntimeError('the build still refuses after %d rounds' % rounds)

    def run_one(self, name, knobs, timeout=None):
        """One run of the scenario: its output, the outcome text, the metrics, the knobs read (k -> reads)."""
        d = self.dir / name
        d.mkdir(parents=True, exist_ok=True)
        reads = d / 'reads.txt'
        if reads.exists():
            reads.unlink()
        sc = self.scenario
        cmd = self.run_cmd.format(state=shlex.quote(str(sc.get('state', ''))), frames=sc.get('frames', 0),
                                  inputs=shlex.quote(str(sc.get('inputs', ''))), dir=shlex.quote(str(d)), name=name)
        r = self.sh(cmd, {KNOBS_ENV: ','.join('%d=%d' % kv for kv in sorted(knobs.items())), READS_ENV: str(reads)}, timeout)
        out = r.stdout + r.stderr
        (d / 'out.txt').write_text(out)
        if self.outcome:
            m = self.outcome.findall(r.stdout + r.stderr)
            oc = '\n'.join(x if isinstance(x, str) else ' '.join(x) for x in m)
        else:
            lines = [x for x in r.stdout.splitlines() if x.strip()]
            oc = lines[-1] if lines else ''
        mets = {}
        for k, rx in self.metrics.items():
            m = rx.findall(out)
            mets[k] = float(m[-1]) if m else None
        rd, other = {}, {}
        if reads.exists():
            for line in reads.read_text().split('\n'):
                w = line.split()
                if w:
                    rd[int(w[0])] = int(w[1])
                    if len(w) == 4:
                        other[int(w[0])] = [int(w[2]), int(w[3])]
        return {'rc': r.returncode, 'outcome': oc, 'metrics': mets, 'reads': rd, 'other': other}

    def scan(self, log=print, only=None, shift=None, list_only=False):
        """The whole loop; returns the report dict (and writes it beside the runs as report.json)."""
        shift = self.shift if shift is None else shift
        log('edges: building with no candidate to list the constants')
        self.build([], log)
        if not self.imms.exists():
            raise RuntimeError('the build wrote no %s: give the translation --immediates %s' % (self.imms, self.imms))
        imms = json.loads(self.imms.read_text())
        cands = candidates(imms, self.values[0], self.values[1], self.mn, self.exclude)
        if only:
            want = {int(str(x), 16) for x in only}
            cands = [c for c in cands if int(c['addr'], 16) in want]
        log('edges: %d constants in the code, %d in %d..%d%s' % (len(imms), len(cands), self.values[0], self.values[1],
                                                                  ' of ' + ', '.join(sorted(self.mn)) if self.mn else ''))
        if list_only:
            return {'immediates': len(imms), 'candidates': cands, 'shift': shift, 'runs': []}
        cands = self.build(cands, log)
        base = self.run_one('base', {})
        log('edges: baseline rc %d, outcome %r, %d of %d candidates executed' % (base['rc'], base['outcome'][:80], len(base['reads']), len(cands)))
        live = [k for k in range(len(cands)) if base['reads'].get(k)]

        def one(k):
            r = self.run_one('k%03d' % k, {k: shift})
            return k, r
        rows = []
        with ThreadPoolExecutor(max_workers=self.jobs) as ex:
            for k, r in ex.map(one, live):
                c = cands[k]
                rows.append({'knob': k, 'addr': c['addr'], 'text': c['text'], 'imm': c['imm'], 'reads': base['reads'][k],
                             'other': base['other'].get(k),
                             'rc': r['rc'], 'changed': r['outcome'] != base['outcome'] or r['rc'] != base['rc'],
                             'outcome': r['outcome'], 'metrics': r['metrics']})
                log('edges: %s %-28s reads %-8d %s' % (c['addr'], c['text'][:28], base['reads'][k], 'CHANGED' if rows[-1]['changed'] else 'same'))
        rep = {'immediates': len(imms), 'candidates': len(cands), 'executed': len(live), 'shift': shift,
               'base': {'rc': base['rc'], 'outcome': base['outcome'], 'metrics': base['metrics']},
               'unexecuted': [c['addr'] for k, c in enumerate(cands) if k not in base['reads']],
               'runs': sorted(rows, key=lambda r: (not r['changed'], r['addr']))}
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / 'report.json').write_text(json.dumps(rep, indent=1) + '\n')
        return rep


def format_report(rep):
    if not rep.get('runs') and 'executed' not in rep:
        return '\n'.join('%s  %-32s %d' % (c['addr'], c['text'], c['simm']) for c in rep['candidates']) + \
            '\n%d candidates of %d constants' % (len(rep['candidates']), rep['immediates'])
    names = sorted({k for r in rep['runs'] for k in r['metrics']} | set(rep['base']['metrics']))
    out = ['shift %+d; %d constants, %d candidates, %d executed in the scenario; baseline outcome: %s' % (
        rep['shift'], rep['immediates'], rep['candidates'], rep['executed'], rep['base']['outcome'][:100] or '(empty)')]
    if names:
        out.append('metrics (baseline): ' + ', '.join('%s %s' % (n, rep['base']['metrics'].get(n)) for n in names))
    for r in rep['runs']:
        m = ''.join(' %s %s' % (n, r['metrics'].get(n)) for n in names if r['metrics'].get(n) != rep['base']['metrics'].get(n))
        o = ' meets %d..%d' % tuple(r['other']) if r.get('other') else ''
        out.append('%s %-8s %-30s reads %-9d%s%s%s' % (r['addr'], 'CHANGED' if r['changed'] else 'same', r['text'][:30], r['reads'], o,
                                                         ' rc %d' % r['rc'] if r['rc'] != rep['base']['rc'] else '', m))
    ch = sum(1 for r in rep['runs'] if r['changed'])
    out.append('%d of %d executed candidates change the scenario at %+d' % (ch, rep['executed'], rep['shift']))
    return '\n'.join(out)
