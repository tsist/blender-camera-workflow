import base64,bpy,json,pathlib,hashlib,math
P=pathlib.Path
def need(x,m):
 if not x:raise ValueError(m)
def d(x):return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
need(bpy.app.background and bpy.app.version==(5,3,0) and bpy.app.build_hash==b'02f0899d78e3','wrong build')
q=json.loads(P('/query.json').read_text());m=q['mode'];need(m in ('edit','verify'),'unsupported mode')
import runpy
schema=runpy.run_path('/legacy_schema.py');schema['register_for_read'](bpy)
need(bpy.ops.wm.open_mainfile(filepath='/input.blend',load_ui=False,use_scripts=False)=={'FINISHED'},'load failed')
for _loaded_scene in bpy.data.scenes:schema['reject_live_rows'](_loaded_scene)
s=bpy.context.scene;t=s.objects.get(q['camera']);need(s.name==q['scene'] and t and t==s.camera and t.type=='CAMERA' and t.data.type in ('PERSP','ORTHO'),'must name an eligible active camera')
need(not('lens' in q and t.data.type!='PERSP'),'lens requires PERSP')
need(not('ortho_scale' in q and t.data.type!='ORTHO'),'ortho_scale requires ORTHO')
need(not any(getattr(bpy.data,k,[]) for k in ('libraries','actions','movieclips','sounds','cache_files','volumes','texts')),'linked, animated, scripted or external scene')
need(len(bpy.data.scenes)==1 and not any(o.animation_data or o.constraints or o.modifiers for o in s.objects),'only unanimated, unconstrained, modifier-free scenes')
need(not t.parent and t.data.users==1 and not t.data.animation_data,'driven, parented or shared camera')
need(all(im.source in ('GENERATED','VIEWER') or (im.source=='FILE' and im.packed_file) for im in bpy.data.images),'unpacked image')
if q.get('authorized_workcopy'):
 # Restricted enrollment is distinct from the two individually qualified frozen files.
 valid_ids=set('cameras scenes objects materials meshes lights screens window_managers images worlds collections palettes linestyles workspaces all_ids'.split())
 for prop in bpy.data.bl_rna.properties:
  if prop.type=='COLLECTION' and prop.identifier not in valid_ids:need(not len(getattr(bpy.data,prop.identifier)),'unsupported datablock: '+prop.identifier)
 need(len(s.objects)<=512 and set(s.objects)==set(bpy.data.objects) and all(o.type in ('MESH','CAMERA','LIGHT','EMPTY') and not o.instance_collection and not o.particle_systems and not o.rigid_body and not o.rigid_body_constraint for o in s.objects),'unsupported object, instance or physics')
 need(len(bpy.data.meshes)<=512 and sum(len(me.vertices) for me in bpy.data.meshes)<=300000 and sum(len(me.loops) for me in bpy.data.meshes)<=1000000,'mesh budget')
 need((not s.sequence_editor or not len(s.sequence_editor.strips)) and not s.rigidbody_world and not getattr(s,'compositing_node_group',None),'sequence, physics or compositor refused')
 for item in bpy.data.all_ids:
  need(not getattr(item,'animation_data',None) and not item.library and not getattr(item,'override_library',None),'driven, linked or overridden datablock')
  tree=getattr(item,'node_tree',None)
  if tree:
   need(not tree.animation_data and len(tree.nodes)<=128 and all(n.bl_idname in {'NodeFrame','NodeReroute','ShaderNodeOutputMaterial','ShaderNodeBsdfPrincipled','ShaderNodeBsdfDiffuse','ShaderNodeOutputWorld','ShaderNodeBackground','ShaderNodeOutputLight','ShaderNodeEmission','ShaderNodeTexImage','ShaderNodeTexCoord','ShaderNodeUVMap','ShaderNodeMapping','ShaderNodeNormalMap','ShaderNodeBump','ShaderNodeValue','ShaderNodeRGB'} for n in tree.nodes),'shader node outside static allowlist')
 for im in bpy.data.images:
  need(im.source in ('VIEWER','GENERATED') or (im.source=='FILE' and im.packed_file and len(im.packed_files)==1),'external or non-static image')
 for path in bpy.utils.blend_paths(absolute=False,packed=False,local=False):
  # Host-installed essential tool assets can be stored in workspace UI preferences.
  # They are not project data. Only the exact pinned runtime brush asset is accepted.
  need(path==q.get('host_brush') or path==q.get('relative_runtime_brush') or path=='/blender/5.3/datafiles/assets/brushes/essentials_brushes-gp_draw.blend','external data path refused: '+str(path)[:160])
pose='rotation' in q
focus='use_dof' in q
if pose or focus:
 need(len(bpy.data.cameras)==1,'pose/focus slice requires one camera')
