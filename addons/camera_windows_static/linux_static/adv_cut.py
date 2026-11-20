"""Native timeline-camera cuts and affine whole-action retiming; worker-only, no I/O."""
from copy import deepcopy
from fractions import Fraction
from struct import pack, unpack

def need(ok, why):
    if not ok: raise ValueError(why)

def name(v):
    need(type(v) is str and v.strip()==v and 0<len(v.encode())<=63 and not any(ord(c)<32 for c in v),"invalid Blender name")

def frame(v):
    need(type(v) is int and -1048574 <= v <= 1048574,"bounded integer frames required")

def validate(q):
    need(type(q) is dict and q.get("kind")=="cut","cut payload required")
    if q.get("operation")=="cuts":
        need(set(q)=={"kind","operation","cuts"} and type(q["cuts"]) is list and 1<=len(q["cuts"])<=64,"explicit cut list required")
        for r in q["cuts"]:
            need(type(r) is dict and set(r)=={"name","frame","camera"},"exact cut fields required")
            name(r["name"]);name(r["camera"]);frame(r["frame"])
    elif q.get("operation")=="move_cut":
        need(set(q)=={"kind","operation","left","right","left_last"},"exact adjacent-cut fields required")
        name(q["left"]);name(q["right"]);frame(q["left_last"])
        need(q["left"]!=q["right"],"two distinct shot marker names required")
    else:
        need(q.get("operation")=="retime" and set(q)=={"kind","operation","source","destination","cameras"},"invalid retime payload")
        for k in ("source","destination"):
            v=q[k];need(type(v) is list and len(v)==2,"two inclusive endpoints required")
            for x in v: frame(x)
            need(v[0]<v[1],"positive source/destination spans required")
        v=q["cameras"];need(type(v) is list and 1<=len(v)<=32,"bounded explicit camera group required")
        for n in v:name(n)
        need(len(set(v))==len(v) and q["source"]!=q["destination"],"duplicate cameras or unchanged interval")

def curves(obj):
    ad=obj.animation_data
    if not ad:return []
    act=ad.action
    need(act and not ad.drivers and not ad.nla_tracks and not ad.use_tweak_mode and ad.action_blend_type=='REPLACE' and ad.action_influence==1,"only a direct full-influence local Action is supported")
    need(not act.library and not act.override_library and act.users==1 and not act.use_frame_range and not act.use_cyclic and len(act.slots)==len(act.layers)==1 and ad.action_slot==act.slots[0],"exclusive, single-slot inferred-range Action required")
    layer=act.layers[0];need(len(layer.strips)==1,"single keyframe strip required")
    strip=layer.strips[0];need(strip.type=='KEYFRAME' and len(strip.channelbags)==1 and strip.channelbag(ad.action_slot)==strip.channelbags[0],"one bound channelbag required")
    cs=list(strip.channelbags[0].fcurves)
    need(0<len(cs)<=6 and len({(f.data_path,f.array_index) for f in cs})==len(cs),"nonempty unique XYZ transform curves required")
    for f in cs:
        need(f.data_path in ("location","rotation_euler") and 0<=f.array_index<=2 and not f.modifiers and not f.sampled_points and not f.mute and not f.lock and f.extrapolation=='CONSTANT' and 1<=len(f.keyframe_points)<=2048,"ineligible transform channel")
    return sorted(cs,key=lambda f:(f.data_path,f.array_index))

def guard(bpy,scene,camera,q):
    validate(q)
    need(not getattr(scene,"camera_live_shots",[]) and not scene.get("camera_live_shots") and (not scene.sequence_editor or not len(scene.sequence_editor.strips)),"Live shot tables or VSE not supported")
    need(not scene.frame_subframe and scene.camera==camera,"park on an integer frame with matching active camera")
    for n in (q["cameras"] if q["operation"]=="retime" else [r["camera"] for r in q.get("cuts",[])]):
        o=scene.objects.get(n);need(o and o.type=='CAMERA' and not o.library and not o.override_library and not o.parent and not o.constraints and not o.data.animation_data,"eligible local cameras required")

def state(bpy,scene,camera,q):
    guard(bpy,scene,camera,q)
    markers=sorted([[m.name,m.frame,m.camera.name if m.camera else None,bool(m.select)] for m in scene.timeline_markers],key=lambda r:r[0])
    need(len(markers)<=4096 and len({m[0] for m in markers})==len(markers),"duplicate marker names or marker budget")
    actions={}
    for n in sorted(q.get("cameras",[])):
        o=scene.objects[n]; cs=curves(o)
        if not cs:continue
        a=o.animation_data.action
        actions[n]={"action":a.name,"slot":a.slots[0].identifier,"layer":a.layers[0].name,"curves":[{"path":f.data_path,"index":f.array_index,"keys":[[list(k.co),list(k.handle_left),list(k.handle_right),k.interpolation,k.handle_left_type,k.handle_right_type,k.type] for k in f.keyframe_points]} for f in cs]}
    return dict(markers=markers,actions=actions,range=[scene.frame_start,scene.frame_end],park=scene.frame_current,active=scene.camera.name,catalog=sorted(o.name for o in scene.objects if o.type=='CAMERA'))

