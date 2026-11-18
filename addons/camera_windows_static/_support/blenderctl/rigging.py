"""Read-only rig and skin witnesses retained for Camera Workflow."""
import math
import bpy
import scenes
import modeling
from inspection import identity, value

def weights_report(o,rig):
    deform={b.name for b in rig.data.bones if b.use_deform};groups={g.index:g.name for g in o.vertex_groups};sums=[];maximum=0;invalid=0
    for v in o.data.vertices:
        ws=[g.weight for g in v.groups if groups.get(g.group) in deform];sums.append(sum(ws));maximum=max(maximum,len([w for w in ws if w>0]));invalid+=sum(not math.isfinite(w) or w<0 or w>1 for w in ws)
    return {'vertices':len(sums),'unweighted':sum(s<1e-8 for s in sums),'not_normalized':sum(abs(s-1)>1e-4 for s in sums),'sum_min':min(sums,default=0),'sum_max':max(sums,default=0),'max_influences':maximum,'invalid_weights':invalid}

def rest_signature(rig,bones):return modeling.sha([{'name':n,'parent':rig.data.bones[n].parent.name if rig.data.bones[n].parent else None,'matrix':value(rig.data.bones[n].matrix_local),'inherit_scale':rig.data.bones[n].inherit_scale,'inherit_rotation':rig.data.bones[n].use_inherit_rotation,'local_location':rig.data.bones[n].use_local_location,'connected':rig.data.bones[n].use_connect} for n in bones])

def state():
    return {'rig_report_version':'1.0','scene':scenes.state(),
        'rigs':[{'object':o.name,'data':identity(o.data),'rest_sha256':rest_signature(o,[b.name for b in o.data.bones]),'bones':[{'name':b.name,'parent':b.parent.name if b.parent else None,'head':value(b.head_local),'tail':value(b.tail_local),'matrix_local':value(b.matrix_local),'connected':b.use_connect,'deform':b.use_deform,'inherit_scale':b.inherit_scale,'inherit_rotation':b.use_inherit_rotation,'pose_matrix':value(o.pose.bones[b.name].matrix),'basis':value(o.pose.bones[b.name].matrix_basis)} for b in o.data.bones]} for o in sorted(bpy.data.objects,key=lambda o:o.name) if o.type=='ARMATURE'],
        'skins':[{'object':o.name,'topology_sha256':modeling.topology(o.data),'groups':[{'name':g.name,'index':g.index,'locked':g.lock_weight} for g in o.vertex_groups],'weights_sha256':modeling.sha([[(g.group,g.weight) for g in v.groups] for v in o.data.vertices]),'bindings':[{'modifier':m.name,'rig':m.object.name,'weights':weights_report(o,m.object)} for m in o.modifiers if m.type=='ARMATURE' and m.object]} for o in sorted(bpy.data.objects,key=lambda o:o.name) if o.type=='MESH'],
        'coverage':'local_rest_pose_weights_layered_actions_slots_NLA_and_non_scripted_drivers; sampled_deformation_separate'}
