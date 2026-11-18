"""Bounded static DOF on an existing rig bone; no helper/Action/Focus retiming.

The caller owns saved-source SHA binding, priming, persistence and cold opens.
No bpy import or platform/persistence implementation is introduced here.
"""
from copy import deepcopy
import hashlib
import json
import math
import re
import struct

try:
    from . import cut_ops
except ImportError:
    import cut_ops


SCHEMA = "camera-static-bone-dof-candidate/1"
SCOPE = "Static DOF only; no Focus timing, helper creation or Action editing qualification"
# Windows5.2.1 probe focus-probe-v002: a bone-focus pointer adds its exact reverse
# reference but changes no ID users count. Full-state equality remains required.
FOCUS_USER_DELTA = 0
REQUEST_KEYS = {"version", "source", "scene", "shot", "focus_object", "focus_subtarget",
                "fstop", "candidate_name", "session", "baseline"}
KEYS = {"schema", "scope", "kind", "source_sha256", "scene", "source_mode", "catalog", "base_rows",
        "shot", "camera", "camera_data", "base_optics", "base_strict_dof", "base_pose",
        "source_info", "focus_catalog", "fstop_range", "use_dof", "focus_object", "focus_subtarget",
        "fstop", "candidate_name", "content_sha256"}


def need(ok, message):
    if not ok:
        raise ValueError(message)


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _seal(doc):
    doc["content_sha256"] = hashlib.sha256(_canonical({k: v for k, v in doc.items()
                                                     if k != "content_sha256"})).hexdigest()
    return doc


def _sha(value):
    need(type(value) is str and re.fullmatch("[0-9a-f]{64}", value) is not None, "SHA256 required")


def _name(value):
    need(type(value) is str and bool(value) and value.strip() == value and "\0" not in value,
         "Exact nonempty name required")


def _f32(value):
    need(type(value) in (int, float) and math.isfinite(value) and value > 0, "Positive finite f-stop required")
    try:
        result = struct.unpack("<f", struct.pack("<f", value))[0]
    except (OverflowError, struct.error) as exc:
        raise ValueError("f-stop outside float32 range") from exc
    need(math.isfinite(result) and result > 0, "Positive finite float32 f-stop required")
    return result


def _table(doc):
    """Pure subset of the frozen Live table schema; no addon imports or RNA."""
    need(doc["source_mode"] == "SEQUENCE", "Static DOF requires sequence source")
    catalog, rows = doc["catalog"], doc["base_rows"]
    need(type(catalog) is list and bool(catalog), "Nonempty camera catalog required")
    for name in catalog:
        _name(name)
    need(catalog == sorted(set(catalog)), "Sorted unique camera catalog required")
    need(type(rows) is list and 1 <= len(rows) <= 100, "Bounded shot sequence required")
    names, previous = set(), None
    for row in rows:
        need(type(row) is dict and set(row) == {"name", "camera", "first", "last"}, "Exact shot row required")
        _name(row["name"])
        _name(row["camera"])
        need(row["name"] not in names and row["camera"] in catalog, "Shot identity/catalog differs")
        first, last = row["first"], row["last"]
        need(type(first) is int and type(last) is int and -1048574 <= first <= last <= 1048574,
             "Bounded integer shot interval required")
        need(previous is None or first == previous + 1, "Contiguous shot sequence required")
        names.add(row["name"])
        previous = last
    return rows


def _rig_catalog(state):
    strict = state["strict_rig_scene"]
    result = {}
    for name, rig in strict["rig_context"]["rigs"].items():
        obj = strict["objects"][name]
        need(obj["type"] == "ARMATURE" and obj["data"] == rig["data"], "Rig focus identity differs")
        bones = rig["bones"]
        pose_bones = rig["pose"]["bones"]
        need(type(bones) is dict and type(pose_bones) is dict and set(bones) == set(pose_bones),
             "Actual armature/pose-bone inventory differs")
        ident = strict["ids"]["Object:" + name]
        need(type(ident["users"]) is int and ident["users"] >= 0, "Object user count required")
        result[name] = {"object": {"type": "Object", "name": name, "library": None},
                        "data": deepcopy(obj["data"]), "bones": sorted(bones),
                        "users": ident["users"], "references": deepcopy(strict["references"]["Object:" + name])}
    need(bool(result), "Existing bounded Armature focus targets required")
    return result


