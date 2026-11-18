"""Finite camera framing diagnostics and camera-space correction suggestions.

audit(bpy, scene, spec) reads explicit subjects and integer sample frames.
Required spec fields are camera, frames and subjects. Each subject has name and
objects, with optional center, center_tolerance, size_range, margin, targets and
look. Margins are [left,right,bottom,top]. size_range is [minimumXY,maximumXY].
Targets use {object, point} with a local point defaulting to the object origin.
look uses {object, axis, minimum_lead}, with the axis in that object's space.
axis uses {a,b,up,side,except_frames}, where a/b are world points or target specs.
allow_occluders lists intentionally transparent-for-diagnosis object names.
safety uses radius and sweep. Sweep checks straight chords between sample poses.
search uses local_x, local_y, lens_ratios, max_offset and locks. Locks contain
local_x, local_y or lens. Candidate poses are evaluated camera-space suggestions.
The caller owns any subsequent editing and persistence operation.
"""
from itertools import product
import math


def _need(ok, message):
    if not ok:
        raise ValueError(message)


def _vector(value, size, label):
    _need(type(value) in (list, tuple) and len(value) == size
          and all(type(x) in (int, float) and math.isfinite(x) for x in value), label)
    return [float(x) for x in value]


def audit(bpy, scene, spec):
    from mathutils import Matrix, Vector

    _need(type(spec) is dict and scene == bpy.context.scene, "Active Scene and explicit spec required")
    frames = spec.get("frames")
    _need(type(frames) is list and 0 < len(frames) <= 240
          and all(type(f) is int and -1048574 <= f <= 1048574 for f in frames) and frames == sorted(set(frames)),
          "Use up to240 ordered unique integer sample frames")
    camera = scene.objects.get(spec.get("camera", ""))
    _need(camera is not None and camera.type == "CAMERA", "Explicit Scene camera required")
    _need(camera.data.type in ("PERSP", "ORTHO"), "UNSUPPORTED: projection type " + camera.data.type)
    subjects = spec.get("subjects")
    _need(type(subjects) is list and 0 < len(subjects) <= 8, "Use1..8 explicit subject groups")
    names = set()
    for subject in subjects:
        _need(type(subject) is dict and type(subject.get("name")) is str
              and subject["name"] and subject["name"] not in names, "Unique named subjects required")
        names.add(subject["name"])
        objects = subject.get("objects")
        _need(type(objects) is list and 0 < len(objects) <= 64 and len(objects) == len(set(objects))
              and all(name in scene.objects and scene.objects[name].type == "MESH" for name in objects),
              "Subject groups require explicit existing mesh names")
        for field, default in (("center", [.5, .5]), ("center_tolerance", [.1, .1]),
                               ("margin", [.02, .02, .02, .02])):
            subject_value = _vector(subject.get(field, default), 4 if field == "margin" else 2, field)
            _need(all(0 <= x <= 1 for x in subject_value), "Normalized " + field + " required")
        limits = subject.get("size_range", [[0, 0], [1, 1]])
        low, high = (_vector(v, 2, "size_range") for v in limits)
        _need(all(0 <= a <= b <= 2 for a, b in zip(low, high)), "Ordered normalized size range required")
        _need(len(subject.get("targets", [])) <= 16, "At most16 visibility targets per subject")
    allow = set(spec.get("allow_occluders", []))
    _need(all(type(name) is str and name in scene.objects for name in allow), "Explicit allowlisted occluders required")
    safety = spec.get("safety", {})
    radius = safety.get("radius", 0.0)
    _need(type(radius) in (int, float) and math.isfinite(radius) and radius >= 0, "Finite safety radius required")
    axis = spec.get("axis")
    if axis:
        _need(axis.get("side") in (-1, 1), "Axis side must be-1 or1")
        _vector(axis.get("up", [0, 0, 1]), 3, "Axis up vector required")
        _need(all(type(f) is int for f in axis.get("except_frames", [])), "Explicit axis exception frames required")
    search = spec.get("search", {})
    locks = set(search.get("locks", []))
    _need(locks <= {"local_x", "local_y", "lens"}, "Unknown correction lock")
    maximum = search.get("max_offset", 0.0)
    _need(type(maximum) in (int, float) and math.isfinite(maximum) and maximum >= 0, "Explicit finite offset budget required")
    xs = [0.0] if "local_x" in locks else search.get("local_x", [0.0])
    ys = [0.0] if "local_y" in locks else search.get("local_y", [0.0])
    lenses = [1.0] if "lens" in locks else search.get("lens_ratios", [1.0])
    for values in (xs, ys, lenses):
        _need(type(values) is list and 0 < len(values) <= 9
              and all(type(v) in (int, float) and math.isfinite(v) for v in values), "Bounded explicit search values required")
    _need(all(abs(v) <= maximum for v in xs + ys) and all(.25 <= v <= 4 for v in lenses), "Search exceeds offset/lens budget")
    _need(camera.data.type == "PERSP" or all(v == 1 for v in lenses), "UNSUPPORTED: lens correction for orthographic projection")
    options = sorted({(0.0, 0.0, 1.0), *product(xs, ys, lenses)})
    _need(len(options) <= 81, "At most81 deterministic correction candidates")
    records = {option: {"issues": [], "samples": [], "score": 0.0} for option in options}
    previous = {}

    def point(target, graph):
        if type(target) in (list, tuple):
            return Vector(_vector(target, 3, "World point required"))
        _need(type(target) is dict and target.get("object") in scene.objects, "Explicit point target object required")
        owner = scene.objects[target["object"]].evaluated_get(graph)
        return owner.matrix_world @ Vector(_vector(target.get("point", [0, 0, 0]), 3, "Local target point required"))

    def ray(origin, target, graph, exemptions, permitted=()):
        direction = target - origin
        length = direction.length
        if length <= 1e-8:
            return None
        direction.normalize()
        travelled = 0.0
        for _ in range(32):
            remaining = length - travelled
            if remaining <= 1e-5:
                return None
            hit, location, normal, face, owner, matrix = scene.ray_cast(graph, origin + direction * travelled,
                                                                       direction, distance=remaining)
            if not hit:
                return None
            name = owner.original.name
            if name in exemptions:
                return None
            distance = (location - origin).length
            if name not in permitted:
                return {"object": name, "distance": distance, "location": list(location), "face": face}
            travelled = distance + max(1e-5, length * 1e-7)
        return {"object": None, "reason": "allowlisted-ray-iteration-limit"}

    def issue(record, frame, kind, subject=None, amount=1.0, witness=None):
        record["issues"].append({"frame": frame, "kind": kind, "subject": subject, "witness": witness})
        record["score"] += 1.0 + max(0.0, float(amount))

    saved = scene.frame_current, scene.frame_subframe, scene.camera
    try:
        for frame in frames:
            scene.frame_set(frame)
            bpy.context.view_layer.update()
            graph = bpy.context.evaluated_depsgraph_get()
            evaluated = camera.evaluated_get(graph)
            base_matrix = evaluated.matrix_world.normalized()
            _need(abs(base_matrix.to_3x3().determinant()) > 1e-12, "Singular camera transform")
            corners = evaluated.data.view_frame(scene=scene)
            _need(all(v.z < 0 for v in corners), "Unsupported camera view frame")
            meshes = {}
            for subject in subjects:
                meshes[subject["name"]] = [obj.matrix_world @ Vector(corner)
                    for name in subject["objects"] for obj in [scene.objects[name].evaluated_get(graph)]
                    for corner in obj.bound_box]
            for option in options:
                x, y, ratio = option
                record = records[option]
                pose = base_matrix @ Matrix.Translation((x, y, 0))
                inverse = pose.inverted()
                origin = pose.translation
                if evaluated.data.type == "PERSP":
                    _need(1 <= evaluated.data.lens * ratio <= 500, "Candidate focal length outside1..500mm")
                    bounds = [[min(v[i] / -v.z for v in corners) / ratio,
                               max(v[i] / -v.z for v in corners) / ratio] for i in (0, 1)]
                else:
                    bounds = [[min(v[i] for v in corners), max(v[i] for v in corners)] for i in (0, 1)]

                def project(world):
                    local = inverse @ world
                    depth = -local.z
                    values = [local[i] / depth if evaluated.data.type == "PERSP" and depth > 1e-10
                              else local[i] for i in (0, 1)]
                    return [(values[i] - bounds[i][0]) / (bounds[i][1] - bounds[i][0]) for i in (0, 1)] + [depth]

                sample = {"frame": frame, "camera_matrix": [list(row) for row in pose],
                          "lens_mm": evaluated.data.lens * ratio, "subjects": []}
                for subject in subjects:
                    name = subject["name"]
                    projected = [project(world) for world in meshes[name]]
                    lo = [min(v[i] for v in projected) for i in (0, 1)]
                    hi = [max(v[i] for v in projected) for i in (0, 1)]
                    size = [b - a for a, b in zip(lo, hi)]
                    center = [(a + b) / 2 for a, b in zip(lo, hi)]
                    witness = {"name": name, "bounds": [lo, hi], "size": size, "center": center,
                               "depth_range": [min(v[2] for v in projected), max(v[2] for v in projected)]}
                    sample["subjects"].append(witness)
                    if min(v[2] for v in projected) <= evaluated.data.clip_start:
                        issue(record, frame, "subject-crosses-near-plane", name, 10, witness)
                    if max(v[2] for v in projected) >= evaluated.data.clip_end:
                        issue(record, frame, "subject-crosses-far-plane", name, 10, witness)
                    margins = subject.get("margin", [.02, .02, .02, .02])
                    deficits = [margins[0] - lo[0], hi[0] - (1 - margins[1]),
                                margins[2] - lo[1], hi[1] - (1 - margins[3])]
                    if max(deficits) > 0:
                        issue(record, frame, "edge-margin", name, max(deficits), witness)
                    desired = subject.get("center", [.5, .5])
                    tolerance = subject.get("center_tolerance", [.1, .1])
                    error = max(abs(center[i] - desired[i]) - tolerance[i] for i in (0, 1))
                    if error > 0:
                        issue(record, frame, "desired-center", name, error, witness)
                    low, high = subject.get("size_range", [[0, 0], [1, 1]])
                    error = max(max(low[i] - size[i], size[i] - high[i]) for i in (0, 1))
                    if error > 0:
                        issue(record, frame, "occupancy", name, error, witness)
                    for target in subject.get("targets", []):
                        target_world = point(target, graph)
                        target_local = inverse @ target_world
                        if not evaluated.data.clip_start < -target_local.z < evaluated.data.clip_end:
                            issue(record, frame, "target-outside-depth-range", name, 4,
                                  {"target": target, "depth": -target_local.z})
                            continue
                        ray_origin = origin
                        if evaluated.data.type == "ORTHO":
                            ray_origin = pose @ Vector((target_local.x, target_local.y, 0.0))
                        blocking = ray(ray_origin, target_world, graph, set(subject["objects"]), allow)
                        if blocking:
                            issue(record, frame, "target-occluded", name, 4, {"target": target, "hit": blocking})
                    look = subject.get("look")
                    if look:
                        owner = scene.objects.get(look.get("object", ""))
                        _need(owner is not None, "Look direction object required")
                        owner = owner.evaluated_get(graph)
                        direction = Vector(_vector(look.get("axis", [1, 0, 0]), 3, "Look axis required"))
                        _need(direction.length > 1e-8, "Nonzero look axis required")
                        a = project(owner.matrix_world.translation)
                        b = project(owner.matrix_world @ direction.normalized())
                        if abs(b[0] - a[0]) < 1e-6:
                            issue(record, frame, "look-direction-depth-aligned", name, witness={"projected_axis": [a, b]})
                            continue
                        sign = 1 if b[0] >= a[0] else -1
                        lead = 1 - hi[0] if sign > 0 else lo[0]
                        minimum_lead = look.get("minimum_lead", .1)
                        _need(type(minimum_lead) in (int, float) and 0 <= minimum_lead <= 1, "Normalized lead room required")
                        if lead < minimum_lead:
                            issue(record, frame, "lead-room", name, minimum_lead - lead, {"direction_x": sign, "lead": lead})
                if axis and frame not in axis.get("except_frames", []):
                    a, b = point(axis["a"], graph), point(axis["b"], graph)
                    normal = (b - a).cross(Vector(axis.get("up", [0, 0, 1])))
                    _need(normal.length > 1e-8, "Axis and up must define a plane")
                    signed = normal.normalized().dot(origin - a) * axis["side"]
                    if signed < 0:
                        issue(record, frame, "axis-side", amount=3, witness={"signed_distance": signed})
                if radius > 0:
                    for direction in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)):
                        blocking = ray(origin, origin + Vector(direction) * radius, graph, set())
                        if blocking:
                            issue(record, frame, "camera-clearance-probe", amount=10, witness=blocking)
                if safety.get("sweep", False) and option in previous:
                    blocking = ray(previous[option], origin, graph, set())
                    if blocking:
                        issue(record, frame, "camera-sampled-chord-collision", amount=10, witness=blocking)
                previous[option] = origin.copy()
                record["samples"].append(sample)
    finally:
        scene.frame_set(saved[0], subframe=saved[1])
        if scene.camera != saved[2]:
            scene.camera = saved[2]
        bpy.context.view_layer.update()
        _need((scene.frame_current, scene.frame_subframe, scene.camera) == saved, "Scene time/camera restoration failed")
    baseline = records[(0.0, 0.0, 1.0)]
    best_option = min(options, key=lambda value: (records[value]["score"],
                       abs(value[0]) + abs(value[1]) + abs(math.log(value[2])), value))
    best = records[best_option]
    improved = best["score"] < baseline["score"]
    return {"schema": "camera-framing-audit/1", "camera": camera.name, "frames": frames,
            "baseline": baseline, "candidate_count": len(options), "locks": sorted(locks), "requested": spec,
            "recommendation": {"local_x": best_option[0], "local_y": best_option[1], "lens_ratio": best_option[2],
                               "improves": improved, "passes_samples": not best["issues"], "validation": best},
            "conflict": bool(best["issues"]), "scene_restored": True,
            "coverage": "Evaluated mesh bound-box corners, explicit visibility rays, six radial clearance probes and optional sampled straight chords",
            "search_scope": "Finite supplied camera-local offset/lens grid evaluated at the explicit sample frames"}
