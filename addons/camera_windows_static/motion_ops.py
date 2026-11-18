"""One existing two-key camera move; no new path, focus or persistence engine.

The caller owns source-byte guards, raw/primed witnesses, saving and cold opens.
The unchanged frozen profile supplies float32 handle mathematics and the special
camera-table ownership check. A LINEAR *dictionary copy* is a mathematics input
only: this module never linearizes the real source and does not claim that a
BEZIER source passed the old LINEAR-only production qualification.
"""
from copy import deepcopy
import hashlib
import importlib
import math
import re

try:
    from . import cut_ops, motion_profile_frozen as profile
except ImportError:
    import cut_ops
    import motion_profile_frozen as profile


SCHEMA = "camera-existing-two-key-motion-candidate/1"
SCOPE = "Existing exclusive XYZ two-key preset timing only; no path, Action copy or Focus edit"
EASINGS = ("EASE_IN_OUT", "EASE_IN", "EASE_OUT")
REQUEST_KEYS = {"version", "source", "scene", "shot", "easing", "candidate_name", "session", "baseline"}
KEYS = {"schema", "scope", "kind", "source_sha256", "scene", "source_mode", "catalog", "base_rows",
        "shot", "camera", "camera_data", "action", "slot_handle", "slot_identifier", "base_bag",
        "base_action", "base_protected_action", "base_binding", "base_pose", "source_info", "identity",
        "optical_witness", "interval", "source_easing", "easing", "allowed_changes", "candidate_name",
        "content_sha256"}


def need(ok, message):
    if not ok:
        raise ValueError(message)


class _Reject:
    @staticmethod
    def fail(code, message):
        raise ValueError(code + ": " + message)


def _canonical(value):
    return profile.canonical(value).encode("utf-8")


def _same(a, b):
    return _canonical(a) == _canonical(b)


def _seal(doc):
    doc["content_sha256"] = hashlib.sha256(_canonical(
        {k: v for k, v in doc.items() if k != "content_sha256"})).hexdigest()
    return doc


def _sha(value):
    need(type(value) is str and re.fullmatch("[0-9a-f]{64}", value) is not None, "SHA256 required")


def _name(value):
    need(type(value) is str and bool(value) and value == value.strip() and "\0" not in value,
         "Exact nonempty name required")


def _linear_math(bag):
    """Pure copied witness, never an RNA write or a legacy eligibility assertion."""
    result = deepcopy(bag)
    need(type(result) is list and len(result) == 3, "Exactly three XYZ curves required")
    for curve in result:
        need(type(curve) is dict and type(curve.get("keys")) is list, "Complete curve witness required")
        for key in curve["keys"]:
            need(type(key) is dict, "Complete key witness required")
            key["interpolation"] = "LINEAR"
    return result


def _recognize(bag):
    """Accept only real LINEAR/FREE or exact frozen BEZIER/FREE presets."""
    math_input = _linear_math(bag)
    interval = profile.interval(math_input, _Reject)
    need(all(c["properties"].get("lock") is False for c in bag), "Locked curves unsupported")
    styles = {key["interpolation"] for curve in bag for key in curve["keys"]}
    if styles == {"LINEAR"}:
        return interval, "LINEAR"
    need(styles == {"BEZIER"}, "Uniform LINEAR or preset BEZIER interpolation required")
    matches = [e for e in EASINGS if _same(bag, profile.expected_bag(math_input, _Reject, e))]
    need(len(matches) == 1, "BEZIER source differs from exact frozen presets")
    return interval, matches[0]


def _selected_bag(doc):
    return profile.expected_bag(_linear_math(doc["base_bag"]), _Reject, doc["easing"])


