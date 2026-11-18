"""Finite existing photography-group retime, with native handle planning.

The sealed plan contains complete old/new curves.  It never reconstructs real
Actions or FCurves, and never adopts the observed after-state as an expectation.
"""
from copy import deepcopy
import hashlib
import math
from pathlib import Path
import re

try:
    from . import common as c, production_snapshot as snap
except ImportError:
    import common as c
    import production_snapshot as snap

SCHEMA = "camera-production-retime/1"
REQUEST_KEYS = {"version", "source", "scene", "candidate_name", "session", "baseline", "resources", "operation"}
OP_KEYS = {"kind", "collection", "actions", "markers", "source_interval", "target_interval", "locked_frames"}
DOC_KEYS = {"schema", "kind", "phase", "source_sha256", "scene", "operation", "resources",
            "source_state_sha256", "identity", "scene_info", "actions", "markers", "candidate_name", "content_sha256"}


def _same(a, b):
    return c.canonical(a) == c.canonical(b)


def _hash(value):
    return hashlib.sha256(c.canonical(value)).hexdigest()


def _name(value):
    c.require(type(value) is str and value and value.strip() == value and "\0" not in value,
              "Exact nonempty name required")


def _sha(value):
    c.require(type(value) is str and re.fullmatch("[0-9a-f]{64}", value) is not None, "SHA256 required")


def _descriptor(value):
    c.require(type(value) is dict and set(value) == {"file", "sha256"}, "Exact file/sha256 descriptor required")
    c.require(type(value["file"]) is str and Path(value["file"]).is_absolute()
              and ".." not in Path(value["file"]).parts, "Absolute resource/source path required")
    _sha(value["sha256"])


def _operation(op):
    c.require(type(op) is dict and set(op) == OP_KEYS and op["kind"] == "retime_camera_group",
              "Exact retime_camera_group operation required")
    _name(op["collection"])
    for field in ("actions", "markers"):
        names = op[field]
        c.require(type(names) is list and len(names) <= 100 and all(type(n) is str for n in names)
                  and len(set(names)) == len(names),
                  "Bounded explicit unique " + field + " required")
        for name in names:
            _name(name)
    c.require(bool(op["actions"]), "At least one explicit Action required")
    for field in ("source_interval", "target_interval"):
        interval = op[field]
        c.require(type(interval) is list and len(interval) == 2 and all(type(f) is int for f in interval)
                  and -1048574 <= interval[0] < interval[1] <= 1048575, "Bounded half-open interval required")
    c.require(op["source_interval"] != op["target_interval"], "Retime must change the interval")
    locks = op["locked_frames"]
    c.require(type(locks) is list and len(locks) <= 1000 and all(type(f) is int for f in locks)
              and len(set(locks)) == len(locks), "Explicit unique integer locked frames required")
    for frame in locks:
        c.require(_mapped(frame, op) == frame, "Locked frame would move: " + str(frame))


def validate_request(request):
    c.require(type(request) is dict and set(request) == REQUEST_KEYS
              and type(request["version"]) is int and request["version"] == 6,
              "Exact version 6 production request required")
    _descriptor(request["source"])
    _name(request["scene"])
    _name(request["candidate_name"])
    _operation(request["operation"])
    c.require((request["session"] is None or type(request["session"]) is dict) and request["baseline"] is None,
              "Production uses a read-only GUI session or SAVED_DISK with baseline=None")
    resources = request["resources"]
    c.require(type(resources) is list and len(resources) <= 1000, "Bounded explicit resources required")
    for row in resources:
        _descriptor(row)
    paths = [str(Path(row["file"])).casefold() for row in resources]
    c.require(len(paths) == len(set(paths)) and resources == sorted(resources, key=lambda r: r["file"].casefold()),
              "Resources must be sorted, unique and explicit")
    return request


def _mapped(frame, op):
    a, b = op["source_interval"]
    x, y = op["target_interval"]
    return x + (frame - a) * ((y - x) / (b - a))


def _seal(doc):
    doc["content_sha256"] = _hash({k: v for k, v in doc.items() if k != "content_sha256"})
    return doc


