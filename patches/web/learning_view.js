/* One shared solid arm mesh; frames come from the five-control environment. */
import {Renderer,ident,compose,T,S,RZ,V,point} from './renderer.js';
import {buildModel} from './model.js';
import {configureKinematics,DEFAULT_DIMS,DEG} from './kinematics.js';
export {Renderer};
export function createView(canvas,meshes,spec,RendererClass=Renderer){
 configureKinematics(spec);const R=new RendererClass(canvas,meshes),M=buildModel(R,{armOnly:true});
 R.hidden.add('markers');R.hidden.add('target');
 let frame=null;
 const sphere=()=>{let p=[],n=[];const at=(i,j)=>{let a=i*Math.PI/16,b=j*Math.PI/12;return[Math.sin(a)*Math.cos(b),Math.sin(a)*Math.sin(b),Math.cos(a)]};for(let i=0;i<16;i++)for(let j=0;j<24;j++){for(let [a,b]of[[i,j],[i+1,j],[i+1,j+1],[i,j],[i+1,j+1],[i,j+1]]){let v=at(a,b);p.push(...v);n.push(...v)}}return{p,n}};
 R.meshes.sphere=R.mesh(sphere());
 for(let p of R.parts){
  if(p.group==='wrist'&&p.category==='tool'){
   let x=p.local[12],y=p.local[13];
   if(p.geometry==='gripperLink'){p._gripLink={x,y};}
   else if(x>=90){p.group=y<0?'jawRight':'jawLeft';}
   else if(p.geometry==='gripperGear'){p._gearBase=p.local;}
  }
 }
 // Second end actuator: gripper servo. Wrist servo already exists in the source mesh.
 R.add({geometry:'roundbox',group:'wrist',local:compose(T(68,0,-15),S(22,12,23)),color:[.16,.19,.23],category:'tool',name:'Gripper MG90S servo - estimated mount',rough:.55});
 const bodies=[];for(let i=0;i<3;i++){let b={geometry:['roundbox','cylinder','sphere'][i],group:'object'+i,local:ident(),color:[[.76,.16,.14],[.18,.56,.27],[.15,.37,.82]][i],category:'object',rough:.65};R.add(b);bodies.push(b)}
 const pad={geometry:'roundbox',group:'pad',local:ident(),color:[.78,.80,.82],category:'workpad',rough:.85};R.add(pad);
 const target={geometry:'ring',group:'targetLearn',local:compose(S(18,18,2)),color:[.96,.58,.08],category:'task',rough:.6};R.add(target);
 const orient={geometry:'box',group:'orientGuide',local:compose(T(20,0,0),S(40,2,2)),color:[.8,.4,.04],category:'task',rough:.6};R.add(orient);
 function show(f){
  frame=f;let p=f.pose;M.update(p,DEFAULT_DIMS,0);
  const original=R.groups.wrist;R.groups.wrist=compose(original,T(26,0,0),RZ((p.wrist||0)*DEG),T(-26,0,0));
  const gap=6+50*(p.gripper??.6),offset=gap/2-39; // jaw centers now match collision aperture
  R.groups.jawLeft=compose(R.groups.wrist,T(0,offset,0));R.groups.jawRight=compose(R.groups.wrist,T(0,-offset,0));
  for(const part of R.parts){if(part._gripLink){let s=part._gripLink.y<0?-1:1;let primary=part._gripLink.x<80;
   let a=primary?[53,s*12]:[64,s*3],b=primary?[99,s*(39+offset)]:[108,s*(29+offset)];
   let dx=b[0]-a[0],dy=b[1]-a[1];part.local=compose(T((a[0]+b[0])/2,(a[1]+b[1])/2,primary?2:-1.5),RZ(Math.atan2(dy,dx)),S(Math.hypot(dx,dy)/50,1,1));
  }}
  for(let i=0;i<3;i++){let o=f.objects[i],r=o.radius;bodies[i].local=o.shape==='cylinder'?compose(T(0,0,-r),S(r,r,2*r)):S(o.shape==='box'?2*r:r,o.shape==='box'?2*r:r,o.shape==='box'?2*r:r);R.groups['object'+i]=T(...o.position);bodies[i].metal=o.pinched?.25:0;}
  R.groups.pad=T(390,0,f.floor_z-4);pad.local=S(310,350,8);
  R.groups.targetLearn=T(...f.goal);R.groups.orientGuide=compose(T(...f.goal),RZ((p.base+f.wrist_goal)*DEG));
  orient.visible=f.task==='orient';R.dirty=true;return f;
 }
 function fit(){R.target=[235,0,135];R.radius=850;R.az=1.20;R.polar=1.12;R.dirty=true;}
 fit();return{renderer:R,model:M,show,fit,get frame(){return frame}};
}
