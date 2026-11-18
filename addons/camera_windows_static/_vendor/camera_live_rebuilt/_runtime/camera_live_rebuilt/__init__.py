"""New independent reconstruction, not a recovery of the lost 0.20.12 addon."""
bl_info = {
    'name': 'Camera Live Rebuilt', 'author': 'OpenAI / private reconstruction',
    'version': (0, 5, 0), 'blender': (5, 2, 0),
    'location': '3D View > Sidebar > Camera Live',
    'description': 'One-pass timer preview, held endpoint and guarded explicit restoration',
    'category': 'Camera',
}
import bpy
from copy import deepcopy
from uuid import uuid4
from bpy.props import EnumProperty, IntProperty, StringProperty, PointerProperty, CollectionProperty
from .core import Preview
from .adapter import Viewport
from .ui_layout import wrap_text, status_text
from .workbench import Candidate, ComparisonViewport, PlaybackViewport
from .authoring import edited_variant, save_new_json

_candidate = None
_compare_side = None

_preview = Preview()
_timer = None
_registered = []
_scene_properties = {}
SCENE_PROPERTIES = ('camera_live_shots', 'camera_live_source')


def remove_timer():
    global _timer
    callback, _timer = _timer, None
    if callback is not None and bpy.app.timers.is_registered(callback):
        bpy.app.timers.unregister(callback)


def start_timer(token):
    global _timer
    def callback():
        global _timer
        try:
            result = _preview.tick(token)
            if result is None and _timer is callback:
                _timer = None
            return result
        except Exception as exc:
            _preview.error(exc)
            if _timer is callback:
                _timer = None
            return None
    _timer = callback
    bpy.app.timers.register(callback, first_interval=1 / 60, persistent=False)


def draw_text(layout, context, text, inset=0, logical_width=None):
    region = getattr(context, 'region', None)
    system = getattr(getattr(context, 'preferences', None), 'system', None)
    width, scale = (logical_width, 1.) if logical_width is not None else (getattr(region, 'width', 244), getattr(system, 'ui_scale', 1.))
    for line in wrap_text(text, width, scale, inset):
        layout.label(text=line)


def short_label(value, limit=96):
    text = str(value)
    return text if len(text) <= limit else text[:limit] + '... [shortened]'


def camera_poll(self, obj):
    return obj.type == 'CAMERA'


class CAMERA_LIVE_REBUILT_PG_shot(bpy.types.PropertyGroup):
    name: StringProperty(name='Shot', default='Shot')
    camera: PointerProperty(name='Camera', type=bpy.types.Object, poll=camera_poll)
    first: IntProperty(name='Start', default=1, min=-1048574, max=1048574)
    last: IntProperty(name='End', default=24, min=-1048574, max=1048574)


class CAMERA_LIVE_REBUILT_OT_add_shot(bpy.types.Operator):
    bl_idname = 'camera_live_rebuilt.add_shot'
    bl_label = 'Add Shot'
    bl_description = 'Append a 24-frame technical placeholder; choose its camera and timing'
    @classmethod
    def poll(cls, context):
        return context.scene is not None and _preview.lease is None and len(context.scene.camera_live_shots) < 100
    def execute(self, context):
        if not type(self).poll(context): return {'CANCELLED'}
        shots = context.scene.camera_live_shots
        first = shots[-1].last + 1 if shots else context.scene.frame_start
        if first > 1048574:
            self.report({'WARNING'}, 'No frame space remains after the last shot.')
            return {'CANCELLED'}
        names = {item.name for item in shots}
        number = 1
        while f'Shot {number}' in names: number += 1
        item = shots.add()
        item.name = f'Shot {number}'
        item.camera = context.scene.camera
        item.first, item.last = first, min(first + 23, 1048574)
        return {'FINISHED'}


