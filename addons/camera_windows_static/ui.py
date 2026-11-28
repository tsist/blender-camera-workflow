"""Small Windows panel over the shared Static core; no scene is changed by CHECK/Create."""
import copy
import json
import os
from pathlib import Path
import subprocess
import threading
import uuid
import bpy
from bpy.props import EnumProperty, FloatProperty, FloatVectorProperty, IntProperty, IntVectorProperty, StringProperty
from . import common as c, service, operations as ops, framing_ops

_registered = []
_timer = None
_slot = {"status": "Idle", "process": None, "thread": None, "done": None, "action": None,
         "control": None, "job": None, "request": None, "ready": None, "terminal": None, "error": ""}
_items = []
_cut_items = []

_ERROR_LABELS = (
    ("A clean saved GUI scene", "请保存当前工程，再核验镜头副本"),
    ("Save the current scene", "请保存当前工程，再检查镜头"),
    ("Save the source", "请保存当前工程后继续"),
    ("Stop playback", "请暂停播放后继续"),
    ("Adjacent right shot", "请在镜头表中添加相邻的后一镜"),
    ("A saved adjacent shot", "请保存含相邻两镜的镜头表"),
    ("Saved shot sequence", "请保存含镜头表的工程"),
    ("Release the previous CHECK", "请先生成或取消上一次核验"),
    ("Dialog source/window changed", "工程或窗口已切换，请重新打开此面板"),
    ("Scene changed while", "对话框打开期间工程已改变，请重新载入参数"),
    ("Scene changed during", "场景已改变，请保存后重新核验"),
    ("Session changed during", "场景已改变，请保存后重新核验"),
    ("Saved source", "保存的源工程已改变，请重新核验"),
    ("Current scene differs", "当前场景与核验时不同，请重新核验"),
    ("CHECK belongs", "核验属于另一个窗口或场景"),
    ("A completed framing report", "请先完成构图诊断"),
    ("Specification belongs", "构图预设对应的是另一个工程或场景"),
    ("Case absent", "构图预设中没有当前诊断方案"),
    ("The suggestion needs", "构图建议需要唯一使用该相机的已保存镜头"),
    ("A Windows static operation", "另一个镜头核验任务还在运行"),
    ("Supervisor failed", "后台核验失败，请查看任务日志"),
    ("Verified result changed", "已核验副本发生变化，请重新核验"),
    ("Open failed", "无法打开已核验副本"),
)


def _display_problem(error):
    message = str(error)
    translated = next((label for prefix, label in _ERROR_LABELS if message.startswith(prefix)), None)
    if translated:
        return translated
    if any("\u4e00" <= char <= "\u9fff" for char in message):
        return message
    return "镜头核验未完成，请检查镜头表与当前工程，详情见任务记录"


def _names(self, context):
    return _items or [("NONE", "没有已保存的镜头", "")]

def _cut_names(self, context):
    return _cut_items or [("NONE", "没有相邻镜头", "")]

def _capture_cut(context, left, cut, name):
    c.require(not bpy.app.background and bpy.data.filepath and not bpy.data.is_dirty, "Save the current scene before CHECK")
    c.require(not context.screen.is_animation_playing, "Stop playback before CHECK")
    _, model, native = c.load_native()
    rows = native.preservation.rows_of(context.scene)
    index = [row["name"] for row in rows].index(left)
    c.require(index + 1 < len(rows), "Adjacent right shot required")
    request = {"version": 2, "source": c.descriptor(Path(bpy.data.filepath)), "scene": context.scene.name,
               "left": left, "right": rows[index + 1]["name"], "left_last": cut,
               "candidate_name": name, "session": None, "baseline": None}
    base = ops.baseline(bpy, native, request)
    doc = ops.candidate(model, base, request)
    state = c.canonical_state(native.state(bpy, context.scene))
    ops.expected(native, state, doc, request)
    c.require(not bpy.data.is_dirty, "Session changed during capture; save and recapture")
    request.update(session=state, baseline=base)
    return c.validate_request(request)

def _idle(): return _slot["process"] is None

def _capture(context, shot, lens, offset, name):
    c.require(not bpy.app.background and bpy.data.filepath and not bpy.data.is_dirty, "Save the current scene before CHECK")
    c.require(not context.screen.is_animation_playing, "Stop playback before CHECK")
    live, model, native = c.load_native()
    # Live is the sole owner of shot properties; the adapter never re-registers it.
    c.require(hasattr(bpy.types.Scene, "camera_live_shots"), "Enable the exact Camera Live 0.7.2 first")
    source = Path(bpy.data.filepath)
    source_sha = c.digest(source)
    baseline = native.baseline(bpy, source_sha, context.scene.name, shot)
    model.offset_variant(baseline, name, lens, list(offset))
    state = c.canonical_state(native.state(bpy, context.scene))
    c.require(not bpy.data.is_dirty, "Session changed during capture; save and recapture")
    return {"version": 1, "source": {"file": str(source), "sha256": source_sha},
            "scene": context.scene.name, "shot": shot, "lens": lens, "local_offset": list(offset),
            "candidate_name": name, "session": state, "baseline": baseline}