def _strict_curves(bag):
    """Map the full RNA bag into the existing strict witness, checking duplicates."""
    result = []
    for curve in bag:
        need(set(curve) == {"data_path", "array_index", "properties", "group", "keys",
                            "modifiers", "sampled_points"}, "Exact native curve fields required")
        keys = []
        for key in curve["keys"]:
            props = deepcopy(key)
            required = {"co", "handle_left", "handle_right", "handle_left_type", "handle_right_type",
                        "interpolation"}
            need(required <= set(props), "Complete native key fields required")
            for field in required:
                props.pop(field)
            # co_ui is a duplicate coordinate in this Blender RNA; never ignore a disagreement.
            if "co_ui" in props:
                need(_same(props.pop("co_ui"), key["co"]), "Native co/co_ui witnesses differ")
            keys.append({"co": deepcopy(key["co"]), "left": deepcopy(key["handle_left"]),
                         "right": deepcopy(key["handle_right"]), "left_type": key["handle_left_type"],
                         "right_type": key["handle_right_type"], "interpolation": key["interpolation"],
                         "properties": props})
        result.append({"path": curve["data_path"], "index": curve["array_index"],
                       "extrapolation": curve["properties"]["extrapolation"], "keys": keys,
                       "properties": deepcopy(curve["properties"]), "group": curve["group"],
                       "modifiers": deepcopy(curve["modifiers"]),
                       "sampled_points": deepcopy(curve["sampled_points"])})
    return result


def _compact_curves(bag):
    result = []
    for curve in _strict_curves(bag):
        result.append({"path": curve["path"], "index": curve["index"],
                       "extrapolation": curve["extrapolation"],
                       "keys": [{k: deepcopy(v) for k, v in key.items() if k != "properties"}
                                for key in curve["keys"]]})
    return result


def _compact_bag(action):
    need(type(action) is dict and set(action) == {"slots", "layers"}, "Exact protected Action required")
    need(len(action["slots"]) == len(action["layers"]) == 1, "Single protected slot/layer required")
    strips = action["layers"][0]["strips"]
    need(len(strips) == 1 and strips[0]["type"] == "KEYFRAME" and len(strips[0]["bags"]) == 1,
         "Single protected KEYFRAME bag required")
    return strips[0]["bags"][0]


def _info(state):
    return {key: deepcopy(state["protected"][key]) for key in ("range", "time", "render")}


def _outside(info, interval):
    time = info["time"]
    need(type(time) is list and len(time) == 2 and type(time[0]) is int
         and type(time[1]) in (int, float) and math.isfinite(time[1]) and 0 <= time[1] < 1,
         "Exact saved frame/subframe required")
    t = time[0] + time[1]
    need(t <= interval[0] or t >= interval[1], "Save source at/outside Motion endpoints first")


def _identity(state, camera, data, action):
    strict = state["strict_rig_scene"]
    keys = ("Object:" + camera, "Camera:" + data, "Action:" + action)
    return {key: {"id": deepcopy(strict["ids"][key]),
                  "references": deepcopy(strict["references"][key])} for key in keys}


def _optics(state):
    return {"camera_optics": deepcopy(state["camera_optics"]),
            "strict_cameras": deepcopy(state["strict_rig_scene"]["cameras"]),
            "protected_camera_data": deepcopy(state["protected"]["camera_data"])}


def _allowed(action):
    return {"action": action, "representations": ["protected.actions", "strict_rig_scene.actions"],
            "curves": [{"data_path": "location", "array_index": i,
                        "first_key": ["interpolation", "handle_right"],
                        "last_key": ["interpolation", "handle_left"]} for i in range(3)]}


def _table(doc):
    need(doc["source_mode"] == "SEQUENCE", "Motion requires sequence source")
    rows, catalog = doc["base_rows"], doc["catalog"]
    need(type(catalog) is list and bool(catalog), "Camera catalog required")
    for name in catalog:
        _name(name)
    need(catalog == sorted(set(catalog)), "Sorted unique camera catalog required")
    need(type(rows) is list and 1 <= len(rows) <= 100, "Bounded shot table required")
    names, previous = set(), None
    for row in rows:
        need(type(row) is dict and set(row) == {"name", "camera", "first", "last"}, "Exact shot row required")
        _name(row["name"])
        _name(row["camera"])
        need(row["name"] not in names and row["camera"] in catalog, "Shot identity/catalog differs")
        need(type(row["first"]) is int and type(row["last"]) is int
             and -1048574 <= row["first"] <= row["last"] <= 1048574, "Bounded shot interval required")
        need(previous is None or previous + 1 == row["first"], "Contiguous shot table required")
        previous = row["last"]
        names.add(row["name"])
    chosen = [row for row in rows if row["name"] == doc["shot"]]
    need(len(chosen) == 1 and chosen[0]["camera"] == doc["camera"]
         and sum(row["camera"] == doc["camera"] for row in rows) == 1,
         "Unique named shot camera required")
    return rows