def _info(state):
    return {key: deepcopy(state["protected"][key]) for key in ("range", "time", "render")}


def _dof_consistent(state, camera, data):
    protected = state["protected"]["camera_data"][camera]
    optics = state["camera_optics"][data]
    strict = state["strict_rig_scene"]["cameras"][data]["dof"]
    dof, props = optics["dof"], strict["properties"]
    need(type(dof["use_dof"]) is bool and type(props["use_dof"]) is bool,
         "Boolean DOF witnesses required")
    need(protected["dof"] == dof["use_dof"] == props["use_dof"], "DOF enabled witnesses differ")
    need(protected["fstop"] == dof["aperture_fstop"] == props["aperture_fstop"], "f-stop witnesses differ")
    focus = dof["focus_object"]
    need(protected["focus"] == focus, "Focus name witnesses differ")
    need(strict["focus_object"] == (None if focus is None else
         {"type": "Object", "name": focus, "library": None}), "Strict focus identity differs")
    need(type(props["focus_subtarget"]) is str, "Focus subtarget witness required")
    for field, value in dof.items():
        if field != "focus_object":
            need(field in props and props[field] == value, "DOF duplicate field differs: " + field)
    need(protected["distance"] == dof["focus_distance"], "Focus-distance witnesses differ")
    return optics, strict


def _validate(document, kind=None):
    need(type(document) is dict and set(document) == KEYS, "Exact static DOF document required")
    doc = deepcopy(document)
    need(doc["schema"] == SCHEMA and doc["scope"] == SCOPE, "Static DOF schema/scope differs")
    need(doc["kind"] in ("BASELINE", "CANDIDATE") and (kind is None or doc["kind"] == kind),
         "DOF document kind differs")
    _sha(doc["source_sha256"])
    for field in ("scene", "shot", "camera", "camera_data", "candidate_name"):
        _name(doc[field])
    rows = _table(doc)
    chosen = [row for row in rows if row["name"] == doc["shot"]]
    need(len(chosen) == 1 and chosen[0]["camera"] == doc["camera"], "Shot camera identity differs")
    need(sum(row["camera"] == doc["camera"] for row in rows) == 1,
         "DOF target reused by another shot")
    need(type(doc["use_dof"]) is bool and type(doc["focus_subtarget"]) is str, "DOF field types differ")
    need(doc["fstop"] == _f32(doc["fstop"]), "Canonical float32 f-stop required")
    limits = doc["fstop_range"]
    need(type(limits) is list and len(limits) == 2
         and all(type(v) in (int, float) and math.isfinite(v) for v in limits)
         and limits[0] <= doc["fstop"] <= limits[1], "f-stop exceeds actual RNA range")
    need(type(doc["base_optics"]) is dict and type(doc["base_strict_dof"]) is dict
         and type(doc["base_pose"]) is dict and type(doc["focus_catalog"]) is dict
         and type(doc["source_info"]) is dict, "Complete source witnesses required")
    original = doc["base_optics"]["dof"]
    if doc["kind"] == "BASELINE":
        need(doc["use_dof"] == original["use_dof"] and doc["focus_object"] == original["focus_object"]
             and doc["focus_subtarget"] == doc["base_strict_dof"]["properties"]["focus_subtarget"]
             and doc["fstop"] == original["aperture_fstop"], "Baseline DOF differs from source")
    else:
        need(doc["use_dof"] is True, "Candidate must enable DOF")
        _name(doc["focus_object"])
        _name(doc["focus_subtarget"])
        target = doc["focus_catalog"].get(doc["focus_object"])
        need(type(target) is dict and doc["focus_subtarget"] in target["bones"],
             "Existing Armature pose bone required")
        need(doc["focus_object"] != doc["camera"], "Camera cannot focus on itself")
        need((doc["use_dof"], doc["focus_object"], doc["focus_subtarget"], doc["fstop"])
             != (original["use_dof"], original["focus_object"],
                 doc["base_strict_dof"]["properties"]["focus_subtarget"], original["aperture_fstop"]),
             "DOF candidate makes no change")
    _sha(doc["content_sha256"])
    need(_seal(deepcopy(doc))["content_sha256"] == doc["content_sha256"], "DOF content seal differs")
    return doc