def _same_session(context, request):
    c.require(_slot.get("origin") == (context.window.as_pointer(), context.scene.as_pointer()), "CHECK belongs to another window or scene")
    c.require(bpy.data.filepath == request["source"]["file"] and not bpy.data.is_dirty, "Saved source/session changed; run a new CHECK")
    c.require(not context.screen.is_animation_playing, "Stop playback before proceeding")
    c.require(c.digest(Path(bpy.data.filepath)) == request["source"]["sha256"], "Saved source changed")
    _, _, native = c.load_native()
    if ops.is_production(request):
        from . import production_snapshot
        observed = production_snapshot.capture()
    else:
        observed = native.state(bpy, context.scene)
    c.require(c.canonical_state(observed) == request["session"], "Current scene differs from CHECK; recapture")

def _capture_dof(context, shot, focus_object, focus_subtarget, fstop, name):
    c.require(not bpy.app.background and bpy.data.filepath and not bpy.data.is_dirty, "Save the current scene before CHECK")
    c.require(not context.screen.is_animation_playing, "Stop playback before CHECK")
    _, model, native = c.load_native()
    request = {"version":3,"source":c.descriptor(Path(bpy.data.filepath)),"scene":context.scene.name,"shot":shot,
               "focus_object":focus_object,"focus_subtarget":focus_subtarget,"fstop":fstop,"candidate_name":name,"session":None,"baseline":None}
    c.validate_request(request)
    base=ops.baseline(bpy,native,request)
    doc=ops.candidate(model,base,request)
    state=c.canonical_state(native.state(bpy,context.scene))
    ops.expected(native,state,doc,request)
    c.require(not bpy.data.is_dirty,"Session changed during capture; save and recapture")
    request.update(session=state,baseline=base)
    return c.validate_request(request)

def _capture_motion(context, shot, easing, name):
    c.require(not bpy.app.background and bpy.data.filepath and not bpy.data.is_dirty, "Save the current scene before CHECK")
    c.require(not context.screen.is_animation_playing, "Stop playback before CHECK")
    _, model, native = c.load_native()
    request = {"version": 4, "source": c.descriptor(Path(bpy.data.filepath)), "scene": context.scene.name,
               "shot": shot, "easing": easing, "candidate_name": name, "session": None, "baseline": None}
    c.validate_request(request)
    base = ops.baseline(bpy, native, request)
    doc = ops.candidate(model, base, request)
    state = c.canonical_state(native.state(bpy, context.scene))
    ops.expected(native, state, doc, request)
    c.require(not bpy.data.is_dirty, "Session changed during capture; save and recapture")
    request.update(session=state, baseline=base)
    return c.validate_request(request)

def _capture_focus(context, shot, helper, new_start, locked_frames, name):
    c.require(not bpy.app.background and bpy.data.filepath and not bpy.data.is_dirty, "Save the current scene before CHECK")
    c.require(not context.screen.is_animation_playing, "Stop playback before CHECK")
    _, model, native = c.load_native()
    request = {"version": 5, "source": c.descriptor(Path(bpy.data.filepath)), "scene": context.scene.name,
               "shot": shot, "helper": helper, "new_start": new_start, "locked_frames": list(locked_frames),
               "candidate_name": name, "session": None, "baseline": None}
    c.validate_request(request)
    base = ops.baseline(bpy, native, request)
    doc = ops.candidate(model, base, request)
    state = c.canonical_state(native.state(bpy, context.scene))
    ops.expected(native, state, doc, request)
    c.require(not bpy.data.is_dirty, "Session changed during capture; save and recapture")
    request.update(session=state, baseline=base)
    return c.validate_request(request)

