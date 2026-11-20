"""Standalone, sealed process for narrowly-scoped advanced camera transactions."""
import base64,bpy,hashlib,importlib.util,json,math,pathlib
P=pathlib.Path
def need(x,m):
 if not x:raise ValueError(m)
def digest(x):
 return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def mat(x):return [list(row) for row in x]
def named(x):return x.name if x else None
def curve(fc):
 return [fc.data_path,fc.array_index,fc.extrapolation,fc.mute,fc.lock,[[*k.co,*k.handle_left,*k.handle_right,k.interpolation,k.easing,k.handle_left_type,k.handle_right_type,k.type,k.amplitude,k.back,k.period] for k in fc.keyframe_points]]
need(bpy.app.background and bpy.app.version==(5,3,0) and bpy.app.build_hash==b'02f0899d78e3','wrong runtime')
q=json.loads(P('/query.json').read_text());m=q['mode'];sq=q['sequence'];kind=sq['kind']
need(kind in ('cut','motion','motion_ease','bone','focus_timing','legacy_cut') and m in ('preflight','edit','verify'),'invalid worker dispatch')
spec=importlib.util.spec_from_file_location('sealed_domain','/adv_'+kind+'.py')
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);mod.validate(sq)
import runpy
schema=runpy.run_path('/legacy_schema.py');schema['register_for_read'](bpy)
if kind=='legacy_cut':mod.prepare(bpy)
need(bpy.ops.wm.open_mainfile(filepath='/input.blend',load_ui=False,use_scripts=False)=={'FINISHED'},'load failed')
if kind!='legacy_cut':
 for _loaded_scene in bpy.data.scenes:schema['reject_live_rows'](_loaded_scene)
else:need(len(bpy.data.scenes)==1,'legacy edit requires one explicit scene')
bpy.context.preferences.filepaths.file_preview_type='NONE'
s=bpy.context.scene;t=s.objects.get(q['camera'])
need(len(bpy.data.scenes)==1 and s.name==q['scene'] and t and t.type=='CAMERA' and t==s.camera and not t.parent and t.data.users==1 and not t.data.animation_data,'requires saved active local unparented camera')
need(s.frame_subframe==0.0 and (not s.sequence_editor or not len(s.sequence_editor.strips)) and not s.rigidbody_world and not getattr(s,'compositing_node_group',None),'fractional frame, VSE, physics or compositor refused')
valid=set('cameras scenes objects materials meshes lights screens window_managers images worlds collections palettes linestyles workspaces all_ids'.split())
if kind=='bone':valid.add('armatures')
valid.add('actions')
for prop in bpy.data.bl_rna.properties:
 if prop.type=='COLLECTION' and prop.identifier not in valid:need(not len(getattr(bpy.data,prop.identifier)),'unsupported datablock '+prop.identifier)
need(len(s.objects)<=512 and set(s.objects)==set(bpy.data.objects),'object budget or unrelated objects')
need(len(bpy.data.meshes)<=512 and sum(len(me.vertices) for me in bpy.data.meshes)<=300000 and sum(len(me.loops) for me in bpy.data.meshes)<=1000000,'mesh budget')
allowed_types={'MESH','CAMERA','LIGHT','EMPTY'}|({'ARMATURE'} if kind=='bone' else set())
for o in s.objects:
 need(o.type in allowed_types and not o.instance_collection and not o.constraints and not o.modifiers and not o.particle_systems and not o.rigid_body and not o.rigid_body_constraint,'unsupported rig/modifier/constraint')
 if o.type=='ARMATURE':
  need(not o.parent and not o.data.animation_data and len(o.data.bones)<=128 and all(not b.constraints and not b.custom_shape for b in o.pose.bones),'unsupported rig pose')
for im in bpy.data.images:need(im.source in ('VIEWER','GENERATED') or (im.source=='FILE' and im.packed_file and len(im.packed_files)==1),'external image refused')
for path in bpy.utils.blend_paths(absolute=False,packed=False,local=False):
 need(path in (q.get('host_brush'),q.get('relative_runtime_brush'),'/blender/5.3/datafiles/assets/brushes/essentials_brushes-gp_draw.blend'),'external data path refused')
