"""Windows-only bounded in-place Focus onset continuation on an existing EMPTY.

This explicitly differs from the restored Linux Focus clone/retain transaction:
no Action is cloned, retained, renamed or removed here. Only the second XYZ key
and its two FREE handles move in time. The old four-key lock/plateau constraints
and move-key mathematics are retained. The caller owns source-byte guards,
raw/primed witnesses, persistence and independent cold opens.
"""
from copy import deepcopy
import importlib
import math
import struct

try:
    from . import cut_ops, motion_ops as motion
except ImportError:
    import cut_ops
    import motion_ops as motion


SCHEMA = "camera-existing-empty-focus-onset-candidate/1"
SCOPE = "Windows exclusive EMPTY Focus onset in place; no Action clone/retention or optical edits"
REQUEST_KEYS = {"version", "source", "scene", "shot", "helper", "new_start", "locked_frames",
                "candidate_name", "session", "baseline"}
KEYS = {"schema", "scope", "kind", "source_sha256", "scene", "source_mode", "catalog", "base_rows",
        "shot", "camera", "camera_data", "helper", "action", "slot_handle", "slot_identifier",
        "base_bag", "base_action", "base_protected_action", "base_binding", "base_camera_record",
        "base_helper_record", "base_camera_pose", "base_helper_pose", "source_info", "identity",
        "optical_witness", "locked_frames", "current_start", "new_start", "allowed_changes",
        "candidate_name", "content_sha256"}
need = motion.need
_same = motion._same
_name = motion._name
_sha = motion._sha
_seal = motion._seal


def _f32(value):
    need(type(value) in (int, float) and math.isfinite(value), "Finite Focus coordinate required")
    try:
        result = struct.unpack("<f", struct.pack("<f", value))[0]
    except (OverflowError, struct.error) as exc:
        raise ValueError("Focus coordinate exceeds float32") from exc
    need(math.isfinite(result), "Finite float32 Focus coordinate required")
    return result


def _frame(value):
    need(type(value) is int and -1048574 <= value <= 1048574 and _f32(value) == value,
         "Bounded representable integer Focus frame required")
    return value


def _locks(value):
    need(type(value) is list and len(value) == 3, "Three explicit Focus locks required")
    result = [_frame(v) for v in value]
    need(result[0] < result[1] < result[2], "Strictly increasing Focus locks required")
    return result


def _bag_start(bag, locked_frames):
    locks = _locks(locked_frames)
    need(type(bag) is list and len(bag) == 3, "Exactly three Focus XYZ curves required")
    # Also validates the complete native-curve/key schema and co_ui duplicate.
    motion._strict_curves(bag)
    starts, moving = [], False
    for index, curve in enumerate(bag):
        props = curve["properties"]
        need(curve["data_path"] == "location" and type(curve["array_index"]) is int
             and curve["array_index"] == index, "Ordered unique Focus XYZ channels required")
        need(not curve["modifiers"] and not curve["sampled_points"]
             and props["extrapolation"] == "CONSTANT" and props["mute"] is False and props["lock"] is False,
             "Focus curves must be plain CONSTANT, unlocked and unmuted")
        keys = curve["keys"]
        need(type(keys) is list and len(keys) == 4, "Exactly four Focus keys required")
        times = []
        for key in keys:
            need(key["interpolation"] == "LINEAR"
                 and key["handle_left_type"] == key["handle_right_type"] == "FREE",
                 "Focus requires exact LINEAR/FREE keys")
            for field in ("co", "handle_left", "handle_right"):
                value = key[field]
                need(type(value) is list and len(value) == 2
                     and all(type(v) in (int, float) and math.isfinite(v) and _f32(v) == v for v in value),
                     "Complete finite float32 Focus key/handle coordinates required")
            t = key["co"][0]
            need(int(t) == t, "Integer authored Focus key times required")
            times.append(_frame(int(t)))
        need(times[0] < times[1] < times[2] < times[3]
             and [times[0], times[2], times[3]] == locks, "Focus keys differ from explicit locks")
        need(_same(keys[0]["co"][1], keys[1]["co"][1])
             and _same(keys[2]["co"][1], keys[3]["co"][1]), "Focus needs constant outer plateaus")
        moving = moving or keys[1]["co"][1] != keys[2]["co"][1]
        starts.append(times[1])
    need(len(set(starts)) == 1, "Focus XYZ onset times differ")
    need(moving, "Static Focus helper has no transfer to retime")
    return starts[0]