class CAMERA_LIVE_REBUILT_OT_remove_shot(bpy.types.Operator):
    bl_idname = 'camera_live_rebuilt.remove_shot'
    bl_label = 'Remove Shot'
    index: IntProperty(default=-1)
    @classmethod
    def poll(cls, context): return context.scene is not None and _preview.lease is None
    def execute(self, context):
        if not type(self).poll(context) or not 0 <= self.index < len(context.scene.camera_live_shots):
            return {'CANCELLED'}
        context.scene.camera_live_shots.remove(self.index)
        return {'FINISHED'}


class CAMERA_LIVE_REBUILT_OT_start(bpy.types.Operator):
    bl_idname = 'camera_live_rebuilt.start'
    bl_label = 'Preview Once'
    bl_description = 'One timer-driven camera pass; not native animation playback or a render'
    range_mode: EnumProperty(name='Range', items=[('SCENE', 'Scene Range', ''),
        ('PREVIEW', 'Preview Range', 'Explicitly use scene preview bounds without changing them'),
        ('CUSTOM', 'Custom Range', 'Temporary operator values, not scene frame-range edits')], default='SCENE')
    first: IntProperty(name='Start', default=185, min=-1048574, max=1048574)
    last: IntProperty(name='End', default=224, min=-1048574, max=1048574)
    shading: EnumProperty(name='View', items=[('SOLID', 'SOLID: Viewport', 'Uses existing viewport DOF; not final render'),
        ('MATERIAL', 'MATERIAL: Optical Viewport', 'Viewport materials/DOF, not the final render')], default='SOLID')

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == 'VIEW_3D' and _preview.lease is None

    def invoke(self, context, event):
        self.range_mode = 'SCENE'
        self.shading = 'SOLID'
        return context.window_manager.invoke_props_dialog(self, width=380)

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        sequence = getattr(scene, 'camera_live_source', 'SCENE') == 'SEQUENCE'
        if sequence:
            draw_text(layout, context, f'Shot sequence: {len(scene.camera_live_shots)} entries', logical_width=380)
            draw_text(layout, context, 'Uses the complete shot table range. Local view only.', logical_width=380)
        else:
            layout.prop(self, 'range_mode')
        if not sequence and self.range_mode == 'CUSTOM':
            row = layout.row(align=True); row.prop(self, 'first'); row.prop(self, 'last')
        elif not sequence:
            bounds = (scene.frame_start, scene.frame_end) if self.range_mode == 'SCENE' else (scene.frame_preview_start, scene.frame_preview_end)
            draw_text(layout, context, f'Frames: {bounds[0]} to {bounds[1]}', logical_width=380)
        layout.prop(self, 'shading')
        if sequence:
            shots = scene.camera_live_shots
            if shots:
                draw_text(layout, context, f'Full range: {shots[0].first} to {shots[-1].last}', logical_width=380)
            for shot in list(shots)[:3]:
                draw_text(layout, context, f'{shot.name}: {shot.first} to {shot.last}', logical_width=380)
                draw_text(layout, context, shot.camera.name if shot.camera else '(missing camera)', logical_width=380)
            if len(shots) > 3:
                draw_text(layout, context, f'{len(shots) - 3} more shots. Full table is in the sidebar.', logical_width=380)
            draw_text(layout, context, 'Each camera keeps its existing optical/DOF settings.', logical_width=380)
        else:
            draw_text(layout, context, 'Camera:', logical_width=380)
            draw_text(layout, context, scene.camera.name if scene.camera else '(none)', logical_width=380)
        if self.shading == 'SOLID':
            draw_text(layout, context, 'Uses existing viewport DOF; not final render.', logical_width=380)
        if self.shading == 'MATERIAL':
            draw_text(layout, context, 'Viewport materials/DOF are not final-render quality.', logical_width=380)
            if not sequence and scene.camera and not scene.camera.data.dof.use_dof:
                draw_text(layout, context, 'Camera DOF is off. This addon will not enable it.', logical_width=380)

    def execute(self, context):
        previous_lease = _preview.lease
        try:
            sequence = getattr(context.scene, 'camera_live_source', 'SCENE') == 'SEQUENCE'
            adapter = Viewport(bpy, context, sequence=True) if sequence else Viewport(bpy, context)
            token = _preview.start(adapter, self.range_mode, self.first, self.last, self.shading,
                                   shots=adapter.shots if sequence else None)
            if _preview.state == 'RUNNING':
                start_timer(token)
            return {'FINISHED'}
        except Exception as exc:
            if _preview.lease is not None and _preview.lease is not previous_lease and _preview.state != 'CONFLICT':
                _preview.error(exc)
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}


