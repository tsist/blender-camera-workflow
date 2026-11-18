"""One source-bound adjacent cut, preserving the frozen full-state contract.

This module performs no saving, priming, registration, or publication. The caller
binds document.source_sha256 to its guarded source descriptor. Existing camera
animation is observed and retained; static-placement eligibility is not used.
"""
from copy import deepcopy
import json


STATE_KEYS = {"protected", "extras", "main_ids", "tables", "camera_optics",
              "object_transforms", "evaluated_scene_matrices", "strict_rig_scene"}
ROW_KEYS = {"name", "camera", "first", "last"}
CUT_FIELDS = {"left", "right", "left_last", "candidate_name"}
REQUEST_FIELDS = CUT_FIELDS | {"version", "source", "scene", "session", "baseline"}


def need(ok, message):
    if not ok:
        raise ValueError(message)


def _model():
    from camera_live_rebuilt import candidate_model
    return candidate_model


def _wire(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), allow_nan=False)
    need(len(raw.encode("utf-8")) <= 64 * 1024 * 1024, "Cut state exceeds byte limit")
    return json.loads(raw)


def _complete(before, scene, rig_contract=None):
    """Frozen integrity.complete checks, without weakening any required section."""
    if rig_contract is None:
        from camera_placement_copy import rig_contract
    need(type(before) is dict and set(before) == STATE_KEYS, "Exact rig state fields")
    strict = before["strict_rig_scene"]
    rig_contract.complete(strict)
    need(strict["scene"]["name"] == scene and set(before["tables"]) == {scene},
         "One matching scene")
    need(all(type(v.get("embedded")) is bool for v in strict["ids"].values()),
         "ID embedding marker required")
    main = [v for v in strict["ids"].values() if not v["embedded"]]
    need(all(v["type"] == "ShaderNodeTree" for v in strict["ids"].values() if v["embedded"]),
         "Unexpected embedded ID")
    ids = {(v["type"], v["name"]): v for v in main}
    need(len(ids) == len(main), "Duplicate ID")
    roster = before["main_ids"]
    need(all(type(v) is list and len(v) == 4 for v in roster), "Main roster shape")
    need(len({tuple(v) for v in roster}) == len(roster), "Duplicate roster")
    need({(v[1], v[2]) for v in roster} == set(ids), "Main/strict inventory differs")
    need(all(ids[(v[1], v[2])]["use_fake_user"] == v[3] for v in roster), "Fake user differs")
    need(set(strict["references"]) == set(strict["ids"]), "References inventory differs")
    need(set(strict["objects"]) == set(before["object_transforms"])
         == set(before["evaluated_scene_matrices"]) == set(before["protected"]["objects"]),
         "Object inventories differ")
    sections = (("objects", {"Object"}), ("geometry", {"Mesh"}), ("actions", {"Action"}),
                ("cameras", {"Camera"}), ("materials", {"Material"}),
                ("lights", {"AreaLight", "PointLight", "SunLight", "SpotLight"}))
    for section, types in sections:
        need(set(strict[section]) == {name for kind, name in ids if kind in types},
             "Section inventory differs: " + section)
    need(set(before["camera_optics"]) == set(strict["cameras"]), "Camera data inventory differs")
    for name, obj in before["protected"]["objects"].items():
        other = strict["objects"][name]
        need(other["type"] == obj["type"] and (other["data"] or {}).get("name") == obj["data"],
             "Object identity differs")
    arms = {name for name, obj in strict["objects"].items() if obj["type"] == "ARMATURE"}
    need(set(strict["rig_context"]["rigs"]) == arms, "Rig inventory differs")


