"""Call / data cross references from ``m68k-elf-objdump`` text (from ``xref.py``).

Input is the text produced by e.g.::

    m68k-elf-objdump -D -b binary -m 68000 --adjust-vma=0xc0 main.bin > prog.txt

Symbols come from an optional JSON ``{"code": {"hexaddr": "name"}, "data": {...}}``.
"""
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

LINE = re.compile(r"^\s+([0-9a-f]+):\t")
CALL = re.compile(r"\t(?:bsr[sw]?|jsr)\s+0x([0-9a-f]+)")
LEA = re.compile(r"lea\s+(?:%pc@\()?0x([0-9a-f]+)\)?,")


def load_syms(path):
    if not path:
        return {}
    syms = json.loads(Path(path).read_text())
    name = {int(k, 16): v for k, v in syms.get("code", {}).items()}
    name.update({int(k, 16): v for k, v in syms.get("data", {}).items()})
    return name


class Xref:
    def __init__(self, text, names=None):
        self.names = names or {}
        self.calls = defaultdict(set)      # target -> {callers}
        self.leas = defaultdict(set)       # target -> {sites}
        self.callees = defaultdict(set)    # caller -> {targets}
        for ln in text.splitlines():
            m = LINE.match(ln)
            if not m:
                continue
            cur = int(m.group(1), 16)
            m2 = CALL.search(ln)
            if m2:
                t = int(m2.group(1), 16)
                self.calls[t].add(cur)
                self.callees[cur].add(t)
                continue
            m2 = LEA.search(ln)
            if m2:
                self.leas[int(m2.group(1), 16)].add(cur)

    @classmethod
    def from_file(cls, prog, syms=None):
        return cls(Path(prog).read_text(), load_syms(syms))

    def nm(self, a):
        return "%s(0x%x)" % (self.names[a], a) if a in self.names else "0x%x" % a

    def callers(self, target):
        return sorted(set(self.calls.get(target, set())) | set(self.leas.get(target, set())))

    def callees_in(self, lo, hi):
        out, seen = [], set()
        for src in sorted(self.callees):
            if lo <= src < hi:
                for t in sorted(self.callees[src]):
                    if t not in seen:
                        seen.add(t)
                        out.append((src, t))
        return out

    def top(self, n=40):
        cnt = Counter({a: len(s) for a, s in self.calls.items()})
        return cnt.most_common(n)

    def top_data(self, n=15):
        cnt = Counter({a: len(s) for a, s in self.leas.items()})
        return cnt.most_common(n)

    def summary(self, top=40):
        L = ["routines called via bsr/jsr: %d, call sites: %d"
             % (len(self.calls), sum(len(s) for s in self.calls.values())),
             "most called routines (shared utilities):"]
        L += ["  %3dx  %s" % (n, self.nm(a)) for a, n in self.top(top)]
        L.append("")
        L.append("most referenced data (lea):")
        L += ["  %3dx  %s" % (n, self.nm(a)) for a, n in self.top_data()]
        return "\n".join(L)


def disrange(text, lo, hi, width=78):
    """Lines of an objdump listing whose address lies in [lo, hi) (``disrange.py``)."""
    out = []
    for line in text.splitlines():
        m = re.match(r'\s*([0-9a-f]+):', line)
        if m and lo <= int(m.group(1), 16) < hi:
            out.append(line.rstrip()[:width])
    return out