def _validate(document, kind=None):
    need(type(document) is dict and set(document) == KEYS, "Exact Motion document required")
    doc = deepcopy(document)
    need(doc["schema"] == SCHEMA and doc["scope"] == SCOPE, "Motion schema/scope differs")
    need(doc["kind"] in ("BASELINE", "CANDIDATE") and (kind is None or kind == doc["kind"]),
         "Motion document kind differs")
    _sha(doc["source_sha256"])
    for field in ("scene", "shot", "camera", "camera_data", "action", "slot_identifier", "candidate_name"):
        _name(doc[field])
    need(type(doc["slot_handle"]) is int, "Actual integer Action slot required")
    _table(doc)
    interval, source_easing = _recognize(doc["base_bag"])
    need(_same(doc["interval"], interval) and doc["source_easing"] == source_easing,
         "Source Motion interval/profile differs")
    need(type(doc["source_info"]) is dict and set(doc["source_info"]) == {"range", "time", "render"},
         "Complete source context required")
    _outside(doc["source_info"], interval)
    need(type(doc["base_pose"]) is dict and type(doc["base_binding"]) is dict,
         "Full source camera pose/binding required")
    binding = doc["base_binding"]
    need(binding["action"] == doc["action"] and binding["slot"] == doc["slot_identifier"]
         and binding["slot_handle"] == doc["slot_handle"], "Source Action/slot binding differs")
    action = doc["base_action"]
    need(type(action) is dict and _same(action["curves"], _strict_curves(doc["base_bag"])),
         "Strict Action/full native bag differs")
    need(len(action["slots"]) == 1 and action["slots"][0]["identifier"] == doc["slot_identifier"]
         and action["slots"][0]["properties"]["handle"] == doc["slot_handle"]
         and action["slots"][0]["properties"]["target_id_type"] == "OBJECT"
         and action["bag"]["slot_handle"] == doc["slot_handle"], "Strict slot/bag identity differs")
    compact = doc["base_protected_action"]
    compact_bag = _compact_bag(compact)
    need(compact["slots"] == [[doc["slot_identifier"], doc["slot_handle"], "OBJECT"]]
         and compact_bag["slot"] == doc["slot_handle"]
         and _same(compact_bag["curves"], _compact_curves(doc["base_bag"])),
         "Protected Action/native bag differs")
    keys = {"Object:" + doc["camera"], "Camera:" + doc["camera_data"], "Action:" + doc["action"]}
    need(type(doc["identity"]) is dict and set(doc["identity"]) == keys, "Complete target ID witnesses required")
    for key, count in (("Object:" + doc["camera"], 2), ("Camera:" + doc["camera_data"], 1),
                       ("Action:" + doc["action"], 1)):
        record = doc["identity"][key]
        need(type(record) is dict and set(record) == {"id", "references"}, "Exact ID/reference record required")
        ident = record["id"]
        need(type(ident["users"]) is int and ident["users"] == count and ident["use_fake_user"] is False
             and ident["use_extra_user"] is False, "Exclusive target ID users required")
    need(type(doc["optical_witness"]) is dict
         and set(doc["optical_witness"]) == {"camera_optics", "strict_cameras", "protected_camera_data"},
         "All optical witnesses required")
    need(_same(doc["allowed_changes"], _allowed(doc["action"])), "Motion allowed-change domain differs")
    if doc["kind"] == "BASELINE":
        need(doc["easing"] == source_easing and doc["candidate_name"] == "Original", "Motion baseline differs")
    else:
        need(type(doc["easing"]) is str and doc["easing"] in EASINGS, "Explicit supported Motion easing required")
        need(not _same(_selected_bag(doc), doc["base_bag"]), "Motion candidate makes no change")
    _sha(doc["content_sha256"])
    need(_seal(deepcopy(doc))["content_sha256"] == doc["content_sha256"], "Motion content seal differs")
    return doc


