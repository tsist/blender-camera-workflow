"""Read-only Action witnesses retained for Camera Workflow."""
import math
import bpy
from .contract import WorkflowError

def fail(code, message, details=None):
    raise WorkflowError(code, message, details or {})

def finite(value):
    value = float(value)
    if not math.isfinite(value):
        fail('UNSUPPORTED', 'Non-finite native animation data')
    return value

def _plain(value, depth=0):
    """Bounded RNA witnesses without pointers or transient memory identifiers."""
    if value is None or isinstance(value, (bool, str, int)):
        return value
    if isinstance(value, float):
        return finite(value)
    if isinstance(value, bpy.types.ID):
        return {'id_type': value.bl_rna.identifier, 'name': value.name}
    if isinstance(value, (set, frozenset)):
        return sorted(_plain(v, depth + 1) for v in value)
    if depth > 6:
        fail('UNSUPPORTED', 'Native animation witness nesting exceeds supported depth')
    if hasattr(value, 'to_list'):
        return _plain(value.to_list(), depth + 1)
    if isinstance(value, dict) or hasattr(value, 'keys') and not hasattr(value, 'bl_rna'):
        return {str(k): _plain(value[k], depth + 1) for k in sorted(value.keys())}
    try:
        return [_plain(v, depth + 1) for v in value]
    except TypeError:
        fail('UNSUPPORTED', 'Unsupported native animation witness value')

def rna_values(item, exclude=()):
    out = {}
    for prop in item.bl_rna.properties:
        name = prop.identifier
        if name == 'rna_type' or name in exclude:
            continue
        if prop.type in {'BOOLEAN', 'INT', 'FLOAT', 'STRING', 'ENUM'}:
            out[name] = _plain(getattr(item, name))
        elif prop.type == 'COLLECTION':
            out[name] = [rna_values(v) for v in getattr(item, name)]
    return out

def custom_state(item):
    return {k: _plain(item[k]) for k in sorted(item.keys())}

def key_state(key):
    return rna_values(key)

def curve_state(curve):
    return {'data_path': curve.data_path, 'array_index': int(curve.array_index),
            'properties': rna_values(curve, {'keyframe_points', 'sampled_points', 'modifiers', 'is_valid', 'is_empty'}),
            'group': curve.group.name if curve.group else None,
            'keys': [key_state(k) for k in curve.keyframe_points],
            'sampled_points': [rna_values(p) for p in curve.sampled_points],
            'modifiers': [rna_values(m) for m in curve.modifiers]}

def bag_state(bag):
    return [curve_state(curve) for curve in sorted(bag.fcurves, key=lambda c: (c.data_path, c.array_index))] if bag else []

def action_state(action):
    if action is None:
        return None
    slot = action.slots[0]
    bag = action.layers[0].strips[0].channelbag(slot)
    return {'properties': custom_state(action), 'curves': bag_state(bag)}
