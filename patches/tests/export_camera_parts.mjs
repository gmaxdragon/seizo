/* Offline build tool: exports the same real mesh instances as the human viewport.
   Node is used only to build this asset, never required on the user's laptop. */
import fs from 'node:fs';
import {createView} from '../web/learning_view.js';
import {ident} from '../web/renderer.js';
const json=p=>JSON.parse(fs.readFileSync(new URL(p,import.meta.url),'utf8'));
class NoGL {constructor(c,m){this.parts=[];this.groups={};this.hidden=new Set();this.meshes={...m};}add(p){this.parts.push(p)}mesh(x){return x}}
const meshes=json('../web/assets/meshes.json');
const view=createView({},meshes,json('../web/assets/kinematics.json'),json('../web/assets/gripper.json'),NoGL);
view.show({pose:{base:0,shoulder:65,forearm:-25,wrist:0,gripper:0},objects:[0,1,2].map((x)=>({shape:['box','cylinder','sphere'][x],radius:12,position:[400,100*x,80]})),floor_z:65,goal:[400,0,180],task:'reach',wrist_goal:0});
const parts=[];const barsSeen={"1":0,"-1":0};
for(const p of view.renderer.parts){
 if(['environment','object','workpad','task','target'].includes(p.category)||p.group==='mast')continue;
 const item={...p,local:Array.from(p.local)};
 if(p.geometry==='gripperLink'){
  item.dynamic='bar';item.side=p.local[13]<0?-1:1;item.primary=barsSeen[item.side]++===0;
  item.group=`bar_${parts.length}`;item.local=Array.from(ident());
 }
 if(p.geometry==='gripperGear'){
  item.dynamic='gear';item.side=p.local[13]<0?-1:1;item.group=`gear_${parts.length}`;
 }
 parts.push(item);
}
const extra={};
for(const [k,v]of Object.entries(view.renderer.meshes))if(!(k in meshes))extra[k]=v;
const out={schema:'seizo-shared-visual-meshes/v1',units:'estimated_mm',parts,extra_meshes:extra,source:'web/model.js + web/gripper_rig.js + web/assets/meshes.json'};
fs.writeFileSync(new URL('../web/assets/camera_parts.json',import.meta.url),JSON.stringify(out));
console.log({parts:parts.length,groups:[...new Set(parts.map(p=>p.group))]});
