# Seizo v12 release: error feedback works; useful reaching remains unproven

Date: October 16, 2026. Project owner: Vivaan Goel.

## Released source

The stable seizo-desktop branch was advanced with an expected-head check from 2fe70580c40db4b56bbb79e7ba2a40e831eb1c16 to 33d730564ae656a57a51c068148d4d34b0af67fc and read back. The manifest is 2026.10.16-learning-feedback-v12. App label: seizo-learning-feedback-v12. Existing START_SEIZO.bat remains the launcher.

Immutable runtime source: 6e8729ad106cca8c991cd287b949284cbab118b8. Tested staging commit: fa3125ba3875626ffb996162351ed060cb47e1f0. Dedicated successful workflow: https://github.com/gmaxdragon/seizo/actions/runs/38960312919

This is a release of no-motion training feedback and diagnostics, NOT a claim that the arm has mastered a task.

## What changed

The camera simulator now emits explicit events and training scores for blocked clearance/penetration actions, out-of-workspace objects, dropped airborne grasps, completed empty grasps, requests past existing simulator joint limits, reduced task progress, and unsuccessful timeouts. Sensor/physics faults are separately labelled. This detects defined simulator conditions, not every possible mistake or real-world hazard.

Those scores enter the original on-policy rollout, GAE and PPO update. Errors cannot collect the novelty movement bonus. No scripted corrective controller or teacher action replaces the learner. Physical geometry, camera observation layout, action mapping and PPO optimizer mathematics remain unchanged.

The pilot exposed a cheaper-early-abort loophole. Guard/workspace-escape transitions now have a total score of at most -8, rather than -1. This is worse than the full idle attempt's time cost. The unit test verifies that specific comparison. It is not proof that every possible reward exploit is removed.

The new Is Seizo learning? panel displays the last scored event, score and penalty, actual actor/critic parameter changes, and frozen before/current/random task results. Increased guard-abort counts remain visible even when success counts are unchanged. Old evaluations lacking the feedback version are labelled historical.

An exact first-v12 checkpoint backup is preserved as pre_feedback_v12.npz. Before each training run, before_training_v12.npz records the current policy for comparison. Compatible v9 camera weights, optimizer state and saved progress are retained; no test model or replacement policy is distributed.

Completed uninterrupted training runs of at least ten episodes automatically request a five-trial comparison for the current lesson. It remains explicitly small-sample evidence. Test all tasks supports larger frozen comparisons, including the actual pre-training reference and a paired random baseline. STOP remains latched during automatic comparisons. Watch policy and tests do not update weights. The evaluation timing budget includes the extra reference trials.

## Actual final camera experiment

This used a SEPARATE test policy initialized from scratch, not Vivaan's laptop checkpoint. Images were actually rendered by the original MuJoCo camera pipeline. No fabricated success scores, scripted teacher or live cloud call was used.

Training seed: 41723. Fresh held-out seed: 1940031, precommitted after the earlier pilot. Task: reach. Two mounted camera views. Original full 220-step task criteria were retained.

| Measurement | Observed result |
| --- | --- |
| Actual training transitions | 192 |
| Completed training episodes | 2 |
| Optimizer update steps | 12 |
| Held-out reach successes before training | 0 / 3 |
| Held-out reach successes after training | 0 / 3 |
| Paired random-action successes | 0 / 3 |
| Guard aborts before training | 0 / 3 |
| Guard aborts after training | 3 / 3 |
| Mean final target distance before | 115.161 simulated mm |
| Mean final target distance after | 135.452 simulated mm |
| Mean return before | -3.384 |
| Mean return after | -8.628 |
| Experiment wall time | 345.565 seconds |

The final training batch contained 64 real transitions and four optimizer steps. It changed 1,332,362 actor parameters and 1,332,094 critic parameters; parameters remained finite. The training ledger recorded two actual unsafe-action endings, seven joint-limit events and 97 reduced-progress events. Event counts can overlap on one transition.

Conclusion: the reward-to-update path is real, but this short experiment DID NOT demonstrate a useful reaching skill. Guard performance became worse in the observed sample. The revised score correctly rates the bad ending below idle behavior; it did not instantly fix the learned behavior. Three trials and two training episodes do not establish reliability, nor determine the quality of the user's separate saved checkpoint. No mastery or physical-transfer claim is made.

