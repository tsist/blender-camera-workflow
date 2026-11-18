"""Bounded, read-only focus-scene snapshot adapter. HOST prepared, native unqualified.

No save/render/frame_set, RNA assignment, registration, or curve-edit engine.
Capture requires an already-loaded private source and the pinned shared animation
native module. Unknown semantic ID/node/dependency types fail closed. It protects
selected authored RNA and geometry for this supported technical-scene domain,
not arbitrary .blend equivalence, evaluated motion, UI state, or optical pixels.
"""
import hashlib
import json
import math
from pathlib import Path

UI_TYPES={'Screen','WorkSpace','WindowManager'}
NODE_TYPES={'ShaderNodeBsdfPrincipled','ShaderNodeOutputMaterial','ShaderNodeRGB','ShaderNodeValue','ShaderNodeEmission','ShaderNodeBackground','ShaderNodeOutputWorld','ShaderNodeOutputLight'}
TRANSIENT={'rna_type','name','name_full','session_uid','users','is_updated','is_updated_data','is_evaluated','is_editable','is_missing','is_runtime_data','is_library_indirect','is_embedded_data','is_valid','is_empty','use_fake_user','use_extra_user'}
LIMITS={'ids':512,'objects':256,'vertices':500000,'polygons':500000,'keys':50000,'nodes':256}

def need(ok,message):
 if not ok:raise ValueError(message)

def plain(value):
 """Finite HOST-safe encoding; never stringify opaque RNA references."""
 if value is None or isinstance(value,(bool,str,int)):return value
 if isinstance(value,float):
  need(math.isfinite(value),'Nonfinite snapshot value');return value
 if isinstance(value,(set,frozenset)):return sorted(plain(x) for x in value)
 if isinstance(value,dict):return {str(k):plain(v) for k,v in sorted(value.items())}
 if isinstance(value,(tuple,list)):return [plain(x) for x in value]
 if hasattr(value,'to_list'):return plain(value.to_list())
 if hasattr(value,'to_dict'):return plain(value.to_dict())
 try:return [plain(x) for x in value]
 except TypeError:raise ValueError('Unsupported snapshot scalar type: '+type(value).__name__)

def identity(block):
 if block is None:return None
 return {'type':block.bl_rna.identifier,'name':block.name_full,'library':block.library.filepath if block.library else None}

def id_key(block):return block.bl_rna.identifier+':'+block.name_full

def scalars(item,exclude=()):
 """All primitive RNA fields except identified transient fields; no recursive RNA graph walk."""
 out={}
 for p in item.bl_rna.properties:
  if p.identifier in TRANSIENT or p.identifier in exclude:continue
  if p.type in {'BOOLEAN','INT','FLOAT','STRING','ENUM'}:out[p.identifier]=plain(getattr(item,p.identifier))
 return out

def custom(item,shared):
 # RNA exposes keys() even for types unable to own IDProperties, e.g. SequenceTimelineChannel.
 if not hasattr(item,'keys'):return {'supported':False,'values':{}}
 try:item.keys()
 except TypeError as error:
  if str(error)!="bpy_struct.keys(): this type doesn't support IDProperties":raise
  return {'supported':False,'values':{}}
 return {'supported':True,'values':shared.custom_state(item)}

def inventory(bpy):
 result={}
 def add(x):
  if not isinstance(x,bpy.types.ID):return
  ptr=int(x.as_pointer())
  if ptr in result:return
  result[ptr]=x
  for attr in ('node_tree','compositing_node_group','shape_keys'):
   child=getattr(x,attr,None)
   if child is not None:add(child)
 for p in bpy.data.bl_rna.properties:
  if p.type=='COLLECTION':
   for x in getattr(bpy.data,p.identifier,()):add(x)
 need(len(result)<=LIMITS['ids'],'ID budget exceeded')
 return sorted(result.values(),key=lambda x:(x.bl_rna.identifier,x.name_full))