def _moved_bag(bag, locked_frames, new_start):
    """Pure source-derived move: co.x and FREE handle x += delta, float32 readback.

    co_ui is the native duplicate of co, not an independently editable channel.
    The real RNA writer changes co.x; its co_ui.x must follow on native readback.
    """
    first = _bag_start(bag, locked_frames)
    _frame(new_start)
    need(locked_frames[0] < new_start < locked_frames[1], "Focus onset must remain strictly inside locks")
    delta = new_start - first
    result = deepcopy(bag)
    for curve in result:
        key = curve["keys"][1]
        key["co"][0] = _f32(new_start)
        for field in ("handle_left", "handle_right"):
            key[field][0] = _f32(key[field][0] + delta)
        if "co_ui" in key:
            key["co_ui"][0] = _f32(new_start)
    need(_bag_start(result, locked_frames) == new_start, "Moved Focus bag readback differs")
    return result


def _outside(info, locks):
    time = info["time"]
    need(type(time) is list and len(time) == 2 and type(time[0]) is int
         and type(time[1]) in (int, float) and math.isfinite(time[1]) and 0 <= time[1] < 1,
         "Exact saved frame/subframe required")
    value = time[0] + time[1]
    need(value <= locks[0] or value >= locks[2], "Save source at/outside Focus outer locks first")


def _unit_pose(pose):
    for field in ("scale", "delta_scale"):
        need(pose[field] == [1.0, 1.0, 1.0], "Focus helper requires unit scale/delta scale")
    for field in ("rotation_euler", "delta_location", "delta_rotation_euler"):
        need(pose[field] == [0.0, 0.0, 0.0], "Focus helper requires identity rotation/delta")
    for field in ("rotation_quaternion", "delta_rotation_quaternion"):
        need(pose[field] == [1.0, 0.0, 0.0, 0.0], "Focus helper requires identity quaternion/delta")
    need(pose["rotation_mode"] == "XYZ" and pose["rotation_axis_angle"][0] == 0.0,
         "Focus helper requires identity XYZ rotation")


def _identity(state, camera, data, helper, action):
    strict = state["strict_rig_scene"]
    return {key: {"id": deepcopy(strict["ids"][key]), "references": deepcopy(strict["references"][key])}
            for key in ("Object:" + camera, "Camera:" + data, "Object:" + helper, "Action:" + action)}


def _allowed(action):
    return {"action": action, "representations": ["protected.actions", "strict_rig_scene.actions"],
            "curves": [{"data_path": "location", "array_index": i, "key_index": 1,
                        "coordinates": ["co.x", "handle_left.x", "handle_right.x"],
                        "native_duplicate": "co_ui.x follows co.x"} for i in range(3)]}


def _optics_consistent(doc):
    optical, data, camera = doc["optical_witness"], doc["camera_data"], doc["camera"]
    need(type(optical) is dict
         and set(optical) == {"camera_optics", "strict_cameras", "protected_camera_data"},
         "Complete Focus optical witnesses required")
    selected = optical["camera_optics"][data]
    compact = optical["protected_camera_data"][camera]
    strict = optical["strict_cameras"][data]["dof"]
    need(selected["type"] == "PERSP" and selected["dof"]["use_dof"] is True
         and selected["dof"]["focus_object"] == doc["helper"]
         and compact["dof"] is True and compact["focus"] == doc["helper"]
         and strict["properties"]["use_dof"] is True and strict["properties"]["focus_subtarget"] == ""
         and _same(strict["focus_object"], {"type": "Object", "name": doc["helper"], "library": None}),
         "Existing direct EMPTY Focus with enabled DOF required")
    need(_same(compact["fstop"], selected["dof"]["aperture_fstop"])
         and _same(strict["properties"]["aperture_fstop"], selected["dof"]["aperture_fstop"]),
         "Focus f-stop duplicate witnesses differ")
    actual_focus = [name for name, value in optical["camera_optics"].items()
                    if value["dof"]["focus_object"] == doc["helper"]]
    need(actual_focus == [data], "Focus helper is reused by another Camera data")


