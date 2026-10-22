"""Read-only, profile-driven module inventory and conservative 68000 reachability.

JSON in, JSON out; the result **never** interprets decoded coverage as semantic
completeness. Only direct control flow is followed, no global address-register
assumptions are made. (From ``architecture_audit.py``.)

Profile format::

    {
      "name": "superfrog",
      "inventory_glob": "build/files/*.bin",
      "modules": {
        "build/files/main.bin": {"role": "main", "base": "0x20700",
                                 "roots": ["0x20700", "0x21234"],
                                 "evidence": ["docs/LOADER.md"]}
      }
    }
"""
import hashlib
import json
import struct
from pathlib import Path

from . import decoder


def address(value):
    return int(value, 0) if isinstance(value, str) else value


def graph(data, base, roots):
    pending = list(roots)
    visited, issues, edges = {}, set(), set()
    limit = base + len(data)
    while pending:
        pc = pending.pop()
        if pc in visited:
            continue
        if not base <= pc < limit:
            issues.add((pc, 'outside_module'))
            continue
        if pc & 1:
            issues.add((pc, 'unaligned_target'))
            continue
        try:
            ins = decoder.decode(data, base, pc)
        except (decoder.Unsupported, struct.error) as exc:
            issues.add((pc, 'decode_error:' + str(exc)))
            continue
        if ins.end > limit or ins.end <= pc:
            issues.add((pc, 'invalid_instruction_extent'))
            continue
        visited[pc] = ins
        targets = []
        if ins.kind in ('rts', 'rte', 'rtr'):
            pass
        elif ins.kind in ('stop', 'trap', 'illegal'):
            issues.add((pc, 'exception_or_wait'))
        elif ins.kind == 'bra':
            targets = [ins.target]
        elif ins.kind in ('bcc', 'dbcc', 'bsr'):
            targets = [ins.target, ins.end]
        elif ins.kind in ('jsr', 'jmp'):
            if ins.ea.mode in decoder.FLOW_MODES:
                targets.append(ins.ea.absval)
            else:
                issues.add((pc, 'unresolved_' + ins.kind))
            if ins.kind == 'jsr':
                targets.append(ins.end)
        else:
            targets = [ins.end]
        for target in targets:
            edges.add((pc, target))
            pending.append(target)
    occupied = {}
    for pc, ins in sorted(visited.items()):
        for byte in range(pc, ins.end):
            if byte in occupied:
                issues.add((pc, 'overlapping_decode'))
            occupied[byte] = pc
    return {
        'status': 'partial_static_graph',
        'roots': [hex(x) for x in roots],
        'unique_instructions': len(visited),
        'decoded_bytes': len(occupied),
        'instruction_addresses': [hex(x) for x in sorted(visited)],
        'edges': [[hex(a), hex(b)] for a, b in sorted(edges)],
        'frontiers': [{'address': hex(a), 'reason': b} for a, b in sorted(issues)],
        'semantic_parity': 'not_measured',
    }


LIMITATIONS = ['Not a full disassembly or a parity certificate.',
               'Unknown modules and indirect targets remain explicit.',
               'No dynamic overlays, self-modification or IRQ scheduling modeled.',
               'No inference of hardware independence from absent absolute writes.']


def audit(profile, root):
    root = Path(root)
    records = []
    declared = profile['modules']
    files = {p.relative_to(root).as_posix(): p for p in root.glob(profile['inventory_glob'])}
    for name in declared:
        files.setdefault(name, root / name)
    for name, path in sorted(files.items()):
        spec = declared.get(name, {})
        record = {'file': name, 'role': spec.get('role', 'unclassified'),
                  'evidence': spec.get('evidence', []), 'graph': {'status': 'not_scanned'}}
        if not path.is_file():
            record['status'] = 'missing'
        else:
            data = path.read_bytes()
            record.update(status='present', bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
            if spec.get('roots'):
                record['graph'] = graph(data, address(spec['base']),
                                        [address(x) for x in spec['roots']])
        records.append(record)
    return {'schema': 1, 'profile': profile['name'],
            'decoder_sha256': hashlib.sha256(Path(decoder.__file__).read_bytes()).hexdigest(),
            'kit': __import__('arek').identity(),
            'profile_sha256': hashlib.sha256(json.dumps(profile, sort_keys=True).encode()).hexdigest(),
            'limitations': LIMITATIONS,
            'modules': records}
