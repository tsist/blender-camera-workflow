"""Pure whitelist for the selected native-state delta; no bpy or IO."""
from copy import deepcopy
import math
from . import model

STATE_KEYS={'protected','extras','main_ids','tables','camera_optics','object_transforms','evaluated_scene_matrices'}
def require(ok,message):
 if not ok:raise ValueError(message)

def selected_pose(document):
 doc=model.validate_document(document);pose=deepcopy(doc['base_pose']);pose['location']=deepcopy(doc['location'])
 for field in ('matrix_basis','matrix_world'):
  for i in range(3):pose[field][i][3]=doc['location'][i]
 return model.validate_pose(pose)

def expected_state(before,document):
 doc=model.validate_document(document);cam,data=doc['camera'],doc['camera_data'];pose=doc['base_pose']
 require(type(before)is dict and set(before) in (STATE_KEYS,STATE_KEYS|{'strict_rig_scene'}),'Selected state fields differ')
 arms={n for n,o in before['protected']['objects'].items() if o['type']=='ARMATURE'}
 arm_ids={v[2] for v in before['main_ids'] if v[1]=='Armature'}
 require(bool(arms)==bool(arm_ids)==('strict_rig_scene' in before),'Strict rig section required by inventory')
 if arms:
  from . import rig_contract
  strict=before['strict_rig_scene'];rig_contract.complete(strict)
  require(set(strict['rig_context']['rigs'])==arms,'Strict/selected rig inventory mismatch')
  require({x['data']['name'] for x in strict['rig_context']['rigs'].values()}==arm_ids,'Strict/selected Armature IDs mismatch')
  require(all(type(v.get('embedded')) is bool for v in strict['ids'].values()),'Strict ID embedding marker required')
  main=[v for v in strict['ids'].values() if not v['embedded']]
  require(all(v['type']=='ShaderNodeTree' for v in strict['ids'].values() if v['embedded']),'Unexpected embedded ID type')
  ids={(v['type'],v['name']):v for v in main}
  require(len(ids)==len(main),'Duplicate strict main ID identity')
  roster={(v[1],v[2]) for v in before['main_ids']}
  require(roster==set(ids),'Strict/main ID inventory mismatch')
  require(all(ids[(v[1],v[2])]['use_fake_user']==v[3] for v in before['main_ids']),'Strict/main fake-user mismatch')
  require(set(strict['references'])==set(strict['ids']),'Strict reference inventory mismatch')
  require(set(strict['objects'])==set(before['object_transforms']),'Strict/all-object inventory mismatch')
  for section,types in [('objects',{'Object'}),('geometry',{'Mesh'}),('actions',{'Action'}),('cameras',{'Camera'}),('materials',{'Material'}),('lights',{'AreaLight','PointLight','SunLight','SpotLight'})]:
   require(set(strict[section])=={name for kind,name in ids if kind in types},'Strict section/ID inventory mismatch: '+section)
  for name,obj in before['protected']['objects'].items():
   so=strict['objects'].get(name,{})
   require(so.get('type')==obj['type'] and (so.get('data')or{}).get('name')==obj['data'],'Strict/selected object identity mismatch')
  require(strict['scene']['name']==doc['scene'],'Strict scene identity mismatch')
 require(before['object_transforms'][cam]==pose,'Source native pose differs')
 require(before['protected']['objects'][cam]['basis']==pose['matrix_basis'],'Source protected basis differs')
 require(before['evaluated_scene_matrices'][cam]==pose['matrix_world'],'Source evaluated target differs')
 require(before['protected']['camera_data'][cam]['lens']==doc['base_lens'] and before['camera_optics'][data]['lens']==doc['base_lens'],'Source lens witness differs')
 expected=deepcopy(before);new_pose=selected_pose(doc)
 expected['protected']['camera_data'][cam]['lens']=doc['lens'];expected['camera_optics'][data]['lens']=doc['lens']
 expected['object_transforms'][cam]=new_pose
 expected['protected']['objects'][cam]['basis']=deepcopy(new_pose['matrix_basis'])
 expected['evaluated_scene_matrices'][cam]=deepcopy(new_pose['matrix_world'])
 if arms:expected['strict_rig_scene']=rig_contract.expected(before['strict_rig_scene'],doc,new_pose)
 return expected

def verify_apply(report,document):
 doc=model.validate_document(document)
 require(type(report)is dict and set(report)=={'output_sha','before','expected','projection_before','projection_after'},'Apply fields differ')
 require(report['expected']==expected_state(report['before'],doc),'Apply changed undeclared state')
 for key,pose,lens in [('projection_before',doc['base_pose'],doc['base_lens']),('projection_after',selected_pose(doc),doc['lens'])]:
  value=report[key]
  require(type(value)is dict and set(value)=={'lens','matrix_world','horizontal_slopes','vertical_slopes'},'Projection fields differ')
  require(value['lens']==lens and value['matrix_world']==pose['matrix_world'],'Projection target differs')
  for axis in ('horizontal_slopes','vertical_slopes'):
   require(type(value[axis])is list and len(value[axis])==4,'Projection shape differs')
   for v in value[axis]:model._scalar32(v)
 for axis in ('horizontal_slopes','vertical_slopes'):
  for old,new in zip(report['projection_before'][axis],report['projection_after'][axis]):
   require(math.isclose(new,old*doc['base_lens']/doc['lens'],rel_tol=3e-6,abs_tol=3e-6),'Native focal projection ratio differs')
 return True