def _baseline_from_state(state, source_sha, scene_name, shot, camera, bag):
    """Pure expected baseline construction; no bpy import or after-state adoption."""
    # These frozen pure contracts must also work in the independent Python
    # result reader. Do not rely on Blender's live-addon module registration.
    if __package__:
        from ._vendor.camera_placement_copy import rig_contract, table_model
    else:
        from _vendor.camera_placement_copy import rig_contract, table_model
    rows, catalog = cut_ops._rows_contract(state, scene_name,
                                         rig_contract=rig_contract, model=table_model)
    strict = state["strict_rig_scene"]
    obj = strict["objects"][camera]
    data, binding = obj["data"]["name"], obj["binding"]
    action = binding["action"]
    interval, easing = _recognize(bag)
    doc = {"schema": SCHEMA, "scope": SCOPE, "kind": "BASELINE", "source_sha256": source_sha,
           "scene": scene_name, "source_mode": "SEQUENCE", "catalog": deepcopy(catalog),
           "base_rows": deepcopy(rows), "shot": shot, "camera": camera, "camera_data": data,
           "action": action, "slot_handle": binding["slot_handle"], "slot_identifier": binding["slot"],
           "base_bag": deepcopy(bag), "base_action": deepcopy(strict["actions"][action]),
           "base_protected_action": deepcopy(state["protected"]["actions"][action]),
           "base_binding": deepcopy(binding), "base_pose": deepcopy(state["object_transforms"][camera]),
           "source_info": _info(state), "identity": _identity(state, camera, data, action),
           "optical_witness": _optics(state), "interval": interval, "source_easing": easing,
           "easing": easing, "allowed_changes": _allowed(action), "candidate_name": "Original"}
    need(state["protected"]["objects"][camera]["action"] == action,
         "Protected camera binding differs")
    return _validate(_seal(doc), "BASELINE")


def _effective_users(item):
    return int(item.users) - int(bool(item.use_fake_user))


def _qualify(bpy, native, scene_name, shot):
    """Read native identities and the complete existing technical-scene contract."""
    scene, state, rows, catalog = cut_ops._scene(bpy, native, scene_name)
    chosen = [row for row in rows if row["name"] == shot]
    need(len(chosen) == 1, "Exactly one named Motion shot required")
    camera = scene.objects.get(chosen[0]["camera"])
    need(camera is not None and camera.type == "CAMERA" and camera.data.type == "PERSP"
         and camera.parent is None and not camera.constraints and not camera.modifiers,
         "Existing parentless unconstrained perspective camera required")
    need(camera.data.animation_data is None, "Animated optics unsupported")
    need([obj for obj in bpy.data.objects if obj.type == "CAMERA" and obj.data == camera.data] == [camera]
         and camera.data.users == 1 and not camera.data.use_fake_user and not camera.data.use_extra_user,
         "Exclusive Camera data required")
    profile.qualify_table_owner(camera, scene, bpy, _effective_users)
    ad = camera.animation_data
    need(ad is not None and ad.action is not None and not ad.drivers and not ad.nla_tracks
         and not ad.use_tweak_mode and ad.action_blend_type == "REPLACE" and ad.action_influence == 1.0,
         "Exclusive full-influence active Action without drivers/NLA required")
    action, slot = ad.action, ad.action_slot
    need(not action.library and not action.override_library and action.users == 1
         and not action.use_fake_user and not action.use_extra_user
         and set(bpy.data.user_map(subset={action}).get(action, set())) == {camera},
         "Actual exclusive Action consumer required")
    need(len(action.slots) == 1 and slot is not None and slot == action.slots[0]
         and slot.target_id_type == "OBJECT" and len(action.layers) == 1
         and len(action.layers[0].strips) == 1, "One active OBJECT slot/layer/strip required")
    layer = action.layers[0]
    need(not getattr(layer, "mute", False) and getattr(layer, "influence", 1.0) == 1.0,
         "Unmuted full-influence Action layer required")
    strip = layer.strips[0]
    need(strip.type == "KEYFRAME" and len(strip.channelbags) == 1,
         "One actual KEYFRAME channelbag required")
    bag = strip.channelbag(slot)
    need(bag is not None and bag == strip.channelbags[0] and bag.slot_handle == slot.handle,
         "Actual Action slot/bag identity differs")
    # Witness primitives are already part of the frozen placement package.
    import importlib
    shared = importlib.import_module(native.__package__ + ".rig_witness")
    raw_bag = cut_ops._wire([shared.curve_state(c) for c in sorted(
        bag.fcurves, key=lambda c: (c.data_path, c.array_index))])
    interval, _ = _recognize(raw_bag)
    _outside(_info(state), interval)
    need(state["strict_rig_scene"]["objects"][camera.name]["binding"]["action"] == action.name
         and state["strict_rig_scene"]["objects"][camera.name]["binding"]["slot_handle"] == slot.handle,
         "Native Action/slot differs from source witness")
    return scene, camera, bag, raw_bag, state