def _launch(action, params):
    global _timer
    c.require(_idle(), "A Windows static operation is already owned")
    manifest_sha, _, (_, blender, python) = c.verify_package()
    control = Path(params["job"]).parent / (".camera-control-" + uuid.uuid4().hex)
    control.mkdir()
    action_file = control / "action.json"
    c.write_new(action_file, {"action": action, "params": params, "manifest_sha": manifest_sha})
    nonce = uuid.uuid4().hex
    gate = control / "launch-gate.json"
    env = dict(os.environ, **{c.BLENDER_ENV: str(blender)})
    command = [str(python), "-I", "-B", str(c.ROOT / "entry.py"), str(action_file), c.digest(action_file), str(gate), nonce]
    _, processes = c.load_host()
    with (control / "supervisor.log").open("xb") as log:
        tree = processes.ProcessTree(command, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
    done = threading.Event()
    status = {"check": "Checking", "apply": "Creating verified copy", "diagnose": "Diagnosing saved framing"}
    _slot.update(status=status[action], process=tree, done=done,
                 action=action, control=str(control), error="", terminal=None)
    def wait_owned():
        try:
            code = tree.process.wait(timeout=900)
            _slot["returncode"] = code
        except BaseException as exc:
            tree.terminate()
            _slot["returncode"] = tree.process.returncode
            _slot["error"] = str(exc)
        finally:
            tree.close()
            done.set()
    thread = threading.Thread(target=wait_owned, daemon=True, name="camera-windows-owned-supervisor")
    _slot["thread"] = thread
    try:
        c.write_new(gate, {"nonce": nonce})
        thread.start()
    except BaseException as exc:
        tree.terminate()
        tree.close()
        _slot.update(process=None, status="Launch failed; child reaped", error=str(exc))
        raise
    if _timer is None:
        _timer = _observe
        bpy.app.timers.register(_timer, first_interval=0.2)

def _observe():
    global _timer
    done = _slot.get("done")
    if done is None or not done.is_set(): return 0.2
    _slot["process"] = None
    path = Path(_slot["control"]) / "result.json"
    try:
        c.require(_slot.get("returncode") == 0 and not _slot["error"], "Supervisor failed; inspect " + _slot["control"])
        result = c.read_json(path)
        if _slot["action"] == "check":
            c.require(result.get("status") == "READY" and result["job"] == _slot["job"], "CHECK result differs")
            c.load_descriptor(result["check"])
            _slot.update(ready=result, status="READY: review, then Create or Cancel")
        elif _slot["action"] == "diagnose":
            c.require(result["status"] == "DIAGNOSED" and result["job"] == _slot["job"], "Diagnosis result differs")
            doc = c.load_descriptor(result["report"])
            name = _slot["framing_case"]
            audit = doc["audits"][name]
            baseline_count = len(audit["baseline"]["issues"])
            remaining = len(audit["recommendation"]["validation"]["issues"])
            summary = f"检查出 {baseline_count} 项，调整后剩 {remaining} 项"
            if audit["conflict"]:
                summary += "，存在锁定冲突"
            elif audit["recommendation"]["improves"]:
                summary += "，可核验改进方案"
            _slot.update(diagnosis=result["report"], framing_summary=summary, status="Framing diagnosed")
        else:
            if result.get("status") == "CANCELLED":
                _slot.update(status="Cancelled; source retained", ready=None)
            else:
                verified = service.verified_result(_slot["job"], c.digest(Path(_slot["job"]) / "terminal.json"))
                c.require(result == verified, "Supervisor result differs from sealed terminal")
                _slot.update(terminal=verified, status="Verified copy ready", ready=None)
    except Exception as exc:
        _slot.update(error=str(exc), status="Failed; evidence retained", ready=None)
    _timer = None
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas: area.tag_redraw()
    return None


class CAMERA_WINDOWS_OT_diagnose(bpy.types.Operator):
    bl_idname = "camera_windows_static.diagnose"
    bl_label = "诊断已保存构图"
    spec_file: StringProperty(name="构图诊断预设", subtype="FILE_PATH")
    case_name: StringProperty(name="检查方案", default="search")
    job_parent: StringProperty(name="任务输出目录", subtype="DIR_PATH")

    @classmethod
    def poll(cls, context):
        return _idle() and _slot["ready"] is None and bool(bpy.data.filepath)

    def invoke(self, context, event):
        self.job_parent = str(Path(bpy.data.filepath).parent)
        return context.window_manager.invoke_props_dialog(self, width=560)

    def execute(self, context):
        try:
            c.require(self.poll(context) and not bpy.data.is_dirty and not context.screen.is_animation_playing,
                      "请保存工程并停止播放后再诊断")
            source = Path(bpy.data.filepath)
            if self.spec_file:
                request = c.read_json(bpy.path.abspath(self.spec_file))
            else:
                from .artist_ui import _camera

                scene = context.scene
                camera = _camera(context)
                settings = scene.camera_artist_ui
                target = settings.subject or context.active_object
                c.require(camera and target and target.type == "MESH" and target.name in scene.objects,
                          "请选择场景中的网格主体和相机")
                resources = {Path(bpy.path.abspath(image.filepath)).resolve()
                             for image in bpy.data.images if image.source == "FILE" and not image.packed_file}
                request = {
                    "source": c.descriptor(source), "scene": scene.name,
                    "specs": {self.case_name: {"camera": camera.name, "frames": [scene.frame_current],
                              "subjects": [{"name": "主体", "objects": [target.name]}]}},
                    "resources": [c.descriptor(path) for path in sorted(resources)],
                }
            request = framing_ops.validate(request)
            c.require(Path(request["source"]["file"]).resolve() == source.resolve()
                      and request["source"]["sha256"] == c.digest(source)
                      and request["scene"] == context.scene.name, "Specification belongs to a different saved scene")
            c.require(self.case_name in request["specs"], "Case absent from framing specification")
            job = c.clean(self.job_parent, True) / ("camera-framing-" + uuid.uuid4().hex[:12])
            _slot.update(job=str(job), diagnosis=None, framing_summary="", framing_case=self.case_name)
            _launch("diagnose", {"request": request, "job": str(job)})
            return {"FINISHED"}
        except Exception as exc:
            self.report({"ERROR"}, _display_problem(exc))
            return {"CANCELLED"}


class CAMERA_WINDOWS_OT_check_framing(bpy.types.Operator):
    bl_idname = "camera_windows_static.check_framing"
    bl_label = "核验构图建议"

    @classmethod
    def poll(cls, context):
        return _idle() and _slot["ready"] is None and bool(_slot.get("diagnosis"))

    def execute(self, context):
        try:
            c.require(self.poll(context), "A completed framing report is required")
            report = c.load_descriptor(_slot["diagnosis"])
            camera, lens, offset = framing_ops.suggestion_for_copy(report, _slot["framing_case"])
            _, _, native = c.load_native()
            rows = [row for row in native.preservation.rows_of(context.scene)
                    if row["camera"] == camera]
            c.require(len(rows) == 1, "The suggestion needs one saved shot using this camera")
            request = _capture(context, rows[0]["name"], lens, offset, "Framing suggestion")
            c.require(request["scene"] == report["scene"]
                      and Path(request["source"]["file"]).resolve() == Path(report["source"]["file"]).resolve()
                      and request["source"]["sha256"] == report["source"]["sha256"], "Saved scene changed since diagnosis")
            parent = Path(_slot["diagnosis"]["file"]).parent.parent
            job = c.clean(parent, True) / ("camera-static-" + uuid.uuid4().hex[:12])
            _slot.update(job=str(job), request=request, terminal=None,
                         origin=(context.window.as_pointer(), context.scene.as_pointer()))
            _launch("check", {"request": request, "job": str(job)})
            return {"FINISHED"}
        except Exception as exc:
            self.report({"ERROR"}, _display_problem(exc))
            return {"CANCELLED"}


class CAMERA_WINDOWS_OT_check(bpy.types.Operator):
    bl_idname = "camera_windows_static.check"
    bl_label = "检查静态机位"
    bl_options = {"REGISTER"}
    shot: EnumProperty(name="镜头", items=_names)
    lens: FloatProperty(name="焦距（毫米）", default=50.0, min=1.0, max=500.0)
    local_offset: FloatVectorProperty(name="机位偏移（右／上／后）", size=3, default=(0, 0, 0))
    candidate_name: StringProperty(name="候选方案", default="静态机位候选")
    job_parent: StringProperty(name="任务输出目录", subtype="DIR_PATH")

    @classmethod
    def poll(cls, context):
        return _idle() and _slot["ready"] is None and bool(bpy.data.filepath) and hasattr(context.scene, "camera_live_shots")

    def invoke(self, context, event):
        global _items
        if bpy.data.is_dirty:
            self.report({"ERROR"}, "请先保存当前工程")
            return {"CANCELLED"}
        _, _, native = c.load_native()
        self._origin = (context.window.as_pointer(), context.scene.as_pointer(), bpy.data.filepath, c.digest(Path(bpy.data.filepath)))
        self._origin_state = c.canonical_state(native.state(bpy, context.scene))
        _items = [(row.name, row.name, "相机：" + row.camera.name) for row in context.scene.camera_live_shots if row.camera]
        if not _items:
            self.report({"ERROR"}, "请先保存包含镜头表的工程")
            return {"CANCELLED"}
        self.shot = "B_Responds" if any(row[0] == "B_Responds" for row in _items) else _items[0][0]
        self.lens = next(row.camera.data.lens for row in context.scene.camera_live_shots if row.name == self.shot)
        self.job_parent = str(Path(bpy.data.filepath).parent)
        return context.window_manager.invoke_props_dialog(self, width=560)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "shot")
        layout.prop(self, "lens")
        layout.prop(self, "local_offset")
        layout.prop(self, "candidate_name")
        layout.prop(self, "job_parent")
        layout.label(text="静态机位会影响这台相机覆盖的所有帧。")
        layout.label(text="检查读取已保存场景，生成后将另存副本。")
        layout.label(text="动画、共享相机及景深目标均会经过核验。")

    def execute(self, context):
        try:
            c.require(_idle() and _slot["ready"] is None, "Release the previous CHECK first")
            if hasattr(self, "_origin"):
                current = (context.window.as_pointer(), context.scene.as_pointer(), bpy.data.filepath, c.digest(Path(bpy.data.filepath)))
                c.require(current == self._origin, "Dialog source/window changed; reopen the dialog")
                _, _, native = c.load_native()
                c.require(c.canonical_state(native.state(bpy, context.scene)) == self._origin_state, "Scene changed while the dialog was open")
            request = _capture(context, self.shot, self.lens, self.local_offset, self.candidate_name)
            parent = c.clean(self.job_parent, True)
            job = parent / ("camera-static-" + uuid.uuid4().hex[:12])
            _slot.update(job=str(job), request=request, terminal=None, origin=(context.window.as_pointer(), context.scene.as_pointer()))
            _launch("check", {"request": request, "job": str(job)})
            return {"FINISHED"}
        except Exception as exc:
            self.report({"ERROR"}, _display_problem(exc))
            return {"CANCELLED"}

