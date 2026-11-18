"""Narrow two-key camera XYZ timing profile within shared core transaction."""
import copy,math,struct,json
SCHEMA='camera-existing-two-key-explicit-v2'
def f32(v):return struct.unpack('f',struct.pack('f',v))[0]
def check(ok,msg,n):
 if not ok:n.fail('UNSUPPORTED',msg)
def canonical(value):
 """Finite JSON only; retain bool/int/float distinctions and reject coercion."""
 def validate(v):
  if v is None or type(v) in (bool,str,int):return
  if type(v) is float:
   if not math.isfinite(v):raise ValueError('Non-finite witness')
   return
  if type(v) is list:
   for x in v:validate(x)
   return
  if type(v) is dict and all(type(k) is str for k in v):
   for x in v.values():validate(x)
   return
  raise ValueError('Non-JSON witness type')
 validate(value)
 return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)
def strict_equal(a,b,n):
 try:return canonical(a)==canonical(b)
 except (ValueError,TypeError,OverflowError):n.fail('UNSUPPORTED','Witness must be strict finite JSON')
def interval(before,n):
 check(type(before)is list and len(before)==3,'Exact XYZ bag required',n)
 times=None
 moving=False
 for i,c in enumerate(before):
  check(c['data_path']=='location'and type(c['array_index'])is int and c['array_index']==i,'Ordered XYZ only',n)
  check(not c['modifiers']and not c['sampled_points']and c['properties']['extrapolation']=='CONSTANT'and c['properties']['mute']is False,'Plain constant curves only',n)
  check(len(c['keys'])==2,'Two keys only',n)
  ts=[]
  for k in c['keys']:
   check(len(k['co'])==2 and all(type(v)in(int,float)and math.isfinite(v)for v in k['co']),'Finite endpoint required',n)
   t=k['co'][0];check(int(t)==t and abs(t)<=1048574 and f32(t)==t,'Representable integer endpoints required',n);ts.append(t)
   check(k['interpolation']=='LINEAR'and k['handle_left_type']==k['handle_right_type']=='FREE','Existing FREE linear keys only',n)
   check(all(type(k[side])is list and len(k[side])==2 and all(type(v)in(int,float)and math.isfinite(v)for v in k[side])for side in ('handle_left','handle_right')),'Finite FREE baseline handles required',n)
  check(ts[0]<ts[1] and (times is None or ts==times),'Common strictly ordered XYZ endpoints required',n)
  times=ts;moving=moving or c['keys'][0]['co'][1]!=c['keys'][1]['co'][1]
 check(moving,'Static camera has no motion to ease',n)
 first,last=times;left=f32(first+(last-first)/3);right=f32(last-(last-first)/3)
 check(first<left<right<last,'Quantized handles must remain strictly inside interval',n)
 return times

def report(w):
 changes=[]
 for old,new in zip(w['before'],w['after']):
  for index,side in ((0,'handle_right'),(1,'handle_left')):
   changes.append({'data_path':old['data_path'],'array_index':old['array_index'],
    'frame':old['keys'][index]['co'][0],'property':side,
    'before':copy.deepcopy(old['keys'][index][side]),'after':copy.deepcopy(new['keys'][index][side])})
 return {'schema':SCHEMA,'camera':w['camera'],'interval':w['interval'],'easing':w.get('easing','EASE_IN_OUT'),
  'handle_changes':changes,'quantization':'IEEE754 float32 inner handles',
  'preserved':'Endpoint coordinates, outer handles, all remaining bag metadata',
  'scope':'Explicit exclusive parentless two-key XYZ existing motion; no new path generation',
  'old_action_recovery':'Original source file; candidate cold retention not asserted'}

def expected_bag(before,n,easing='EASE_IN_OUT'):
 check(type(easing)is str and easing in ('EASE_IN_OUT','EASE_IN','EASE_OUT'),'Unsupported easing profile',n)
 first,last=interval(before,n);after=copy.deepcopy(before)
 for c in after:
  for k in c['keys']:k['interpolation']='BEZIER'
  a,b=c['keys'][0]['co'][1],c['keys'][1]['co'][1]
  # Quadratic one-sided easing; all inner controls remain inside endpoint hull.
  left=f32(a+2*(b-a)/3) if easing=='EASE_OUT' else a
  right=f32(a+(b-a)/3) if easing=='EASE_IN' else b
  c['keys'][0]['handle_right']=[f32(first+(last-first)/3),left]
  c['keys'][1]['handle_left']=[f32(last-(last-first)/3),right]
 return after