def _validate(document, kind=None):
    need(type(document) is dict and set(document) == KEYS, "Exact Focus onset document required")
    doc = deepcopy(document)
    need(doc["schema"] == SCHEMA and doc["scope"] == SCOPE, "Focus onset schema/scope differs")
    need(doc["kind"] in ("BASELINE", "CANDIDATE") and (kind is None or doc["kind"] == kind),
         "Focus document kind differs")
    _sha(doc["source_sha256"])
    for field in ("scene", "shot", "camera", "camera_data", "helper", "action", "slot_identifier", "candidate_name"):
        _name(doc[field])
    need(doc["helper"] != doc["camera"], "Focus helper cannot be its camera")
    motion._table(doc)
    _locks(doc["locked_frames"])
    current = _bag_start(doc["base_bag"], doc["locked_frames"])
    need(type(doc["current_start"]) is int and doc["current_start"] == current, "Source Focus onset differs")
    _frame(doc["new_start"])
    need(doc["locked_frames"][0] < doc["new_start"] < doc["locked_frames"][1],
         "Focus onset must remain strictly inside locks")
    need(type(doc["source_info"]) is dict and set(doc["source_info"]) == {"range", "time", "render"},
         "Complete Focus source context required")
    _outside(doc["source_info"], doc["locked_frames"])
    _unit_pose(doc["base_helper_pose"])
    binding, action = doc["base_binding"], doc["base_action"]
    need(type(doc["slot_handle"]) is int and binding["action"] == doc["action"]
         and binding["slot"] == doc["slot_identifier"] and binding["slot_handle"] == doc["slot_handle"],
         "Focus Action/slot binding differs")
    need(_same(doc["base_helper_record"]["binding"], binding)
         and doc["base_helper_record"]["type"] == "EMPTY" and doc["base_helper_record"]["data"] is None,
         "Focus helper identity/binding differs")
    need(doc["base_camera_record"]["type"] == "CAMERA"
         and _same(doc["base_camera_record"]["data"],
                   {"type": "Camera", "name": doc["camera_data"], "library": None}),
         "Focus camera/data identity differs")
    need(_same(action["curves"], motion._strict_curves(doc["base_bag"])),
         "Complete Focus source Action/bag differs")
    need(action["use_fake_user"] is False and len(action["slots"]) == 1
         and action["slots"][0]["identifier"] == doc["slot_identifier"]
         and action["slots"][0]["properties"]["handle"] == doc["slot_handle"]
         and action["slots"][0]["properties"]["target_id_type"] == "OBJECT"
         and action["bag"]["slot_handle"] == doc["slot_handle"], "Focus strict slot/bag differs")
    compact = doc["base_protected_action"]
    compact_bag = motion._compact_bag(compact)
    need(compact["slots"] == [[doc["slot_identifier"], doc["slot_handle"], "OBJECT"]]
         and compact_bag["slot"] == doc["slot_handle"]
         and _same(compact_bag["curves"], motion._compact_curves(doc["base_bag"])),
         "Focus protected Action/bag differs")
    expected_ids = {"Object:" + doc["camera"], "Camera:" + doc["camera_data"],
                    "Object:" + doc["helper"], "Action:" + doc["action"]}
    need(type(doc["identity"]) is dict and set(doc["identity"]) == expected_ids,
         "Complete Focus target ID/reference witnesses required")
    for key, count in (("Object:" + doc["camera"], 2), ("Camera:" + doc["camera_data"], 1),
                       ("Object:" + doc["helper"], 1), ("Action:" + doc["action"], 1)):
        ident = doc["identity"][key]["id"]
        need(type(ident["users"]) is int and ident["users"] == count
             and ident["use_fake_user"] is False and ident["use_extra_user"] is False,
             "Focus requires exclusive actual ID users without fake/extra")
    _optics_consistent(doc)
    need(_same(doc["allowed_changes"], _allowed(doc["action"])), "Focus allowed-change domain differs")
    if doc["kind"] == "BASELINE":
        need(doc["new_start"] == current and doc["candidate_name"] == "Original", "Focus baseline differs")
    else:
        need(doc["new_start"] != current, "Focus candidate makes no change")
        _moved_bag(doc["base_bag"], doc["locked_frames"], doc["new_start"])
    _sha(doc["content_sha256"])
    need(_seal(deepcopy(doc))["content_sha256"] == doc["content_sha256"], "Focus content seal differs")
    return doc


