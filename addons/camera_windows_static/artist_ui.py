# SPDX-License-Identifier: GPL-3.0-or-later
"""镜头表、现场构图及程序运镜的侧栏入口。"""

import bpy
from bpy.props import EnumProperty, FloatProperty, IntProperty, PointerProperty, StringProperty
from mathutils import Vector

from . import common, shot_motion
from ._ui_kit import (
    IconPack, SidebarDock, apply_collection_theme, draw_brand_header,
    ensure_object_mode, get_theme, primary_button, prop_column, section_panel, status_banner,
)

DOMAIN = "camera"
THEME = get_theme(DOMAIN)
_ICONS = IconPack(DOMAIN)
_PROPERTY = "camera_artist_ui"
_COLLECTION = "镜头工作台"


def _shot(scene, index):
    shots = scene.camera_live_shots
    return shots[index] if 0 <= index < len(shots) else None


def _camera(context):
    shot = _shot(context.scene, getattr(context.scene, _PROPERTY).shot_index)
    return (shot.camera if shot else None) or context.scene.camera


def _camera_only(_settings, obj):
    return obj.type == "CAMERA"


def _place_camera(scene, camera):
    collection = next((col for col in scene.collection.children if col.get("camera_workflow_owner")), None)
    if collection is None:
        collection = bpy.data.collections.new(_COLLECTION)
        collection["camera_workflow_owner"] = True
        scene.collection.children.link(collection)
    apply_collection_theme(collection, DOMAIN)
    collection.objects.link(camera)
    if camera.name in scene.collection.objects:
        scene.collection.objects.unlink(camera)


def _show_camera(context, camera):
    if context.area and context.area.type == "VIEW_3D":
        space = context.space_data
        if space.use_local_camera:
            space.camera = camera
        space.region_3d.view_perspective = "CAMERA"


class CAMERA_WINDOWS_PG_artist(bpy.types.PropertyGroup):
    shot_index: IntProperty(default=0, min=0)
    subject: PointerProperty(name="跟拍目标", type=bpy.types.Object)
    comparison_camera: PointerProperty(name="候选机位", type=bpy.types.Object, poll=_camera_only)
    motion: EnumProperty(name="运镜", items=(
        ("dolly", "推近", "相机沿视线向前移动"),
        ("pull", "拉远", "相机沿视线向后移动"),
        ("crane", "升降", "沿世界 Z 轴抬升相机"),
        ("slide", "横移", "沿相机局部右轴平移"),
        ("orbit", "环绕", "绕目标旋转并保持对焦"),
    ))
    distance: FloatProperty(name="位移", default=2.0, min=0.01, soft_max=10.0, subtype="DISTANCE")
    last_report: StringProperty()
    last_report_kind: StringProperty(default="INFO")


class CAMERA_WINDOWS_UL_shots(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index=0):
        row = layout.row(align=True)
        row.label(text=item.name, icon="CAMERA_DATA")
        row.label(text=f"{item.first}–{item.last}")


class CAMERA_WINDOWS_OT_shot(bpy.types.Operator):
    bl_idname = "camera_windows_static.artist_shot"
    bl_label = "编辑镜头"
    bl_options = {"REGISTER", "UNDO"}

    action: EnumProperty(items=(
        ("ADD", "添加镜头", ""),
        ("REMOVE", "移除镜头", ""),
        ("VIEW", "切入机位", ""),
    ))

    def execute(self, context):
        scene = context.scene
        settings = getattr(scene, _PROPERTY)
        shots = scene.camera_live_shots
        shot = _shot(scene, settings.shot_index)
        if self.action == "ADD":
            if bpy.ops.camera_live_rebuilt.add_shot() != {"FINISHED"}:
                return {"CANCELLED"}
            settings.shot_index = len(shots) - 1
            shot = shots[settings.shot_index]
            used = {item.name for item in shots if item != shot}
            number = 1
            while f"镜头 {number:02d}" in used:
                number += 1
            shot.name = f"镜头 {number:02d}"
        elif self.action == "REMOVE":
            if shot is None or bpy.ops.camera_live_rebuilt.remove_shot(index=settings.shot_index) != {"FINISHED"}:
                return {"CANCELLED"}
            settings.shot_index = max(0, min(settings.shot_index, len(shots) - 1))
        else:
            if shot is None or shot.camera is None:
                self.report({"WARNING"}, "请为镜头选择相机")
                return {"CANCELLED"}
            scene.frame_set(shot.first)
            scene.camera = shot.camera
            _show_camera(context, shot.camera)
        return {"FINISHED"}