def f32(x):return unpack('f',pack('f',x))[0]

def expected(before,q):
    validate(q); b=deepcopy(before); rows=b["markers"];lo,hi=b["range"]
    if q["operation"]=="cuts":
        for r in q["cuts"]:
            need(lo<=r["frame"]<=hi and r["camera"] in b["catalog"],"cut outside scene or missing camera")
            need(not any(m[0]==r["name"] or m[1]==r["frame"] for m in rows),"cut marker name/frame collision")
            rows.append([r["name"],r["frame"],r["camera"],False])
    elif q["operation"]=="move_cut":
        cuts=sorted((m for m in rows if m[2]),key=lambda r:r[1])
        need(all(lo<=m[1]<=hi for m in cuts) and len({m[1] for m in cuts})==len(cuts),"scene-bounded unambiguous native cut table required")
        i=next((i for i,r in enumerate(cuts) if r[0]==q["left"]),-1)
        need(0<=i<len(cuts)-1 and cuts[i+1][0]==q["right"],"named camera markers must be adjacent in order")
        left,right=cuts[i:i+2];new=q["left_last"]+1
        stop=cuts[i+2][1] if i+2<len(cuts) else hi+1
        need(left[1]<new<stop and new!=right[1],"cut must change and preserve both nonempty shots")
        need(not any(m!=right and m[1]==new for m in rows),"target frame occupied by another marker")
        right[1]=new
    else:
        a,z=q["source"];c,d=q["destination"]
        need(lo<=min(a,c) and max(z,d)<=hi and all(n in b["catalog"] for n in q["cameras"]),"unknown camera or interval outside scene")
        need(b["park"]<=min(a,c) or b["park"]>=max(z,d),"park at unchanged endpoint or plateau")
        def mapped(x):return c+(Fraction(x)-a)*Fraction(d-c,z-a)
        moved=[];bound=[]
        for m in rows:
            if m[2] in q["cameras"] and a<=m[1]<=z:
                bound.append(m[0])
                v=mapped(m[1]);need(v.denominator==1,"cut would land on a fractional frame")
                if m[1]!=v:moved.append(m[0])
                m[1]=int(v)
        for m in rows:
            if m[0] in moved:need(sum(r[1]==m[1] for r in rows)==1,"retimed marker collision")
        for ac in b['actions'].values():
            for curve in ac['curves']:
                keys=curve['keys'];need(all(a<=k[0][0]<=z for k in keys),"retime requires entire selected transform action")
                for k in keys:
                    need(k[3] in ('CONSTANT','LINEAR','BEZIER') and (k[3]!='BEZIER' or k[4:6]==['FREE','FREE']),"only constant/linear or free-handle Bezier keys")
                    for pt in k[:3]:pt[0]=f32(float(mapped(pt[0])))
                need(all(keys[i][0][0]<keys[i+1][0][0] for i in range(len(keys)-1)),"keys collapse under float precision")
        need(bound and b["actions"],"group requires camera cut and transform action")
    rows.sort(key=lambda m:m[0]); cuts=sorted((m[1],m[2]) for m in rows if m[2])
    need(len(set(f for f,_ in cuts))==len(cuts),"ambiguous simultaneous camera cuts")
    if cuts:
        past=[n for f,n in cuts if f<=b['park']]
        need((past[-1] if past else cuts[0][1])==b['active'],"cut changes parked active camera")
    need(b!=before,"no effective change")
    return b

def apply(bpy,scene,camera,q):
    wanted=expected(state(bpy,scene,camera,q),q)
    if q["operation"]=="cuts":
        for r in q["cuts"]:
            m=scene.timeline_markers.new(r["name"],frame=r["frame"]);m.camera=scene.objects[r["camera"]];m.select=False
    elif q["operation"]=="move_cut":
        scene.timeline_markers[q["right"]].frame=q["left_last"]+1
    else:
        for n,fr,_,_ in wanted['markers']:scene.timeline_markers[n].frame=fr
        for n,ac in wanted['actions'].items():
            for f,cv in zip(curves(scene.objects[n]),ac['curves']):
                for k,row in zip(f.keyframe_points,cv['keys']):
                    k.co=row[0];k.handle_left=row[1];k.handle_right=row[2]
    need(state(bpy,scene,camera,q)==wanted,"native changes differ from predicted cut/retime state")