def action_record(a,shared):
 need(len(a.slots)==1 and len(a.layers)==1 and len(a.layers[0].strips)==1,'Single-slot/layer/strip Actions only')
 strip=a.layers[0].strips[0]
 need(strip.type=='KEYFRAME' and len(strip.channelbags)==1,'Single KEYFRAME bag only')
 bag=strip.channelbags[0];need(bag.slot_handle==a.slots[0].handle,'Action bag slot mismatch')
 curves=[];count=0
 for fc in sorted(bag.fcurves,key=lambda f:(f.data_path,f.array_index)):
  need(not fc.modifiers and not fc.sampled_points,'FCurve modifiers/samples unsupported')
  count+=len(fc.keyframe_points);need(count<=LIMITS['keys'],'Action key budget exceeded')
  raw=shared.curve_state(fc)
  keys=[]
  for k in fc.keyframe_points:
   # Full key scalar witness retained, while canonical locations allow existing HOST contract use.
   props=scalars(k,{'co','co_ui','handle_left','handle_right','handle_left_type','handle_right_type','interpolation'})
   keys.append({'co':plain(k.co),'left':plain(k.handle_left),'right':plain(k.handle_right),'left_type':k.handle_left_type,'right_type':k.handle_right_type,'interpolation':k.interpolation,'properties':props})
  curves.append({'path':fc.data_path,'index':fc.array_index,'extrapolation':fc.extrapolation,'keys':keys,'properties':raw['properties'],'group':raw['group'],'modifiers':raw['modifiers'],'sampled_points':raw['sampled_points']})
 return {'use_fake_user':bool(a.use_fake_user),'curves':curves,'properties':scalars(a),'custom':custom(a,shared),'slots':[{'identifier':s.identifier,'properties':scalars(s)} for s in a.slots],'layer':{'name':a.layers[0].name,'properties':scalars(a.layers[0])},'strip':scalars(strip),'bag':{'slot_handle':bag.slot_handle,'properties':scalars(bag),'groups':[{'name':g.name,'properties':scalars(g)} for g in bag.groups]}}

def binding(obj):
 ad=getattr(obj,'animation_data',None)
 if ad is None:return None
 need(not ad.drivers and not ad.nla_tracks and not ad.use_tweak_mode,'Drivers/NLA/tweak mode unsupported')
 return {'action':ad.action.name if ad.action else None,'slot':ad.action_slot.identifier if ad.action_slot else None,'slot_handle':ad.action_slot_handle,'properties':scalars(ad)}

def validate_id_animation(block):
 # Only Object bindings have a protected binding section in this fixed-source adapter.
 if block.bl_rna.identifier!='Object':
  need(getattr(block,'animation_data',None) is None,'Non-Object animation_data unsupported: '+block.bl_rna.identifier)
 return binding(block)

def socket_identity(socket,direction,index):
 """Use actual RNA and socket-instance identity, never interface-only bl_socket_idname."""
 need(direction in {'INPUT','OUTPUT'},'Socket direction required')
 rna=socket.bl_rna.identifier;identifier=socket.identifier;dtype=socket.type;is_output=socket.is_output
 need(isinstance(rna,str) and rna.startswith('NodeSocket') and isinstance(identifier,str) and bool(identifier),'Explicit socket RNA/identifier required')
 need(type(is_output) is bool and is_output==(direction=='OUTPUT'),'Socket direction mismatch')
 need(isinstance(dtype,str) and bool(dtype),'Socket data type required')
 declared_default=any(prop.identifier=='default_value' for prop in socket.bl_rna.properties)
 return {'name':socket.name,'identifier':identifier,'rna_type':rna,'data_type':dtype,'direction':direction,'index':index,'default_declared_in_rna':declared_default}

def socket_record(socket,direction,index):
 identity_record=socket_identity(socket,direction,index)
 need(identity_record['data_type'] in {'VALUE','INT','BOOLEAN','VECTOR','RGBA','SHADER'},'Unsupported shader socket data type: '+identity_record['data_type'])
 # A declared RNA default must be read successfully. No catch/default-on-AttributeError.
 value=plain(socket.default_value) if identity_record['default_declared_in_rna'] else None
 return {**identity_record,'properties':scalars(socket),'default':value}

def tree_owners(bpy):
 refs={}
 for owner in inventory(bpy):
  for attribute in ('node_tree','compositing_node_group'):
   tree=getattr(owner,attribute,None)
   if tree is not None and tree.bl_rna.identifier=='ShaderNodeTree':
    refs.setdefault(int(tree.as_pointer()),[]).append([owner.bl_rna.identifier,owner.name_full,attribute])
 return {ptr:sorted(values) for ptr,values in refs.items()}