def _validate(doc, kind=None):
    c.require(type(doc) is dict and set(doc) == DOC_KEYS and doc["schema"] == SCHEMA,
              "Exact production plan required")
    c.require(doc["kind"] in ("BASELINE", "CANDIDATE") and (kind is None or doc["kind"] == kind),
              "Production plan kind differs")
    c.require(doc["phase"] in ("SOURCE", "OUTPUT"), "Production plan phase differs")
    _sha(doc["source_sha256"])
    _sha(doc["source_state_sha256"])
    _sha(doc["content_sha256"])
    _name(doc["scene"])
    _name(doc["candidate_name"])
    _operation(doc["operation"])
    c.require(type(doc["actions"]) is dict and set(doc["actions"]) == set(doc["operation"]["actions"]),
              "Explicit complete Action plans required")
    c.require(type(doc["identity"]) is dict and type(doc["scene_info"]) is dict
              and type(doc["markers"]) is list, "Complete source identity/context required")
    c.require(type(doc["resources"]) is list, "Explicit resource ledger required")
    for resource in doc["resources"]:
        _descriptor(resource)
    c.require(len(doc["markers"]) == len(doc["operation"]["markers"]), "Complete marker plans required")
    marker_names = []
    for marker in doc["markers"]:
        c.require(type(marker) is dict and set(marker) == {"name", "before", "after", "camera"}
                  and type(marker["before"]) is int and type(marker["after"]) is int,
                  "Exact integer marker plan required")
        _name(marker["name"])
        _name(marker["camera"])
        marker_names.append(marker["name"])
        wanted = marker["before"] if doc["phase"] == "OUTPUT" else _mapped(marker["before"], doc["operation"])
        c.require(wanted == marker["after"], "Marker plan differs from declared map")
    c.require(len(set(marker_names)) == len(marker_names)
              and set(marker_names) == set(doc["operation"]["markers"]), "Marker plan identities differ")
    if doc["kind"] == "BASELINE":
        c.require(doc["candidate_name"] == "Original", "Baseline name differs")
    for name, row in doc["actions"].items():
        c.require(type(row) is dict and set(row) == {"owner", "before", "after"}
                  and type(row["owner"]) is dict and set(row["owner"]) == {"type", "name"},
                  "Complete Action owner/curve plan required")
        _name(row["owner"]["name"])
        c.require(row["owner"]["type"] in ("Object", "Camera"), "Only photographic owner Actions supported")
        for state in (row["before"], row["after"]):
            c.require(type(state) is dict and set(state) == {"properties", "curves"}
                      and type(state["curves"]) is list and bool(state["curves"]), "Complete native Action required")
            for curve in state["curves"]:
                c.require(not curve["modifiers"] and not curve["sampled_points"] and curve["keys"],
                          "Only existing keyframe curves without modifiers/samples supported")
        _curve_delta(row["before"], row["after"], doc["operation"], output=doc["phase"] == "OUTPUT")
    c.require(_seal(deepcopy(doc))["content_sha256"] == doc["content_sha256"], "Production plan seal differs")
    return doc


def _curve_delta(before, after, op, output=False):
    c.require(before["properties"] == after["properties"] and len(before["curves"]) == len(after["curves"]),
              "Action properties/curve count changed")
    for old, new in zip(before["curves"], after["curves"]):
        x, y = deepcopy(old), deepcopy(new)
        oldkeys, newkeys = x.pop("keys"), y.pop("keys")
        c.require(_same(x, y) and len(oldkeys) == len(newkeys), "Non-time curve fields changed")
        for oldkey, newkey in zip(oldkeys, newkeys):
            p, q = deepcopy(oldkey), deepcopy(newkey)
            for field in ("co", "co_ui", "handle_left", "handle_right"):
                if field in p:
                    oldco, newco = p.pop(field), q.pop(field)
                    c.require(all(math.isfinite(v) for v in oldco + newco), "Nonfinite curve coordinate")
                    if output:
                        c.require(oldco == newco, "Output baseline must preserve current coordinates")
                    elif field in ("co", "co_ui"):
                        # Blender stores coordinates in float32. Native planning is
                        # authoritative, but never permits changing the key value.
                        import struct
                        wanted = struct.unpack("f", struct.pack("f", _mapped(oldco[0], op)))[0]
                        c.require(newco[0] == wanted and newco[1] == oldco[1], "Key time/value differs from affine map")
            c.require(_same(p, q), "Non-time key metadata changed")


