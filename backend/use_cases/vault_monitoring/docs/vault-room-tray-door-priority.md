# Replay Tray/Door overlap and repeated-interaction audit

## Verified cause at 11.666667 seconds

The evidence shows Track 1's right hand at the tray on top of the vault.
The saved upload profile version 5 was used unchanged, including the user-drawn
Door Handle exclusion. All four reliable samples of the old Door confirmation
window were inside both the Door and Tray polygons:

| Source time | Wrist x | Wrist y | Visibility | Presence | Door | Tray |
| --- | --- | --- | --- | --- | --- | --- |
| 11.041667 | 0.765125 | 0.235806 | 0.926430 | 0.935464 | Inside | Inside |
| 11.250000 | 0.764989 | 0.236471 | 0.922113 | 0.935781 | Inside | Inside |
| 11.458333 | 0.764881 | 0.236584 | 0.920762 | 0.935247 | Inside | Inside |
| 11.666667 | 0.764773 | 0.236989 | 0.922203 | 0.939075 | Inside | Inside |

The old monitor counted those four overlapping samples for 0.625 seconds and
emitted Door. This is a verified spatial overlap error, not a missing event write.

## Targeted change

For the same reliable tracked wrist, membership in both Door and Tray now clears
Door pending confirmation and exit samples with reason `TRAY_AREA_PRIORITY`.
Tray continues evaluating normally. An already-fired Door latch is retained:
overlap is not fabricated exit evidence. Door remains eligible outside Tray,
using fresh positive samples, and confirmed physical ROI exit/re-entry still
allows subsequent episodes. Another wrist or track inside Tray cannot suppress
this wrist's Door interaction.

There is no workflow order, previous-event prerequisite, global event limit,
cooldown or change to the 0.5-second / three-observation confirmation settings.
The existing Door Handle exclusion for Ornament is unchanged.

## Ornament repeat audit

Both Ornament events use Track 1/right wrist. The 3.750-second evidence shows
the open cabinet and hand in its interior; the 8.541667-second evidence shows
the operator holding the tray near the cabinet. They are distinct confirmed
spatial ROI episodes, not repeated emissions during one continuous membership:

- First confirmation: four reliable inside samples, 3.125–3.750 seconds.
- Eight reliable outside samples: 6.250–7.708333 seconds (1.458333 seconds).
  Exit confirms at 6.875 seconds after four samples spanning 0.625 seconds.
- Outside points stay near `(0.6823, 0.7049)` with visibility about 0.939 and
  presence about 0.970. Their minimum normalized distance from the polygon
  boundary is 0.050888, well beyond the existing 0.002 boundary tolerance.
- Re-entry: four fresh reliable inside samples, 7.916667–8.541667 seconds.

The sustained, substantial exit is not boundary jitter, pose loss or a track-ID
change. Both events are retained. No hysteresis or cooldown adjustment is
justified by this recording. As before, these are observed wrist-to-ROI
interactions, not verified ornament removal or object identity claims.

## Fresh real-video results

Recording: `temp/vault_monitoring_hand_raise_updated_25s.mp4`, 1280 x 720,
24 FPS, 599 frames. SHA-256:
`be7a0e0781991302efc232ab9553bdf9cf048a89542ab3f30d5ec6d28c3debde`.
Before session: `d65acf5e75dd44789266f13c323cf474`.
Fresh after session: `a7652b00cd474737b1ffb158453e1d90`.
All 120 sampled frames completed and all activity writes finalized.

| Interaction | Before source time | After source time | Result |
| --- | --- | --- | --- |
| VAULT_DOOR_INTERACTION | 2.291667 | 2.291667 | Initial handle reach preserved |
| VAULT_AREA_INTERACTION | 2.708333 | 2.708333 | Existing detector unchanged |
| ORNAMENT_AREA_INTERACTION | 3.750000 | 3.750000 | First spatial episode preserved |
| ORNAMENT_AREA_INTERACTION | 8.541667 | 8.541667 | Genuine confirmed re-entry preserved |
| TRAY_INTERACTION | 10.000000 | 10.000000 | Preserved |
| VAULT_DOOR_INTERACTION | 11.666667 | None | Suppressed: same-wrist Tray overlap |
| VAULT_DOOR_INTERACTION | None | 14.791667 | Later handle reach now confirms independently |
| TRAY_INTERACTION | 19.375000 | 19.375000 | Repeated Tray episode preserved |

Total remains **11 persisted records**: two PERSON_DETECTED, one PERSON_ENTERED,
one SESSION_STARTED, one VAULT_AREA_INTERACTION, two Door, two Ornament and two
Tray interactions. The first four records retain their original 1.25-second
source times. VAULT_AREA_ENTERED remains absent under unchanged body membership.

Fifteen reliable samples from 11.041667 through 13.958333 seconds are rejected
for Door with `TRAY_AREA_PRIORITY`; none accumulates pending Door evidence.
At 14.166667 seconds the wrist is inside Door and outside Tray. Four fresh
samples spanning 0.625 seconds confirm at 14.791667, wrist
`(0.722372, 0.562537)`, visibility 0.911374, presence 0.995121. All four samples
are outside Tray. The later evidence was visually inspected and shows the hand
at the actual door handle. No verified closing or lock-engagement claim is added.

All 11 evidence JPEGs loaded. Every new interaction was matched to its captured
source-frame wrist, track, ROI, sample count and duration. All Door confirmation
frames were outside Tray; Ornament frames remained outside the Handle exclusion.
Saved profile contents were identical before and after. There were no replay
alerts, production alert rows or production authorization rows for this session.

## Regression and UI validation

- **88 backend tests passed**, covering replay lifecycle, region isolation,
  wrist association, profile persistence, evidence and independent interactions.
  New cases cover pending Door invalidation during Tray overlap, same-wrist
  priority, other-hand/other-track independence, overlap not rearming Door,
  genuine exit/re-entry allowing another Door event, and Ornament boundary
  flicker/unreliable/missing samples not rearming a continuous episode.
- **Six frontend timeline tests passed**; frontend code was not modified.
- Browser checks used real committed API records and bound launch requests to
  the validation session to avoid duplicate inference. Read-only response
  visibility was staged as 4, 5, 6, then 11 records to verify polling appends.
  Full UI/API oldest-first order, manual refresh, page reload and the later Door
  event's full-resolution evidence viewer passed.
- Pause/resume and clean/debug toggling preserved source-frame alignment. The
  removed large debug panel remains absent.
- The idle main Vault service was reloaded with its environment preserved; the
  same durable records are available through port 8010. Temporary validation
  runtime/process cleanup preserves all saved events, evidence and regions.
- The existing ByteTrack deprecation warning remains.

Files changed for this task, relative to `backend/use_cases/vault_monitoring`:

- `app/services/vault_workflow.py` (localized same-wrist Tray priority only)
- `tests/test_vault_workflow.py`
- `docs/vault-room-tray-door-priority.md`

No detector, tracker, pose model, body or Vault Area event rule, authorization,
activity persistence, evidence generation, saved ROI, timeline, live monitoring,
production alerts, Entrance Camera or Grill Gate behavior was changed.