def qualified_id_key(block,owners):
 base=id_key(block)
 if block.bl_rna.identifier=='ShaderNodeTree' and int(block.as_pointer()) in owners:
  return base+'@owners='+json.dumps(owners[int(block.as_pointer())],ensure_ascii=False,separators=(',',':'))
 return base

def all_shader_tree_preflight(bpy):
 owners=tree_owners(bpy);result={}
 for tree in inventory(bpy):
  if tree.bl_rna.identifier!='ShaderNodeTree':continue
  key=qualified_id_key(tree,owners);need(key not in result,'Ambiguous shader tree identity')
  nodes=[]
  for node in tree.nodes:
   nodes.append({'name':node.name,'type':node.bl_idname,'inputs':[socket_identity(sock,'INPUT',i) for i,sock in enumerate(node.inputs)],'outputs':[socket_identity(sock,'OUTPUT',i) for i,sock in enumerate(node.outputs)]})
  result[key]={'tree':identity(tree),'owners':owners.get(int(tree.as_pointer()),[]),'nodes':nodes}
 return result

def node_tree(tree,shared):
 if tree is None:return None
 need(tree.bl_rna.identifier=='ShaderNodeTree','Only bounded ShaderNodeTree supported')
 need(tree.animation_data is None,'Animated shader trees unsupported')
 need(len(tree.nodes)<=LIMITS['nodes'],'Node budget exceeded')
 nodes={}
 for node in tree.nodes:
  need(node.bl_idname in NODE_TYPES,'Unsupported shader node: '+node.bl_idname)
  inputs=[socket_record(sock,'INPUT',i) for i,sock in enumerate(node.inputs)];outputs=[socket_record(sock,'OUTPUT',i) for i,sock in enumerate(node.outputs)]
  need(len({x['identifier'] for x in inputs})==len(inputs) and len({x['identifier'] for x in outputs})==len(outputs),'Ambiguous socket identifiers')
  nodes[node.name]={'type':node.bl_idname,'properties':scalars(node),'custom':custom(node,shared),'inputs':inputs,'outputs':outputs}
 return {'name':tree.name,'properties':scalars(tree),'custom':custom(tree,shared),'nodes':nodes,'links':sorted([[l.from_node.name,l.from_socket.identifier,l.to_node.name,l.to_socket.identifier] for l in tree.links])}

def sequence_record(scene,shared):
 need(not scene.rigidbody_world,'Rigid body world unsupported')
 seq=scene.sequence_editor
 if seq is None:return {'exists':False}
 need(not len(seq.strips_all),'Nonempty VSE unsupported')
 need(getattr(seq,'active_strip',None) is None,'VSE active strip inconsistent with empty inventory')
 need(not len(getattr(seq,'meta_stack',())),'VSE meta stack unsupported')
 channels=[{'name':ch.name,'properties':scalars(ch),'custom':custom(ch,shared)} for ch in getattr(seq,'channels',())]
 pointers={}
 for prop in seq.bl_rna.properties:
  if prop.identifier=='rna_type':continue
  if prop.type=='POINTER':
   value=getattr(seq,prop.identifier)
   need(value is None or value==scene,'Unknown nested VSE setting: '+prop.identifier)
   pointers[prop.identifier]=None if value is None else {'scene':scene.name}
  elif prop.type=='COLLECTION' and prop.identifier not in {'channels','strips','strips_all','meta_stack'}:
   need(not len(getattr(seq,prop.identifier)),'Unknown nonempty VSE collection: '+prop.identifier)
 return {'exists':True,'strips':[],'active_strip':None,'meta_stack':[],'channels':channels,'pointers':pointers,'properties':scalars(seq),'custom':custom(seq,shared)}