def _rows_contract(before, scene, rig_contract=None, model=None):
    _complete(before, scene, rig_contract=rig_contract)
    table, strict = before["tables"][scene], before["strict_rig_scene"]
    need(table["mode"] == "SEQUENCE" and strict["tables"]["source"] == "SEQUENCE",
         "Sequence required")
    rows = table["rows"]
    need(type(rows) is list and bool(rows), "Nonempty rows required")
    names = [row["name"] for row in rows]
    need(len(names) == len(set(names)), "Unique named rows required")
    for index, row in enumerate(rows):
        need(type(row) is dict and set(row) == ROW_KEYS, "Exact row fields")
        need(type(row["name"]) is str and type(row["camera"]) is str, "Row names must be strings")
        need(type(row["first"]) is int and type(row["last"]) is int
             and row["first"] <= row["last"], "Nonempty integer interval")
        if index:
            need(rows[index - 1]["last"] + 1 == row["first"], "Continuous rows required")
    props = strict["scene"]["properties"]
    need(type(props["frame_start"]) is int and type(props["frame_end"]) is int,
         "Strict range integers")
    need(rows[0]["first"] == props["frame_start"] and rows[-1]["last"] == props["frame_end"],
         "Whole scene range required")
    need(before["protected"]["range"][:2] == [props["frame_start"], props["frame_end"]],
         "Selected/strict range differs")
    strict_rows = strict["tables"]["rows"]
    need(len(strict_rows) == len(rows), "Strict row count differs")
    for row, other in zip(rows, strict_rows):
        camera = strict["objects"].get(row["camera"])
        need(type(camera) is dict and camera.get("type") == "CAMERA"
             and row["camera"] in before["evaluated_scene_matrices"], "Actual scene camera required")
        data = camera.get("data")
        need(type(data) is dict and set(data) == {"type", "name", "library"}
             and data["type"] == "Camera" and data["library"] is None
             and data["name"] in strict["cameras"], "Actual local Camera data required")
        need(type(other["name"]) is str and type(other["first"]) is int
             and type(other["last"]) is int, "Strict row types")
        need(set(other) == {"name", "camera", "first", "last", "custom"}, "Strict row schema")
        need(other["camera"] == {"type": "Object", "name": row["camera"], "library": None},
             "Camera identity differs")
        need(all(other[k] == row[k] for k in ("name", "first", "last")), "Strict table differs")
        custom = other["custom"]
        need(set(custom) == {"supported", "values"} and custom["supported"] is True,
             "Supported row data required")
        values = custom["values"]
        need(type(values) is dict, "Exact custom mapping required")
        need(type(values.get("name")) is str and type(values.get("first")) is int
             and type(values.get("last")) is int, "Custom row types")
        need(all(values.get(k) == row[k] for k in ("name", "first", "last")), "Stored row fields differ")
        need(values.get("camera") == {"id_type": "Object", "name": row["camera"]}, "Stored camera differs")
    catalog = sorted(name for name, obj in strict["objects"].items() if obj["type"] == "CAMERA")
    (model if model is not None else _model()).export_snapshot("0" * 64, scene, "SEQUENCE", rows, catalog)
    return rows, catalog


def _single(document):
    doc = _model().validate_document(document)
    need(doc["source_mode"] == "SEQUENCE", "Cut requires sequence source")
    ops = doc["operations"]
    need(len(ops) == 1 and ops[0]["op"] == "move_cut", "Exactly one move_cut required")
    op = ops[0]
    names = [row["name"] for row in doc["base_rows"]]
    index = names.index(op["left"])
    need(doc["base_rows"][index]["last"] != op["left_last"], "No change")
    return doc, op, index


def _scene(bpy, native, scene_name):
    from camera_live_rebuilt.adapter import validate_camera_markers
    scene = bpy.data.scenes.get(scene_name)
    need(len(bpy.data.scenes) == 1 and scene is not None and scene == bpy.context.scene,
         "Single loaded active scene required")
    need(bpy.context.mode == "OBJECT" and bpy.context.view_layer.objects.active is not None,
         "OBJECT/active context required")
    native.preservation.reject_unpreserved(bpy)
    need(not native.has_animation(scene), "Scene animation/driver/NLA unsupported")
    validate_camera_markers(scene.timeline_markers)
    for block in native.all_ids(bpy):
        need(not block.library and not block.override_library, "Linked/override data unsupported")
        animation = getattr(block, "animation_data", None)
        need(not animation or not len(animation.drivers), "Drivers unsupported")
    for row in scene.camera_live_shots:
        camera = row.camera
        need(camera is not None and camera in list(scene.objects) and camera.type == "CAMERA"
             and not camera.library and not camera.override_library
             and camera.data is not None and not camera.data.library and not camera.data.override_library,
             "Actual local scene camera required")
    state = _wire(native.state(bpy, scene))
    rows, catalog = _rows_contract(state, scene_name)
    need(catalog == sorted(obj.name for obj in scene.objects if obj.type == "CAMERA"),
         "Actual scene catalog differs")
    return scene, state, rows, catalog


