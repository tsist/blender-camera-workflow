"""Read-only material-binding witness retained for Camera Workflow."""
import bpy
import scenes

def snapshot():
    return {'scene': scenes.state(), 'bindings': [
        {'object': o.name, 'slots': [{'material': s.material.name if s.material else None,
                                     'link': s.link} for s in o.material_slots]}
        for o in sorted(bpy.data.objects, key=lambda o: o.name) if o.type == 'MESH']}
