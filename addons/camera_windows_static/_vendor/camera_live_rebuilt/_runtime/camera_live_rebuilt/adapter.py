"""Narrow Blender RNA adapter. Never assigns scene.camera or render/compositor data."""
from .core import require, shading_capability, validate_shots


def validate_camera_markers(markers):
    """Read-only refusal of every bound marker, including duplicate names."""
    require(not any(marker.camera is not None for marker in markers),
            'Camera-bound timeline markers are not supported in this rebuild; scene.camera must remain unchanged.')


class Viewport:
    def __init__(self, bpy, context, sequence=False):
        require(not bpy.app.background, 'Start requires an actual GUI VIEW_3D, not background mode.')
        self.bpy = bpy
        self.window, self.screen, self.area = context.window, context.screen, context.area
        self.scene = context.scene
        require(self.window is not None and self.screen is not None and self.area is not None and
                self.area.type == 'VIEW_3D', 'Use the sidebar of an owned 3D View.')
        self.space = self.area.spaces.active
        require(not self.space.region_quadviews, 'Use a single 3D View, not Quad View.')
        regions = [region for region in self.area.regions if region.type == 'WINDOW']
        require(len(regions) == 1, 'One owned viewport WINDOW region required.')
        self.region = regions[0]
        self.rv3d = self.space.region_3d
        require(self.rv3d is not None, 'Original RegionView3D is unavailable.')
        self.sequence = sequence
        self.camera = self.scene.camera
        require(self.camera is not None and self.camera.type == 'CAMERA', 'Set the intended scene camera before Start.')
        self.camera_token = self.camera.as_pointer()
        # Keep actual original RNA references, not relookups by name.
        self.cameras = {self.camera_token: self.camera}
        if self.space.camera is not None:
            self.cameras[self.space.camera.as_pointer()] = self.space.camera
        self.shots = None
        self.shot_cameras = {}
        if sequence:
            self.shots = self.read_shots()
            for item in self.scene.camera_live_shots:
                camera = item.camera
                self.shot_cameras[camera.as_pointer()] = camera
            self.cameras.update(self.shot_cameras)
        self.owner = tuple(obj.as_pointer() for obj in (self.window, self.screen, self.area, self.space, self.region, self.rv3d, self.scene))
        self.check_owner()

    def read_shots(self):
        return validate_shots(tuple((item.name, item.camera.as_pointer() if item.camera else 0,
                                     item.first, item.last) for item in self.scene.camera_live_shots))

    def check_owner(self):
        require(not self.bpy.app.background, 'GUI ownership lost.')
        current = tuple(obj.as_pointer() for obj in (self.window, self.screen, self.area, self.space, self.region, self.rv3d, self.scene))
        require(current == self.owner and all(current), 'Original RNA owner is invalid.')
        require(any(w == self.window for w in self.bpy.context.window_manager.windows) and
                self.window.screen == self.screen and self.window.scene == self.scene and
                any(a == self.area for a in self.screen.areas) and self.area.type == 'VIEW_3D' and
                self.area.spaces.active == self.space and self.space.region_3d == self.rv3d and
                any(r == self.region for r in self.area.regions) and not self.space.region_quadviews,
                'Window/scene/viewport changed; stopped without restoring.')
        validate_camera_markers(self.scene.timeline_markers)
        require(self.scene.camera == self.camera, 'Scene camera changed externally; stopped without restoring.')
        require(self.camera.as_pointer() == self.camera_token and self.camera.type == 'CAMERA' and
                any(obj == self.camera for obj in self.scene.objects), 'Original preview camera is no longer in the scene.')

        if self.sequence:
            require(self.read_shots() == self.shots, 'Shot sequence changed externally; stopped without restoring.')
            for token, camera in self.shot_cameras.items():
                require(camera.as_pointer() == token and camera.type == 'CAMERA' and
                        any(obj == camera for obj in self.scene.objects),
                        'A shot camera is no longer in the scene; stopped without restoring.')

    def shading_capability(self, shading):
        self.check_owner()
        with self.bpy.context.temp_override(window=self.window, area=self.area, region=self.region):
            return shading_capability(self.scene.render.engine, self.bpy.app.version, shading)

    def is_playing(self):
        return any(w.screen is not None and w.screen.is_animation_playing
                   for w in self.bpy.context.window_manager.windows)

    def configuration(self, mode, first, last):
        if mode == 'SCENE':
            first, last = self.scene.frame_start, self.scene.frame_end
        elif mode == 'PREVIEW':
            first, last = self.scene.frame_preview_start, self.scene.frame_preview_end
        return (first, last, self.scene.render.fps, self.scene.render.fps_base)

    def read_time(self):
        return self.scene.frame_current, self.scene.frame_subframe

    def read_view(self):
        camera = self.space.camera
        return {'local_camera': bool(self.space.use_local_camera), 'camera': camera.as_pointer() if camera else 0,
                'perspective': self.rv3d.view_perspective, 'rotation': tuple(self.rv3d.view_rotation),
                'location': tuple(self.rv3d.view_location), 'distance': self.rv3d.view_distance,
                'camera_zoom': self.rv3d.view_camera_zoom, 'camera_offset': tuple(self.rv3d.view_camera_offset),
                'lock_camera': bool(self.space.lock_camera), 'shading': self.space.shading.type,
                'use_dof': bool(self.space.shading.use_dof) if hasattr(self.space.shading, 'use_dof') else None}

    def set_view(self, key, value):
        self.check_owner()
        with self.bpy.context.temp_override(window=self.window, area=self.area, region=self.region):
            if key == 'camera':
                camera = self.cameras.get(value) if value else None
                require(not value or (camera is not None and camera.as_pointer() == value), 'Held original camera reference lost.')
                require(self.space.use_local_camera, 'Only the local viewport camera may be assigned.')
                self.space.camera = camera
            elif key == 'local_camera':
                self.space.use_local_camera = value
            elif key == 'shading':
                self.space.shading.type = value
            elif key == 'use_dof':
                require(value is not None and hasattr(self.space.shading, 'use_dof'), 'Viewport DOF RNA is unavailable.')
                self.space.shading.use_dof = value
            else:
                fields = {'perspective': 'view_perspective', 'rotation': 'view_rotation', 'location': 'view_location',
                          'distance': 'view_distance', 'camera_zoom': 'view_camera_zoom', 'camera_offset': 'view_camera_offset'}
                setattr(self.rv3d, fields[key], value)
        self.area.tag_redraw()

    def set_time(self, frame, subframe):
        self.check_owner()
        with self.bpy.context.temp_override(window=self.window, area=self.area, region=self.region):
            self.scene.frame_set(frame, subframe=subframe)
        self.area.tag_redraw()