def _driver_boundary(inspection, closure, scene):
    """Reject implicit reads; retain unrelated, explicit-ID simple drivers.

    This is a finite dependency gate, not a general Python/RNA data-flow solver.
    Direct outside consumers are independently rejected by the user_map gate.
    """
    forbidden = closure | {scene, scene.collection}
    variable_types = {"SINGLE_PROP", "TRANSFORMS", "ROTATION_DIFF", "LOC_DIFF"}
    driver_types = {"SCRIPTED", "AVERAGE", "SUM", "MIN", "MAX"}
    owners = list(inspection.all_ids())
    seen = {owner.as_pointer() for owner in owners}
    # Material/Light/World embedded trees are IDs but are not necessarily exposed
    # by a bpy.data collection. They can carry their own animation_data/drivers.
    for owner in owners:
        for field in ("node_tree", "compositing_node_group"):
            tree = getattr(owner, field, None)
            if tree is not None and tree.as_pointer() not in seen:
                seen.add(tree.as_pointer())
                owners.append(tree)
    for owner in owners:
        animation = getattr(owner, "animation_data", None)
        if animation is None:
            continue
        for curve in animation.drivers:
            label = owner.bl_rna.identifier + ":" + owner.name + "/" + curve.data_path
            c.require(owner not in closure, "UNSUPPORTED: Photography closure driver: " + label)
            driver = curve.driver
            c.require(driver.type in driver_types, "UNSUPPORTED: Unqualified driver type: " + label)
            if driver.type == "SCRIPTED":
                c.require(driver.is_simple_expression and not driver.use_self,
                          "UNSUPPORTED: Driver may hide Python/self reads: " + label)
            for variable in driver.variables:
                c.require(variable.type in variable_types,
                          "UNSUPPORTED: Driver variable has implicit or unknown ID source: " + label)
                c.require(len(variable.targets) > 0, "UNSUPPORTED: Driver variable lacks explicit ID targets: " + label)
                for target in variable.targets:
                    identity = getattr(target, "id", None)
                    c.require(identity is not None,
                              "UNSUPPORTED: Driver target lacks an explicit ID: " + label)
                    c.require(identity not in forbidden,
                              "UNSUPPORTED: Outside driver reads photography closure or target Scene/rootCollection: " + label)


