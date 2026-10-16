"""Observable simulator mistakes, bounded rewards, and honest learning comparisons.

Reward/scoring may use simulator truth. This module adds NO actor/critic inputs,
physical I/O, teacher actions, replay buffer or cloud-model fine-tuning.
"""
from __future__ import annotations
import copy
import math
from collections import Counter
import numpy as np

VERSION = 'seizo-feedback/v12'
MESSAGES = {
    'unsafe_action': 'The simulator blocked this action at a clearance/penetration guard.',
    'dropped_object': 'The object was held above the floor and then lost its grip.',
    'empty_grasp': 'The jaws finished closing without holding the selected object.',
    'joint_limit': 'The requested increment exceeded an existing simulator joint limit.',
    'task_score_decreased': 'Task progress decreased. Exploration can still require some setbacks.',
    'time_limit': 'The attempt used its move budget without completing the task.',
    'object_out_of_workspace': 'The selected object left the simulated workspace.',
    'sensor_or_physics_fault': 'Sensor/physics fault. This is not proof of a bad learned decision.',
    'success': 'The existing sustained task-success criteria were met in simulation.',
    'progress': 'The action improved the existing task score.',
    'no_progress': 'No meaningful improvement in the task score on this step.',
}


def assess(*, reward, progress, guard='', fault=False, fallen=False, success=False,
           truncated=False, was_held=False, held=False, previous_lift=0.,
           closing_empty=False, limit=False, active=True):
    """One scored transition. Existing progress reward is retained, not counted twice.

Failure penalties do not manufacture a corrective action. PPO sees this reward
on its own sampled transition and updates the policy in the next optimizer batch.
"""
    if not all(math.isfinite(float(x)) for x in (reward, progress, previous_lift)):
        raise ValueError('Non-finite feedback measurement')
    if not active:
        return {'version': VERSION, 'events': [], 'reason': 'inactive', 'penalty': 0.,
                'base_reward': 0., 'total_reward': 0., 'discovery_allowed': False,
                'message': 'Attempt already ended; no new transition.'}
    events=[];penalty=0.
    fault=bool(fault or (guard and guard not in ('table-clearance guard','excess penetration guard')))
    if fault:
        events=['sensor_or_physics_fault']
        # Do not attribute injected or sensor faults to a learned motor choice.
        reward=min(float(reward),0.)
    elif guard:
        events=['unsafe_action'];penalty=-8.
    elif fallen:
        events=['object_out_of_workspace'];penalty=-8.
    elif success:
        events=['success']
    else:
        if was_held and not held and previous_lift>15.:
            events.append('dropped_object');penalty-=.5
        if closing_empty and not held:
            events.append('empty_grasp');penalty-=.10
        if limit:
            events.append('joint_limit');penalty-=.04
        if progress < -.005:events.append('task_score_decreased')
        if truncated:
            events.append('time_limit');penalty-=.25
        if not events:events=['progress' if progress>.005 else 'no_progress']
    # The novelty bonus must not turn a mistake into a rewarded exploration step.
    allowed=(events[0] in ('progress','no_progress') and not truncated)
    total=float(reward)+penalty
    if any(e not in ('success','progress','no_progress','sensor_or_physics_fault') for e in events):
        total=min(total,-8. if events[0] in ('unsafe_action','object_out_of_workspace') else -.015)
    reason=events[0]
    return {'version': VERSION, 'events': events, 'reason': reason,
            'penalty': float(total-float(reward)), 'base_reward': float(reward),
            'total_reward': total, 'discovery_allowed': allowed, 'message': MESSAGES[reason]}


