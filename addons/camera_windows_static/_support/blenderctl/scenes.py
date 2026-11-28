"""Read-only scene witnesses retained for Camera Workflow."""
import bpy
from inspection import all_ids, record, key, identity, value

def update():
    for scene in bpy.data.scenes:
        for layer in scene.view_layers:layer.update()

def state(record_fn=None):
    update();blocks=sorted(((record_fn or record)(i) for i in all_ids()),key=lambda r:key({k:r[k] for k in ('type','name','library')}))
    scenes=[]
    for scene in sorted(bpy.data.scenes,key=lambda s:s.name):
        layers=[]
        for layer in scene.view_layers:
            flags=[]
            def walk(node,path):
                for child in node.children:
                    path2=path+[child.name];flags.append({'path':path2,'exclude':child.exclude,'holdout':child.holdout,'indirect_only':child.indirect_only});walk(child,path2)
            walk(layer.layer_collection,[])
            layers.append({'name':layer.name,'use':layer.use,'active':layer.objects.active.name if layer.objects.active else None,'selected_objects':sorted(o.name for o in layer.objects if o.select_get(view_layer=layer)),'objects':sorted(o.name for o in layer.objects),'collections':flags})
        scenes.append({'name':scene.name,'root_collections':sorted(c.name for c in scene.collection.children),'root_objects':sorted(o.name for o in scene.collection.objects),'world':identity(scene.world) if scene.world else None,'camera':scene.camera.name if scene.camera else None,'frame':scene.frame_current,'timeline':[scene.frame_start,scene.frame_end,scene.render.fps,scene.render.fps_base],'units':{p:getattr(scene.unit_settings,p) for p in ('system','length_unit','scale_length')},'view_layers':layers})
    collections=[{'name':c.name,'library':c.library.filepath if c.library else None,'children':sorted(n.name for n in c.children),'objects':sorted(o.name for o in c.objects),'instance_offset':list(c.instance_offset)} for c in sorted(bpy.data.collections,key=lambda c:c.name)]
    layer=bpy.context.view_layer;layer.update();graph=bpy.context.evaluated_depsgraph_get()
    objects=[{'name':o.name,'library':o.library.filepath if o.library else None,'matrix_world':value(o.evaluated_get(graph).matrix_world if o.name in layer.objects else o.matrix_world),'evaluated_in_active_view_layer':o.name in layer.objects,'parent_type':o.parent_type,'parent_bone':o.parent_bone,'instance_type':o.instance_type,'instance_collection':identity(o.instance_collection) if o.instance_collection else None,'hide_viewport':o.hide_viewport,'collections':sorted(c.name for c in o.users_collection)} for o in sorted(bpy.data.objects,key=lambda o:o.name)]
    return {'scene_report_version':'1.0','scenes':scenes,'collections':collections,'objects':objects,'datablocks':blocks,'evaluation_context':{'scene':bpy.context.scene.name,'view_layer':layer.name,'frame':bpy.context.scene.frame_current,'mode':bpy.context.mode},'coverage':'declared_scene_fields_and_existing_content_snapshot; not_all_plugin_or_render_state'}
