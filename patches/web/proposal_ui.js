/** Explicit user requests only. Never retry a proposal or resume after disconnect. */
export function setupProposalUI({api,show}) {
 const $=id=>document.getElementById(id);
 if (!$('proposalPrepare')) return;
 let owned=null,reading=false,shown=null,broken=false;
 const words={
  idle:'Idle',checking_checkpoint:'Checking saved checkpoint',interpreting_instruction:'Interpreting instruction',
  reading_saved_policy:'Reading saved policy',proposed:'Proposed, not authorized',
  received_by_mock_pi:'Received by mock Pi, not executed',rejected:'Rejected'
 };
 function display(s) {
  const why=(s.blockers||[]).join(', ');
  $('proposalState').textContent=`${words[s.state]||s.state}. ${why}`;
  $('proposalPrepare').disabled=Boolean(s.busy);
  const e=s.evaluation,c=s.checkpoint;
  $('proposalEvidence').textContent=(c?`Saved checkpoint ${c.sha256.slice(0,16)}. Neural fingerprint ${c.fingerprint.slice(0,16)}. `:'')+
   (e?`Frozen task tests: ${e.successes}/${e.trials}; random baseline ${e.random_successes}/${e.trials}. Demonstrated: ${e.demonstrated?'yes, in simulation only':'no'}.`:'No task evidence loaded.');
  const p=s.proposal;
  $('proposalActions').textContent=p?p.actions[0].axis_order.map((name,i)=>
   `${name}: ${p.actions[0].normalized[i].toFixed(5)} normalized -> ${p.actions[0].requested_delta[i].toFixed(5)} ${p.actions[0].delta_units[i]} requested`).join('\n'):
   'No valid action proposal yet.';
  $('proposalPhysical').textContent='Input: simulated overhead + wrist images. Simulated movement: not run. Real Pi: not connected. Authorized: no. Executed: no. Physically verified: no. Physical calibration missing.';
  if(p&&s.frame&&shown!==p.proposal_id){shown=p.proposal_id;show(s.frame);}
  if(!s.busy) owned=null;
 }
 $('proposalPrepare').addEventListener('click',async()=>{
  $('proposalPrepare').disabled=true;broken=false;
  try{
   const r=await api('/api/proposal/prepare',{
    instruction:$('proposalInstruction').value,model:$('keyModel').value});
   owned=r.job_id;await poll();
  }catch(e){owned=null;$('proposalState').textContent=e.message;$('proposalPrepare').disabled=false;}
 });
 $('proposalStop').addEventListener('click',async()=>{
  owned=null;
  $('proposalState').textContent='STOP requested. This stops proposals, not the real arm.';
  try{await api('/api/proposal/stop',{});await poll();}
  catch(e){$('proposalState').textContent='Stop acknowledgement unavailable. No retry or automatic resume. '+e.message;}
 });
 async function poll(){
  if(reading||broken)return;
  reading=true;
  try{
   if(owned){try{await api('/api/proposal/heartbeat',{job_id:owned});}catch(e){owned=null;}}
   display(await api('/api/proposal/status'));
  }catch(e){
   owned=null;broken=true;$('proposalPrepare').disabled=false;
   $('proposalState').textContent='Connection lost. Proposal will not be retried or resumed. '+e.message;
  }finally{reading=false;}
 }
 // Heartbeat ownership lives only in this page, never localStorage. A reload
 // does not adopt an old job. Missing heartbeats invalidate the pending work.
 setInterval(poll,1000);
 poll();
}