def baseline(bpy, native, source_sha, scene_name, left):
    """Return the complete Live table baseline, anchored at an existing adjacent cut."""
    _, _, rows, catalog = _scene(bpy, native, scene_name)
    names = [row["name"] for row in rows]
    need(left in names and names.index(left) + 1 < len(rows), "Left shot must have a right neighbor")
    return _model().export_snapshot(source_sha, scene_name, "SEQUENCE", rows, catalog)


def candidate(base, request):
    model = _model()
    base = model.validate_document(base)
    need(base["source_mode"] == "SEQUENCE" and base["operations"] == []
         and base["rows"] == base["base_rows"], "Fresh table baseline required")
    need(type(request) is dict and set(request) in (CUT_FIELDS, REQUEST_FIELDS), "Exact cut request fields")
    if set(request) == REQUEST_FIELDS:
        need(type(request["version"]) is int and request["version"] == 2, "Cut request version differs")
        need(type(request["source"]) is dict and set(request["source"]) == {"file", "sha256"}
             and request["source"]["sha256"] == base["source_sha256"]
             and request["scene"] == base["scene"], "Request source/scene differs")
    doc = model.variant(base, request["candidate_name"], [{"op": "move_cut", "left": request["left"],
                        "right": request["right"], "left_last": request["left_last"]}])
    return _single(doc)[0]


def expected(before, document):
    """Compile only six duplicated scalar writes from a complete immutable source."""
    doc, op, index = _single(document)
    rows, catalog = _rows_contract(before, doc["scene"])
    need(doc["catalog"] == catalog and doc["base_rows"] == rows, "Actual catalog/table differs")
    strict_sha = before["strict_rig_scene"].get("source_sha")
    if strict_sha is not None:
        need(strict_sha == doc["source_sha256"], "State source SHA differs")
    names = [row["name"] for row in rows]
    need(names[index] == op["left"] and index + 1 < len(rows)
         and names[index + 1] == op["right"], "Adjacent ordered rows required")
    cut = op["left_last"]
    need(type(cut) is int and rows[index]["first"] <= cut < rows[index + 1]["last"],
         "Cut creates empty row")
    need(cut != rows[index]["last"], "No change")
    out = deepcopy(before)
    for i, field, value in ((index, "last", cut), (index + 1, "first", cut + 1)):
        out["tables"][doc["scene"]]["rows"][i][field] = value
        row = out["strict_rig_scene"]["tables"]["rows"][i]
        row[field] = value
        row["custom"]["values"][field] = value
    need(out["tables"][doc["scene"]]["rows"] == doc["rows"], "Replay differs")
    return out


def check_document(bpy, native, document, selected=False):
    """Read-only validation; return (scene, native shot rows), preserving all cameras."""
    need(type(selected) is bool, "Selected flag must be boolean")
    doc, _, _ = _single(document)
    scene, _, rows, catalog = _scene(bpy, native, doc["scene"])
    need(doc["catalog"] == catalog and rows == doc["rows" if selected else "base_rows"],
         "Saved source mode/catalog/table differs")
    return scene, list(scene.camera_live_shots)


def apply(bpy, native, document):
    """Only the adjacent last/first fields are assigned; never save or change time."""
    doc, op, index = _single(document)
    scene, rows = check_document(bpy, native, doc)
    before = _wire(native.state(bpy, scene))
    wanted = expected(before, doc)
    rows[index].last = op["left_last"]
    rows[index + 1].first = op["left_last"] + 1
    need(_wire(native.state(bpy, scene)) == wanted, "Undeclared state change after cut")
    check_document(bpy, native, doc, selected=True)
    return scene


def projection(bpy, native, scene):
    """Cut-stage observation, not optical projection or visual acceptance."""
    loaded, _, rows, _ = _scene(bpy, native, scene.name)
    need(loaded == scene, "Projection scene differs")
    return {"rows": deepcopy(rows)}


def next_baseline(bpy, native, output_sha, scene_name, left):
    return baseline(bpy, native, output_sha, scene_name, left)