def _baseline_from_state(state, source_sha, scene_name, shot, helper, locked_frames, bag):
    """Pure sealed-state rebuild using explicit frozen contract dependencies."""
    if __package__:
        from ._vendor.camera_placement_copy import rig_contract, table_model
    else:
        from _vendor.camera_placement_copy import rig_contract, table_model
    rows, catalog = cut_ops._rows_contract(state, scene_name, rig_contract=rig_contract, model=table_model)
    chosen = [row for row in rows if row["name"] == shot]
    need(len(chosen) == 1, "Exactly one named Focus shot required")
    camera = chosen[0]["camera"]
    strict = state["strict_rig_scene"]
    helper_record, camera_record = strict["objects"][helper], strict["objects"][camera]
    data, binding = camera_record["data"]["name"], helper_record["binding"]
    action = binding["action"]
    current = _bag_start(bag, locked_frames)
    need(state["protected"]["objects"][helper]["action"] == action, "Protected Focus helper Action differs")
    need(helper not in strict["rig_context"]["bindings"]
         and helper not in {value["parent"]["name"] for value in strict["rig_context"]["bindings"].values()
                            if value["parent"] is not None}, "Focus helper cannot be a rig binding/root")
    doc = {"schema": SCHEMA, "scope": SCOPE, "kind": "BASELINE", "source_sha256": source_sha,
           "scene": scene_name, "source_mode": "SEQUENCE", "catalog": deepcopy(catalog),
           "base_rows": deepcopy(rows), "shot": shot, "camera": camera, "camera_data": data,
           "helper": helper, "action": action, "slot_handle": binding["slot_handle"],
           "slot_identifier": binding["slot"], "base_bag": deepcopy(bag),
           "base_action": deepcopy(strict["actions"][action]),
           "base_protected_action": deepcopy(state["protected"]["actions"][action]),
           "base_binding": deepcopy(binding), "base_camera_record": deepcopy(camera_record),
           "base_helper_record": deepcopy(helper_record),
           "base_camera_pose": deepcopy(state["object_transforms"][camera]),
           "base_helper_pose": deepcopy(state["object_transforms"][helper]),
           "source_info": motion._info(state), "identity": _identity(state, camera, data, helper, action),
           "optical_witness": motion._optics(state), "locked_frames": deepcopy(locked_frames),
           "current_start": current, "new_start": current, "allowed_changes": _allowed(action),
           "candidate_name": "Original"}
    return _validate(_seal(doc), "BASELINE")


