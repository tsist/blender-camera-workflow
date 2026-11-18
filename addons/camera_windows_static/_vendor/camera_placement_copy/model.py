"""Pure source-bound static placement/lens candidates; no bpy, IO or execution.

PROVENANCE: New bounded optics slice, reusing the frozen Camera Live 0.6
candidate_model's strict table validation, duplicate-safe JSON parser and
canonical JSON format. Not a recovered historical optics implementation.
Native eligibility and actual camera/data ownership are checked by the separate
saved-disk service; a valid document alone cannot prove those scene facts.
"""
import copy
import hashlib
import math
import re
import struct

from . import table_model

SCHEMA = 'camera-static-placement-candidate/1'
MAX_BYTES = table_model.MAX_BYTES
LENS_MIN = 1.0
LENS_MAX = 5000.0
KEYS = {'schema', 'source_sha256', 'scene', 'source_mode', 'catalog',
        'base_rows', 'shot', 'camera', 'camera_data', 'base_lens', 'lens',
        'candidate_name', 'content_sha256', 'base_pose', 'location', 'target_mode'}
CandidateError = table_model.CandidateError
TARGET_MODES = {'SEQUENCE_SHOT', 'NAMED_CAMERA'}
SOURCE_TABLE_SCHEMA = 'camera-placement-source-table/1'
SOURCE_TABLE_KEYS = {'schema', 'source_sha256', 'scene', 'source_mode', 'rows',
                     'catalog', 'content_sha256'}
LOCATION_LIMIT = 1_000_000.0
RIGID_TOLERANCE = 1e-5
ROTATION_MODES = {'XYZ', 'XZY', 'YXZ', 'YZX', 'ZXY', 'ZYX', 'QUATERNION', 'AXIS_ANGLE'}
POSE_KEYS = {'location', 'rotation_mode', 'rotation_euler', 'rotation_quaternion',
             'rotation_axis_angle', 'scale', 'delta_location', 'delta_rotation_euler',
             'delta_rotation_quaternion', 'delta_scale', 'matrix_basis', 'matrix_world'}


def _require(condition, message):
    if not condition:
        raise CandidateError(message)


def _name(value):
    _require(type(value) is str and bool(value) and value.strip() == value
             and '\x00' not in value, 'Invalid name')
    return value


def _sha(value):
    _require(type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None,
             'Invalid SHA256')


def canonical_json(value):
    """Use the table candidate canonical representation, without JSON coercion."""
    try:
        result = table_model.canonical_json(value)
        result.encode('utf-8')
        return result
    except (UnicodeError, RecursionError) as exc:
        raise CandidateError('Invalid canonical JSON') from exc


def _digest(value):
    return hashlib.sha256(canonical_json(value).encode('utf-8')).hexdigest()


def _float32(value):
    _require(type(value) in (int, float), 'Lens must be a number, not bool')
    # Range checking before conversion also rejects arbitrarily large integers
    # without overflowing Python's int-to-float conversion.
    _require(LENS_MIN <= value <= LENS_MAX, 'Lens must be finite and in range 1..5000')
    _require(math.isfinite(value), 'Lens must be finite')
    return struct.unpack('!f', struct.pack('!f', value))[0]


def _scalar32(value, limit=None):
    _require(type(value) in (int, float), 'Pose value must be numeric, not bool')
    # Bound before float conversion, including arbitrarily large Python ints.
    bound = 3.4028234663852886e38 if limit is None else limit
    _require(-bound <= value <= bound, 'Pose value must be finite and in range')
    _require(math.isfinite(value), 'Pose value must be finite')
    return struct.unpack('!f', struct.pack('!f', value))[0]


def _vector(value, size, *, canonical=True, limit=None):
    _require(type(value) is list and len(value) == size, 'Invalid pose vector shape')
    result = [_scalar32(v, limit) for v in value]
    if canonical:
        _require(value == result, 'Pose values must already be float32-normalized')
    return result


