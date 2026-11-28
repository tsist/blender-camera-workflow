"""Generate an editable camera on a saved-copy worker, using scene units and frames."""
import math

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Euler, Vector


def anchor(scene, name, bone=None):
    obj = scene.objects[name].evaluated_get(bpy.context.evaluated_depsgraph_get())
    if bone:
        if obj.type != "ARMATURE" or bone not in obj.pose.bones:
            raise ValueError(f"Unknown bone {name}/{bone}")
        return obj.matrix_world @ obj.pose.bones[bone].head
    return obj.matrix_world.translation.copy()


def generate(scene, spec):
    """Create a new camera; do not replace the scene camera or edit shared camera data."""
    name = spec["name"]
    first, last = spec["frames"]
    if name in bpy.data.objects or not 0 < last - first < 100000:
        raise ValueError("Camera name must be new and frame range must contain 2–100000 frames")
    mode = spec["motion"]
    if mode not in {"orbit", "dolly", "crane", "follow_path", "handheld", "static"}:
        raise ValueError("Unknown camera motion")
    target = scene.objects[spec["target"]]
    bone = spec.get("bone", "")
    track = spec.get("track", "DAMPED_TRACK")
    if track not in {"TRACK_TO", "DAMPED_TRACK", "BAKED"}:
        raise ValueError("Unknown camera tracking mode")
    start = Vector(spec["start"])
    end = Vector(spec.get("end", start))
    data = bpy.data.cameras.new(name)
    cam = bpy.data.objects.new(name, data)
    scene.collection.objects.link(cam)
    cam.rotation_mode = "XYZ"
    data.show_composition_thirds = spec.get("thirds", True)
    data.show_safe_areas = spec.get("safe_areas", True)
    data.show_passepartout = True
    data.passepartout_alpha = spec.get("passepartout", 0.9)
    data.dof.use_dof = spec.get("dof", False)
    if mode == "follow_path":
        path = scene.objects[spec["path"]]
        if path.type != "CURVE":
            raise ValueError("A CURVE object is required for follow_path")
        follow = cam.constraints.new("FOLLOW_PATH")
        follow.target = path
        follow.use_fixed_location = True
        for frame, offset in ((first, 0.0), (last, 1.0)):
            follow.offset_factor = offset
            follow.keyframe_insert(data_path="offset_factor", frame=frame)
    if track != "BAKED":
        constraint = cam.constraints.new(track)
        constraint.target = target
        constraint.subtarget = bone
        constraint.track_axis = "TRACK_NEGATIVE_Z"
        if track == "TRACK_TO":
            constraint.up_axis = "UP_Y"
    fps = scene.render.fps / scene.render.fps_base
    old_frame, subframe = scene.frame_current, scene.frame_subframe
    lens = float(spec.get("lens", 45))
    amplitude = spec.get("handheld_amplitude", 0.016 if mode == "handheld" else 0)
    hz = spec.get("handheld_hz", 1.6)
    if not 0 < lens <= 5000 or not 0 <= hz < fps / 2 or amplitude < 0:
        raise ValueError("Invalid lens or handheld amplitude/frequency")
    try:
        scene.frame_set(first)
        origin = anchor(scene, target.name, bone)
        initial_distance = (start - origin).length
        if mode == "follow_path":
            initial_distance = (cam.matrix_world.translation - origin).length
        if initial_distance < 1e-6:
            raise ValueError("Camera and target coincide")
        for frame in range(first, last + 1):
            scene.frame_set(frame)
            center = anchor(scene, target.name, bone)
            u = (frame - first) / (last - first)
            blend = u * u * (3 - 2 * u) if spec.get("ease", True) else u
            if mode == "orbit":
                relative = start - origin
                relative.rotate(Euler((0, 0, math.radians(spec["angle_deg"]) * blend)))
                location = center + relative
            elif mode == "crane":
                location = start + Vector((0, 0, (end.z - start.z) * blend))
            elif mode == "follow_path":
                location = Vector((0, 0, 0))
            elif mode == "static":
                location = start.copy()
            else:
                location = start.lerp(end, blend)
            phase = (frame - first) / fps * 2 * math.pi * hz
            location += amplitude * Vector((math.sin(phase), math.sin(phase * 0.73),
                                             math.sin(phase * 0.53)))
            cam.location = location
            cam.keyframe_insert(data_path="location", frame=frame)
            bpy.context.view_layer.update()
            direction = center - cam.matrix_world.translation
            if track == "BAKED":
                orientation = direction.to_track_quat("-Z", "Y")
                cam.rotation_euler = orientation.to_euler("XYZ", cam.rotation_euler)
                cam.keyframe_insert(data_path="rotation_euler", frame=frame)
            distance = max(data.clip_start, direction.length)
            data.dof.focus_distance = distance
            data.dof.keyframe_insert(data_path="focus_distance", frame=frame)
            data.lens = lens * (1 + spec.get("breathing", 0) * (initial_distance / distance - 1))
            data.keyframe_insert(data_path="lens", frame=frame)
    finally:
        scene.frame_set(old_frame, subframe=subframe)
    return cam


def diagnose(scene, camera, subject, bone="", desired=(0.5, 0.5), size_ratio=1):
    """Camera-local corrections for one anchor, including roll and optical-axis dolly."""
    if size_ratio <= 0:
        raise ValueError("size_ratio must be positive")
    point = anchor(scene, subject, bone)
    projected = world_to_camera_view(scene, camera, point)
    if projected.z <= 0:
        raise ValueError("Anchor is behind camera")
    corners = camera.data.view_frame(scene=scene)
    horizontal = max(p.x for p in corners) - min(p.x for p in corners)
    vertical = max(p.y for p in corners) - min(p.y for p in corners)
    depth = abs(corners[0].z)
    orientation = camera.matrix_world.to_quaternion()
    up = orientation.inverted() @ Vector((0, 0, 1))
    report = {"anchor_ndc": list(projected), "projection": camera.data.type,
              "roll_to_level_deg": math.degrees(math.atan2(-up.x, up.y))}
    if camera.data.type == "ORTHO":
        report.update(local_x=(projected.x - desired[0]) * horizontal,
                      local_y=(projected.y - desired[1]) * vertical,
                      ortho_scale=camera.data.ortho_scale / size_ratio)
    elif camera.data.type == "PERSP":
        left=min(p.x for p in corners)
        bottom=min(p.y for p in corners)
        report.update(yaw_deg=math.degrees(math.atan2(left + projected.x*horizontal, depth)
                                           - math.atan2(left + desired[0]*horizontal, depth)),
                      tilt_deg=math.degrees(math.atan2(bottom + projected.y*vertical, depth)
                                           - math.atan2(bottom + desired[1]*vertical, depth)),
                      dolly_towards_subject=projected.z * (1 - 1 / size_ratio))
    else:
        raise ValueError("Framing corrections require a perspective or orthographic camera")
    return report

