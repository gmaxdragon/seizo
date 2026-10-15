/* Shared rigid tool: one shaft rotation plus one mechanically coupled aperture.
 * A frame from MuJoCo overrides ideal transforms with actual simulated body poses.
 * Opening=0 is the CLOSED jaw geometry. Never translate it farther inward.
 */
import {T,S,RZ,compose,point,V} from './renderer.js';
export function setupGripper(R,spec){
 const jawParts=[],bars=[],gears=[];
 for(const p of R.parts){
  if(p.group!=='wrist')continue;
  const x=p.local[12],y=p.local[13],side=y<0?-1:1;
  if(p.category==='forearm'||p.name==='Wrist crosshead'||p.name==='Wrist adapter'){
   p.group='wristMount';continue;
  }
  if(p.geometry==='gripperLink'){bars.push({part:p,side,primary:x<80});continue;}
  if(p.geometry==='gripperGear'){gears.push({part:p,side,local:p.local});continue;}
  if(p.name==='Thin orange fingertip pad'){
   p.group=side>0?'jawLeft':'jawRight';p.local=compose(T(spec.pad_center[0],side*spec.pad_center[1],spec.pad_center[2]),S(...spec.pad_halfsize.map(v=>2*v)));jawParts.push(p);continue;
  }
  if(p.geometry==='finger'||(p.category==='tool'&&x>=90)){
   p.group=side>0?'jawLeft':'jawRight';p.local=compose(T(-99,-side*39,2),p.local);jawParts.push(p);
  }
 }
 function barTransform(a,b,z){
  const d=V.sub(b,a),len=Math.hypot(...d),u=V.norm(d),normal=V.norm(z);
  const v=V.norm(V.cross(normal,u));const n=V.norm(V.cross(u,v));
  return new Float32Array([u[0]*len/60,u[1]*len/60,u[2]*len/60,0,v[0],v[1],v[2],0,n[0],n[1],n[2],0,(a[0]+b[0])/2,(a[1]+b[1])/2,(a[2]+b[2])/2,1]);
 }
 function update(frame,baseWrist){
  const p=frame.pose;const angle=(p.wrist||0)*Math.PI/180;
  const shaft=compose(baseWrist,T(...spec.wrist_pivot),RZ(angle),T(...spec.wrist_pivot.map(v=>-v)));
  const a=Math.max(0,Math.min(1,p.gripper??.6))*spec.max_link_angle_rad;
  const [lx,ly]=spec.link;
  const dx=lx*(Math.cos(a)-1)-ly*Math.sin(a),dy=lx*Math.sin(a)+ly*(Math.cos(a)-1);
  const rigid=frame.rigid_bodies;
  R.groups.wristMount=rigid?.wristMount?new Float32Array(rigid.wristMount):baseWrist;
  R.groups.wrist=rigid?.wrist?new Float32Array(rigid.wrist):shaft;
  for(const [group,side]of[['jawLeft',1],['jawRight',-1]]){
   R.groups[group]=rigid?.[group]?new Float32Array(rigid[group]):compose(R.groups.wrist,T(99+dx,side*(43+dy),-2));
  }
  const normal=V.sub(point(R.groups.wrist,[0,0,1]),point(R.groups.wrist,[0,0,0]));
  for(const {part,side,primary}of bars){
   const root=primary?[53,side*12,0]:[64,side*3,0];
   const tip=primary?[0,0,2]:[11,-side*9,2];
   const A=point(R.groups.wrist,root),B=point(R.groups[side>0?'jawLeft':'jawRight'],tip);
   part.group='gripperBars';R.groups.gripperBars=T(0,0,0);part.local=barTransform(A,B,normal);
  }
  for(const {part,side,local}of gears){part.local=compose(T(53,side*11,0),RZ(side*a),T(-53,-side*11,0),local);}
  return {opening:p.gripper,shaftMatrix:R.groups.wrist,left:R.groups.jawLeft,right:R.groups.jawRight,jawParts};
 }
 return {update,jawParts};
}