def validate_pose(pose):
    """Check frozen structural witnesses without normalizing or changing them.

    Native capture must separately prove these fields describe the same actual
    camera. This pure check does not derive a matrix from active rotation fields.
    Inactive rotation representations are retained as finite float32 witnesses.
    """
    _require(type(pose) is dict and set(pose) == POSE_KEYS, 'Invalid base_pose fields')
    _require(type(pose['rotation_mode']) is str and pose['rotation_mode'] in ROTATION_MODES,
             'Unsupported rotation mode')
    _vector(pose['location'], 3, limit=LOCATION_LIMIT)
    for field, size in (('rotation_euler', 3), ('rotation_quaternion', 4),
                        ('rotation_axis_angle', 4), ('scale', 3),
                        ('delta_location', 3), ('delta_rotation_euler', 3),
                        ('delta_rotation_quaternion', 4), ('delta_scale', 3)):
        _vector(pose[field], size)
    for field, expected in (('scale', [1, 1, 1]), ('delta_scale', [1, 1, 1]),
                            ('delta_location', [0, 0, 0]),
                            ('delta_rotation_euler', [0, 0, 0]),
                            ('delta_rotation_quaternion', [1, 0, 0, 0])):
        _require(pose[field] == expected, 'Nonidentity scale/delta unsupported: ' + field)
    for field in ('matrix_basis', 'matrix_world'):
        matrix = pose[field]
        _require(type(matrix) is list and len(matrix) == 4, 'Invalid matrix shape')
        for row in matrix:
            _vector(row, 4, limit=LOCATION_LIMIT)
        _require(matrix[3] == [0, 0, 0, 1], 'Non-affine matrix unsupported')
        _require([matrix[i][3] for i in range(3)] == pose['location'],
                 'Matrix translation differs from base location')
        columns = [[matrix[i][k] for i in range(3)] for k in range(3)]
        for i in range(3):
            for k in range(3):
                dot = sum(a * b for a, b in zip(columns[i], columns[k]))
                _require(abs(dot - (1 if i == k else 0)) <= RIGID_TOLERANCE,
                         'Nonrigid or sheared matrix unsupported')
        a, b, c = matrix[:3]
        determinant = (a[0] * (b[1] * c[2] - b[2] * c[1])
                       - a[1] * (b[0] * c[2] - b[2] * c[0])
                       + a[2] * (b[0] * c[1] - b[1] * c[0]))
        _require(determinant > 0 and abs(determinant - 1) <= RIGID_TOLERANCE,
                 'Reflected or nonunit matrix unsupported')
    _require(pose['matrix_basis'] == pose['matrix_world'], 'Basis/world mismatch unsupported')
    return copy.deepcopy(pose)


def _table(source_sha256, scene, source_mode, rows, catalog):
    _sha(source_sha256)
    _name(scene)
    _require(type(source_mode) is str and source_mode in ('SCENE', 'SEQUENCE'),
             'Unsupported saved source mode')
    _require(type(catalog) is list and bool(catalog), 'Invalid camera catalog')
    for name in catalog:
        _name(name)
    _require(catalog == sorted(set(catalog)), 'Catalog must be sorted and unique')
    if source_mode == 'SCENE':
        _require(type(rows) is list and not rows, 'SCENE requires a genuinely empty table')
        return []
    # This validates exact row fields, names, frame types/bounds, uniqueness,
    # adjacency, and membership using the frozen existing table contract.
    return table_model.export_snapshot(source_sha256, scene, source_mode,
                                       rows, catalog)['base_rows']


def validate_source_table(document):
    """Verify a sealed source-table witness, not a replayable workbench candidate."""
    _require(type(document) is dict and set(document) == SOURCE_TABLE_KEYS,
             'Invalid source-table witness fields')
    _require(document['schema'] == SOURCE_TABLE_SCHEMA, 'Unsupported source-table schema')
    _sha(document['content_sha256'])
    _table(document['source_sha256'], document['scene'], document['source_mode'],
           document['rows'], document['catalog'])
    _require(len(canonical_json(document).encode('utf-8')) <= MAX_BYTES,
             'Source-table witness exceeds size limit')
    _require(document['content_sha256'] == _digest(
        {k: v for k, v in document.items() if k != 'content_sha256'}),
        'Source-table fingerprint mismatch')
    return copy.deepcopy(document)


def validate_source_table_snapshot(document):
    """Public explicit-name validator for source_table_snapshot output."""
    return validate_source_table(document)


def source_table_snapshot(source_sha256, scene, source_mode, rows, catalog):
    """Preserve actual mode and rows; never fabricate a shot for an empty scene."""
    checked_rows = _table(source_sha256, scene, source_mode, rows, catalog)
    return validate_source_table(_seal(dict(
        schema=SOURCE_TABLE_SCHEMA, source_sha256=source_sha256, scene=scene,
        source_mode=source_mode, rows=copy.deepcopy(checked_rows), catalog=copy.deepcopy(catalog))))


def _target(rows, shot):
    _name(shot)
    matches = [row for row in rows if row['name'] == shot]
    _require(len(matches) == 1, 'Unknown or ambiguous shot')
    camera = matches[0]['camera']
    _require(sum(row['camera'] == camera for row in rows) == 1,
             'Target camera must occur in exactly one shot')
    return camera


def _resolve_target(target_mode, source_mode, rows, catalog, shot, camera=None):
    _require(type(target_mode) is str and target_mode in TARGET_MODES, 'Invalid target mode')
    if target_mode == 'SEQUENCE_SHOT':
        _require(source_mode == 'SEQUENCE', 'SEQUENCE_SHOT requires SEQUENCE source')
        selected = _target(rows, shot)
        if camera is not None:
            _name(camera)
            _require(camera == selected, 'Camera differs from selected shot')
        return selected
    _require(source_mode == 'SCENE' and type(rows) is list and not rows,
             'NAMED_CAMERA requires SCENE with an empty actual table')
    _require(shot is None, 'NAMED_CAMERA has no shot or shot time interval')
    _name(camera)
    _require(camera in catalog, 'Named camera is absent from source catalog')
    return camera


