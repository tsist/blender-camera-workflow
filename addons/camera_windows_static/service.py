"""One Windows CHECK/apply transaction shared by GUI and the public CLI bridge."""
from contextlib import ExitStack
import os
from pathlib import Path
import subprocess
import time
import uuid
from . import common as c, operations as ops

class Cancelled(Exception):
    pass

def descriptor(path):
    return {"file": str(path), "sha256": c.digest(path)}

def _guard(stack, path, wanted=None, renameable=False, parents=None):
    fs, _ = c.load_host()
    path = c.clean(path)
    if parents is not None:
        for parent in reversed(path.parents):
            key = str(parent)
            if key not in parents:
                stack.enter_context(fs.FileGuard(parent, directory=True))
                parents.add(key)
    guard = stack.enter_context(fs.FileGuard(path, renameable=renameable))
    c.require(guard._information().links == 1, "Aliased file refused")
    if wanted is not None: c.require(guard.sha256() == wanted, "Guarded bytes changed: " + str(path))
    return guard

def _code_guards(stack, expected=None):
    manifest_sha, manifest = c.verify_package(expected)
    parents = set()
    _guard(stack, c.ROOT / "CODE-MANIFEST.json", manifest_sha, parents=parents)
    for name, sha in manifest["files"].items(): _guard(stack, c.ROOT / name, sha, parents=parents)
    binary, python = c.runtime_paths()
    _guard(stack, binary, c.BINARY_SHA, parents=parents)
    _guard(stack, python, c.PYTHON_SHA, parents=parents)
    return manifest_sha, parents

def _guard_descriptor(stack, item, parents):
    c.require(type(item) is dict and set(item) == {"file", "sha256"}, "Exact file descriptor required")
    _guard(stack, Path(item["file"]), item["sha256"], parents=parents)
    return c.load_descriptor(item)

def _progress(job, stage):
    fs, _ = c.load_host()
    path = job / "progress.json"
    tmp = job / (".progress-" + uuid.uuid4().hex + ".json")
    c.write_new(tmp, {"stage": stage, "at": time.time()})
    os.replace(tmp, path)

def _decision(job, check_sha):
    path = job / "decision.json"
    if not path.exists(): return None
    fs, _ = c.load_host()
    c.clean(path)
    raw = fs.read_shared_bytes(path)
    c.require(len(raw) <= 4096, "Bounded decision required")
    value = c.parse(raw)
    c.require(set(value) == {"check_sha", "decision"} and value["check_sha"] == check_sha and value["decision"] in ("CANCEL", "COMMIT"), "Decision binding differs")
    return value["decision"]

def _publish_decision(job, check_sha, decision):
    """Publish only complete bytes, with no replacement and one atomic winner."""
    fs, _ = c.load_host()
    temp = job / (".decision-" + uuid.uuid4().hex + ".json")
    c.write_new(temp, {"check_sha": check_sha, "decision": decision})
    with fs.FileGuard(temp, renameable=True) as guard:
        try: guard.rename_new(job / "decision.json")
        except Exception:
            if not (job / "decision.json").exists(): raise
    # A losing complete proposal is retained as diagnostic evidence.
    return _decision(job, check_sha)

def _cancelled(job, check_sha):
    if _decision(job, check_sha) == "CANCEL": raise Cancelled("Cancellation won before commit")

def cancel(job, check_sha):
    job = c.clean(job, True)
    with ExitStack() as stack:
        _guard(stack, job / "check.json", check_sha, parents=set())
        winner = _publish_decision(job, check_sha, "CANCEL")
        return {"accepted": winner == "CANCEL", "decision": winner, "scope": "COMMIT winner cannot be cancelled"}

