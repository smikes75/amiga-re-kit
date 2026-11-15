"""arek discover (kit 1.0.81): the run-time half of making a translation complete - run the game's scenarios on the
translation built with -DAREK_DISCOVER, take the first target the translation does not know, put it where the
project's build reads it, build again, run the same scenario with the same input again, until it runs clean.

The five rebuilds before it (Xenon 2, SWIV, Turrican II, Superfrog, Alien Breed II) each wrote this loop by hand; their
lessons are its rules: only the first unknown of a run counts (later ones run garbage), every round has a fresh folder
(a stale record gave false greens), the same scenario and the same input until it is clean, a target outside the code
or odd is a wild jump to report and never a root, and "clean" means the run reached its frames, not only "no record".

The project keeps its build: the driver only appends to its files and runs its commands.

    {
      "build": "sh tools/build_discover.sh",      # translate + compile with -DAREK_DISCOVER; reads the files below
      "run": "build/host {state} {frames} {inputs}",   # one scenario; {name} {state} {frames} {inputs} {dir} substituted
      "roots": "discover/roots.txt",             # targets in the resident code, one hex address a line (appended)
      "module_roots": "discover/module_roots.txt",   # targets inside an overlay area (appended)
      "modules": "discover/modules.json",        # [{fp, base, size, entry, key, dump}] - unknown modules and their dumps
      "code": [["400", "40400"]],                # resident code ranges [lo, hi) (hex)
      "areas": [["54e00", "2b200"]],             # overlay areas [base, size] (hex)
      "dir": "discover/runs",                    # a fresh folder per round under it
      "rounds": 40,                              # per scenario
      "clean": "records",                        # optional: a regex the clean run's output must show (it reached its end)
      "scenarios": [{"name": "level1", "state": "cap/l1", "frames": 3000,
                     "inputs": {"fuzz": {"seed": 7, "start": 300, "keys": "RLUDF"}}, "env": {"GAME_LEVEL": "1"}}]
    }

A run ends one of four ways: exit 0 (clean when the output matches "clean", if given), exit 40 with a routine record,
exit 41 with a module record (its area dumped beside the record), anything else (a crash, a wild jump the runtime
caught itself) - reported with the output's tail. Paths in the config are relative to the config's folder.
"""
import json
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path

from . import fuzz

EXIT_ROUTINE, EXIT_MODULE = 40, 41


def _hex(v):
    return int(v, 16) if isinstance(v, str) else int(v)


