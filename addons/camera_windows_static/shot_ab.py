"""Same-scene fixed-frame SOLID camera A/B. No file opening, save, rendering or frame setting."""
import os
import bpy
from bpy.props import StringProperty, BoolProperty, EnumProperty
from bpy.app.handlers import persistent

_lease=None

def need(v,msg):
    if not v:raise ValueError(msg)

def _ctx(ctx):
    w,a,s=ctx.window,ctx.area,ctx.scene
    need(not bpy.app.background and w and a and a.type=='VIEW_3D' and ctx.mode=='OBJECT','Use an actual 3D View in Object Mode')
    sp=a.spaces.active;r=sp.region_3d
    need(r and not sp.region_quadviews and not w.screen.is_animation_playing,'Use one stopped, non-Quad 3D View')
    need(sp.shading.type=='SOLID' and not sp.lock_camera,'Use Solid shading with Lock Camera to View off')
    return w,a,s,sp,r

def _view(sp,r):
    return(dict(local=sp.use_local_camera,camera=sp.camera,mode=r.view_perspective,offset=tuple(r.view_camera_offset),zoom=r.view_camera_zoom,
                location=tuple(r.view_location),rotation=tuple(r.view_rotation),distance=r.view_distance))

def _scope(ctx):
    w,a,s,sp,r=_ctx(ctx)
    return (tuple(x.as_pointer() for x in (w,w.screen,a,s,sp,r)),bpy.data.filepath,s.frame_current,s.frame_subframe,s.camera.as_pointer() if s.camera else None)

def _camera(s,n):
    o=s.objects.get(n)
    need(o and o.type=='CAMERA' and not o.library and not o.override_library and o.data and not o.data.library and not o.data.override_library,'Choose a local camera object and local camera data')
    return o

def _assert_owner(ctx,l):
    need(_scope(ctx)==l['scope'],'Owner, file, frame, or scene camera changed; release without restoring')
    _,_,s,sp,r=_ctx(ctx)
    actual=_view(sp,r)
    # Camera drawing refreshes RegionView3D.view_rotation. This cache is not a
    # navigation input in CAMERA mode. Everything else, incl. zoom/offset, stays guarded.
    if actual['mode']==l['last']['mode']=='CAMERA':actual['rotation']=l['last']['rotation']
    need(actual==l['last'],'Viewport changed outside A/B; release without restoring')
    for o in l['cams']:need(_camera(s,o.name)==o,'Camera identity changed')
    return sp,r

def _set(sp,r,cam):
    sp.use_local_camera=True;sp.camera=cam;r.view_perspective='CAMERA'

def _restore(sp,r,v):
    sp.use_local_camera=True;sp.camera=v['camera']
    r.view_perspective=v['mode'];r.view_camera_zoom=v['zoom'];r.view_camera_offset=v['offset']
    r.view_location=v['location'];r.view_rotation=v['rotation'];r.view_distance=v['distance']
    sp.use_local_camera=v['local']

def start(ctx,first,second,review_file):
    global _lease
    need(_lease is None,'A/B is active; restore or release first')
    w,a,s,sp,r=_ctx(ctx);path=bpy.data.filepath
    need(path and os.path.isabs(path) and path==review_file,'Confirm the currently open saved review copy, using its exact path')
    cams=(_camera(s,first),_camera(s,second));need(cams[0]!=cams[1],'Choose two different local camera objects')
    saved=_view(sp,r);scope=_scope(ctx)
    try:
        _set(sp,r,cams[0]);need(_scope(ctx)==scope and sp.camera==cams[0] and sp.use_local_camera and r.view_perspective=='CAMERA','Failed to isolate local camera')
    except Exception:
        _restore(sp,r,saved);raise
    _lease=dict(scope=scope,saved=saved,last=_view(sp,r),cams=cams,side='A');a.tag_redraw()

def choose(ctx,side):
    l=_lease;need(l is not None and side in ('A','B'),'Start A/B first')
    sp,r=_assert_owner(ctx,l);cam=l['cams'][side=='B'];_set(sp,r,cam)
    need(_scope(ctx)==l['scope'] and sp.camera==cam and sp.use_local_camera and r.view_perspective=='CAMERA','Could not isolate camera')
    l.update(last=_view(sp,r),side=side);ctx.area.tag_redraw()

