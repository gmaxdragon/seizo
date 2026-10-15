import {setupKeyUI} from './key_ui.js';
const $=id=>document.getElementById(id),token=document.querySelector('meta[name="lab-token"]').content;
let view=null,status=null,play=null,epoch=0,busy=false,lastId=0,lastFrame=0,closed=false,evalSeen='';
let controlSeq=Date.now()*1000;
let connected=false,graphicsReady=false,graphicsFailed=false,animationStarted=false,latestFrame=null;
const TASKS=['reach','orient','push','lift','place','rotate','orient_place'];
let suggestedLesson=null;
async function api(path,body){
 if(body!==undefined&&['/api/start','/api/stop'].includes(path))body={...body,control_seq:++controlSeq};
 const abort=new AbortController();
 const limit=path.includes('/hackclub/test')||path.includes('/hackclub/review')?40000:['/api/trial','/api/gripper-check'].includes(path)?180000:['/api/initial','/api/cameras/preview'].includes(path)?60000:15000;
 const timer=setTimeout(()=>abort.abort(),limit);
 try{
  const r=await fetch(path,{method:body===undefined?'GET':'POST',headers:{'X-Lab-Token':token,...(body===undefined?{}:{'Content-Type':'application/json'})},body:body===undefined?undefined:JSON.stringify(body),cache:'no-store',signal:abort.signal});
  let j;try{j=await r.json()}catch(e){throw Error('The local app returned an unreadable reply. Reopen the address printed by START_SEIZO.bat.');}
  if(!r.ok)throw Error(j.error||`Local request failed (${r.status}).`);
  return j;
 }catch(e){
  if(e.name==='AbortError')throw Error('This request timed out. The key was not deleted. Keep START_SEIZO.bat open and try again.');
  if(e instanceof TypeError)throw Error('Cannot reach the local Seizo app. Run START_SEIZO.bat and use the READY address it prints, not an old bookmark.');
  throw e;
 }finally{clearTimeout(timer);}
}
function say(s,error=false){$('status').textContent=s;$('status').className=error?'error':'';}
function fail(e){say(e.message||String(e),true);}
function task(){const s=$('task').value;return TASKS.includes(s)?s:s==='all'?TASKS[Math.floor(Math.random()*TASKS.length)]:TASKS[status?.stage||0];}
let cameraURLs={},lastCameraSerial=-1;
function cameraFrames(frame){
 const c=frame?.cameras;if(!c)return;
 for(const [name,id] of [['overhead','overheadFrame'],['wrist','wristFrame']]){
  if(!c[name])continue;
  if(cameraURLs[name])URL.revokeObjectURL(cameraURLs[name]);
  const bytes=Uint8Array.from(atob(c[name]),c=>c.charCodeAt(0));
  cameraURLs[name]=URL.createObjectURL(new Blob([bytes],{type:'image/png'}));$(id).src=cameraURLs[name];
 }
 const p=c.settings||{};
 $('cameraState').textContent=`Policy input: ONLY these two RGB frames + their previous frames + task instructions. Setup: ${p.profile||'unknown'}; overhead ${p.overhead_fovy?.toFixed(0)||'?'}° FOV. ${frame.safety_abort?'Trial aborted: '+frame.safety_abort+'.':''}`;
}
function controls(){const unavailable=!connected;const active=['training','stopping','evaluating','watching'].includes(status?.status);$('train').disabled=unavailable||active||busy;$('watch').disabled=unavailable||!graphicsReady||active||busy;$('evaluate').disabled=unavailable||active||busy;$('task').disabled=unavailable||active||busy;$('gripperCheck').disabled=unavailable||!graphicsReady||active||busy;$('reviewAI').disabled=unavailable||active||busy;}
function show(f){
 latestFrame=f;cameraFrames(f);if(f.diagnostic)$('cameraState').textContent='Scripted mechanism check: camera learning is inactive. The images above retain the last policy observation.';if(!view||!graphicsReady)return;view.show(f);
 const selected=f.objects[f.selected_object],roll=((f.pose.wrist%360)+360)%360;
 let touch=f.gripper_object_contact?`Finger contact${f.gripper_contact_continues?' / bounded squeeze':''}`:
             f.contacts?.arm_object?'Arm touching an object':f.contacts?.environment?'Arm touching the table':'No finger contact';
 let extra=['rotate','orient_place'].includes(f.task)?` · object orientation error ${f.object_orientation_error_degrees?.toFixed(0)}°`:'';
 $('taskInfo').textContent=`${f.diagnostic?f.diagnostic_phase:f.task_label} · tool ROLL ${roll.toFixed(0)}° · opening ${(f.pose.gripper*100).toFixed(0)}% · ${touch}${extra}${f.diagnostic?' · MECHANISM CHECK, NOT LEARNING':''}`;
}