def _qualify(bpy, native, scene_name, shot):
    scene, state, rows, catalog = cut_ops._scene(bpy, native, scene_name)
    chosen = [row for row in rows if row["name"] == shot]
    need(len(chosen) == 1, "Exactly one named shot required")
    camera = scene.objects.get(chosen[0]["camera"])
    need(camera is not None and camera.type == "CAMERA" and camera.data.type == "PERSP",
         "Local perspective camera required")
    need(camera.parent is None and not camera.constraints and not native.has_animation(camera)
         and not native.has_animation(camera.data), "Target camera parent/constraint/animation unsupported")
    owners = [obj for obj in bpy.data.objects if obj.type == "CAMERA" and obj.data == camera.data]
    need(owners == [camera] and camera.data.users == 1, "Exclusive Camera data required")
    need(list(camera.users_scene) == [scene]
         and sum(row["camera"] == camera.name for row in rows) == 1, "Exclusive shot camera required")
    _dof_consistent(state, camera.name, camera.data.name)
    _rig_catalog(state)
    return scene, camera, state, rows, catalog


def baseline(bpy, native, source_sha, scene_name, shot):
    _sha(source_sha)
    _, camera, state, rows, catalog = _qualify(bpy, native, scene_name, shot)
    optics, strict_dof = _dof_consistent(state, camera.name, camera.data.name)
    prop = camera.data.dof.bl_rna.properties["aperture_fstop"]
    need(prop.type == "FLOAT", "Native float f-stop property required")
    doc = {"schema": SCHEMA, "scope": SCOPE, "kind": "BASELINE", "source_sha256": source_sha,
           "scene": scene_name, "source_mode": "SEQUENCE", "catalog": deepcopy(catalog),
           "base_rows": deepcopy(rows), "shot": shot, "camera": camera.name, "camera_data": camera.data.name,
           "base_optics": deepcopy(optics), "base_strict_dof": deepcopy(strict_dof),
           "base_pose": deepcopy(state["object_transforms"][camera.name]), "source_info": _info(state),
           "focus_catalog": _rig_catalog(state), "fstop_range": [prop.hard_min, prop.hard_max],
           "use_dof": optics["dof"]["use_dof"], "focus_object": optics["dof"]["focus_object"],
           "focus_subtarget": strict_dof["properties"]["focus_subtarget"],
           "fstop": optics["dof"]["aperture_fstop"], "candidate_name": "Original"}
    return _validate(_seal(doc), "BASELINE")


def candidate(base, request):
    doc = _validate(base, "BASELINE")
    need(type(request) is dict and set(request) == REQUEST_KEYS
         and type(request["version"]) is int and request["version"] == 3, "Exact DOF request required")
    need(type(request["source"]) is dict and set(request["source"]) == {"file", "sha256"}
         and request["source"]["sha256"] == doc["source_sha256"] and request["scene"] == doc["scene"]
         and request["shot"] == doc["shot"], "DOF request source/shot differs")
    doc.update(kind="CANDIDATE", use_dof=True, focus_object=request["focus_object"],
               focus_subtarget=request["focus_subtarget"], fstop=_f32(request["fstop"]),
               candidate_name=request["candidate_name"])
    return _validate(_seal(doc), "CANDIDATE")