class CAMERA_WINDOWS_OT_cut_check(bpy.types.Operator):
    bl_idname = "camera_windows_static.cut_check"
    bl_label = "检查相邻切点"
    bl_options = {"REGISTER"}
    left: EnumProperty(name="前一镜头", items=_cut_names)
    left_last: IntProperty(name="前一镜头结束帧", default=108)
    candidate_name: StringProperty(name="候选方案", default="相邻切点候选")
    job_parent: StringProperty(name="任务输出目录", subtype="DIR_PATH")

    @classmethod
    def poll(cls, context):
        return _idle() and _slot["ready"] is None and bool(bpy.data.filepath) and hasattr(context.scene, "camera_live_shots")

    def invoke(self, context, event):
        global _cut_items
        try:
            c.require(not bpy.data.is_dirty, "请先保存当前工程")
            _, _, native = c.load_native()
            self._origin = (context.window.as_pointer(), context.scene.as_pointer(), bpy.data.filepath, c.digest(Path(bpy.data.filepath)))
            self._origin_state = c.canonical_state(native.state(bpy, context.scene))
            rows = list(context.scene.camera_live_shots)
            _cut_items = [(row.name, row.name + " -> " + rows[i + 1].name, "") for i, row in enumerate(rows[:-1])]
            c.require(bool(_cut_items), "A saved adjacent shot pair is required")
            self.left = "A_Signals" if any(row[0] == "A_Signals" for row in _cut_items) else _cut_items[0][0]
            self.left_last = next(row.last for row in rows if row.name == self.left)
            self.job_parent = str(Path(bpy.data.filepath).parent)
            return context.window_manager.invoke_props_dialog(self, width=560)
        except Exception as exc:
            self.report({"ERROR"}, _display_problem(exc))
            return {"CANCELLED"}

    def draw(self, context):
        layout = self.layout
        for field in ("left", "left_last", "candidate_name", "job_parent"): layout.prop(self, field)
        layout.label(text="下一镜头从紧接的一帧开始。")
        layout.label(text="仅调整所选切点。")
        layout.label(text="检查通过后可另存核验副本。")

    def execute(self, context):
        try:
            c.require(_idle() and _slot["ready"] is None, "Release the previous CHECK first")
            if hasattr(self, "_origin"):
                current = (context.window.as_pointer(), context.scene.as_pointer(), bpy.data.filepath, c.digest(Path(bpy.data.filepath)))
                c.require(current == self._origin, "Dialog source/window changed; reopen the dialog")
                _, _, native = c.load_native()
                c.require(c.canonical_state(native.state(bpy, context.scene)) == self._origin_state, "Scene changed while the dialog was open")
            request = _capture_cut(context, self.left, self.left_last, self.candidate_name)
            parent = c.clean(self.job_parent, True)
            job = parent / ("camera-cut-" + uuid.uuid4().hex[:12])
            _slot.update(job=str(job), request=request, terminal=None, origin=(context.window.as_pointer(), context.scene.as_pointer()))
            _launch("check", {"request": request, "job": str(job)})
            return {"FINISHED"}
        except Exception as exc:
            self.report({"ERROR"}, _display_problem(exc))
            return {"CANCELLED"}

