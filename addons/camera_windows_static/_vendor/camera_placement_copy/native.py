"""Conservative static-placement ownership checks and selected authored/evaluated witnesses."""
import copy
from . import model
from . import preservation
from . import state_contract
from camera_live_rebuilt import candidate_model as table_model
from camera_live_rebuilt.adapter import validate_camera_markers


def require(ok, message):
    if not ok:
        raise ValueError(message)


def has_animation(block):
    a = getattr(block, 'animation_data', None)
    return bool(a and (a.action is not None or len(a.drivers) or len(a.nla_tracks)))


def all_ids(bpy):
    seen = set()
    for prop in bpy.data.bl_rna.properties:
        if prop.type == 'COLLECTION':
            for block in getattr(bpy.data, prop.identifier, ()):
                if isinstance(block, bpy.types.ID):
                    for item in (block, getattr(block, 'node_tree', None), getattr(block, 'compositing_node_group', None)):
                        if isinstance(item, bpy.types.ID) and item.as_pointer() not in seen:
                            seen.add(item.as_pointer())
                            yield item


def eligible(bpy, scene_name, shot_name, target_mode='SEQUENCE_SHOT', camera_name=None):
    """No writes. Refuse relationships this fixed-orientation placement slice cannot scope."""
    preservation.reject_unpreserved(bpy)
    scene = bpy.data.scenes.get(scene_name)
    require(scene is not None and not scene.library and not scene.override_library, 'Local scene required')
    require(scene == bpy.context.scene, 'Selected scene must be the loaded active scene')
    require(target_mode in ('SEQUENCE_SHOT', 'NAMED_CAMERA'), 'Unknown target mode')
    if target_mode == 'SEQUENCE_SHOT':
        require(scene.camera_live_source == 'SEQUENCE', 'Shot sequence required')
    else:
        require(scene.camera_live_source == 'SCENE' and shot_name is None, 'Named camera requires SCENE and no shot')
    require(not has_animation(scene), 'Scene animation/driver/NLA unsupported')
    rows = preservation.rows_of(scene)
    catalog = sorted(o.name for o in scene.objects if o.type == 'CAMERA')
    # Reuse current table validation, including contiguous integer bounds and unique names.
    model.source_table_snapshot('0' * 64, scene.name, scene.camera_live_source, rows, catalog)
    if target_mode == 'SEQUENCE_SHOT':
        chosen = [r for r in rows if r['name'] == shot_name]
        require(len(chosen) == 1, 'Exactly one named source shot required')
        require(camera_name is None or camera_name == chosen[0]['camera'], 'Explicit camera differs from shot')
        camera = scene.objects.get(chosen[0]['camera'])
    else:
        require(rows == [], 'Named-camera mode requires a genuinely empty source table')
        model._name(camera_name)
        camera = scene.objects.get(camera_name)
    require(camera is not None and camera.type == 'CAMERA', 'Named camera required')
    data = camera.data
    require(not camera.library and not camera.override_library and not data.library and not data.override_library,
            'Linked/override target unsupported')
    require(data.type == 'PERSP', 'Only perspective optical candidates supported')
    require(camera.parent is None and len(camera.constraints) == 0 and not has_animation(camera),
            'Target camera parent/constraints/animation unsupported')
    require(not has_animation(data), 'Target Camera data Action/driver/NLA unsupported')
    owners = [o for o in bpy.data.objects if o.type == 'CAMERA' and o.data == data]
    require(owners == [camera] and data.users == 1, 'Shared or extra-user Camera data unsupported')
    require(len(camera.users_scene) == 1 and camera.users_scene[0] == scene,
            'Target camera shared across scenes')
    uses = []
    for other in bpy.data.scenes:
        validate_camera_markers(other.timeline_markers)
        require(other == scene or other.camera != camera, 'Target camera used by another scene')
        uses.extend((other.name, row.name) for row in other.camera_live_shots if row.camera == camera)
    if target_mode == 'SEQUENCE_SHOT':
        require(uses == [(scene.name, shot_name)], 'Target camera reused by another shot')
    else:
        require(uses == [], 'Named camera is referenced by a shot table')
    for block in all_ids(bpy):
        a = getattr(block, 'animation_data', None)
        require(not a or not len(a.drivers), 'Drivers anywhere in the source unsupported')
    require(not any(o.instance_type != 'NONE' for o in bpy.data.objects), 'Object/collection instancing unsupported')
    rna = data.bl_rna.properties['lens']
    require(rna.type == 'FLOAT' and rna.hard_min <= model.LENS_MIN and rna.hard_max >= model.LENS_MAX,
            'Lens RNA range does not cover validated model range')
    require(not data.dof.use_dof, 'Initial placement candidates require target DOF disabled')
    bpy.context.view_layer.update()
    model.validate_pose(pose(camera))
    return scene, camera, rows, catalog