class CAMERA_LIVE_REBUILT_OT_stop(bpy.types.Operator):
    bl_idname = 'camera_live_rebuilt.stop'
    bl_label = 'Stop (Hold Current)'
    @classmethod
    def poll(cls, context): return _preview.state == 'RUNNING'
    def execute(self, context):
        _preview.stop()  # Invalidate the token before unregistering the callback.
        try: remove_timer()
        except Exception as exc: self.report({'WARNING'}, str(exc))
        return {'FINISHED'}


class CAMERA_LIVE_REBUILT_OT_restore(bpy.types.Operator):
    bl_idname = 'camera_live_rebuilt.restore'
    bl_label = 'Restore Original Time + View'
    @classmethod
    def poll(cls, context): return _preview.state in ('RUNNING', 'HELD')
    def execute(self, context):
        if _preview.lease is None:
            self.report({'WARNING'}, 'No retained baseline.')
            return {'CANCELLED'}
        adapter = _preview.lease['adapter']
        if context.window != adapter.window or context.area != adapter.area or context.scene != adapter.scene:
            self.report({'WARNING'}, 'Restore from the original preview viewport and scene only.')
            return {'CANCELLED'}  # Do not strand the original running timer from another viewport.
        try:
            _preview.restore()
            remove_timer()
            return {'FINISHED'}
        except Exception as exc:
            try: remove_timer()
            except Exception: pass
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}


class CAMERA_LIVE_REBUILT_OT_release(bpy.types.Operator):
    bl_idname = 'camera_live_rebuilt.release'
    bl_label = 'Release (Keep Current)'
    bl_description = 'Forget the baseline without changing current time/view; no restoration or retry'
    @classmethod
    def poll(cls, context): return _preview.state in ('HELD', 'CONFLICT')
    def execute(self, context):
        _preview.release()
        try: remove_timer()
        except Exception as exc: self.report({'WARNING'}, str(exc))
        return {'FINISHED'}


class CAMERA_LIVE_REBUILT_OT_load_candidate(bpy.types.Operator):
    bl_idname = 'camera_live_rebuilt.load_candidate'
    bl_label = 'Load Table Candidate'
    bl_description = 'Read a source-bound JSON for A/B preview only; no table or project writes'
    filepath: StringProperty(name='Candidate JSON', subtype='FILE_PATH')
    filter_glob: StringProperty(default='*.json', options={'HIDDEN'})
    @classmethod
    def poll(cls, context): return _preview.lease is None and context.scene is not None
    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}
    def execute(self, context):
        global _candidate, _compare_side
        if not type(self).poll(context): return {'CANCELLED'}
        try:
            loaded = Candidate(bpy, context.scene, bpy.path.abspath(self.filepath))
            _candidate, _compare_side = loaded, None
            self.report({'INFO'}, 'Candidate loaded for preview only. Original table unchanged.')
            return {'FINISHED'}
        except Exception as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}


class CAMERA_LIVE_REBUILT_OT_clear_candidate(bpy.types.Operator):
    bl_idname = 'camera_live_rebuilt.clear_candidate'
    bl_label = 'Clear Candidate'
    @classmethod
    def poll(cls, context): return _preview.lease is None and _candidate is not None
    def execute(self, context):
        global _candidate, _compare_side
        if not type(self).poll(context): return {'CANCELLED'}
        _candidate, _compare_side = None, None
        return {'FINISHED'}