class Project:
    def __init__(self, conf_path):
        self.path = Path(conf_path).resolve()
        self.root = self.path.parent
        c = json.loads(self.path.read_text())
        self.c = c
        self.build_cmd, self.run_cmd = c['build'], c['run']
        p = lambda k, d: (self.root / c.get(k, d))
        self.roots, self.module_roots, self.modules = p('roots', 'discover/roots.txt'), p('module_roots', 'discover/module_roots.txt'), p('modules', 'discover/modules.json')
        self.dir = p('dir', 'discover/runs')
        self.code = [(_hex(a), _hex(b)) for a, b in c.get('code', [])]
        self.areas = [(_hex(a), _hex(a) + _hex(n)) for a, n in c.get('areas', [])]
        self.rounds = int(c.get('rounds', 40))
        self.clean = re.compile(c['clean']) if c.get('clean') else None
        self.scenarios = c.get('scenarios', [])

    # -- the project's files
    def known(self, path):
        if not path.exists():
            return set()
        return {int(x.split('#')[0].strip(), 16) for x in path.read_text().splitlines() if x.split('#')[0].strip()}

    def add_root(self, path, addr, why):
        """One bare hex address a line (projects read the file as whitespace-separated words); where it came from goes
        to found.jsonl beside the runs."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a') as f:
            f.write('%06x\n' % addr)
        self.dir.mkdir(parents=True, exist_ok=True)
        with (self.dir.parent / 'found.jsonl').open('a') as f:
            f.write(json.dumps({'addr': '%06x' % addr, 'file': str(path.relative_to(self.root)), 'why': why}) + '\n')

    def module_list(self):
        return json.loads(self.modules.read_text()) if self.modules.exists() else []

    def add_module(self, rec, dump_from):
        mods = self.module_list()
        dst = self.modules.parent / 'modules' / Path(rec['dump']).name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(dump_from, dst)
        mods.append({k: rec[k] for k in ('fp', 'base', 'size', 'entry', 'key')} | {'dump': str(dst.relative_to(self.root))})
        self.modules.write_text(json.dumps(mods, indent=1) + '\n')

    # -- where a target belongs
    def place(self, t):
        """'area' (inside an overlay area), 'code' (a resident range) or None (a wild jump: odd, or outside both)."""
        if t & 1:
            return None
        if any(a <= t < b for a, b in self.areas):
            return 'area'
        if any(a <= t < b for a, b in self.code):
            return 'code'
        return None

    # -- one round
    def inputs_file(self, sc, d):
        i = sc.get('inputs')
        if not i:
            return ''
        if isinstance(i, str):
            return str(self.root / i)
        z = dict(i['fuzz'])
        lines = fuzz.inputs(seed=int(z.pop('seed')), frames=int(z.pop('frames', sc['frames'])),
                            hold=tuple(int(x) for x in str(z.pop('hold', '3:22')).split(':')), **{k: (float(v) if k == 'rest' else v if k == 'keys' else int(v)) for k, v in z.items()})
        f = d / 'inputs.txt'
        f.write_text('\n'.join(lines) + '\n')
        return str(f)

    def run_once(self, sc, n, log):
        d = self.dir / ('%s-%03d' % (sc['name'], n))
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
        rec = d / 'unknown.jsonl'
        env = {**os.environ, **{k: str(v) for k, v in sc.get('env', {}).items()},
               'AREK_UNKNOWN': str(rec), 'AREK_COVER': str(d / 'cover.txt')}
        q = lambda v: shlex.quote(str(v)) if str(v) else "''"     # the config's commands are the project's shell lines; the values are quoted
        cmd = self.run_cmd.format(name=q(sc['name']), state=q(sc.get('state', '')), frames=q(sc.get('frames', '')),
                                  inputs=q(self.inputs_file(sc, d)), dir=q(d))
        p = subprocess.run(cmd, shell=True, cwd=self.root, env=env, capture_output=True, text=True)
        (d / 'output.txt').write_text(p.stdout + p.stderr)
        recs = [json.loads(x) for x in rec.read_text().splitlines() if x.strip()] if rec.exists() else []
        return d, p.returncode, recs, p.stdout + p.stderr

    def build(self, log):
        p = subprocess.run(self.build_cmd, shell=True, cwd=self.root, capture_output=True, text=True)
        if p.returncode:
            return (p.stdout + p.stderr)[-2000:]
        return None

    def scenario(self, sc, log=print):
        """Run one scenario until clean. Returns {name, status, rounds, roots, module_roots, modules, wild, last}."""
        out = {'name': sc['name'], 'status': None, 'rounds': 0, 'roots': [], 'module_roots': [], 'modules': [], 'wild': None, 'last': None}
        added = set()
        for n in range(1, self.rounds + 1):
            out['rounds'] = n
            d, rc, recs, text = self.run_once(sc, n, log)
            out['last'] = str(d.relative_to(self.root))
            if rc == 0 and not recs:
                if self.clean and not self.clean.search(text):
                    out['status'] = 'ended early'
                    out['tail'] = text[-1000:]
                else:
                    out['status'] = 'clean'
                log('%s: clean after %d run(s)' % (sc['name'], n))
                return out
            if rc == EXIT_ROUTINE and recs and recs[0]['kind'] == 'routine':
                r = recs[0]
                t = int(r['target'], 16)
                where = self.place(t)
                if where is None:
                    out['status'], out['wild'] = 'wild jump', r
                    log('%s: a wild jump to %06x from %s (%s line %s) - not a root; stopped' % (sc['name'], t, r['fn'], r['file'], r['line']))
                    return out
                path = self.module_roots if where == 'area' else self.roots
                if t in added or t in self.known(path):
                    out['status'], out['wild'] = 'not taken', r
                    log('%s: %06x again after it was added - the build did not take it; stopped' % (sc['name'], t))
                    return out
                added.add(t)
                self.add_root(path, t, '%s run %d: %s line %s' % (sc['name'], n, r['fn'], r['line']))
                out['module_roots' if where == 'area' else 'roots'].append('%06x' % t)
                log('%s run %d: %06x (%s) from %s line %s' % (sc['name'], n, t, 'module root' if where == 'area' else 'root', r['fn'], r['line']))
            elif rc == EXIT_MODULE and recs and recs[0]['kind'] == 'module':
                r = recs[0]
                if any(m['fp'] == r['fp'] for m in self.module_list()):
                    out['status'], out['wild'] = 'not taken', r
                    log('%s: module %s again after it was registered - the build did not take it; stopped' % (sc['name'], r['fp']))
                    return out
                self.add_module(r, d / Path(r['dump']).name)
                out['modules'].append(r['fp'])
                log('%s run %d: module at %s (entry %s, fp %s) dumped' % (sc['name'], n, r['base'], r['entry'], r['fp']))
            else:
                out['status'] = 'failed'
                out['exit'] = rc
                out['tail'] = text[-1000:]
                log('%s run %d: exit %d without a record - see %s/output.txt' % (sc['name'], n, rc, out['last']))
                return out
            err = self.build(log)
            if err:
                out['status'] = 'build failed'
                out['tail'] = err
                log('%s: the build failed:\n%s' % (sc['name'], err[-600:]))
                return out
        out['status'] = 'limit'
        log('%s: still not clean after %d runs' % (sc['name'], self.rounds))
        return out


def run(conf, only=None, rounds=None, build_first=True, log=print):
    """Every scenario of the config (or those named in ``only``) until clean. Returns the list of scenario results."""
    pr = Project(conf)
    if rounds:
        pr.rounds = rounds
    if build_first:
        err = pr.build(log)
        if err:
            return [{'name': '(build)', 'status': 'build failed', 'tail': err}]
    res = []
    for sc in pr.scenarios:
        if only and sc['name'] not in only:
            continue
        r = pr.scenario(sc, log)
        res.append(r)
        if r['status'] == 'build failed':
            break                      # the project's build broke: every next run would run the old translation
    return res
