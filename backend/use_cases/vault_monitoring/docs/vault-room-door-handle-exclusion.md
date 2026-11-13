# Door handle exclusion for uploaded replay

The initial upload profile (version 4) contained the original five polygons and no
handle polygon. Evidence at 2.291667 seconds shows a hand on the physical handle,
with a reliable wrist inside both Door and Ornament polygons. A broad Door ROI
cannot distinguish this reach from genuine Ornament interactions. No existing
coordinates were changed and no handle coordinates were generated. The user then
drew and saved a four-point handle polygon in upload profile version 5. All five
original region records, including coordinates and settings, remain unchanged.

`vault_door_handle_roi` is now an optional sixth region in the existing editor,
profile validation/storage and debug outlines. Select **Vault Door Handle**, draw
its polygon on the appropriate video frame, and save the uploaded-video profile.
The original five-region profiles remain valid. A missing or disabled handle
region leaves existing behavior unchanged and exposes
`HANDLE_EXCLUSION_NOT_CONFIGURED` in replay diagnostics.

For reliable, associated current wrists, the replay monitor evaluates handle
membership independently. If a wrist is in both Handle and Ornament, its Ornament
pending samples and exit confirmation are cleared with reason
`DOOR_HANDLE_PRIORITY`. Suppressed samples cannot accumulate duration or later
complete an event. Once outside Handle and inside Ornament, confirmation starts
fresh. An already-emitted Ornament episode remains latched until a genuine
confirmed exit from Ornament; handle membership is not fabricated exit evidence.
Door and Tray processing and other wrists/tracks are unaffected. Broad Door
membership alone never suppresses Ornament. There are no workflow prerequisites.

The handle moves with the door. A static exclusion must be drawn and validated
for the intended camera view; a large swept-area polygon may also exclude valid
reaches. No claim of object recognition or physical-operation verification is made.

## Actual recording validation

Baseline: `vault_monitoring_hand_raise_updated_25s.mp4`, session
`7529de1beed346c584e9f0528264f620`, 11 durable events:

| Event | Before: count / source seconds | After |
| --- | --- | --- |
| PERSON_DETECTED | 2 / 1.25, 1.25 | 2 / 1.25, 1.25 |
| PERSON_ENTERED | 1 / 1.25 | 1 / 1.25 |
| SESSION_STARTED | 1 / 1.25 | 1 / 1.25 |
| VAULT_AREA_INTERACTION | 1 / 2.708333 | 1 / 2.708333 |
| VAULT_DOOR_INTERACTION | 2 / 2.291667, 11.666667 | 2 / 2.291667, 11.666667 |
| ORNAMENT_AREA_INTERACTION | 2 / 2.291667, 8.541667 | 2 / 3.750000, 8.541667 |
| TRAY_INTERACTION | 2 / 10.0, 19.375 | 2 / 10.0, 19.375 |

The fresh replay `d65acf5e75dd44789266f13c323cf474` completed all 120 sampled
frames of the 1280 x 720, 24 FPS recording. SHA-256:
`be7a0e0781991302efc232ab9553bdf9cf048a89542ab3f30d5ec6d28c3debde`.
The exact user-drawn polygon was loaded; the profile was unchanged afterward.

The original 2.291667-second Ornament event is suppressed. Seven reliable
Track 1/right-wrist samples from 1.666667 through 2.916667 seconds have
`DOOR_HANDLE_PRIORITY`, no pending Ornament evidence and no Ornament emission.
Door still confirms normally at 2.291667 seconds.

**Total events remain 11, rather than decreasing to 10.** At 3.125 seconds the
wrist leaves the handle exclusion while remaining inside Ornament. Four fresh
reliable observations then confirm a new Ornament interaction at 3.750000 seconds
(0.625 seconds, visibility 0.648925, presence 0.982839). Its normalized wrist is
`(0.740813, 0.701180)`, outside the user-drawn handle polygon. Its evidence shows
the open cabinet and hand in the interior area. This is a supported spatial ROI
interaction, not a claim of verified ornament removal or object recognition.
No suppressed handle samples contribute to that confirmation.

The later Ornament interaction remains at 8.541667 seconds, also using four fresh
observations over 0.625 seconds, with wrist `(0.746919, 0.639576)` outside Handle.
Its evidence shows the operator holding the tray near the cabinet. Both evidence
images were visually inspected. Event IDs:

- 3.750000 s: `754d99f8-b909-5810-8e13-801661671332`.
- 8.541667 s: `b3768234-0341-5d5a-a992-d82a773bb13d`.

A control evaluation reused the exact same fresh tracked wrist samples with only
Handle excluded from the in-memory configuration. It reproduced the old Ornament
events at 2.291667 and 8.541667 seconds. This isolates the effect of the exclusion;
no additional ML inference or saved-profile changes were used for the control.

All 11 committed events and evidence JPEGs were retrieved. Main port 8010 returned
the identical activity records. Browser checks used real committed records,
binding launch requests to the validation replay to avoid duplicate inference.
Read-only responses exposed 4, then 5, then 6, then 11 records to verify append
behavior; UI/API order, refresh, page reload and the evidence viewer passed.
Pause/resume and clean/debug toggling preserved the same source frame. No replay
alerts, production alert rows or production authorization rows were created.
Temporary validation runtime cleanup retains these durable activities/evidence.

## Checks and scope

84 focused backend tests passed, covering handle overlap, valid Ornament outside
Handle, invalidation of pending evidence, handle-to-Ornament transitions, genuine
exit/re-entry, unreliable/missing wrists, track/hand isolation, disabled/missing
Handle, six-region API persistence/reload and existing replay/activity behavior.
Six chronological timeline tests passed. Frontend production build passed to a
temporary output directory because the existing `dist/assets` directory denied
cleanup. Existing ByteTrack deprecation and bundle-size warnings remain.

Browser verification confirmed the new option is selectable and polygon drawing
is enabled on uploaded video; the check drew/saved no coordinates. The idle main
Vault backend was reloaded with its environment preserved to enable user saving.
The 0.5-second / three-observation interaction thresholds, confidence, source
timestamps, evidence writer, timeline, model selection, live detection and other
use cases remain unchanged. The removed large debug panel remains absent.

Files changed relative to the repository root:

- `backend/use_cases/vault_monitoring/app/services/vault_workflow.py`
- `backend/use_cases/vault_monitoring/app/services/vault_region_profiles.py`
- `backend/use_cases/vault_monitoring/app/api/routes/vault_region_profiles.py`
- `backend/use_cases/vault_monitoring/app/services/vault_pose_debug.py`
- `backend/use_cases/vault_monitoring/tests/test_vault_workflow.py`
- `backend/use_cases/vault_monitoring/tests/test_vault_region_profiles.py`
- `backend/use_cases/vault_monitoring/tests/test_vault_pose_debug.py`
- `frontend/src/use-cases/vault-monitoring/hooks/useVaultRoomRegions.js`
- `backend/use_cases/vault_monitoring/docs/vault-room-door-handle-exclusion.md`
