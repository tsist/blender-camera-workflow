"""Apply original two-endpoint location easing to an existing exclusive native action.
Source is qualified as LINEAR/FREE or a frozen preset. No new action, slot, path,
key, camera or save; host owns protected state, new output and cold transaction.
"""
import math,struct
from copy import deepcopy

def need(b,s):
    if not b:raise ValueError(s)
def f(x): return struct.unpack('f',struct.pack('f',x))[0]
E=('EASE_IN','EASE_OUT','EASE_IN_OUT')
def validate(q):
    need(type(q) is dict and set(q)=={'kind','interpolation'} and q['kind']=='motion_ease' and q['interpolation'] in E,'expected exact motion_ease request')
def owned(bpy,scene,c):
    ad=c.animation_data
    need(c.type=='CAMERA' and c==scene.camera and len(c.users_scene)==1 and c.library is None and not c.override_library and not c.parent and not c.constraints and not c.modifiers and not any(c.lock_location) and tuple(c.delta_location)==(0,0,0) and c.data.animation_data is None,'unconstrained local camera required')
    need(ad and not ad.drivers and not ad.nla_tracks and not ad.use_tweak_mode and ad.action and ad.action_influence==1 and ad.action_blend_type=='REPLACE','exclusive unsuppressed action required')
    a=ad.action
    need(a.library is None and not a.override_library and a.users==1 and not a.use_fake_user and len(a.slots)==len(a.layers)==1 and ad.action_slot==a.slots[0],'action must be local exclusive single-slot')
    layer=a.layers[0];need(len(layer.strips)==1,'exactly one strip required')
    st=layer.strips[0];need(st.type=='KEYFRAME' and len(st.channelbags)==1,'one keyframe strip required')
    bag=st.channelbag(ad.action_slot)
    need(bag and len(bag.fcurves)==3,'exactly three location curves required')
    curves=sorted(bag.fcurves,key=lambda v:v.array_index)
    for i,v in enumerate(curves):
        need(v.data_path=='location' and v.array_index==i and v.is_valid and not v.mute and not v.lock and not v.modifiers and not v.sampled_points and len(v.keyframe_points)==2,'only unmodified XYZ two-key curves')
        need(not v.group or (not v.group.lock and not v.group.mute),'muted/locked group')
        need(all(k.handle_left_type==k.handle_right_type=='FREE' for k in v.keyframe_points),'FREE handles required')
    return a,curves
def capture(a,cs,c):
    curves=[]
    for v in cs:
        curve=[]
        for k in v.keyframe_points:
            curve.append(dict(co=list(k.co),l=list(k.handle_left),r=list(k.handle_right),mode=k.interpolation))
        curves.append(curve)
    times=[k['co'][0] for k in curves[0]]
    need(all([k['co'][0] for k in v]==times for v in curves),'unsynchronised endpoints')
    need(all(t==int(t) and 0<=t<=10000 for t in times) and times[1]-times[0]>=1,'bounded positive integral interval required')
    need(all(abs(k['co'][1])<=1000 and all(math.isfinite(x) for x in k['l']+k['r']) for v in curves for k in v),'invalid coordinates')
    return dict(camera=c.name,action=a.name,curves=curves)
def modify(curves,e):
    result=deepcopy(curves)
    for l,r in result:
        (a,x),(b,y)=l['co'],r['co']
        l['mode']=r['mode']='BEZIER'
        l['r']=[f(a+(b-a)/3),f(x+2*(y-x)/3) if e=='EASE_OUT' else x]
        r['l']=[f(b-(b-a)/3),f(x+(y-x)/3) if e=='EASE_IN' else y]
    return result
def style(cs):
    modes={k['mode'] for v in cs for k in v}
    if modes=={'LINEAR'}:return 'LINEAR'
    candidates=[e for e in E if cs==modify(cs,e)]
    need(len(candidates)==1,'Bezier handles do not uniquely match a frozen preset')
    return candidates[0]
def samples(cs):
    (t0,x),(t1,y)=[k['co'] for k in cs[0]]
    rows=[]
    for u in (0,.25,.5,.75,1):
        vals=[]
        for a,b in cs:
            p=a['co'][1];z=b['co'][1];v=1-u
            vals.append(v*p+u*z if a['mode']=='LINEAR' else v**3*p+3*v*v*u*a['r'][1]+3*v*u*u*b['l'][1]+u**3*z)
        rows.append([t0+u*(t1-t0),vals])
    return rows
def guard(bpy,scene,camera,q):
    validate(q);a,cs=owned(bpy,scene,camera);style(capture(a,cs,camera)['curves'])
def state(bpy,scene,camera,q):
    validate(q);a,cs=owned(bpy,scene,camera);d=capture(a,cs,camera);style(d['curves']);rows=samples(d['curves'])
    frame,sub=scene.frame_current,scene.frame_subframe
    try:
        for t,v in rows:
            scene.frame_set(int(t),subframe=t-int(t))
            w=camera.evaluated_get(bpy.context.evaluated_depsgraph_get()).matrix_world.translation
            need(all(math.isclose(x,y,abs_tol=4e-4,rel_tol=5e-5) for x,y in zip(w,v)),'world location differs from predicted path at '+str(t))
    finally:scene.frame_set(frame,subframe=sub)
    d['samples']=rows;return d
def expected(before,q):
    validate(q);d=deepcopy(before);style(d['curves']);d['curves']=modify(d['curves'],q['interpolation']);d['samples']=samples(d['curves']);need(d!=before,'no effective ease change');return d
def apply(bpy,scene,camera,q):
    guard(bpy,scene,camera,q);a,cs=owned(bpy,scene,camera);raw=capture(a,cs,camera)['curves'];out=modify(raw,q['interpolation']);need(out!=raw,'no effective ease change')
    for c,(l,r) in zip(cs,out):
        k,j=c.keyframe_points
        k.interpolation=j.interpolation='BEZIER';k.handle_right=l['r'];j.handle_left=r['l'];c.update()
    scene.frame_set(scene.frame_current,subframe=scene.frame_subframe)
