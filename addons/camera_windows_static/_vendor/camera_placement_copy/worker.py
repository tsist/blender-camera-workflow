"""Private pinned native stages. Only apply changes target Object.location and Camera.lens in a copied file."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import types


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        while True:
            chunk=stream.read(1024*1024)
            if not chunk:break
            h.update(chunk)
    return h.hexdigest()


def load_package(job, pins):
    prefixes = ('camera_live_rebuilt', 'camera_placement_copy')
    if any(k == p or k.startswith(p + '.') for k in sys.modules for p in prefixes):
        raise ValueError('Foreign package owner')
    for prefix in prefixes:
        pkg = types.ModuleType(prefix)
        pkg.__path__ = []
        sys.modules[prefix] = pkg
    def load(name, relative, package=False):
        path = job / relative
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != pins[relative]:
            raise ValueError('Package pin changed')
        spec = importlib.util.spec_from_file_location(name, path, submodule_search_locations=[] if package else None)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        # Relative imports also see already-loaded siblings as attributes.
        if '.' in name:
            parent, child = name.rsplit('.', 1)
            setattr(sys.modules[parent], child, mod)
        exec(compile(raw, str(path), 'exec'), mod.__dict__)
        return mod
    for part in ('core', 'adapter', 'ui_layout', 'candidate_model', 'workbench', 'authoring'):
        load('camera_live_rebuilt.' + part, 'camera_live_rebuilt/' + part + '.py')
    addon = load('camera_live_rebuilt', 'camera_live_rebuilt/__init__.py', True)
    for part in ('core', 'table_model', 'model', 'preservation', 'rig_witness', 'rig_snapshot', 'rig_contract', 'state_contract', 'native'):
        load('camera_placement_copy.' + part, 'camera_placement_copy/' + part + '.py')
    return addon, sys.modules['camera_placement_copy.model'], sys.modules['camera_placement_copy.native']


def main():
    args = sys.argv[sys.argv.index('--') + 1:]
    if len(args) not in (3, 5):
        raise ValueError('Expected config, stage, config SHA')
    config_path, stage, expected_sha = Path(args[0]), args[1], args[2]
    raw = config_path.read_bytes()
    if len(raw) > 1024 * 1024 or hashlib.sha256(raw).hexdigest() != expected_sha:
        raise ValueError('Config fingerprint differs')
    cfg = json.loads(raw)
    job = Path(cfg['job'])
    if config_path != job / 'job.json' or stage not in ('capture', 'apply', 'cold_staging', 'cold_final'):
        raise ValueError('Stage/path differs')
    if (stage == 'capture') != (cfg['mode'] == 'capture'):
        raise ValueError('Config mode differs')
    cold_stage = stage in ('cold_staging','cold_final')
    if len(args) != (5 if cold_stage else 3):
        raise ValueError('Expected parent-pinned apply evidence for cold stage')
    if cold_stage and digest(job/'apply-report.json') != args[3]:
        raise ValueError('Parent-pinned apply report changed')
    import bpy
    if not bpy.app.background or bpy.data.filepath or tuple(bpy.app.version) < (5, 3, 0):
        raise ValueError('Fresh Blender 5.3.0 or later required')
    if '--factory-startup' not in sys.argv or '--disable-autoexec' not in sys.argv or '--offline-mode' not in sys.argv:
        raise ValueError('Required safe flags absent')
    for relative, expected in cfg['package'].items():
        p = Path(relative)
        if p.is_absolute() or '..' in p.parts or digest(job / p) != expected:
            raise ValueError('Package changed')
    if digest(job / 'source.blend') != cfg['source_sha']:
        raise ValueError('Saved source snapshot changed')
    addon, model, native = load_package(job, cfg['package'])
    def write(name, value):
        limit=64*1024*1024 if name=='apply-report.json' else 1024*1024
        count=0
        with (job/name).open('xb') as f:
            for part in json.JSONEncoder(allow_nan=False,separators=(',',':')).iterencode(value):
                raw=part.encode();count+=len(raw)
                if count>limit:raise ValueError('Private report write budget exceeded')
                f.write(raw)
    if stage == 'capture':
        doc = None
    else:
        if digest(job / 'candidate.json') != cfg['candidate_sha']:
            raise ValueError('Candidate snapshot changed')
        doc = model.load_json((job / 'candidate.json').read_bytes())
        if doc['source_sha256'] != cfg['source_sha']:
            raise ValueError('Candidate source differs')
    path = job / ('source.blend' if stage in ('capture', 'apply') else 'staging.blend' if stage == 'cold_staging' else 'candidate.blend')
    if cold_stage and digest(path) != args[4]:
        raise ValueError('Parent-pinned cold file changed before open')
    addon.register()
    try:
        if bpy.ops.wm.open_mainfile(filepath=str(path), load_ui=False, use_scripts=False) != {'FINISHED'}:
            raise ValueError('Open failed')
        if stage == 'capture':
            baseline = native.baseline(bpy, cfg['source_sha'], cfg['scene'], cfg['shot'], cfg['target_mode'], cfg['camera'])
            write('baseline.json', baseline)
            write('capture-report.json', {'verified': True, 'source_sha': cfg['source_sha'], 'scene': cfg['scene'],
                                          'shot': cfg['shot'], 'baseline_sha': digest(job / 'baseline.json')})
            return
        scene, camera = native.check_document(bpy, doc, selected=stage != 'apply')
        before = native.state(bpy, scene)
        if stage == 'apply':
            expected = native.expected_state(before, doc)
            original_projection = native.projection(camera, scene)
            camera.location = doc['location']
            camera.data.lens = doc['lens']
            bpy.context.view_layer.update()
            if camera.data.lens != doc['lens'] or list(camera.location) != doc['location']:
                raise ValueError('Placement/lens write did not match canonical value')
            after = native.state(bpy, scene)
            if native.preservation.fingerprint(after) != native.preservation.fingerprint(expected):
                raise ValueError('Unexpected selected authored-state change')
            output = job / 'staging.blend'
            if output.exists() or output.is_symlink():
                raise ValueError('Staging exists')
            if bpy.ops.wm.save_as_mainfile(filepath=str(output), check_existing=True, copy=True, relative_remap=False) != {'FINISHED'}:
                raise ValueError('Save failed')
            write('apply-report.json', {'output_sha': digest(output), 'before': before, 'expected': expected,
                                       'projection_before': original_projection, 'projection_after': native.projection(camera, scene)})
        else:
            report_path=job/'apply-report.json'
            if report_path.stat().st_size>64*1024*1024:raise ValueError('Strict report exceeds bounded size')
            with report_path.open('rb') as stream:report_raw=stream.read(64*1024*1024+1)
            applied = sys.modules['camera_placement_copy.rig_contract'].parse_report(report_raw)
            if 'strict_rig_scene' not in applied.get('before',{}) and report_path.stat().st_size>1024*1024:raise ValueError('Legacy report exceeds bounded size')
            if digest(job/'apply-report.json') != args[3] or digest(path) != args[4] or applied['output_sha'] != args[4] or native.preservation.fingerprint(before) != native.preservation.fingerprint(applied['expected']):
                raise ValueError('Cold state or output fingerprint differs')
            if native.projection(camera, scene) != applied['projection_after']:
                raise ValueError('Cold projection differs')
            baseline_sha = table_sha = None
            if stage == 'cold_final':
                baseline = native.baseline(bpy, digest(path), doc['scene'], doc['shot'], doc['target_mode'], doc['camera'])
                write('baseline.json', baseline)
                table = model.source_table_snapshot(digest(path),scene.name,scene.camera_live_source,
                          native.preservation.rows_of(scene),sorted(o.name for o in scene.objects if o.type=='CAMERA'))
                write('table-witness.json',table)
                baseline_sha, table_sha = digest(job / 'baseline.json'), digest(job / 'table-witness.json')
            write(stage + '-report.json', {'stage': stage, 'verified': True, 'output_sha': digest(path), 'filepath': str(path),
                                          'baseline_sha': baseline_sha, 'table_witness_sha': table_sha})
    finally:
        addon.unregister()


if __name__ == '__main__':
    main()
