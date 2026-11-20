"""Linux Blender native static DOF binding; no helper or animation writes."""
import math
import struct
from copy import deepcopy


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def validate(q):
    need(type(q) is dict and set(q) == {"kind", "focus_object", "focus_subtarget", "fstop"}
         and q["kind"] == "bone", "Exact bone request fields required")
    for k in ("focus_object", "focus_subtarget"):
        s = q[k]
        need(type(s) is str and s.strip() and "\x00" not in s, "Exact nonempty names required")
    f = q["fstop"]
    need(type(f) in (int, float) and 0.1 <= f <= 128, "fstop must be within [0.1,128]")


def guard(bpy, scene, camera, q):
    validate(q)
    rig = scene.objects.get(q["focus_object"])
    need(rig is not None and rig.type == "ARMATURE" and rig.pose
         and rig.pose.bones.get(q["focus_subtarget"]) is not None, "Existing exact named armature bone required")
    need(scene.objects.get(camera.name) == camera and camera.type == "CAMERA", "Scene camera required")
    need(camera.data.users == 1, "Single-user camera data required")
    for x in (rig, rig.data, camera, camera.data):
        need(not x.library and not x.override_library, "Local nonoverride rig and camera required")
    need(camera.data.animation_data is None, "Animated camera data unsupported")
    need(not rig.data.is_editmode, "Armature must not be in edit mode")
    f = camera.data.dof.bl_rna.properties["aperture_fstop"]
    need(f.hard_min <= q["fstop"] <= f.hard_max, "fstop beyond RNA range")
    return rig


def _pose(camera, rig, bone, graph):
    from mathutils import Vector
    evaluated = rig.evaluated_get(graph)
    point = evaluated.matrix_world @ evaluated.pose.bones[bone].matrix.translation
    mat = camera.evaluated_get(graph).matrix_world
    axis = (mat.to_quaternion() @ Vector((0, 0, -1))).normalized()
    return {"world": list(point), "rig_origin": list(evaluated.matrix_world.translation),
            "axial_distance": (point - mat.translation).dot(axis)}


def state(bpy, scene, camera, q):
    rig = guard(bpy, scene, camera, q)
    dof = camera.data.dof
    return {"use_dof": dof.use_dof, "focus_object": dof.focus_object.name if dof.focus_object else None,
            "focus_subtarget": dof.focus_subtarget, "fstop": dof.aperture_fstop,
            "candidate_pose": _pose(camera, rig, q["focus_subtarget"], bpy.context.evaluated_depsgraph_get())}


def expected(before, q):
    validate(q)
    out = deepcopy(before)
    out.update(use_dof=True, focus_object=q["focus_object"], focus_subtarget=q["focus_subtarget"],
               fstop=struct.unpack("f", struct.pack("f", q["fstop"]))[0])
    return out


def apply(bpy, scene, camera, q):
    rig = guard(bpy, scene, camera, q)
    dof = camera.data.dof
    dof.focus_object = rig
    dof.focus_subtarget = q["focus_subtarget"]
    dof.aperture_fstop = q["fstop"]
    dof.use_dof = True


def bone_focus_witness(camera, depsgraph):
    """Evaluated native binding; geometric axial distance, not rendered blur."""
    d = camera.evaluated_get(depsgraph).data.dof
    need(d.use_dof and d.focus_object and d.focus_object.type == "ARMATURE"
         and d.focus_object.pose.bones.get(d.focus_subtarget), "Missing native bone binding")
    r = d.focus_object.original
    return dict(focus_object=r.name, focus_subtarget=d.focus_subtarget,
                **_pose(camera, r, d.focus_subtarget, depsgraph))