def validate_candidate(document, request):
    """Rebuild the immutable baseline and replay the complete requested DOF change."""
    doc = _validate(document, "CANDIDATE")
    original = deepcopy(doc)
    original.update(kind="BASELINE", use_dof=doc["base_optics"]["dof"]["use_dof"],
                    focus_object=doc["base_optics"]["dof"]["focus_object"],
                    focus_subtarget=doc["base_strict_dof"]["properties"]["focus_subtarget"],
                    fstop=doc["base_optics"]["dof"]["aperture_fstop"], candidate_name="Original")
    base = _validate(_seal(original), "BASELINE")
    need(candidate(base, request) == doc, "DOF candidate operation differs from request")
    return doc


def _selected_optics(doc):
    optics, strict = deepcopy(doc["base_optics"]), deepcopy(doc["base_strict_dof"])
    optics["dof"].update(use_dof=True, focus_object=doc["focus_object"], aperture_fstop=doc["fstop"])
    strict["properties"].update(use_dof=True, focus_subtarget=doc["focus_subtarget"], aperture_fstop=doc["fstop"])
    strict["focus_object"] = {"type": "Object", "name": doc["focus_object"], "library": None}
    return optics, strict


def _references(out, doc):
    need(type(FOCUS_USER_DELTA) is int and FOCUS_USER_DELTA in (0, 1),
         "Focus pointer user-count policy awaits exact native observation")
    strict = out["strict_rig_scene"]
    old, new = doc["base_optics"]["dof"]["focus_object"], doc["focus_object"]
    owner = {"id_key": "Camera:" + doc["camera_data"],
             "identity": {"type": "Camera", "name": doc["camera_data"], "library": None}}
    if old == new:
        need(owner in strict["references"]["Object:" + new], "Existing focus reverse edge missing")
        return
    if old is not None:
        key = "Object:" + old
        need(owner in strict["references"][key], "Old focus reverse edge missing")
        strict["references"][key] = [value for value in strict["references"][key] if value != owner]
        need(strict["ids"][key]["users"] >= FOCUS_USER_DELTA, "Invalid old focus users")
        strict["ids"][key]["users"] -= FOCUS_USER_DELTA
    key = "Object:" + new
    need(key in strict["ids"] and key in strict["references"], "Focus target identity missing")
    refs = strict["references"][key]
    if owner not in refs:
        refs.append(owner)
        refs.sort(key=lambda value: value["id_key"])
        strict["ids"][key]["users"] += FOCUS_USER_DELTA


def expected(before, document):
    doc = _validate(document, "CANDIDATE")
    cut_ops._complete(before, doc["scene"])
    rows, catalog = cut_ops._rows_contract(before, doc["scene"])
    need(rows == doc["base_rows"] and catalog == doc["catalog"], "DOF source table/catalog differs")
    need(_info(before) == doc["source_info"] and _rig_catalog(before) == doc["focus_catalog"],
         "DOF source context/rig target identity differs")
    camera, data = doc["camera"], doc["camera_data"]
    optics, strict = _dof_consistent(before, camera, data)
    need(optics == doc["base_optics"] and strict == doc["base_strict_dof"]
         and before["object_transforms"][camera] == doc["base_pose"], "DOF source camera witnesses differ")
    out = deepcopy(before)
    protected = out["protected"]["camera_data"][camera]
    protected.update(dof=True, focus=doc["focus_object"], fstop=doc["fstop"])
    selected_optics, selected_strict = _selected_optics(doc)
    out["camera_optics"][data] = selected_optics
    out["strict_rig_scene"]["cameras"][data]["dof"] = selected_strict
    _references(out, doc)
    return out