def _worker(stack, job, stage, manifest_sha, request_desc, check_desc=None, output_sha=None, check_sha=None):
    _, processes = c.load_host()
    _progress(job, stage)
    cfg = {"schema": 1, "stage": stage, "job": str(job), "manifest_sha": manifest_sha, "request": request_desc}
    if check_desc is not None: cfg["check"] = check_desc
    if output_sha is not None: cfg["output_sha"] = output_sha
    cfg_path = job / (stage + "-config.json")
    c.write_new(cfg_path, cfg)
    cfg_sha = c.digest(cfg_path)
    _guard(stack, cfg_path, cfg_sha, parents=set())
    env = os.environ.copy()
    for key in ("PYTHONPATH", "PYTHONHOME"): env.pop(key, None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    for key, folder in (("BLENDER_USER_CONFIG", "config"), ("BLENDER_USER_SCRIPTS", "scripts"),
                        ("BLENDER_USER_DATAFILES", "datafiles"), ("BLENDER_USER_EXTENSIONS", "extensions"),
                        ("TEMP", "tmp"), ("TMP", "tmp")):
        path = job / "profiles" / stage / folder
        path.mkdir(parents=True, exist_ok=False) if not path.exists() else c.clean(path, True)
        env[key] = str(path)
    binary, _ = c.runtime_paths()
    command = [str(binary), "--background", "--factory-startup", "--disable-autoexec", "--offline-mode",
               "--python-exit-code", "17", "--python", str(c.ROOT / "worker.py"), "--", str(cfg_path), cfg_sha]
    with (job / (stage + ".log")).open("xb") as log:
        tree = processes.ProcessTree(command, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        interrupted = None
        deadline = time.monotonic() + 180
        try:
            while True:
                if check_sha is not None: _cancelled(job, check_sha)
                try:
                    code = tree.process.wait(timeout=0.2)
                    break
                except subprocess.TimeoutExpired:
                    if time.monotonic() >= deadline: raise TimeoutError("Owned Blender stage exceeded 180 seconds")
        except BaseException as exc:
            interrupted = exc
            tree.terminate()
            code = tree.process.returncode
        finally:
            tree.close()
    record = {"stage": stage, "pid": tree.process.pid, "returncode": code, "waited": True, "job_closed": True,
              "command": command, "config_sha": cfg_sha}
    if interrupted is not None: record["interrupted"] = type(interrupted).__name__
    c.write_new(job / (stage + "-child.json"), record)
    if interrupted is not None: raise interrupted
    c.require(code == 0, "Blender stage failed; see " + str(job / (stage + ".log")))
    _guard(stack, job / (stage + "-worker.json"), parents=set())
    result = c.read_json(job / (stage + "-worker.json"))
    c.require(result.get("verified") is True and result.get("stage") == stage, "Worker stage result differs")
    return result

def check(request, job):
    request = c.validate_request(request)
    job = Path(job)
    c.clean(job.parent, True)
    c.require(not job.exists(), "CHECK requires a new job directory")
    job.mkdir()
    fs, _ = c.load_host()
    with fs.PathLocks([job]), ExitStack() as stack:
        manifest_sha, parents = _code_guards(stack)
        source = request["source"]
        _guard(stack, Path(source["file"]), source["sha256"], parents=parents)
        if request["version"] == 6:
            for resource in request["resources"]:
                _guard(stack, Path(resource["file"]), resource["sha256"], parents=parents)
        c.write_new(job / "request.json", request)
        request_desc = descriptor(job / "request.json")
        _guard_descriptor(stack, request_desc, parents)
        try:
            _worker(stack, job, "check", manifest_sha, request_desc)
            state_desc, candidate_desc = descriptor(job / "state.json"), descriptor(job / "candidate.json")
            _guard_descriptor(stack, state_desc, parents)
            _guard_descriptor(stack, candidate_desc, parents)
            receipt = {"schema": 1, "nonce": uuid.uuid4().hex, "manifest_sha": manifest_sha,
                       "request": request_desc, "state": state_desc, "candidate": candidate_desc,
                       "source": source, "job": str(job), "session_mode": "GUI_BOUND" if request["session"] is not None else "SAVED_DISK"}
            c.write_new(job / "check.json", receipt)
            result = {"status": "READY", "check": descriptor(job / "check.json"), "job": str(job),
                      "candidate": candidate_desc, "source_sha": source["sha256"], "session_mode": receipt["session_mode"]}
            c.write_new(job / "CHECK-READY.json", result)
            _progress(job, "READY")
            return result
        except BaseException as exc:
            c.write_new(job / "CHECK-FAILED.json", {"status": "FAILED", "error": str(exc), "type": type(exc).__name__})
            _progress(job, "CHECK_FAILED")
            raise

def _read_check(stack, job, check_sha):
    manifest_sha, parents = _code_guards(stack)
    _guard(stack, job / "check.json", check_sha, parents=parents)
    receipt = c.read_json(job / "check.json")
    c.require(set(receipt) == {"schema", "nonce", "manifest_sha", "request", "state", "candidate", "source", "job", "session_mode"} and receipt["schema"] == 1, "Check receipt schema")
    c.require(receipt["job"] == str(job) and receipt["manifest_sha"] == manifest_sha, "Check job/code binding differs")
    request = _guard_descriptor(stack, receipt["request"], parents)
    c.validate_request(request)
    _guard_descriptor(stack, receipt["state"], parents)
    _guard_descriptor(stack, receipt["candidate"], parents)
    c.require(receipt["source"] == request["source"], "Check source binding differs")
    _guard(stack, Path(receipt["source"]["file"]), receipt["source"]["sha256"], parents=parents)
    if request["version"] == 6:
        for resource in request["resources"]:
            _guard(stack, Path(resource["file"]), resource["sha256"], parents=parents)
    return receipt, parents

def apply(job, check_sha, on_stage=None):
    job = c.clean(job, True)
    fs, _ = c.load_host()
    with fs.PathLocks([job]), ExitStack() as stack:
        receipt, parents = _read_check(stack, job, check_sha)
        c.write_new(job / "apply-start.json", {"check_sha": check_sha, "pid": os.getpid(), "nonce": uuid.uuid4().hex})
        check_desc = {"file": str(job / "check.json"), "sha256": check_sha}
        committed = False
        try:
            _cancelled(job, check_sha)
            applied = _worker(stack, job, "apply", receipt["manifest_sha"], receipt["request"], check_desc, check_sha=check_sha)
            output_sha = applied["output_sha"]
            staging = _guard(stack, job / "staging.blend", output_sha, parents=parents)
            staging_identity = staging.identity()
            _progress(job, "SAVED_STAGING")
            if on_stage: on_stage("SAVED_STAGING", job, check_sha)
            _cancelled(job, check_sha)
            cold_staging = _worker(stack, job, "cold_staging", receipt["manifest_sha"], receipt["request"], check_desc, output_sha, check_sha)
            c.require(cold_staging.get("output_sha") == output_sha, "Staging output binding differs")
            if on_stage: on_stage("VERIFIED_STAGING", job, check_sha)
            _cancelled(job, check_sha)
            _publish_decision(job, check_sha, "COMMIT")
            c.require(_decision(job, check_sha) in ("CANCEL", "COMMIT"), "Commit decision missing")
            _cancelled(job, check_sha)
            committed = True
            # CRT/Blender readers do not share DELETE. Upgrade only for rename,
            # and prove identity plus content again on each newly acquired handle.
            staging.close()
            publishing = _guard(stack, job / "staging.blend", output_sha, renameable=True, parents=parents)
            c.require(publishing.identity() == staging_identity, "Staging identity changed during handle upgrade")
            publishing.rename_new(job / "candidate.blend")
            publishing.close()
            final_guard = _guard(stack, job / "candidate.blend", output_sha, parents=parents)
            c.require(final_guard.identity() == staging_identity, "Final identity changed during reader handoff")
            if on_stage: on_stage("COMMITTED", job, check_sha)
            final = _worker(stack, job, "cold_final", receipt["manifest_sha"], receipt["request"], check_desc, output_sha)
            c.require(final.get("output_sha") == output_sha and final_guard.sha256() == output_sha, "Final output binding differs")
            evidence = {name: descriptor(job / name) for name in ("check.json", "request.json", "state.json", "candidate.json", "apply-worker.json", "cold_staging-worker.json", "cold_final-worker.json", "next-baseline.json")}
            result = {"status": "SUCCEEDED", "check_sha": check_sha, "output": {"file": str(job / "candidate.blend"), "sha256": output_sha},
                      "source": receipt["source"], "manifest_sha": receipt["manifest_sha"], "evidence": evidence,
                      "session_mode": receipt["session_mode"], "committed": True}
            c.write_new(job / "terminal.json", result)
            _progress(job, "SUCCEEDED")
            return result
        except BaseException as exc:
            status = "CANCELLED" if isinstance(exc, Cancelled) else "FAILED_AFTER_COMMIT" if committed else "FAILED"
            terminal = {"status": status, "check_sha": check_sha, "committed": committed, "error": str(exc), "type": type(exc).__name__,
                        "retained_staging": (job / "staging.blend").exists(), "candidate_present": (job / "candidate.blend").exists()}
            c.write_new(job / "terminal.json", terminal)
            _progress(job, status)
            if isinstance(exc, Cancelled): return terminal
            raise

def verified_result(job, terminal_sha=None):
    job = c.clean(job, True)
    with ExitStack() as stack:
        parents = set()
        _guard(stack, job / "terminal.json", terminal_sha, parents=parents)
        terminal = c.read_json(job / "terminal.json")
        c.require(terminal.get("status") == "SUCCEEDED" and terminal.get("committed") is True, "No verified successful result")
        c.require(set(terminal) == {"status", "check_sha", "output", "source", "manifest_sha", "evidence", "session_mode", "committed"}, "Exact terminal fields required")
        receipt, parents = _read_check(stack, job, terminal["check_sha"])
        c.require(terminal["source"] == receipt["source"] and terminal["manifest_sha"] == receipt["manifest_sha"], "Terminal binding differs")
        c.require(terminal["session_mode"] == receipt["session_mode"] and _decision(job, terminal["check_sha"]) == "COMMIT", "Commit/session binding differs")
        c.require(terminal["output"]["file"] == str(job / "candidate.blend"), "Final candidate path differs")
        names = {"check.json", "request.json", "state.json", "candidate.json", "apply-worker.json", "cold_staging-worker.json", "cold_final-worker.json", "next-baseline.json"}
        c.require(type(terminal["evidence"]) is dict and set(terminal["evidence"]) == names, "Complete exact final evidence required")
        _guard(stack, Path(terminal["output"]["file"]), terminal["output"]["sha256"], parents=parents)
        docs = {}
        for name, item in terminal["evidence"].items():
            c.require(item["file"] == str(job / name), "Final evidence path differs")
            docs[name] = _guard_descriptor(stack, item, parents)
        for field, name in (("request", "request.json"), ("state", "state.json"), ("candidate", "candidate.json")):
            c.require(terminal["evidence"][name] == receipt[field], "CHECK/final evidence binding differs")
        c.require(terminal["evidence"]["check.json"]["sha256"] == terminal["check_sha"], "Final CHECK SHA differs")
        for stage in ("apply", "cold_staging", "cold_final"):
            report = docs[stage + "-worker.json"]
            c.require(report.get("stage") == stage and report.get("verified") is True and report.get("output_sha") == terminal["output"]["sha256"], "Final stage proof differs")
        applied = docs["apply-worker.json"]
        c.require(docs["cold_staging-worker.json"]["projection"] == applied["projection_after"] == docs["cold_final-worker.json"]["projection"], "Final projection proof differs")
        candidate, base = docs["candidate.json"], docs["next-baseline.json"]
        request = c.validate_request(docs["request.json"])
        ops.verify_next(base, candidate, docs["state.json"], terminal["output"]["sha256"], request)
        return terminal

def diagnose(request, job):
    from . import framing_ops
    request = framing_ops.validate(request)
    job = Path(job)
    c.clean(job.parent, True)
    job.mkdir(exist_ok=False)
    fs, _ = c.load_host()
    with fs.PathLocks([job]), ExitStack() as stack:
        manifest_sha, parents = _code_guards(stack)
        for item in [request["source"], *request["resources"]]:
            _guard(stack, Path(item["file"]), item["sha256"], parents=parents)
        request_desc = c.write_new(job / "request.json", request)
        _guard_descriptor(stack, request_desc, parents)
        observed = _worker(stack, job, "diagnose", manifest_sha, request_desc)
        report = observed["report"]
        _guard_descriptor(stack, report, parents)
        doc = c.load_descriptor(report)
        c.require(doc["source"] == request["source"] and doc["scene"] == request["scene"]
                  and set(doc["audits"]) == set(request["specs"]) and doc["source_saved"] is False,
                  "Framing report does not bind to the request")
        result = {"status": "DIAGNOSED", "job": str(job), "report": report,
                  "case_names": sorted(doc["audits"])}
        c.write_new(job / "DIAGNOSED.json", result)
        _progress(job, "DIAGNOSED")
        return result


def dispatch(action, params):
    keys = {"check": {"request", "job"}, "apply": {"job", "check_sha"}, "cancel": {"job", "check_sha"},
            "result": {"job", "terminal_sha"}, "diagnose": {"request", "job"}}
    c.require(action in keys and type(params) is dict and set(params) == keys[action], "Exact static action parameters required")
    if action == "check": return check(params["request"], params["job"])
    if action == "apply": return apply(params["job"], params["check_sha"])
    if action == "cancel": return cancel(params["job"], params["check_sha"])
    if action == "result": return verified_result(params["job"], params.get("terminal_sha"))
    if action == "diagnose": return diagnose(params["request"], params["job"])
    raise ValueError("Unknown static workflow action")