class CAMERA_LIVE_REBUILT_OT_compare(bpy.types.Operator):
    bl_idname = 'camera_live_rebuilt.compare'
    bl_label = 'Compare at Fixed Frame'
    side: EnumProperty(items=[('A', 'A: Original Table', ''), ('B', 'B: Candidate Table', '')], default='A')
    frame: IntProperty(name='Fixed frame', default=1, min=-1048574, max=1048574)
    shading: EnumProperty(name='View', items=[('SOLID', 'SOLID: Viewport', ''),
        ('MATERIAL', 'MATERIAL: Optical Viewport', '')], default='SOLID')
    @classmethod
    def poll(cls, context):
        lease = _preview.lease
        return _candidate is not None and context.area is not None and context.area.type == 'VIEW_3D' and (
            lease is None or (_preview.state == 'HELD' and 'still_tokens' in lease))
    def invoke(self, context, event):
        if _preview.lease is not None: return self.execute(context)
        self.frame = context.scene.frame_current
        self.shading = 'SOLID'
        return context.window_manager.invoke_props_dialog(self, width=380)
    def draw(self, context):
        self.layout.prop(self, 'frame')
        self.layout.prop(self, 'shading')
        draw_text(self.layout, context, 'A/B stays at this frame until Restore or Release.', logical_width=380)
        draw_text(self.layout, context, 'Preview only: original shot table and scene camera stay unchanged.', logical_width=380)
    def execute(self, context):
        global _compare_side
        if not type(self).poll(context): return {'CANCELLED'}
        prior = _preview.lease
        try:
            if prior is None:
                adapter = ComparisonViewport(bpy, context, _candidate, self.frame, self.side)
                _preview.start_still(adapter, self.frame, adapter.camera_token, self.shading)
            else:
                adapter = prior['adapter']
                if not isinstance(adapter, ComparisonViewport) or adapter.candidate is not _candidate:
                    raise RuntimeError('Different comparison owner; Restore or Release first.')
                if context.window != adapter.window or context.area != adapter.area or context.scene != adapter.scene:
                    raise RuntimeError('Use the original comparison viewport and scene.')
                try:
                    _candidate.check(bpy, context.scene, disk=True)
                except Exception as exc:
                    _preview.error(exc)
                    raise
                shot = _candidate.selected(self.side, adapter.frame)
                _preview.choose_still(shot[1])
            _compare_side = self.side
            return {'FINISHED'}
        except Exception as exc:
            if _preview.lease is not None and _preview.lease is not prior and _preview.state != 'CONFLICT':
                _preview.error(exc)
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}


class CAMERA_LIVE_REBUILT_OT_play_candidate(bpy.types.Operator):
    bl_idname = 'camera_live_rebuilt.play_candidate'
    bl_label = 'Play Candidate Once'
    bl_description = 'One full A or B table pass; local viewport only, no table edits or save'
    side: EnumProperty(items=[('A', 'A: Original Table', ''), ('B', 'B: Candidate Table', '')], default='A')
    shading: EnumProperty(name='View', items=[('SOLID', 'SOLID: Viewport', ''),
        ('MATERIAL', 'MATERIAL: Optical Viewport', '')], default='SOLID')
    @classmethod
    def poll(cls, context):
        return _candidate is not None and _preview.lease is None and context.area is not None and context.area.type == 'VIEW_3D'
    def invoke(self, context, event):
        if not type(self).poll(context): return {'CANCELLED'}
        self.shading = 'SOLID'
        return context.window_manager.invoke_props_dialog(self, width=380)
    def draw(self, context):
        if _candidate is not None:
            plan = _candidate.a if self.side == 'A' else _candidate.b
            draw_text(self.layout, context, 'Play ' + self.side + ': ' + str(plan[0][2]) + ' to ' + str(plan[-1][3]), logical_width=380)
        self.layout.prop(self, 'shading')
        draw_text(self.layout, context, 'One pass, then hold last frame. Stop holds current.', logical_width=380)
        draw_text(self.layout, context, 'Restore or Release before another pass. No table edits or save.', logical_width=380)
    def execute(self, context):
        if not type(self).poll(context): return {'CANCELLED'}
        previous_lease = _preview.lease
        try:
            adapter = PlaybackViewport(bpy, context, _candidate, self.side)
            token = _preview.start(adapter, shading=self.shading, shots=adapter.shots)
            if _preview.state == 'RUNNING': start_timer(token)
            return {'FINISHED'}
        except Exception as exc:
            if _preview.lease is not None and _preview.lease is not previous_lease and _preview.state != 'CONFLICT':
                _preview.error(exc)
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}