for item in bpy.data.all_ids:
 need(not item.library and not getattr(item,'override_library',None),'linked datablock')
 ad=getattr(item,'animation_data',None)
 if ad:
  allow=(kind in ('cut','motion','motion_ease','legacy_cut') and item.type=='CAMERA' and (kind in ('cut','legacy_cut') or item==t)) or (kind=='bone' and item.type=='ARMATURE' and item.name==sq['focus_object']) or (kind=='focus_timing' and item.type=='EMPTY' and item.name==sq['helper']) if isinstance(item,bpy.types.Object) else False
  need(allow and ad.action and not ad.nla_tracks and not ad.drivers,'only opcode-scoped regular active actions are allowed')
 tree=getattr(item,'node_tree',None)
 if tree:need(not tree.animation_data and len(tree.nodes)<=128 and all(n.bl_idname in {'NodeFrame','NodeReroute','ShaderNodeOutputMaterial','ShaderNodeBsdfPrincipled','ShaderNodeBsdfDiffuse','ShaderNodeOutputWorld','ShaderNodeBackground','ShaderNodeOutputLight','ShaderNodeEmission','ShaderNodeTexImage','ShaderNodeTexCoord','ShaderNodeUVMap','ShaderNodeMapping','ShaderNodeNormalMap','ShaderNodeBump','ShaderNodeValue','ShaderNodeRGB'} for n in tree.nodes),'unsupported shader')
def actions():
 vals={}
 for a in bpy.data.actions:
  owners=[o for o in s.objects if o.animation_data and o.animation_data.action==a]
  need(len(owners)==1 and len(a.layers)==1 and len(a.slots)==1 and len(a.layers[0].strips)==1 and a.users==1,'action must have one camera owner, slot, layer and strip')
  st=a.layers[0].strips[0];need(st.type=='KEYFRAME' and len(st.channelbags)==1,'unsupported action strip')
  curves=st.channelbags[0].fcurves
  paths={'location','rotation_euler','scale'} if owners[0].type=='CAMERA' else {'location'} if owners[0].type=='EMPTY' and kind=='focus_timing' else {owners[0].pose.bones[sq['focus_subtarget']].path_from_id(k) for k in ('location','rotation_euler','rotation_quaternion','scale')}
  need(len(curves)<=12 and all(f.data_path in paths and not f.modifiers and not f.sampled_points and len(f.keyframe_points)<=1024 for f in curves),'unsupported action channel')
  vals[owners[0].name]=[a.name,a.slots[0].identifier,a.layers[0].name,sorted([curve(f) for f in curves],key=lambda z:(z[0],z[1]))]
 return vals
if hasattr(mod,'guard'):mod.guard(bpy,s,t,sq)
def material_graphs():
 result={}
 for mt in bpy.data.materials:
  tree=mt.node_tree
  topology=None
  if tree:
   need(not tree.library and tree.bl_idname=='ShaderNodeTree','local material shader tree required')
   nodes=[]
   for n in tree.nodes:
    uv=[n.uv_map,bool(n.from_instancer)] if n.bl_idname=='ShaderNodeUVMap' else None
    tex=[n.image.name if n.image else None,n.interpolation,n.projection,n.extension] if n.bl_idname=='ShaderNodeTexImage' else None
    nodes.append([n.name,n.bl_idname,uv,tex])
   links=sorted([[e.from_node.name,e.from_socket.identifier,e.to_node.name,e.to_socket.identifier,bool(e.is_muted)] for e in tree.links])
   topology=[sorted(nodes,key=lambda x:x[0]),links]
  result[mt.name]=[list(mt.diffuse_color),topology]
 return result
