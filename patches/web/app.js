import {setupKeyUI} from './key_ui.js';
const $=id=>document.getElementById(id),token=document.querySelector('meta[name="lab-token"]').content;
let view=null,status=null,play=null,epoch=0,busy=false,lastId=0,lastFrame=0,closed=false,evalSeen='';
let controlSeq=Date.now()*1000;
let connected=false,graphicsReady=false,graphicsFailed=false,animationStarted=false,latestFrame=null;
const TASKS=['reach','orient','push','lift','place'];
async function api(path,body){
 if(body!==undefined&&['/api/start','/api/stop'].includes(path))body={...body,control_seq:++controlSeq};
 const abort=new AbortController();
 const limit=path.includes('/hackclub/test')?40000:path==='/api/trial'?90000:15000;
 const timer=setTimeout(()=>abort.abort(),limit);
 try{
  const r=await fetch(path,{method:body===undefined?'GET':'POST',headers:{'X-Lab-Token':token,...(body===undefined?{}:{'Content-Type':'application/json'})},body:body===undefined?undefined:JSON.stringify(body),cache:'no-store',signal:abort.signal});
  let j;try{j=await r.json()}catch(e){throw Error('The local app returned an unreadable reply. Reopen the address printed by START.bat.');}
  if(!r.ok)throw Error(j.error||`Local request failed (${r.status}).`);
  return j;
 }catch(e){
  if(e.name==='AbortError')throw Error('This request timed out. The key was not deleted. Keep START.bat open and try again.');
  if(e instanceof TypeError)throw Error('Cannot reach the local Seizo app. Run START.bat and use the READY address it prints, not an old bookmark.');
  throw e;
 }finally{clearTimeout(timer);}
}
function say(s,error=false){$('status').textContent=s;$('status').className=error?'error':'';}
function fail(e){say(e.message||String(e),true);}
function task(){const s=$('task').value;return TASKS.includes(s)?s:s==='all'?TASKS[Math.floor(Math.random()*5)]:TASKS[status?.stage||0];}
function controls(){const unavailable=!connected;const active=['training','stopping','evaluating'].includes(status?.status);$('train').disabled=unavailable||active||busy;$('watch').disabled=unavailable||!graphicsReady||active||busy;$('evaluate').disabled=unavailable||active||busy;$('task').disabled=unavailable||active||busy;}
function show(f){latestFrame=f;if(!view||!graphicsReady)return;view.show(f);const selected=f.objects[f.selected_object];let extra=f.task==='orient'?` · targets: wrist ${f.wrist_goal.toFixed(0)}°, opening ${(f.gap_goal*100).toFixed(0)}%`:['lift','place'].includes(f.task)?` · lift ${f.lift_mm.toFixed(0)} mm · ${selected.pinched?'grasped':'not grasped'}`:'';$('taskInfo').textContent=`${f.task_label} · ${selected.name} · wrist ${f.pose.wrist.toFixed(0)}° · gripper ${(f.pose.gripper*100).toFixed(0)}%${extra}${f.arm_object_contact?' · solid collision':''}`}
function begin(trace,label){play={trace,index:0,at:0,label,generation:epoch};show(trace.frames[0]);$('overlay').textContent=label;}
function interpolate(a,b,t){
 const f={...a,pose:{...a.pose},objects:a.objects.map(o=>({...o,position:[...o.position]}))};
 for(const k of Object.keys(f.pose))f.pose[k]=a.pose[k]+(b.pose[k]-a.pose[k])*t;
 for(let i=0;i<3;i++)for(let j=0;j<3;j++)f.objects[i].position[j]=a.objects[i].position[j]+(b.objects[i].position[j]-a.objects[i].position[j])*t;
 return f;
}
function frame(t){
 try {
 if(graphicsFailed)return;
 const dt=lastFrame?Math.min(200,t-lastFrame):0;lastFrame=t;
 if(play&&play.generation===epoch){
  play.at+=dt;const ms=+$('speed').value;
  const fs=play.trace.frames;
  if(play.index<fs.length-1)show(interpolate(fs[play.index],fs[play.index+1],Math.min(1,play.at/ms)));
  if(play.at>=ms){play.at=0;play.index++;
   if(play.index<fs.length){show(fs[play.index]);$('overlay').textContent=`${play.label} · move ${play.index}/${fs.length-1}`;}
   else{const p=play;play=null;$('outcome').textContent=p.trace.fault?'Trial stopped on an injected fault. This is a supervisor test, not learned safety.':p.trace.success?'This virtual trial reached its success criteria. Check progress tests more fresh scenes.':'This trial did not succeed. No scripted rescue or replacement was used.';}
  }
 }
 view?.renderer.render();
 }catch(e){graphicsError(e.message||String(e));}
 finally{requestAnimationFrame(frame);}
}
$('train').onclick=async()=>{busy=true;controls();epoch++;play=null;try{say('Starting local neural training...');await api('/api/start',{episodes:+$('episodes').value,task:$('task').value,compute:$('compute').value,fault_probability:0});lastId=0;await poll();}catch(e){fail(e)}finally{busy=false;controls()}};
$('stop').onclick=async()=>{epoch++;play=null;say('Displayed movement stopped. Saving policy...');try{await api('/api/stop',{});await poll();}catch(e){fail(e)}};
$('watch').onclick=async()=>{busy=true;controls();const id=++epoch;play=null;say('Running a frozen virtual-policy trial...');try{const tr=await api('/api/trial',{task:task(),source:$('source').value,fault:$('fault').checked});if(id!==epoch)return;begin(tr,tr.policy_updates?'Saved neural policy':'Untrained neural policy: random exploration');say(tr.policy_updates?'Watching learned decisions. No weights change during this test.':'Watching the untrained policy. It has not learned yet.');}catch(e){fail(e)}finally{busy=false;controls()}};
$('evaluate').onclick=async()=>{epoch++;play=null;try{say('Testing fresh scenarios and matching random baselines...');await api('/api/evaluate',{task:$('task').value==='all'?'all':task()});await poll()}catch(e){fail(e)}};
let polling=false;
async function poll(){if(polling||closed)return;polling=true;try{status=await api('/api/status');connected=true;$('connection').textContent='Local app connected · '+location.host;$('connection').className='online';let s=status;const nf=n=>Number(n).toLocaleString();$('progress').textContent=`${nf(s.episodes)} / ${nf(s.target_episodes)} completed episodes · ${nf(s.moves)} movements · ${nf(s.updates)} network updates`;$('bar').max=s.target_episodes;$('bar').value=s.episodes;
 if(s.status==='training'){say(`Learning: ${s.lesson}. ${s.episodes<1?'Exploring before the first completed episode.':''}`);let tr=s.trace;if(graphicsReady&&!play&&tr&&tr.id!==lastId){lastId=tr.id;begin(tr,`Training exploration from episode ${nf(tr.episode)}`);}let eta=s.estimated_seconds_remaining;$('outcome').textContent=`Showing a sampled trial, not every background movement. ${eta?`At the measured rate, remaining budget is about ${Math.ceil(eta/3600)} hours (rough estimate).`:''}`;}
 else if(s.status==='stopping')say('Stopped. Finishing the current update and saving...');
 else if(s.status==='evaluating')say('Evaluating without changing the policy. Training counters stay unchanged.');
 else if(s.status==='error')say(s.error,true);
 else if(!play&&!busy)say(s.updates?`Saved. ${nf(s.updates)} neural updates completed. Choose Watch policy or Check progress.`:'Ready. The policy starts untrained. Watch it first, then Train / resume.');
 if(s.evaluation&&JSON.stringify(s.evaluation)!==evalSeen){evalSeen=JSON.stringify(s.evaluation);let a=s.evaluation.current,b=s.evaluation.random_actions;$('evaluation').textContent=s.evaluation.by_task?s.evaluation.by_task.map(r=>`${r.current.task}: policy ${r.current.successes}/${r.current.trials}, random ${r.random_actions.successes}/${r.random_actions.trials}`).join(' · '):`Fresh ${a.task} test: learned policy ${a.successes}/${a.trials}; random actions ${b.successes}/${b.trials}. Mean error ${a.mean_error_mm.toFixed(1)} mm versus ${b.mean_error_mm.toFixed(1)} mm (estimated simulation units).`;}
 controls();}catch(e){connected=false;$('connection').textContent=e.message;$('connection').className='error';controls();}finally{polling=false}}
