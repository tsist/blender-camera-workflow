"""Saved-scene framing inspection shared by Windows GUI and public CLI."""
from pathlib import Path

try:
    from . import common as c, framing
except ImportError:
    import common as c
    import framing


def validate(request):
    c.require(type(request) is dict and set(request) == {"source", "scene", "specs", "resources"},
              "Expected source, scene, specs and resources")
    c.require(type(request["scene"]) is str and 0 < len(request["scene"]) <= 128, "Explicit scene required")
    specs = request["specs"]
    c.require(type(specs) is dict and 1 <= len(specs) <= 4
              and all(0 < len(name) <= 64 and type(spec) is dict for name, spec in specs.items()),
              "Use up to four named framing specifications")
    resources = request["resources"]
    c.require(type(resources) is list and len(resources) <= 64, "Use up to 64 resource descriptors")
    identifiers = set()
    for item in [request["source"], *resources]:
        c.require(type(item) is dict and set(item) == {"file", "sha256"}, "Exact file descriptor required")
        c.require(type(item["file"]) is str and Path(item["file"]).is_absolute()
                  and ".." not in Path(item["file"]).parts, "Absolute input path required")
        sha = item["sha256"]
        c.require(type(sha) is str and len(sha) == 64 and set(sha) <= set("0123456789abcdef"), "SHA256 required")
        identity = str(Path(item["file"]).resolve()).casefold()
        c.require(identity not in identifiers, "Duplicate input path")
        identifiers.add(identity)
    c.require(Path(request["source"]["file"]).suffix.lower() == ".blend", "Saved .blend source required")
    return request


def inspect_saved(bpy, request):
    c.require(bpy.app.background, "Use the owned background framing worker")
    source = request["source"]
    c.require(bpy.ops.wm.open_mainfile(filepath=source["file"], load_ui=False, use_scripts=False) == {"FINISHED"},
              "Cannot open the requested source")
    scene = bpy.context.scene
    c.require(scene.name == request["scene"], "Opened a different scene")
    c.require(not bpy.data.libraries, "Linked project resources require a scene-specific adapter")
    expected = {str(Path(row["file"]).resolve()).casefold() for row in request["resources"]}
    images = {str(Path(bpy.path.abspath(image.filepath)).resolve()).casefold()
              for image in bpy.data.images if image.source == "FILE" and not image.packed_file}
    c.require(images == expected, "External FILE image inventory differs from resources")
    return {name: framing.audit(bpy, scene, spec) for name, spec in request["specs"].items()}


def suggestion_for_copy(report, name):
    c.require(name in report["audits"], "Select a case from the verified report")
    audit = report["audits"][name]
    suggestion = audit["recommendation"]
    c.require(suggestion["improves"] and suggestion["passes_samples"] and not audit["conflict"],
              "The selected case has no conflict-free correction to check")
    lenses = {sample["lens_mm"] for sample in suggestion["validation"]["samples"]}
    c.require(len(lenses) == 1, "Animated optics require an explicit camera-motion workflow")
    return audit["camera"], lenses.pop(), [suggestion["local_x"], suggestion["local_y"], 0.0]
