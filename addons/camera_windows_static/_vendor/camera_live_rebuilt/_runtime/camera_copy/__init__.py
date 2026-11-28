"""Private SAVED_DISK copy workflow 0.1. Not public blenderctl."""
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
        if q.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError('Reparse path refused: ' + str(q))
    mode = p.stat().st_mode
    if not (stat.S_ISDIR(mode) if directory else stat.S_ISREG(mode)): raise ValueError('Wrong file type')
    return p


def read_checked(path, expected, limit=MAX_SOURCE):
    if not isinstance(expected,str) or not re.fullmatch('[0-9a-f]{64}',expected): raise ValueError('Invalid SHA256')
    p=clean(path)
    fd=os.open(p,os.O_RDONLY | os.O_BINARY)
    with os.fdopen(fd,'rb') as f:
        st=os.fstat(f.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_size>limit: raise ValueError('Input size/type refused')
        raw=f.read(limit+1)
    if len(raw)>limit or sha(raw)!=expected: raise ValueError('Input SHA mismatch: '+str(p))
    return raw


def exclusive(path, raw):
    """No overwrite/delete. Any partial or replaced output remains for inspection."""
    p=Path(path); clean(p.parent,directory=True)
    fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_BINARY,0o600)
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


def run_child(binary,worker,config,stage,job,expected_config_sha):
    log=job/(stage+'.log'); record={'stage':stage,'waited':False}
    env=dict(os.environ)
    env['BLENDER_USER_RESOURCES'] = str(job)
    for key, folder in (('BLENDER_USER_CONFIG', 'config'), ('BLENDER_USER_DATAFILES', 'datafiles'),
                        ('BLENDER_USER_SCRIPTS', 'scripts'), ('BLENDER_USER_EXTENSIONS', 'extensions'),
                        ('TEMP', 'tmp'), ('TMP', 'tmp')):
        directory=job/('blender_'+folder)
        directory.mkdir(mode=0o700,exist_ok=True);clean(directory,directory=True)
        env[key]=str(directory)
    env.pop('PYTHONPATH',None);env.pop('PYTHONHOME',None)
    with log.open('xb') as f:
        child=subprocess.Popen([str(binary),'--background','--factory-startup','--disable-autoexec','--offline-mode','--threads','2',
            '--python-exit-code','17','--python',str(worker),'--',str(config),stage,expected_config_sha],stdin=subprocess.DEVNULL,stdout=f,stderr=subprocess.STDOUT,env=env,
            creationflags=subprocess.CREATE_NO_WINDOW)
        record['pid']=child.pid
        interrupted=None
        try:
            record['returncode']=child.wait(timeout=TIMEOUT);record['timed_out']=False
        except subprocess.TimeoutExpired:
            child.kill();record['returncode']=child.wait();record['timed_out']=True
        except BaseException as exc:
            interrupted=exc
            child.kill();record['returncode']=child.wait();record['interrupted']=type(exc).__name__
        record['waited']=True
    json_new(job/(stage+'-child.json'),record)
    if interrupted is not None:raise interrupted
    if record['returncode']!=0 or record['timed_out']: raise RuntimeError('Child failed: '+stage)
    return record


def validate_cold_report(path,stage,filepath,expected_sha):
    report=json.loads(clean(path).read_text())
    keys={'stage','verified','output_sha','filepath','baseline_sha'}
    if type(report) is not dict or set(report)!=keys:raise ValueError('Malformed cold receipt')
    if report['stage']!=stage or report['verified'] is not True or report['filepath']!=str(filepath) or report['output_sha']!=expected_sha:
        raise ValueError('Cold receipt binding differs')
    if stage=='cold_staging':
        if report['baseline_sha'] is not None:raise ValueError('Unexpected staging baseline')
    elif not isinstance(report['baseline_sha'],str) or not re.fullmatch('[0-9a-f]{64}',report['baseline_sha']):
        raise ValueError('Invalid final baseline SHA')
    return report


