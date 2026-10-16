"""Extend the existing v11 application. Fail rather than patch unexpected source."""
from pathlib import Path
import json,hashlib,os
ROOT=Path(__file__).resolve().parents[1]/'patches'
def write(path,text):path.write_bytes(text.encode('utf-8'))
def edit(name,old,new):
    p=ROOT/name;s=p.read_text(encoding='utf-8')
    assert s.count(old)==1,(name,s.count(old),old[:70])
    write(p,s.replace(old,new))
edit('core/view_world.py','from . import world as base','from . import world as base\nfrom .learning_feedback import assess, VERSION as FEEDBACK_VERSION')
edit('core/view_world.py','self.last_discovery=np.zeros(int(n));self.last_task_reward=np.zeros(int(n))','self.last_discovery=np.zeros(int(n));self.last_task_reward=np.zeros(int(n))\n        self.last_feedback=[None]*int(n)')
edit('core/view_world.py','self.last_discovery[i]=0.;self.last_task_reward[i]=0.','self.last_discovery[i]=0.;self.last_task_reward[i]=0.;self.last_feedback[i]=None')
edit('core/view_world.py','        for i in np.where(np.all(~self._available[:,:2],axis=1))[0]:','        active=~self.episode_done\n        for i in np.where(np.all(~self._available[:,:2],axis=1))[0]:')
edit('core/view_world.py','oldq=self.q.copy();self._cached=[None]*self.n;self._previous_action=a.copy()', '''oldq=self.q.copy();oldtarget=self.targetq.copy()
        previous_phi=self.metrics()[0].copy()
        previous_held=self.pinched[np.arange(self.n),self.target_obj].copy()
        previous_lift=self.floor_clearance().copy()
        self._cached=[None]*self.n;self._previous_action=a.copy()''')
edit('core/view_world.py','''        self.last_task_reward=reward.copy();self.last_discovery[:]=0
        if self.learning_enabled:''','''        progress=self.metrics()[0]-previous_phi
        adjusted=reward.copy()
        for i in range(self.n):
            requested=oldtarget[i]+np.clip(a[i],-1,1)*base.DELTA
            # Axial wrist roll is periodic. Do not apply a false physical range.
            indices=[0,1,2,4]
            limit=bool(np.any(requested[indices]<base.LOW[indices]-1e-6) or
                       np.any(requested[indices]>base.HIGH[indices]+1e-6))
            item=assess(reward=float(reward[i]),progress=float(progress[i]),
                guard=self.guard_reason[i],fault=bool(info['fault'][i] or
                    (info['invalid_physics'][i] and not self.guard_reason[i])),
                fallen=bool(info['fallen'][i]),success=bool(info['success'][i]),
                truncated=bool(truncated[i]),was_held=bool(previous_held[i]),
                held=bool(info['grip'][i]),previous_lift=float(previous_lift[i]),
                closing_empty=bool(self.task[i]>=3 and oldq[i,4]>.15 and self.q[i,4]<=.15),
                limit=limit,active=bool(active[i]))
            self.last_feedback[i]=item;adjusted[i]=item['total_reward']
        self.returns+=adjusted-reward
        reward=adjusted;self.last_task_reward=reward.copy();self.last_discovery[:]=0
        if self.learning_enabled:''')
edit('core/view_world.py',"invalid=bool(self.physics_failures[i] or info['fault'][i] or info['fallen'][i]))", "invalid=not self.last_feedback[i]['discovery_allowed'])")
edit('core/view_world.py',"        info['discovery_bonus']=self.last_discovery.copy();info['task_reward']=self.last_task_reward.copy()", "        for i,item in enumerate(self.last_feedback):\n            item['discovery_bonus']=float(self.last_discovery[i])\n            item['total_reward']=float(reward[i])\n        info['discovery_bonus']=self.last_discovery.copy();info['task_reward']=self.last_task_reward.copy()")
edit('core/view_world.py',"info['return']=self.returns.copy()", """info['return']=self.returns.copy()
        info['failure_reason']=np.array([x['reason'] for x in self.last_feedback])
        info['feedback_penalty']=np.array([x['penalty'] for x in self.last_feedback])
        info['feedback_version']=np.array([FEEDBACK_VERSION]*self.n)""")
edit('core/view_world.py',"discovery_reward_is_skill=False)","discovery_reward_is_skill=False,learning_feedback=copy.deepcopy(self.last_feedback[i]))")
edit('core/ppo.py',"result['safety_abort']=bool(info.get('invalid_physics',np.zeros(world.n,bool))[i])", """result['safety_abort']=bool(info.get('invalid_physics',np.zeros(world.n,bool))[i])
            result['failure_reason']=str(info.get('failure_reason',['unclassified']*world.n)[i])""")