def preflight_inventory(bpy):
 """Diagnostic only, emitted even when supported snapshot refuses later. No repair."""
 scene=bpy.context.scene;seq=scene.sequence_editor
 return {'rigidbody_world_exists':scene.rigidbody_world is not None,'sequence_editor_exists':seq is not None,'sequence_strip_count':len(seq.strips_all) if seq else 0,'sequence_active_strip':getattr(getattr(seq,'active_strip',None),'name',None),'sequence_meta_depth':len(getattr(seq,'meta_stack',())) if seq else 0,'compositor_exists':bool(getattr(scene,'compositing_node_group',None) or getattr(scene,'node_tree',None)),'id_types':sorted(set(x.bl_rna.identifier for x in inventory(bpy))),'meshes':{m.name:{'uv_layers':[u.name for u in m.uv_layers],'color_attributes':[a.name for a in m.color_attributes],'attributes':[{'name':a.name,'domain':a.domain,'type':a.data_type,'count':len(a.data)} for a in m.attributes]} for m in bpy.data.meshes},'shader_tree_count':sum(x.bl_rna.identifier=='ShaderNodeTree' for x in inventory(bpy)),'nonobject_animation_data':[identity(x) for x in inventory(bpy) if x.bl_rna.identifier!='Object' and getattr(x,'animation_data',None) is not None]}

def mesh_attributes(mesh):
 """Read actual typed attribute payloads, including UVMap/topology/selection, without guessing field names."""
 counts={'POINT':len(mesh.vertices),'EDGE':len(mesh.edges),'FACE':len(mesh.polygons),'CORNER':len(mesh.loops)}
 supported={'FLOAT2','FLOAT_VECTOR','INT','INT32_2D','BOOLEAN'}
 result={};total=0
 for attr in mesh.attributes:
  need(attr.data_type in supported and attr.domain in counts,'Unsupported mesh attribute type/domain: '+attr.name)
  need(len(attr.data)==counts[attr.domain],'Attribute domain cardinality mismatch: '+attr.name)
  total+=len(attr.data);need(total<=2000000,'Attribute value budget exceeded')
  data=[]
  for value in attr.data:
   row=scalars(value);need(bool(row),'Unknown empty attribute payload: '+attr.name);data.append(row)
  result[attr.name]={'type':attr.data_type,'domain':attr.domain,'properties':scalars(attr),'data':data}
 return result

def uv_layers_record(mesh,attributes):
 result=[]
 for uv in mesh.uv_layers:
  need(uv.name in attributes and attributes[uv.name]['type']=='FLOAT2' and attributes[uv.name]['domain']=='CORNER','UV layer missing matching attribute')
  result.append({'name':uv.name,'properties':scalars(uv)})
 return {'layers':result,'active_index':getattr(mesh.uv_layers,'active_index',None),'active_name':getattr(getattr(mesh.uv_layers,'active',None),'name',None)}

