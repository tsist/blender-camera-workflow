"""Isolated new-file-only static camera saved-copy adapter. No Windows transaction claims."""
import base64, math, argparse, ctypes as C, errno, fcntl, hashlib, json, os, pathlib, platform, re, stat, subprocess, sys
P=pathlib.Path
BASE=P(__file__).resolve().parent
KNOWN={'ea2573f1f202e9fdceb2fb12f8d5b2c0b7e860869207df42bf4259104d74b215','0e23483b9391a67bc4d0e017d862e9f802f62cc2422c9e7ce4a6192cfea1e3bc'}
SHA_B='baaa36cb5d7a35092388e6d123739b0829012c252b0705bc2debec292e4ebffb'
SHA_P='be767e5ad6f60784b8858f48e136fb98129e2169f23722b6e48a864525de7f90'
SHA_F='00503f3f35404cd4ef1e0935aaa7017ec512b9436b70f24d2abc90d25da3ed38'
ADVANCED_PINS={'adv_focus_timing.py': '3376f6c58fac0431f9a6a241504070e476ff29137a5151459919e7433817b07d', 'adv_motion_ease.py': 'b3680e1e268e5a65f88dc0f58369c493f1ec3c2d10fb83edcab0089d00c35cac', 'adv_legacy_cut.py': '76def39b136945334e736a2b1295abe1d2035c006ee5c064a7812c492c5efd4a', 'adv_bone.py': '782d04866f46c33aa635ecd656553206ba9027f57b523640fd412d716651c67f', 'adv_motion.py': 'fcb5114bdd675e3835d11e5bc1b1642b4f66584241dee04e143c2e3c59448191', 'adv_cut.py': '98608ff27a8224effd49e5b880a899497bb46ca7b0d38b92e8e47b2fac1aca48', 'advanced_worker.py': '0f8075847cb5b8660e01024db2621d06be1735ba1b73bd6346be6dd211a33a54'}
def need(x,m):
 if not x:raise ValueError(m)
def contents(p,cap):
 p=P(p).absolute(); need(p==p.resolve(),'symlink/traversal refused')
 with os.fdopen(os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK),'rb') as f:
  s=os.fstat(f.fileno());need(stat.S_ISREG(s.st_mode) and s.st_nlink==1 and 0<s.st_size<=cap,'unqualified file')
  data=f.read(cap+1);need(len(data)==s.st_size,'size changed');return data
def sha(b):return hashlib.sha256(b).hexdigest()
def fd(b):
 f=os.memfd_create('ro-snapshot',os.MFD_ALLOW_SEALING);os.write(f,b);need(os.lseek(f,0,2)==len(b),'short write');os.lseek(f,0,0)
 fcntl.fcntl(f,getattr(fcntl,'F_ADD_SEALS',1033),15);return f
def nonet():
 l=C.CDLL('libseccomp.so.2');l.seccomp_init.argtypes=[C.c_uint32];l.seccomp_init.restype=C.c_void_p
 c=l.seccomp_init(0x7fff0000);need(c,'seccomp_init')
 l.seccomp_rule_add.argtypes=[C.c_void_p,C.c_uint32,C.c_int,C.c_uint];l.seccomp_syscall_resolve_name.argtypes=[C.c_char_p]
 for n in ('socket','socketpair','connect','bind','listen','accept','accept4','io_uring_setup','ptrace','process_vm_writev'):
  num=l.seccomp_syscall_resolve_name(n.encode());need(num>=0 and l.seccomp_rule_add(c,0x00050000|errno.EPERM,num,0)==0,'seccomp rule')
 dest=os.memfd_create('no-net');l.seccomp_export_bpf.argtypes=[C.c_void_p,C.c_int];need(l.seccomp_export_bpf(c,dest)==0,'seccomp export');os.lseek(dest,0,0);return dest

