"""Source-bound table candidates. No bpy, filesystem mutation, or native pointers."""
import copy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re

from . import core as _CORE
SCHEMA = 'camera-shot-candidate/1'
MAX_BYTES = 1048576
KEYS = {'schema', 'source_sha256', 'scene', 'source_mode', 'catalog', 'base_rows', 'rows', 'base_table_sha256', 'candidate_name', 'operations', 'content_sha256'}
ROW_KEYS = {'name', 'camera', 'first', 'last'}


class CandidateError(ValueError):
    pass


def _require(ok, message):
    if not ok:
        raise CandidateError(message)


def _name(value):
    _require(type(value) is str and bool(value) and value.strip() == value and '\x00' not in value, 'Invalid name')
    return value


def canonical_json(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError, UnicodeError) as exc:
        raise CandidateError('Not canonical JSON') from exc


def _hash(value):
    try:
        return hashlib.sha256(canonical_json(value).encode('utf-8')).hexdigest()
    except UnicodeError as exc:
        raise CandidateError('Invalid Unicode') from exc


def _sha(value):
    _require(type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None, 'Invalid SHA256')


def _rows(rows, catalog):
    _require(type(rows) is list, 'Rows must be a list')
    tokens = {name: i + 1 for i, name in enumerate(catalog)}
    tuples = []
    for row in rows:
        _require(type(row) is dict and set(row) == ROW_KEYS, 'Invalid row fields')
        _name(row['name']); _name(row['camera'])
        _require(row['camera'] in tokens, 'Camera not in source scene catalog')
        tuples.append((row['name'], tokens[row['camera']], row['first'], row['last']))
    try:
        _CORE.validate_shots(tuples)
    except _CORE.PreviewError as exc:
        raise CandidateError(str(exc)) from exc


def _replay(base, operations, catalog):
    _require(type(operations) is list and len(operations) <= 300, 'Invalid operations list')
    rows = copy.deepcopy(base)
    by_name = {r['name']: i for i, r in enumerate(rows)}
    written = set()
    def write(index, field, value):
        key = (index, field)
        _require(key not in written, 'Duplicate field write')
        written.add(key)
        rows[index][field] = value
    for op in operations:
        _require(type(op) is dict, 'Operation must be an object')
        kind = op.get('op')
        if kind == 'choose_camera':
            _require(set(op) == {'op', 'shot', 'camera'}, 'Invalid choose_camera fields')
            _name(op['shot']); _name(op['camera'])
            _require(op['shot'] in by_name and op['camera'] in catalog, 'Unknown shot or camera')
            write(by_name[op['shot']], 'camera', op['camera'])
        elif kind == 'move_cut':
            _require(set(op) == {'op', 'left', 'right', 'left_last'}, 'Invalid move_cut fields')
            _name(op['left']); _name(op['right'])
            _require(op['left'] in by_name and op['right'] in by_name, 'Unknown cut shot')
            left, right = by_name[op['left']], by_name[op['right']]
            _require(right == left + 1, 'Cut shots must be adjacent and ordered')
            frame = op['left_last']
            _require(type(frame) is int, 'Cut frame must be an integer')
            write(left, 'last', frame); write(right, 'first', frame + 1)
        else:
            raise CandidateError('Unknown operation')
    _rows(rows, catalog)
    return rows


def _seal(doc):
    doc['content_sha256'] = _hash({k: v for k, v in doc.items() if k != 'content_sha256'})
    return doc


def validate_document(doc):
    """Validate every field and reproduce the selected rows from baseline operations."""
    _require(type(doc) is dict and set(doc) == KEYS, 'Invalid document fields')
    _require(doc['schema'] == SCHEMA, 'Unsupported schema')
    _sha(doc['source_sha256']); _sha(doc['base_table_sha256']); _sha(doc['content_sha256'])
    _name(doc['scene']); _name(doc['candidate_name'])
    _require(type(doc['source_mode']) is str and doc['source_mode'] in ('SCENE', 'SEQUENCE'), 'Invalid source mode')
    catalog = doc['catalog']
    _require(type(catalog) is list and bool(catalog), 'Invalid camera catalog')
    for name in catalog:
        _name(name)
    _require(catalog == sorted(set(catalog)), 'Catalog must be sorted and unique')
    _rows(doc['base_rows'], catalog); _rows(doc['rows'], catalog)
    _require(doc['base_table_sha256'] == _hash({'source_mode': doc['source_mode'], 'rows': doc['base_rows']}), 'Baseline fingerprint mismatch')
    expected = _replay(doc['base_rows'], doc['operations'], catalog)
    _require(doc['rows'] == expected, 'Rows do not match declared operations')
    _require(doc['content_sha256'] == _hash({k: v for k, v in doc.items() if k != 'content_sha256'}), 'Content fingerprint mismatch')
    _require(len(canonical_json(doc).encode('utf-8')) <= MAX_BYTES, 'Candidate exceeds size limit')
    return copy.deepcopy(doc)


def export_snapshot(source_sha256, scene, source_mode, rows, catalog, candidate_name='Original'):
    _require(type(catalog) is list, 'Camera catalog must be a list')
    for name in catalog:
        _name(name)
    _require(len(set(catalog)) == len(catalog), 'Duplicate catalog camera')
    doc = dict(schema=SCHEMA, source_sha256=source_sha256, scene=scene,
               source_mode=source_mode, catalog=sorted(catalog), base_rows=copy.deepcopy(rows),
               rows=copy.deepcopy(rows), candidate_name=candidate_name, operations=[])
    doc['base_table_sha256'] = _hash({'source_mode': source_mode, 'rows': rows})
    return validate_document(_seal(doc))


def variant(document, candidate_name, operations):
    """Operations always target the frozen baseline, never a predecessor's selected rows."""
    doc = validate_document(document)
    _name(candidate_name)
    doc['candidate_name'] = candidate_name
    doc['operations'] = copy.deepcopy(operations)
    doc['rows'] = _replay(doc['base_rows'], operations, doc['catalog'])
    return validate_document(_seal(doc))


def compare(a, b):
    a, b = validate_document(a), validate_document(b)
    family = ('source_sha256', 'scene', 'source_mode', 'catalog', 'base_table_sha256', 'base_rows')
    _require(all(a[k] == b[k] for k in family), 'Different source families')
    changed, unchanged = [], []
    for before, after in zip(a['rows'], b['rows']):
        fields = {key: {'before': before[key], 'after': after[key]} for key in ('camera', 'first', 'last') if before[key] != after[key]}
        if fields:
            changed.append({'shot': before['name'], 'fields': fields})
        else:
            unchanged.append(before['name'])
    return {'changed': changed, 'unchanged': unchanged}


def parse_json(text):
    _require(type(text) in (str, bytes), 'JSON input must be text or bytes')
    try:
        _require(len(text.encode('utf-8') if type(text) is str else text) <= MAX_BYTES, 'JSON exceeds size limit')
        def pairs(items):
            result = {}
            for key, value in items:
                _require(key not in result, 'Duplicate JSON key')
                result[key] = value
            return result
        def bad_constant(value):
            raise CandidateError('Non-finite JSON number')
        def finite_float(value):
            number = float(value)
            _require(math.isfinite(number), 'Non-finite JSON number')
            return number
        doc = json.loads(text, object_pairs_hook=pairs, parse_constant=bad_constant, parse_float=finite_float)
        return doc
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise CandidateError('Invalid JSON') from exc


def load_json(text):
    return validate_document(parse_json(text))