class FeedbackLedger:
    """Small bounded statistics. Not an off-policy training replay buffer."""
    def __init__(self, saved=None):
        self.steps=0;self.counts=Counter();self.last=None;self.last_update=None;self.episodes=[]
        if isinstance(saved,dict) and saved.get('version')==VERSION:
            self.steps=int(saved.get('steps',0));self.counts=Counter(saved.get('counts',{}))
            self.last=saved.get('last');self.last_update=saved.get('last_update')
            self.episodes=list(saved.get('episodes',[]))[-100:]
    def observe(self, items):
        for item in items:
            if item.get('reason')=='inactive':continue
            self.steps+=1;self.counts.update(item['events']);self.last=copy.deepcopy(item)
            self.last['transition']=self.steps
    def episode(self,item):
        self.episodes.append({k:item.get(k) for k in ('episode','task','success','fault','fallen','safety_abort','failure_reason')})
        self.episodes=self.episodes[-100:]
    def snapshot(self):
        return {'version':VERSION,'steps':self.steps,'counts':dict(self.counts),
                'last':copy.deepcopy(self.last),'last_update':copy.deepcopy(self.last_update),
                'episodes':copy.deepcopy(self.episodes),'physical_motion':False,
                'note':'Feedback is used only in local PPO training. Frozen tests do not learn.'}


def update_evidence(agent, before, fingerprint, updates, sample_count, stats):
    groups={}
    for label,prefix in (('actor','p'),('critic','v')):
        keys=[k for k in agent.p if k.startswith(prefix) or (label=='actor' and k=='logstd')]
        changed=sum(int(np.count_nonzero(agent.p[k]!=before[k])) for k in keys)
        delta=math.sqrt(sum(float(np.sum((agent.p[k].astype(np.float64)-before[k])**2)) for k in keys))
        groups[label]={'changed_parameters':changed,'l2_change':delta}
    return {'before_fingerprint':fingerprint,'after_fingerprint':agent.signature(),
            'optimizer_updates':agent.updates-updates,'samples':int(sample_count),
            **groups,'finite':all(np.isfinite(v).all() for v in agent.p.values()),
            'stats':dict(stats[-1]) if stats else {},
            'weights_updated':fingerprint!=agent.signature(),
            'skill_improvement_proven':False,'physical_motion':False}


def compare_scores(current, reference, random_baseline, reference_kind):
    """Paired held-out success outcomes. Reward increase alone never proves skill."""
    n=current['trials']
    if any(row.get('trials')!=n or row.get('seed')!=current['seed'] or
           row.get('task')!=current['task'] for row in (reference,random_baseline)):
        raise ValueError('Learning comparison needs paired tasks, counts and seeds')
    before=reference.get('outcomes',[]);after=current.get('outcomes',[])
    if len(before)!=n or len(after)!=n:raise ValueError('Per-trial evidence missing')
    wins=sum(not b['success'] and a['success'] for b,a in zip(before,after))
    losses=sum(b['success'] and not a['success'] for b,a in zip(before,after))
    discordant=wins+losses
    p=min(1.,2.*sum(math.comb(discordant,k) for k in range(min(wins,losses)+1))/2**discordant) if discordant else 1.
    if n<20:state='small_sample_not_proof'
    elif wins>losses and p<=.05 and current['invalid_physics']<=reference['invalid_physics']:
        state='improved_on_paired_test'
    elif losses>wins and p<=.05:state='regressed_on_paired_test'
    elif not discordant:state='no_success_change_detected'
    else:state='inconclusive'
    return {'state':state,'task':current['task'],'trials':n,'reference_kind':reference_kind,
            'reference_successes':reference['successes'],'current_successes':current['successes'],
            'random_successes':random_baseline['successes'],'paired_wins':wins,'paired_losses':losses,
            'paired_exact_p_two_sided':p,'success_change':(wins-losses)/n,
            'mean_error_before_mm':reference['mean_error_mm'],'mean_error_after_mm':current['mean_error_mm'],
            'physics_aborts_before':reference['invalid_physics'],'physics_aborts_after':current['invalid_physics'],
            'safety_observation':('more_guard_aborts_observed' if current['invalid_physics']>reference['invalid_physics'] else 'fewer_guard_aborts_observed' if current['invalid_physics']<reference['invalid_physics'] else 'same_guard_abort_count'),
            'mastery_claim':False,'physical_validation':False,
            'qualification':'One task/test batch, unadjusted per-task test. Not independent replication or hardware validation.'}