def _seal(doc):
    doc['content_sha256'] = _digest({k: v for k, v in doc.items()
                                     if k != 'content_sha256'})
    return doc


def validate_document(document):
    """Validate without normalizing/resealing input; return an independent copy.

    Numeric int values equivalent to their float32 value are allowed, but
    unquantized floating-point values are rejected even when their seal matches.
    Export/variant always store Python float values quantized to float32.
    """
    _require(type(document) is dict and set(document) == KEYS,
             'Invalid document fields')
    _require(type(document['schema']) is str and document['schema'] == SCHEMA,
             'Unsupported schema')
    _sha(document['source_sha256'])
    _sha(document['content_sha256'])
    for key in ('scene', 'camera', 'camera_data', 'candidate_name'):
        _name(document[key])
    _require(len(canonical_json(document).encode('utf-8')) <= MAX_BYTES,
             'Candidate exceeds size limit')
    rows = _table(document['source_sha256'], document['scene'],
                  document['source_mode'], document['base_rows'], document['catalog'])
    _resolve_target(document['target_mode'], document['source_mode'], rows,
                    document['catalog'], document['shot'], document['camera'])
    for key in ('base_lens', 'lens'):
        _require(document[key] == _float32(document[key]),
                 key + ' must already be float32-normalized')
    validate_pose(document['base_pose'])
    _vector(document['location'], 3, limit=LOCATION_LIMIT)
    _require(document['content_sha256'] == _digest(
        {k: v for k, v in document.items() if k != 'content_sha256'}),
        'Content fingerprint mismatch')
    return copy.deepcopy(document)


def export_snapshot(source_sha256, scene, source_mode, rows, catalog, shot,
                    camera_data, base_lens, base_pose, candidate_name='Original', *,
                    target_mode='SEQUENCE_SHOT', camera=None):
    """Freeze a source/table/target baseline, with baseline selected initially."""
    checked_rows = _table(source_sha256, scene, source_mode, rows, catalog)
    value = _float32(base_lens)
    pose = validate_pose(base_pose)
    target = _resolve_target(target_mode, source_mode, checked_rows, catalog, shot, camera)
    doc = dict(schema=SCHEMA, source_sha256=source_sha256, scene=scene,
               source_mode=source_mode, catalog=copy.deepcopy(catalog),
               base_rows=checked_rows, shot=shot, camera=target, target_mode=target_mode,
               camera_data=camera_data, base_lens=value, lens=value,
               candidate_name=candidate_name, base_pose=pose,
               location=copy.deepcopy(pose['location']))
    return validate_document(_seal(doc))


def variant(document, candidate_name, lens, location):
    """Choose absolute world location/lens; freeze all original family witnesses."""
    doc = validate_document(document)
    _name(candidate_name)
    doc['candidate_name'] = candidate_name
    doc['lens'] = _float32(lens)
    doc['location'] = _vector(location, 3, canonical=False, limit=LOCATION_LIMIT)
    return validate_document(_seal(doc))


def offset_variant(document, candidate_name, lens, offset_camera):
    """Offset original camera right/up/back axes in scene units; never cumulative.

    Positive local Z is camera back, not its viewing direction (-Z). Rotation
    remains fixed. No look-at, subject-size compensation or animation is implied.
    """
    doc = validate_document(document)
    offset = _vector(offset_camera, 3, canonical=False, limit=LOCATION_LIMIT)
    pose = doc['base_pose']
    matrix = pose['matrix_world']
    location = [pose['location'][i] + sum(matrix[i][k] * offset[k] for k in range(3))
                for i in range(3)]
    return variant(doc, candidate_name, lens, location)


def load_json(text):
    """Duplicate-safe, finite, bounded JSON input via the strict table parser."""
    return validate_document(table_model.parse_json(text))


def compare(before, after):
    """Compare chosen lens/location only inside the identical frozen source family."""
    a, b = validate_document(before), validate_document(after)
    family = ('source_sha256', 'scene', 'source_mode', 'catalog', 'base_rows',
              'shot', 'camera', 'camera_data', 'base_lens', 'base_pose', 'target_mode')
    _require(all(a[key] == b[key] for key in family), 'Different source families')
    return {'target_mode': a['target_mode'], 'shot': a['shot'], 'camera': a['camera'], 'camera_data': a['camera_data'],
            'base_lens': a['base_lens'], 'before': a['lens'], 'after': b['lens'],
            'base_location': copy.deepcopy(a['base_pose']['location']),
            'before_location': copy.deepcopy(a['location']),
            'after_location': copy.deepcopy(b['location']),
            'lens_changed': a['lens'] != b['lens'],
            'location_changed': a['location'] != b['location'],
            'changed': a['lens'] != b['lens'] or a['location'] != b['location']}
