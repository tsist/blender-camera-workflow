"""Read-only mesh fingerprints retained for Camera Workflow."""
import hashlib
import json

def sha(value):return hashlib.sha256(json.dumps(value,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def topology(mesh):return sha({'vertices':len(mesh.vertices),'edges':[list(e.vertices) for e in mesh.edges],'faces':[list(f.vertices) for f in mesh.polygons]})
