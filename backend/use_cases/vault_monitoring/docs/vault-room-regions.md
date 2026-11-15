# Vault Room Zones & Regions

Open **Vault Room Camera**, choose a source, and use **Zones & Regions** below the
preview. Select a camera/profile, then select a predefined region and Draw polygon.
Finish by clicking its first point or Finish polygon. Edit supports moving vertices
or dragging the polygon. Cancel restores an edit or discards an unfinished drawing.
Show/Hide changes presentation only; Delete is applied when Save configuration is clicked.

The canvas is extracted from Grill Gate's existing editor into
`frontend/src/components/regions/PolygonFrameCanvas.jsx`. Grill Gate keeps its original
defaults, drawing behavior, line editing, and APIs. Vault adds an overlay mode with
the same validation and normalized geometry. Pointer coordinates use the SVG frame
transform, account for cover/contain fitting, and undo webcam mirroring before saving.
Uploaded playback pauses for drawing/editing; live webcams and RTSP feeds keep running.
Polygons stay inside the fullscreen preview and resize with its actual video frame.

## Profiles and persistence

Default profiles are Webcam, CCTV, and Uploaded video. Create a named profile for
each additional camera or recording viewpoint. The selected profile is remembered
separately for each source in this browser; selecting a profile loads its saved regions.
Profiles persist on the backend across page refresh and service restart.

Storage reuses Vault's existing `zone_from_dict`, `load_zones`, and atomic `save_zones`
format under `var/vault-room-region-profiles`. A staged file adds profile name,
version, and confirmation durations before atomic replacement. Version conflicts
return 409 instead of overwriting a newer configuration. Existing global Vault
zones, registry assignments, and other use cases are not overwritten. This separate
namespace is needed because the existing common registry's file-backed Vault zones
are bound to one global active assignment and cannot represent all local camera and
upload profiles independently. No database schema changes are required.

All profile endpoints require the existing Vault Room API-key dependency:

| Method | Path under `/api/v1/vault-room/region-profiles` | Purpose |
| --- | --- | --- |
| GET | base | List profiles |
| POST | base | Create `{ "name": "Camera B" }` |
| GET | `/{id}` | Load profile and normalized polygons |
| PUT | `/{id}` | Save `{ "version": n, "zones": [...] }` |
| POST | `/{id}/activate` | Snapshot the profile before connecting a live source |

Webcam/CCTV connects activate the selected profile before starting the existing
camera flow. Replay start accepts `profile_id` and loads its own immutable snapshot.
Editing/saving while a run is paused prepares the next run; stop and process again
to apply the changes. Profiles cannot be switched during an active run. Named
profiles must be selected explicitly for different cameras sharing the same source type.

## Entry events

All five predefined keys are configurable. Only two add monitoring behavior:

- `person_monitoring_roi`: people count uses tracked bottom-center reference points
  inside this polygon. Exactly two consistent ByteTrack IDs, the existing stable
  counter reporting two, and the configured confirmation duration produce
  `PERSON_ENTERED` once per replay session.
- `vault_area_roi`: each tracked person remaining inside for the configured duration
  produces `VAULT_AREA_ENTERED`. Leaving silently re-arms entry confirmation; no exit
  event is generated. Missing/stale frames reset pending confirmation.

Default confirmation duration is one second and can be changed per region (0–60s).
The other three keys (`vault_door_roi`, `tray_area_roi`, `ornament_area_roi`) are stored
and displayed only. Existing RF-DETR, ByteTrack, counting, room rules, event publishing,
and replay isolation are reused. No door-state, tray-pickup, ornament-removal, or exit
detection is introduced. Without a person ROI, existing full-frame counting remains.

Restart Vault Monitoring to register the new profile routes if running without reload.

### Diagnosing profile-save 404 responses

`PUT /api/v1/vault-room/region-profiles/upload` is the established save path for the
default Uploaded video profile. `upload` is a dynamic profile identifier, alongside
the default `webcam` and `cctv` identifiers; named profiles receive generated IDs
from `POST /api/v1/vault-room/region-profiles`. Default profiles exist before their
first save and are persisted on that first PUT. Creating a named profile returns
its ID and current version, which must be sent when updating it.

Check the running server's `/openapi.json`: the profile collection must expose GET
and POST, and `/{profile_id}` must expose GET and PUT. A plain `{"detail":"Not Found"}`
with those paths absent means the server has not loaded the current router. Restart
the Vault backend on port 8010; changing the frontend URL or creating another router
will not fix that stale process. An unknown profile on a current server instead
returns `{"detail":"Vault Room region profile not found"}`. Do not create an unrelated
profile automatically or discard unsaved polygons in response to either error.

Coordinates are validated as finite numbers strictly within [0, 1] before the
existing polygon validator runs, so out-of-range values are rejected rather than
clamped. Valid coordinates, supplied region names, reference, enabled state, and
confirmation duration round trip through the existing atomic profile storage.
