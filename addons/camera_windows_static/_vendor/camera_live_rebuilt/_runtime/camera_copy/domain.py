"""Selected protection/dependency checks adapted from frozen candidate_v02 bridge; not exhaustive."""
import hashlib
import json

def require(condition, message):
    if not condition: raise ValueError(message)

def reject_unpreserved(bpy):
    """Conservative v1: self-contained local technical scenes only."""
    for prop in bpy.data.bl_rna.properties:
        if prop.type == 'COLLECTION':
            for block in getattr(bpy.data, prop.identifier, ()):
                if isinstance(block, bpy.types.ID):
                    require(not block.library and not block.override_library, 'linked/override data unsupported')
    for key in ('libraries', 'texts', 'sounds', 'movieclips', 'volumes', 'cache_files', 'particles'):
        require(not len(getattr(bpy.data, key, ())), 'unsupported data collection: ' + key)
    for image in bpy.data.images:
        require(image.source in ('GENERATED', 'VIEWER') and not image.filepath, 'file image unsupported')
    for font in bpy.data.fonts:
        require(font.filepath == '<builtin>', 'external font unsupported')
    for scene in bpy.data.scenes:
        require(not scene.rigidbody_world, 'rigid body unsupported')
        require(scene.sequence_editor is None or len(scene.sequence_editor.strips_all) == 0,
                'nonempty sequencer unsupported')
    for obj in bpy.data.objects:
        require(not obj.library and not obj.override_library, 'linked object unsupported')
        for modifier in obj.modifiers:
            require(modifier.type not in {'CLOTH', 'FLUID', 'SOFT_BODY', 'DYNAMIC_PAINT',
                    'PARTICLE_SYSTEM', 'MESH_SEQUENCE_CACHE', 'MESH_CACHE', 'NODES'}, 'simulation/cache/nodes modifier unsupported')
    for group in bpy.data.node_groups:
        require(not any('Simulation' in n.bl_idname or 'Bake' in n.bl_idname for n in group.nodes), 'simulation/bake node unsupported')


def protected(bpy, scene):
    """Selected authored fields, explicitly not an exhaustive .blend equivalence."""
    actions = {}
    for action in bpy.data.actions:
        layers = []
        for layer in action.layers:
            strips = []
            for strip in layer.strips:
                bags = []
                for bag in strip.channelbags:
                    curves = []
                    for fc in bag.fcurves:
                        curves.append({'path': fc.data_path, 'index': fc.array_index,
                            'extrapolation': fc.extrapolation,
                            'keys': [{'co': list(k.co), 'left': list(k.handle_left), 'right': list(k.handle_right),
                                      'left_type': k.handle_left_type, 'right_type': k.handle_right_type,
                                      'interpolation': k.interpolation} for k in fc.keyframe_points]})
                    bags.append({'slot': bag.slot_handle, 'curves': curves})
                strips.append({'type': strip.type, 'bags': bags})
            layers.append({'name': layer.name, 'strips': strips})
        actions[action.name] = {'slots': [(s.identifier, s.handle, s.target_id_type) for s in action.slots], 'layers': layers}
    tree = getattr(scene, 'compositing_node_group', None) or getattr(scene, 'node_tree', None)
    return {'sequence_editor': {'exists': scene.sequence_editor is not None,
            'strips': [] if scene.sequence_editor is None else [s.name for s in scene.sequence_editor.strips_all]},
        'scene_camera': scene.camera.name if scene.camera else None,
        'time': [scene.frame_current, scene.frame_subframe],
        'range': [scene.frame_start, scene.frame_end, scene.use_preview_range, scene.frame_preview_start, scene.frame_preview_end],
        'render': {k: getattr(scene.render, k) for k in ('engine', 'fps', 'fps_base', 'resolution_x', 'resolution_y', 'resolution_percentage', 'filepath', 'film_transparent', 'use_compositing', 'use_sequencer')},
        'camera_data': {o.name: {'lens': o.data.lens, 'type': o.data.type, 'ortho_scale': o.data.ortho_scale,
            'clip_start': o.data.clip_start, 'clip_end': o.data.clip_end, 'shift': [o.data.shift_x, o.data.shift_y],
            'dof': o.data.dof.use_dof, 'fstop': o.data.dof.aperture_fstop, 'distance': o.data.dof.focus_distance,
            'focus': o.data.dof.focus_object.name if o.data.dof.focus_object else None}
            for o in scene.objects if o.type == 'CAMERA'},
        'objects': {o.name: {'type': o.type, 'data': o.data.name if o.data else None,
            'parent': o.parent.name if o.parent else None,
            'basis': [list(row) for row in o.matrix_basis],
            'action': o.animation_data.action.name if o.animation_data and o.animation_data.action else None}
            for o in scene.objects},
        'markers': [(m.name, m.frame, m.camera.name if m.camera else None) for m in scene.timeline_markers],
        'actions': actions,
        'compositor': None if tree is None else {'name': tree.name,
            'nodes': [(n.name, n.bl_idname) for n in tree.nodes],
            'links': [(l.from_node.name, l.from_socket.identifier, l.to_node.name, l.to_socket.identifier) for l in tree.links]}}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def rows_of(scene):
    return [{'name': r.name, 'camera': r.camera.name if r.camera else None,
             'first': r.first, 'last': r.last} for r in scene.camera_live_shots]

