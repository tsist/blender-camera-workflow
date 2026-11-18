"""Isolated official-Python launcher for the frozen private SAVED_DISK helper."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys

RUNTIME_MANIFEST_SHA = '99c12cc7c97081f9a9dbf0c91e83d6c98b0bc6442241c61fd2e54e5036bdc76d'
BLENDER_SHA = 'c2fd82553c979a7f6ba85202c487aa1173c90db588a67d74d70cc7b0c2bea01c'
PYTHON_SHA = '940551e8051d3daf320c30b9671e3fefe079b471f1a57a9d4b77466560b30043'


def clean(path):
    p=Path(path)
    if not p.is_absolute() or '..' in p.parts:raise ValueError('Invalid path')
    for part in (p,*p.parents):
        if stat.S_ISLNK(part.lstat().st_mode):raise ValueError('Symlink refused')
    return p


def digest(path):
    p=clean(path)
    if not stat.S_ISREG(p.stat().st_mode):raise ValueError('Regular file required')
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def read_json(path,maximum=1024*1024,expected_sha=None):
    p=clean(path)
    if not stat.S_ISREG(p.stat().st_mode) or p.stat().st_size>maximum:raise ValueError('Bounded regular JSON required')
    raw=p.read_bytes()
    if len(raw)>maximum:raise ValueError('JSON grew')
    if expected_sha is not None and hashlib.sha256(raw).hexdigest()!=expected_sha:
        raise ValueError('JSON SHA differs')
    return json.loads(raw)


def verified_result(request):
    job=clean(request['output_directory']);success=read_json(job/'SUCCESS.json')
    output=job/'candidate.blend';baseline=job/'baseline.json'
    if success.get('status')!='success' or success.get('output')!=str(output) or success.get('baseline')!=str(baseline):raise ValueError('Helper success binding differs')
    children=success.get('children')
    if type(children)is not list or len(children)!=3:raise ValueError('Three child records required')
    pids=[]
    for child,stage in zip(children,('apply','cold_staging','cold_final')):
        persisted=read_json(job/(stage+'-child.json'))
        if child!=persisted or child.get('stage')!=stage or child.get('waited')is not True or type(child.get('returncode'))is not int or child['returncode']!=0 or child.get('timed_out')is not False or 'interrupted'in child:raise ValueError('Child not normally reaped')
        if type(child.get('pid'))is not int or child['pid']<=0:raise ValueError('Invalid child PID')
        pids.append(child['pid'])
    if len(set(pids))!=3:raise ValueError('Child identities reused')
    output_sha=digest(output)
    if success.get('output_sha')!=output_sha:raise ValueError('Output SHA differs')
    for stage,path in [('cold_staging',job/'staging.blend'),('cold_final',output)]:
        cold=read_json(job/(stage+'-report.json'))
        if set(cold)!={'stage','verified','output_sha','filepath','baseline_sha'} or cold['stage']!=stage or cold['verified']is not True or cold['filepath']!=str(path) or cold['output_sha']!=output_sha:raise ValueError('Cold binding differs')
        if stage=='cold_staging' and cold['baseline_sha']is not None:raise ValueError('Unexpected staging baseline')
    baseline_sha=digest(baseline)
    if cold['baseline_sha']!=baseline_sha:raise ValueError('Baseline SHA differs')
    doc=read_json(baseline)
    if doc.get('source_sha256')!=output_sha or doc.get('operations')!=[] or doc.get('base_rows')!=doc.get('rows') or doc.get('source_mode')!='SEQUENCE':raise ValueError('Baseline not rebound')
    if digest(request['source_path'])!=request['source_sha'] or digest(request['candidate_path'])!=request['candidate_sha']:raise ValueError('Original inputs changed')
    evidence={name:digest(job/name) for name in ('SUCCESS.json','apply-child.json','cold_staging-child.json','cold_final-child.json','cold_staging-report.json','cold_final-report.json','baseline.json')}
    return {'output':str(output),'output_sha':output_sha,'baseline':str(baseline),'baseline_sha':baseline_sha,'evidence':evidence}


def main():
    if len(sys.argv)!=3:raise ValueError('Expected request path and SHA')
    path=clean(sys.argv[1]);expected=sys.argv[2]
    request=read_json(path,expected_sha=expected);control=path.parent
    if type(request)is not dict or set(request)!={'source_path','source_sha','candidate_path','candidate_sha','output_directory','blender_path','control_directory','runtime_directory'} or any(type(v)is not str for v in request.values()):raise ValueError('Exact scalar request required')
    if request['control_directory']!=str(control) or path.name!='request.json':raise ValueError('Control binding differs')
    terminal={'schema':'camera-copy-launcher/1','request_sha':expected,'control_directory':str(control),'output_directory':request['output_directory'],'launcher_pid':os.getpid(),'status':'failed'}
    try:
        if not sys.flags.isolated or not sys.dont_write_bytecode:raise ValueError('Isolated no-bytecode Python required')
        if digest(sys.executable)!=PYTHON_SHA or digest(request['blender_path'])!=BLENDER_SHA:raise ValueError('Official executable SHA differs')
        runtime=clean(request['runtime_directory'])
        if runtime!=Path(__file__).resolve().parent/'_runtime':raise ValueError('Fixed runtime layout required')
        manifest=runtime/'RUNTIME-PINS.json'
        pins=read_json(manifest,expected_sha=RUNTIME_MANIFEST_SHA)
        for name,expected_sha in pins.items():
            if Path(name).is_absolute() or '..'in Path(name).parts or digest(runtime/name)!=expected_sha:raise ValueError('Frozen runtime source differs')
        if 'camera_copy'in sys.modules:raise ValueError('Foreign helper owner')
        spec=importlib.util.spec_from_file_location('camera_copy',runtime/'camera_copy/__init__.py',submodule_search_locations=[])
        helper=importlib.util.module_from_spec(spec);sys.modules['camera_copy']=helper
        raw=(runtime/'camera_copy/__init__.py').read_bytes()
        if hashlib.sha256(raw).hexdigest()!=pins['camera_copy/__init__.py']:raise ValueError('Helper changed')
        exec(compile(raw,str(runtime/'camera_copy/__init__.py'),'exec'),helper.__dict__)
        helper.apply_saved_candidate(request['source_path'],request['source_sha'],request['candidate_path'],request['candidate_sha'],request['output_directory'],request['blender_path'],BLENDER_SHA)
        terminal.update(verified_result(request));terminal['status']='success'
    except Exception as exc:
        terminal['error']=str(exc)
    with (control/'terminal.json').open('x',encoding='utf-8') as f:
        json.dump(terminal,f,indent=2,allow_nan=False);f.flush();os.fsync(f.fileno())
    return 0 if terminal['status']=='success' else 1

if __name__=='__main__':sys.exit(main())