function begin(trace,label){play={trace,index:0,at:0,label,generation:epoch};show(trace.frames[0]);$('overlay').textContent=label;}
function frame(t){
 try {
 if(graphicsFailed)return;
 const dt=lastFrame?Math.min(200,t-lastFrame):0;lastFrame=t;
 if(play&&play.generation===epoch){
  play.at+=dt;const ms=+$('speed').value;
  const fs=play.trace.frames;
  if(play.index<fs.length-1)show(fs[play.index]);
  if(play.at>=ms){play.at=0;play.index++;
   if(play.index<fs.length){show(fs[play.index]);$('overlay').textContent=`${play.label} · move ${play.index}/${fs.length-1}`;}
   else{const p=play;play=null;$('outcome').textContent=p.trace.diagnostic?p.trace.diagnostic_message:p.trace.fault?'Trial stopped on an injected fault. This is a supervisor test, not learned safety.':p.trace.success?'This virtual trial reached its success criteria. Check progress tests more fresh scenes.':'This trial did not succeed. No scripted rescue or replacement was used.';}
  }
 }
 view?.renderer.render();
 }catch(e){graphicsError(e.message||String(e));}
 finally{requestAnimationFrame(frame);}
}
$('train').onclick=async()=>{busy=true;controls();epoch++;play=null;try{say('Starting local neural training...');await api('/api/start',{episodes:+$('episodes').value,task:$('task').value,compute:$('compute').value,fault_probability:0});lastId=0;await poll();}catch(e){fail(e)}finally{busy=false;controls()}};
$('stop').onclick=async()=>{epoch++;play=null;say('Displayed movement stopped. Saving policy...');try{await api('/api/stop',{});await poll();}catch(e){fail(e)}};
$('watch').onclick=async()=>{busy=true;controls();const id=++epoch;play=null;say('Running a frozen virtual-policy trial...');try{const tr=await api('/api/trial',{task:task(),source:$('source').value,fault:$('fault').checked});if(id!==epoch)return;begin(tr,tr.policy_updates?'Updated policy, skill not guaranteed':'Untrained neural policy: random exploration');say(tr.policy_updates?'Testing updated policy weights. Improvement is not guaranteed. No learning during this test.':'Watching the untrained policy. It has not learned yet.');}catch(e){fail(e)}finally{busy=false;controls()}};
$('evaluate').onclick=async()=>{epoch++;play=null;try{say('Testing ALL seven tasks and paired random baselines. No cloud calls or weight updates.');await api('/api/evaluate',{task:'all',trials:+$('evalTrials').value});await poll()}catch(e){fail(e)}};
let polling=false;
async function poll(){if(polling||closed)return;polling=true;try{status=await api('/api/status');connected=true;$('connection').textContent='Local app connected · '+location.host;$('connection').className='online';let s=status;if(s.live_camera&&s.live_camera.serial!==lastCameraSerial){lastCameraSerial=s.live_camera.serial;cameraFrames(s.live_camera);}const nf=n=>Number(n).toLocaleString();$('physicsBadge').textContent=s.build+' · '+s.physics;$('progress').textContent=`${nf(s.episodes)} / ${nf(s.target_episodes)} completed episodes · ${nf(s.moves)} movements · ${nf(s.updates)} network updates`;$('saveStatus').textContent=s.save_verified&&s.saved_fingerprint===s.policy_fingerprint?
  `Saved and verified by reload: ${new Date(s.last_saved*1000).toLocaleTimeString()} · policy ${s.saved_fingerprint.slice(0,10)}. Safe to close after the run is idle.`:
  (s.status==='stopping'?'Not finished saving yet. Keep the terminal open.':'Current changes are not yet checkpointed. STOP & save before closing.');
 $('bar').max=s.target_episodes;$('bar').value=s.episodes;
 if(s.status==='training'){say(`Practising ${s.lesson}. This is the current lesson, not a pass. ${s.episodes<1?'Exploring before the first completed episode.':''}`);let tr=s.trace;if(graphicsReady&&!play&&tr&&tr.id!==lastId){lastId=tr.id;begin(tr,`Training exploration from episode ${nf(tr.episode)}`);}let eta=s.estimated_seconds_remaining;$('outcome').textContent=`Showing a sampled trial, not every background movement. ${eta?`At the measured rate, remaining budget is about ${Math.ceil(eta/3600)} hours (rough estimate).`:''}`;}
 else if(s.status==='stopping')say('Stop requested. Waiting for the current operation to stop and the checkpoint to verify...');
 else if(s.status==='evaluating')say(`Frozen evaluation: ${s.evaluation_progress?.phase||'starting'} · ${s.evaluation_progress?.completed||0}/${s.evaluation_progress?.total||7} tasks. No learning or API calls.`);
 else if(s.status==='watching')say('Computing a camera-only policy test. STOP cancels it.');
 else if(s.status==='error')say(s.error,true);
 else if(!play&&!busy)say(s.updates?`Idle. ${nf(s.updates)} neural updates completed. See saved-checkpoint status below.`:'Ready. The policy starts untrained. Watch it first, then Train / resume.');
 $('learningEvidence').textContent=`Parameter-update evidence, not skill mastery: ${nf(s.parameters_changed_from_initial||0)} parameter values differ from the initial network. ${s.weights_changed_from_initial?'Weights changed; evaluation determines whether performance improved.':'No parameter update yet.'}`;
 const usage=s.cloud?.api_usage;
 if(usage)$('apiActivity').textContent=`API: ${usage.attempts} request attempts · ${usage.successful_responses} accepted responses · ${usage.total_tokens} reported tokens. Last: ${usage.last?.purpose||'none'}. Training uses 0 API calls.`;
 if(!s.evaluation&&evalSeen){$('evaluation').replaceChildren();evalSeen='';}
 const evaluationStamp=s.evaluation?JSON.stringify(s.evaluation)+s.policy_fingerprint+JSON.stringify(s.camera_config):'';
 if(s.evaluation&&evaluationStamp!==evalSeen){
  evalSeen=evaluationStamp;const e=s.evaluation,box=$('evaluation');box.replaceChildren();
  const matches=e.policy_fingerprint===s.policy_fingerprint&&JSON.stringify(e.camera_config||{})===JSON.stringify(s.camera_config||{});
  const heading=document.createElement('p');heading.textContent=`${matches?'CURRENT policy evaluation':'OLDER evaluation: policy or camera settings changed'}. At ${e.episodes_at_test} episodes: ${e.current.successes}/${e.current.trials} successful trials. This is not proof of mastery. Evaluation itself changed no weights: ${e.fingerprint_unchanged}.`;box.append(heading);
  const table=document.createElement('table');const head=document.createElement('tr');
  for(const text of ['Task','Policy success','Random success','95% interval']){let cell=document.createElement('th');cell.textContent=text;head.append(cell)}table.append(head);
  for(const r of e.by_task||[]){const tr=document.createElement('tr'),c=r.current,ci=c.success_interval_95;
   for(const text of [c.task,`${c.successes}/${c.trials}`,`${r.random_actions.successes}/${r.random_actions.trials}`,ci?`${(100*ci[0]).toFixed(0)}–${(100*ci[1]).toFixed(0)}%`:'']){let td=document.createElement('td');td.textContent=text;tr.append(td)}table.append(tr);
  }box.append(table);
  if(e.fault_test){let p=document.createElement('p');p.textContent=`Separate fault exercise: ${e.fault_test.faults}/${e.fault_test.trials} fault aborts. These are not counted as task successes.`;box.append(p)}
 }

 controls();}catch(e){connected=false;$('connection').textContent=e.message;$('connection').className='error';controls();}finally{polling=false}}

