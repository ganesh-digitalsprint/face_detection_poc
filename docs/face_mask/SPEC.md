# Face Mask — SPEC (DRAFT, reconstructed from the task prompts)

> **Status: DRAFT.** No SPEC was supplied; this was reconstructed from the implementation prompts so FM-xx ids exist.
> Anything marked **TBC** is a default awaiting client confirmation. Replace this file when the real spec arrives, then re-map test names.

## 1. Purpose
Detect, at entrances, whether a person entering has a **VISIBLE** or **CONCEALED** face, and raise one alert per concealed entry.
The system never identifies anyone.

| ID | Requirement |
|---|---|
| FM-01 | Evaluate only persons who are **entering** (see section 2). Passing, waiting, leaving are not evaluated for alerts |
| FM-02 | Classify each evaluated entry as VISIBLE, CONCEALED or UNABLE_TO_ASSESS |
| FM-03 | Concealed entry raises exactly one event and one alert per Track ID |
| FM-04 | Poor-quality frames (small, blurry, dark, bright, turned away) never alert; wait for a better frame |
| FM-05 | Each event carries evidence: best-head snapshot, MP4 clip (pre + post roll), details |
| FM-06 | Review workflow with audit trail |
| FM-07 | Sources: RTSP/IP cameras, uploaded video, existing video; same behaviour as Branch Exterior |
| FM-08 | Entry ROI + inward direction per camera, editable live |
| FM-09 | Live annotated stream |
| FM-10 | All thresholds come from `face_mask.yaml`; none hard-coded |
| FM-11 | Alerts go to alert_service with type `FACE_CONCEALMENT`, use_case `face_mask`; retries never duplicate and never block the pipeline |
| FM-12 | Events list, filters, stats, CSV export |
| FM-13 | Credentials never returned by any GET, never logged |
| FM-14 | **Privacy:** no recognition, no embeddings, no identity or name stored anywhere (tables, models, logs) |
| FM-15 | Failure of face_mask never breaks other use cases, Dashboard, Alerts or Security Brief |

## 2. Entering
A person is **entering** when the foot point (bottom-centre of the person box) is inside the camera's entry ROI **and** has moved along the ROI's inward vector by at least `min_inward_displacement_px` over the last `entering_window_frames` frames. Otherwise not-entering; tracking continues, and a track that later enters is evaluated then. Fragmented tracks are merged by the per-camera cooldown (section 4).

## 3. Visibility rules (binding)
| Case | Result |
|---|---|
| Normal face | VISIBLE |
| Sunglasses only, nose/mouth/chin visible | VISIBLE |
| Head turned away or down, nothing covering | not concealed; UNABLE_TO_ASSESS if no usable view |
| Surgical/cloth mask, scarf (even partial), helmet, cap hiding the face | CONCEALED |
| Human-like / animal mask | CONCEALED. **TBC (open question):** whether to alert |
| Image too small / blurry / dark / bright | quality gate FAIL; wait, never alert |

Classifier classes: `visible, sunglasses_only, surgical_mask, scarf, cap_concealing, helmet, other_mask, unable`. `visible` and `sunglasses_only` map to VISIBLE; `unable` to UNABLE; the rest to CONCEALED.

## 4. Lifecycle
`NEW_TRACK → IN_ENTRY_ROI → EVALUATING → CLEARED | UNABLE_TO_ASSESS | CONCEALMENT_EVENT_OPEN`.
CONCEALED is confirmed when `frames_to_confirm` of the last `confirm_window` evaluated frames are CONCEALED with score ≥ `visibility_threshold`. One event per Track ID; later frames update `last_seen`, frame count, best score. A new event on the same camera within `cooldown_seconds` and `cooldown_radius_px` of an earlier event's last position is suppressed as track fragmentation. A track ending while EVALUATING becomes UNABLE_TO_ASSESS (no alert). Every evaluated entry is logged to `fm_entry_log`.

## 5. Evidence and alert
Per event: best-head snapshot (head box drawn), MP4 clip with `clip_pre_seconds` before and `clip_post_seconds` after confirmation, details JSON. If the clip fails, keep the snapshot and set clip status `failed` with a reason. Written off the frame thread. Alert severity `high`; channels from YAML (dashboard on; sms/email/app disabled placeholders).

## 6. Review
`OPEN → UNDER_REVIEW → CONFIRMED | FALSE_POSITIVE → CLOSED`. Remarks required on close. Every transition is written to `fm_review_action`. Invalid transition returns 409.

## 7. TBC defaults (initial `face_mask.yaml`)
Visibility threshold 0.60 · frames_to_confirm 5 of 8 · quality: min head height 48 px, sharpness ≥ 60, brightness 40–220, max yaw 55° · analyzer `heuristic` · clip pre 5 s / post 5 s · cooldown 30 s / 120 px · processing 8 fps · person detector RF-DETR conf 0.40 · tracker ByteTrack (branch settings) · entering window 10 frames, min inward 12 px. Exact values are in `backend/use_cases/face_mask/config/face_mask.yaml`.

## 8. Training (optional)
A classifier trained on locally collected head crops improves the heuristic backend. Crops stay local; retain only as long as needed for training; never used for identification.