_EMPTY_AUTHOR_ENUM = [('NONE', 'Unavailable', 'Load a candidate first')]
_author_enum_cache = None
_author_owner = None


def author_items(self, key):
    # RNA callbacks can receive OperatorProperties, not our Python Operator instance.
    cache = _author_enum_cache
    if cache is not None and getattr(self, 'author_token', '') == cache['token']:
        return cache[key]
    return _EMPTY_AUTHOR_ENUM


def author_shots(self, context): return author_items(self, 'shots')
def author_cameras(self, context): return author_items(self, 'cameras')
def author_cuts(self, context): return author_items(self, 'cuts')


def release_author(self):
    global _author_owner
    if _author_owner is self:
        _author_owner = None
    # Keep strings alive through operator teardown; replace only on a later capture.


class CAMERA_LIVE_REBUILT_OT_save_candidate(bpy.types.Operator):
    bl_idname = 'camera_live_rebuilt.save_candidate'
    bl_label = 'Save Candidate As'
    bl_description = 'Save a new JSON; preserve current B and all untargeted candidate changes'
    filepath: StringProperty(name='New JSON', subtype='FILE_PATH')
    filter_glob: StringProperty(default='*.json', options={'HIDDEN'})
    candidate_name: StringProperty(name='New name', default='Candidate copy')
    operation: EnumProperty(name='Edit', items=[('COPY', 'Copy current B', ''),
        ('CAMERA', 'Choose existing camera', ''), ('CUT', 'Move adjacent cut', '')], default='COPY')
    author_token: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    shot: EnumProperty(name='Shot', items=author_shots)
    camera: EnumProperty(name='Camera', items=author_cameras)
    cut: EnumProperty(name='Adjacent cut', items=author_cuts)
    left_last: IntProperty(name='New left end', default=1, min=-1048574, max=1048574)

    @classmethod
    def poll(cls, context):
        return _candidate is not None and _preview.lease is None and context.scene is not None

    def capture(self, context):
        global _author_enum_cache, _author_owner
        if _author_owner is not None:
            raise RuntimeError('Close the existing Save Candidate dialog first.')
        if not type(self).poll(context): raise RuntimeError('Release or Restore before saving a candidate.')
        _candidate.check(bpy, context.scene, disk=True)
        self._captured_candidate = _candidate
        self._captured_sha = _candidate.document['content_sha256']
        self._captured_scene, self._captured_window = context.scene, context.window
        self._document = deepcopy(_candidate.document)
        # Long names are not enum identifiers. Retain all item strings for native enum lifetime.
        self._row_names = tuple(r['name'] for r in _candidate.document['rows'])
        self._camera_names = tuple(_candidate.document['catalog'])
        self._cut_pairs = tuple(zip(self._row_names, self._row_names[1:]))
        self._shot_items = [('R' + str(i), str(i + 1) + ': ' + short_label(n), '') for i, n in enumerate(self._row_names)]
        self._camera_items = [('C' + str(i), str(i + 1) + ': ' + short_label(n), '') for i, n in enumerate(self._camera_names)]
        self._cut_items = [('K' + str(i), str(i + 1) + ': ' + short_label(a, 40) + ' / ' + short_label(b, 40), '') for i, (a, b) in enumerate(self._cut_pairs)] or _EMPTY_AUTHOR_ENUM
        self.author_token = uuid4().hex
        _author_enum_cache = {'token': self.author_token, 'shots': self._shot_items,
                              'cameras': self._camera_items, 'cuts': self._cut_items}
        _author_owner = self
        self.candidate_name = _candidate.document['candidate_name'] + ' copy'
        self.operation = 'COPY'
        self.shot, self.camera = 'R0', 'C0'
        self.cut = 'K0' if self._cut_pairs else 'NONE'
        self.left_last = _candidate.document['rows'][0]['last']

    def invoke(self, context, event):
        try:
            self.capture(context)
            context.window_manager.fileselect_add(self)
            return {'RUNNING_MODAL'}
        except Exception as exc:
            release_author(self)
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}

    def cancel(self, context):
        # File chooser cancellation writes nothing and leaves the current B untouched.
        release_author(self)

    def _index(self, identifier, prefix, count):
        if type(identifier) is not str or not identifier.startswith(prefix) or not identifier[len(prefix):].isdigit():
            raise ValueError('Choose a valid captured item')
        index = int(identifier[len(prefix):])
        if not 0 <= index < count: raise ValueError('Captured item index is invalid')
        return index

    def draw(self, context):
        layout = self.layout
        layout.prop(self, 'candidate_name'); layout.prop(self, 'operation')
        if self.operation == 'CAMERA':
            layout.prop(self, 'shot'); layout.prop(self, 'camera')
        elif self.operation == 'CUT':
            layout.prop(self, 'cut'); layout.prop(self, 'left_last')
            try:
                i = self._index(self.cut, 'K', len(self._cut_pairs))
                left, right = self._document['rows'][i:i + 2]
                draw_text(layout, context, 'Current: ' + str(left['first']) + '-' + str(left['last']) + ' / ' + str(right['first']) + '-' + str(right['last']))
                draw_text(layout, context, 'New right start: ' + str(self.left_last + 1))
            except (AttributeError, ValueError):
                draw_text(layout, context, 'Choose a valid adjacent cut.')
        draw_text(layout, context, 'New JSON only. Current B stays unchanged.')
        draw_text(layout, context, 'Use Load Candidate JSON to preview the saved result.')

    def execute(self, context):
        try:
            if _author_owner is not self or _author_enum_cache is None or self.author_token != _author_enum_cache['token']:
                raise RuntimeError('Save dialog is no longer active; open Save Candidate As again.')
            if not type(self).poll(context): raise RuntimeError('Release or Restore before saving a candidate.')
            captured = getattr(self, '_captured_candidate', None)
            if captured is None or _candidate is not captured:
                raise RuntimeError('Candidate changed or Save was not invoked. Open Save Candidate As again.')
            if context.scene != self._captured_scene or context.window != self._captured_window:
                raise RuntimeError('Original scene or window changed; save cancelled.')
            captured.check(bpy, context.scene, disk=True)
            if captured.document['content_sha256'] != self._captured_sha:
                raise RuntimeError('Candidate content changed; open Save Candidate As again.')
            if self.operation == 'COPY': edit = {'op': 'copy'}
            elif self.operation == 'CAMERA':
                row = self._row_names[self._index(self.shot, 'R', len(self._row_names))]
                camera = self._camera_names[self._index(self.camera, 'C', len(self._camera_names))]
                edit = {'op': 'choose_camera', 'shot': row, 'camera': camera}
            elif self.operation == 'CUT':
                left, right = self._cut_pairs[self._index(self.cut, 'K', len(self._cut_pairs))]
                edit = {'op': 'move_cut', 'left': left, 'right': right, 'left_last': self.left_last}
            else: raise ValueError('Unknown authoring operation')
            result = edited_variant(captured.document, self.candidate_name, edit)
            saved = save_new_json(bpy.path.abspath(self.filepath), result, (captured.path, captured.source_path))
            self.report({'INFO'}, 'Saved ' + saved['file'] + '. Current B unchanged; use Load Candidate JSON to preview.')
            return {'FINISHED'}
        except Exception as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}

        finally:
            release_author(self)


