"""Bounded, author-confirmed movement of an existing Camera Live sequence boundary.
Operates solely on the pinned two-property original Camera Live RNA definitions.
"""
from copy import deepcopy
def need(ok,msg):
 if not ok:raise ValueError(msg)
def name(n):return type(n)==str and 0<len(n.encode())<=63 and n==n.strip() and '\x00' not in n
def validate(q):
 need(type(q)==dict and set(q)=={'kind','left','right','left_camera','right_camera','old_left_last','new_left_last'} and q['kind']=='legacy_cut','exact legacy_cut request required')
 for k in ('left','right','left_camera','right_camera'):need(name(q[k]),'exact names required')
 need(q['left']!=q['right'] and q['left_camera']!=q['right_camera'],'distinct adjacent named shots and cameras required')
 need(all(type(q[k]) is int and -1048574<=q[k]<=1048574 for k in ('old_left_last','new_left_last')) and q['old_left_last']!=q['new_left_last'],'effective bounded cut shift required')
def prepare(bpy):
 need(not hasattr(bpy.types.Scene,'camera_live_source') and not bpy.data.filepath and bpy.app.background,'empty schema worker required')
 bpy.types.Scene.camera_live_source=bpy.props.EnumProperty(name='Source',items=[('SCENE','Scene Camera','Existing single-camera preview'),('SEQUENCE','Shot Sequence','Continuous local viewport cuts; does not change rendered camera')],default='SCENE')
def row_extras(row):
 # Preserve small explicitly observable annotations rather than discarding them.
 result={}
 for k in row.keys():
  if k in ('name','camera','first','last'):continue  # represented as typed values and explicit-set flags
  v=row[k]
  need(name(k) and type(v) in (str,bool,int,float) and (type(v)!=str or len(v.encode())<2048),'unqualified extra row metadata')
  result[k]=v
 need(len(result)<=16,'row metadata budget exceeded')
 return result
def guard(bpy,s,c,q):
 validate(q)
 pr=s.bl_rna.properties.get('camera_live_shots')
 need(pr and pr.type=='COLLECTION' and pr.fixed_type.identifier=='CAMERA_LIVE_REBUILT_PG_shot' and set(p.identifier for p in pr.fixed_type.properties)=={'rna_type','name','camera','first','last'},'unknown typed row schema')
 need('camera_live_shots' not in s.keys() and 'camera_live_source' not in s.keys(),'ambiguous raw legacy storage')
 need(s.camera_live_source=='SEQUENCE' and s.is_property_set('camera_live_source') and s.is_property_set('camera_live_shots'),'requires explicitly saved original SEQUENCE source and row collection')
 need(2<=len(s.camera_live_shots)<=100 and len(s.timeline_markers)<=1024 and all(not m.camera for m in s.timeline_markers),'bound native camera markers conflict with Live sequence; no migration implied')
def state(bpy,s,c,q):
 guard(bpy,s,c,q);rows=[];seen=set()
 for r in s.camera_live_shots:
  need(name(r.name) and r.name not in seen and r.camera and s.objects.get(r.camera.name)==r.camera and r.camera.type=='CAMERA' and not r.camera.library and not r.camera.override_library and r.camera.data and not r.camera.data.library,'duplicate row or invalid camera pointer')
  need(s.frame_start<=r.first<=r.last<=s.frame_end and (not rows or r.first==rows[-1]['last']+1),'noncontiguous or out-of-scene row interval')
  seen.add(r.name);rows.append({'name':r.name,'camera':r.camera.name,'camera_data':r.camera.data.name,'first':r.first,'last':r.last,'extra':row_extras(r),'is_set':[r.is_property_set(n) for n in ('name','camera','first','last')]})
 need(rows[0]['first']==s.frame_start and rows[-1]['last']==s.frame_end,'sequence must cover the entire declared scene interval')
 need(len({m.name for m in s.timeline_markers})==len(s.timeline_markers),'ambiguous annotation marker names')
 return dict(rows=rows,range=[s.frame_start,s.frame_end],park=s.frame_current,active=c.name,source_mode=s.camera_live_source,notes=sorted([[m.name,m.frame,bool(m.select)] for m in s.timeline_markers]))
def expected(before,q):
 validate(q);out=deepcopy(before);rows=out['rows']
 i=next((i for i,row in enumerate(rows) if row['name']==q['left']),-1)
 need(0<=i<len(rows)-1 and rows[i+1]['name']==q['right'],'named rows are not adjacent in stored order')
 left,right=rows[i:i+2];old=q['old_left_last'];new=q['new_left_last']
 need(left['camera']==q['left_camera'] and right['camera']==q['right_camera'] and left['last']==old and right['first']==old+1,'stale boundary, order, or camera identity')
 need(left['first']<=new<right['last'] and not(min(old,new)<out['park']<=max(old,new)),'would empty a shot or change the parked frame shot')
 left['last']=new;right['first']=new+1;left['is_set'][3]=True;right['is_set'][2]=True
 return out
def apply(bpy,s,c,q):
 b=state(bpy,s,c,q);expected(b,q)
 rows=list(s.camera_live_shots);i=next(i for i,r in enumerate(rows) if r.name==q['left'])
 rows[i].last=q['new_left_last'];rows[i+1].first=q['new_left_last']+1
