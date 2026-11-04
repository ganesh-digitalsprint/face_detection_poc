# Regions & Zones page baseline

Recorded from source inspection on 2026-11-03 before the Stage 2 page changes. This is the regression reference for the existing Branch Exterior workflow.

## Entry point and components

- URL: `/regions`.
- Route: `frontend/src/App.jsx` registers `path="regions"` inside the Branch Exterior `BxLayout` route group. `frontend/src/layouts/routes.js` includes `/regions` in `MOVED_BRANCH_PAGES`; the sidebar entry in `frontend/src/layouts/navConfig.js` links to `/regions`.
- Page: `frontend/src/use-cases/branch-exterior/pages/RegionsZonesPage.jsx`.
- API client: `frontend/src/use-cases/branch-exterior/api/index.js`, with Branch base URL from `frontend/src/config/services.js`.
- Camera registration: `frontend/src/use-cases/branch-exterior/components/AddCameraModal.jsx`.
- Zone form: `ZoneModal` inside the page. Preview and polygon editor are also implemented in this page using `<video>`, `<img>` and a canvas overlay; there is no separate region editor component or location selector.

## Load defaults and selection behavior

On mount the page requests the Branch health/build information, camera list and camera statuses, then polls camera statuses every 1.5 seconds. It selects the first valid camera in this order: `?camera=`, `localStorage.regionsCameraId`, `localStorage.liveCameraId`, then the first camera returned by the API. There is no location selection in the baseline. The selected camera ID is saved to `localStorage.regionsCameraId`.

Changing the camera loads that camera's zones and preview. Zone loading is scoped by `camera_id`. The baseline does not guard all concurrent camera/status/zone requests against stale responses, and changing camera clears in-progress drawing without a confirmation prompt.

## Preview and polygon editing

For a selected camera the page requests `/cameras/{camera_id}/prep`. A video source uses the returned video URL; otherwise it requests a still frame from `/cameras/{camera_id}/frame?pos=...`. “Live test” starts the selected Branch worker with `/cameras/{camera_id}/activate` and displays `/streams/{camera_id}/processed`.

The canvas overlays the selected image/video. Drawing requires at least three points. Existing points can be dragged, a point can be inserted by clicking an edge, and a point can be removed by right-clicking it (never below three points). The page pauses video while drawing. The preview crop and canvas resize are accounted for before coordinates are normalized.

`cleanPolygon` clamps each point to the canvas and produces `{x, y}` floats in `[0, 1]`, normalized by canvas width and height. The database stores these as JSON pairs; API responses use `{x, y}` objects. These are frame-relative coordinates, not screen pixels.

## Zone creation, edit, delete and enable semantics

The Zone modal supports a name, one of the existing types (`entrance`, `atm`, `side_lane`, `forecourt`, `rear`, `restricted`, `other`), `restricted`, `alert_mode` (`off`, `suspicious`, `enter`, `near`) and `alert_severity` (`low`, `medium`, `high`, `critical`). New zones default to alert mode based on type. Editing reuses the current zone's metadata and polygon.

“Save zone” submits the polygon and metadata. A new zone includes `camera_id`; a patch does not. On HTTP 422 the page retries in two steps (base zone fields, then alert fields) for compatibility with older Branch schemas. Delete asks for browser confirmation and calls the camera-independent zone ID endpoint. There is no zone `enabled` field or enable/disable action. `alert_mode: "off"` disables zone-specific alerts but does not disable the polygon for all Branch spatial analysis.

## Existing API calls and payloads

All paths below are relative to the Branch API base (`http://localhost:8011/api` by default).

| Method and path | Request | Response/use |
|---|---|---|
| `GET /health` | None | Build and schema compatibility checks. |
| `GET /cameras` | None | Camera records; the UI uses IDs/names and free-text `location`. |
| `GET /cameras/status/all` | None | Status keyed by camera ID; repeated every 1.5 seconds. |
| `GET /zones?camera_id={id}` | None | Zones belonging to one camera. |
| `POST /zones` | `{camera_id, name, zone_type, restricted, alert_mode, alert_severity, polygon:[{x,y},...]}` | Created zone. `polygon` values are normalized frame fractions. |
| `PATCH /zones/{zone_id}` | Changed zone fields; on normal save includes `{name, zone_type, restricted, alert_mode, alert_severity, polygon}` | Updated zone. Camera ownership cannot be changed through this body. |
| `DELETE /zones/{zone_id}` | None | `{deleted:true}`. |
| `GET /cameras/{id}/prep` | None | Preview kind, dimensions, crop and/or video URL. |
| `GET /cameras/{id}/frame?pos={fraction}&t={cache-buster}` | None | JPEG still image. |
| `POST /cameras/{id}/activate` | Empty JSON | Starts the camera worker for live test. |
| `GET /streams/{id}/processed?t={cache-buster}` | None | Processed MJPEG stream used by live test. |
| `GET /cameras/status/all` | None | Status polling while page is mounted. |

Camera creation UI is opened from this page. `AddCameraModal` additionally uses `GET /uploads/browse`, `POST /uploads/video` (multipart for uploaded video), `POST /cameras?start=false` (camera JSON including name, cam_type, source, credentials, location, enabled and loop_video), and the page's `POST /cameras/sync-folder` rescan action. These are existing camera configuration APIs and are not part of zone save payloads.

## Baseline limitations to preserve or address explicitly

- There is no use-case selector or location dropdown. Camera location is free-text metadata.
- Branch API camera IDs scope zones; the page must keep the same IDs and payload when location filtering is added.
- There is no zone enabled flag. Do not silently treat `alert_mode: "off"` as a universal disabled state.
- In-progress polygon/modal changes can be discarded by changing camera or leaving the page without a prompt.
- Preview errors leave the zone list/page available, and Reload retries preview preparation; the baseline has no separate camera retry control.
- Existing Branch alert fields, type values, and the 422 compatibility save path are part of the current API behavior.