def baseline(bpy, native, source_sha, scene_name, shot):
    _sha(source_sha)
    _, camera, _, bag, state = _qualify(bpy, native, scene_name, shot)
    return _baseline_from_state(state, source_sha, scene_name, shot, camera.name, bag)


def candidate(base, request):
    doc = _validate(base, "BASELINE")
    need(type(request) is dict and set(request) == REQUEST_KEYS and type(request["version"]) is int
         and request["version"] == 4, "Exact Motion version4 request required")
    need(type(request["source"]) is dict and set(request["source"]) == {"file", "sha256"}
         and type(request["source"]["file"]) is str and bool(request["source"]["file"])
         and request["source"]["sha256"] == doc["source_sha256"]
         and request["scene"] == doc["scene"] and request["shot"] == doc["shot"],
         "Motion request source/shot differs")
    doc.update(kind="CANDIDATE", easing=request["easing"], candidate_name=request["candidate_name"])
    return _validate(_seal(doc), "CANDIDATE")


def validate_candidate(document, request):
    doc = _validate(document, "CANDIDATE")
    original = deepcopy(doc)
    original.update(kind="BASELINE", easing=doc["source_easing"], candidate_name="Original")
    base = _validate(_seal(original), "BASELINE")
    need(_same(candidate(base, request), doc), "Motion candidate differs from exact request")
    return doc


def _source_matches(before, doc):
    rebuilt = _baseline_from_state(before, doc["source_sha256"], doc["scene"], doc["shot"],
                                   doc["camera"], doc["base_bag"])
    original = deepcopy(doc)
    original.update(kind="BASELINE", easing=doc["source_easing"], candidate_name="Original")
    need(_same(rebuilt, _seal(original)), "Motion source identities/bag/context/optics differ")


def expected(before, document):
    """Derive all permitted repeated fields from sealed before/source, never after."""
    doc = _validate(document, "CANDIDATE")
    _source_matches(before, doc)
    out, target = deepcopy(before), _selected_bag(doc)
    action = doc["action"]
    strict_keys = out["strict_rig_scene"]["actions"][action]["curves"]
    protected_keys = _compact_bag(out["protected"]["actions"][action])["curves"]
    for index, curve in enumerate(target):
        for curves in (strict_keys, protected_keys):
            need(curves[index]["path"] == "location" and curves[index]["index"] == index,
                 "Expected Action curve ordering differs")
            for i in (0, 1):
                curves[index]["keys"][i]["interpolation"] = curve["keys"][i]["interpolation"]
            curves[index]["keys"][0]["right"] = deepcopy(curve["keys"][0]["handle_right"])
            curves[index]["keys"][1]["left"] = deepcopy(curve["keys"][1]["handle_left"])
    return out


