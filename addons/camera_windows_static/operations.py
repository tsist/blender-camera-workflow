"""Small operation bridge; the transaction and frozen original cores stay shared."""
try:
    from . import common as c, cut_ops, dof_ops, motion_ops, focus_ops
except ImportError:
    import common as c
    import cut_ops
    import dof_ops
    import motion_ops
    import focus_ops


def production():
    try:
        from . import production_ops
    except ImportError:
        import production_ops
    return production_ops


def is_production(request):
    return request["version"] == 6


def is_cut(request):
    return request["version"] == 2

def is_dof(request):
    return request["version"] == 3

def is_motion(request):
    return request["version"] == 4

def is_focus(request):
    return request["version"] == 5


def baseline(bpy, native, request, sha=None):
    if is_production(request): return production().baseline(bpy, native, request, sha=sha)
    source_sha = sha or request["source"]["sha256"]
    if is_focus(request):
        return focus_ops.baseline(bpy, native, source_sha, request["scene"], request["shot"], request["helper"], request["locked_frames"])
    if is_motion(request):
        return motion_ops.baseline(bpy, native, source_sha, request["scene"], request["shot"])
    if is_cut(request):
        return cut_ops.baseline(bpy, native, source_sha, request["scene"], request["left"])
    if is_dof(request):
        return dof_ops.baseline(bpy, native, source_sha, request["scene"], request["shot"])
    return native.baseline(bpy, source_sha, request["scene"], request["shot"])


def candidate(model, base, request):
    if is_production(request): return production().candidate(model, base, request)
    if is_focus(request): return focus_ops.candidate(base, request)
    if is_motion(request):
        return motion_ops.candidate(base, request)
    if is_cut(request):
        return cut_ops.candidate(base, request)
    if is_dof(request):
        return dof_ops.candidate(base, request)
    return model.offset_variant(base, request["candidate_name"], request["lens"], request["local_offset"])


def expected(native, before, doc, request):
    if is_production(request): return production().expected(before, doc)
    if is_focus(request): return focus_ops.expected(before, doc)
    if is_motion(request): return motion_ops.expected(before, doc)
    if is_dof(request): return dof_ops.expected(before, doc)
    return cut_ops.expected(before, doc) if is_cut(request) else native.expected_state(before, doc)


def validate_candidate(model, doc, request):
    if is_production(request): return production().validate_candidate(doc, request)
    c.require(doc["source_sha256"] == request["source"]["sha256"] and doc["scene"] == request["scene"], "Candidate source/scene differs")
    if is_focus(request):
        c.require(focus_ops.validate_candidate(doc, request) == doc, "Focus candidate operation differs")
    elif is_motion(request):
        c.require(motion_ops.validate_candidate(doc, request) == doc, "Motion candidate operation differs")
    elif is_dof(request):
        c.require(dof_ops.validate_candidate(doc, request) == doc, "Optical candidate operation differs")
    elif is_cut(request):
        from camera_live_rebuilt import candidate_model as table_model
        base = table_model.export_snapshot(doc["source_sha256"], doc["scene"], doc["source_mode"], doc["base_rows"], doc["catalog"])
        c.require(candidate(model, base, request) == doc, "Candidate operation differs from request")
        c.require(doc["operations"] == [{"op": "move_cut", "left": request["left"], "right": request["right"], "left_last": request["left_last"]}], "Exact move_cut required")
    else:
        c.require(candidate(model, doc, request) == doc, "Candidate operation differs from request")
        c.require(doc["shot"] == request["shot"], "Candidate shot differs")


def projection(bpy, native, doc, request, selected=False):
    if is_production(request): return production().projection(bpy, native, doc, request, selected=selected)
    if is_focus(request): return c.canonical_state(focus_ops.projection(bpy, native, doc, selected=selected))
    if is_motion(request): return c.canonical_state(motion_ops.projection(bpy, native, doc, selected=selected))
    if is_dof(request): return c.canonical_state(dof_ops.projection(bpy, native, doc, selected=selected))
    if is_cut(request):
        scene, _ = cut_ops.check_document(bpy, native, doc, selected=selected)
        return c.canonical_state(cut_ops.projection(bpy, native, scene))
    scene, camera = native.check_document(bpy, doc, selected=selected)
    return c.canonical_state(native.projection(camera, scene))


def apply(bpy, native, doc, request):
    if is_production(request): return production().apply(bpy, native, doc)
    if is_focus(request):
        focus_ops.apply(bpy, native, doc)
    elif is_motion(request):
        motion_ops.apply(bpy, native, doc)
    elif is_dof(request):
        dof_ops.apply(bpy, native, doc)
    elif is_cut(request):
        cut_ops.apply(bpy, native, doc)
    else:
        _, camera = native.check_document(bpy, doc)
        camera.location = doc["location"]
        camera.data.lens = doc["lens"]


def verify_next(base, doc, state, output_sha, request):
    if is_production(request): return production().verify_next(base, doc, state, output_sha, request)
    if is_focus(request): return focus_ops.verify_next(base, doc, state, output_sha)
    if is_motion(request): return motion_ops.verify_next(base, doc, state, output_sha)
    if is_dof(request): return dof_ops.verify_next(base, doc, state, output_sha)
    c.require(base["source_sha256"] == output_sha, "Reopened baseline output differs")
    if is_cut(request):
        c.require(set(base) == set(doc) and base["schema"] == doc["schema"], "Reopened table schema differs")
        c.require(base["operations"] == [] and base["rows"] == base["base_rows"] == doc["rows"], "Reopened cut table differs")
        for field in ("scene", "source_mode", "catalog"):
            c.require(base[field] == doc[field], "Reopened cut identity differs")
        c.require(base["base_table_sha256"] == c.hashlib.sha256(c.canonical({"source_mode": base["source_mode"], "rows": base["rows"]})).hexdigest(), "Reopened table seal differs")
        c.require(base["content_sha256"] == c.hashlib.sha256(c.canonical({k:v for k,v in base.items() if k != "content_sha256"})).hexdigest(), "Reopened content seal differs")
    else:
        c.require(base["base_lens"] == doc["lens"] == base["lens"], "Reopened baseline lens differs")
        for field in ("scene", "source_mode", "catalog", "base_rows", "shot", "camera", "camera_data", "target_mode"):
            c.require(base[field] == doc[field], "Reopened target/table differs")
        c.require(base["base_pose"] == state["expected_raw"]["object_transforms"][doc["camera"]], "Reopened target pose differs")
