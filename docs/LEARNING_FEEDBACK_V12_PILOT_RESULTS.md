# V12 pilot evidence, including failure

This is a development audit, not Vivaan Goel's laptop checkpoint.

Run 38958919489 (code 94f3b903fe99d6bf3c96fcd700833a38477dadd6) passed software checks but did NOT establish skill. Actual camera training: 128 transitions, 8 optimizer steps, zero completed training episodes. Three full held-out reach trials: before 0/3, after 0/3, random 0/3. Guard aborts rose from 0/3 to 3/3 after the update. Mean terminal distance changed from 152.536 to 157.055 simulated mm. Return increased from -3.543 to -1.628 despite worse guard behavior. This is specifically NOT labelled improved learning.

The early-abort score was too small compared with a full idle attempt. The revised candidate gives guard and workspace-escape transitions a total score of at most -8, rather than -1, with no novelty bonus. This closes that specific cheaper-early-ending comparison, not every possible reward exploit. Defined errors are still not a universal physical safety detector.

The follow-up audit uses a fresh, precommitted held-out seed 1940031, retains original 220-step task criteria, and collects at least two complete training episodes, bounded at 512 real transitions. Results must be taken from its completed JSON, including any failures. Do not select a seed or alter a score to manufacture success. The first audit remains part of the evidence.

The first attempt, run 38957500209, also remains a failed attempt: a test expected two full camera episodes within 100 seconds, and the experiment spent its training time budget on baseline evaluation before collecting any training data. No successful learning was claimed from that run. The lifecycle check now deliberately exercises one real eight-transition optimizer batch followed by STOP/save, and is labelled a short lifecycle check rather than a completed skill experiment.

All of this is simulated. The physical robot remains locked. No test-trained model is distributed or substituted for the user's saved weights.
