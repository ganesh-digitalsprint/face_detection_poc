# Five-zone replay debug visualization

## Cause

All five regions were present in the selected upload profile and loaded into
`VaultRegionMonitor.profile`. The debug snapshot previously forwarded only the
Vault Area polygon and the renderer drew only that polygon. The four omitted
regions were Person Monitoring Area, Vault Door, Tray Area and Ornament Area.
The separate generic `zones_status.zone_count` was not used to diagnose loading.

The current saved upload profile is version **3** (not the version 2 used in
earlier reports). Its normalized, finite, in-range polygons contain:

| Region | Points | Debug color |
| --- | --- | --- |
| person_monitoring_roi | 7 | Green |
| vault_area_roi | 6 | Yellow |
| vault_door_roi | 4 | Blue |
| tray_area_roi | 5 | Purple |
| ornament_area_roi | 4 | Orange |

No profile data was edited by this task.

## Change

Each existing atomic processed-frame debug snapshot now includes a deep copy of
the selected region profile's full zone list and profile ID. This also works when
pose inference is unavailable or wrist monitoring is disabled. It does not depend
on MediaPipe returning a pose or on the generic zone registry.

The existing debug renderer projects each saved normalized coordinate using the
actual JPEG width and height. All translucent fills are drawn first at 8% opacity,
then thin colored outlines and labels, preserving distinguishable overlapping
borders. Labels avoid the existing track status cards. Skeletons, wrist colors,
association diagnostics and confirmation status retain their existing inputs.

A compact legend reports each actual configured region's name, loaded status and
point count. Missing configuration or invalid polygon coordinates produce an
explicit reason and no fabricated polygon. A configured disabled region remains
visible for debugging and is labeled `LOADED (disabled)`; this does not enable
its detection. Hardcoded names/colors do not imply successful loading.

Clean frame output, default-off behavior, zone editing and frontend rendering are
unchanged. Because all debug geometry is drawn in the same source JPEG, existing
letterboxing, resizing, pause and fullscreen scale it together with the footage.
There is no additional pose inference, model initialization or detection change.

## Real-video validation

Input: `temp/vault_authorized_employee_operation_30s_smooth.mp4`, 1280 x 720,
24 FPS, 30 seconds. SHA-256:
`96162fc1ac51bd11c1dc66649058ec6d89b13b2492e6815cff07e5445bec624b`.
Completed replay: `62341e8db0a14084b994ec1fdae0f2d2`.

- All 144 sampled frames completed in approximately 72 seconds, including an
  intentional pause. Runtime is not a controlled benchmark against prior runs.
- Every captured frame snapshot contained the exact zone coordinates from the
  selected profile. The editor loads this same profile; no separate polygons
  were constructed for visualization. The API profile before/after was identical.
- All five polygons and legend entries were visible in actual frame API images
  and the browser preview. Source images around 7.083 seconds and the letterboxed
  browser preview were inspected. Nested yellow, blue and orange regions remained
  distinguishable; the green monitoring region and purple tray region were visible.
- Person boxes, matched pose skeletons, wrist markers and backend confirmation
  status remained visible. Track 1's right-wrist interaction was confirmed at
  7.083333 seconds, as before. Body-position Vault Area entry remained absent.
- Events: PERSON_DETECTED x3, PERSON_ENTERED x1, SESSION_STARTED x1,
  VAULT_AREA_ENTERED x0, VAULT_AREA_INTERACTION x1. No replay alerts occurred.
  All six activity evidence images were successfully retrieved.
- Repeated paused debug images were identical. Clean and debug image requests
  shared the same frame sequence; debug-off returned unchanged clean bytes with
  normal person boxes. Resume continued without shifting geometry.
- Browser validation used the real replay APIs, binding launch requests to this
  existing run. Default-off, clean/debug switching, fullscreen, delayed/failed
  preview recovery, event timeline and full-resolution evidence passed. No new
  frontend player or zone-editor changes were needed.
- The saved regions, live authorization, automatic simulated authorization,
  timer, activity rules, alerts, RF-DETR, ByteTrack, MediaPipe thresholds,
  Entrance and Grill Gate behavior were not modified.

## Tests and files changed

77 focused backend tests passed. New coverage verifies all five profile regions,
unchanged coordinates, missing/invalid-region diagnostics, and a complete region
snapshot without initializing pose inference. The final label-position adjustment
also passed the three debug renderer/snapshot tests. Existing frame atomicity,
clean-output, wrist, activity, replay, pose-preview and profile-isolation tests
remain passing. The existing ByteTrack deprecation warning remains.

Paths relative to `backend/use_cases/vault_monitoring`:

- `app/services/vault_room_manager.py` — full profile in frame debug snapshots.
- `app/services/vault_pose_debug.py` — five colors, polygons, labels and diagnostics.
- `tests/test_vault_pose_debug.py` — complete/missing/invalid profile tests.
- `docs/vault-room-five-zone-debug.md` — this report.

No frontend files or saved configuration files were changed for this task.
Start a new replay to generate full-profile frame snapshots with the updated worker.
