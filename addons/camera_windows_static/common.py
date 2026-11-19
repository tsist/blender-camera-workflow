"""Bindings shared by the Windows static adapter; the frozen domain core is unchanged."""
import copy
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import sys

if __package__:
    from .runtime_pins import RUNTIME_PINS
else:
    from runtime_pins import RUNTIME_PINS

ROOT = Path(__file__).resolve().parent
HOST = ROOT / "_support" / "blenderctl"
BLENDER_ENV = "CAMERA_WORKFLOW_BLENDER"
LIMIT = 64 * 1024 * 1024

def require(ok, message):
    if not ok:
        raise ValueError(message)


def qualified_runtime():
    """Resolve and verify the selected Blender and its own bundled interpreter."""
    require(os.name == "nt", "The saved-copy transaction requires Windows")
    app = getattr(sys.modules.get("bpy"), "app", None)
    active = getattr(app, "binary_path", "")
    configured = os.environ.get(BLENDER_ENV, "")
    require(bool(active or configured), f"Set {BLENDER_ENV} to a qualified Blender executable")
    binary = clean(Path(active or configured))
    if active and configured:
        require(clean(Path(configured)).resolve() == binary.resolve(), "Configured Blender differs from the active application")
    fingerprint = digest(binary)
    version = next((version for version, pins in RUNTIME_PINS.items() if pins["blender"] == fingerprint), None)
    require(version is not None, "An exact qualified Windows Blender distribution is required")
    pins = RUNTIME_PINS[version]
    if app is not None:
        require(tuple(app.version) == tuple(map(int, version.split(".")))
                and app.build_hash == pins["build"].encode("ascii"), "Blender build differs")
    python = clean(binary.parent / version.rsplit(".", 1)[0] / "python/bin/python.exe")
    require(digest(python) == pins["python"], "Bundled Python identity differs")
    if app is None:
        require(clean(Path(sys.executable)).resolve() == python.resolve(), "Use the selected Blender's bundled Python")
    return version, binary, python

def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")

def canonical_state(value):
    raw = canonical(value)
    require(len(raw) <= LIMIT, "State report exceeds 64 MiB")
    return parse(raw)

def parse(raw):
    require(type(raw) is bytes and len(raw) <= LIMIT, "Bounded JSON bytes required")
    def pairs(items):
        out = {}
        for key, value in items:
            require(key not in out, "Duplicate JSON key")
            out[key] = value
        return out
    def constant(value):
        raise ValueError("Nonfinite JSON: " + value)
    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    def check(v, depth=0):
        require(depth <= 40, "JSON depth budget")
        if isinstance(v, dict):
            for item in v.values(): check(item, depth + 1)
        elif isinstance(v, list):
            for item in v: check(item, depth + 1)
        elif isinstance(v, float): require(math.isfinite(v), "Nonfinite JSON")
    check(value)
    return value

def clean(path, directory=False):
    p = Path(path)
    require(p.is_absolute() and ".." not in p.parts, "Absolute non-traversing path required")
    for part in (p, *p.parents):
        require(not part.is_symlink() and not part.is_junction(), "Reparse input refused: " + str(part))
    require(p.is_dir() if directory else p.is_file(), "Wrong input type: " + str(p))
    if not directory: require(p.stat().st_nlink == 1, "Aliased input refused")
    return p

