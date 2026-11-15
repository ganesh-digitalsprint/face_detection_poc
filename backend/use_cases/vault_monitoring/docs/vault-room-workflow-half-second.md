# Workflow confirmation: 1.0 to 0.5 seconds

## Applied change and effective worker configuration

Only the production YAML value `vault_room.workflow.confirmation_seconds` changed
from **1.0 to 0.5 seconds**. No workflow algorithm was redesigned.

| Worker setting | Effective value |
| --- | --- |
| workflow.confirmation_seconds | **0.5** |
| workflow.min_observations | 3 |
| workflow.exit_confirmation_seconds | 0.5 |
| workflow.exit_min_observations | 3 |
| workflow.dropout_tolerance_seconds | 0.5 |
| wrist_interaction.confirmation_seconds | 1.0, unchanged |
| wrist visibility/presence threshold | 0.5 each, unchanged |
| Vault Area body confirmation / reference | 1.0 s / bottom_center, unchanged saved profile |

Replay workers inherit their parent manager's cached configuration. The idle main
backend was therefore reloaded, with its existing environment preserved, rather
than assuming a new replay alone would invalidate that cache. A new validation
listener/worker also loaded the YAML afresh. Its actual configuration and frame
debug snapshots were asserted to contain 0.5 seconds on **all 120 sampled frames**.
Existing optional diagnostics were enabled only in the validation process; the
saved diagnostics flag remains false.

## New replay and complete persisted results

Recording: `temp/vault_monitoring_hand_raise_updated_25s.mp4`.
SHA-256: `be7a0e0781991302efc232ab9553bdf9cf048a89542ab3f30d5ec6d28c3debde`.
1280 x 720, 24 FPS, 599 source frames / 24.958333 seconds.

New session: **`460e8a0cd75746da9af0b361d34834d9`**.
Baseline 1.0-second session: `f2260c224e384a568af44c7de16f16ea`.

The entire recording finished: 120 sampled frames, final source time 24.791667,
`completed`, `finalized: true`. All six activity-write ledger entries were
PERSISTED before the final API verification. Wall time was approximately 189
seconds including initialization, diagnostics, polling and pause; it is not used
for confirmation or the six-minute timer.

| Event | Before | After | Source time | Result / rejection reason |
| --- | ---: | ---: | --- | --- |
| PERSON_DETECTED | 2 | 2 | 1.250 s | Unchanged confirmed tracks 1 and 2 |
| PERSON_ENTERED | 1 | 1 | 1.250 s | Unchanged two-person presence |
| SESSION_STARTED | 1 | 1 | 1.250 s | Unchanged simulated authorization |
| VAULT_AREA_INTERACTION | 1 | 1 | 2.708333 s | Existing wrist threshold remains 1.0 s |
| First VAULT_DOOR_INTERACTION | 1 | 1 | **15.208333 -> 14.791667 s** | Same eligible Door episode confirms earlier |
| ORNAMENT_AREA_INTERACTION | 0 | 0 | None | Reliable Ornament membership occurs before eligible Door; none afterward |
| First TRAY_INTERACTION | 0 | 0 | None | Valid Tray observations exist, but missing ordered Ornament stage blocks them |
| Second VAULT_DOOR_INTERACTION | 0 | 0 | None | Stage 7 never becomes eligible |
| Second TRAY_INTERACTION | 0 | 0 | None | Stage 8 never becomes eligible |
| VAULT_AREA_ENTERED | 0 | 0 | None | Body references remain outside cabinet ROI; unchanged |

The original five non-workflow records retain identical source timestamps, track
IDs, ROI IDs and evidence checksums. Door count remains one; the lower threshold
correctly changes its timestamp/evidence instead of creating an extra copy at the
old timestamp. Every event in the new session has a unique ID.

New Door event: `d43f1989-2f0b-5d15-86ca-bfb7adf95db6`, Track 1/right wrist,
stage 4, `vault_door_roi`, source 14.791667 s. Confirmation used **four observations
over 0.625 seconds**, visibility 0.911374 and presence 0.995121, wrist
`(0.722372, 0.562537)`. At the existing approximately 4.8 FPS sampling, the third
sample spans only 0.416667 s; the fourth is the first to satisfy 0.5 s. This is
normal source-frame quantization, not a change to `min_observations`.

Its evidence checksum is
`06fded7aed3fae943f95a79c4e5636d12164606c39aac67d0b89163e2c01aade`.
The event-time debug frame was inspected: the reliable wrist is inside Door and
Vault, outside Ornament, with Door selected as the more specific region. The
description continues to mark the physical operation unverified.

## Actual reliable wrist-to-ROI timeline

These are contiguous runs of **current reliable** observations for operator Track
1. Missing/unreliable observations are not filled or counted as positive. All
times are source-video seconds; coordinates use the unchanged profile version 4.

| ROI | Right wrist inside | Left wrist inside |
| --- | --- | --- |
| Vault Area | 1.667–17.083; 18.750–20.208 | 20.417–21.667 |
| Vault Door | 1.667–9.167; 11.042–17.083 | None |
| Ornament Area | **1.667–6.042; 7.917–9.167** | None |
| Tray Area | **9.375–13.958; 18.750–20.208** | None |