edit('core/runner.py','from .ppo import Agent,rollout','from .ppo import Agent,rollout\nfrom .learning_feedback import FeedbackLedger,update_evidence,compare_scores,VERSION as FEEDBACK_VERSION')
edit('core/runner.py',"        path=self.folder/'policy.npz'", "        self.feedback=FeedbackLedger()\n        path=self.folder/'policy.npz'")
edit('core/runner.py',"self.best_scores=extra.get('best_scores',{});self.initial=self.Agent(self.agent.seed)","self.best_scores=extra.get('best_scores',{});self.initial=self.Agent(self.agent.seed)\n                self.feedback=FeedbackLedger(extra.get('learning_feedback'))")
edit('core/runner.py',"'physics':_BACKEND_LABEL,", "'learning_feedback':self.feedback.snapshot(),'physics':_BACKEND_LABEL,")
edit('core/runner.py',"'best_scores':self.best_scores,'camera_config':self.camera_config})", "'best_scores':self.best_scores,'camera_config':self.camera_config,'learning_feedback':self.feedback.snapshot()})")
edit('core/runner.py',"            if cfg['task']!=self.config['task']:","""            # Preserve the user's exact starting point for a before/after test.
            # This is a reference copy, never an automatic replacement policy.
            if self.is_camera:
                backup=self.folder/'pre_feedback_v12.npz'
                if not backup.exists():
                    source=self.folder/'policy.npz'
                    if source.exists():
                        import shutil
                        shutil.copy2(source,backup)
                    else:self.agent.save(backup,{'camera_config':self.camera_config})
                self.agent.save(self.folder/'before_training_v12.npz',
                    {'camera_config':self.camera_config,'feedback_version':FEEDBACK_VERSION,
                     'reference_kind':'before_latest_training_run'})
            if cfg['task']!=self.config['task']:""")
edit('core/runner.py',"                if hasattr(self,'record_training_episode'):self.record_training_episode(item)", "                self.feedback.episode(item)\n                if hasattr(self,'record_training_episode'):self.record_training_episode(item)")
edit('core/runner.py',"                trace.append(world.frame())", """                if getattr(world,'last_feedback',None):
                    with self.lock:self.feedback.observe([x for x in world.last_feedback if x is not None])
                trace.append(world.frame())""")
edit('core/runner.py',"                        stats=self.agent.update(batch,epochs=4,stop=self.stop_event.is_set)\n                        if stats:self.latest_stats=stats[-1]", """                        before={k:v.copy() for k,v in self.agent.p.items()}
                        fingerprint=self.agent.signature();updates=self.agent.updates
                        stats=self.agent.update(batch,epochs=4,stop=self.stop_event.is_set)
                        self.feedback.last_update=update_evidence(self.agent,before,fingerprint,updates,len(batch[0]),stats)
                        if stats:self.latest_stats=stats[-1]""")
edit('core/runner.py',"    return {'task':task,'trials':n,'successes':k", """    reasons={}
    for r in records:
        name=str(r.get('failure_reason','success' if r['success'] else 'unclassified'))
        reasons[name]=reasons.get(name,0)+1
    return {'outcomes':[{'success':bool(r['success']),'fault':bool(r['fault']),
            'invalid_physics':bool(r.get('invalid_physics',False)),
            'reason':str(r.get('failure_reason','unclassified'))} for r in records],
        'failure_counts':reasons,'feedback_version':FEEDBACK_VERSION,
        'task':task,'trials':n,'successes':k""")
edit('core/runner.py',"            current=self.agent.clone();initial=self.initial.clone();self.status='evaluating';self.last_evaluation=None;before=current.signature()", """            current=self.agent.clone();initial=self.initial.clone();reference=initial.clone()
            reference_kind='untrained_same_model'
            path=self.folder/'before_training_v12.npz'
            if self.is_camera and path.exists():
                reference,extra=self.Agent.load(path)
                if extra.get('camera_config')==self.camera_config:
                    reference_kind='before_latest_training_run'
                else:
                    reference=initial.clone();reference_kind='untrained_camera_setup_changed'
            reference_fingerprint=reference.signature()
            self.status='evaluating';self.last_evaluation=None;before=current.signature()""")
edit('core/runner.py',"                    rows.append({'current':now,'random_actions':baseline})", """                    with self.lock:self.evaluation_progress={'phase':name+' / before-training reference','completed':index,'total':len(names)}
                    earlier=evaluate(reference,name,trials,seed+index*1000,stop=self.stop_event.is_set,
                        world_factory=self.World,world_options=self.evaluation_options(),on_trial=self._eval_trial,
                        on_timing=(lambda t,r,s,f:self.record_trial_time(t,r,s,f,label='reference'))
                            if hasattr(self,'record_trial_time') else None)
                    rows.append({'current':now,'random_actions':baseline,'reference':earlier,
                                 'learning_comparison':compare_scores(now,earlier,baseline,reference_kind)})""")