$('task').onchange=()=>{epoch++;play=null;$('outcome').textContent='Choose Watch policy to test this task.'};
$('settingsOpen').onclick=()=>$('settings').showModal();$('settingsClose').onclick=()=>$('settings').close();$('fit').onclick=()=>view?.fit();
$('reset').onclick=async()=>{if(!confirm('Back up this policy and start a completely untrained one? Stop training first.'))return;try{epoch++;play=null;await api('/api/reset',{confirmed:true});evalSeen='';$('evaluation').textContent='';await poll();$('settings').close()}catch(e){fail(e)}};
$('export').onclick=async()=>{try{const r=await api('/api/status');delete r.trace;const u=URL.createObjectURL(new Blob([JSON.stringify(r,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=u;a.download='Seizo_Learning_Report.json';a.click();setTimeout(()=>URL.revokeObjectURL(u),1000)}catch(e){fail(e)}};
const keyUI=setupKeyUI(api);
$('quit').onclick=async()=>{try{epoch++;play=null;await api('/api/quit',{});closed=true;say('Saving and closing. Wait for Saved in the terminal.');$('settings').close()}catch(e){fail(e)}};
window.addEventListener('error',e=>fail(Error(e.message)));window.addEventListener('unhandledrejection',e=>fail(e.reason));
document.addEventListener('keydown',e=>{if(e.code==='Space'&&!['INPUT','SELECT','TEXTAREA','BUTTON'].includes(e.target.tagName)){e.preventDefault();$('stop').click()}});
function graphicsError(text){
 graphicsFailed=true;graphicsReady=false;play=null;
 $('graphicsError').hidden=false;
 $('graphicsMessage').textContent='3D view unavailable: '+text+' Training and key controls still work.';
 controls();
}
$('retryView').onclick=()=>location.reload();
document.addEventListener('studio-error',e=>graphicsError(e.detail));
$('viewport').addEventListener('webglcontextlost',e=>{e.preventDefault();graphicsError('The browser paused its graphics context. Reload the view to restore it.');});
async function init(){
 // Start backend connection and key controls independently of WebGL/module loading.
 await poll();
 setInterval(poll,1500);
 window.__seizo={get view(){return view},get state(){return status},get playback(){return play}};
 if(status?.config){$('episodes').value=status.config.episodes;$('task').value=status.config.task;$('compute').value=status.config.compute;}
 try{
  const fetchJSON=async path=>{const r=await fetch(path,{cache:'no-store'});if(!r.ok)throw Error('Missing '+path+'; extract the whole download folder.');return r.json();};
  const [module,meshes,spec]=await Promise.all([import('./learning_view.js'),fetchJSON('/assets/meshes.json'),fetchJSON('/assets/kinematics.json')]);
  view=module.createView($('viewport'),meshes,spec);graphicsReady=true;graphicsFailed=false;
  show(await api('/api/initial'));if(!animationStarted){animationStarted=true;requestAnimationFrame(frame);}
  controls();
 }catch(e){graphicsError(e.message||String(e));}
}
init();