class CAMERA_WINDOWS_OT_dof_check(bpy.types.Operator):
    bl_idname = "camera_windows_static.dof_check"
    bl_label = "检查骨骼对焦"
    bl_options = {"REGISTER"}
    shot: EnumProperty(name="镜头",items=_names)
    focus_object: StringProperty(name="目标骨架",default="M3.B.Rig")
    focus_subtarget: StringProperty(name="目标骨骼",default="head")
    fstop: FloatProperty(name="光圈",default=1.4,min=0.7,max=64.0)
    candidate_name: StringProperty(name="候选方案",default="浅景深候选")
    job_parent: StringProperty(name="任务输出目录",subtype="DIR_PATH")

    @classmethod
    def poll(cls,context):
        return _idle() and _slot["ready"] is None and bool(bpy.data.filepath) and hasattr(context.scene,"camera_live_shots")

    def invoke(self,context,event):
        global _items
        try:
            c.require(not bpy.data.is_dirty,"请先保存当前工程")
            _,_,native=c.load_native()
            self._origin=(context.window.as_pointer(),context.scene.as_pointer(),bpy.data.filepath,c.digest(Path(bpy.data.filepath)))
            self._origin_state=c.canonical_state(native.state(bpy,context.scene))
            _items=[(row.name,row.name,"相机："+row.camera.name) for row in context.scene.camera_live_shots if row.camera]
            c.require(bool(_items),"Saved shot sequence required")
            self.shot="B_Responds" if any(row[0]=="B_Responds" for row in _items) else _items[0][0]
            self.job_parent=str(Path(bpy.data.filepath).parent)
            return context.window_manager.invoke_props_dialog(self,width=560)
        except Exception as exc:
            self.report({"ERROR"}, _display_problem(exc));return {"CANCELLED"}

    def draw(self,context):
        for field in ("shot","focus_object","focus_subtarget","fstop","candidate_name","job_parent"):self.layout.prop(self,field)
        self.layout.label(text="将现有骨架的指定骨骼设为焦点。")
        self.layout.label(text="检查通过后可另存核验副本。")

    def execute(self,context):
        try:
            c.require(_idle() and _slot["ready"] is None,"Release the previous CHECK first")
            if hasattr(self,"_origin"):
                current=(context.window.as_pointer(),context.scene.as_pointer(),bpy.data.filepath,c.digest(Path(bpy.data.filepath)))
                c.require(current==self._origin,"Dialog source/window changed; reopen the dialog")
                _,_,native=c.load_native()
                c.require(c.canonical_state(native.state(bpy,context.scene))==self._origin_state,"Scene changed while the dialog was open")
            request=_capture_dof(context,self.shot,self.focus_object,self.focus_subtarget,self.fstop,self.candidate_name)
            parent=c.clean(self.job_parent,True);job=parent/("camera-dof-"+uuid.uuid4().hex[:12])
            _slot.update(job=str(job),request=request,terminal=None,origin=(context.window.as_pointer(),context.scene.as_pointer()))
            _launch("check",{"request":request,"job":str(job)})
            return {"FINISHED"}
        except Exception as exc:
            self.report({"ERROR"}, _display_problem(exc));return {"CANCELLED"}