edit('core/runner.py',"'fingerprint_unchanged':before==current.signature(),'policy_fingerprint':before,'episodes_at_test':current.episodes,", """'fingerprint_unchanged':before==current.signature() and reference_fingerprint==reference.signature(),
                        'reference_fingerprint':reference_fingerprint,'reference_kind':reference_kind,
                        'feedback_version':FEEDBACK_VERSION,
                        'policy_fingerprint':before,'episodes_at_test':current.episodes,""")
edit('core/runner.py',"match=bool(evidence and evidence.get('policy_fingerprint')==self.agent.signature()", "match=bool(evidence and evidence.get('feedback_version')==FEEDBACK_VERSION and evidence.get('policy_fingerprint')==self.agent.signature()")
edit('core/runner.py',"last_save=time.monotonic();next_eval=self.agent.steps+16000", "last_save=time.monotonic();validation_interval=2048 if self.is_camera else 16000;next_eval=self.agent.steps+validation_interval")
edit('core/runner.py',"self.save();next_eval=self.agent.steps+16000", "self.save();next_eval=self.agent.steps+validation_interval")
edit('core/runner.py',"if self.config['task']=='curriculum' and val['success_rate']>=.7:", "if self.config['task']=='curriculum' and val['success_rate']>=.7 and not val['invalid_physics'] and not val['faults']:")
edit('core/runner.py',"            with self.lock:self.status='paused' if self.stop_event.is_set() else 'complete'", "            with self.lock:self.status='paused' if self.stop_event.is_set() else 'complete'\n            if self.is_camera and not self.stop_event.is_set() and self.agent.episodes-self.start_episodes>=10:\n                name=TASKS[self.stage] if self.config['task'] not in TASKS else self.config['task']\n                self.begin_evaluation(task=name,trials=5,_inline=True)")
for name in ('core/runner.py','core/session_runner.py'):
    edit(name,"def begin_evaluation(self,task='all',trials=20):","def begin_evaluation(self,task='all',trials=20,_inline=False):")
edit('core/runner.py',"        self.thread=threading.Thread(target=run,daemon=True);self.thread.start();return {'ok':True,'cloud_requests':0}", "        if _inline:run()\n        else:\n            self.thread=threading.Thread(target=run,daemon=True);self.thread.start()\n        return {'ok':True,'cloud_requests':0}")
edit('core/session_runner.py',"super().begin_evaluation(task,trials)","super().begin_evaluation(task,trials,_inline=_inline)")
edit('core/session_runner.py',"for label in ('policy','random')", "for label in ('policy','random','reference')")
edit('core/session_runner.py',"def record_trial_time(self,task,random_policy,seconds,fault_probability=0.):", "def record_trial_time(self,task,random_policy,seconds,fault_probability=0.,label=None):")
edit('core/session_runner.py',"'eval_'+('fault' if fault_probability else ('random' if random_policy else 'policy'))", "'eval_'+(label or ('fault' if fault_probability else ('random' if random_policy else 'policy')))")
edit('tests/test_run_controls_v10.py',"['remaining_trials'],290)","['remaining_trials'],430)")
edit('tests/test_run_controls_v10.py',"['remaining_trials'],1450)","['remaining_trials'],2150)")
edit('core/proposal_policy.py',"    'core/world.py', 'core/ppo.py',", "    'core/learning_feedback.py', 'core/world.py', 'core/ppo.py',")
edit('web/index.html','<section id="apiKeys"', '''<section id="mistakePanel" aria-label="Learning from mistakes">
<strong>Is Seizo learning?</strong>
<p id="mistakeMessage">No scored training step yet.</p>
<p id="mistakeUpdate">No verified optimizer update in this release yet.</p>
<p id="mistakeProof">Test all tasks compares the saved policy with its pre-training reference and random actions. Scores, not animation, determine improvement.</p>
</section>
<section id="apiKeys"''')
edit('web/index.html','v11: AI proposals only.','v12: learning feedback and AI proposals only.')
edit('web/app.js',"status=await api('/api/status');restoreSettings(status);", "status=await api('/api/status');showFeedback(status);restoreSettings(status);")
edit('web/app.js',"Testing ALL seven tasks and paired random baselines.","Testing ALL seven tasks, before-training reference and paired random baselines.")
s='''
function showFeedback(s){
 const f=s.learning_feedback,m=f?.last,u=f?.last_update;
 $('mistakeMessage').textContent=m?`${m.message} Feedback score ${Number(m.total_reward).toFixed(3)}; extra penalty ${Number(m.penalty).toFixed(3)}. Training transition ${m.transition}.`:'No scored training step recorded yet. Watch policy and tests do not train.';
 $('mistakeUpdate').textContent=u?`Latest batch: ${u.samples} real training transitions; ${u.optimizer_updates} optimizer steps. Actor parameters changed: ${u.actor.changed_parameters}. Critic parameters changed: ${u.critic.changed_parameters}. ${u.actor.changed_parameters?'Action policy updated from feedback.':'No action-policy change in this batch.'} This alone does not prove improved skill.`:'No verified optimizer update recorded in this release. Train / resume uses local rewards; a cloud reply does not train the arm.';
 const e=s.evaluation;
 const current=e?.policy_fingerprint===s.policy_fingerprint&&e?.feedback_version==='seizo-feedback/v12'&&Object.keys(s.camera_config||{}).every(k=>e.camera_config?.[k]===s.camera_config[k]);
 const rows=e?.by_task?.filter(x=>x.learning_comparison)||[];
 $('mistakeProof').textContent=rows.length?(current?'Current frozen results. ':'Historical results, not current proof. ')+rows.map(x=>{const c=x.learning_comparison;return `${c.task}: before ${c.reference_successes}/${c.trials}, now ${c.current_successes}/${c.trials}, random ${c.random_successes}/${c.trials}. ${c.state.replaceAll('_',' ')}.`}).join(' '):'No before/after skill proof yet. Test all tasks runs frozen comparisons. Select 20 trials in settings for a meaningful first check; a one-trial quick test is not proof.';
}
'''
p=ROOT/'web/app.js';write(p,p.read_text(encoding='utf-8')+s)
for name in ('app.py','tests/test_camera_release.py','tests/test_proposal_release.py','tests/test_proposal_assets.py','tests/browser_proposal_bridge.py'):
    p=ROOT/name;write(p,p.read_text(encoding='utf-8').replace('seizo-proposal-bridge-v11','seizo-learning-feedback-v12'))