def check_document(bpy, native, document, selected=False):
    need(type(selected) is bool, "Boolean selected flag required")
    doc = _validate(document, "CANDIDATE")
    scene, camera, bag, raw_bag, state = _qualify(bpy, native, doc["scene"], doc["shot"])
    wanted_bag = _selected_bag(doc) if selected else doc["base_bag"]
    need(camera.name == doc["camera"] and camera.data.name == doc["camera_data"]
         and _same(raw_bag, wanted_bag), "Actual Motion target/bag differs")
    if selected:
        # Reconstruct the expected selected baseline solely from the original
        # declared source fields. The caller separately checks full-state equality.
        need(_same(state["strict_rig_scene"]["objects"][camera.name]["binding"], doc["base_binding"])
             and _same(_identity(state, doc["camera"], doc["camera_data"], doc["action"]), doc["identity"])
             and _same(_info(state), doc["source_info"]) and _same(_optics(state), doc["optical_witness"])
             and _same(state["object_transforms"][camera.name], doc["base_pose"]),
             "Selected Motion identity/context/optics/pose differs")
        rows, catalog = cut_ops._rows_contract(state, doc["scene"])
        need(_same(rows, doc["base_rows"]) and _same(catalog, doc["catalog"]), "Selected Motion table differs")
        action_record = deepcopy(doc["base_action"])
        compact_record = deepcopy(doc["base_protected_action"])
        action_record["curves"] = _strict_curves(wanted_bag)
        _compact_bag(compact_record)["curves"] = _compact_curves(wanted_bag)
        need(_same(state["strict_rig_scene"]["actions"][doc["action"]], action_record)
             and _same(state["protected"]["actions"][doc["action"]], compact_record),
             "Selected complete Action witnesses differ")
    else:
        _source_matches(state, doc)
    return scene, camera


def apply(bpy, native, document):
    doc = _validate(document, "CANDIDATE")
    scene, camera = check_document(bpy, native, doc)
    before = cut_ops._wire(native.state(bpy, scene))
    wanted = expected(before, doc)
    target = _selected_bag(doc)
    ad = camera.animation_data
    bag = ad.action.layers[0].strips[0].channelbag(ad.action_slot)
    for index in range(3):
        curve = bag.fcurves.find("location", index=index)
        for i in (0, 1):
            if curve.keyframe_points[i].interpolation != target[index]["keys"][i]["interpolation"]:
                curve.keyframe_points[i].interpolation = target[index]["keys"][i]["interpolation"]
        curve.keyframe_points[0].handle_right = target[index]["keys"][0]["handle_right"]
        curve.keyframe_points[1].handle_left = target[index]["keys"][1]["handle_left"]
        curve.update()
    need(_same(cut_ops._wire(native.state(bpy, scene)), wanted), "Undeclared Motion delta")
    check_document(bpy, native, doc, selected=True)
    return scene


def projection(bpy, native, document, selected=False):
    scene, camera = check_document(bpy, native, document, selected=selected)
    doc = _validate(document, "CANDIDATE")
    return {"camera": camera.name, "camera_data": camera.data.name, "action": doc["action"],
            "slot_handle": doc["slot_handle"], "interval": deepcopy(doc["interval"]),
            "bag": deepcopy(_selected_bag(doc) if selected else doc["base_bag"]),
            "native_camera": native.projection(camera, scene)}


def verify_next(base, document, state, output_sha):
    """Pure cold-receipt check; no importing bpy or silently trusting expected_*.

    The worker must have independently compared both cold raw/primed states to
    the sealed expected values before submitting its freshly captured baseline.
    """
    doc, reopened = _validate(document, "CANDIDATE"), _validate(base, "BASELINE")
    _sha(output_sha)
    need(type(state) is dict and set(state) == {"raw", "primed", "expected_raw", "expected_primed"},
         "Complete Motion state receipt required")
    for source, target in (("raw", "expected_raw"), ("primed", "expected_primed")):
        need(_same(expected(state[source], doc), state[target]),
             "Sealed Motion expectation differs from source-derived delta")
    wanted = _baseline_from_state(state["expected_primed"], output_sha, doc["scene"], doc["shot"],
                                  doc["camera"], _selected_bag(doc))
    need(_same(reopened, wanted), "Reopened complete Motion source/bag/protection differs")
    return True
