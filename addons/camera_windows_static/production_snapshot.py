"""Read-only composition of the established follow/material witnesses.

No Undo, ID creation, file open, activation or save is performed here.  This is
also the GUI session witness; native planning belongs to the background worker.
"""
import hashlib
from pathlib import Path

try:
    from . import common as c
except ImportError:
    import common as c


def _runtime():
    import sys
    for path in (str(c.HOST), str(c.HOST.parent)):
        if path not in sys.path:
            sys.path.insert(0, path)
    import bpy, rigging, inspection, material_workflow
    from animation_curves_workflow_addon.native import action_state
    # An import may return a module cached by a different GUI addon. Check the
    # actual loaded sources, including already loaded host dependencies; adding
    # HOST to sys.path alone does not establish their provenance.
    expected = {path.stem: path.resolve() for path in c.HOST.glob("*.py")}
    # The standalone worker deliberately imports these adapter modules by their
    # bare names. Their own manifest-pinned paths take precedence over a same-
    # named host helper (notably HOST/operations.py).
    own = {name: (c.ROOT / (name + ".py")).resolve() for name in
           ("operations", "common", "production_ops", "production_snapshot")}
    expected.update(own)
    for name, module in tuple(sys.modules.items()):
        wanted = expected.get(name)
        if wanted is not None:
            source = getattr(module, "__file__", None)
            c.require(source is not None and Path(source).resolve() == wanted,
                      "Foreign production snapshot module: " + name)
        for package in ("animation_curves_workflow_addon", "material_workflow_addon"):
            if name == package or name.startswith(package + "."):
                source = getattr(module, "__file__", None)
                relative = Path(*name.split("."))
                base = c.HOST.parent / relative
                wanted = base / "__init__.py" if source and Path(source).name == "__init__.py" else base.with_suffix(".py")
                c.require(source is not None and Path(source).resolve() == wanted.resolve(),
                          "Foreign production snapshot addon module: " + name)
    return bpy, rigging, inspection, material_workflow, action_state


def image_ledger(bpy):
    """File bytes, not display names, define external resource identity."""
    c.require(not bpy.data.libraries, "Production retime rejects linked Libraries")
    for kind in ("sounds", "movieclips", "volumes", "cache_files", "fonts"):
        for item in getattr(bpy.data, kind, ()):
            path = getattr(item, "filepath", "")
            c.require(not path or path == "<builtin>", "Unsupported external resource: " + kind)
    result = {}
    for image in sorted(bpy.data.images, key=lambda i: i.name):
        c.require(not image.library and not image.override_library, "Linked image rejected")
        c.require(image.source == "FILE", "Unsupported image source: " + image.name + "/" + image.source)
        packed = []
        for entry in getattr(image, "packed_files", ()):
            data = entry.packed_file
            c.require(data is not None, "Incomplete packed image")
            packed.append({"filepath": entry.filepath, "size": int(data.size),
                           "sha256": hashlib.sha256(bytes(data.data)).hexdigest()})
        if not packed and image.packed_file:
            data = image.packed_file
            packed.append({"filepath": image.filepath, "size": int(data.size),
                           "sha256": hashlib.sha256(bytes(data.data)).hexdigest()})
        row = {"source": image.source, "filepath": image.filepath,
               "packed": packed, "external": None}
        if not packed:
            c.require(Path(image.filepath).is_absolute() and not image.filepath.startswith("//"),
                      "Unpacked image must use an absolute path: " + image.name)
            path = c.clean(image.filepath)
            row["external"] = {"file": str(path), "sha256": c.digest(path)}
        result[image.name] = row
    return result


def resources(images):
    unique = {}
    for row in images.values():
        resource = row["external"]
        if resource:
            key = str(Path(resource["file"])).casefold()
            c.require(key not in unique or unique[key] == resource, "Resource aliases disagree")
            unique[key] = resource
    return sorted(unique.values(), key=lambda r: r["file"].casefold())


def capture():
    bpy, rigging, inspection, material_workflow, action_state = _runtime()
    images = image_ledger(bpy)
    actions = {}
    for action in bpy.data.actions:
        c.require(len(action.slots) == len(action.layers) == 1
                  and len(action.layers[0].strips) == 1, "Full Action witness requires one slot/layer/strip")
        strip = action.layers[0].strips[0]
        c.require(strip.type == "KEYFRAME" and len(strip.channelbags) == 1
                  and strip.channelbag(action.slots[0]) == strip.channelbags[0],
                  "Full Action witness requires one exclusive KEYFRAME bag")
        actions[action.name] = action_state(action)
    trees = {}
    for kind in ("materials", "lights", "worlds"):
        for owner in getattr(bpy.data, kind):
            if getattr(owner, "node_tree", None):
                trees[kind + "/" + owner.name] = inspection.record(owner.node_tree)
    scene = bpy.context.scene
    def markers(s):
        return [{"name": m.name, "frame": m.frame,
                 "camera": m.camera.name if m.camera else None} for m in s.timeline_markers]
    follow = {"rig": rigging.state(), "complete_actions": actions,
              "embedded_node_trees": trees, "markers": markers(scene),
              "render": inspection.configuration(scene.render),
              "view": inspection.properties(scene.view_settings),
              "scene_metadata": {s.name: {"range": [s.frame_start, s.frame_end],
                  "time": [s.frame_current, s.frame_subframe], "markers": markers(s),
                  "camera": s.camera.name if s.camera else None}
                  for s in sorted(bpy.data.scenes, key=lambda s: s.name)}}
    return c.canonical_state({"follow": follow, "material": material_workflow.snapshot(), "images": images})


def prime(bpy, scene, request):
    c.require(bpy.context.scene == scene and scene.name == request["scene"],
              "Production snapshot requires the already active requested Scene")
    raw = capture()
    c.require(c.canonical(resources(raw["images"])) == c.canonical(request["resources"]),
              "External FILE resources missing, extra, duplicated or changed")
    return raw, raw