if pose:
 need(t.rotation_mode=='XYZ' and not any(abs(v)>1e-8 for v in t.delta_rotation_euler) and all(abs(x-y)<1e-8 for x,y in zip(t.delta_rotation_quaternion,(1,0,0,0))),'use an XYZ camera without delta rotation')
if focus:
 need(t.data.type=='PERSP' and not t.data.dof.focus_subtarget,'focus requires perspective camera without bone subtarget')
 target_name=q.get('focus_object','')
 if target_name:
  subject=s.objects.get(target_name)
  need(subject and subject.type in ('MESH','EMPTY') and subject!=t and not subject.library and not subject.animation_data and not subject.constraints and not subject.parent and not subject.instance_collection,'focus object must be a named unparented local static mesh or empty')
def focus_item(c):
 f=c.dof
 return dict(use_dof=f.use_dof,focus_distance=f.focus_distance,fstop=f.aperture_fstop,focus_object=f.focus_object.name if f.focus_object else '',focus_subtarget=f.focus_subtarget,aperture_blades=f.aperture_blades,aperture_rotation=f.aperture_rotation,aperture_ratio=f.aperture_ratio)
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
def state():
 obj={}
 for o in s.objects:
  ob=[o.type,o.parent.name if o.parent else None,o.data.name if o.data else None,sorted(c.name for c in o.users_collection),o.rotation_mode,None if pose and o==t else list(o.rotation_euler),list(o.delta_rotation_euler),list(o.delta_rotation_quaternion),list(o.delta_location),list(o.delta_scale),list(o.scale),bool(o.hide_render),bool(o.hide_viewport)]
  if o!=t:ob += [list(o.location),[list(row) for row in o.matrix_world]]
  obj[o.name]=ob
 meshes={g.name:d([[list(v.co) for v in g.vertices],[list(e.vertices) for e in g.edges],[[list(f.vertices),f.material_index] for f in g.polygons],[[u.name,[list(x.uv) for x in u.data]] for u in g.uv_layers],[m.name if m else None for m in g.materials]]) for g in bpy.data.meshes}
 imgs={i.name:[i.source,list(i.size),[hashlib.sha256(z.packed_file.data).hexdigest() for z in i.packed_files]] for i in bpy.data.images}
 cams={c.name:[c.type,c.sensor_width,c.sensor_height,c.shift_x,c.shift_y,c.clip_start,c.clip_end,{k:v for k,v in focus_item(c).items() if c!=t.data or k not in q},c.lens if c!=t.data or t.data.type!='PERSP' else None,c.ortho_scale if c!=t.data or t.data.type!='ORTHO' else None] for c in bpy.data.cameras}
 w=dict(objects=obj,meshes=meshes,images=imgs,optics=cams,materials=material_graphs(),lights={l.name:[l.type,l.energy,list(l.color)] for l in bpy.data.lights},scene=[s.name,s.camera.name,s.frame_start,s.frame_end,s.frame_current,s.render.engine,s.render.resolution_x,s.render.resolution_y,s.view_settings.view_transform])
 return dict(protected=d(w),mesh_count=len(meshes),object_count=len(obj),location=list(t.location),lens=t.data.lens,ortho_scale=t.data.ortho_scale,projection=t.data.type,rotation=list(t.rotation_euler),**focus_item(t.data))
bpy.context.preferences.filepaths.file_preview_type='NONE'  # worker only; never save preferences or render a file preview
before=state()
if m=='edit':
 if 'ortho_scale' in q:t.data.ortho_scale=q['ortho_scale']
 if 'location' in q:t.location=q['location']
 if 'lens' in q:t.data.lens=q['lens']
 if pose:t.rotation_euler=q['rotation']
 if focus:
  t.data.dof.use_dof=q['use_dof']
  if 'fstop' in q:t.data.dof.aperture_fstop=q['fstop']
  if 'focus_object' in q:t.data.dof.focus_object=s.objects[q['focus_object']] if q['focus_object'] else None
  if 'focus_distance' in q:t.data.dof.focus_distance=q['focus_distance']
 bpy.context.view_layer.update()
 after=state();need(after['protected']==before['protected'],'non-target witness changed')
 import runpy;runpy.run_path('/portable_brush.py')['normalize'](q)
 need(bpy.ops.wm.save_as_mainfile(filepath='/tmp/candidate.blend',copy=True,relative_remap=False)=={'FINISHED'},'save failed')
 blob=P('/tmp/candidate.blend').read_bytes();need(len(blob)<=32<<20,'oversize candidate')
 print('CAMERA-COPY:'+json.dumps(dict(before=before,after=after,blob=base64.b64encode(blob).decode()),separators=(',',':')))
else:print('CAMERA-COPY:'+json.dumps(dict(cold=before),separators=(',',':')))