def digest(path):
    with clean(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()

def read_json(path, limit=LIMIT):
    p = clean(path)
    require(p.stat().st_size <= limit, "Input exceeds byte limit")
    with p.open("rb") as f: raw = f.read(limit + 1)
    require(len(raw) <= limit, "Input grew beyond limit")
    return parse(raw)

def write_new(path, value):
    p = Path(path)
    clean(p.parent, True)
    raw = canonical(value) + b"\n"
    require(len(raw) <= LIMIT, "Output JSON exceeds byte limit")
    with p.open("xb") as f:
        require(f.write(raw) == len(raw), "Short JSON write")
        f.flush()
        os.fsync(f.fileno())
    require(digest(p) == hashlib.sha256(raw).hexdigest(), "JSON readback changed")
    return descriptor(p)

def descriptor(path):
    p = clean(path)
    return {"file": str(p), "sha256": digest(p)}

def load_descriptor(doc):
    require(type(doc) is dict and set(doc) == {"file", "sha256"}, "Exact file descriptor required")
    require(type(doc["sha256"]) is str and len(doc["sha256"]) == 64, "SHA256 required")
    p = clean(doc["file"])
    require(digest(p) == doc["sha256"], "Descriptor content changed: " + str(p))
    return read_json(p)

def load_host():
    require(os.name == "nt", "This adapter requires Windows")
    if str(HOST) not in sys.path: sys.path.insert(0, str(HOST))
    modules = [importlib.import_module(name) for name in ("filesystem", "processes", "protocol")]
    for module in modules:
        require(Path(module.__file__).resolve().parent == HOST.resolve(), "Foreign Windows host module")
    return modules[0], modules[1]

def verify_package(expected_manifest_sha=None):
    manifest_path = ROOT / "CODE-MANIFEST.json"
    actual = digest(manifest_path)
    if expected_manifest_sha is not None: require(actual == expected_manifest_sha, "Adapter code manifest changed")
    doc = read_json(manifest_path)
    require(set(doc) == {"schema", "files", "runtime"} and doc["schema"] == 3, "Code manifest schema")
    require(doc["runtime"] == RUNTIME_PINS, "Runtime pins changed")
    for name, wanted in doc["files"].items():
        require(not Path(name).is_absolute() and ".." not in Path(name).parts, "Invalid code member")
        require(digest(ROOT / name) == wanted, "Adapter code changed: " + name)
    actual_files = {p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*.py") if "__pycache__" not in p.parts}
    require(set(doc["files"]) == actual_files, "Installed source inventory differs")
    return actual, doc, qualified_runtime()

def load_native():
    vendor = ROOT / "_vendor"
    if str(vendor) not in sys.path: sys.path.insert(0, str(vendor))
    live = importlib.import_module("camera_live_rebuilt")
    native = importlib.import_module("camera_placement_copy.native")
    model = importlib.import_module("camera_placement_copy.model")
    # Existing Live is allowed only when every loaded module has the frozen bytes.
    for name, module in tuple(sys.modules.items()):
        if not (name == "camera_live_rebuilt" or name.startswith("camera_live_rebuilt.") or name == "camera_placement_copy" or name.startswith("camera_placement_copy.")):
            continue
        path = getattr(module, "__file__", None)
        if not path: continue
        rel = Path(*name.split("."))
        wanted = vendor / rel / "__init__.py" if Path(path).name == "__init__.py" else (vendor / rel).with_suffix(".py")
        require(wanted.is_file() and digest(Path(path)) == digest(wanted), "Foreign camera core: " + name)
    return live, model, native

def prime(bpy, native, scene, request=None):
    if request is not None and request.get("version") == 6:
        try:
            from . import production_snapshot
        except ImportError:
            import production_snapshot
        return production_snapshot.prime(bpy, scene, request)
    require(len(bpy.data.scenes) == 1 and bpy.context.mode == "OBJECT" and bpy.context.view_layer.objects.active is not None, "Single-scene OBJECT/active context required")
    raw = canonical_state(native.state(bpy, scene))
    require("strict_rig_scene" in raw, "Initial Windows slice requires bounded independent rig witness")
    key = "Scene:" + scene.name_full
    ref = {"id_key": key, "identity": {"type": "Scene", "name": scene.name_full, "library": None}}
    refs = raw["strict_rig_scene"]["references"][key]
    require(ref not in refs, "Preexisting Scene self reference refused")
    expected = copy.deepcopy(raw)
    expected["strict_rig_scene"]["references"][key] = sorted(refs + [ref], key=lambda x: x["id_key"])
    require(bpy.ops.ed.undo_push(message="Camera Windows static state initialization") == {"FINISHED"}, "Undo initialization failed")
    primed = canonical_state(native.state(bpy, scene))
    require(primed == expected, "Initialization changed undeclared state")
    return raw, primed

def validate_request(value):
    if type(value) is dict and value.get("version") == 6:
        try:
            from . import production_ops
        except ImportError:
            import production_ops
        return production_ops.validate_request(value)
    require(type(value) is dict and type(value.get("version")) is int and value["version"] in (1, 2, 3, 4, 5), "Exact camera request version required")
    cut = value["version"] == 2
    dof = value["version"] == 3
    motion = value["version"] == 4
    focus = value["version"] == 5
    keys = {"version", "source", "scene", "candidate_name", "session", "baseline"}
    keys |= {"left", "right", "left_last"} if cut else {"shot", "focus_object", "focus_subtarget", "fstop"} if dof else {"shot", "easing"} if motion else {"shot", "helper", "new_start", "locked_frames"} if focus else {"shot", "lens", "local_offset"}
    require(set(value) == keys, "Exact camera request fields required")
    require(type(value["source"]) is dict and set(value["source"]) == {"file", "sha256"}, "Source descriptor")
    require(Path(value["source"]["file"]).suffix.lower() == ".blend", "Saved .blend source required")
    for key in (("scene", "left", "right", "candidate_name") if cut else ("scene", "shot", "candidate_name")):
        require(type(value[key]) is str and 0 < len(value[key]) <= 128, "Named target required")
    if cut:
        require(value["left"] != value["right"] and type(value["left_last"]) is int, "Distinct cut rows and integer frame required")
    elif focus:
        require(type(value["helper"]) is str and 0 < len(value["helper"]) <= 128, "Explicit focus helper required")
        require(type(value["new_start"]) is int, "Integer focus onset required")
        locks = value["locked_frames"]
        require(type(locks) is list and len(locks) == 3 and all(type(f) is int for f in locks)
                and -1048574 <= locks[0] < locks[1] < locks[2] <= 1048574, "Three ordered integer focus locks required")
        require(locks[0] < value["new_start"] < locks[1], "Focus onset must stay strictly inside the first two locks")
    elif motion:
        require(type(value["easing"]) is str and value["easing"] in ("EASE_IN_OUT", "EASE_IN", "EASE_OUT"), "Explicit motion easing required")
    elif dof:
        for key in ("focus_object", "focus_subtarget"):
            require(type(value[key]) is str and 0 < len(value[key]) <= 128, "Named focus object/bone required")
        require(type(value["fstop"]) in (float, int) and math.isfinite(value["fstop"]) and 0.7 <= value["fstop"] <= 64, "F-stop must be finite within0.7..64")
    else:
        require(type(value["lens"]) in (float, int) and not isinstance(value["lens"], bool), "Lens number required")
        require(type(value["local_offset"]) is list and len(value["local_offset"]) == 3, "Three camera-axis offsets required")
    require(value["session"] is None or type(value["session"]) is dict, "Full session witness required")
    require(value["baseline"] is None or type(value["baseline"]) is dict, "Baseline witness required")
    require((value["session"] is None) == (value["baseline"] is None), "GUI source witnesses must be supplied together")
    canonical(value)
    return copy.deepcopy(value)
