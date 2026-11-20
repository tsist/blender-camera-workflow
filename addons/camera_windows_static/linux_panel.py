"""Original add-on's Linux entry: bounded static optics CHECK and new-copy APPLY."""
import bpy, hashlib, json, os, stat, subprocess, tempfile
from pathlib import Path
from bpy.app.handlers import persistent
from bpy.props import BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty, StringProperty

STATE = {}
ROOT = Path(__file__).resolve().parent
def need(x,msg):
    if not x: raise ValueError(msg)
def digest(path):
    with path.open('rb') as f: return hashlib.file_digest(f,'sha256').hexdigest()
def runtime():
    root=Path(bpy.app.binary_path).parent
    py=root/'5.3/python/bin/python3.13'
    need(bpy.app.version==(5,3,0) and bpy.app.build_hash==b'02f0899d78e3','Unqualified Blender version/build')
    for p,h in ((root/'blender','baaa36cb5d7a35092388e6d123739b0829012c252b0705bc2debec292e4ebffb'),(py,'be767e5ad6f60784b8858f48e136fb98129e2169f23722b6e48a864525de7f90')):
        need(p==p.resolve() and digest(p)==h,'Unqualified runtime identity')
    return root,py
def verify():
    manifest=json.loads((ROOT/'CODE-MANIFEST.json').read_bytes())['files']
    need(set(manifest)=={p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*.py') if '__pycache__' not in p.parts},'Package inventory mismatch')
    for n,h in manifest.items(): need((ROOT/n).resolve()==ROOT/n and digest(ROOT/n)==h,'Package identity mismatch: '+n)
def capture(ctx):
    s=ctx.scene; cam=s.camera
    need(bpy.data.filepath and not bpy.data.is_dirty and cam,'A clean, saved file and active camera are required')
    p=Path(bpy.data.filepath); t=p.lstat()
    need(p==p.resolve() and stat.S_ISREG(t.st_mode) and t.st_nlink==1 and 0<t.st_size<=32<<20,'Unqualified saved source')
    need(not ctx.screen or not ctx.screen.is_animation_playing,'Stop playback before CHECK/APPLY')
    return (str(p),digest(p),t.st_dev,t.st_ino,t.st_size,t.st_mtime_ns,t.st_ctime_ns,s.as_pointer(),ctx.window.as_pointer(),s.name,cam.name,cam.data.type)
def execute_backend(token,q,out,check,authorize):
    verify();root,py=runtime();parent=out.parent
    st=parent.stat()
    need(out.is_absolute() and out==out.resolve() and not out.exists() and st.st_uid==os.geteuid() and not st.st_mode&0o077,'Choose a NEW directory inside an owner-only (0700) existing directory')
    with tempfile.TemporaryDirectory(dir=parent,prefix='.camera-control-') as tmp:
        f=Path(tmp)/'request.json'; f.write_text(json.dumps(q,allow_nan=False))
        cmd=[str(py),'-I','-B',str(ROOT/'linux_static/transaction.py'),'--runtime',str(root),'--source',token[0],'--sha256',token[1],'--query',str(f),'--out',str(out)]
        if authorize:cmd+=['--authorize-owned-static-workcopy']
        if check: cmd+=['--check-only']
        r=subprocess.run(cmd,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env={'HOME':tmp,'PATH':'/usr/bin:/bin','TMPDIR':tmp},timeout=160)
        need(r.returncode==0,'Isolated transaction failed: '+r.stderr[-500:])
        return json.loads(r.stdout) if check else json.loads((out/'receipt.json').read_bytes())
class CHECK(bpy.types.Operator):
    bl_idname='camera_windows_static.check'
    bl_label='CHECK pose, optics and focus'
    optics: BoolProperty(name='Change lens / ortho scale',default=True)
    aim: BoolProperty(name='Change XYZ rotation',default=False)
    rotation: FloatVectorProperty(name='Absolute XYZ Euler angles',subtype='EULER',size=3,min=-6.2831855,max=6.2831855)
    focus: EnumProperty(name='Depth of field',items=[('KEEP','Keep unchanged',''),('OFF','Disable (preserve focus setup)',''),('DISTANCE','Enable: manual distance',''),('OBJECT','Enable: focus on object','')],default='KEEP')
    distance: FloatProperty(name='Manual focus distance (scene units)',min=0.01,max=100000,default=10)
    fstop: FloatProperty(name='Aperture f-stop',min=0.1,max=128,default=2.8)
    object_name: StringProperty(name='Static focus mesh / empty')
    target: FloatProperty(name='Focal length (mm) or orthographic scale',min=0.01,max=10000,default=55)
    authorize: BoolProperty(name='Enroll my own trusted static work-copy for this operation',description='Not for downloaded/third-party files. Requires a private folder and uncompressed project work-copy. Does not grant permanent approval',default=False,options={'SKIP_SAVE'})
    move: BoolProperty(name='Also set unparented camera location',default=False)
    position: FloatVectorProperty(name='Camera location (scene units)',size=3,min=-10000,max=10000,default=(0,0,0))
    out: StringProperty(name='New output directory',subtype='DIR_PATH')
    def invoke(self,ctx,event): return ctx.window_manager.invoke_props_dialog(self,width=520)
    def draw(self,ctx):
        layout=self.layout;layout.prop(self,'authorize');layout.prop(self,'optics')
        if self.optics:layout.prop(self,'target')
        layout.prop(self,'move')
        if self.move:layout.prop(self,'position')
        layout.prop(self,'aim')
        if self.aim:layout.prop(self,'rotation')
        layout.prop(self,'focus')
        if self.focus in {'DISTANCE','OBJECT'}:
            layout.prop(self,'fstop')
            if self.focus=='DISTANCE':layout.prop(self,'distance')
            else:layout.prop_search(self,'object_name',ctx.scene,'objects')
        layout.prop(self,'out')
    def execute(self,ctx):
        STATE.clear()
        try:
            tok=capture(ctx); out=Path(self.out);need(tok[-1] in ('PERSP','ORTHO'),'Unsupported projection')
            q={'scene':tok[-3],'camera':tok[-2]}
            if self.optics:q['lens' if tok[-1]=='PERSP' else 'ortho_scale']=self.target
            if self.aim:q['rotation']=list(self.rotation)
            if self.focus!='KEEP':
                q['use_dof']=self.focus!='OFF'
                if self.focus in {'DISTANCE','OBJECT'}:
                    q['fstop']=self.fstop;q['focus_object']='' if self.focus=='DISTANCE' else self.object_name
                    if self.focus=='DISTANCE':q['focus_distance']=self.distance
                    else:need(bool(self.object_name),'Choose a focus mesh or empty')
            need(len(q)>2 or self.move,'Select at least one change')
            if self.move:q["location"]=list(self.position)
            ck=execute_backend(tok,q,out,True,self.authorize);need(capture(ctx)==tok,'Source/session changed during CHECK')
            STATE.update(tok=tok,q=q,out=out,ck=ck,authorize=self.authorize);self.report({'INFO'},'Checked. Source unmodified; no candidate created.');return {'FINISHED'}
        except Exception as e:self.report({'ERROR'},str(e));return {'CANCELLED'}
class SEQUENCE(bpy.types.Operator):
    bl_idname='camera_windows_static.sequence_check'
    bl_label='CHECK advanced camera operation'
    request_json: StringProperty(name='One operation (JSON)',maxlen=16384,options={'SKIP_SAVE'})
    out: StringProperty(name='New copy directory',subtype='DIR_PATH')
    authorize: BoolProperty(name='This is my trusted project work-copy',default=False,options={'SKIP_SAVE'})
    def invoke(self,ctx,event):return ctx.window_manager.invoke_props_dialog(self,width=720)
    def draw(self,ctx):
        self.layout.label(text='One bounded operation: cut, motion, easing, focus timing or bone focus.')
        for n in ('request_json','out','authorize'):self.layout.prop(self,n)
    def execute(self,ctx):
        STATE.clear()
        try:
            need(self.authorize,'Explicit work-copy approval required')
            def unique(pairs):
                out={}
                for k,v in pairs:need(k not in out,'Duplicate JSON key: '+k);out[k]=v
                return out
            sq=json.loads(self.request_json,object_pairs_hook=unique,parse_constant=lambda s:need(False,'Non-finite JSON'))
            need(type(sq)==dict and sq.get('kind') in ('cut','motion','motion_ease','bone','focus_timing','legacy_cut'),'Unknown operation kind')
            tok=capture(ctx);out=Path(self.out);q={'scene':tok[-3],'camera':tok[-2],'sequence':sq}
            ck=execute_backend(tok,q,out,True,True);need(capture(ctx)==tok,'Source/session changed during CHECK')
            STATE.update(tok=tok,q=q,out=out,ck=ck,authorize=True)
            self.report({'INFO'},'Advanced CHECK passed; no project saved.');return {'FINISHED'}
        except Exception as e:self.report({'ERROR'},str(e));return {'CANCELLED'}
class APPLY(bpy.types.Operator):
    bl_idname='camera_windows_static.create'
    bl_label='APPLY to new verified copy'
    @classmethod
    def poll(cls,ctx):return bool(STATE)
    def execute(self,ctx):
        st=STATE.copy();STATE.clear()
        try:
            need(capture(ctx)==st['tok'],'Source/session differs from CHECK')
            receipt=execute_backend(st['tok'],st['q'],st['out'],False,st['authorize'])
            need(receipt.get('prediction')==st['ck'].get('prediction') and receipt['source']==st['ck']['baseline'] and receipt['query']==st['q'] and receipt['source_sha256']==st['tok'][1],'Receipt does not match CHECK')
            self.report({'INFO'},'Verified new copy: '+str(st['out']/'candidate.blend'));return {'FINISHED'}
        except Exception as e:self.report({'ERROR'},str(e));return {'CANCELLED'}
class PANEL(bpy.types.Panel):
    bl_idname='CAMERA_WORKFLOW_PT_linux_static';bl_label='Camera Workflow · Linux static camera';bl_space_type='VIEW_3D';bl_region_type='UI';bl_category='Camera Live'
    def draw(self,ctx):
        self.layout.label(text='Trusted static work-copies. Source is never written.')
        self.layout.operator(CHECK.bl_idname)
        self.layout.operator(SEQUENCE.bl_idname)
        if STATE:self.layout.label(text='Checked '+str(STATE['q'].get('sequence',{}).get('kind','static'))+'; ready to apply.')
        self.layout.operator(APPLY.bl_idname)
@persistent
def clear(*_):STATE.clear()
def register():
    verify();runtime()
    for cls in (CHECK,SEQUENCE,APPLY,PANEL):bpy.utils.register_class(cls)
    bpy.app.handlers.load_pre.append(clear)
def unregister():
    clear()
    if clear in bpy.app.handlers.load_pre:bpy.app.handlers.load_pre.remove(clear)
    for cls in (PANEL,APPLY,SEQUENCE,CHECK):bpy.utils.unregister_class(cls)
