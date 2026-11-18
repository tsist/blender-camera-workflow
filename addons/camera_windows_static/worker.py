"""Windows static-placement worker; publication and cancellation belong to service."""
import os
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common
import operations as ops
import bpy


STAGES = {"check", "apply", "cold_staging", "cold_final", "diagnose"}
SHA = re.compile(r"[0-9a-f]{64}\Z")


def run():
    require = common.require
    inputs = {}
    registered = False
    live = None

    def absolute(value):
        require(type(value) is str and bool(value), "Absolute path string required")
        path = Path(value)
        require(path.is_absolute() and ".." not in path.parts, "Absolute path required")
        return path

    def pin(path, expected):
        require(type(expected) is str and SHA.fullmatch(expected), "Invalid SHA256")
        require(path.is_file(), "Input file missing: " + str(path))
        require(common.digest(path) == expected, "Input identity differs: " + str(path))
        key = os.path.normcase(str(path.resolve()))
        if key in inputs:
            require(inputs[key][1] == expected, "Conflicting input identity")
        inputs[key] = (path, expected)

    def descriptor(value):
        require(type(value) is dict and set(value) == {"file", "sha256"}, "Invalid descriptor")
        pin(absolute(value["file"]), value["sha256"])
        result = common.load_descriptor(value)
        require(type(result) is dict, "Descriptor must contain a JSON object")
        return result

    def check_inputs():
        for path, expected in inputs.values():
            require(common.digest(path) == expected, "Input changed: " + str(path))

    def capture(native, scene):
        if ops.is_production(request):
            try:
                from . import production_snapshot
            except ImportError:
                import production_snapshot
            return common.canonical_state(production_snapshot.capture())
        return common.canonical_state(native.state(bpy, scene))

    try:
        require(sys.argv.count("--") == 1, "Exact worker argument separator required")
        args = sys.argv[sys.argv.index("--") + 1:]
        require(len(args) == 2, "Expected config_path config_sha")
        config_path = absolute(args[0])
        pin(config_path, args[1])
        config = common.read_json(config_path)
        require(type(config) is dict and type(config.get("schema")) is int
                and config["schema"] == 1, "Config schema differs")
        stage = config.get("stage")
        require(stage in STAGES, "Unknown worker stage")
        config_keys = {"schema", "stage", "job", "manifest_sha", "request"}
        if stage not in {"check", "diagnose"}:
            config_keys.add("check")
        if stage in {"cold_staging", "cold_final"}:
            config_keys.add("output_sha")
        require(set(config) == config_keys, "Exact stage config fields required")
        job = absolute(config.get("job"))
        require(job.is_dir(), "Job directory missing")
        manifest_sha = config.get("manifest_sha")
        require(type(manifest_sha) is str and SHA.fullmatch(manifest_sha), "Invalid package manifest SHA")
        common.verify_package(manifest_sha)
        require(os.name == "nt" and bpy.app.background, "Windows background worker required")
        require(tuple(bpy.app.version) == (5, 2, 1)
                and bpy.app.build_hash == b"9e2066aef7ef", "Blender build differs")
        require(common.digest(Path(bpy.app.binary_path)) == common.BINARY_SHA,
                "Windows binary identity differs")
        require(all(flag in sys.argv for flag in
                    ("--background", "--factory-startup", "--disable-autoexec", "--offline-mode")),
                "Required startup isolation flags missing")
        require(not bpy.data.filepath, "Worker must start without a loaded file")
        for env_key, resource in (("BLENDER_USER_CONFIG", "CONFIG"),
                                  ("BLENDER_USER_SCRIPTS", "SCRIPTS"),
                                  ("BLENDER_USER_DATAFILES", "DATAFILES")):
            require(env_key in os.environ, "Missing isolated profile: " + env_key)
            require(absolute(os.environ[env_key]).resolve()
                    == Path(bpy.utils.user_resource(resource)).resolve(), "Profile API mismatch")
        if "BLENDER_USER_EXTENSIONS" in os.environ:
            require(absolute(os.environ["BLENDER_USER_EXTENSIONS"]).resolve()
                    == Path(bpy.utils.user_resource("EXTENSIONS")).resolve(), "Extensions profile mismatch")

        if stage == "diagnose":
            import framing_ops
            request = framing_ops.validate(descriptor(config["request"]))
            for item in [request["source"], *request["resources"]]:
                pin(absolute(item["file"]), item["sha256"])
            audits = framing_ops.inspect_saved(bpy, request)
            check_inputs()
            common.verify_package(manifest_sha)
            report = common.write_new(job / "framing-report.json", {
                "source": request["source"], "scene": request["scene"], "audits": audits, "source_saved": False})
            common.write_new(job / "diagnose-worker.json", {"stage": stage, "verified": True, "report": report})
            return

        live, model, native = common.load_native()
        live.register()
        registered = True

        if stage == "check":
            require("request" in config and "check" not in config
                    and "output_sha" not in config, "CHECK config binding differs")
            request = common.validate_request(descriptor(config["request"]))
            require(type(request.get("version")) is int and request["version"] in (1, 2, 3, 4, 5, 6),
                    "Request version differs")
            source_desc = request.get("source")
            require(type(source_desc) is dict and set(source_desc) == {"file", "sha256"},
                    "Request source descriptor differs")
            source = absolute(source_desc["file"])
            pin(source, source_desc["sha256"])
            if ops.is_production(request):
                for resource in request["resources"]:
                    pin(absolute(resource["file"]), resource["sha256"])
            require(bpy.ops.wm.open_mainfile(filepath=str(source), load_ui=False,
                                            use_scripts=False) == {"FINISHED"}, "Open source failed")
            scene = bpy.context.scene
            require(scene.name == request.get("scene"), "Requested scene differs")
            raw, primed = common.prime(bpy, native, scene, request)
            raw, primed = common.canonical_state(raw), common.canonical_state(primed)
            require("session" in request and "baseline" in request, "Missing GUI binding fields")
            if request["session"] is not None:
                require(type(request["session"]) is dict
                        and common.canonical_state(request["session"]) == primed,
                        "GUI session witness differs")
            base = ops.baseline(bpy, native, request)
            if request["baseline"] is not None:
                require(type(request["baseline"]) is dict
                        and common.canonical_state(request["baseline"]) == common.canonical_state(base),
                        "GUI baseline differs")
            doc = ops.candidate(model, base, request)
            expected_raw = common.canonical_state(ops.expected(native, raw, doc, request))
            expected_primed = common.canonical_state(ops.expected(native, primed, doc, request))
            if ops.is_production(request):
                require(raw == primed and expected_raw == expected_primed,
                        "Production compact state requires exact before/primed aliases")
            require(capture(native, scene) == primed, "CHECK changed source state")
            check_inputs()
            common.write_new(job / "candidate.json", doc)
            common.write_new(job / "state.json", {
                "schema": "camera-production-state/1", "before": raw, "expected": expected_raw
            } if ops.is_production(request) else {
                "raw": raw, "primed": primed,
                "expected_raw": expected_raw, "expected_primed": expected_primed})
            common.write_new(job / "check-worker.json", {
                "stage": stage, "verified": True, "source_sha": source_desc["sha256"],
                "request_sha": config["request"]["sha256"], "manifest_sha": manifest_sha,
                "scene": doc["scene"], "operation": "retime_camera_group" if ops.is_production(request) else "focus" if ops.is_focus(request) else "motion" if ops.is_motion(request) else "dof" if ops.is_dof(request) else "move_cut" if ops.is_cut(request) else "static",
                "candidate_sha": common.digest(job / "candidate.json")})
            return

        require("check" in config and "request" in config, "Stage CHECK receipt missing")
        receipt = descriptor(config["check"])
        require(set(receipt) == {"schema", "nonce", "manifest_sha", "request", "state", "candidate",
                                 "source", "job", "session_mode"}
                and type(receipt["schema"]) is int and receipt["schema"] == 1,
                "Exact CHECK receipt fields required")
        require(absolute(receipt["job"]).resolve() == job.resolve(), "Receipt job differs")
        require(receipt.get("manifest_sha") == manifest_sha, "Receipt package identity differs")
        require(type(receipt.get("nonce")) is str and bool(receipt["nonce"]), "Receipt nonce missing")
        require(config["request"] == receipt["request"], "Config/CHECK request descriptor differs")
        request = common.validate_request(descriptor(receipt.get("request")))
        require(type(request["version"]) is int, "Request version type differs")
        require(receipt["session_mode"] == ("GUI_BOUND" if request["session"] is not None else "SAVED_DISK"),
                "Receipt session mode differs")
        state = descriptor(receipt.get("state"))
        doc = descriptor(receipt.get("candidate"))
        if ops.is_production(request):
            require(set(state) == {"schema", "before", "expected"}
                    and state["schema"] == "camera-production-state/1"
                    and type(state["before"]) is type(state["expected"]) is dict,
                    "Production compact state schema differs")
            state = {"raw": state["before"], "primed": state["before"],
                     "expected_raw": state["expected"], "expected_primed": state["expected"]}
        require(set(state) == {"raw", "primed", "expected_raw", "expected_primed"}
                and all(type(value) is dict for value in state.values()),
                "Sealed state fields differ")
        source_desc = receipt.get("source")
        require(type(source_desc) is dict and set(source_desc) == {"file", "sha256"},
                "Receipt source descriptor differs")
        require(source_desc == request.get("source"), "Receipt/request source differs")
        pin(absolute(source_desc["file"]), source_desc["sha256"])
        if ops.is_production(request):
            for resource in request["resources"]:
                pin(absolute(resource["file"]), resource["sha256"])
        ops.validate_candidate(model, doc, request)
        # Re-derive both expected states from sealed source states before applying anything.
        require(common.canonical_state(ops.expected(native, state["raw"], doc, request)) == state["expected_raw"],
                "Sealed raw expectation differs")
        require(common.canonical_state(ops.expected(native, state["primed"], doc, request)) == state["expected_primed"],
                "Sealed primed expectation differs")

        if stage == "apply":
            require("output_sha" not in config, "APPLY must not supply output identity")
            opened = absolute(source_desc["file"])
        else:
            opened = job / ("staging.blend" if stage == "cold_staging" else "candidate.blend")
            pin(opened, config.get("output_sha"))
        require(bpy.ops.wm.open_mainfile(filepath=str(opened), load_ui=False,
                                        use_scripts=False) == {"FINISHED"}, "Open bound input failed")
        scene = bpy.context.scene
        require(scene.name == doc["scene"], "Opened scene differs")
        raw, primed = common.prime(bpy, native, scene, request)
        raw, primed = common.canonical_state(raw), common.canonical_state(primed)
        if stage == "apply":
            require(raw == state["raw"] and primed == state["primed"], "Source state changed after CHECK")
            projection_before = ops.projection(bpy, native, doc, request)
            ops.apply(bpy, native, doc, request)
            require(capture(native, scene) == state["expected_primed"], "Undeclared application delta")
            projection_after = ops.projection(bpy, native, doc, request, selected=True)
            target = job / "staging.blend"
            require(not target.exists(), "Staging output already exists")
            check_inputs()
            require(bpy.ops.wm.save_as_mainfile(filepath=str(target), copy=True,
                                              relative_remap=False, check_existing=True) == {"FINISHED"},
                    "Save staging failed")
            require(capture(native, scene) == state["expected_primed"], "Post-save state differs")
            check_inputs()
            common.write_new(job / "apply-worker.json", {
                "stage": stage, "verified": True, "output_sha": common.digest(target),
                "projection_before": projection_before, "projection_after": projection_after})
        else:
            require(raw == state["expected_raw"] and primed == state["expected_primed"],
                    "Cold raw/primed output differs")
            projection = ops.projection(bpy, native, doc, request, selected=True)
            if request["version"] == 1:
                require(projection["lens"] == doc["lens"]
                        and projection["matrix_world"] == native.state_contract.selected_pose(doc)["matrix_world"],
                        "Cold projection differs")
            output_sha = config["output_sha"]
            if stage == "cold_final":
                next_base = ops.baseline(bpy, native, request, sha=output_sha)
                require(capture(native, scene) == primed, "Baseline capture changed cold state")
                common.write_new(job / "next-baseline.json", next_base)
            check_inputs()
            common.write_new(job / (stage + "-worker.json"), {
                "stage": stage, "verified": True, "output_sha": output_sha,
                "projection": projection})
    finally:
        try:
            if registered:
                live.unregister()
        finally:
            check_inputs()


if __name__ == "__main__":
    run()