class CAMERA_WINDOWS_OT_motion_check(bpy.types.Operator):
    bl_idname = "camera_windows_static.motion_check"
    bl_label = "检查运镜节奏"
    bl_options = {"REGISTER"}
    shot: EnumProperty(name="镜头", items=_names)
    easing: EnumProperty(name="运镜时间", items=[
        ("EASE_OUT", "缓出", "起步后逐渐减速停下"),
        ("EASE_IN_OUT", "缓入缓出", "逐渐启动，再减速停下"),
        ("EASE_IN", "缓入", "平缓起步，结束时仍保持运动")], default="EASE_OUT")
    candidate_name: StringProperty(name="候选方案", default="运镜节奏候选")
    job_parent: StringProperty(name="任务输出目录", subtype="DIR_PATH")

    @classmethod
    def poll(cls, context):
        return _idle() and _slot["ready"] is None and bool(bpy.data.filepath) and hasattr(context.scene, "camera_live_shots")

    def invoke(self, context, event):
        global _items
        try:
            c.require(not bpy.data.is_dirty, "请先保存当前工程")
            _, _, native = c.load_native()
            self._origin = (context.window.as_pointer(), context.scene.as_pointer(), bpy.data.filepath, c.digest(Path(bpy.data.filepath)))
            self._origin_state = c.canonical_state(native.state(bpy, context.scene))
            _items = [(row.name, row.name, "相机：" + row.camera.name) for row in context.scene.camera_live_shots if row.camera]
            c.require(bool(_items), "Saved shot sequence required")
            self.shot = "Resolve" if any(row[0] == "Resolve" for row in _items) else _items[0][0]
            self.job_parent = str(Path(bpy.data.filepath).parent)
            return context.window_manager.invoke_props_dialog(self, width=560)
        except Exception as exc:
            self.report({"ERROR"}, _display_problem(exc))
            return {"CANCELLED"}

    def draw(self, context):
        for field in ("shot", "easing", "candidate_name", "job_parent"):
            self.layout.prop(self, field)
        self.layout.label(text="沿用现有起止帧与位置。")
        self.layout.label(text="支持双关键帧相机的节奏调整。")
        self.layout.label(text="检查通过后可另存核验副本。")

    def execute(self, context):
        try:
            c.require(_idle() and _slot["ready"] is None, "Release the previous CHECK first")
            if hasattr(self, "_origin"):
                current = (context.window.as_pointer(), context.scene.as_pointer(), bpy.data.filepath, c.digest(Path(bpy.data.filepath)))
                c.require(current == self._origin, "Dialog source/window changed; reopen the dialog")
                _, _, native = c.load_native()
                c.require(c.canonical_state(native.state(bpy, context.scene)) == self._origin_state, "Scene changed while the dialog was open")
            request = _capture_motion(context, self.shot, self.easing, self.candidate_name)
            parent = c.clean(self.job_parent, True)
            job = parent / ("camera-motion-" + uuid.uuid4().hex[:12])
            _slot.update(job=str(job), request=request, terminal=None, origin=(context.window.as_pointer(), context.scene.as_pointer()))
            _launch("check", {"request": request, "job": str(job)})
            return {"FINISHED"}
        except Exception as exc:
            self.report({"ERROR"}, _display_problem(exc))
            return {"CANCELLED"}

class CAMERA_WINDOWS_OT_focus_check(bpy.types.Operator):
    bl_idname = "camera_windows_static.focus_check"
    bl_label = "检查焦点转移"
    bl_options = {"REGISTER"}
    shot: EnumProperty(name="镜头", items=_names)
    helper: StringProperty(name="已有对焦控制器", default="M3.A.FocusHelper")
    new_start: IntProperty(name="转移开始帧", default=83)
    locked_frames: IntVectorProperty(name="锁定起点／到达／终点帧", size=3, default=(73, 97, 108))
    candidate_name: StringProperty(name="候选方案", default="焦点转移候选")
    job_parent: StringProperty(name="任务输出目录", subtype="DIR_PATH")

    @classmethod
    def poll(cls, context):
        return _idle() and _slot["ready"] is None and bool(bpy.data.filepath) and hasattr(context.scene, "camera_live_shots")

    def invoke(self, context, event):
        global _items
        try:
            c.require(not bpy.data.is_dirty, "请先保存当前工程")
            _, _, native = c.load_native()
            self._origin = (context.window.as_pointer(), context.scene.as_pointer(), bpy.data.filepath, c.digest(Path(bpy.data.filepath)))
            self._origin_state = c.canonical_state(native.state(bpy, context.scene))
            _items = [(row.name, row.name, "相机：" + row.camera.name) for row in context.scene.camera_live_shots if row.camera]
            c.require(bool(_items), "Saved shot sequence required")
            self.shot = "A_Signals" if any(row[0] == "A_Signals" for row in _items) else _items[0][0]
            self.job_parent = str(Path(bpy.data.filepath).parent)
            return context.window_manager.invoke_props_dialog(self, width=580)
        except Exception as exc:
            self.report({"ERROR"}, _display_problem(exc))
            return {"CANCELLED"}

    def draw(self, context):
        for field in ("shot", "helper", "new_start", "locked_frames", "candidate_name", "job_parent"):
            self.layout.prop(self, field)
        self.layout.label(text="只调整已有的焦点转移开始帧。")
        self.layout.label(text="沿用现有到达帧、外围关键帧与光学设置。")
        self.layout.label(text="检查通过后可另存核验副本。")

    def execute(self, context):
        try:
            c.require(_idle() and _slot["ready"] is None, "Release the previous CHECK first")
            if hasattr(self, "_origin"):
                current = (context.window.as_pointer(), context.scene.as_pointer(), bpy.data.filepath, c.digest(Path(bpy.data.filepath)))
                c.require(current == self._origin, "Dialog source/window changed; reopen the dialog")
                _, _, native = c.load_native()
                c.require(c.canonical_state(native.state(bpy, context.scene)) == self._origin_state, "Scene changed while the dialog was open")
            request = _capture_focus(context, self.shot, self.helper, self.new_start, self.locked_frames, self.candidate_name)
            parent = c.clean(self.job_parent, True)
            job = parent / ("camera-focus-" + uuid.uuid4().hex[:12])
            _slot.update(job=str(job), request=request, terminal=None, origin=(context.window.as_pointer(), context.scene.as_pointer()))
            _launch("check", {"request": request, "job": str(job)})
            return {"FINISHED"}
        except Exception as exc:
            self.report({"ERROR"}, _display_problem(exc))
            return {"CANCELLED"}