def capture(bpy):
 from . import rig_witness as shared
 source_sha="0"*64
 helper_name=None
 """Return envelope{snapshot,evidence,scope}; does not open, save, sample, or edit."""
 need(isinstance(source_sha,str) and len(source_sha)==64,'Pinned source lineage required')
 need(tuple(bpy.app.version)==(5,2,1),'Pinned Blender version required')
 need(len(bpy.data.objects)<=128 and len(bpy.data.armatures)<=4,'Static rig context object/rig budget exceeded')
 need(sum(len(m.vertices) for m in bpy.data.meshes)<=10000 and sum(len(m.polygons) for m in bpy.data.meshes)<=12000,'Static rig context total geometry budget exceeded')
 native_sha=hashlib.sha256(Path(shared.__file__).read_bytes()).hexdigest()
 need(sum(len(m.edges) for m in bpy.data.meshes)<=24000,'Static total edge budget exceeded')
 need(sum(len(m.loops) for m in bpy.data.meshes)<=48000,'Static total loop budget exceeded')
 need(sum(len(m.attributes) for m in bpy.data.meshes)<=1024,'Static attribute count budget exceeded')
 need(sum(len(at.data) for m in bpy.data.meshes for at in m.attributes)<=350000,'Static attribute element budget exceeded')
 need(all(len(m.uv_layers)<=4 for m in bpy.data.meshes) and sum(len(m.uv_layers) for m in bpy.data.meshes)<=128,'Static UV layer budget exceeded')
 need(sum(len(v.groups) for m in bpy.data.meshes for v in m.vertices)<=20000,'Static total weight budget exceeded')
 need(all(len(o.vertex_groups)<=64 for o in bpy.data.objects),'Static vertex group budget exceeded')
 need(sum(len(fc.keyframe_points) for ac in bpy.data.actions for la in ac.layers for st in la.strips for bag in st.channelbags for fc in bag.fcurves)<=5000,'Static total key budget exceeded')
 need(len(bpy.data.scenes)==1,'One technical scene only');scene=bpy.context.scene
 need(scene.name=='NeutralTechnical','Fixed scene required')
 sequence=sequence_record(scene,shared)
 need(not getattr(scene,'compositing_node_group',None) and not getattr(scene,'node_tree',None),'Compositor unsupported')
 rig_context=capture_rig_context(bpy,shared,helper_name)
 blocks=inventory(bpy);ids={};references={};owners=tree_owners(bpy)
 allowed={'Armature','Object','Mesh','Camera','Action','Collection','Scene','Material','ShaderNodeTree','World','AreaLight','PointLight','SunLight','SpotLight'}
 reverse=bpy.data.user_map()
 for x in blocks:
  if x.bl_rna.identifier in UI_TYPES:continue
  need(x.bl_rna.identifier in allowed,'Unsupported semantic ID: '+x.bl_rna.identifier)
  need(not x.library and not x.override_library,'Linked/override ID unsupported')
  validate_id_animation(x)
  key=qualified_id_key(x,owners);need(key not in ids,'Ambiguous semantic ID snapshot key')
  ids[key]={'type':x.bl_rna.identifier,'name':x.name_full,'embedded':bool(x.is_embedded_data),'users':int(x.users),'use_fake_user':bool(x.use_fake_user),'use_extra_user':bool(x.use_extra_user),'custom':custom(x,shared)}
  references[key]=[{'id_key':qualified_id_key(y,owners),'identity':identity(y)} for y in sorted(reverse.get(x,set()),key=lambda y:qualified_id_key(y,owners))]
 helper=None
 objects={};geometry={};materials={};lights={};cameras={};layers={}
 helper_derived={}
 need(len(bpy.data.objects)<=LIMITS['objects'],'Object budget exceeded')
 for o in bpy.data.objects:
  need(o.type in {'ARMATURE','MESH','EMPTY','CAMERA','LIGHT'},'Unsupported object type')
  if o.name not in rig_context['bindings']:
   need(o.parent is None and not o.constraints and not o.modifiers and o.instance_type=='NONE','Parent/constraint/modifier/instance unsupported')
  need(not o.rigid_body and not o.rigid_body_constraint,'Object rigidbody unsupported')
  fields=('location','rotation_euler','rotation_quaternion','rotation_axis_angle','scale','delta_location','delta_rotation_euler','delta_rotation_quaternion','delta_scale')
  derived={'location','matrix_basis','matrix_world','matrix_local'} if o==helper else set()
  if o==helper:helper_derived={n:plain(getattr(o,n)) for n in sorted(derived)}
  objects[o.name]={'type':o.type,'data':identity(o.data),'properties':scalars(o,derived),'transform':{n:plain(getattr(o,n)) for n in fields if n not in derived},'custom':custom(o,shared),'materials':[identity(s.material) for s in o.material_slots],'vertex_groups':[{'name':g.name,'index':g.index,'lock_weight':g.lock_weight} for g in o.vertex_groups]}
  if o.name in rig_context['bindings']:objects[o.name]['rig_context_ref']=o.name
  if o!=helper:objects[o.name]['matrix_basis']=plain(o.matrix_basis)
  # Only helper's allowed Action binding lives in the dedicated section.
  if o!=helper:objects[o.name]['binding']=binding(o)
 for mesh in bpy.data.meshes:
  need(mesh.shape_keys is None and mesh.animation_data is None,'Animated/shape-key mesh unsupported')
  need(len(mesh.vertices)<=LIMITS['vertices'] and len(mesh.polygons)<=LIMITS['polygons'],'Geometry budget exceeded')
  need(not mesh.color_attributes,'Color attributes require a further adapter')
  attributes=mesh_attributes(mesh);uv_layout=uv_layers_record(mesh,attributes)
  geometry[mesh.name]={'attributes':attributes,'uv_layers':uv_layout,'properties':scalars(mesh),'custom':custom(mesh,shared),'vertices':[{'co':plain(v.co),'properties':scalars(v),'groups':[{'group':g.group,'weight':g.weight} for g in v.groups]} for v in mesh.vertices],'edges':[{'vertices':plain(e.vertices),'properties':scalars(e)} for e in mesh.edges],'polygons':[{'vertices':plain(p.vertices),'properties':scalars(p)} for p in mesh.polygons],'loops':[{'vertex_index':l.vertex_index,'edge_index':l.edge_index} for l in mesh.loops],'materials':[identity(m) for m in mesh.materials]}
 for m in bpy.data.materials:
  need(m.animation_data is None,'Animated material unsupported')
  materials[m.name]={'properties':scalars(m),'custom':custom(m,shared),'tree':node_tree(m.node_tree,shared)}
 for l in bpy.data.lights:
  need(l.animation_data is None,'Animated lights unsupported')
  lights[l.name]={'type':l.type,'properties':scalars(l),'custom':custom(l,shared),'tree':node_tree(l.node_tree,shared)}
 for c in bpy.data.cameras:
  need(c.animation_data is None and not c.background_images,'Animated camera data/background images unsupported')
  cameras[c.name]={'properties':scalars(c,{'angle','angle_x','angle_y'}),'custom':custom(c,shared),'dof':{'properties':scalars(c.dof),'focus_object':identity(c.dof.focus_object)}}
 for layer in scene.view_layers:
  def lc(c):return {'name':c.name,'collection':identity(c.collection),'properties':scalars(c),'children':[lc(x) for x in c.children]}
  layers[layer.name]={'properties':scalars(layer),'collections':lc(layer.layer_collection),'objects':{o.name:{'hide':o.hide_get(view_layer=layer),'selected':o.select_get(view_layer=layer)} for o in layer.objects},'active':identity(layer.objects.active)}
 worlds={w.name:{'properties':scalars(w),'custom':custom(w,shared),'tree':node_tree(w.node_tree,shared)} for w in bpy.data.worlds}
 rows=[]
 if hasattr(scene,'camera_live_shots'):
  rows=[{'name':r.name,'camera':identity(r.camera),'first':r.first,'last':r.last,'custom':custom(r,shared)} for r in scene.camera_live_shots]
 collections={c.name:{'properties':scalars(c),'custom':custom(c,shared),'objects':sorted(o.name for o in c.objects),'children':sorted(x.name for x in c.children)} for c in bpy.data.collections}
 snapshot={'source_sha':source_sha,'ids':ids,'objects':objects,'geometry':geometry,'materials':materials,'lights':lights,'cameras':cameras,'layers':layers,'actions':{a.name:action_record(a,shared) for a in bpy.data.actions},'tables':{'source':getattr(scene,'camera_live_source',None),'rows':rows,'markers':[{'name':m.name,'frame':m.frame,'camera':identity(m.camera)} for m in scene.timeline_markers]},'scene':{'name':scene.name,'sequence_editor':sequence,'properties':scalars(scene),'camera':identity(scene.camera),'custom':custom(scene,shared),'render':scalars(scene.render),'units':scalars(scene.unit_settings),'view_settings':scalars(scene.view_settings),'display_settings':scalars(scene.display_settings),'world':identity(scene.world),'worlds':worlds,'collections':collections}}
 if rig_context['rigs']:snapshot['rig_context']=rig_context
 # Ensure serializability and finite values before claiming a captured snapshot.
 need(len(json.dumps(snapshot,sort_keys=True,allow_nan=False,separators=(',',':')).encode())<=24*1024*1024,'Strict snapshot byte budget exceeded')
 snapshot.pop('source_sha');snapshot['references']=references
 need(bool(rig_context['rigs']),'Strict Static context requires rigs')
 return snapshot



