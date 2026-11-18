"""Private static-placement saved-disk core. IO and child ownership adapted from frozen SAVED_DISK0.1; not public blenderctl."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess

MAX_SOURCE = 256 * 1024 * 1024
TIMEOUT = 120


def sha(raw): return hashlib.sha256(raw).hexdigest()


def clean(path, directory=False):
    p = Path(path)
    if not p.is_absolute() or '..' in p.parts: raise ValueError('Absolute non-traversing path required')
    for q in (p, *p.parents):
        if stat.S_ISLNK(q.lstat().st_mode): raise ValueError('Symlink refused: ' + str(q))
    mode = p.stat().st_mode
    if not (stat.S_ISDIR(mode) if directory else stat.S_ISREG(mode)): raise ValueError('Wrong file type')
    return p


def read_checked(path, expected, limit=MAX_SOURCE):
    if not isinstance(expected,str) or not re.fullmatch('[0-9a-f]{64}',expected): raise ValueError('Invalid SHA256')
    p=clean(path)
    fd=os.open(p,os.O_RDONLY | getattr(os,'O_NOFOLLOW',0) | getattr(os,'O_NONBLOCK',0))
    with os.fdopen(fd,'rb') as f:
        st=os.fstat(f.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_size>limit: raise ValueError('Input size/type refused')
        raw=f.read(limit+1)
    if len(raw)>limit or sha(raw)!=expected: raise ValueError('Input SHA mismatch: '+str(p))
    return raw


def exclusive(path, raw):
    """No overwrite/delete. Any partial or replaced output remains for inspection."""
    p=Path(path); clean(p.parent,directory=True)
    fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
    with os.fdopen(fd,'wb') as f:
        st=os.fstat(f.fileno()); identity=(st.st_dev,st.st_ino)
        if f.write(raw)!=len(raw): raise OSError('Short write; partial output retained: '+str(p))
        f.flush();os.fsync(f.fileno())
    now=p.lstat()
    if not stat.S_ISREG(now.st_mode) or (now.st_dev,now.st_ino)!=identity: raise OSError('Output replaced: '+str(p))
    if read_checked(str(p),sha(raw),max(len(raw),1))!=raw: raise OSError('Readback differs')
    return sha(raw)


def json_new(path,value):
    return exclusive(path,(json.dumps(value,indent=2,sort_keys=True,allow_nan=False)+'\n').encode())


def run_child(binary,worker,config,stage,job,expected_config_sha,stage_pins=()):
    log=job/(stage+'.log'); record={'stage':stage,'waited':False}
    env=dict(os.environ)
    for key,folder in [('BLENDER_USER_CONFIG','config'),('BLENDER_USER_DATAFILES','datafiles'),('BLENDER_USER_SCRIPTS','scripts'),('XDG_CONFIG_HOME','xdg_config'),('XDG_CACHE_HOME','xdg_cache'),('TMPDIR','tmp')]:
        directory=job/('blender_'+folder)
        directory.mkdir(mode=0o700,exist_ok=True);clean(directory,directory=True)
        env[key]=str(directory)
    env.pop('PYTHONPATH',None);env.pop('PYTHONHOME',None)
    with log.open('xb') as f:
        child=subprocess.Popen([str(binary),'--background','--factory-startup','--disable-autoexec','--offline-mode','--threads','2',
            '--python-exit-code','17','--python',str(worker),'--',str(config),stage,expected_config_sha,*stage_pins],stdout=f,stderr=subprocess.STDOUT,env=env)
        record['pid']=child.pid
        interrupted=None
        try:
            record['returncode']=child.wait(timeout=TIMEOUT);record['timed_out']=False
        except subprocess.TimeoutExpired:
            child.kill();record['returncode']=child.wait();record['timed_out']=True
        except BaseException as exc:
            interrupted=exc
            if child.poll() is None:child.kill()
            record['returncode']=child.wait();record['interrupted']=type(exc).__name__
        record['waited']=True
    json_new(job/(stage+'-child.json'),record)
    if interrupted is not None:raise interrupted
    if record['returncode']!=0 or record['timed_out']: raise RuntimeError('Child failed: '+stage)
    return record


OFFICIAL_BINARY_SHA = 'c2fd82553c979a7f6ba85202c487aa1173c90db588a67d74d70cc7b0c2bea01c'


def sha_report(path):
    p=clean(path)
    with p.open('rb') as stream:raw=stream.read(64*1024*1024+1)
    if len(raw)>64*1024*1024:raise ValueError('Report hash size exceeded')
    return sha(raw)

def _json(path,limit=1024*1024):
    from . import table_model
    p = clean(path)
    if p.stat().st_size > limit:
        raise ValueError('Receipt exceeds bounded JSON size')
    with p.open('rb') as stream:raw=stream.read(limit+1)
    if len(raw)>limit:raise ValueError('Report grew beyond bounded size')
    if limit>1024*1024:
        from . import rig_contract
        return rig_contract.parse_report(raw)
    return table_model.parse_json(raw)


def _prepare(source_path, source_sha, output_directory, binary_path, runtime_manifest_sha, candidate_path=None, candidate_sha=None):
    from . import model
    if Path(source_path).suffix.lower() != '.blend':
        raise ValueError('Saved .blend source required')
    source = read_checked(source_path, source_sha)
    binary = clean(binary_path)
    if binary.name != 'blender':
        raise ValueError('Official Blender binary required')
    read_checked(str(binary), OFFICIAL_BINARY_SHA, 1024 * 1024 * 1024)
    candidate = None
    if candidate_path is not None:
        if clean(source_path).samefile(clean(candidate_path)):
            raise ValueError('Source/candidate identity conflict')
        candidate = read_checked(candidate_path, candidate_sha, model.MAX_BYTES)
        doc = model.load_json(candidate)
        if doc['source_sha256'] != source_sha:
            raise ValueError('Candidate saved-source fingerprint differs')
    root = Path(__file__).resolve().parent.parent
    manifest_path = root / 'RUNTIME-PINS.json'
    manifest = read_checked(manifest_path, runtime_manifest_sha, 1024 * 1024)
    pins = model.table_model.parse_json(manifest)
    expected_files = {str(p.relative_to(root)) for folder in ('camera_placement_copy', 'camera_live_rebuilt')
                      for p in (root / folder).glob('*.py')}
    if type(pins) is not dict or set(pins) != expected_files:
        raise ValueError('Runtime manifest/package layout differs')
    package_bytes = {name: read_checked(root / name, expected, 1024 * 1024) for name, expected in pins.items()}
    job = Path(output_directory)
    if not job.is_absolute() or '..' in job.parts:
        raise ValueError('New absolute job directory required')
    clean(job.parent, directory=True)
    job.mkdir(mode=0o700)
    identity = job.stat().st_dev, job.stat().st_ino
    try:
        exclusive(job / 'source.blend', source)
        if candidate is not None:
            exclusive(job / 'candidate.json', candidate)
        for folder in ('camera_placement_copy', 'camera_live_rebuilt'):
            (job / folder).mkdir()
        package = {name: exclusive(job / name, data) for name, data in package_bytes.items()}
    except BaseException as exc:
        _failure(job, exc)
        raise
    def check():
        clean(job, directory=True)
        if (job.stat().st_dev, job.stat().st_ino) != identity:
            raise ValueError('Job directory identity changed')
        read_checked(source_path, source_sha)
        read_checked(binary, OFFICIAL_BINARY_SHA, 1024 * 1024 * 1024)
        read_checked(manifest_path, runtime_manifest_sha, 1024 * 1024)
        read_checked(job / 'source.blend', source_sha)
        if candidate is not None:
            read_checked(candidate_path, candidate_sha, model.MAX_BYTES)
            read_checked(job / 'candidate.json', candidate_sha, model.MAX_BYTES)
        for name, expected in package.items():
            read_checked(root / name, expected, 1024 * 1024)
            read_checked(job / name, expected, 1024 * 1024)
    return job, binary, package, check


def _failure(job, exc):
    try:
        json_new(job / 'FAILURE.json', {'status': 'failed', 'error': str(exc), 'exception': type(exc).__name__,
                                     'outputs_retained': True, 'job': str(job)})
    except Exception:
        pass


def capture_saved_placement(source_path, source_sha, scene, shot, output_directory, binary_path, runtime_manifest_sha, *, target_mode='SEQUENCE_SHOT', camera=None):
    from . import model
    model._name(scene)
    if target_mode=='SEQUENCE_SHOT':model._name(shot)
    elif target_mode=='NAMED_CAMERA' and shot is None:model._name(camera)
    else:raise ValueError('Invalid target selector')
    if camera is not None:model._name(camera)
    job, binary, package, check = _prepare(source_path, source_sha, output_directory, binary_path, runtime_manifest_sha)
    try:
        cfg = {'mode': 'capture', 'job': str(job), 'source_sha': source_sha, 'scene': scene, 'shot': shot, 'target_mode':target_mode, 'camera':camera, 'package': package}
        cfg_sha = json_new(job / 'job.json', cfg)
        check()
        child = run_child(binary, job / 'camera_placement_copy/worker.py', job / 'job.json', 'capture', job, cfg_sha)
        check()
        read_checked(job / 'job.json', cfg_sha, 1024 * 1024)
        receipt = _json(job / 'capture-report.json')
        if type(receipt) is not dict or set(receipt) != {'verified','source_sha','scene','shot','baseline_sha'} or receipt['verified'] is not True:
            raise ValueError('Malformed capture receipt')
        if receipt['source_sha'] != source_sha or receipt['scene'] != scene or receipt['shot'] != shot:
            raise ValueError('Capture receipt identity differs')
        baseline = model.load_json(read_checked(job / 'baseline.json', receipt['baseline_sha'], model.MAX_BYTES))
        if baseline['source_sha256'] != source_sha or baseline['scene'] != scene or baseline['shot'] != shot or baseline['base_lens'] != baseline['lens'] or baseline['location'] != baseline['base_pose']['location'] or baseline['target_mode'] != target_mode or (camera is not None and baseline['camera'] != camera):
            raise ValueError('Captured baseline differs')
        result = {'status':'success', 'workflow':'private static placement capture/1', 'baseline':str(job/'baseline.json'),
                  'baseline_sha':receipt['baseline_sha'], 'source_sha':source_sha, 'children':[child]}
        json_new(job/'SUCCESS.json', result)
        return result
    except BaseException as exc:
        _failure(job, exc)
        raise


def _cold(path, stage, output, output_sha):
    r = _json(path)
    if type(r) is not dict or set(r) != {'stage','verified','output_sha','filepath','baseline_sha','table_witness_sha'}:
        raise ValueError('Malformed cold receipt')
    if r['stage'] != stage or r['verified'] is not True or r['output_sha'] != output_sha or r['filepath'] != str(output):
        raise ValueError('Cold receipt binding differs')
    for field in ('baseline_sha','table_witness_sha'):
        if stage == 'cold_staging':
            if r[field] is not None:
                raise ValueError('Unexpected staging baseline')
        elif type(r[field]) is not str or re.fullmatch('[0-9a-f]{64}',r[field]) is None:
            raise ValueError('Malformed baseline hash')
    return r


def apply_saved_placement(source_path, source_sha, candidate_path, candidate_sha, output_directory, binary_path, runtime_manifest_sha):
    from . import model, state_contract
    job, binary, package, check = _prepare(source_path, source_sha, output_directory, binary_path, runtime_manifest_sha, candidate_path, candidate_sha)
    try:
        doc = model.load_json(read_checked(job/'candidate.json', candidate_sha, model.MAX_BYTES))
        cfg = {'mode':'apply', 'job':str(job), 'source_sha':source_sha, 'candidate_sha':candidate_sha, 'package':package}
        cfg_sha = json_new(job/'job.json', cfg)
        def snapshots():
            check()
            read_checked(job/'job.json', cfg_sha, 1024*1024)
        snapshots()
        children = [run_child(binary, job/'camera_placement_copy/worker.py', job/'job.json', 'apply', job, cfg_sha)]
        snapshots()
        report_path=clean(job/'apply-report.json')
        if report_path.stat().st_size>64*1024*1024:raise ValueError('Strict report exceeds bounded size')
        applied_sha = sha(read_checked(report_path,sha_report(report_path),64*1024*1024))
        applied = _json(report_path,64*1024*1024)
        report_limit=64*1024*1024 if 'strict_rig_scene' in applied.get('before',{}) else 1024*1024
        if report_path.stat().st_size>report_limit:raise ValueError('Report exceeds applicable bounded size')
        if type(applied) is not dict or set(applied) != {'output_sha','before','expected','projection_before','projection_after'}:
            raise ValueError('Malformed apply receipt')
        state_contract.verify_apply(applied,doc)
        raw = read_checked(job/'staging.blend', applied['output_sha'])
        stage_pins = (applied_sha, sha(raw))
        def applied_pins():
            read_checked(job/'apply-report.json', applied_sha, report_limit)
            read_checked(job/'staging.blend', stage_pins[1])
        applied_pins();snapshots()
        children.append(run_child(binary, job/'camera_placement_copy/worker.py', job/'job.json', 'cold_staging', job, cfg_sha, stage_pins))
        applied_pins();snapshots()
        _cold(job/'cold_staging-report.json', 'cold_staging', job/'staging.blend', sha(raw))
        final_sha = exclusive(job/'candidate.blend', raw)
        snapshots()
        children.append(run_child(binary, job/'camera_placement_copy/worker.py', job/'job.json', 'cold_final', job, cfg_sha, stage_pins))
        applied_pins();snapshots()
        read_checked(job/'candidate.blend', final_sha)
        cold = _cold(job/'cold_final-report.json', 'cold_final', job/'candidate.blend', final_sha)
        baseline = model.load_json(read_checked(job/'baseline.json', cold['baseline_sha'], model.MAX_BYTES))
        table = model.validate_source_table(model.table_model.parse_json(read_checked(job/'table-witness.json', cold['table_witness_sha'], model.MAX_BYTES)))
        expected_baseline = model.export_snapshot(final_sha,doc['scene'],doc['source_mode'],doc['base_rows'],doc['catalog'],doc['shot'],doc['camera_data'],doc['lens'],state_contract.selected_pose(doc),target_mode=doc['target_mode'],camera=doc['camera'])
        if baseline != expected_baseline:
            raise ValueError('Fresh optical baseline differs')
        expected_table = model.source_table_snapshot(final_sha,doc['scene'],doc['source_mode'],doc['base_rows'],doc['catalog'])
        if table != expected_table:
            raise ValueError('Fresh table baseline differs')
        result = {'status':'success', 'workflow':'private static placement apply/1', 'output':str(job/'candidate.blend'),
                  'output_sha':final_sha, 'baseline':str(job/'baseline.json'), 'baseline_sha':cold['baseline_sha'],
                  'table_witness':str(job/'table-witness.json'), 'table_witness_sha':cold['table_witness_sha'],
                  'children':children, 'limits':'Static location/lens, fixed orientation, no target DOF, conservative ownership gates and selected authored/evaluated witnesses. No motion or public CLI/artistic qualification; standalone table witness is not a legacy table candidate.'}
        json_new(job/'SUCCESS.json', result)
        return result
    except BaseException as exc:
        _failure(job, exc)
        raise