class CAMERA_WINDOWS_OT_lens(bpy.types.Operator):
    bl_idname = "camera_windows_static.artist_lens"
    bl_label = "设置焦段"
    bl_options = {"REGISTER", "UNDO"}

    lens: FloatProperty(name="焦距（毫米）", min=1.0, max=500.0)

    def execute(self, context):
        camera = _camera(context)
        if camera is None or camera.data.type != "PERSP" or camera.library:
            return {"CANCELLED"}
        if camera.data.users > 1 or camera.data.library:
            camera.data = camera.data.copy()
        camera.data.lens = self.lens
        return {"FINISHED"}


class CAMERA_WINDOWS_OT_motion(bpy.types.Operator):
    bl_idname = "camera_windows_static.artist_motion"
    bl_label = "创建候选机位"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        settings = getattr(scene, _PROPERTY)
        shot = _shot(scene, settings.shot_index)
        target = settings.subject
        source = _camera(context)
        if target is None or target.name not in scene.objects:
            self.report({"WARNING"}, "请选择当前场景中的跟拍目标")
            return {"CANCELLED"}
        first, last = (shot.first, shot.last) if shot else (scene.frame_start, scene.frame_end)
        if last <= first:
            self.report({"WARNING"}, "运镜范围至少需要两帧")
            return {"CANCELLED"}
        center = target.matrix_world.translation
        start = source.matrix_world.translation.copy() if source else center + Vector((4, -7, 3))
        direction = center - start
        if direction.length < 1e-6:
            self.report({"WARNING"}, "相机与跟拍目标重合")
            return {"CANCELLED"}
        name = f"{shot.name if shot else '镜头'} · 候选"
        unique = name
        number = 2
        while unique in bpy.data.objects:
            unique = f"{name} {number:02d}"
            number += 1
        distance = settings.distance
        right = source.matrix_world.to_quaternion() @ Vector((1, 0, 0)) if source else Vector((1, 0, 0))
        offset = {
            "dolly": direction.normalized() * min(distance, direction.length * 0.8),
            "pull": -direction.normalized() * distance,
            "crane": Vector((0, 0, distance)),
            "slide": right * distance,
            "orbit": Vector((0, 0, 0)),
        }[settings.motion]
        with ensure_object_mode(context):
            camera = shot_motion.generate(scene, {
                "name": unique, "frames": (first, last), "target": target.name,
                "motion": settings.motion if settings.motion in {"crane", "orbit"} else "dolly",
                "start": start, "end": start + offset, "angle_deg": 45.0,
                "lens": source.data.lens if source else 50.0,
            })
            _place_camera(scene, camera)
        settings.comparison_camera = camera
        settings.last_report = f"已创建 {camera.name}，可播放并对比原机位"
        settings.last_report_kind = "OK"
        return {"FINISHED"}


class CAMERA_WINDOWS_OT_compare_view(bpy.types.Operator):
    bl_idname = "camera_windows_static.artist_compare_view"
    bl_label = "对比相机机位"

    candidate: bpy.props.BoolProperty(default=False)

    def execute(self, context):
        settings = getattr(context.scene, _PROPERTY)
        camera = settings.comparison_camera if self.candidate else _camera(context)
        if not context.area or context.area.type != "VIEW_3D" or camera is None:
            return {"CANCELLED"}
        space = context.space_data
        space.use_local_camera = True
        space.camera = camera
        space.region_3d.view_perspective = "CAMERA"
        return {"FINISHED"}


