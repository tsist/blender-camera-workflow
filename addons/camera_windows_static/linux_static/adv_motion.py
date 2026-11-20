"""Linux authoring slice. Unlike motion_ops.py this creates a NEW location+XYZ
action; no existing action can be edited. The easing control formulae reproduce
motion_profile_frozen's inner controls on each segment; deterministic constant
extrapolation. Angles are component-wise radians, not quaternion shortest arcs.
No bpy import at module load, external I/O, rendering or handlers.
"""
import math
import struct

PATHS=('location','rotation_euler')
MODES=('LINEAR','CONSTANT','EASE_IN_OUT','EASE_IN','EASE_OUT')
def need(ok,msg):
    if not ok: raise ValueError(msg)
def f(x): return struct.unpack('f',struct.pack('f',x))[0]
def validate(q):
    need(type(q) is dict and set(q)=={'kind','keys','interpolation'} and q['kind']=='motion','motion: exact request required')
    need(q['interpolation'] in MODES,'unsupported interpolation')
    keys=q['keys']
    need(type(keys) is list and 2<=len(keys)<=32,'expected 2..32 keys')
    last=-1
    for k in keys:
        need(type(k) is dict and set(k)=={'frame',*PATHS},'pose requires frame,location,rotation_euler')
        t=k['frame']; need(type(t) is int and last<t<=10000,'strictly increasing integral frames 0..10000');last=t
        for p,cap in zip(PATHS,(1000,2*math.pi)):
            v=k[p];need(type(v) is list and len(v)==3 and all(type(x) in (float,int) and abs(x)<=cap for x in v),'invalid '+p)
def label(cam):return 'CW.Motion.'+cam.name
def guard(bpy,scene,camera,q):
    validate(q)
    need(scene.camera==camera and camera.type=='CAMERA' and camera.rotation_mode=='XYZ' and camera.library is None and camera.override_library is None and len(camera.users_scene)==1,'exclusive local active XYZ camera required')
    need(camera.parent is None and not camera.constraints and not camera.modifiers and camera.data.animation_data is None,'existing animation or rig not supported')
    need(tuple(camera.delta_location)==(0,0,0) and tuple(camera.delta_rotation_euler)==(0,0,0) and tuple(camera.delta_scale)==(1,1,1) and tuple(camera.scale)==(1,1,1),'nonidentity scale or deltas')
    need(not any(camera.lock_location) and not any(camera.lock_rotation),'locked transforms')
    need(len(label(camera).encode())<=63 and (not bpy.data.actions.get(label(camera)) or (camera.animation_data and camera.animation_data.action==bpy.data.actions.get(label(camera)))),'action name unavailable')
    if camera.animation_data is not None:
        need(camera.animation_data.action and camera.animation_data.action.name==label(camera),'existing camera animation')
def plan(q):
    curves=[]
    for path in PATHS:
        for axis in range(3):
            rows=[]
            for k in q['keys']:
                base=[float(k['frame']),f(k[path][axis])];rows.append([base,base[:],base[:]])
            rows[0][1][0]-=1;rows[-1][2][0]+=1
            for l,r in zip(rows,rows[1:]):
                (a,x),(b,y)=l[0],r[0];mode=q['interpolation']
                l[2]=[f(a+(b-a)/3), f(x+2*(y-x)/3) if mode=='EASE_OUT' else x]
                r[1]=[f(b-(b-a)/3), f(x+(y-x)/3) if mode=='EASE_IN' else y]
            curves.append([path,axis,q['interpolation'] if q['interpolation'] in MODES[:2] else 'BEZIER',rows])
    return curves
def probes(q):
    ks=q['keys'];return sorted({float(k['frame']) for k in ks}|{(a['frame']+b['frame'])/2 for a,b in zip(ks,ks[1:])})