class CAMERA_WINDOWS_OT_production_check(bpy.types.Operator):
    bl_idname = "camera_windows_static.production_check"
    bl_label = "检查相机组改时"
    bl_options = {"REGISTER"}
    collection: StringProperty(name="相机集合")
    action_names: StringProperty(name="动作（逗号分隔）")
    marker_names: StringProperty(name="相机标记（逗号分隔）")
    source_start: IntProperty(name="原始开始帧", default=1)
    source_end: IntProperty(name="原始结束边界", default=289)
    target_start: IntProperty(name="新开始帧", default=1)
    target_end: IntProperty(name="新结束边界", default=361)
    locked_frames: StringProperty(name="锁定帧", default="1")
    candidate_name: StringProperty(name="候选方案", default="相机组改时候选")
    job_parent: StringProperty(name="任务输出目录", subtype="DIR_PATH")

    @classmethod
    def poll(cls, context):
        return _idle() and _slot["ready"] is None and bool(bpy.data.filepath)

    def invoke(self, context, event):
        try:
            from . import production_snapshot
            c.require(not bpy.data.is_dirty and not context.screen.is_animation_playing,
                      "Save the source and stop playback before CHECK")
            self._origin = (context.window.as_pointer(), context.scene.as_pointer(),
                            bpy.data.filepath, c.digest(Path(bpy.data.filepath)))
            self._origin_state = c.canonical_state(production_snapshot.capture())
            camera = context.scene.camera
            if camera and len(camera.users_collection) == 1:
                group = camera.users_collection[0]
                self.collection = group.name
                names = set()
                for obj in group.all_objects:
                    for owner in (obj, obj.data):
                        animation = getattr(owner, "animation_data", None)
                        if animation and animation.action:
                            names.add(animation.action.name)
                self.action_names = ", ".join(sorted(names))
                members = set(group.all_objects)
                self.marker_names = ", ".join(m.name for m in context.scene.timeline_markers
                                               if m.camera in members)
            self.source_start = self.target_start = context.scene.frame_start
            self.source_end = context.scene.frame_end + 1
            self.target_end = self.target_start + round((self.source_end-self.source_start)*1.25)
            self.locked_frames = str(self.source_start)
            self.job_parent = str(Path(bpy.data.filepath).parent)
            return context.window_manager.invoke_props_dialog(self, width=620)
        except Exception as exc:
            self.report({"ERROR"}, _display_problem(exc))
            return {"CANCELLED"}

    def draw(self, context):
        for field in ("collection", "action_names", "marker_names", "source_start", "source_end",
                      "target_start", "target_end", "locked_frames", "candidate_name", "job_parent"):
            self.layout.prop(self, field)
        self.layout.label(text="在副本中调整指定相机动作和时间线标记。")
        self.layout.label(text="角色表演沿用现有场景时间。")

    def execute(self, context):
        try:
            from . import production_snapshot
            c.require(_idle() and _slot["ready"] is None, "Release the previous CHECK first")
            c.require(not bpy.app.background and bpy.data.filepath and not bpy.data.is_dirty,
                      "A clean saved GUI scene is required")
            c.require(not context.screen.is_animation_playing, "Stop playback before CHECK")
            current = (context.window.as_pointer(), context.scene.as_pointer(),
                       bpy.data.filepath, c.digest(Path(bpy.data.filepath)))
            state = c.canonical_state(production_snapshot.capture())
            if hasattr(self, "_origin"):
                c.require(current == self._origin and state == self._origin_state,
                          "Dialog source or scene changed; reopen the dialog")
            names = lambda value: [x.strip() for x in value.split(",") if x.strip()]
            resources = production_snapshot.resources(state["images"])
            request = c.validate_request({"version": 6, "source": c.descriptor(Path(bpy.data.filepath)),
                "scene": context.scene.name, "candidate_name": self.candidate_name,
                "session": state, "baseline": None, "resources": resources,
                "operation": {"kind": "retime_camera_group", "collection": self.collection,
                    "actions": names(self.action_names), "markers": names(self.marker_names),
                    "source_interval": [self.source_start, self.source_end],
                    "target_interval": [self.target_start, self.target_end],
                    "locked_frames": [int(x) for x in names(self.locked_frames)]}})
            c.require(not bpy.data.is_dirty, "Scene changed during capture; save and recapture")
            parent = c.clean(self.job_parent, True)
            job = parent / ("camera-production-" + uuid.uuid4().hex[:12])
            _slot.update(job=str(job), request=request, terminal=None,
                         origin=(context.window.as_pointer(), context.scene.as_pointer()))
            _launch("check", {"request": request, "job": str(job)})
            return {"FINISHED"}
        except Exception as exc:
            self.report({"ERROR"}, _display_problem(exc))
            return {"CANCELLED"}


