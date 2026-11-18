"""Read-only witness primitives copied from 0.4.7 shared native; no edit engine."""
import bpy, math
def fail(code,message,details=None): raise ValueError(code+": "+message)

def finite(value):
    value = float(value)
    if not math.isfinite(value):
        fail('UNSUPPORTED', 'Non-finite native animation data')
    return value

def _plain(value, depth=0):
    """Bounded RNA witnesses without pointers or transient memory identifiers."""
    if isinstance(value,str) and len(value)>65536:fail('UNSUPPORTED','Witness string budget exceeded')
    if not isinstance(value,(str,bytes,bpy.types.ID)) and hasattr(value,'__len__') and len(value)>4096:fail('UNSUPPORTED','Witness collection budget exceeded')
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
