"""Existing direct-EMPTY focus onset. Changes only second key time and two FREE
handle times per existing location channel. No Action cloning or retention,
rig authoring, focus distance changes, save, rendering, or external I/O."""
import math,struct
from copy import deepcopy
def need(b,s):
    if not b:raise ValueError(s)
def f(x):return struct.unpack('f',struct.pack('f',x))[0]
def validate(q):
    need(type(q) is dict and set(q)=={'kind','helper','new_start','locked_frames'} and q['kind']=='focus_timing','exact focus_timing request required')
    locks=q['locked_frames'];new=q['new_start']
    need(type(q['helper']) is str and 0<len(q['helper'].encode())<=63 and q['helper']==q['helper'].strip() and '\x00' not in q['helper'],'exact helper name required')
    need(type(locks) is list and len(locks)==3 and all(type(x) is int and 0<=x<=10000 for x in locks) and locks[0]<locks[1]<locks[2],'three increasing locks in [0,10000] required')
    need(type(new) is int and locks[0]<new<locks[1],'target onset must lie strictly between first two locks')
def owned(bpy,s,c,q):
    validate(q);lk=q['locked_frames'];t=s.frame_current+s.frame_subframe
    need(t<=lk[0] or t>=lk[2],'save outside focus movement first')
    need(c==s.camera and c.type=='CAMERA' and not c.library and not c.override_library and c.data.type=='PERSP' and not c.parent and not c.constraints and not c.modifiers and not c.animation_data,'static local perspective camera required')
    h=s.objects.get(q['helper']);d=c.data
    need(h and h.type=='EMPTY' and not h.data and not h.parent and not h.constraints and not h.modifiers and h.instance_type=='NONE' and not h.library and not h.override_library,'flat local EMPTY helper required')
    need(not d.library and not d.override_library and not d.animation_data and d.users==1 and not d.use_fake_user and not d.use_extra_user and d.dof.use_dof and not d.dof.focus_subtarget and d.dof.focus_object==h and [a for a in bpy.data.cameras if a.dof.focus_object==h]==[d],'exclusive bound enabled DOF target required')
    need(tuple(h.users_scene)==(s,) and len(h.users_collection)==1 and not h.use_fake_user and not h.use_extra_user and h.users==1 and set(bpy.data.user_map(subset={h}).get(h,()))==({s,d} if h.users_collection[0]==s.collection else {s,h.users_collection[0],d}),'unexpected helper owner/reference')
    need(h.rotation_mode=='XYZ' and tuple(h.rotation_euler)==tuple(h.delta_location)==tuple(h.delta_rotation_euler)==(0,0,0) and tuple(h.scale)==tuple(h.delta_scale)==(1,1,1) and tuple(h.rotation_quaternion)==tuple(h.delta_rotation_quaternion)==(1,0,0,0) and h.rotation_axis_angle[0]==0 and not any(h.lock_location),'identity helper orientation and deltas required')
    ad=h.animation_data
    need(ad and ad.action and not ad.drivers and not ad.nla_tracks and not ad.use_tweak_mode and ad.action_blend_type=='REPLACE' and ad.action_influence==1,'single full influence non-driven action required')
    a=ad.action
    need(not a.library and not a.override_library and a.users==1 and not a.use_fake_user and not a.use_extra_user and set(bpy.data.user_map(subset={a}).get(a,()))=={h},'exclusive local helper action required')
    need(len(a.layers)==len(a.slots)==1 and ad.action_slot==a.slots[0] and ad.action_slot.target_id_type=='OBJECT','single bound object slot required')
    layer=a.layers[0]
    need(not getattr(layer,'mute',False) and getattr(layer,'influence',1)==1 and len(layer.strips)==1,'one unmuted layer required')
    st=layer.strips[0];need(st.type=='KEYFRAME' and len(st.channelbags)==1,'single keyframe bag required');bag=st.channelbag(ad.action_slot)
    need(bag and len(bag.fcurves)==3,'expected exactly three XYZ curves')
    cs=sorted(bag.fcurves,key=lambda v:v.array_index)
    for i,v in enumerate(cs):
        need(v.data_path=='location' and v.array_index==i and len(v.keyframe_points)==4 and v.is_valid and not v.modifiers and not v.sampled_points and v.extrapolation=='CONSTANT' and not v.mute and not v.lock and (not v.group or (not v.group.lock and not v.group.mute)),'plain location XYZ x four required')
    return h,a,cs
def capture(h,a,cs,q):
    curves=[];starts=[];moving=False;lk=q['locked_frames']
    for v in cs:
        pts=[]
        for k in v.keyframe_points:
            need(k.interpolation=='LINEAR' and k.handle_left_type==k.handle_right_type=='FREE','LINEAR/FREE only')
            co=list(k.co);l=list(k.handle_left);r=list(k.handle_right)
            need(list(k.co_ui)==co and all(math.isfinite(z) for z in co+l+r),'nonfinite or incoherent key')
            pts.append([co,l,r])
        ts=[p[0][0] for p in pts];ys=[p[0][1] for p in pts]
        need([ts[0],ts[2],ts[3]]==lk and ts[0]<ts[1]<ts[2] and ts[1]==int(ts[1]),'key times disagree with locks')
        need(ys[0]==ys[1] and ys[2]==ys[3],'outer focus holds required')
        starts.append(ts[1]);moving|=ys[1]!=ys[2];curves.append(pts)
    need(len(set(starts))==1 and moving,'shared effective onset required')
    return dict(helper=h.name,action=a.name,slot=h.animation_data.action_slot.identifier,curves=curves)
def sample(cs):
    t0,t1,t2,t3=[p[0][0] for p in cs[0]]
    return [[t,[v[1][0][1]+min(1,max(0,(t-t1)/(t2-t1)))*(v[2][0][1]-v[1][0][1]) for v in cs]] for t in (t0,t1,(t1+t2)/2,t2,t3)]
def guard(bpy,scene,camera,q):
    h,a,cs=owned(bpy,scene,camera,q);capture(h,a,cs,q)
def state(bpy,scene,camera,q):
    h,a,cs=owned(bpy,scene,camera,q);d=capture(h,a,cs,q);rows=sample(d['curves']);fr,sub=scene.frame_current,scene.frame_subframe
    try:
        for t,pos in rows:
            scene.frame_set(int(t),subframe=t-int(t));hp=h.evaluated_get(bpy.context.evaluated_depsgraph_get()).matrix_world.translation
            need(all(math.isclose(x,y,rel_tol=1e-5,abs_tol=2e-5) for x,y in zip(pos,hp)),'evaluated focus helper world position mismatch')
    finally:scene.frame_set(fr,subframe=sub)
    d['samples']=rows;return d
def expected(before,q):
    validate(q);d=deepcopy(before);delta=q['new_start']-d['curves'][0][1][0][0];need(delta!=0,'focus onset unchanged')
    for curve in d['curves']:
        for xy in curve[1]:xy[0]=f(xy[0]+delta)
    d['samples']=sample(d['curves']);return d
def apply(bpy,scene,camera,q):
    h,a,cs=owned(bpy,scene,camera,q);target=expected(capture(h,a,cs,q),q)
    for v,rows in zip(cs,target['curves']):
        co,l,r=rows[1];k=v.keyframe_points[1];k.co[0]=co[0];k.handle_left[0]=l[0];k.handle_right[0]=r[0];v.update()
    scene.frame_set(scene.frame_current,subframe=scene.frame_subframe)