def _qualify(bpy, request, output=False):
    op = request["operation"]
    scene = bpy.data.scenes.get(request["scene"])
    group = bpy.data.collections.get(op["collection"])
    c.require(scene is not None and bpy.context.scene == scene and group is not None,
              "Existing active requested Scene/Collection required")
    c.require(not scene.library and not group.library and not group.override_library, "Local Scene/group required")
    live_rows = getattr(scene, "camera_live_shots", ())
    saved_live_rows = scene.get("camera_live_shots", ())
    c.require(len(live_rows) == 0 and len(saved_live_rows) == 0,
              "UNSUPPORTED: Nonempty Live shot table requires timing synchronization; production retime supports explicit markers only")
    for existing_scene in bpy.data.scenes:
        c.require(existing_scene.sequence_editor is None or len(existing_scene.sequence_editor.strips_all) == 0,
                  "UNSUPPORTED: Nonempty VSE requires consumer timing synchronization: " + existing_scene.name)
    def descendants(root):
        result = {root}
        for child in root.children:
            result.update(descendants(child))
        return result
    groups = descendants(group)
    c.require(all(not g.library and not g.override_library for g in groups), "Local group closure required")
    scene_groups = {s.name: descendants(s.collection) for s in bpy.data.scenes}
    c.require(group in scene_groups[scene.name]
              and all(not (groups & tree) for name, tree in scene_groups.items() if name != scene.name),
              "Photography Collection must belong only to requested Scene")
    objects = set(group.all_objects)
    c.require(objects and all(o.type in {"CAMERA", "EMPTY", "CURVE"} for o in objects),
              "Photography group admits only CAMERA/EMPTY/CURVE members")
    for obj in objects:
        c.require(not obj.library and not obj.override_library
                  and set(obj.users_scene) == {scene} and set(obj.users_collection) <= groups,
                  "Group member has external Scene/Collection ownership: " + obj.name)
        c.require(obj.parent is None or obj.parent in objects, "External photographic parent unsupported")
        c.require(not obj.modifiers, "Photographic member modifiers unsupported")
        for constraint in obj.constraints:
            target = getattr(constraint, "target", None)
            c.require(target is None or target in objects, "External photographic constraint target unsupported")
        if obj.data:
            c.require(not obj.data.library and not obj.data.override_library and obj.data.users == 1
                      and not obj.data.use_fake_user, "Photographic data must be exclusive")
        if obj.type == "CURVE":
            c.require(obj.data.animation_data is None and obj.data.shape_keys is None,
                      "Animated Curve data/shape keys require another adapter")
    # Do not alter an actor, outside constraint, parent, instance or driver through
    # a reference to this group. Scene/Collection structural links are expected.
    user_map = bpy.data.user_map()
    data = {o.data for o in objects if o.data}
    closure = groups | objects | data
    _, _, inspection, _, _ = snap._runtime()
    _driver_boundary(inspection, closure, scene)
    for target in closure:
        for user in user_map.get(target, set()):
            c.require(user in closure or user == scene or user == scene.collection,
                      "Photography closure has external consumer: " + user.name)
    owners = list(objects) + [o.data for o in objects if o.type == "CAMERA"]
    bindings = {}
    for owner in owners:
        ad = owner.animation_data
        c.require(ad is None or (not ad.drivers and not ad.nla_tracks and not ad.use_tweak_mode),
                  "Group drivers/NLA/tweak mode unsupported")
        if not ad or not ad.action:
            continue
        action, slot = ad.action, ad.action_slot
        c.require(action.name not in bindings and action.name in op["actions"],
                  "Every group Action must be explicitly listed and unique")
        c.require(action.users == 1 and not action.use_fake_user and not action.use_extra_user
                  and not action.library and not action.override_library
                  and set(user_map.get(action, set())) == {owner}, "Shared/external Action rejected")
        c.require(ad.action_blend_type == "REPLACE" and ad.action_influence == 1.0,
                  "Full-influence REPLACE Action required")
        c.require(len(action.slots) == len(action.layers) == 1 and slot == action.slots[0]
                  and len(action.layers[0].strips) == 1, "Single active slot/layer/strip required")
        expected_type = "OBJECT" if owner in objects else "CAMERA"
        c.require(slot.target_id_type == expected_type, "Action slot owner type differs")
        layer = action.layers[0]
        c.require(not getattr(layer, "mute", False) and getattr(layer, "influence", 1.0) == 1.0,
                  "Full-influence unmuted Action layer required")
        strip = layer.strips[0]
        c.require(strip.type == "KEYFRAME" and len(strip.channelbags) == 1
                  and strip.channelbag(slot) == strip.channelbags[0], "Exclusive single KEYFRAME bag required")
        bag = strip.channelbags[0]
        c.require(bool(bag.fcurves), "Nonempty existing Action required")
        lo, hi = op["target_interval"] if output else op["source_interval"]
        for curve in bag.fcurves:
            c.require(not curve.modifiers and not curve.sampled_points and curve.keyframe_points
                      and not curve.lock and not curve.mute, "Editable keyframe curves only")
            c.require(all(lo <= k.co.x < hi for k in curve.keyframe_points), "Key outside declared half-open interval")
            try:
                owner.path_resolve(curve.data_path)
            except (ValueError, TypeError, AttributeError) as exc:
                raise ValueError("Unresolved owner curve path") from exc
        bindings[action.name] = (owner, action, bag)
    c.require(set(bindings) == set(op["actions"]), "Every explicit Action needs exactly one photographic owner")
    interval = op["target_interval"] if output else op["source_interval"]
    c.require([scene.frame_start, scene.frame_end] == [interval[0], interval[1] - 1], "Scene range differs from declared interval")
    selected = [m for m in scene.timeline_markers if m.name in op["markers"]]
    c.require(len(selected) == len(op["markers"]) and len({m.name for m in selected}) == len(selected),
              "Every explicit marker must exist exactly once")
    camera_markers = {m.name for m in scene.timeline_markers if m.camera in objects}
    c.require(camera_markers == set(op["markers"]), "Explicit markers must cover exactly this group's bound cameras")
    c.require(scene.camera in objects and scene.camera.type == "CAMERA", "Scene must use the explicit photographic group")
    for marker in selected:
        c.require(interval[0] <= marker.frame < interval[1], "Marker outside declared interval")
        if not output:
            mapped = _mapped(marker.frame, op)
            c.require(mapped == int(mapped), "Mapped marker is noninteger: " + marker.name)
    identity = {"collection": group.name, "collections": sorted(g.name for g in groups),
                "objects": sorted(o.name for o in objects),
                "owners": {name: {"type": owner.bl_rna.identifier, "name": owner.name,
                    "slot": action.slots[0].identifier, "slot_handle": action.slots[0].handle,
                    "users": action.users, "fake_user": action.use_fake_user}
                    for name, (owner, action, bag) in bindings.items()}}
    return scene, objects, bindings, selected, identity