class CAMERA_WINDOWS_PT_artist(bpy.types.Panel):
    bl_label = ""
    bl_space_type = THEME.editor_space
    bl_region_type = "UI"
    bl_category = THEME.tab_label
    bl_options = {"HEADER_LAYOUT_EXPAND"}

    def draw_header(self, context):
        draw_brand_header(self.layout, DOMAIN, _ICONS, fallback_icon="CAMERA_DATA")

    def draw(self, context):
        from . import ui

        layout = self.layout
        scene = context.scene
        settings = getattr(scene, _PROPERTY)
        shot = _shot(scene, settings.shot_index)
        layout.template_list("CAMERA_WINDOWS_UL_shots", "", scene, "camera_live_shots",
                             settings, "shot_index", rows=3)
        row = layout.row(align=True)
        row.operator("camera_windows_static.artist_shot", text="添加镜头", icon="ADD").action = "ADD"
        row.operator("camera_windows_static.artist_shot", text="", icon="REMOVE").action = "REMOVE"
        if shot:
            props = prop_column(layout)
            props.prop(shot, "name", text="镜头名")
            props.prop(shot, "camera", text="相机")
            frames = layout.row(align=True)
            frames.prop(shot, "first", text="起始帧")
            frames.prop(shot, "last", text="结束帧")
            primary_button(layout, "camera_windows_static.artist_shot", "切入镜头机位",
                           icon_value=_ICONS.action_id("shot_table"), enabled=bool(shot.camera)).action = "VIEW"
        else:
            prop_column(layout).prop(scene, "camera", text="场景相机")
        camera = _camera(context)
        if camera and camera.data:
            data = camera.data
            layout.label(text="焦段与构图", icon_value=_ICONS.action_id("framing_guides"))
            row = layout.row(align=True)
            row.enabled = data.type == "PERSP" and not camera.library
            for focal in (24, 35, 50, 85):
                row.operator("camera_windows_static.artist_lens", text=f"{focal} mm",
                             depress=abs(data.lens - focal) < 0.01).lens = focal
            row = layout.row(align=True)
            row.enabled = data.users == 1 and data.library is None
            row.prop(data, "show_composition_thirds", text="三分线", toggle=True)
            row.prop(data, "show_safe_areas", text="安全框", toggle=True)

        _, body = section_panel(layout, "cw_focus", "景深与焦点追踪",
                                icon_value=_ICONS.action_id("focus_dof"), default_closed=True)
        if body is not None:
            if camera:
                col = prop_column(body)
                col.enabled = camera.data.users == 1 and camera.data.library is None
                dof = camera.data.dof
                col.prop(dof, "use_dof", text="启用景深")
                col.prop(dof, "focus_object", text="焦点对象")
                if dof.focus_object is None:
                    col.prop(dof, "focus_distance", text="焦点距离")
                col.prop(dof, "aperture_fstop", text="光圈")
            body.operator("camera_windows_static.dof_check")
        _, body = section_panel(layout, "cw_motion", "程序运镜与预演",
                                icon_value=_ICONS.action_id("proc_motion"), default_closed=True)
        if body is not None:
            col = prop_column(body)
            col.prop(settings, "subject")
            col.prop(settings, "motion")
            if settings.motion != "orbit":
                col.prop(settings, "distance")
            body.operator("camera_windows_static.artist_motion", icon="CAMERA_DATA")
            col.prop(settings, "comparison_camera")
            if camera and settings.comparison_camera:
                compare = body.row(align=True)
                compare.operator("camera_windows_static.artist_compare_view", text="A · 原机位").candidate = False
                compare.operator("camera_windows_static.artist_compare_view", text="B · 候选").candidate = True
            row = body.row(align=True)
            row.operator_context = "EXEC_DEFAULT"
            preview = row.operator("camera_live_rebuilt.start", text="播放预演", icon="PLAY")
            if shot and shot.camera and scene.camera_live_source == "SCENE":
                preview.local_camera_name = shot.camera.name
                preview.range_mode = "CUSTOM"
                preview.first = shot.first
                preview.last = shot.last
            row.operator("camera_live_rebuilt.stop", text="", icon="PAUSE")
            row.operator("camera_live_rebuilt.restore", text="", icon="LOOP_BACK")
            if settings.comparison_camera and scene.camera_live_source == "SCENE":
                candidate = row.operator("camera_live_rebuilt.start", text="播放 B")
                candidate.local_camera_name = settings.comparison_camera.name
                if shot:
                    candidate.range_mode = "CUSTOM"
                    candidate.first, candidate.last = shot.first, shot.last
            body.prop_enum(scene, "camera_live_source", "SCENE", text="单机位预演")
            body.prop_enum(scene, "camera_live_source", "SEQUENCE", text="全片镜头表预演")
            body.operator("camera_windows_static.motion_check")
        _, body = section_panel(layout, "cw_diagnosis", "镜头质检与副本",
                                icon="FILE_TICK", default_closed=True)
        if body is not None:
            ui.draw_copy_controls(body, context)
        status_banner(layout, context, settings.last_report, kind=settings.last_report_kind, icon_pack=_ICONS)


_CLASSES = (CAMERA_WINDOWS_PG_artist, CAMERA_WINDOWS_UL_shots, CAMERA_WINDOWS_OT_shot,
            CAMERA_WINDOWS_OT_lens, CAMERA_WINDOWS_OT_motion, CAMERA_WINDOWS_OT_compare_view,
            CAMERA_WINDOWS_PT_artist)


def register():
    _ICONS.register()
    registered = []
    try:
        for cls in _CLASSES:
            bpy.utils.register_class(cls)
            registered.append(cls)
        setattr(bpy.types.Scene, _PROPERTY, PointerProperty(type=CAMERA_WINDOWS_PG_artist))
        SidebarDock.register_plugin(DOMAIN, _ICONS.icons_dir)
    except Exception:
        SidebarDock.unregister_plugin(DOMAIN)
        if hasattr(bpy.types.Scene, _PROPERTY):
            delattr(bpy.types.Scene, _PROPERTY)
        for cls in reversed(registered):
            bpy.utils.unregister_class(cls)
        _ICONS.unregister()
        raise


def unregister():
    SidebarDock.unregister_plugin(DOMAIN)
    delattr(bpy.types.Scene, _PROPERTY)
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
    _ICONS.unregister()