def pose(obj):
    fields=('location','rotation_euler','rotation_quaternion','rotation_axis_angle','scale',
            'delta_location','delta_rotation_euler','delta_rotation_quaternion','delta_scale')
    result={name:list(getattr(obj,name)) for name in fields}
    result['rotation_mode']=obj.rotation_mode
    result['matrix_basis']=[list(row) for row in obj.matrix_basis]
    result['matrix_world']=[list(row) for row in obj.matrix_world]
    return result


def baseline(bpy, source_sha, scene_name, shot_name, target_mode='SEQUENCE_SHOT', camera_name=None):
    scene,camera,rows,catalog=eligible(bpy,scene_name,shot_name,target_mode,camera_name)
    if len(bpy.data.armatures) or any(o.type=='ARMATURE' for o in bpy.data.objects):
        from . import rig_snapshot
        rig_snapshot.capture(bpy)
    return model.export_snapshot(source_sha,scene.name,scene.camera_live_source,rows,catalog,shot_name,
        camera.data.name,camera.data.lens,pose(camera),target_mode=target_mode,camera=camera.name)


def check_document(bpy, doc, selected=False):
    doc=model.validate_document(doc)
    scene,camera,rows,catalog=eligible(bpy,doc['scene'],doc['shot'],doc['target_mode'],doc['camera'])
    require(scene.camera_live_source==doc['source_mode'] and rows==doc['base_rows'] and catalog==doc['catalog'],'Saved source mode/table/catalog differs')
    require(camera.name==doc['camera'] and camera.data.name==doc['camera_data'],'Target identity differs')
    require(camera.data.lens==(doc['lens'] if selected else doc['base_lens']),'Saved lens baseline differs')
    require(pose(camera)==(state_contract.selected_pose(doc) if selected else doc['base_pose']),'Saved native pose differs')
    return scene,camera


def state(bpy, scene):
    data_fields = ('lens', 'type', 'sensor_fit', 'sensor_width', 'sensor_height', 'ortho_scale',
                   'clip_start', 'clip_end', 'shift_x', 'shift_y', 'lens_unit', 'display_size')
    dof_fields = ('use_dof', 'focus_distance', 'aperture_fstop', 'aperture_blades', 'aperture_rotation', 'aperture_ratio')
    bpy.context.view_layer.update()
    depsgraph=bpy.context.evaluated_depsgraph_get()
    result = {'object_transforms':{o.name:pose(o) for o in bpy.data.objects},
            'evaluated_scene_matrices':{o.name:[list(row) for row in o.evaluated_get(depsgraph).matrix_world] for o in scene.objects},
            'protected': preservation.protected(bpy, scene), 'extras': preservation.extras(scene),
            'main_ids': preservation.main_id_roster(bpy),
            'tables': {s.name: {'mode': s.camera_live_source, 'rows': preservation.rows_of(s)} for s in bpy.data.scenes},
            'camera_optics': {d.name: {**{n: getattr(d, n) for n in data_fields},
                                     'dof': {**{n: getattr(d.dof, n) for n in dof_fields},
                                             'focus_object': d.dof.focus_object.name if d.dof.focus_object else None}}
                              for d in bpy.data.cameras}}
    if len(bpy.data.armatures) or any(o.type=='ARMATURE' for o in bpy.data.objects):
        from . import rig_snapshot
        result['strict_rig_scene']=rig_snapshot.capture(bpy)
    return result


def expected_state(before, doc):
    return state_contract.expected_state(before,doc)


def projection(camera, scene):
    """Native camera frame slopes, not a rendered/visual acceptance claim."""
    frame = camera.data.view_frame(scene=scene)
    return {'lens': camera.data.lens, 'matrix_world':[list(row) for row in camera.matrix_world], 'horizontal_slopes': sorted(float(v.x / -v.z) for v in frame),
            'vertical_slopes': sorted(float(v.y / -v.z) for v in frame)}