class CLREBUILD_PT_preview(bpy.types.Panel):
    bl_idname = 'CLREBUILD_PT_preview'
    bl_label = 'Camera Live'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Camera Live'
    def draw(self, context):
        layout = self.layout
        scene = context.scene
        draw_text(layout, context, 'Rebuild 0.5.0')
        draw_text(layout, context, f'Scene frames: {scene.frame_start} to {scene.frame_end}')
        draw_text(layout, context, 'Camera:')
        draw_text(layout, context, scene.camera.name if scene.camera else '(none)')
        draw_text(layout, context, 'Timer preview; not final render.')
        # Full-width, taller standard Blender buttons. No custom input/retry logic.
        for action, label in (('start', 'Start'), ('stop', 'Stop'), ('restore', 'Restore'), ('release', 'Release')):
            row = layout.row()
            row.scale_y = 1.5
            row.operator('camera_live_rebuilt.' + action, text=label)
        draw_text(layout, context, 'Restore: original time/view. Release: keep current.')
        title, message = status_text(_preview.state, _preview.message)
        draw_text(layout, context, title)
        box = layout.box()
        draw_text(box, context, message, inset=18)

        box = layout.box()
        draw_text(box, context, 'Table Candidate A/B', inset=18)
        draw_text(box, context, 'No table edits or .blend save.', inset=18)
        draw_text(box, context, 'Uses current scene optics/animation.', inset=18)
        box.operator('camera_live_rebuilt.load_candidate', text='Load Candidate JSON')
        if _candidate is not None:
            draw_text(box, context, 'A: Original table', inset=18)
            draw_text(box, context, 'B: ' + short_label(_candidate.document['candidate_name']), inset=18)
            for change in _candidate.diff['changed'][:3]:
                draw_text(box, context, short_label(change['shot'], 64) + ': ' + ', '.join(change['fields']), inset=18)
            if len(_candidate.diff['changed']) > 3:
                draw_text(box, context, str(len(_candidate.diff['changed']) - 3) + ' more changed shots', inset=18)
            for side in ('A', 'B'):
                row = box.row(); row.scale_y = 1.4
                row.operator('camera_live_rebuilt.compare', text='Show ' + side).side = side
            for side in ('A', 'B'):
                row = box.row(); row.scale_y = 1.4
                row.operator('camera_live_rebuilt.play_candidate', text='Play ' + side).side = side
            lease = _preview.lease
            if lease is not None and isinstance(lease['adapter'], PlaybackViewport):
                adapter = lease['adapter']
                draw_text(box, context, 'Playback ' + adapter.side + ': ' + str(adapter.shots[0][2]) + ' to ' + str(adapter.shots[-1][3]), inset=18)
                draw_text(box, context, 'Restore or Release before replay.', inset=18)
            if lease is not None and 'still_tokens' in lease:
                adapter = lease['adapter']
                draw_text(box, context, 'Fixed frame: ' + str(adapter.frame) + ' / ' + str(_compare_side), inset=18)
                for side in ('A', 'B'):
                    shot = _candidate.selected(side, adapter.frame)
                    camera_name = next((name for name, token in _candidate.camera_tokens.items() if token == shot[1]), '(missing camera)')
                    draw_text(box, context, side + ': ' + short_label(shot[0], 64), inset=18)
                    draw_text(box, context, short_label(camera_name), inset=18)
            box.operator('camera_live_rebuilt.save_candidate', text='Save Candidate As...')
            box.operator('camera_live_rebuilt.clear_candidate', text='Clear Candidate')
        draw_text(box, context, 'Restore returns original time/view. Release keeps current.', inset=18)

        settings = layout.column()
        settings.enabled = _preview.lease is None
        settings.prop(scene, 'camera_live_source', text='Source')
        if getattr(scene, 'camera_live_source', 'SCENE') == 'SEQUENCE':
            draw_text(settings, context, 'Ordered shots: inclusive bounds, no gaps or overlaps.')
            for index, shot in enumerate(scene.camera_live_shots):
                box = settings.box()
                box.prop(shot, 'name')
                box.prop(shot, 'camera')
                box.prop(shot, 'first')
                box.prop(shot, 'last')
                box.operator('camera_live_rebuilt.remove_shot', text='Remove Shot').index = index
            settings.operator('camera_live_rebuilt.add_shot', text='Add Shot')
            draw_text(settings, context, 'Local view cuts only; scene camera and render unchanged.')