## Earlier failures retained

Pilot run 38958919489: 128 transitions, eight optimizer steps, zero completed training episodes; 0/3 reach successes before and after, with guard aborts rising from 0 to 3. Its higher mean return despite worse guard behavior motivated the terminal-cost correction. Both pilot and final results are retained. The differing seed, training length and reward mean these are not a controlled reward-ablation comparison.

Initial run 38957500209 also failed: a two-full-episode smoke exceeded 100 seconds, and the experiment's budget was consumed by baseline evaluation before training. No successful learning claim was made from that run. The lifecycle smoke now explicitly tests one real eight-transition optimizer batch followed by STOP/save. It is not labelled two completed episodes or a skill benchmark.

## Executed software validation

| Check | Result |
| --- | --- |
| Linux full application suite | 254 tests, 253 passed, one native-Windows skip; 223.419 seconds |
| Windows proposal/updater suite | 70 tests, 69 passed, one MuJoCo-rendering skip; 21.266 seconds |
| Windows feedback suite | 27 tests, 22 passed, five MuJoCo-dependent skips; 0.549 seconds |
| Windows credential suite | 17 tests, 16 passed, one non-Windows skip; 0.115 seconds |
| Actual Chromium learning-feedback UI | Passed, real eight-transition training and actual frozen scores |
| Existing mock-Pi browser integration | Passed; its intent/passing-score fixtures remain explicitly synthetic |

Controlled optimizer tests verified that negative feedback reduced the penalized action's relative likelihood and reversed feedback reversed that change. These controlled inputs establish update direction, not camera-task mastery.

The new browser test showed before 0/1, current 0/1 and random 0/1, labelled small sample not proof. Those are actual simulated outcomes, not fixture scores. It showed the real actor update count and guard counts. No JavaScript errors were observed. The separate mock-Pi browser STOP acknowledgement took 0.067394 seconds on its runner while the mocked provider remained blocked.

Linux used MuJoCo 3.3.7 and CPU software OpenGL. Windows did not validate native interactive graphics. No live Hack Club API request was made in CI; provider parsing and failure handling use synthetic responses. The user's live API key, local GPU and current checkpoint performance were not inspected. Local PPO learning is separate from the Hack Club model used for task interpretation.

## Independent package checks and preservation

Returned candidate archive SHA256: 06fd9d0ad54e14a1c9e347d46c3986368fe56a6a8777816923b3713aabaa0182. Its 89 source hashes matched the Linux, Windows and experiment records. The locally reconstructed Git patches tree matched b6d6d5abf8b747cc92c1cf009af555f72ec0856d. All 63 Python files compiled. Manifest and proof Git blob hashes matched the committed tree.

The 49 runtime manifest entries point to the immutable source commit and satisfy the original updater's 80-file limit. Test-only files remain in GitHub/CI rather than consuming runtime manifest slots. A local isolated install/relaunch test with the exact original updater preserved checkpoint, evaluation, settings and environment sentinel bytes, then reconstructed the three original fixed assets byte-identically. These are test installations, not an inspection of the user's laptop.

Physical SeizoOfficial/main was read back unchanged at 3bcaba531a67997f9689d5aae008de4972096e71. No physical Pi, servo, stepper, serial/GPIO, firmware, HAT, Railway or PEAC change occurred. REAL ARM LOCKED remains visible. Even passing simulator tests cannot authorize physical movement. The October 16 marker-placement record remains intact; no physical marker transform or travel limit was inferred or changed.

The dedicated workflow passed. Unrelated legacy repository CI is not claimed green.

## Install and inspect your actual saved policy

END RUN & SAVE. Wait for Saved. Close the old terminal. Reopen the existing START_SEIZO.bat with internet and confirm seizo-learning-feedback-v12. Do not reset or delete training data.

For a bounded first diagnostic, select Reach and a ten-episode budget, then let the run finish and inspect the automatic comparison. It checks the saved policy on that machine against its own pre-training reference. Read successes and guard aborts, not just weight counts. A small quick check remains provisional; larger frozen tests are needed for stronger evidence. No claim is made that ten episodes will teach the task.
