import fs from 'node:fs';
import assert from 'node:assert/strict';
import {createView} from '../web/learning_view.js';
import {point,ident} from '../web/renderer.js';
const json=p=>JSON.parse(fs.readFileSync(new URL(p,import.meta.url),'utf8'));
class NoGL {constructor(c,meshes){this.parts=[];this.groups={};this.hidden=new Set();this.meshes=meshes;this.dirty=true;this.canvas=c;}add(p){this.parts.push(p)}mesh(x){return x}render(){}}
const meshes=json('../web/assets/meshes.json'),spec=json('../web/assets/kinematics.json'),grip=json('../web/assets/gripper.json');
const view=createView({},meshes,spec,grip,NoGL);
const frame={pose:{base:0,shoulder:65,forearm:-25,wrist:0,gripper:0},objects:[0,1,2].map((x)=>({shape:['box','cylinder','sphere'][x],radius:12,position:[400,100*x,80]})),floor_z:65,goal:[400,0,180],task:'orient',wrist_goal:0};
const refs=[];
for(let i=0;i<=100;i++){
 frame.pose.gripper=i/100;view.show(frame);
 const L=view.renderer.groups.jawLeft,R=view.renderer.groups.jawRight;
 const ly=L[13],ry=R[13];assert(ly>=43-.001);assert(ry<=-43+.001);
 for(const [group,side] of [['jawLeft',1],['jawRight',-1]]){
  for(const p of view.renderer.parts.filter(p=>p.group===group)){
   if(p.geometry!=='finger')continue;
   for(let j=0;j<meshes.finger.p.length;j+=3){
    const local=point(p.local,meshes.finger.p.slice(j,j+3));
    const a=point(view.renderer.groups[group],local);assert(side*a[1]>2.99,'visible jaw crosses center');
   }
  }
 }
 refs.push([ly,ry]);
}
assert(refs[100][0]-refs[0][0]>18);
// Collision-body matrices take priority; the renderer must use actual dynamics.
frame.rigid_bodies={wrist:Array.from(ident()),wristMount:Array.from(ident()),jawLeft:Array.from(ident()),jawRight:Array.from(ident())};
frame.rigid_bodies.jawLeft[13]=57;frame.rigid_bodies.jawRight[13]=-58;
view.show(frame);assert.equal(view.renderer.groups.jawLeft[13],57);assert.equal(view.renderer.groups.jawRight[13],-58);
assert(!view.renderer.parts.some(p=>p.group==='mast'));
// A local roll turns the transverse axis but preserves the tool's long axis.
delete frame.rigid_bodies;frame.pose.gripper=.5;
frame.pose.wrist=0;view.show(frame);const baseW=Array.from(view.renderer.groups.wrist);
for (const deg of [90,180,270,360]) {
 frame.pose.wrist=deg;view.show(frame);const w=view.renderer.groups.wrist;
 for(const k of [0,1,2,12,13,14])assert(Math.abs(w[k]-baseW[k])<.001,'Roll steered or translated the shaft');
 if(deg===90)assert(Math.abs(w[6])>.99,'90-degree roll must rotate across the tool shaft');
}

console.log(JSON.stringify({sampled_apertures:101,jaw_crossings:0,actual_body_matrices_preserved:true,red_tower:false,parts:view.renderer.parts.length}));