def preflight(manifest,rows,plan,n):
 check(type(plan)is dict and set(plan) in ({'schema','camera','before_bag'},{'schema','camera','before_bag','easing'})and plan['schema']==SCHEMA and type(plan['camera'])is str and bool(plan['camera']),'Exact compiled plan required',n)
 check(len(rows)==3,'Exactly three targets',n)
 owner=rows[0]['owner'];action=rows[0]['action'];bag=rows[0]['bag']
 check(owner.name==plan['camera'] and owner.type=='CAMERA'and owner.parent is None and not owner.constraints and not owner.modifiers,'Parentless unconstrained camera only',n)
 check(action is not None and n.effective_users(action)==1,'Exclusive existing Action required',n)
 check(all(r['owner']==owner and r['action']==action and r['bag']==bag for r in rows),'One actual owner Action and bag',n)
 check(sorted((r['spec']['data_path'],r['spec']['array_index'])for r in rows)==[('location',i)for i in range(3)],'Unique XYZ targets only',n)
 ad=owner.animation_data
 check(ad is not None and not ad.drivers and not ad.nla_tracks and not ad.use_tweak_mode,'No drivers/NLA/tweak mode',n)
 check(owner.data.animation_data is None,'Animated optics unsupported in first slice',n)
 before=n.bag_state(bag);check(strict_equal(before,plan['before_bag'],n),'Actual source bag differs',n);after=expected_bag(before,n,plan.get('easing','EASE_IN_OUT'))
 want=[]
 for r in rows:
  i=r['spec']['array_index']
  for k in before[i]['keys']:want.append({'op':'set_key','target':r['spec']['id'],'frame':k['co'][0],'value':k['co'][1],'interpolation':'BEZIER'})
 check(len(manifest['operations'])==6 and all(o in want for o in manifest['operations']) and len({(o['target'],o['frame'])for o in manifest['operations']})==6,'Exactly six unchanged-value BEZIER operations',n)
 return {'before':before,'after':after,'camera':owner.name,'interval':interval(before,n),'easing':plan.get('easing','EASE_IN_OUT')}
def apply(rows,w,n):
 bag=rows[0]['candidate_bag']
 for i in range(3):
  c=bag.fcurves.find('location',index=i)
  c.keyframe_points[0].handle_right=w['after'][i]['keys'][0]['handle_right']
  c.keyframe_points[1].handle_left=w['after'][i]['keys'][1]['handle_left']
  c.update()
 check(n.bag_state(bag)==w['after'],'Candidate exact rounded handles/whole bag readback mismatch',n)
def verify(rows,w,n):
 check(n.bag_state(rows[0]['bag'])==w['after'],'Fresh candidate whole-bag mismatch',n)

def qualify_table_owner(owner,scene,bpy,effective_users):
 """Existing narrow table ownership, generalized names/ranges, not shared-ID waiver.
 Full table and all unrelated state must remain exact in caller's snapshot.
 """
 def require(ok):
  if not ok:raise ValueError('Camera table owner reference qualification failed')
 require(owner.type=='CAMERA' and owner.library is None and owner.override_library is None)
 require(owner.use_fake_user is False and owner.use_extra_user is False and owner.users==2)
 require(tuple(owner.users_scene)==(scene,) and len(owner.users_collection)==1 and scene.camera!=owner)
 collection=owner.users_collection[0]
 require(collection in tuple(scene.collection.children_recursive)+(scene.collection,))
 # Embedded master-collection references are folded into the owning Scene by Blender.
 # Keep exact users/scene/collection/table/Action gates; never waive other users.
 if collection==scene.collection:
  require(collection.is_embedded_data and collection.library is None and collection.override_library is None)
  require(owner.name in collection.objects and len(bpy.data.scenes)==1)
  expected_users={scene}
 else:
  require(not collection.is_embedded_data)
  expected_users={scene,collection}
 require(set(bpy.data.user_map(subset={owner}).get(owner,set()))==expected_users)
 require(scene.camera_live_source=='SEQUENCE' and 1<=len(scene.camera_live_shots)<=128)
 names=set();last=None
 for row in scene.camera_live_shots:
  require(type(row.name)is str and bool(row.name) and row.name not in names);names.add(row.name)
  require(type(row.first)is int and type(row.last)is int and row.first<=row.last)
  require(last is None or row.first==last+1);last=row.last
  require(row.camera is not None and row.camera.type=='CAMERA' and row.camera in tuple(scene.objects))
 require(sum(row.camera==owner for row in scene.camera_live_shots)==1)
 ad=owner.animation_data
 require(ad is not None and ad.action is not None and effective_users(ad.action)==1)