p=ROOT/'tests/preserved_source_hashes.json';h=json.loads(p.read_text(encoding='utf-8'))
for name in ('core/runner.py','core/ppo.py'):h[name]=hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
write(p,json.dumps(h,indent=2)+'\n')
write(ROOT/'START_HERE.txt','''Seizo v12: mistake feedback and measured learning

END RUN & SAVE. Wait for Saved, close the terminal, and reopen your
existing START_SEIZO.bat with internet. Confirm seizo-learning-feedback-v12.
No new launcher or training reset. Your camera_views_v9 policy is preserved.

Train / resume uses bounded penalties for blocked actions, dropped objects,
empty grasps, limit requests and expired attempts. Moving away from the task
cannot earn a novelty bonus. No corrective motor script replaces the policy.

Is Seizo learning? shows the last failure, the feedback score, and measured
actor/critic parameter changes after a real optimizer batch. Updates alone
are not proof of skill. Completed runs of at least 10 episodes automatically
run a 5-trial comparison on the current lesson, plus a random baseline and
fault trials. Small tests are explicitly not proof. Test all tasks with
20 trials for fuller comparisons against the pre-training reference.
Before each training run a reference copy is saved. The first v12 training
run also preserves the previous checkpoint in pre_feedback_v12.npz.

Watch policy and Test all tasks are frozen tests; they do not learn.
The Hack Club chat model interprets tasks; local PPO learns the controls.
This release does not certify learned task success or fix unmeasured geometry.
REAL ARM LOCKED. No physical Pi, serial, GPIO or motor connection.
''')
repo=ROOT.parent
old=json.loads((repo/'desktop_manifest.json').read_text(encoding='utf-8'));entries={}
for name,value in old['patches'].items():
    if not name.startswith('tests/'):entries[name]=dict(value)
entries['core/learning_feedback.py']={}
for name in entries:
    entries[name]={'url':'https://raw.githubusercontent.com/gmaxdragon/seizo/'+os.environ['GITHUB_SHA']+'/patches/'+name,
                   'sha256':hashlib.sha256((ROOT/name).read_bytes()).hexdigest()}
manifest={'schema':old['schema'],'version':'2026.10.16-learning-feedback-v12','base':old['base'],'patches':entries}
assert len(entries)<=80
write(repo/'release-candidate-manifest.json',json.dumps(manifest,separators=(',',':'))+'\n')
write(repo/'feedback-source-hashes.json',json.dumps({p.relative_to(repo).as_posix():
    hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(ROOT.rglob('*')) if p.is_file() and '__pycache__' not in p.parts},indent=2)+'\n')