def apply_saved_candidate(source_path, expected_source_sha, candidate_path, expected_candidate_sha,
                          new_output_directory, trusted_blender_path, expected_binary_sha):
    if Path(source_path).suffix.lower() != '.blend': raise ValueError('Source must be .blend')
    if clean(source_path).samefile(clean(candidate_path)): raise ValueError('Duplicate source/candidate')
    source=read_checked(source_path,expected_source_sha)
    candidate=read_checked(candidate_path,expected_candidate_sha,1024*1024)
    binary=clean(trusted_blender_path)
    read_checked(str(binary),expected_binary_sha,1024*1024*1024)
    job=Path(new_output_directory)
    if not job.is_absolute() or '..' in job.parts: raise ValueError('New absolute directory required')
    clean(job.parent,directory=True)
    job.mkdir(mode=0o700)  # exclusive, no exist_ok; never reuse a consumed job
    identity=(job.stat().st_dev,job.stat().st_ino)
    def check_inputs():
        clean(job,directory=True)
        if (job.stat().st_dev,job.stat().st_ino)!=identity: raise RuntimeError('Job directory replaced')
        read_checked(source_path,expected_source_sha);read_checked(candidate_path,expected_candidate_sha,1024*1024)
        read_checked(str(binary),expected_binary_sha,1024*1024*1024)
    try:
        root=Path(__file__).resolve().parent.parent
        pins=json.loads((root/'RUNTIME-PINS.json').read_text())
        for name,expected in pins.items():read_checked(str(root/name),expected,1024*1024)
        exclusive(job/'source.blend',source);exclusive(job/'candidate.json',candidate)
        root=Path(__file__).resolve().parent.parent
        package={}
        for folder in ('camera_copy','camera_live_rebuilt'):
            (job/folder).mkdir()
            for p in sorted((root/folder).glob('*.py')):
                rel=folder+'/'+p.name
                if rel not in pins:raise RuntimeError('Unpinned package file')
                raw=read_checked(str(p),pins[rel],1024*1024);package[rel]=exclusive(job/rel,raw)
        if len([k for k in package if k.startswith('camera_live_rebuilt/')])!=7: raise RuntimeError('Addon layout differs')
        config={'job':str(job),'source_directory':str(Path(source_path).parent),'source_sha':expected_source_sha,'candidate_sha':expected_candidate_sha,'package':package}
        config_sha=json_new(job/'job.json',config)
        def check_snapshots():
            read_checked(str(job/'job.json'),config_sha,1024*1024)
            read_checked(str(job/'source.blend'),expected_source_sha)
            read_checked(str(job/'candidate.json'),expected_candidate_sha,1024*1024)
            for name,expected in package.items():
                read_checked(str(job/name),expected,1024*1024)
        children=[]
        for stage in ('apply','cold_staging'):
            check_inputs();check_snapshots()
            children.append(run_child(binary,job/'camera_copy/worker.py',job/'job.json',stage,job,config_sha))
        apply=json.loads((job/'apply-report.json').read_text())
        stage_raw=read_checked(str(job/'staging.blend'),apply['output_sha'])
        check_snapshots()
        validate_cold_report(job/'cold_staging-report.json','cold_staging',job/'staging.blend',sha(stage_raw))
        final_sha=exclusive(job/'candidate.blend',stage_raw)
        check_inputs();check_snapshots()
        children.append(run_child(binary,job/'camera_copy/worker.py',job/'job.json','cold_final',job,config_sha))
        check_inputs();read_checked(str(job/'candidate.blend'),final_sha)
        read_checked(str(job/'source.blend'),expected_source_sha)
        read_checked(str(job/'candidate.json'),expected_candidate_sha,1024*1024)
        check_snapshots()
        for name,expected in pins.items():read_checked(str(root/name),expected,1024*1024)
        final_report=validate_cold_report(job/'cold_final-report.json','cold_final',job/'candidate.blend',final_sha)
        read_checked(str(job/'baseline.json'),final_report['baseline_sha'],1024*1024)
        result={'status':'success','workflow':'private SAVED_DISK 0.1','output':str(job/'candidate.blend'),
            'output_sha':final_sha,'baseline':str(job/'baseline.json'),'children':children,
            'limitations':'Selected protection only; no GUI/render/public CLI acceptance.'}
        json_new(job/'SUCCESS.json',result)
        return result
    except Exception as exc:
        # Leave evidence and partial outputs. Never remove or retry a consumed directory.
        try: json_new(job/'FAILURE.json',{'status':'failed','error':str(exc),'job':str(job),'outputs_retained':True})
        except Exception: pass
        raise RuntimeError('Copy failed; inspect retained job '+str(job)+': '+str(exc)) from exc