$('gripperCheck').onclick=async()=>{
 busy=true;controls();const id=++epoch;play=null;
 try{
  say('Computing a local two-servo physics check. No API key or physical arm is used.');
  const tr=await api('/api/gripper-check',{mode:$('gripperMode').value});
  if(id!==epoch)return;
  begin(tr,'Gripper check, not AI learning');
  if(tr.frames?.length){view.renderer.target=tr.frames[0].tool;view.renderer.radius=430;view.renderer.polar=.65;view.renderer.az=1.15;}
  say('Arm axes fixed for this diagnostic. STOP cancels playback.');
 }catch(e){fail(e)}finally{busy=false;controls()}
};

$('reviewAI').onclick=async()=>{
 busy=true;controls();$('aiAdvice').textContent='Sending your measured evaluation summary to Hack Club AI. One manual request.';
 try{const r=await api('/api/hackclub/review',{model:$('keyModel').value});suggestedLesson=r.advice.next_task;
  $('aiAdvice').textContent=`${r.advice.summary} Suggested lesson: ${suggestedLesson}. ${r.advice.reason} This is context-based advice, not cloud model training.`;
  $('useAdvice').hidden=false;await poll();
 }catch(e){$('aiAdvice').textContent=e.message}finally{busy=false;controls()}
};
$('useAdvice').onclick=()=>{if(TASKS.includes(suggestedLesson)&&!['training','evaluating','stopping'].includes(status?.status)){
 $('task').value=suggestedLesson;say('Lesson selected. Press Train / resume when ready. No hardware control.');
}};
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
  const [module,meshes,spec,gripperSpec]=await Promise.all([import('./learning_view.js'),fetchJSON('/assets/meshes.json'),fetchJSON('/assets/kinematics.json'),fetchJSON('/assets/gripper.json')]);
  view=module.createView($('viewport'),meshes,spec,gripperSpec);graphicsReady=true;graphicsFailed=false;
  show(await api('/api/initial'));if(!animationStarted){animationStarted=true;requestAnimationFrame(frame);}
  controls();
 }catch(e){graphicsError(e.message||String(e));}
}
init();

$('applyCameras').onclick=async()=>{
 try{
 const value={profile:$('cameraProfile').value,overhead_height_m:Number($('cameraHeight').value)/100,
   overhead_side_m:Number($('cameraSide').value)/100,wrist_mount:$('cameraMount').value,frame_faults:$('cameraFaults').checked};
 await api('/api/cameras/config',value);
 const frame=await api('/api/cameras/preview',{});show(frame);say('Camera setup saved. This preview is not a learned trial.');
 await poll();
 }catch(e){fail(e)}
};
$('sampleCameras').onclick=async()=>{try{const frame=await api('/api/cameras/preview',{});show(frame);say('Another bounded simulated camera setup. No training was started.')}catch(e){fail(e)}};
