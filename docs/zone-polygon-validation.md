# Shared zone polygon validation

The drawing handlers appended all pointer/click positions, including clicks intended to finish near the first corner. There was no near-start completion gesture or frontend segment-intersection check. Grill Gate additionally rounded normalized coordinates to four decimals during pointer conversion. The backend already closes the last edge back to the first corner, so the extra near-start vertex in the reported Mesh outline created a tiny edge crossing the first edge. The supplied polygon was reproduced as invalid; removing its redundant last point yields a valid four-corner polygon.

## Completion and normalization

Both the common registry editor and Grill Gate frame editor use a shared hit test within 10 CSS pixels of the first corner after at least three corners exist. That click completes the polygon without appending its position. Completion validates the outline, retains the original first corner and order, and keeps the existing Canvas/SVG closing mechanism. Undo/Clear remains available. Grill Gate also retains its Finish polygon button. Pointer coordinates are no longer rounded to four decimal places.

`frontend/src/utils/zonePolygons.js` provides shared normalization, validation, and error mapping. It removes exact consecutive duplicates and explicit duplicate closing points. It preserves valid close corners. A near-closing tail is removed only when all these conditions hold:

- Reference dimensions are available.
- The tail is within 3 reference pixels of the start and within 0.003 normalized distance.
- The original outline is invalid and all nonadjacent intersections are between the first edge and the edge leading to that tail.
- Removing the tail produces a fully valid polygon.

Other self-intersections are rejected rather than reordered or repaired. If dimensions are missing or the tail exceeds the conservative tolerance, it remains available for manual correction. The supplied Mesh outline safely normalizes at 1920x1080 and at the common editor's 1280x720 canvas resolution; it is deliberately not auto-simplified at 3840x2160, where that offset exceeds 3 pixels.

## Validation and errors

Before submitting a configuration, the complete zone array is checked for finite coordinates within 0..1, at least three distinct corners, repeated vertices, zero-length edges, nonadjacent intersections (including touching and collinear overlap), adjacent backtracking/overlap, and polygon area. Valid concave polygons are accepted. The common registry/Grill Gate minimum area matches the backend's 0.001 of frame area. The legacy Branch adapter retains its nonzero-area policy.

Disabled polygon geometry is also checked because the existing Pydantic schema validates it on submission. Configuration-client guards cover video configuration, named configurations, and self-contained upload configurations. Registry adapter guards cover all common-module use cases. Existing saved geometry is copied and normalized at the save boundary; load/edit does not mutate it.

Invalid saves are blocked before mutation, identify the zone by name, and preserve the user's draft and other zones. Grill Gate selects the offending outline when an indexed geometry error is available. Backend FastAPI errors such as `['body', 'zones', 3, 'polygon']` map to `zones[3].name`; only the useful validation message is shown. Backend schemas remain the authoritative final validation layer and were not changed.

After a successful save, the relevant editor shows the normalized geometry. Live assignment mutations remain separate API calls; preflight prevents geometry errors from causing partial saves, but this change does not make those existing multi-call saves transactional.

## Gate ROI contract

`SlidingGateCalibration.gate_roi_zone_key` is a literal logical alias, `gate_leaf_roi`. `pick_gate_leaf_zone()` selects the first enabled zone with `zone_type == 'gate_leaf_roi'`; it does not match the generated `zone_key`. Therefore a zone key such as `gate_leaf_roi_mwc7nojd` is valid and needs no calibration rewrite. No gate detection, crossing, tracking, mesh monitoring, timer, or alert semantics were changed.

The current video configuration save endpoint is `PUT /api/v1/grill-gate/videos/{job_id}/config`; the task's example called it POST. No endpoint was added or renamed.

## Files changed

- `frontend/src/utils/zonePolygons.js` (new)
- `frontend/src/utils/zonePolygons.test.js` (new)
- `frontend/src/use-cases/branch-exterior/pages/CommonRegionsZonesPage.jsx`
- `frontend/src/use-cases/branch-exterior/regionsAdapters.js`
- `frontend/src/use-cases/grill-gate/components/ZonesSection.jsx`
- `frontend/src/use-cases/grill-gate/api/grillGate.js`
- `backend/use_cases/grill_gate_monitoring/tests/test_video_job_api.py` (regressions only)
- `docs/zone-polygon-validation.md` (new)

## Verification

- `npm.cmd test`: 171 passed, including 11 new shared polygon tests.
- Production build: passed; existing bundle-size warning remains. Verification output is in `tmp/zone-polygons-final-build`.
- Focused backend API tests: 2 passed, 73 deselected. They prove rejection of the original Mesh polygon, successful persistence of its normalized outline, and the ROI alias/generated-key contract.
- `git diff --check`: passed.

No interactive browser drawing smoke test was performed. The geometry utilities, common adapter save behavior, backend persistence contract, and production compilation were exercised.