def capture_rig_context(bpy,shared,helper_name):
 custom_record=lambda x:custom(x,shared)
 def graph(x,allowed):
  for p in x.bl_rna.properties:
   if p.identifier=='rna_type' or p.type not in {'POINTER','COLLECTION'}:continue
   v=getattr(x,p.identifier)
   if p.identifier in allowed:continue
   need(v is None if p.type=='POINTER' else len(v)==0,'Unprotected rig graph edge: '+x.bl_rna.identifier+'.'+p.identifier)
 def color(c):
  graph(c,{'custom'});graph(c.custom,set());return {'properties':scalars(c),'custom_palette':scalars(c.custom)}
 rigs={};bindings={}
 rig_objects=[o for o in bpy.data.objects if o.type=='ARMATURE']
 need({int(o.data.as_pointer())for o in rig_objects}=={int(a.as_pointer())for a in bpy.data.armatures},'Orphan armature data unsupported')
 need(all(o.data.users==1 for o in rig_objects),'Shared armature data unsupported')
 roots=[o.parent for o in rig_objects]
 need(all(x is not None for x in roots) and len({int(x.as_pointer())for x in roots})==len(roots),'Each rig requires an exclusive root')
 need(all(x.name!=helper_name for x in roots),'Focus helper cannot be a rig root')
 for o in bpy.data.objects:
  if o.parent or o.modifiers or o.type=='ARMATURE':
   need(o.type in {'MESH','ARMATURE'},'Only rig/mesh parent dependency supported')
   need(o.parent_type=='OBJECT' and not o.parent_bone,'Bone/vertex parenting unsupported')
   need(not o.constraints and o.instance_type=='NONE','Rig object constraints/instances unsupported')
   if o.type=='ARMATURE':
    need(o.parent is not None and o.parent.type=='EMPTY' and o.parent.parent is None and not o.parent.constraints and not o.parent.modifiers,'Rig requires independent plain EMPTY root')
    need(not o.modifiers,'Rig modifiers unsupported')
   else:
    need(o.parent is not None and o.parent.type=='ARMATURE','Bound mesh requires armature parent')
    need(len(o.modifiers)==1,'One armature modifier only');m=o.modifiers[0]
    need(m.type=='ARMATURE' and m.object==o.parent and m.use_vertex_groups and not m.use_bone_envelopes,'Plain vertex-group armature binding required')
    graph(m,{'object'})
   bindings[o.name]={'parent':identity(o.parent),'parent_type':o.parent_type,'parent_bone':o.parent_bone,'matrix_parent_inverse':plain(o.matrix_parent_inverse),'modifiers':[{'type':m.type,'name':m.name,'properties':scalars(m),'custom':custom_record(m),'object':identity(m.object)}for m in o.modifiers]}
  else:need(not o.constraints,'Object constraints unsupported')
 for o in bpy.data.objects:
  if o.type!='ARMATURE':continue
  a=o.data;need(not a.library and not a.override_library and a.animation_data is None,'Local unanimated armature data required')
  need(0<len(a.bones)<=64 and not a.is_editmode and not a.collections_all,'Bounded bones, object mode, no bone collections required')
  graph(a,{'original','library','library_weak_reference','asset_data','override_library','preview','animation_data','bones'})
  need(a.asset_data is None,'Armature asset metadata unsupported')
  graph(o.pose,{'bones','animation_visualization'});need(o.pose.ik_param is None,'Pose IK unsupported')
  vis=o.pose.animation_visualization;graph(vis,{'motion_path'});graph(vis.motion_path,set())
  bones={};poses={}
  for b in a.bones:
   need(b.bbone_segments==1,'Bendy bones unsupported');graph(b,{'parent','children','color'})
   bones[b.name]={'properties':scalars(b),'custom':custom_record(b),'parent':b.parent.name if b.parent else None,'children':[x.name for x in b.children],'color':color(b.color)}
  for p in o.pose.bones:
   graph(p,{'bone','parent','child','color','constraints'})
   cs=[]
   for c in p.constraints:
    need(c.type=='LIMIT_ROTATION' and c.owner_space=='LOCAL' and c.space_object is None,'Only self-contained LOCAL rotation limit supported');graph(c,set())
    cs.append({'type':c.type,'name':c.name,'properties':scalars(c),'custom':custom_record(c)})
   poses[p.name]={'properties':scalars(p),'custom':custom_record(p),'bone':p.bone.name,'parent':p.parent.name if p.parent else None,'child':p.child.name if p.child else None,'color':color(p.color),'constraints':cs}
  rigs[o.name]={'data':identity(a),'properties':scalars(a),'custom':custom_record(a),'weak_reference':scalars(a.library_weak_reference)if a.library_weak_reference else None,'bones':bones,'pose':{'properties':scalars(o.pose),'custom':custom_record(o.pose),'visualization':{'properties':scalars(vis),'motion_path':scalars(vis.motion_path)},'bones':poses}}
 need(all(o.type in {'MESH','EMPTY','ARMATURE','CAMERA','LIGHT'}for o in bpy.data.objects),'Unknown object type')
 if helper_name is not None:
  helper=bpy.data.objects.get(helper_name);need(helper is not None and helper.parent is None and not helper.constraints and not helper.modifiers,'Helper must stay flat')
 return {'schema':'bounded-independent-rig-context-v1','rigs':rigs,'bindings':bindings}
