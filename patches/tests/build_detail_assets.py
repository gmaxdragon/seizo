"""Build-only camera LOD export. Runtime needs neither Node nor these mesh tools."""
from pathlib import Path
import numpy as np,trimesh,fast_simplification,json,gzip,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from core.camera_observation import png
root=ROOT/'web/assets'
s=json.loads((root/'camera_parts.json').read_text());m=json.loads((root/'meshes.json').read_text());m.update(s['extra_meshes']);out={}
for key in sorted({p['geometry'] for p in s['parts']}):
 p=np.asarray(m[key]['p'],float).reshape(-1,3)
 mesh=trimesh.Trimesh(vertices=p,faces=np.arange(len(p)).reshape(-1,3),process=True)
 target=300
 if any(w in key.lower() for w in ('forearm','upper','finger','base')):target=1400
 if 'motor' in key.lower():target=600
 if 'washer' in key.lower():target=180
 if len(mesh.faces)>target:
  v,f=fast_simplification.simplify(mesh.vertices,mesh.faces,target_count=target,agg=5)
  mesh=trimesh.Trimesh(v,f,process=True)
 points=mesh.vertices[mesh.faces].reshape(-1,3);normals=np.repeat(mesh.face_normals,3,axis=0)
 out[key]={'p':np.round(points,5).ravel().tolist(),'n':np.round(normals,5).ravel().tolist()}
(root/'camera_lod.json.gz').write_bytes(gzip.compress(json.dumps(out,separators=(',',':')).encode(),mtime=0))
s.pop('extra_meshes');s['build_only_lod']='Derived from shipped detailed arm, hollow surfaces retained; no change to collision geometry.'
(root/'camera_parts.json').write_text(json.dumps(s,separators=(',',':')))
# Procedural materials, not extracted room photographs or a measured reconstruction.
r=np.random.default_rng(209);h,w=256,512;y,x=np.mgrid[:h,:w]
gr=(np.sin(y*.56+np.sin(x*.03)*2)*2+r.normal(0,2,(h,w))+(x//64%3-1)*7)
base=np.array([120,88,57]);wood=base+gr[:,:,None]*np.array([1.,.85,.65]);wood[x%64<2]*=.5
(root/'room_wood.png').write_bytes(png(np.clip(wood,0,255).astype(np.uint8)))
h=w=256;y,x=np.mgrid[:h,:w];weave=r.normal(0,3,(h,w))+((x%4<2)^(y%4<2))*3
fabric=np.array([14,28,43])+weave[:,:,None]
(root/'room_fabric.png').write_bytes(png(np.clip(fabric,0,255).astype(np.uint8)))
print(json.dumps({'camera_parts':len(s['parts']),'instanced_triangles':sum(len(out[p['geometry']]['p'])//9 for p in s['parts']),
 'compressed_asset_bytes':(root/'camera_lod.json.gz').stat().st_size,'runtime_build_dependencies':False}))
