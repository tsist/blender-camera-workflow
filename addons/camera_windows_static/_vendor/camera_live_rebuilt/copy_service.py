"""Small stdlib-only UI observer for an independent saved-disk copy launcher."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import types
import uuid

REGISTRY_NAME = '_camera_live_saved_copy_registry_v1'
REGISTRY_MARKER = 'camera-live/private-saved-copy/1'
RUNTIME_MANIFEST_SHA = '5d9acb0a5305cb874a4a037278953d53f1134c9269853004598b1939c7f64c74'
LAUNCHER_SHA = '406f9a9f39db50153ceb94e4a40cd0de0e7f0219d0c00d56b74ff268eb263554'
REQUEST_KEYS = {'source_path','source_sha','candidate_path','candidate_sha','output_directory','blender_path'}
CHUNK = 1024 * 1024


def registry():
    existing=sys.modules.get(REGISTRY_NAME)
    if existing is not None:
        if not isinstance(existing,types.ModuleType) or getattr(existing,'marker',None)!=REGISTRY_MARKER or getattr(existing,'version',None)!=1:
            raise RuntimeError('Copy registry ownership conflict')
        # Adopt the known v1 registry from 0.6-v01 without losing its Popen.
        if not hasattr(existing,'epoch'):existing.epoch=0
        if type(existing.epoch)is not int or existing.epoch<0:raise RuntimeError('Copy registry epoch conflict')
        return existing
    slot=types.ModuleType(REGISTRY_NAME)
    slot.marker=REGISTRY_MARKER;slot.version=1;slot.epoch=0
    slot.process=None;slot.control='';slot.request_sha='';slot.status='Idle'
    slot.output='';slot.baseline='';slot.error=''
    sys.modules[REGISTRY_NAME]=slot
    return slot


def busy():return registry().process is not None


def clean(path,directory=False):
    p=Path(path)
    if not p.is_absolute() or '..' in p.parts:raise ValueError('Absolute non-traversing path required')
    for part in (p,*p.parents):
        if part.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError('Reparse path refused')
    mode=p.stat().st_mode
    if not (stat.S_ISDIR(mode) if directory else stat.S_ISREG(mode)):raise ValueError('Unexpected path type')
    return p


def identity(path):
    st=clean(path).stat()
    return [st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns]


def new_output(path):
    p=Path(path)
    if not p.is_absolute() or '..' in p.parts or not p.name or '\\' in p.name:raise ValueError('New absolute output directory required')
    clean(p.parent,True)
    if p.exists() or p.is_symlink():raise ValueError('Output directory already exists')
    return p


def read_json(path,maximum=CHUNK):
    p=clean(path)
    if p.stat().st_size>maximum:raise ValueError('JSON exceeds limit')
    raw=p.read_bytes()
    if len(raw)>maximum:raise ValueError('JSON grew')
    return json.loads(raw),raw


def sha(raw):return hashlib.sha256(raw).hexdigest()


def preflight(request,addon_dir):
    """No writes. Caller checks registration generation before next()/submit()."""
    if busy():raise RuntimeError('A submitted copy is still running or awaiting collection')
    if type(request)is not dict or set(request)!=REQUEST_KEYS or any(type(v)is not str for v in request.values()):raise ValueError('Exact scalar copy request required')
    request=dict(request)
    for key in ('source_sha','candidate_sha'):
        if not re.fullmatch('[0-9a-f]{64}',request[key]):raise ValueError('Invalid input SHA')
    if Path(request['source_path']).suffix.lower()!='.blend':raise ValueError('Saved .blend source required')
    output=new_output(request['output_directory']);addon=clean(addon_dir,True)
    if sys.platform != 'win32':
        raise ValueError('Only qualified Windows Blender 5.3.0 is supported')
    import bpy
    binary=clean(request['blender_path'])
    if tuple(bpy.app.version) < (5, 3, 0) or not binary.samefile(bpy.app.binary_path):
        raise ValueError('Use the current Windows Blender 5.3.0 or later')
    version='.'.join(map(str,bpy.app.version[:2]))
    python=clean(binary.parent / version / 'python/bin/python.exe')
    runtime=clean(addon/'_runtime',True);manifest=runtime/'RUNTIME-PINS.json';launcher=addon/'copy_launcher.py'
    pins,raw=read_json(manifest)
    if sha(raw)!=RUNTIME_MANIFEST_SHA or type(pins)is not dict or len(pins)!=11:raise ValueError('Frozen runtime manifest differs')
    checks=[(binary,None,1024*CHUNK),(python,None,1024*CHUNK),
            (Path(request['source_path']),request['source_sha'],256*CHUNK),
            (Path(request['candidate_path']),request['candidate_sha'],CHUNK),
            (manifest,RUNTIME_MANIFEST_SHA,CHUNK),(launcher,LAUNCHER_SHA,CHUNK)]
    for name,expected in pins.items():
        if Path(name).is_absolute() or '..'in Path(name).parts:raise ValueError('Invalid runtime member')
        checks.append((runtime/name,expected,CHUNK))
    identities={}
    for path,expected,limit in checks:
        path=clean(path);before=identity(path)
        if before[2]>limit:raise ValueError('Input exceeds supported size')
        h=hashlib.sha256();count=0
        with path.open('rb') as f:
            while True:
                raw=f.read(CHUNK)
                if not raw:break
                count+=len(raw)
                if count>limit:raise ValueError('Input grew')
                h.update(raw)
                yield 'Checking '+path.name
        if identity(path)!=before or (expected is not None and h.hexdigest()!=expected):raise ValueError('Input identity/SHA differs: '+str(path))
        identities[str(path)]=before
    new_output(str(output))
    return {'request':request,'identities':identities,'python':str(python),'launcher':str(launcher),'runtime':str(runtime)}


def write_new(path,raw):
    with Path(path).open('xb') as f:
        if f.write(raw)!=len(raw):raise OSError('Short control write')
        f.flush();os.fsync(f.fileno())


def submit(prepared):
    slot=registry()
    if slot.process is not None:raise RuntimeError('Copy already submitted')
    request=dict(prepared['request']);output=new_output(request['output_directory'])
    for path,expected in prepared['identities'].items():
        if identity(path)!=expected:raise ValueError('Input changed after preflight')
    control=output.parent/('.'+output.name+'.camera-copy-'+uuid.uuid4().hex)
    control.mkdir(mode=0o700)
    slot.control=str(control);slot.output='';slot.baseline='';slot.error='';slot.status='Submitting'
    request.update({'control_directory':str(control),'runtime_directory':prepared['runtime']})
    raw=(json.dumps(request,sort_keys=True,indent=2)+'\n').encode();slot.request_sha=sha(raw)
    try:
        write_new(control/'request.json',raw)
        env=dict(os.environ);env.pop('PYTHONPATH',None);env.pop('PYTHONHOME',None)
        with (control/'launcher.log').open('xb') as log:
            process=subprocess.Popen([prepared['python'],'-I','-B',prepared['launcher'],str(control/'request.json'),slot.request_sha],
                stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW,env=env,cwd=str(control))
            slot.process=process  # Retain immediately, including across addon unregister/re-register.
        slot.status='Running independently'
    except Exception as exc:
        slot.status='Failed';slot.error='Submission failed; inspect '+str(control)+': '+str(exc)
        if slot.process is None:raise RuntimeError(slot.error) from exc
    return slot


def verify_terminal(control,request_sha,pid,returncode):
    if type(pid)is not int or pid<=0 or type(returncode)is not int:raise ValueError('Invalid launcher completion identity')
    control=clean(control,True);request,raw=read_json(control/'request.json')
    if type(request)is not dict or set(request)!=REQUEST_KEYS|{'control_directory','runtime_directory'} or any(type(v)is not str for v in request.values()):raise ValueError('Request structure differs')
    if sha(raw)!=request_sha or request.get('control_directory')!=str(control):raise ValueError('Request binding differs')
    terminal,_=read_json(control/'terminal.json')
    if type(terminal)is not dict or type(terminal.get('launcher_pid'))is not int:raise ValueError('Terminal structure differs')
    if terminal.get('schema')!='camera-copy-launcher/1' or terminal.get('request_sha')!=request_sha or terminal.get('control_directory')!=str(control) or terminal.get('output_directory')!=request['output_directory'] or terminal.get('launcher_pid')!=pid:raise ValueError('Launcher terminal binding differs')
    if returncode!=0 or terminal.get('status')!='success':raise ValueError(terminal.get('error','Launcher did not complete normally'))
    if set(terminal)!={'schema','request_sha','control_directory','output_directory','launcher_pid','status','output','output_sha','baseline','baseline_sha','evidence'}:raise ValueError('Unexpected terminal fields')
    for key in ('request_sha','output_sha','baseline_sha'):
        if type(terminal[key])is not str or not re.fullmatch('[0-9a-f]{64}',terminal[key]):raise ValueError('Invalid terminal digest')
    job=clean(request['output_directory'],True)
    if terminal.get('output')!=str(job/'candidate.blend') or terminal.get('baseline')!=str(job/'baseline.json'):raise ValueError('Result path differs')
    expected_names={'SUCCESS.json','apply-child.json','cold_staging-child.json','cold_final-child.json','cold_staging-report.json','cold_final-report.json','baseline.json'}
    evidence=terminal.get('evidence')
    if type(evidence)is not dict or set(evidence)!=expected_names:raise ValueError('Evidence set differs')
    docs={}
    for name,expected in evidence.items():
        doc,data=read_json(job/name)
        if sha(data)!=expected:raise ValueError('Evidence changed after launcher check')
        docs[name]=doc
    success=docs['SUCCESS.json'];stages=('apply','cold_staging','cold_final')
    if success.get('status')!='success' or success.get('output')!=terminal['output'] or success.get('baseline')!=terminal['baseline'] or success.get('output_sha')!=terminal.get('output_sha'):raise ValueError('Helper success differs')
    children=success.get('children')
    if type(children)is not list or len(children)!=3:raise ValueError('Expected three original children')
    pids=[]
    for child,stage in zip(children,stages):
        if child!=docs[stage+'-child.json'] or child.get('stage')!=stage or child.get('waited')is not True or type(child.get('returncode'))is not int or child['returncode']!=0 or child.get('timed_out')is not False or 'interrupted'in child:raise ValueError('Child completion differs')
        if type(child.get('pid'))is not int or child['pid']<=0:raise ValueError('Invalid child identity')
        pids.append(child['pid'])
    if len(set(pids))!=3:raise ValueError('Child identities differ')
    for stage,path in [('cold_staging',job/'staging.blend'),('cold_final',job/'candidate.blend')]:
        cold=docs[stage+'-report.json']
        if set(cold)!={'stage','verified','output_sha','filepath','baseline_sha'} or cold['stage']!=stage or cold['verified']is not True or cold['output_sha']!=terminal['output_sha'] or cold['filepath']!=str(path):raise ValueError('Cold receipt differs')
        if stage=='cold_staging' and cold['baseline_sha']is not None:raise ValueError('Staging baseline differs')
    baseline=docs['baseline.json']
    if cold['baseline_sha']!=terminal.get('baseline_sha') or terminal['baseline_sha']!=evidence['baseline.json'] or baseline.get('source_sha256')!=terminal['output_sha'] or baseline.get('operations')!=[] or baseline.get('base_rows')!=baseline.get('rows') or baseline.get('source_mode')!='SEQUENCE':raise ValueError('Baseline binding differs')
    clean(job/'candidate.blend')  # Existence/type only here; launcher verified full bytes before terminal.
    return terminal


def poll():
    slot=registry();process=slot.process
    if process is None:return slot
    code=process.poll()
    if code is None:return slot
    code=process.wait(timeout=0)  # Never wait on a running launcher.
    slot.process=None
    try:
        terminal=verify_terminal(slot.control,slot.request_sha,process.pid,code)
        slot.status='Success (verified when launcher finished)';slot.output=terminal['output'];slot.baseline=terminal['baseline'];slot.error=''
    except Exception as exc:
        slot.status='Failed';slot.error=str(exc);slot.output='';slot.baseline=''
    return slot