class CAMERA_WINDOWS_OT_create(bpy.types.Operator):
    bl_idname = "camera_windows_static.create"
    bl_label = "生成核验副本"
    @classmethod
    def poll(cls, context): return _idle() and _slot["ready"] is not None
    def execute(self, context):
        try:
            _same_session(context, _slot["request"])
            ready = _slot["ready"]
            _launch("apply", {"job": ready["job"], "check_sha": ready["check"]["sha256"]})
            return {"FINISHED"}
        except Exception as exc:
            self.report({"ERROR"}, _display_problem(exc))
            return {"CANCELLED"}

class CAMERA_WINDOWS_OT_cancel(bpy.types.Operator):
    bl_idname = "camera_windows_static.cancel"
    bl_label = "取消核验"
    @classmethod
    def poll(cls, context): return _slot["ready"] is not None
    def execute(self, context):
        try:
            ready = _slot["ready"]
            result = service.cancel(ready["job"], ready["check"]["sha256"])
            if _idle(): _slot.update(ready=None, status="CHECK released; start a new request")
            else: _slot["status"] = "Cancellation requested" if result["accepted"] else "Commit already won; awaiting final verification"
            return {"FINISHED"}
        except Exception as exc:
            self.report({"ERROR"}, _display_problem(exc))
            return {"CANCELLED"}

class CAMERA_WINDOWS_OT_open(bpy.types.Operator):
    bl_idname = "camera_windows_static.open_verified"
    bl_label = "打开核验副本"
    @classmethod
    def poll(cls, context): return _idle() and _slot["terminal"] is not None
    def invoke(self, context, event): return context.window_manager.invoke_confirm(self, event)
    def execute(self, context):
        try:
            _same_session(context, _slot["request"])
            terminal_path = Path(_slot["job"]) / "terminal.json"
            result = service.verified_result(_slot["job"], c.digest(terminal_path))
            c.require(result == _slot["terminal"], "Verified result changed")
            c.require(bpy.ops.wm.open_mainfile(filepath=result["output"]["file"], load_ui=False, use_scripts=False) == {"FINISHED"}, "Open failed")
            _slot.update(status="Opened verified copy; native edits may be saved and recaptured", terminal=None, request=None)
            return {"FINISHED"}
        except Exception as exc:
            self.report({"ERROR"}, _display_problem(exc))
            return {"CANCELLED"}

def draw_copy_controls(layout, context):
    from .artist_ui import _ICONS, status_banner

    layout.operator("camera_windows_static.check", text="检查静态机位")
    layout.operator("camera_windows_static.cut_check", text="检查相邻切点")
    layout.operator("camera_windows_static.focus_check", text="检查焦点转移")
    layout.operator("camera_windows_static.production_check", text="检查相机组改时")
    layout.operator("camera_windows_static.diagnose", text="诊断已保存的构图")
    if _slot.get("framing_summary"):
        layout.label(text=_slot["framing_summary"])
        layout.operator("camera_windows_static.check_framing", text="核验构图建议")
    row = layout.row(align=True)
    row.operator("camera_windows_static.create", text="生成副本")
    row.operator("camera_windows_static.cancel", text="取消核验")
    layout.operator("camera_windows_static.open_verified", text="打开已核验副本")
    if _slot["job"]:
        layout.label(text="任务 " + Path(_slot["job"]).name)
    if _slot.get("process"):
        status_banner(layout, context, "正在后台核验镜头副本", kind="RUNNING", icon_pack=_ICONS)
    elif _slot.get("ready"):
        status_banner(layout, context, "检查通过，可以生成副本", kind="OK", icon_pack=_ICONS)
    elif _slot.get("terminal"):
        status_banner(layout, context, "副本已就绪", kind="OK", icon_pack=_ICONS)
    if _slot["error"]:
        status_banner(layout, context, _display_problem(_slot["error"]), kind="ERROR", icon_pack=_ICONS)

CLASSES = (CAMERA_WINDOWS_OT_check, CAMERA_WINDOWS_OT_cut_check, CAMERA_WINDOWS_OT_dof_check, CAMERA_WINDOWS_OT_motion_check,
           CAMERA_WINDOWS_OT_focus_check, CAMERA_WINDOWS_OT_production_check, CAMERA_WINDOWS_OT_diagnose,
           CAMERA_WINDOWS_OT_check_framing, CAMERA_WINDOWS_OT_create, CAMERA_WINDOWS_OT_cancel,
           CAMERA_WINDOWS_OT_open)

def register():
    c.require(not _registered, "Windows static adapter already registered")
    c.verify_package()
    c.load_native()
    for cls in CLASSES:
        bpy.utils.register_class(cls)
        _registered.append(cls)

def unregister():
    c.require(_idle(), "Wait for the owned static operation before disabling this candidate adapter")
    for cls in reversed(_registered): bpy.utils.unregister_class(cls)
    _registered.clear()