def check_document(bpy, native, document, selected=False):
    need(type(selected) is bool, "Boolean selected flag required")
    doc = _validate(document, "CANDIDATE")
    scene, camera, state, rows, catalog = _qualify(bpy, native, doc["scene"], doc["shot"])
    need(camera.name == doc["camera"] and camera.data.name == doc["camera_data"]
         and rows == doc["base_rows"] and catalog == doc["catalog"], "DOF target identity/table differs")
    need(state["object_transforms"][camera.name] == doc["base_pose"] and _info(state) == doc["source_info"],
         "DOF camera pose/source context differs")
    target = scene.objects.get(doc["focus_object"])
    need(target is not None and target.type == "ARMATURE" and not target.library and not target.override_library
         and target.data is not None and not target.data.library and not target.data.override_library,
         "Existing local Armature focus target required")
    need(target != camera and target.pose is not None and target.pose.bones.get(doc["focus_subtarget"]) is not None,
         "Actual named focus pose bone required")
    wanted = _selected_optics(doc) if selected else (doc["base_optics"], doc["base_strict_dof"])
    need(_dof_consistent(state, camera.name, camera.data.name) == wanted, "Saved DOF state differs")
    return scene, camera


def apply(bpy, native, document):
    doc = _validate(document, "CANDIDATE")
    scene, camera = check_document(bpy, native, doc)
    before = cut_ops._wire(native.state(bpy, scene))
    wanted = expected(before, doc)
    camera.data.dof.use_dof = True
    camera.data.dof.focus_object = scene.objects[doc["focus_object"]]
    camera.data.dof.focus_subtarget = doc["focus_subtarget"]
    camera.data.dof.aperture_fstop = doc["fstop"]
    need(cut_ops._wire(native.state(bpy, scene)) == wanted, "Undeclared static DOF delta")
    check_document(bpy, native, doc, selected=True)
    return scene


def projection(bpy, native, document, selected=False):
    scene, camera = check_document(bpy, native, document, selected=selected)
    value = native.projection(camera, scene)
    dof = cut_ops._wire(native.state(bpy, scene))["camera_optics"][camera.data.name]["dof"]
    value["dof"] = deepcopy(dof)
    value["dof"]["focus_subtarget"] = camera.data.dof.focus_subtarget
    return value


def verify_next(base, document, state, output_sha):
    doc = _validate(document, "CANDIDATE")
    reopened = _validate(base, "BASELINE")
    _sha(output_sha)
    need(type(state) is dict and set(state) == {"raw", "primed", "expected_raw", "expected_primed"},
         "Complete DOF state receipt required")
    need(reopened["source_sha256"] == output_sha, "Reopened DOF source SHA differs")
    for field in ("scene", "source_mode", "catalog", "base_rows", "shot", "camera", "camera_data", "fstop_range"):
        need(reopened[field] == doc[field], "Reopened DOF identity differs: " + field)
    selected_optics, selected_strict = _selected_optics(doc)
    need(reopened["base_optics"] == selected_optics and reopened["base_strict_dof"] == selected_strict,
         "Reopened DOF optics differ")
    for key in ("expected_raw", "expected_primed"):
        after = state[key]
        need(type(after) is dict and set(after) == cut_ops.STATE_KEYS, "Complete sealed DOF output state required")
        need(after["tables"] == {doc["scene"]: {"mode": doc["source_mode"], "rows": doc["base_rows"]}},
             "Sealed DOF output table differs")
        need(_dof_consistent(after, doc["camera"], doc["camera_data"])
             == (selected_optics, selected_strict), "Sealed DOF output optics differ")
        need(after["object_transforms"][doc["camera"]] == doc["base_pose"]
             and _info(after) == doc["source_info"], "Sealed DOF output context differs")
    raw = state["expected_raw"]
    need(reopened["base_pose"] == raw["object_transforms"][doc["camera"]]
         and reopened["source_info"] == _info(raw)
         and reopened["focus_catalog"] == _rig_catalog(raw), "Reopened DOF context/target differs")
    return True
