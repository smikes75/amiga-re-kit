"""A knowledge base of the rebuilds: records of what was measured and learned, found by the symptom an agent sees.

The base itself is a folder outside the kit (``AREK_KB``, a private repository of the user's); the kit only reads,
searches and writes proposals. A record is one Markdown file ``records/<kind>/<id>.md`` with a small header and
sections::

    ---
    id: kit-recomp-push-rts
    kind: symptom
    title: move.l X,-(a7); rts translated as a plain return
    status: fixed
    fixed_in: 1.0.24
    games: [xenon2]
    tags: [recomp, stack]
    ---
    ## Symptom
    ...

Kinds: ``symptom`` (a problem and its fix), ``fact`` (a game or engine fact), ``procedure`` (how to do something),
``game`` (a game's card). Status: ``open``, ``fixed``, ``verified``, ``hypothesis``, ``superseded``. Lists are written
``[a, b]``. The header is a strict subset of YAML (no dependency). Search is BM25 over the title, the tags, the
symptom and the rest, the title and the symptom weighted up - an agent searches with the words of the log it sees.
Proposals go to ``inbox/<source>/`` and become records after review (``promote``). No game data in a record: a long
hex dump is refused by ``check``.
"""
import math
import os
import re
import shutil

KINDS = ('symptom', 'fact', 'procedure', 'game')
STATUS = ('open', 'fixed', 'verified', 'hypothesis', 'superseded')
LISTS = ('games', 'disks', 'tags', 'sources')
REQUIRED = ('id', 'kind', 'title', 'status')
SECTIONS = ('Symptom', 'Cause', 'Check', 'Resolution', 'Evidence', 'Notes')
ID = re.compile(r'^[a-z0-9][a-z0-9-]{2,80}$')
HEXDUMP = re.compile(r'(?:[0-9a-fA-F]{2}[ :]?){48,}')          # 48+ bytes in a row: data, not a signature
WEIGHT = {'title': 3.0, 'tags': 2.0, 'symptom': 2.0, 'games': 1.5, 'body': 1.0}


class KBError(ValueError):
    pass


def root(path=None):
    """The base folder: ``path``, else ``$AREK_KB``."""
    p = path or os.environ.get('AREK_KB')
    if not p:
        raise KBError('no knowledge base: set AREK_KB to its folder (or pass --kb)')
    p = os.path.abspath(os.path.expanduser(p))
    if not os.path.isdir(p):
        raise KBError('knowledge base folder not found: %s' % p)
    return p


def _value(v):
    v = v.strip()
    if v.startswith('[') and v.endswith(']'):
        return [x.strip().strip('"\'') for x in v[1:-1].split(',') if x.strip()]
    if len(v) >= 2 and v[0] == v[-1] and v[0] in '"\'':
        return v[1:-1]
    return v


def parse(text, path=''):
    """A record's text -> dict: the header fields, ``sections`` {name: text}, ``body`` (all text below the header)."""
    if not text.startswith('---'):
        raise KBError('%s: no header (the file starts with ---)' % path)
    end = text.find('\n---', 3)
    if end < 0:
        raise KBError('%s: the header is not closed (---)' % path)
    rec = {}
    for n, line in enumerate(text[3:end].split('\n'), 1):
        line = line.split(' #', 1)[0].rstrip() if ' #' in line else line.rstrip()
        if not line.strip():
            continue
        if ':' not in line:
            raise KBError('%s: header line %d is not "key: value"' % (path, n))
        k, v = line.split(':', 1)
        rec[k.strip()] = _value(v)
    for k in LISTS:
        v = rec.get(k, [])
        rec[k] = v if isinstance(v, list) else ([v] if v else [])
    body = text[end + 4:].lstrip('\n')
    rec['body'] = body
    secs, cur = {}, None
    for line in body.split('\n'):
        m = re.match(r'^##\s+(.+?)\s*$', line)
        if m:
            cur = m.group(1)
            secs[cur] = ''
        elif cur:
            secs[cur] += line + '\n'
    rec['sections'] = {k: v.strip() for k, v in secs.items()}
    rec['path'] = path
    return rec


