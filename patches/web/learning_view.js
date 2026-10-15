/* One shared solid arm mesh; frames come from the five-control environment. */
import {Renderer,ident,compose,T,S,RX,RZ,V,point} from './renderer.js';
import {buildModel} from './model.js';
import {setupGripper} from './gripper_rig.js';
import {configureKinematics,DEFAULT_DIMS,DEG} from './kinematics.js';
export {Renderer};
export function createView(canvas,meshes,spec,gripperSpec,RendererClass=Renderer){
 configureKinematics(spec);const R=new RendererClass(canvas,meshes),M=buildModel(R,{armOnly:true});
 R.hidden.add('markers');R.hidden.add('target');
 let frame=null;
 const sphere=()=>{let p=[],n=[];const at=(i,j)=>{let a=i*Math.PI/16,b=j*Math.PI/12;return[Math.sin(a)*Math.cos(b),Math.sin(a)*Math.sin(b),Math.cos(a)]};for(let i=0;i<16;i++)for(let j=0;j<24;j++){for(let [a,b]of[[i,j],[i+1,j],[i+1,j+1],[i,j],[i+1,j+1],[i,j+1]]){let v=at(a,b);p.push(...v);n.push(...v)}}return{p,n}};
 R.meshes.sphere=R.mesh(sphere());
 const G=setupGripper(R,gripperSpec);
 // Second end actuator: gripper servo. Wrist servo already exists in the source mesh.
 R.add({geometry:'roundbox',group:'wrist',local:compose(T(68,0,-15),S(22,12,23)),color:[.16,.19,.23],category:'tool',name:'Gripper MG90S servo - estimated mount',rough:.55});
 const bodies=[];for(let i=0;i<3;i++){let b={geometry:['roundbox','cylinder','sphere'][i],group:'object'+i,local:ident(),color:[[.76,.16,.14],[.18,.56,.27],[.15,.37,.82]][i],category:'object',rough:.65};R.add(b);bodies.push(b)}
 const pad={geometry:'roundbox',group:'pad',local:ident(),color:[.78,.80,.82],category:'workpad',rough:.85};R.add(pad);
 const target={geometry:'ring',group:'targetLearn',local:compose(S(18,18,2)),color:[.96,.58,.08],category:'task',rough:.6};R.add(target);
 const orient={geometry:'box',group:'orientGuide',local:compose(T(0,0,22),S(3,3,44)),color:[.8,.4,.04],category:'task',rough:.6};R.add(orient);
 function quaternionMatrix(q,p){let[w,x,y,z]=q;return new Float32Array([1-2*(y*y+z*z),2*(x*y+z*w),2*(x*z-y*w),0,2*(x*y-z*w),1-2*(x*x+z*z),2*(y*z+x*w),0,2*(x*z+y*w),2*(y*z-x*w),1-2*(x*x+y*y),0,...p,1]);}
 function show(f){
  frame=f;let p=f.pose;M.update(p,DEFAULT_DIMS,0);
  G.update(f,R.groups.wrist);
  for(let i=0;i<3;i++){let o=f.objects[i],r=o.radius;bodies[i].local=o.shape==='cylinder'?compose(T(0,0,-(o.half_height||13)),S(r,r,2*(o.half_height||13))):S(o.shape==='box'?2*r:r,o.shape==='box'?2*r:r,o.shape==='box'?2*r:r);R.groups['object'+i]=o.quaternion_wxyz?quaternionMatrix(o.quaternion_wxyz,o.position):T(...o.position);bodies[i].metal=o.pinched?.25:0;}
  R.groups.pad=T(390,0,f.floor_z-4);pad.local=S(310,350,8);
  R.groups.targetLearn=T(...f.goal);R.groups.orientGuide=f.target_orientation_wxyz?quaternionMatrix(f.target_orientation_wxyz,f.goal):compose(T(...f.goal),RZ(p.base*DEG),RX(f.wrist_goal*DEG));
  orient.visible=['orient','rotate','orient_place'].includes(f.task);R.dirty=true;return f;
 }
 function fit(){R.target=[235,0,135];R.radius=850;R.az=1.20;R.polar=1.12;R.dirty=true;}
 fit();return{renderer:R,model:M,show,fit,gripper:G,get frame(){return frame}};
}
