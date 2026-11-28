"""Pure single-pass preview state machine. No bpy, renderer, saving or native playback."""
import math
import time


class PreviewError(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise PreviewError(message)


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def shading_capability(engine, version, shading):
    """Fail-closed contract from actual 5.3.0 RNA setter probes, not enum_items."""
    require(type(engine) is str and engine, 'Render engine identity is unavailable.')
    version = tuple(version)
    require(shading in ('SOLID', 'MATERIAL'), 'Unsupported preview shading.')
    if shading == 'MATERIAL':
        require(engine == 'BLENDER_EEVEE' and version >= (5, 3, 0),
                'MATERIAL is verified for Blender 5.3.0 or later / BLENDER_EEVEE. Choose SOLID explicitly; the render engine will not be changed.')
    return engine, version


def validate_shots(shots):
    """Pure shared plan contract: (unique name, camera token, first, last)."""
    require(type(shots) in (tuple, list) and 1 <= len(shots) <= 100,
            'Shot sequence needs 1 to 100 entries.')
    result, names, previous = [], set(), None
    for item in shots:
        require(type(item) in (tuple, list) and len(item) == 4, 'Invalid shot entry.')
        name, camera, first, last = item
        require(type(name) is str and name.strip() == name and bool(name) and name not in names,
                'Shot names must be nonempty, unique and have no outer spaces.')
        require(type(camera) is int and camera > 0, 'Every shot needs a valid camera.')
        require(type(first) is int and type(last) is int and -1048574 <= first <= last <= 1048574,
                'Shot frames must be integers within Blender bounds, start <= end.')
        require(previous is None or first == previous + 1,
                'Shots must be ordered and contiguous; gaps and overlaps are refused.')
        names.add(name); previous = last; result.append((name, camera, first, last))
    return tuple(result)


def shot_at(shots, frame):
    """Closed shot intervals; exact cut belongs to the incoming shot."""
    require(type(frame) is int, 'Shot lookup needs an integer frame.')
    for shot in shots:
        if shot[2] <= frame <= shot[3]:
            return shot
    raise PreviewError('Frame lies outside the shot sequence.')


class Preview:
    """One retained baseline until Restore or explicit Release.

    Adapter reads return plain values. All writes are confined to time and the
    held viewport. Guards are sampled, not a complete edit-history detector.
    """
    ENTER_ORDER = ('local_camera', 'camera', 'perspective', 'shading', 'use_dof')
    RESTORE_ORDER = ('shading', 'use_dof', 'location', 'distance',
                     'camera_zoom', 'camera_offset', 'camera', 'perspective', 'rotation', 'local_camera')

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.generation = 0
        self.state = 'IDLE'
        self.message = 'Ready. This is timer-driven viewport preview, not native playback.'
        self.lease = None
        self.updates = 0
        self.skipped_steps = 0

    def _now(self):
        value = self.clock()
        require(finite(value), 'Invalid monotonic clock; preview stopped.')
        return value

    def _fail(self, exc):
        self.generation += 1
        self.state = 'CONFLICT'
        self.message = str(exc) or type(exc).__name__

    def _guard(self):
        lease = self.lease
        require(lease is not None, 'No retained preview baseline.')
        adapter = lease['adapter']
        adapter.check_owner()
        if lease['shots'] is not None:
            require(adapter.read_shots() == lease['shots'], 'Shot sequence changed externally; stopped without restoring.')
        require(adapter.shading_capability(lease['shading']) == lease['capability'],
                'Render engine/capability changed externally; stopped without restoring.')
        require(not adapter.is_playing(), 'External animation playback detected; stopped without restoring.')
        require(adapter.configuration(*lease['range_args']) == lease['config'],
                'Frame range/FPS changed externally; stopped without restoring.')
        require(adapter.read_time() == lease['time'],
                'Time changed externally; stopped without restoring.')
        actual_view = adapter.read_view()
        expected_view = lease['view']
        camera_cache = actual_view['perspective'] == expected_view['perspective'] == 'CAMERA'
        compared_view = dict(actual_view)
        if camera_cache:
            # In CAMERA this RNA value is a draw-derived cache, not a navigation input.
            # All other fields must still match before accepting that cache value.
            compared_view['rotation'] = expected_view['rotation']
        require(compared_view == expected_view,
                'Viewport changed externally; stopped without restoring.')
        if camera_cache:
            # Track only this cache for the later controlled exit to PERSP/ORTHO.
            # Never alter original_view: its raw rotation is restored after exit.
            expected_view['rotation'] = actual_view['rotation']

    def _view(self, key, value):
        self._guard()
        if self.lease['view'][key] == value:
            return
        self.lease['view'][key] = value
        self.lease['adapter'].set_view(key, value)
        self._guard()

    def _time(self, value):
        self._guard()
        if self.lease['time'] == value:
            return
        self.lease['time'] = value
        self.lease['adapter'].set_time(*value)
        self._guard()
        self.updates += 1

    def start(self, adapter, range_mode='SCENE', custom_start=185, custom_end=224, shading='SOLID', shots=None):
        require(self.lease is None, 'Restore or Release the retained baseline before another Start.')
        require(shading in ('SOLID', 'MATERIAL'), 'Choose SOLID layout or MATERIAL optical preview.')
        require(range_mode in ('SCENE', 'PREVIEW', 'CUSTOM'), 'Unknown range mode.')
        if shots is not None:
            shots = validate_shots(shots)
            require(adapter.read_shots() == shots, 'Shot sequence does not match the held adapter.')
            range_mode, custom_start, custom_end = 'CUSTOM', shots[0][2], shots[-1][3]
        adapter.check_owner()
        capability = adapter.shading_capability(shading)  # Before generation, lease or any view/time write.
        require(not adapter.is_playing(), 'Stop existing animation playback before preview.')
        config = adapter.configuration(range_mode, custom_start, custom_end)
        require(type(config) is tuple and len(config) == 4, 'Invalid frame-range/FPS configuration.')
        first, last, fps, fps_base = config
        require(type(first) is int and type(last) is int and first <= last, 'Start frame must not exceed end frame.')
        require(finite(fps) and finite(fps_base) and fps_base > 0 and 0 < fps / fps_base <= 240,
                'Effective FPS must be finite, greater than zero and at most 240.')
        original_time = adapter.read_time()
        require(type(original_time[0]) is int and finite(original_time[1]) and 0 <= original_time[1] < 1,
                'Invalid original frame/subframe.')
        original_view = adapter.read_view()
        require(original_view['lock_camera'] is False,
                'Disable Lock Camera to View first; preview will not edit the camera.')
        before = self._now()
        self.generation += 1
        self.updates = self.skipped_steps = 0
        self.lease = {'adapter': adapter, 'shots': shots, 'shading': shading, 'capability': capability, 'range_args': (range_mode, custom_start, custom_end),
                      'config': config, 'original_time': original_time, 'original_view': dict(original_view),
                      'time': original_time, 'view': dict(original_view), 'fps': fps / fps_base}
        self.state = 'STARTING'
        try:
            target = dict(original_view, local_camera=True, camera=shots[0][1] if shots else adapter.camera_token,
                          perspective='CAMERA', shading=shading)
            if shading == 'MATERIAL' and original_view['use_dof'] is not None:
                target['use_dof'] = True
            for key in self.ENTER_ORDER:
                self._view(key, target[key])
            self._time((first, 0.0))
            now = self._now()
            require(now >= before, 'Monotonic clock moved backward.')
            self.lease.update(origin=now, last_tick=now)
            self.state = 'HELD' if first == last else 'RUNNING'
            self.message = 'End frame held. Restore or Release to start again.' if first == last else 'One pass running.'
            return self.generation
        except Exception as exc:
            self._fail(exc)
            raise

    def start_still(self, adapter, frame, camera_token, shading='SOLID'):
        """One locked frame, explicit adapter whitelist; no timer or table mutation."""
        require(self.lease is None, 'Restore or Release before a new comparison.')
        require(type(frame) is int and -1048574 <= frame <= 1048574, 'Invalid comparison frame.')
        tokens = tuple(adapter.still_camera_tokens)
        require(tokens and all(type(t) is int and t > 0 for t in tokens) and type(camera_token) is int and camera_token in tokens,
                'Camera is outside the comparison whitelist.')
        require(adapter.camera_token == camera_token, 'Initial comparison camera differs.')
        generation = self.start(adapter, 'CUSTOM', frame, frame, shading)
        self.lease['still_tokens'] = tokens
        self.message = 'Comparison frame held. A/B changes only the local camera.'
        return generation

    def choose_still(self, camera_token):
        require(self.state == 'HELD' and self.lease is not None and 'still_tokens' in self.lease,
                'A held comparison is required; ordinary LIVE cannot switch this way.')
        try:
            self._guard()
            require(tuple(self.lease['adapter'].still_camera_tokens) == self.lease['still_tokens'],
                    'Comparison whitelist changed.')
            require(type(camera_token) is int and camera_token in self.lease['still_tokens'],
                    'Camera is outside the comparison whitelist.')
            require(self.lease['config'][0] == self.lease['config'][1], 'Comparison frame is not locked.')
            self._view('camera', camera_token)
            self.message = 'Comparison frame held. A/B changes only the local camera.'
        except Exception as exc:
            self._fail(exc)
            raise

    def tick(self, token):
        # A queued old callback must be inert after Stop/Restore/Release/restart.
        if token != self.generation or self.state != 'RUNNING':
            return None
        try:
            self._guard()
            now = self._now()
            require(now >= self.lease['last_tick'], 'Monotonic clock moved backward.')
            self.lease['last_tick'] = now
            first, last = self.lease['config'][:2]
            elapsed = now - self.lease['origin']
            duration = (last - first) / self.lease['fps']
            # Clamp BEFORE multiplication/frame_set. Never modulo, wrap or seek back.
            frame = last if elapsed >= duration else min(last, first + int(elapsed * self.lease['fps']))
            prior = self.lease['time'][0]
            require(prior <= frame <= last, 'Nonmonotonic preview step refused.')
            self.skipped_steps += max(0, frame - prior - 1)
            if self.lease['shots'] is not None:
                self._view('camera', shot_at(self.lease['shots'], frame)[1])
            self._time((frame, 0.0))
            if frame == last:
                self.generation += 1
                self.state = 'HELD'
                self.message = 'End frame held. Restore or Release to start again.'
                return None
            return max(1 / 240, min(1 / 30, 1 / self.lease['fps']))
        except Exception as exc:
            self._fail(exc)
            return None

    def stop(self):
        self.generation += 1
        if self.lease is None or self.state == 'CONFLICT':
            return
        try:
            self._guard()
            self.state = 'HELD'
            self.message = 'Stopped at current frame. Restore or Release to start again.'
        except Exception as exc:
            self._fail(exc)

    def restore(self):
        self.generation += 1
        require(self.lease is not None, 'No retained baseline to restore.')
        require(self.state != 'CONFLICT', 'Conflict is retained. Release keeps current values; no forced restore.')
        try:
            self._guard()
            self.state = 'RESTORING'
            self._time(self.lease['original_time'])
            for key in self.RESTORE_ORDER:
                self._view(key, self.lease['original_view'][key])
            self._guard()
            self.lease = None
            self.state = 'IDLE'
            self.message = 'Original frame/subframe and held viewport restored.'
        except Exception as exc:
            self._fail(exc)
            raise

    def release(self):
        """No writes to Blender. Also used on unregister; never force restoration."""
        self.generation += 1
        self.lease = None
        self.state = 'IDLE'
        self.message = 'Baseline released; current scene time and viewport left untouched.'

    def error(self, exc):
        self._fail(exc)
