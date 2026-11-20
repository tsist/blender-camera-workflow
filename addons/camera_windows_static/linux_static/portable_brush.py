"""Canonicalize only a bundled, pinned Material library-weak-reference for copy portability."""
import bpy,hashlib,pathlib
def require(v,s):
 if not v:raise ValueError(s)
def normalize(q):
 relative='5.3/datafiles/assets/brushes/essentials_brushes-gp_draw.blend'
 canonical=q['host_brush']
 require(canonical.startswith('/') and canonical.endswith('/'+relative),'invalid runtime brush path')
 pin=pathlib.Path('/blender')/relative
 require(hashlib.sha256(pin.read_bytes()).hexdigest()=='0596dce9286b824c31af67197b96e83a0c4a42ce2dbb36f40dfc8ecab3fe9f06','stock brush fingerprint differs')
 choices={canonical,q['relative_runtime_brush'],str(pin)}
 original=sorted(bpy.utils.blend_paths(absolute=False,packed=False,local=False))
 refs={i.as_pointer():i.library_weak_reference.filepath for i in bpy.data.materials if i.library_weak_reference and i.library_weak_reference.filepath in choices}
 if not refs:return
 def fail_if_strong(i,path,meta):
  if path in choices:raise ValueError('brush reference also used as a project dependency')
  return None
 # Exceptions raised from Blender visitor callbacks are not guaranteed to propagate.
 strong=[];bpy.data.file_path_foreach(lambda i,path,meta:strong.append(path) if path in choices else None,flags={'SKIP_PACKED','SKIP_WEAK_REFERENCES'})
 require(not strong,'stock brush also used as non-weak dependency')
 changed=[]
 def visit(i,path,meta):
  if path not in choices:return None
  if refs.get(i.as_pointer())!=path or meta.is_readonly or meta.is_cache:changed.append(None);return None
  changed.append(i.as_pointer());return canonical
 bpy.data.file_path_foreach(visit,flags=set())
 require(None not in changed and sorted(changed)==sorted(refs),'unexpected weak path owner')
 actual=sorted(bpy.utils.blend_paths(absolute=False,packed=False,local=False))
 require(actual==sorted(canonical if x in choices else x for x in original),'unrelated external path changed')
 require(all(i.library_weak_reference.filepath==canonical for i in bpy.data.materials if i.as_pointer() in refs),'weak reference normalization failed')