def main():
 a=argparse.ArgumentParser(description=__doc__)
 for k in ('runtime','source','sha256','query','out'):a.add_argument('--'+k,required=True)
 a.add_argument('--authorize-owned-static-workcopy',action='store_true');a.add_argument('--check-only',action='store_true'); v=a.parse_args();need(platform.system()=='Linux' and platform.machine()=='x86_64','Linux x86_64 only')
 root=P(v.runtime).absolute();need(root==root.resolve(),'runtime symlink refused')
 for p,h in [('blender',SHA_B),('5.3/python/bin/python3.13',SHA_P)]:
  with (root/p).open('rb') as s:need(hashlib.file_digest(s,'sha256').hexdigest()==h,'runtime pin mismatch')
 src=P(v.source); b=contents(src,32<<20);need(sha(b)==v.sha256,'source hash mismatch')
 dynamic=v.sha256 not in KNOWN
 if dynamic:
  need(v.authorize_owned_static_workcopy,'not enrolled: explicit authorization for your own static work-copy required')
  st=src.lstat();parent_st=src.parent.stat()
  need(src.is_absolute() and src.suffix.lower()=='.blend' and st.st_uid==os.geteuid() and not st.st_mode&0o022 and parent_st.st_uid==os.geteuid() and not parent_st.st_mode&0o077,'private owner-only work-copy directory and owned source required')
  need(b.startswith(b'BLENDER') and len(b)<=16<<20,'use an uncompressed .blend work-copy of at most 16 MiB')
  source_identity=(st.st_dev,st.st_ino,st.st_ctime_ns,st.st_mtime_ns,st.st_size)
 def source_same():
  need(sha(contents(src,32<<20))==v.sha256,'source changed')
  if dynamic:
   ss=src.lstat();need((ss.st_dev,ss.st_ino,ss.st_ctime_ns,ss.st_mtime_ns,ss.st_size)==source_identity,'source identity changed')
 original=b
 def unique(pairs):
  o={}
  for k,vv in pairs:need(k not in o,'duplicate JSON property');o[k]=vv
  return o
 qbytes=contents(v.query,16<<10);request=json.loads(qbytes,object_pairs_hook=unique,parse_constant=lambda v:need(False,'non-finite number'))
 adv=isinstance(request,dict) and 'sequence' in request
 if adv:
  need(set(request)=={'scene','camera','sequence'} and v.authorize_owned_static_workcopy,'advanced work-copy requires explicit single-operation authorization')
  sq=request['sequence'];need(type(sq)==dict and sq.get('kind') in ('cut','bone','motion','motion_ease','focus_timing','legacy_cut'),'unsupported sequence request')

 need(type(request)==dict and {'scene','camera'}<set(request)<=set(('scene','camera','location','lens','ortho_scale','rotation','use_dof','focus_distance','fstop','focus_object','sequence')),'explicit camera edit required')
 need(all(type(request[k])==str and 0<len(request[k])<=128 for k in ('scene','camera')),'scene and camera required')
 if 'ortho_scale' in request:need(type(request['ortho_scale']) in (int,float) and 0.01<=request['ortho_scale']<=10000,'invalid orthographic scale')
 if 'lens' in request:need(type(request['lens']) in (int,float) and 1<=request['lens']<=1000,'invalid focal length')
 if 'location' in request:need(type(request['location'])==list and len(request['location'])==3 and all(type(n) in (int,float) and math.isfinite(n) and abs(n)<=10000 for n in request['location']),'invalid location')
 if 'rotation' in request:need(type(request['rotation'])==list and len(request['rotation'])==3 and all(type(n) in (int,float) and math.isfinite(n) and abs(n)<=2*math.pi+1e-5 for n in request['rotation']),'XYZ radians outside ±360 degrees')
 if set(request)&{'use_dof','focus_distance','fstop','focus_object'}:
  need(type(request.get('use_dof')) is bool,'explicit DOF toggle required')
  if request['use_dof']:
   need(type(request.get('fstop')) in (int,float) and 0.1<=request['fstop']<=128,'f-stop must be 0.1 to 128')
   name=request.get('focus_object');need(type(name) is str and len(name)<=128,'exact focus target or empty manual-focus name required')
   if name:need('focus_distance' not in request,'object and manual focus distance conflict')
   else:need(type(request.get('focus_distance')) in (int,float) and 0.01<=request['focus_distance']<=100000,'manual focus distance must be 0.01 to 100000')
  else:need(not (set(request)&{'fstop','focus_distance','focus_object'}),'disabling DOF must preserve focus setup')
 edit_keys=set(request)-{'camera','scene'}
 def match(one,two):
  if type(two) in (list,tuple):return type(one) in (list,tuple) and len(one)==len(two) and all(match(x,y) for x,y in zip(one,two))
  if type(two) in (int,float):return type(one) in (int,float) and math.isclose(one,two,rel_tol=1e-6,abs_tol=1e-6)
  return type(one)==type(two) and one==two
 w=contents(BASE/'worker.py',64<<10);need(sha(w)=='08da790686966cf13014fddcb26c56e2eab89714f943457d676efea5777e9316','worker pin mismatch')
 portable=contents(BASE/'portable_brush.py',32<<10);need(sha(portable)=='3119cc8af5047cfbbce95f7501d2b7610ed00b15349d76bad3a7fc782c5f007d','portable brush worker hash changed')
 legacy=contents(BASE/'legacy_schema.py',32<<10);need(sha(legacy)=='5b5692c4d5afc12e606a456bef4ba0479025f37d455754ab74ba953d5ab472c9','legacy schema fingerprint differs')
 extra=[(portable,'/portable_brush.py'),(legacy,'/legacy_schema.py')]
 if adv:
  required={'advanced_worker.py':ADVANCED_PINS['advanced_worker.py'],'adv_'+sq['kind']+'.py':ADVANCED_PINS['adv_'+sq['kind']+'.py']}
  for nm,hh in required.items():
   raw=contents(BASE/nm,96<<10);need(sha(raw)==hh,'advanced worker/module hash changed');extra.append((raw,'/'+nm))
 out=P(v.out).absolute();parent=out.parent;need(out.name not in ('.','..') and parent==parent.resolve(),'unsafe destination')
 dirfd=os.open(parent,os.O_DIRECTORY|os.O_NOFOLLOW);st=os.fstat(dirfd)
 need(st.st_uid==os.geteuid() and not st.st_mode&0o022,'unowned or writable output parent')
 need(not out.exists(),'new output directory required')
 nix=nonet()
 def invoke(b,mode):
  q=json.dumps(dict(**request,mode=mode,authorized_workcopy=dynamic,relative_runtime_brush='//'+os.path.relpath(root/'5.3/datafiles/assets/brushes/essentials_brushes-gp_draw.blend',src.parent),host_brush=str(root/'5.3/datafiles/assets/brushes/essentials_brushes-gp_draw.blend'))).encode()
  args=['/usr/bin/bwrap','--unshare-pid','--unshare-ipc','--unshare-uts','--die-with-parent','--new-session','--clearenv','--ro-bind','/usr','/usr','--symlink','usr/lib','/lib','--symlink','usr/lib64','/lib64','--symlink','usr/bin','/bin','--ro-bind','/etc/ld.so.cache','/etc/ld.so.cache','--ro-bind','/etc/fonts','/etc/fonts','--proc','/proc','--dev','/dev','--tmpfs','/tmp','--dir','/home','--setenv','HOME','/tmp','--setenv','TMPDIR','/tmp','--setenv','PATH','/usr/bin','--setenv','PYTHONDONTWRITEBYTECODE','1','--setenv','OMP_NUM_THREADS','2','--ro-bind',str(root),'/blender']
  files=[(fd(data),name) for data,name in [(b,'/input.blend'),(q,'/query.json'),(w,'/worker.py')]+extra]
  for x,name in files:args+=['--ro-bind-data',str(x),name]
  args+=['--seccomp',str(nix),'--','/blender/blender','--factory-startup','--disable-autoexec','--offline-mode','-b','-t','2','--python-exit-code','17','--python','/advanced_worker.py' if adv else '/worker.py']
  os.lseek(nix,0,0)
  try:r=subprocess.run(args,pass_fds=(nix,*[x for x,name in files]),stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=45)
  finally:
   for x,name in files:os.close(x)
  need(r.returncode==0,'isolated worker failed: '+r.stdout[-600:].decode(errors='replace') if r.returncode else '')
  lines=[i[12:] for i in r.stdout.splitlines() if i.startswith(b'CAMERA-COPY:')];need(len(lines)==1,'missing unique result');return json.loads(lines[0])
 first=invoke(original,'preflight' if adv else 'verify')
 baseline=first['cold']; prediction=first.get('prediction')
 if v.check_only:
  need(invoke(original,'preflight' if adv else 'verify')==first,'independent source checks differ')
  if not adv:need(any(not match(baseline[k],request[k]) for k in edit_keys),'no effective edit')
  source_same()
  print(json.dumps(dict(baseline=baseline,prediction=prediction,source_sha256=v.sha256,query=request)));return
 build=invoke(original,'edit')
 need(build['before']==baseline,'independent input witness differs')
 candidate=base64.b64decode(build['blob'],validate=True);need(0<len(candidate)<=(32<<20) and sha(candidate)!=sha(original),'invalid candidate')
 cold=invoke(candidate,'verify')['cold'];need(build['after']==cold and cold['protected']==baseline['protected'],'cold witness differs')
 if adv:
  need(prediction==cold['sequence'] and cold['sequence']!=baseline['sequence'],'cold result differs from independent expected sequence')
 else:
  for key,val in baseline.items():need(match(cold[key],request.get(key,val) if key in edit_keys else val),'requested or preserved camera value differs: '+key)
  need(any(not match(baseline[k],cold[k]) for k in edit_keys),'no effective edit')
 source_same()
 receipt=dict(enrollment='explicit-owned-static-workcopy-v1' if dynamic else 'frozen-known-sha',mode='bounded-advanced-camera-private-copy' if adv else 'static-camera-private-copy',prediction=prediction,build='02f0899d78e3',source_sha256=v.sha256,candidate_sha256=sha(candidate),query=request,source=baseline,cold_readback=cold)
 # Order matters: receipt is the final completion marker. No replace/reuse of destinations.
 os.mkdir(out.name,0o700,dir_fd=dirfd);dest=os.open(out.name,os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=dirfd)
 for name,data in [('candidate.blend',candidate),('receipt.json',json.dumps(receipt,indent=2,allow_nan=False).encode()+b'\n')]:
  with os.fdopen(os.open(name,os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_WRONLY,0o600,dir_fd=dest),'wb') as fp:need(fp.write(data)==len(data),'short write');fp.flush();os.fsync(fp.fileno())
  with os.fdopen(os.open(name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=dest),'rb') as fp:need(hashlib.file_digest(fp,'sha256').hexdigest()==sha(data),'published byte readback failed')
 os.fsync(dest);os.fsync(dirfd);print(out/'receipt.json')
if __name__=='__main__':main()