def _write_curves(bag, curves):
    actual = sorted(bag.fcurves, key=lambda f: (f.data_path, f.array_index))
    c.require(len(actual) == len(curves), "FCurve count changed")
    for curve, wanted in zip(actual, curves):
        c.require(curve.data_path == wanted["data_path"] and curve.array_index == wanted["array_index"]
                  and len(curve.keyframe_points) == len(wanted["keys"]), "Existing curve identity/count differs")
        for key, record in zip(curve.keyframe_points, wanted["keys"]):
            key.co = record["co"]
            key.handle_left = record["handle_left"]
            key.handle_right = record["handle_right"]
        curve.update()


def _baseline_doc(state, sha, request, identity, actions, markers, output):
    return _seal({"schema": SCHEMA, "kind": "BASELINE", "phase": "OUTPUT" if output else "SOURCE",
        "source_sha256": sha, "scene": request["scene"], "operation": deepcopy(request["operation"]),
        "resources": deepcopy(request["resources"]), "source_state_sha256": _hash(state),
        "identity": deepcopy(identity), "scene_info": deepcopy(state["follow"]["scene_metadata"][request["scene"]]),
        "actions": actions, "markers": markers, "candidate_name": "Original"})


def baseline(bpy, native, request, sha=None):
    validate_request(request)
    source_sha = sha or request["source"]["sha256"]
    _sha(source_sha)
    output = source_sha != request["source"]["sha256"]
    c.require(output or bpy.app.background, "Native retime planning is background-only; GUI must capture session without planning")
    scene, objects, bindings, markers, identity = _qualify(bpy, request, output)
    before = snap.capture()
    c.require(_same(snap.resources(before["images"]), request["resources"]), "External resource set drift")
    _, _, _, _, action_state = snap._runtime()
    actions = {}
    saved_time = scene.frame_current + scene.frame_subframe
    for name in request["operation"]["actions"]:
        owner, action, bag = bindings[name]
        old = deepcopy(before["follow"]["complete_actions"][name])
        new = deepcopy(old)
        if not output:
            temporary = None
            try:
                temporary = action.copy()
                temporary.use_fake_user = False
                planned = deepcopy(old["curves"])
                for curve in planned:
                    for key in curve["keys"]:
                        for field in ("co", "handle_left", "handle_right"):
                            key[field][0] = _mapped(key[field][0], request["operation"])
                temp_bag = temporary.layers[0].strips[0].channelbag(temporary.slots[0])
                _write_curves(temp_bag, planned)
                new = action_state(temporary)
                for original, changed in zip(sorted(bag.fcurves, key=lambda f: (f.data_path, f.array_index)),
                                             sorted(temp_bag.fcurves, key=lambda f: (f.data_path, f.array_index))):
                    c.require(original.evaluate(saved_time) == changed.evaluate(saved_time),
                              "Save source on an unchanged common endpoint/plateau before retiming")
            finally:
                if temporary is not None:
                    c.require(temporary.users == 0, "Temporary planning Action acquired a consumer")
                    bpy.data.actions.remove(temporary)
        actions[name] = {"owner": {"type": owner.bl_rna.identifier, "name": owner.name}, "before": old, "after": new}
    c.require(_same(snap.capture(), before), "Native temporary planning changed the source snapshot")
    marker_rows = [{"name": m.name, "before": m.frame,
                    "after": m.frame if output else int(_mapped(m.frame, request["operation"])),
                    "camera": m.camera.name if m.camera else None} for m in markers]
    c.require(request["operation"]["source_interval"][0] <= saved_time < request["operation"]["source_interval"][1]
              and request["operation"]["target_interval"][0] <= saved_time < request["operation"]["target_interval"][1],
              "Saved frame must be inside both intervals")
    def active(rows, key):
        candidates = [r for r in rows if r[key] <= saved_time]
        return max(candidates, key=lambda r: r[key])["camera"] if candidates else None
    c.require(output or (active(marker_rows, "before") or scene.camera.name)
              == (active(marker_rows, "after") or scene.camera.name) == scene.camera.name,
              "Saved-frame camera cut would change; save at a common endpoint")
    return _validate(_baseline_doc(before, source_sha, request, identity, actions, marker_rows, output), "BASELINE")


