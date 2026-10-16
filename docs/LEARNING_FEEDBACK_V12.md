# Seizo v12: explicit mistakes and falsifiable learning evidence

Owner: Vivaan Goel. Extends desktop v11 and preserves the October 16 marker-placement correction. No physical SeizoOfficial, HAT, GPIO, serial, motor, Railway or PEAC changes.

## What was missing

The existing PPO optimizer genuinely used rewards and changed network weights. That was not evidence of useful manipulation skill. The camera wrapper did not make every guard/failure an explicit negative reward, and its novelty bonus could reward movement that reduced task progress. The existing full evaluator compared the current policy with random actions but did not compare it with the actual policy before the latest training run.

## Implemented changes

- Versioned simulator feedback: blocked clearance/penetration actions, lost airborne grasps, completed empty closes, out-of-range requests, out-of-workspace objects and unsuccessful timeouts. Existing progress reward stays in place. Desired object contact is not blanket-penalized. Sensor/physics faults are distinguished from bad decisions. These are defined simulator events, not a universal mistake detector or real-camera classifier.
- Bounded penalties go into the same on-policy rollout, GAE and existing PPO optimizer. The novelty bonus is suppressed for these errors and for reduced task progress. No teacher/controller overrides a policy action. Old failures are not replayed as though they were fresh PPO samples.
- After each batch, measure actor and critic parameter changes separately, update counts, sample count, fingerprints, finite values and loss diagnostics. The UI says a policy changed only when it did, and never equates parameter change with skill.
- Keep an exact first-v12 checkpoint backup and a pre-training policy reference. Existing compatible v9 observation shape, model ID and weights are retained. No reset or pretrained replacement. The optimizer mathematics, geometry, physical limits and camera definitions are unchanged.
- Test all tasks now evaluates current policy, the pre-training reference (or explicitly labelled untrained reference), and paired random actions on matching held-out seeds. Store every outcome and failure reason. Report improved, regressed, unchanged or inconclusive, with small samples explicitly not proof. The exact paired success test is per task, unadjusted, and not independent replication or hardware certification.
- Completed uninterrupted training runs of at least ten episodes automatically run a five-trial comparison for the current lesson, plus random and fault trials. These quick checks are intentionally labelled small-sample evidence. STOP cancels them and is never cleared by an automatic comparison. Periodic current-policy validation starts after 2,048 camera training steps instead of 16,000 and uses fresh random seeds.

## Boundaries

The software cannot guarantee every mistake is identified or eliminated after one update. Policy-gradient learning changes probabilities, not a promise never to repeat an error. Poor success scores are retained, not replaced or hidden. A successful feedback/optimizer unit test is not a manipulation benchmark.

A separate bounded camera experiment uses real rendered RGB, the original encoder/policy/optimizer and disjoint training/test seeds. Its scores must be read from the completed workflow artifact; no score is asserted here before it runs. It starts a separate test policy and never uses, replaces or claims to inspect Vivaan's laptop checkpoint. The live Hack Club key is not used. Existing mock-Pi browser tests still use explicit synthetic fixtures; the new learning experiment and learning-feedback browser test do not fabricate success outcomes.

## Delivery

Publish only after the dedicated Linux/Windows, original-updater, browser and real-experiment checks complete, preserving all observed failures in the report. Use the same START_SEIZO.bat channel. The manifest remains compatible with the original 80-file updater and fixed JSON asset envelope; runtime downloads omit test-only files, which remain in GitHub/CI. No model checkpoint, key, test-trained weights or private photo is bundled.

Expected app label: seizo-learning-feedback-v12. Release manifest: 2026.10.16-learning-feedback-v12. Real arm remains locked. A desktop release is not physical commissioning.

## Primary methodology references

- Schulman et al., Proximal Policy Optimization Algorithms, 2017: https://arxiv.org/abs/1707.06347
- Stable Baselines3, Reinforcement Learning Tips and Tricks, retrieved October 16, 2026: https://stable-baselines3.readthedocs.io/en/master/guide/rl_tips.html

These support on-policy reward learning and separate evaluation. They do not validate this implementation or its physical transfer; the saved execution evidence must do that.
