"""Pure strict Static protected-delta contract; no bpy."""
SECTIONS={'scene','ids','objects','geometry','materials','lights','cameras','tables','layers','actions','references'}
def need(ok,msg):
 if not ok:raise ValueError(msg)
def complete(s):
 need(set(s)==SECTIONS|{'rig_context'},'Exact required snapshot sections')
 if 'rig_context' in s:
  r=s['rig_context'];need(isinstance(r,dict) and set(r)=={'schema','rigs','bindings'} and r['schema']=='bounded-independent-rig-context-v1' and isinstance(r['rigs'],dict) and bool(r['rigs']) and isinstance(r['bindings'],dict),'Exact bounded rig context section')
 for key in SECTIONS:need(isinstance(s[key],dict),'Structured snapshot '+key)
 need(bool(s['actions']) and bool(s['objects']) and bool(s['ids']),'Empty inventory not proof')
 arms={name for name,o in s['objects'].items()if o.get('type')=='ARMATURE'}
 arm_ids={key for key,v in s['ids'].items()if v.get('type')=='Armature'}
 refs={name for name,o in s['objects'].items()if 'rig_context_ref'in o}
 need(bool(arms)==bool(arm_ids)==('rig_context'in s),'Armature inventory requires rig context')
 if not arms:need(not refs,'Rig references without rig context');return
 r=s['rig_context'];need(set(r['rigs'])==arms and set(r['bindings'])==refs,'Rig context inventory mismatch')
 need(arms<=refs,'Missing rig binding')
 expected_ids=set();roots=[]
 for name in arms:
  obj=s['objects'][name];record=r['rigs'][name];data=obj['data']
  need(isinstance(data,dict) and data.get('type')=='Armature' and record.get('data')==data,'Rig data identity mismatch')
  expected_ids.add('Armature:'+data['name'])
 need(expected_ids==arm_ids and len(expected_ids)==len(arms),'Armature data inventory/shared mismatch')
 for name in refs:
  obj=s['objects'][name];binding=r['bindings'][name];parent=binding.get('parent');need(obj['rig_context_ref']==name and isinstance(parent,dict) and parent.get('type')=='Object','Rig binding reference mismatch')
  parent_name=parent.get('name');need(parent_name in s['objects'],'Missing rig parent')
  need(binding.get('parent_type')=='OBJECT' and binding.get('parent_bone')=='','Unsupported rig parent kind')
  if name in arms:
   need(s['objects'][parent_name]['type']=='EMPTY' and binding.get('modifiers')==[],'Rig root binding mismatch');roots.append(parent_name)
  else:
   mods=binding.get('modifiers');need(obj['type']=='MESH' and parent_name in arms and isinstance(mods,list) and len(mods)==1 and mods[0].get('type')=='ARMATURE' and mods[0].get('object')==parent,'Bound mesh context mismatch')
 need(len(set(roots))==len(roots),'Shared/helper rig root')


def expected(before,document,new_pose):
 from copy import deepcopy
 complete(before)
 cam,data=document['camera'],document['camera_data']
 obj=before['objects'][cam];props=obj['properties'];base=document['base_pose']
 need(obj['type']=='CAMERA' and obj['data']=={'type':'Camera','name':data,'library':None},'Strict target identity')
 need(props['location']==base['location'] and obj['transform']['location']==base['location'],'Strict source location')
 for field in ('matrix_basis','matrix_local','matrix_world'):
  need(props[field]==base['matrix_basis' if field=='matrix_local' else field],'Strict source matrix')
 need(obj['matrix_basis']==base['matrix_basis'],'Strict source authored matrix')
 need(before['cameras'][data]['properties']['lens']==document['base_lens'],'Strict source lens')
 value=deepcopy(before);o=value['objects'][cam]
 o['properties']['location']=deepcopy(new_pose['location']);o['transform']['location']=deepcopy(new_pose['location'])
 for field in ('matrix_basis','matrix_local','matrix_world'):
  o['properties'][field]=deepcopy(new_pose['matrix_basis' if field=='matrix_local' else field])
 o['matrix_basis']=deepcopy(new_pose['matrix_basis'])
 value['cameras'][data]['properties']['lens']=document['lens']
 return value

REPORT_LIMIT=64*1024*1024
def parse_report(raw):
 import json,math
 need(type(raw) is bytes and len(raw)<=REPORT_LIMIT,'Bounded strict report bytes required')
 depth=0;quoted=False;escape=False
 for byte in raw:
  if quoted:
   if escape:escape=False
   elif byte==92:escape=True
   elif byte==34:quoted=False
  elif byte==34:quoted=True
  elif byte in (91,123):
   depth+=1;need(depth<=32,'Report nesting budget exceeded')
  elif byte in (93,125):depth-=1;need(depth>=0,'Report nesting invalid')
 need(depth==0 and not quoted,'Incomplete report JSON')
 def pairs(items):
  out={}
  for k,v in items:
   need(k not in out,'Duplicate report JSON key');out[k]=v
  return out
 def number(s):
  f=float(s);need(math.isfinite(f),'Nonfinite report number');return f
 def bad(s):raise ValueError('Nonfinite report constant')
 return json.loads(raw,object_pairs_hook=pairs,parse_float=number,parse_constant=bad)