def frozen():
 act=actions()
 if kind in ('motion','motion_ease'):act.pop(t.name,None)
 elif kind=='focus_timing':act.pop(sq['helper'],None)
 elif kind=='cut' and sq.get('operation')=='retime':
  # Module's expected() owns complete channel records for the selected cameras.
  for n in sq.get('cameras',[]):act.pop(n,None)
 objs={}
 for o in s.objects:
  moving=(o==t and kind in ('motion','motion_ease'))
  objs[o.name]=[o.type,named(o.data),named(o.parent),sorted(c.name for c in o.users_collection),o.rotation_mode,list(o.scale),list(o.delta_scale),list(o.delta_location),list(o.delta_rotation_euler),list(o.delta_rotation_quaternion),([list(o.rotation_euler),list(o.rotation_axis_angle),list(o.rotation_quaternion)] if kind=='motion_ease' else None) if moving else [list(o.location),list(o.rotation_euler),list(o.rotation_quaternion),list(o.rotation_axis_angle),mat(o.matrix_world)],o.hide_render,o.hide_viewport]
 data={}
 for me in bpy.data.meshes:
  data[me.name]=digest([[list(v.co) for v in me.vertices],[list(e.vertices) for e in me.edges],[[list(f.vertices),f.material_index] for f in me.polygons],[[u.name,[list(v.uv) for v in u.data]] for u in me.uv_layers],[named(x) for x in me.materials]])
 cams={}
 for c in bpy.data.cameras:
  f=c.dof;ds=[f.use_dof,named(f.focus_object),f.focus_subtarget,f.aperture_fstop]
  cams[c.name]=[c.type,c.lens,c.ortho_scale,c.sensor_width,c.sensor_height,c.shift_x,c.shift_y,c.clip_start,c.clip_end,f.focus_distance,f.aperture_ratio,f.aperture_rotation,f.aperture_blades,None if kind=='bone' and c==t.data else ds]
 rigs={}
 for o in s.objects:
  if o.type=='ARMATURE':rigs[o.name]=[[b.name,named(b.parent),list(b.head_local),list(b.tail_local),mat(b.matrix_local),mat(o.pose.bones[b.name].matrix_basis)] for b in o.data.bones]
 marks=None if kind=='cut' else [[z.name,z.frame,named(z.camera)] for z in s.timeline_markers]
 lights={l.name:[l.type,l.energy,list(l.color)] for l in bpy.data.lights}
 mats=material_graphs()
 images={i.name:[i.source,list(i.size),[hashlib.sha256(z.packed_file.data).hexdigest() for z in i.packed_files]] for i in bpy.data.images}
 return digest([objs,data,cams,rigs,act,marks,lights,mats,images,[s.name,named(s.camera),s.frame_start,s.frame_end,s.frame_current,s.render.fps,s.render.fps_base,s.render.resolution_x,s.render.resolution_y]])
def observe():
 a=frozen();seq=mod.state(bpy,s,t,sq);need(a==frozen(),'module read changed state')
 return dict(protected=a,sequence=seq)
before=observe()
if m=='verify':out={'cold':before}
else:
 prediction=mod.expected(json.loads(json.dumps(before['sequence'],allow_nan=False)),sq)
 need(prediction!=before['sequence'],'no effective advanced edit')
 if m=='preflight':out={'cold':before,'prediction':prediction}
 else:
  mod.apply(bpy,s,t,sq);bpy.context.view_layer.update()
  after=observe();need(before['protected']==after['protected'],'protected scene witness changed')
  need(prediction==after['sequence'],'advanced edit differs from predicted state')
  import runpy;runpy.run_path('/portable_brush.py')['normalize'](q)
  need(bpy.ops.wm.save_as_mainfile(filepath='/tmp/candidate.blend',copy=True,compress=False,relative_remap=False)=={'FINISHED'},'save failed')
  blob=P('/tmp/candidate.blend').read_bytes();need(0<len(blob)<=32<<20,'candidate size budget')
  out={'before':before,'after':after,'blob':base64.b64encode(blob).decode()}
print('CAMERA-COPY:'+json.dumps(out,separators=(',',':'),allow_nan=False))