def candidate(model, base, request):
    validate_request(request)
    _validate(base, "BASELINE")
    c.require(base["phase"] == "SOURCE" and base["source_sha256"] == request["source"]["sha256"]
              and base["scene"] == request["scene"] and _same(base["operation"], request["operation"])
              and _same(base["resources"], request["resources"]), "Production baseline/request differ")
    doc = deepcopy(base)
    doc.update(kind="CANDIDATE", candidate_name=request["candidate_name"])
    return _validate(_seal(doc), "CANDIDATE")


def validate_candidate(doc, request):
    validate_request(request)
    _validate(doc, "CANDIDATE")
    c.require(doc["phase"] == "SOURCE" and doc["source_sha256"] == request["source"]["sha256"]
              and doc["scene"] == request["scene"] and doc["candidate_name"] == request["candidate_name"]
              and _same(doc["operation"], request["operation"]) and _same(doc["resources"], request["resources"]),
              "Production candidate/request differ")
    return doc


def _inspection_curve(curve):
    return {"path": curve["data_path"], "index": curve["array_index"],
        "extrapolation": curve["properties"]["extrapolation"],
        "points": [{"co": k["co"], "left": k["handle_left"], "right": k["handle_right"],
            "interpolation": k["interpolation"], "left_type": k["handle_left_type"],
            "right_type": k["handle_right_type"]} for k in curve["keys"]], "samples": [], "modifiers": []}


def _one(rows, predicate, message):
    selected = [r for r in rows if predicate(r)]
    c.require(len(selected) == 1, message)
    return selected[0]


def expected(before, doc):
    _validate(doc, "CANDIDATE")
    c.require(_hash(before) == doc["source_state_sha256"], "Complete production source witness differs")
    out = deepcopy(before)
    scene_name = doc["scene"]
    target = doc["operation"]["target_interval"]
    for name, plan in doc["actions"].items():
        c.require(_same(out["follow"]["complete_actions"][name], plan["before"]), "Source native Action differs")
        out["follow"]["complete_actions"][name] = deepcopy(plan["after"])
    for scene_state in (out["follow"]["rig"]["scene"], out["material"]["scene"]):
        row = _one(scene_state["scenes"], lambda r: r["name"] == scene_name, "Unique Scene report required")
        row["timeline"][:2] = [target[0], target[1] - 1]
        block = _one(scene_state["datablocks"], lambda r: r["type"] == "Scene" and r["name"] == scene_name,
                     "Unique Scene datablock required")
        block["scene"]["frames"] = [target[0], target[1] - 1]
        for name, plan in doc["actions"].items():
            block = _one(scene_state["datablocks"], lambda r: r["type"] == "Action" and r["name"] == name,
                         "Unique Action datablock required")
            bags = block["action"]["layers"][0]["strips"][0]["bags"]
            c.require(len(bags) == 1, "Unique repeated Action bag required")
            wanted_old = [_inspection_curve(curve) for curve in plan["before"]["curves"]]
            c.require(_same(sorted(bags[0]["curves"], key=lambda r: (r["path"], r["index"])), wanted_old),
                      "Repeated Action source witness differs")
            # inspection sorts by canonical JSON, not by channel identity.
            bags[0]["curves"] = sorted([_inspection_curve(curve) for curve in plan["after"]["curves"]],
                                       key=lambda r: c.canonical(r).decode("utf-8"))
    meta = out["follow"]["scene_metadata"][scene_name]
    c.require(_same(meta, doc["scene_info"]), "Complete saved Scene context differs")
    meta["range"] = [target[0], target[1] - 1]
    for collection in (meta["markers"], out["follow"]["markers"]):
        for plan in doc["markers"]:
            marker = _one(collection, lambda r: r["name"] == plan["name"], "Unique marker source required")
            c.require(marker["frame"] == plan["before"] and marker["camera"] == plan["camera"], "Marker source differs")
            marker["frame"] = plan["after"]
    return out


