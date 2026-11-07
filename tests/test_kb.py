"""arek.kb (1.0.25): the knowledge base of the rebuilds - parse, validate, search by the symptom, propose, promote.
Synthetic records only."""
import json

import pytest

from arek import cli, kb

PUSH_RTS = """---
id: kit-recomp-push-rts
kind: symptom
title: move.l X,-(a7); rts translated as a plain return
status: fixed
fixed_in: 1.0.24
games: [xenon2]
tags: [recomp, stack, rts]
sources: [Xenon/docs/KIT-GAPS.md#4]
date: 2026-11-07
---
## Symptom
host_trace diverges from the original after ~140 passes and crashes at a nonsense address; resident $5920.
## Cause
The translation's rts returned to the C caller and dropped the pushed target.
## Resolution
Kit 1.0.24: rts compares the stack with the routine's entry and jumps through call_addr.
"""
LEVEL = """---
id: alienbreed2-level-table
kind: fact
title: level table of the Alien Breed engine
status: verified
games: [alienbreed2]
engine: team17-ab
disks: [abc123]
tags: [levels, loader]
---
## Notes
The level table sits at $1352, three longs per world. Measured with arek bpstate.
"""
TOD = """---
id: rebuild-random-seed-cia-tod
kind: symptom
title: objects in another phase than the original - the random seed comes from CIA-B TOD
status: verified
games: [superfrog]
tags: [random, cia, parity]
---
## Symptom
Enemy positions differ from the original although every routine matches.
"""


@pytest.fixture
def base(tmp_path):
    for kind, text in (('symptom', PUSH_RTS), ('fact', LEVEL), ('symptom', TOD)):
        rec = kb.parse(text)
        d = tmp_path / 'records' / kind
        d.mkdir(parents=True, exist_ok=True)
        (d / (rec['id'] + '.md')).write_text(text)
    (tmp_path / 'inbox').mkdir()
    return tmp_path


def test_parse_header_lists_and_sections():
    r = kb.parse(PUSH_RTS, 'x.md')
    assert r['id'] == 'kit-recomp-push-rts' and r['kind'] == 'symptom' and r['fixed_in'] == '1.0.24'
    assert r['games'] == ['xenon2'] and r['tags'] == ['recomp', 'stack', 'rts'] and r['disks'] == []
    assert r['sections']['Symptom'].startswith('host_trace diverges') and 'Resolution' in r['sections']
    assert kb.validate(r) == []
    again = kb.parse(kb.render(r))
    assert {k: again[k] for k in ('id', 'kind', 'games', 'tags', 'sections')} == {k: r[k] for k in ('id', 'kind', 'games', 'tags', 'sections')}
    with pytest.raises(kb.KBError, match='no header'):
        kb.parse('# just text')
    with pytest.raises(kb.KBError, match='not closed'):
        kb.parse('---\nid: x\n')


def test_validate_refuses_bad_fields_and_data_dumps():
    r = kb.parse(PUSH_RTS)
    assert kb.validate(dict(r, kind='note')) and kb.validate(dict(r, status='done')) and kb.validate(dict(r, id='Bad Id'))
    assert any('Symptom' in p for p in kb.validate(dict(r, sections={})))
    dump = dict(r, body=r['body'] + '\n' + ' '.join('%02x' % (i & 0xff) for i in range(64)))
    assert any('hex dump' in p for p in kb.validate(dump))
    assert not kb.validate(dict(r, body=r['body'] + '\nsignature 4e75 4e71 60fe 2f3c 0000 1010'))   # a short signature is fine


def test_search_by_symptom_words_addresses_and_filters(base):
    recs = kb.load(str(base))
    hits = kb.search(recs, 'host_trace diverges after a few passes, crash at a nonsense address')
    assert hits[0]['id'] == 'kit-recomp-push-rts' and hits[0]['snippet']
    assert kb.search(recs, '$5920')[0]['id'] == 'kit-recomp-push-rts' and kb.search(recs, '0x5920')[0]['id'] == 'kit-recomp-push-rts'
    assert kb.search(recs, 'move.l')[0]['id'] == 'kit-recomp-push-rts'
    assert kb.search(recs, 'random seed differs')[0]['id'] == 'rebuild-random-seed-cia-tod'
    assert [h['id'] for h in kb.search(recs, 'level table', game='team17-ab')] == ['alienbreed2-level-table']   # an engine matches too
    assert kb.search(recs, 'level', kind='symptom') == [] and kb.search(recs, '') == []
    assert [h['id'] for h in kb.search(recs, 'level table', game='team17')] == ['alienbreed2-level-table']       # the family finds its member
    fam = [dict(r, engine='team17') if r['id'] == 'rebuild-random-seed-cia-tod' else r for r in recs]
    assert [h['id'] for h in kb.search(fam, 'random seed', game='team17-ab')] == ['rebuild-random-seed-cia-tod']   # and the member its family
    assert kb.get(recs, 'alienbreed2-level-table')['engine'] == 'team17-ab'
    with pytest.raises(kb.KBError):
        kb.get(recs, 'nope')
    assert kb.stats(recs)['kind'] == {'symptom': 2, 'fact': 1}


def test_propose_check_and_promote(base):
    new = PUSH_RTS.replace('kit-recomp-push-rts', 'kit-recomp-push-rts-2')
    p = kb.add(new, 'xenon2', str(base))
    assert p.endswith('inbox/xenon2/kit-recomp-push-rts-2.md')
    with pytest.raises(kb.KBError, match='taken'):
        kb.add(PUSH_RTS, 'xenon2', str(base))
    with pytest.raises(kb.KBError, match='does not validate'):
        kb.add(new.replace('kind: symptom', 'kind: note'), 'xenon2', str(base))
    assert kb.check(str(base)) == {'records': 3, 'inbox': 1, 'problems': []}
    assert [h['id'] for h in kb.search(kb.load(str(base), inbox=True), 'nonsense address')][:2] == ['kit-recomp-push-rts', 'kit-recomp-push-rts-2']
    assert len(kb.load(str(base))) == 3                                     # the inbox stays out of the default search
    out = kb.promote('inbox/xenon2/kit-recomp-push-rts-2.md', str(base))
    assert out.endswith('records/symptom/kit-recomp-push-rts-2.md') and kb.check(str(base))['records'] == 4
    (base / 'records' / 'fact' / 'dup.md').write_text(LEVEL.replace('alienbreed2-level-table', 'dup').replace('kind: fact', 'kind: symptom'))
    probs = kb.check(str(base))['problems']
    assert any('folder is not the kind' in p for _, p in probs) and any('Symptom' in p for _, p in probs)


def test_cli_and_the_environment(base, monkeypatch, capsys):
    monkeypatch.setenv('AREK_KB', str(base))
    assert cli.main(['kb', 'search', 'crash', 'at', 'a', 'nonsense', 'address', '--json']) == 0
    hits = json.loads(capsys.readouterr().out)
    assert hits[0]['id'] == 'kit-recomp-push-rts'
    assert cli.main(['kb', 'get', 'kit-recomp-push-rts']) == 0 and 'fixed_in: 1.0.24' in capsys.readouterr().out
    assert cli.main(['kb', 'check']) == 0 and '3 records' in capsys.readouterr().out
    monkeypatch.delenv('AREK_KB')
    with pytest.raises(kb.KBError, match='AREK_KB'):
        kb.root()