### What blocks the sequence

1. At the existing Vault confirmation at 2.708333 s, the right wrist is already
   continuously inside overlapping Vault/Door/Ornament regions. The next Door
   stage cannot reuse that held episode. Its right-wrist exit gate remains set
   until **10.000 s**, after the required genuine outside interval and samples.
   Lowering confirmation duration does not change this exit requirement.
2. Door membership resumes at 11.041667 s, but the wrist is also inside the smaller
   Tray ROI. `MORE_SPECIFIC_REGION_TRAY_AREA_ROI` suppresses Door through 13.958333 s.
   Tray itself cannot advance because the expected stage is still Door.
3. Door-only eligible observations begin at **14.166667 s**. Samples at 14.375,
   14.583333 and 14.791667 reach the new threshold. Door confirms at 14.791667 s,
   rather than waiting for the original sixth sample at 15.208333 s.
4. The Ornament stage then becomes eligible, but **neither wrist has a reliable
   Ornament-inside observation afterward**. Pending Ornament duration/sample count
   stay zero. Across the remaining sampled frames the exact reasons are
   `WRIST_OUTSIDE_EXPECTED_REGION` (41) and `NO_RELIABLE_CURRENT_WRIST` (7).
   An exit gate is not the continuing blocker for Ornament; the required
   current ROI membership is absent.
5. Later right-wrist Tray membership at 18.750–20.208 s is long enough for a local
   0.5-second interaction, but the strict workflow is still waiting for Ornament.
   It cannot emit Tray and skip stage 5. The subsequent Door and Tray stages
   are never evaluated as eligible stages.

**Strict ordering blocks otherwise valid earlier Ornament/Tray observations and
the later Tray episode. Overlap/episode gates delay the first Door stage.** The
selected wrist does not remain inside all regions for the entire recording:
it genuinely exits Door, but the useful Ornament observations have already ended.
Changing duration alone cannot reorder those observations.

The recording's visible actions/captions are not triggers. The actual saved
polygons contain reliable Ornament/Tray wrist observations in the windows above,
but not in the required eligible order. No event was backdated, fabricated,
automatically skipped, or created from a cached wrist.

## Reviewable diagnostics and API snapshot

- [120-frame CSV](diagnostics/vault-workflow-0.5-460e8a0c.csv)
- [Complete six-event persisted list and loaded configuration](diagnostics/vault-workflow-0.5-460e8a0c-events.json)

The CSV records source frame index/sequence/time, actual workflow operator,
current left/right coordinates and visibility/presence/reliability, all four
memberships, dominant ROI, evaluated/next stage, expected ROI, gates, pending
duration/sample counts before and after evaluation, confirmation-frame counts,
emitted/persisted event metadata, and the exact rejection/transition reason.
`analyzed_track_id` identifies the final selected operator for pre-selection
diagnostics; `workflow_operator_id` stays blank until the workflow actually selects
that track. Blank coordinates mean no current matched observation, not a reused
last-known wrist. Membership is null for unreliable observations.

The complete list was retrieved through the existing session activity API. The
main backend's filtered API also returned the same six records, and all six JPEGs
were retrieved successfully. There were no duplicate IDs, replay alerts, or
production authorization/security-alert rows for this test. The final worker
reported the same 0.5-second configuration, simulated authorization, and correct
source-time timer. Saved profile data and every frame's polygon snapshot matched
before/after the run.

## Additional changes and regression tests

No workflow trigger bug was found, and **no workflow redesign was applied**.
The missing stages are data/order/overlap constraints, not failures to commit
events. To produce a different ordered result from this recording would require
a reviewed event/stage policy change or approved ROI/event-definition changes;
reducing this threshold cannot provide the absent eligible Ornament evidence.
For example, independently recording out-of-order observed interactions without
advancing the ordered workflow would be a policy change, not this threshold fix.
No such change, stage skip or polygon adjustment was made.

**90 backend tests passed**, including a new regression that reads the actual
YAML configuration, checks the retained exit/dropout/wrist values, and requires
three current positive observations spanning 0.5 s. Existing overlap, stale-wrist,
exit/re-entry, source-time, deduplication, evidence, live-parent isolation and
other monitoring regression tests remained passing. No frontend implementation
changed, so no frontend rebuild was required for this task. Existing ByteTrack
deprecation warnings remain.

Files changed for this task:

- `config/models.yaml` — only the workflow confirmation value.
- `tests/test_vault_workflow.py` — loaded-value/three-observation regression.
- `docs/vault-room-workflow-half-second.md` — this report.
- `docs/diagnostics/vault-workflow-0.5-460e8a0c.csv` — sampled-frame diagnostics.
- `docs/diagnostics/vault-workflow-0.5-460e8a0c-events.json` — persisted API results.

Paths above are relative to `backend/use_cases/vault_monitoring`. Runtime reload
updated ignored launcher metadata/logs. No wrist/body threshold, confidence,
model, saved geometry, stage algorithm, live Vault, Entrance, Grill Gate or
production alert implementation was modified.
