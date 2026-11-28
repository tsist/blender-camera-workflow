"""Private bounded child entry; three separate factory processes, no public runner injection."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import types


def load_pinned(job, pins):
    prefix='camera_live_rebuilt'
    if any(k==prefix or k.startswith(prefix+'.') for k in sys.modules): raise ValueError('Foreign module owner')
    pkg=types.ModuleType(prefix);pkg.__path__=[];sys.modules[prefix]=pkg
    def load(name,relative,package=False):
        p=job/relative;raw=p.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=pins[relative]:raise ValueError('Package SHA changed')
        spec=importlib.util.spec_from_file_location(name,p,submodule_search_locations=[] if package else None)
        m=importlib.util.module_from_spec(spec);sys.modules[name]=m
        exec(compile(raw,str(p),'exec'),m.__dict__);return m
    for name in ('core','adapter','ui_layout','candidate_model','workbench','authoring'):
        load(prefix+'.'+name,prefix+'/'+name+'.py')
    addon=load(prefix,prefix+'/__init__.py',True)
    domain=load('_camera_copy_domain','camera_copy/domain.py')
    return addon,sys.modules[prefix+'.candidate_model'],domain


def reject_scene_animation(scene):
    a=scene.animation_data
    if a and (a.action or len(a.drivers) or len(a.nla_tracks)):
        raise ValueError('Scene action/driver/NLA unsupported (not only shot-table animation)')


def apply_rows(scene, rows):
    current=list(scene.camera_live_shots)
    if len(current)!=len(rows) or [r.name for r in current]!=[r['name'] for r in rows]:
        raise ValueError('Row count/name/order differs')
    cameras=[scene.objects.get(r['camera']) for r in rows]
    if any(c is None or c.type!='CAMERA' for c in cameras):raise ValueError('Camera missing')
    for item,row,camera in zip(current,rows,cameras):
        if item.camera!=camera:item.camera=camera
        if item.first!=row['first']:item.first=row['first']
        if item.last!=row['last']:item.last=row['last']


def extras(scene):
    # Row ID properties are explicitly retained; hand-authored sentinels are selected witnesses.
    def value(v):
        if hasattr(v,'to_dict'):return v.to_dict()
        if hasattr(v,'to_list'):return v.to_list()
        return v
    return {'rows':[{k:value(r[k]) for k in r.keys() if k not in {'name','camera','first','last'}} for r in scene.camera_live_shots],
            'scene_sentinel':value(scene.get('camera_copy_sentinel')),
            'object_sentinels':{o.name:value(o.get('camera_copy_sentinel')) for o in scene.objects}}


def main_id_roster(bpy):
    """Main IDs only, excluding UI and embedded IDs; users count intentionally absent."""
    result=[]
    for prop in bpy.data.bl_rna.properties:
        if prop.type!='COLLECTION':continue
        for block in getattr(bpy.data,prop.identifier,()):
            if not isinstance(block,bpy.types.ID) or getattr(block,'is_embedded_data',False):continue
            kind=block.bl_rna.identifier
            if kind in {'Screen','WorkSpace','WindowManager'}:continue
            result.append([prop.identifier,kind,block.name,bool(block.use_fake_user)])
    return sorted(result)


def main():
    args=sys.argv[sys.argv.index('--')+1:];config_path=Path(args[0]);stage=args[1]
    raw=config_path.read_bytes()
    if len(args)!=3 or hashlib.sha256(raw).hexdigest()!=args[2]:raise ValueError('Config SHA differs before parse')
    cfg=json.loads(raw);job=Path(cfg['job'])
    import bpy
    if config_path!=job/'job.json' or stage not in ('apply','cold_staging','cold_final'):raise ValueError('Invalid child request')
    if (sys.platform != 'win32' or not bpy.app.background or bpy.data.filepath
            or tuple(bpy.app.version) < (5, 3, 0)):
        raise ValueError('Fresh Windows Blender 5.3.0 or later is required')
    if bpy.app.online_access or not {'--factory-startup', '--disable-autoexec', '--offline-mode'} <= set(sys.argv):
        raise ValueError('Offline factory startup required')
    for rel,expected in cfg['package'].items():
        if Path(rel).is_absolute() or '..' in Path(rel).parts or hashlib.sha256((job/rel).read_bytes()).hexdigest()!=expected:raise ValueError('Package changed')
    addon,model,d=load_pinned(job,cfg['package'])
    def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
    def write(name,obj):
        with (job/name).open('x') as f:json.dump(obj,f,indent=2,allow_nan=False)
    if digest(job/'source.blend')!=cfg['source_sha'] or digest(job/'candidate.json')!=cfg['candidate_sha']:raise ValueError('Snapshot changed')
    doc=model.load_json((job/'candidate.json').read_bytes())
    if doc['source_sha256']!=cfg['source_sha']:raise ValueError('Candidate source differs')
    path=job/('source.blend' if stage=='apply' else 'staging.blend' if stage=='cold_staging' else 'candidate.blend')
    addon.register()
    try:
        if bpy.ops.wm.open_mainfile(filepath=str(path),load_ui=False,use_scripts=False)!={'FINISHED'}:raise ValueError('Open failed')
        d.reject_unpreserved(bpy)
        textures = {}
        for image in bpy.data.images:
            if image.source != 'FILE':
                continue
            if image.packed_file:
                textures[image.name] = hashlib.sha256(image.packed_file.data).hexdigest()
                continue
            # The input snapshot lives in the job. Resolve relative FILE images against the original.
            source_dir = cfg['source_directory'] if stage == 'apply' else str(path.parent)
            texture = Path(bpy.path.abspath(image.filepath, start=source_dir)).resolve(strict=True)
            if not texture.is_file():
                raise ValueError('Missing texture: ' + str(texture))
            with texture.open('rb') as stream:
                textures[image.name] = hashlib.file_digest(stream, 'sha256').hexdigest()
            if stage == 'apply':
                image.filepath = bpy.path.relpath(str(texture), start=str(job))
        
        scene=bpy.data.scenes.get(doc['scene'])
        if scene is None:raise ValueError('Scene absent')
        reject_scene_animation(scene)
        sys.modules['camera_live_rebuilt.adapter'].validate_camera_markers(scene.timeline_markers)
        catalog=sorted(o.name for o in scene.objects if o.type=='CAMERA')
        if catalog!=doc['catalog'] or scene.camera_live_source!='SEQUENCE':raise ValueError('Catalog/mode differs')
        before={'protected':d.protected(bpy,scene),'extras':extras(scene),'main_ids':main_id_roster(bpy),'textures':textures}
        if stage=='apply':
            if d.rows_of(scene)!=doc['base_rows']:raise ValueError('Saved baseline differs')
            apply_rows(scene,doc['rows'])
            if d.rows_of(scene)!=doc['rows']:raise ValueError('Applied rows differ')
            after={'protected':d.protected(bpy,scene),'extras':extras(scene),'main_ids':main_id_roster(bpy),'textures':textures}
            if d.fingerprint(before)!=d.fingerprint(after):raise ValueError('Selected protected fields changed')
            output=job/'staging.blend'
            if output.exists() or output.is_symlink():raise ValueError('Staging exists')
            if bpy.ops.wm.save_as_mainfile(filepath=str(output),check_existing=True,copy=True,relative_remap=False)!={'FINISHED'}:raise ValueError('Save failed')
            write('apply-report.json',{'output_sha':digest(output),'selected':before,'rows':doc['rows']})
        else:
            report=json.loads((job/'apply-report.json').read_text())
            if digest(path)!=report['output_sha'] or d.rows_of(scene)!=doc['rows'] or d.fingerprint(before)!=d.fingerprint(report['selected']):raise ValueError('Cold selected state differs')
            if stage=='cold_final':
                baseline=model.export_snapshot(digest(path),scene.name,scene.camera_live_source,d.rows_of(scene),catalog)
                write('baseline.json',baseline)
                loaded=sys.modules['camera_live_rebuilt.workbench'].Candidate(bpy,scene,str(job/'baseline.json'))
                if loaded.document['operations'] or loaded.document['base_rows']!=doc['rows']:raise ValueError('New baseline invalid')
            write(stage+'-report.json',{'stage':stage,'verified':True,'output_sha':digest(path),'filepath':bpy.data.filepath,
                'baseline_sha':digest(job/'baseline.json') if stage=='cold_final' else None})
    finally:addon.unregister()


if __name__=='__main__':main()