def apply(bpy, native, doc):
    _validate(doc, "CANDIDATE")
    request = {"version": 6, "source": {"file": str(Path(bpy.data.filepath)), "sha256": doc["source_sha256"]},
               "scene": doc["scene"], "candidate_name": doc["candidate_name"], "session": {}, "baseline": None,
               "resources": doc["resources"], "operation": doc["operation"]}
    scene, objects, bindings, markers, identity = _qualify(bpy, request)
    c.require(_same(identity, doc["identity"]), "Production Action ownership drift")
    before = snap.capture()
    wanted = expected(before, doc)
    for name, plan in doc["actions"].items():
        _write_curves(bindings[name][2], plan["after"]["curves"])
    for marker in markers:
        marker.frame = _one(doc["markers"], lambda r: r["name"] == marker.name, "Marker plan missing")["after"]
    lo, hi = doc["operation"]["target_interval"]
    scene.frame_start, scene.frame_end = lo, hi - 1
    bpy.context.view_layer.update()
    c.require(_same(snap.capture(), wanted), "Undeclared production retime delta")
    return scene


def projection(bpy, native, doc, request, selected=False):
    validate_candidate(doc, request)
    c.require(type(selected) is bool, "Boolean selected projection required")
    scene, objects, bindings, markers, identity = _qualify(bpy, request, output=selected)
    c.require(_same(identity, doc["identity"]), "Projection ownership differs")
    before = snap.capture()
    for name, plan in doc["actions"].items():
        c.require(_same(before["follow"]["complete_actions"][name], plan["after" if selected else "before"]),
                  "Projection Action differs from sealed plan")
    interval = doc["operation"]["target_interval" if selected else "source_interval"]
    first, end = interval
    frames = sorted({first, end - 1, *[m.frame for m in markers],
                     *[first + (end - 1 - first) * n / 4 for n in (1, 2, 3)]})
    frame, subframe, camera = scene.frame_current, scene.frame_subframe, scene.camera
    rows = []
    try:
        for value in frames:
            integer = math.floor(value)
            scene.frame_set(integer, subframe=value - integer)
            bpy.context.view_layer.update()
            graph = bpy.context.evaluated_depsgraph_get()
            cameras = []
            for obj in sorted((o for o in objects if o.type == "CAMERA"), key=lambda o: o.name):
                evaluated = obj.evaluated_get(graph)
                data = evaluated.data
                cameras.append({"camera": obj.name, "matrix_world": [list(row) for row in evaluated.matrix_world],
                    "lens": data.lens, "focus_distance": data.dof.focus_distance,
                    "focus_object": data.dof.focus_object.name if data.dof.focus_object else None})
            rows.append({"frame": value, "active_camera": scene.camera.name if scene.camera else None, "cameras": cameras})
    finally:
        scene.frame_set(frame, subframe=subframe)
        scene.camera = camera
        bpy.context.view_layer.update()
    c.require(_same(snap.capture(), before), "Projection failed to restore complete Scene/camera state")
    return {"schema": "camera-production-projection/1", "scene": scene.name, "interval": interval, "samples": rows}


def verify_next(base, doc, state, output_sha, request):
    validate_candidate(doc, request)
    _validate(base, "BASELINE")
    _sha(output_sha)
    c.require(type(state) is dict, "Production state receipt must be a dictionary")
    if set(state) == {"schema", "before", "expected"}:
        c.require(state["schema"] == "camera-production-state/1", "Deduplicated state schema differs")
        before, after = state["before"], state["expected"]
        c.require(_same(expected(before, doc), after), "Deduplicated expectation differs from sealed source delta")
    else:
        c.require(set(state) == {"raw", "primed", "expected_raw", "expected_primed"}, "Complete production state receipt required")
        for source, target in (("raw", "expected_raw"), ("primed", "expected_primed")):
            c.require(_same(expected(state[source], doc), state[target]), "Expected production state differs from source delta")
        c.require(_same(state["raw"], state["primed"]) and _same(state["expected_raw"], state["expected_primed"]),
                  "Production prime may not change source state")
        before, after = state["primed"], state["expected_primed"]
    actions = {name: {"owner": deepcopy(plan["owner"]), "before": deepcopy(plan["after"]),
                      "after": deepcopy(plan["after"])} for name, plan in doc["actions"].items()}
    markers = [{**deepcopy(plan), "before": plan["after"]} for plan in doc["markers"]]
    wanted = _baseline_doc(after, output_sha, request, doc["identity"], actions, markers, True)
    c.require(_same(base, wanted), "Cold reopened production baseline differs from source-derived expectation")
    return True