def restore(ctx):
    global _lease
    l=_lease;need(l is not None,'No A/B session')
    sp,r=_assert_owner(ctx,l);_restore(sp,r,l['saved'])
    need(_view(sp,r)==l['saved'] and _scope(ctx)==l['scope'],'Could not restore exact saved view')
    _lease=None;ctx.area.tag_redraw()

def release():
    global _lease
    _lease=None

@persistent
def _drop(_unused):release()

def _run(op,fn,*args):
    try:fn(*args)
    except (ValueError,ReferenceError,RuntimeError) as e:op.report({'ERROR'},str(e));return {'CANCELLED'}
    return {'FINISHED'}

class CAMERA_AB_OT_start(bpy.types.Operator):
    bl_idname='camera_ab.start';bl_label='Start Fixed-frame Camera A/B'
    camera_a:StringProperty(name='Camera A')
    camera_b:StringProperty(name='Camera B')
    review_file:StringProperty(name='Open review copy',subtype='FILE_PATH')
    confirm:BoolProperty(name='I chose this saved review copy for comparison',default=False,options={'SKIP_SAVE'})
    def invoke(self,ctx,event):
        self.review_file=bpy.data.filepath;self.confirm=False
        cams=[o.name for o in ctx.scene.objects if o.type=='CAMERA']
        self.camera_a=ctx.scene.camera.name if ctx.scene.camera else (cams[0] if cams else '')
        self.camera_b=next((n for n in cams if n!=self.camera_a),'')
        return ctx.window_manager.invoke_props_dialog(self,width=465)
    def draw(self,ctx):
        lay=self.layout;lay.label(text='Fixed frame: '+str(ctx.scene.frame_current));lay.prop(self,'review_file')
        lay.prop_search(self,'camera_a',ctx.scene,'objects');lay.prop_search(self,'camera_b',ctx.scene,'objects');lay.prop(self,'confirm')
    def execute(self,ctx):
        if not self.confirm:self.report({'ERROR'},'First confirm this is your chosen review copy');return {'CANCELLED'}
        return _run(self,start,ctx,self.camera_a,self.camera_b,self.review_file)

class CAMERA_AB_OT_choose(bpy.types.Operator):
    bl_idname='camera_ab.choose';bl_label='Show A or B'
    side:EnumProperty(items=[('A','A',''),('B','B','')])
    def execute(self,ctx):return _run(self,choose,ctx,self.side)

class CAMERA_AB_OT_restore(bpy.types.Operator):
    bl_idname='camera_ab.restore';bl_label='Restore Original View'
    def execute(self,ctx):return _run(self,restore,ctx)

class CAMERA_AB_OT_release(bpy.types.Operator):
    bl_idname='camera_ab.release';bl_label='Release Without Restoring'
    def execute(self,ctx):release();return {'FINISHED'}

class CAMERA_AB_PT_compare(bpy.types.Panel):
    bl_label='Fixed-frame Camera A/B';bl_idname='CAMERA_AB_PT_compare';bl_space_type='VIEW_3D';bl_region_type='UI';bl_category='Camera'
    def draw(self,ctx):
        l=self.layout
        if not _lease:l.operator('camera_ab.start');return
        l.label(text='Fixed frame %s | Showing %s'%(_lease['scope'][2],_lease['side']))
        row=l.row(align=True)
        for side in ('A','B'):row.operator('camera_ab.choose',text='Show '+side).side=side
        l.operator('camera_ab.restore');l.operator('camera_ab.release')

classes=(CAMERA_AB_OT_start,CAMERA_AB_OT_choose,CAMERA_AB_OT_restore,CAMERA_AB_OT_release,CAMERA_AB_PT_compare)
def register():
    for cls in classes:bpy.utils.register_class(cls)
    bpy.app.handlers.load_pre.append(_drop)
def unregister():
    if _lease:
        try:restore(bpy.context)
        except (ValueError,RuntimeError,ReferenceError):release()
    if _drop in bpy.app.handlers.load_pre:bpy.app.handlers.load_pre.remove(_drop)
    for cls in reversed(classes):bpy.utils.unregister_class(cls)