def _qualify(bpy, native, scene_name, shot, helper_name, locked_frames):
    _name(helper_name)
    _locks(locked_frames)
    scene, state, rows, _ = cut_ops._scene(bpy, native, scene_name)
    chosen = [row for row in rows if row["name"] == shot]
    need(len(chosen) == 1, "Exactly one named Focus shot required")
    camera = scene.objects.get(chosen[0]["camera"])
    need(camera is not None and camera.type == "CAMERA" and camera.data.type == "PERSP"
         and camera.parent is None and not camera.constraints and not camera.modifiers
         and not native.has_animation(camera), "Static parentless Focus camera required")
    data = camera.data
    need(data.animation_data is None and data.users == 1 and not data.use_fake_user and not data.use_extra_user
         and [obj for obj in bpy.data.objects if obj.type == "CAMERA" and obj.data == data] == [camera]
         and sum(row["camera"] == camera.name for row in rows) == 1,
         "Exclusive unanimated Camera data and unique Focus shot required")
    helper = scene.objects.get(helper_name)
    need(helper is not None and helper != camera and helper.type == "EMPTY" and helper.data is None
         and helper.parent is None and not helper.constraints and not helper.modifiers
         and helper.instance_type == "NONE" and not helper.library and not helper.override_library,
         "Existing flat local EMPTY Focus helper required")
    need(data.dof.use_dof and data.dof.focus_object == helper and data.dof.focus_subtarget == ""
         and [c for c in bpy.data.cameras if c.dof.focus_object == helper] == [data],
         "Enabled direct EMPTY Focus must belong to exactly one camera")
    need(helper.users == 1 and not helper.use_fake_user and not helper.use_extra_user
         and tuple(helper.users_scene) == (scene,) and len(helper.users_collection) == 1,
         "Focus helper requires one actual user without fake/extra")
    collection = helper.users_collection[0]
    need(set(bpy.data.user_map(subset={helper}).get(helper, set())) == {scene, collection, data},
         "Focus helper has undeclared real reverse references")
    _unit_pose(state["object_transforms"][helper_name])
    ad = helper.animation_data
    need(ad is not None and ad.action is not None and not ad.drivers and not ad.nla_tracks
         and not ad.use_tweak_mode and ad.action_blend_type == "REPLACE" and ad.action_influence == 1.0,
         "Focus requires one full-influence active Action without drivers/NLA")
    action, slot = ad.action, ad.action_slot
    need(not action.library and not action.override_library and action.users == 1
         and not action.use_fake_user and not action.use_extra_user
         and set(bpy.data.user_map(subset={action}).get(action, set())) == {helper},
         "Focus Action must have exactly the helper as its actual user")
    need(len(action.slots) == 1 and slot is not None and slot == action.slots[0]
         and slot.target_id_type == "OBJECT" and len(action.layers) == 1
         and len(action.layers[0].strips) == 1, "Focus requires one active OBJECT slot/layer/strip")
    layer = action.layers[0]
    need(not getattr(layer, "mute", False) and getattr(layer, "influence", 1.0) == 1.0,
         "Focus Action layer must be unmuted/full influence")
    strip = layer.strips[0]
    need(strip.type == "KEYFRAME" and len(strip.channelbags) == 1, "Focus requires exactly one KEYFRAME bag")
    bag = strip.channelbag(slot)
    need(bag is not None and bag == strip.channelbags[0] and bag.slot_handle == slot.handle,
         "Focus active slot/bag identity differs")
    shared = importlib.import_module(native.__package__ + ".rig_witness")
    raw_bag = cut_ops._wire([shared.curve_state(c) for c in sorted(
        bag.fcurves, key=lambda c: (c.data_path, c.array_index))])
    _bag_start(raw_bag, locked_frames)
    _outside(motion._info(state), locked_frames)
    need(state["strict_rig_scene"]["objects"][helper_name]["binding"]["action"] == action.name
         and state["strict_rig_scene"]["objects"][helper_name]["binding"]["slot_handle"] == slot.handle,
         "Native Focus Action/slot differs from sealed witnesses")
    return scene, camera, helper, bag, raw_bag, state


def baseline(bpy, native, source_sha, scene_name, shot, helper, locked_frames):
    _sha(source_sha)
    _, _, _, _, bag, state = _qualify(bpy, native, scene_name, shot, helper, locked_frames)
    return _baseline_from_state(state, source_sha, scene_name, shot, helper, locked_frames, bag)


def candidate(base, request):
    doc = _validate(base, "BASELINE")
    need(type(request) is dict and set(request) == REQUEST_KEYS and type(request["version"]) is int
         and request["version"] == 5, "Exact Focus version5 request required")
    need(type(request["source"]) is dict and set(request["source"]) == {"file", "sha256"}
         and type(request["source"]["file"]) is str and bool(request["source"]["file"])
         and request["source"]["sha256"] == doc["source_sha256"] and request["scene"] == doc["scene"]
         and request["shot"] == doc["shot"] and request["helper"] == doc["helper"]
         and _same(_locks(request["locked_frames"]), doc["locked_frames"]),
         "Focus request source/shot/helper/locks differ")
    doc.update(kind="CANDIDATE", new_start=request["new_start"], candidate_name=request["candidate_name"])
    return _validate(_seal(doc), "CANDIDATE")


def _original_baseline(doc):
    result = deepcopy(doc)
    result.update(kind="BASELINE", new_start=doc["current_start"], candidate_name="Original")
    return _validate(_seal(result), "BASELINE")


def validate_candidate(document, request):
    doc = _validate(document, "CANDIDATE")
    need(_same(candidate(_original_baseline(doc), request), doc), "Focus candidate differs from exact request")
    return doc


def _source_matches(before, doc):
    rebuilt = _baseline_from_state(before, doc["source_sha256"], doc["scene"], doc["shot"], doc["helper"],
                                   doc["locked_frames"], doc["base_bag"])
    need(_same(rebuilt, _original_baseline(doc)), "Focus source identities/bag/context/optics differ")