CLASSES = (CAMERA_LIVE_REBUILT_OT_start, CAMERA_LIVE_REBUILT_OT_stop, CAMERA_LIVE_REBUILT_OT_restore, CAMERA_LIVE_REBUILT_OT_release, CAMERA_LIVE_REBUILT_PG_shot, CAMERA_LIVE_REBUILT_OT_add_shot, CAMERA_LIVE_REBUILT_OT_remove_shot, CAMERA_LIVE_REBUILT_OT_load_candidate, CAMERA_LIVE_REBUILT_OT_clear_candidate, CAMERA_LIVE_REBUILT_OT_compare, CAMERA_LIVE_REBUILT_OT_play_candidate, CAMERA_LIVE_REBUILT_OT_save_candidate, CLREBUILD_PT_preview)


def registered_class(cls):
    """Resolve the actual native owner, including bpy.types-invisible PropertyGroups."""
    if issubclass(cls, bpy.types.PropertyGroup):
        return bpy.types.PropertyGroup.bl_rna_get_subclass_py(cls.__name__, None)
    return getattr(bpy.types, cls.__name__, None)


def clear_registered_classes():
    for cls in reversed(_registered):
        if registered_class(cls) is cls:
            bpy.utils.unregister_class(cls)
    _registered.clear()


def register():
    if _registered or _scene_properties or any(hasattr(bpy.types.Scene, name) for name in SCENE_PROPERTIES) or any(registered_class(cls) is not None for cls in CLASSES):
        raise RuntimeError('Camera Live Rebuilt registration already exists; no duplicate owner.')
    try:
        for cls in CLASSES:
            bpy.utils.register_class(cls)
            _registered.append(cls)
        definitions = {
            'camera_live_shots': CollectionProperty(type=CAMERA_LIVE_REBUILT_PG_shot),
            'camera_live_source': EnumProperty(name='Source', items=[('SCENE', 'Scene Camera', 'Existing single-camera preview'),
                ('SEQUENCE', 'Shot Sequence', 'Continuous local viewport cuts; does not change rendered camera')], default='SCENE'),
        }
        for name, definition in definitions.items():
            setattr(bpy.types.Scene, name, definition)
            _scene_properties[name] = getattr(bpy.types.Scene, name)
    except Exception:
        clear_scene_properties()
        clear_registered_classes()
        raise


def clear_scene_properties():
    for name, descriptor in tuple(_scene_properties.items()):
        if getattr(bpy.types.Scene, name, None) is descriptor:
            delattr(bpy.types.Scene, name)
    _scene_properties.clear()


def unregister():
    global _candidate, _compare_side, _author_owner, _author_enum_cache
    _author_owner, _author_enum_cache = None, None
    _candidate, _compare_side = None, None
    # No automatic restoration: foreign changes must not be overwritten on unload.
    _preview.release()
    try: remove_timer()
    finally:
        clear_scene_properties()
        clear_registered_classes()