def render(rec):
    """A dict -> the record's text (the inverse of ``parse`` for the fields it knows)."""
    keys = ['id', 'kind', 'title', 'status', 'fixed_in', 'games', 'engine', 'disks', 'kit', 'tags', 'sources', 'date']
    head = []
    for k in keys + sorted(k for k in rec if k not in keys and k not in ('body', 'sections', 'path')):
        if k not in rec:
            continue
        v = rec[k]
        head.append('%s: %s' % (k, '[%s]' % ', '.join(v) if isinstance(v, list) else v))
    body = rec.get('body')
    if not body:
        body = '\n'.join('## %s\n%s\n' % (s, rec['sections'][s]) for s in SECTIONS if rec.get('sections', {}).get(s))
    return '---\n%s\n---\n%s' % ('\n'.join(head), body if body.endswith('\n') else body + '\n')


def validate(rec, path=''):
    """The problems of one record (empty list = fine)."""
    out = []
    for k in REQUIRED:
        if not rec.get(k):
            out.append('missing %s' % k)
    if rec.get('id') and not ID.match(rec['id']):
        out.append('id %r: lower case, digits and dashes, 3-81 characters' % rec['id'])
    if rec.get('kind') and rec['kind'] not in KINDS:
        out.append('kind %r: one of %s' % (rec['kind'], ', '.join(KINDS)))
    if rec.get('status') and rec['status'] not in STATUS:
        out.append('status %r: one of %s' % (rec['status'], ', '.join(STATUS)))
    if path and rec.get('id') and os.path.splitext(os.path.basename(path))[0] != rec['id']:
        out.append('the file name is not the id')
    if rec.get('kind') == 'symptom' and not rec.get('sections', {}).get('Symptom'):
        out.append('a symptom record needs a "## Symptom" section')
    if HEXDUMP.search(rec.get('body', '')):
        out.append('a long hex dump in the body - game data does not belong here (a signature is at most 16 bytes)')
    return out


def _files(base, inbox):
    dirs = [os.path.join(base, 'records')] + ([os.path.join(base, 'inbox')] if inbox else [])
    for d in dirs:
        for dp, _, fs in os.walk(d):
            for f in sorted(fs):
                if f.endswith('.md'):
                    yield os.path.join(dp, f)


def load(path=None, inbox=False):
    """Every record (and with ``inbox`` the proposals), parsed; a file that does not parse raises."""
    base = root(path)
    out = []
    for f in _files(base, inbox):
        with open(f, encoding='utf-8') as fh:
            rec = parse(fh.read(), os.path.relpath(f, base))
        rec['inbox'] = rec['path'].startswith('inbox' + os.sep)
        out.append(rec)
    return out


def check(path=None):
    """{'records': n, 'inbox': n, 'problems': [(path, problem)]}: parse errors, field problems, duplicate ids."""
    base = root(path)
    probs, seen, n, ni = [], {}, 0, 0
    for f in _files(base, True):
        rel = os.path.relpath(f, base)
        try:
            with open(f, encoding='utf-8') as fh:
                rec = parse(fh.read(), rel)
        except KBError as e:
            probs.append((rel, str(e)))
            continue
        ni += rel.startswith('inbox')
        n += not rel.startswith('inbox')
        probs += [(rel, p) for p in validate(rec, f)]
        if not rel.startswith('inbox') and rel.split(os.sep)[1] != rec.get('kind'):
            probs.append((rel, 'records/<kind>/ folder is not the kind %r' % rec.get('kind')))
        if rec.get('id') in seen:
            probs.append((rel, 'duplicate id (also %s)' % seen[rec['id']]))
        seen.setdefault(rec.get('id'), rel)
    return {'records': n, 'inbox': ni, 'problems': probs}


_WORD = re.compile(r'[$#]?[0-9a-z_.]+')


def tokens(text):
    """Lower-case words; ``$5920`` and ``0x5920`` both give ``5920``; dotted mnemonics also split (``move.l`` ->
    ``move.l``, ``move``)."""
    out = []
    for w in _WORD.findall(str(text).lower()):
        w = w.lstrip('$#')
        if w.startswith('0x'):
            w = w[2:]
        w = w.strip('.')
        if len(w) < 2:
            continue
        out.append(w)
        if '.' in w:
            out += [p for p in w.split('.') if len(p) >= 2]
    return out


def _fields(rec):
    rest = rec.get('body', '')
    return {'title': rec.get('title', ''), 'tags': ' '.join(rec.get('tags', [])), 'games': ' '.join(rec.get('games', []) + [rec.get('engine', '')]),
            'symptom': rec.get('sections', {}).get('Symptom', ''), 'body': rest + ' ' + rec.get('id', '').replace('-', ' ')}


