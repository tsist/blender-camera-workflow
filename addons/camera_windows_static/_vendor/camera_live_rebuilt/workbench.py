"""Read-only source-bound candidate comparison; never saves or edits shot tables."""
import hashlib
from pathlib import Path
import stat
from . import candidate_model as model
from .core import require, validate_shots, shot_at
from .adapter import Viewport


def file_bytes(path, maximum):
    p = Path(path)
    require(p.is_absolute() and '..' not in p.parts, 'Use an absolute saved file path.')
    for part in (p, *p.parents):
        require(not stat.S_ISLNK(part.lstat().st_mode), 'Symlink input or ancestor is unsupported.')
    info = p.stat()
    require(stat.S_ISREG(info.st_mode) and info.st_size <= maximum, 'Input must be a bounded regular file.')
    with p.open('rb') as stream:
        raw = stream.read(maximum + 1)
    require(len(raw) <= maximum, 'Input grew beyond its limit.')
    return raw


def rows_of(scene):
    return [{'name': r.name, 'camera': r.camera.name if r.camera else None,
             'first': r.first, 'last': r.last} for r in scene.camera_live_shots]


class Candidate:
    def __init__(self, bpy, scene, filepath):
        raw = file_bytes(filepath, model.MAX_BYTES)
        self.document = model.load_json(raw)
        self.path = str(Path(filepath))
        self.json_sha = hashlib.sha256(raw).hexdigest()
        self.scene = scene
        self.scene_token = scene.as_pointer()
        self.source_path = bpy.data.filepath
        self.document_sha = self.document['content_sha256']
        self.cameras = {o.name: o for o in scene.objects if o.type == 'CAMERA'}
        self.camera_tokens = {name: obj.as_pointer() for name, obj in self.cameras.items()}
        self.check(bpy, scene, disk=True)
        self.a = self._resolve(self.document['base_rows'])
        self.b = self._resolve(self.document['rows'])
        original = model.export_snapshot(self.document['source_sha256'], self.document['scene'],
            self.document['source_mode'], self.document['base_rows'], self.document['catalog'])
        self.diff = model.compare(original, self.document)

    def _resolve(self, rows):
        return validate_shots([(r['name'], self.camera_tokens[r['camera']], r['first'], r['last']) for r in rows])

    def check(self, bpy, scene, disk=False):
        require(scene == self.scene and scene.as_pointer() == self.scene_token and self.scene_token,
                'Candidate belongs to another scene or reloaded file. Load it again.')
        require(bpy.data.filepath == self.source_path and bool(self.source_path), 'Saved source path changed.')
        require(not bpy.data.is_dirty, 'Unsaved scene changes: save a separate source and export a new candidate first.')
        doc = model.validate_document(self.document)
        require(doc['content_sha256'] == self.document_sha, 'Loaded candidate changed.')
        require(scene.name == doc['scene'] and scene.camera_live_source == doc['source_mode'] == 'SEQUENCE',
                'Candidate requires its original SEQUENCE source scene.')
        require(rows_of(scene) == doc['base_rows'], 'Current shot table differs from candidate baseline.')
        catalog = sorted(o.name for o in scene.objects if o.type == 'CAMERA')
        require(catalog == doc['catalog'], 'Scene camera catalog changed.')
        require(not scene.library and not scene.override_library, 'Linked or override scene unsupported.')
        for name, camera in self.cameras.items():
            require(camera.as_pointer() == self.camera_tokens[name] and camera.name == name and camera.type == 'CAMERA'
                    and any(o == camera for o in scene.objects), 'Held candidate camera changed or disappeared.')
            require(not camera.library and not camera.override_library, 'Linked or override camera unsupported.')
        if disk:
            require(hashlib.sha256(file_bytes(self.source_path, 256 * 1024 * 1024)).hexdigest() == doc['source_sha256'],
                    'Saved source SHA differs from candidate.')
            require(hashlib.sha256(file_bytes(self.path, model.MAX_BYTES)).hexdigest() == self.json_sha,
                    'Candidate JSON file changed; load it again.')

    def selected(self, side, frame):
        require(side in ('A', 'B'), 'Unknown comparison side.')
        return shot_at(self.a if side == 'A' else self.b, frame)


class CandidateViewport:
    """Shared original-table/owner guard; candidate cameras never replace source rows."""
    def __init__(self, bpy, context, candidate):
        candidate.check(bpy, context.scene, disk=True)
        self.base = Viewport(bpy, context, sequence=True)
        self.candidate = candidate
        self.base.cameras.update({obj.as_pointer(): obj for obj in candidate.cameras.values()})

    def __getattr__(self, name):
        return getattr(self.base, name)

    def check_owner(self):
        self.base.check_owner()
        self.candidate.check(self.base.bpy, self.base.scene)

    def set_view(self, key, value):
        self.check_owner()
        self.base.set_view(key, value)

    def set_time(self, frame, subframe):
        self.check_owner()
        self.base.set_time(frame, subframe)


class ComparisonViewport(CandidateViewport):
    def __init__(self, bpy, context, candidate, frame, side):
        super().__init__(bpy, context, candidate)
        self.frame = frame
        self.still_camera_tokens = tuple(sorted(set((candidate.selected('A', frame)[1], candidate.selected('B', frame)[1]))))
        self.camera_token = candidate.selected(side, frame)[1]
        self.check_owner()


class PlaybackViewport(CandidateViewport):
    """A fixed alternative plan feeding the existing one-pass preview engine."""
    def __init__(self, bpy, context, candidate, side):
        require(side in ('A', 'B'), 'Unknown playback side.')
        super().__init__(bpy, context, candidate)
        self.side = side
        self._chosen_side = side
        self.shots = validate_shots(candidate.a if side == 'A' else candidate.b)
        self.check_owner()

    def read_shots(self):
        return self.shots

    def check_owner(self):
        super().check_owner()
        require(self.side == self._chosen_side and self.side in ('A', 'B') and
                (self.candidate.a if self.side == 'A' else self.candidate.b) == self.shots,
                'Loaded playback plan changed; stopped without restoring.')