def evaluate(cs,t):
    vals=[]
    for p,i,mode,rows in cs:
        hit=next((r[0][1] for r in rows if r[0][0]==t),None)
        if hit is None:
            l,r=next((a,b) for a,b in zip(rows,rows[1:]) if a[0][0]<t<b[0][0])
            x,y=l[0][1],r[0][1]
            if mode=='LINEAR':hit=(x+y)/2
            elif mode=='CONSTANT':hit=x
            else:hit=(x+3*l[2][1]+3*r[1][1]+y)/8
        vals.append(hit)
    return [t,vals[:3],vals[3:]]
def expected(before,q):
    validate(q);need(before['action'] is None,'motion would overwrite animation')
    cs=plan(q)
    return dict(camera=before['camera'],action='CW.Motion.'+before['camera'],curves=cs,samples=[evaluate(cs,t) for t in probes(q)])
def bag_for(ad):
    a=ad.action
    need(len(a.slots)==len(a.layers)==len(a.layers[0].strips)==1 and ad.action_slot==a.slots[0],'unexpected layered action structure')
    s=a.layers[0].strips[0]; need(s.type=='KEYFRAME' and len(s.channelbags)==1,'unexpected strips/bags')
    return s.channelbag(ad.action_slot)
def state(bpy,scene,camera,q):
    ad=camera.animation_data
    if ad is None:return dict(camera=camera.name,action=None,curves=[],samples=[])
    need(ad.action and ad.action.name==label(camera) and ad.action.users==1 and not ad.drivers and not ad.nla_tracks,'unexpected camera animation')
    curves=[]
    for c in sorted(bag_for(ad).fcurves,key=lambda c:(PATHS.index(c.data_path),c.array_index)):
        pts=c.keyframe_points;mode=pts[0].interpolation
        need(not c.modifiers and not c.mute and c.extrapolation=='CONSTANT' and all(k.interpolation==mode and k.handle_left_type==k.handle_right_type=='FREE' for k in pts),'unexpected curve properties')
        curves.append([c.data_path,c.array_index,mode,[[list(k.co),list(k.handle_left),list(k.handle_right)] for k in pts]])
    samples=[];frame=scene.frame_current;sub=scene.frame_subframe
    try:
        for t in probes(q):
            scene.frame_set(int(t),subframe=t-int(t));ob=camera.evaluated_get(bpy.context.evaluated_depsgraph_get())
            row=evaluate(curves,t)
            # Canonicalize only after checking the actual evaluated world transform
            # and local angles. Blender's bezier solver is single precision.
            from mathutils import Euler
            rot=Euler(row[2],'XYZ').to_matrix();w=ob.matrix_world
            for a,b in zip([*w.translation,*ob.rotation_euler],[*row[1],*row[2]]):
                need(math.isclose(a,b,rel_tol=3e-5,abs_tol=2e-4),'evaluated pose disagrees at '+str(t))
            need(all(abs(w[i][j]-rot[i][j])<3e-4 for i in range(3) for j in range(3)),'evaluated world orientation disagrees')
            samples.append(row)
    finally:scene.frame_set(frame,subframe=sub)
    return dict(camera=camera.name,action=ad.action.name,curves=curves,samples=samples)
def apply(bpy,scene,camera,q):
    guard(bpy,scene,camera,q)
    need(camera.animation_data is None,'motion will not replace animation')
    ad=camera.animation_data_create();action=bpy.data.actions.new(label(camera));slot=action.slots.new('OBJECT',camera.name)
    ad.action=action;ad.action_slot=slot
    bag=action.layers.new('Motion').strips.new(type='KEYFRAME').channelbags.new(slot)
    for path,axis,mode,rows in plan(q):
        c=bag.fcurves.new(path,index=axis);c.keyframe_points.add(len(rows))
        for k,(co,left,right) in zip(c.keyframe_points,rows):
            k.co=co;k.interpolation=mode;k.handle_left_type=k.handle_right_type='FREE';k.handle_left=left;k.handle_right=right
        c.update()
    scene.frame_set(scene.frame_current,subframe=scene.frame_subframe)