def search(records, query, game=None, kind=None, status=None, limit=10):
    """The best records for ``query`` (BM25 per field, weighted), filtered by game (also matches the engine), kind
    and status (an engine family: ``team17`` also finds ``team17-ab`` and the reverse); each hit: id, kind, title, status,
    games, score, path and a snippet around the first matching word."""
    q = tokens(query)
    def family(e):                                         # an engine family: team17 covers team17-ab, and team17-ab finds team17's records
        return bool(e) and (game == e or game.startswith(e + '-') or e.startswith(game + '-'))
    pool = [r for r in records if (not kind or r.get('kind') == kind) and (not status or r.get('status') == status)
            and (not game or game in r.get('games', []) or family(r.get('engine')))]
    if not q or not pool:
        return []
    docs = [{f: tokens(t) for f, t in _fields(r).items()} for r in pool]
    N = len(docs)
    df = {}
    for d in docs:
        for w in set(w for f in d.values() for w in f):
            df[w] = df.get(w, 0) + 1
    avg = {f: (sum(len(d[f]) for d in docs) / N) or 1 for f in WEIGHT}
    k1, b = 1.2, 0.75
    hits = []
    for r, d in zip(pool, docs):
        s = 0.0
        for w in set(q):
            if w not in df:
                continue
            idf = math.log(1 + (N - df[w] + 0.5) / (df[w] + 0.5))
            for f, wt in WEIGHT.items():
                tf = d[f].count(w)
                if tf:
                    s += wt * idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * len(d[f]) / avg[f]))
        if s > 0:
            hits.append((s, r))
    hits.sort(key=lambda h: (-h[0], h[1].get('id', '')))
    out = []
    for s, r in hits[:limit]:
        text = re.sub(r'\s+', ' ', r.get('body', ''))
        low, pos = text.lower(), -1
        for w in q:
            pos = low.find(w)
            if pos >= 0:
                break
        snip = text[max(0, pos - 60):pos + 140] if pos >= 0 else text[:200]
        out.append({'id': r.get('id'), 'kind': r.get('kind'), 'title': r.get('title'), 'status': r.get('status'),
                    'games': r.get('games', []), 'score': round(s, 2), 'path': r.get('path'), 'snippet': snip.strip()})
    return out


def get(records, rid):
    for r in records:
        if r.get('id') == rid:
            return r
    raise KBError('no record %r' % rid)


def add(text, source, path=None):
    """A proposal (the record's text) into ``inbox/<source>/<id>.md``; refused when it does not validate or the id is
    taken by a record. Returns the path."""
    base = root(path)
    if not re.match(r'^[a-z0-9][a-z0-9-]{1,40}$', source or ''):
        raise KBError('source %r: a short slug (the game or the session)' % source)
    rec = parse(text, 'proposal')
    probs = validate(rec)
    if probs:
        raise KBError('the proposal does not validate: ' + '; '.join(probs))
    for f in _files(base, False):
        if os.path.splitext(os.path.basename(f))[0] == rec['id']:
            raise KBError('id %r is taken (%s) - choose another or edit that record' % (rec['id'], os.path.relpath(f, base)))
    d = os.path.join(base, 'inbox', source)
    os.makedirs(d, exist_ok=True)
    out = os.path.join(d, rec['id'] + '.md')
    with open(out, 'w', encoding='utf-8') as f:
        f.write(text if text.endswith('\n') else text + '\n')
    return out


def promote(rel, path=None):
    """A reviewed proposal ``inbox/<source>/<id>.md`` -> ``records/<kind>/<id>.md``. Returns the new path."""
    base = root(path)
    src = os.path.join(base, rel)
    with open(src, encoding='utf-8') as f:
        rec = parse(f.read(), rel)
    probs = validate(rec, src)
    if probs:
        raise KBError('%s does not validate: %s' % (rel, '; '.join(probs)))
    dst = os.path.join(base, 'records', rec['kind'], rec['id'] + '.md')
    if os.path.exists(dst):
        raise KBError('%s exists' % os.path.relpath(dst, base))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.move(src, dst)
    return dst


def stats(records):
    by = {}
    for r in records:
        for k in ('kind', 'status'):
            by.setdefault(k, {}).setdefault(r.get(k), 0)
            by[k][r.get(k)] += 1
        for g in r.get('games', []):
            by.setdefault('games', {}).setdefault(g, 0)
            by['games'][g] += 1
    return {'records': len(records), **by}