def expected(before, document):
    """Precompute exactly 18 source-derived scalar changes in the two Action witnesses."""
    doc = _validate(document, "CANDIDATE")
    _source_matches(before, doc)
    out = deepcopy(before)
    target = _moved_bag(doc["base_bag"], doc["locked_frames"], doc["new_start"])
    action = doc["action"]
    strict = out["strict_rig_scene"]["actions"][action]["curves"]
    compact = motion._compact_bag(out["protected"]["actions"][action])["curves"]
    for index in range(3):
        for curves in (strict, compact):
            need(curves[index]["path"] == "location" and curves[index]["index"] == index,
                 "Focus repeated curve ordering differs")
            key, selected = curves[index]["keys"][1], target[index]["keys"][1]
            key["co"][0] = selected["co"][0]
            key["left"][0] = selected["handle_left"][0]
            key["right"][0] = selected["handle_right"][0]
    return out


def _selected_baseline(doc):
    result = deepcopy(doc)
    bag = _moved_bag(doc["base_bag"], doc["locked_frames"], doc["new_start"])
    result.update(kind="BASELINE", base_bag=bag, current_start=doc["new_start"], candidate_name="Original")
    result["base_action"]["curves"] = motion._strict_curves(bag)
    motion._compact_bag(result["base_protected_action"])["curves"] = motion._compact_curves(bag)
    return _validate(_seal(result), "BASELINE")


def check_document(bpy, native, document, selected=False):
    need(type(selected) is bool, "Boolean selected flag required")
    doc = _validate(document, "CANDIDATE")
    scene, camera, helper, bag, raw_bag, state = _qualify(
        bpy, native, doc["scene"], doc["shot"], doc["helper"], doc["locked_frames"])
    rebuilt = _baseline_from_state(state, doc["source_sha256"], doc["scene"], doc["shot"], doc["helper"],
                                   doc["locked_frames"], raw_bag)
    need(_same(rebuilt, _selected_baseline(doc) if selected else _original_baseline(doc)),
         "Actual Focus baseline/bag/optics/identity differs")
    return scene, camera


def apply(bpy, native, document):
    doc = _validate(document, "CANDIDATE")
    scene, _ = check_document(bpy, native, doc)
    before = cut_ops._wire(native.state(bpy, scene))
    wanted = expected(before, doc)
    target = _moved_bag(doc["base_bag"], doc["locked_frames"], doc["new_start"])
    helper = scene.objects[doc["helper"]]
    ad = helper.animation_data
    bag = ad.action.layers[0].strips[0].channelbag(ad.action_slot)
    for index in range(3):
        curve = bag.fcurves.find("location", index=index)
        key, selected = curve.keyframe_points[1], target[index]["keys"][1]
        key.co.x = selected["co"][0]
        key.handle_left.x = selected["handle_left"][0]
        key.handle_right.x = selected["handle_right"][0]
        curve.update()
    need(_same(cut_ops._wire(native.state(bpy, scene)), wanted), "Undeclared in-place Focus delta")
    check_document(bpy, native, doc, selected=True)
    return scene


def projection(bpy, native, document, selected=False):
    scene, camera = check_document(bpy, native, document, selected=selected)
    doc = _validate(document, "CANDIDATE")
    return {"camera": camera.name, "camera_data": camera.data.name, "helper": doc["helper"],
            "action": doc["action"], "slot_handle": doc["slot_handle"],
            "locked_frames": deepcopy(doc["locked_frames"]),
            "onset": doc["new_start"] if selected else doc["current_start"],
            "bag": (_moved_bag(doc["base_bag"], doc["locked_frames"], doc["new_start"])
                    if selected else deepcopy(doc["base_bag"])),
            "native_camera": native.projection(camera, scene)}


def verify_next(base, document, state, output_sha):
    """Pure independent receipt verification, without ambient Live registration."""
    doc, reopened = _validate(document, "CANDIDATE"), _validate(base, "BASELINE")
    _sha(output_sha)
    need(type(state) is dict and set(state) == {"raw", "primed", "expected_raw", "expected_primed"},
         "Complete Focus state receipt required")
    for source, target in (("raw", "expected_raw"), ("primed", "expected_primed")):
        need(_same(expected(state[source], doc), state[target]),
             "Sealed Focus expectation differs from exact source-derived delta")
    bag = _moved_bag(doc["base_bag"], doc["locked_frames"], doc["new_start"])
    wanted = _baseline_from_state(state["expected_primed"], output_sha, doc["scene"], doc["shot"],
                                  doc["helper"], doc["locked_frames"], bag)
    need(_same(reopened, wanted), "Reopened Focus source/bag/protection differs")
    return True
