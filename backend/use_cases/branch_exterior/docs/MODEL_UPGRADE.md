# Upgrading from the POC detectors to production models

This POC was built in a sandboxed environment with **no internet access**,
so every detector it ships with is either (a) bundled inside
`opencv-python` / `opencv-contrib-python` with no extra download, or (b) a
transparent, rule-based heuristic. This document explains exactly what to
swap in for a real deployment, and where.

## What's real vs. a placeholder today

| Capability | POC implementation | Status |
|---|---|---|
| Person detection | Background-subtraction blobs (`motion_detector.py`), or OpenCV HOG+SVM (`hog_detector.py`) | Real, working, free, offline. Not as accurate as a trained detector. |
| Tracking | Custom IoU+centroid tracker (`tracker.py`) | Real, working, dependency-free. |
| Zone / loitering / gathering / movement / after-hours (Tasks 1-4) | Rule-based Python, operating on tracked positions | Real, working, fully explainable - this is how the workflow document said these should be built. No upgrade needed. |
| Face detection | OpenCV Haar cascade | Real, working, offline. |
| Guard recognition | OpenCV LBPH recognizer, trained on enrolled photos | Real, working, offline. Good enough for a small roster; not a production biometric system. |
| Weapon detection (Task 5.1) | Edge/contour heuristic (`weapon_detector.py`) | **Placeholder for demonstration only.** Flags are labelled `method: heuristic` in the event metadata so they are never confused with a trained model's output. |
| Fighting/action recognition (Task 5.3) | Speed/proximity/jitter rules (`action_recognizer.py`) | Real but simple. Good enough to demonstrate the pipeline; a trained model will be far more accurate. |

This mirrors the team's own licensing analysis
(`Free_Pretrained_Models_for_Suspicious_Activity_Detection.docx`): there is
no ready-made, reliable, free-for-commercial-use pretrained model for guns,
knives, swords, rods or fighting. Production quality requires fine-tuning on
the client's own licence-clean data.

## Swapping in RF-DETR for person/weapon detection

1. `uv add rfdetr` (Apache-2.0; use the **Nano/Small/Medium/Large** checkpoints
   only - the XL/2XL checkpoints ship under a different licence, PML 1.0).
2. Fine-tune on your own labelled data (see the companion workflow document's
   Section 8, "Training Pipeline for Weapons and Fighting").
3. Implement `RfDetrPersonDetectorStub.detect()` in
   `app/services/detection/rfdetr_stub.py` - the class and constructor
   signature already match what `app/services/detection/factory.py` expects,
   so no other file needs to change.
4. Set `PERSON_DETECTOR_BACKEND=rfdetr` and `WEAPON_MODEL_PATH=/path/to/weights`
   in `.env` (or from the Settings page).

## Swapping in a trained action-recognition model

`ActionRecognizer` in `app/services/detection/action_recognizer.py` currently
sets `track.action_label` / `track.action_confidence` from simple rules.
A trained model (e.g. a small skeleton-GCN using RTMPose keypoints, or a
fine-tuned V-JEPA 2 / MMAction2 model - both MIT/Apache-2.0 - trained on your
own staged + real footage) should populate exactly those same two fields.
Everything downstream (fusion, alerting, the UI) already consumes them and
does not need to change.

## Swapping ByteTrack in for the custom tracker

`app/services/detection/tracker.py` ships a small dependency-free tracker so
the POC has zero install friction. For production, `pip install trackers`
(Roboflow's ByteTrack implementation, Apache-2.0) and adapt
`CameraWorker._... ` to call it instead - keep exposing the same `Track`
shape (`.track_id`, `.detection`, `.history`) so `app/services/analytics/*`
and `app/services/annotate.py` need no changes.

## Calibrating real ground-plane metres

`app/services/analytics/geometry.py` assumes a fixed ~14m frame diagonal so
that metre-based thresholds (gathering proximity, etc.) have *some* real
effect without a calibration step. For production accuracy, implement the
homography-based mapping described in the workflow document (Section 1.6,
"S2 Zone and ground-plane mapping"): survey 4+ floor points per camera,
compute `cv2.findHomography`, and replace `approx_pixels_per_metre` with a
real per-camera pixel-to-metre transform.


# Models used (current state)

| Job | Model / method | Licence | Where |
|---|---|---|---|
| Person / vehicle / weapon-like object detection | RF-DETR (COCO-pretrained, Nano..Large) | Apache-2.0 | `services/detection/rfdetr_detector.py` |
| Tracking | ByteTrack (own numpy/scipy implementation) | MIT algorithm | `services/detection/bytetrack.py` |
| Body keypoints | RTMPose via `rtmlib` + onnxruntime | Apache-2.0 | `services/detection/pose_estimator.py` |
| Fall / fight / run | Rules on keypoints + track speed | own code | `services/detection/action_recognizer.py` |
| Guard face match | OpenCV Haar + LBPH (needs opencv-contrib) | Apache-2.0 | `services/detection/face_recognizer.py` |
| Fallback detectors | Motion (MOG2), HOG+SVM | Apache-2.0 | `motion_detector.py`, `hog_detector.py` |

Do not use RF-DETR XL / 2XL checkpoints (different licence).

## Real weapon detection
COCO only knows "knife" and "baseball bat" (no guns), so it will miss weapons and sometimes false-alarm.
For real accuracy fine-tune RF-DETR on your own labelled weapon images, then set `WEAPON_MODEL_PATH=/path/to/checkpoint.pth`
(and `WEAPON_CLASS_NAMES` if the checkpoint has no class names).

## Tuning fall / fight
Starting thresholds in `action_recognizer.py` were checked on synthetic skeletons only. Every fighting event stores
`agitation_a`, `agitation_b`, `strikes_3s`, `close_seconds` in its details - use them to tune on your footage.


# Getting real weapon detection

## What the app does today (no training)
* RF-DETR (COCO) can only recognise **knife** and **baseball bat** - there is no gun class.
* To find hand-held objects the app re-checks a zoomed crop around each person (`WEAPON_CROP_*`), which
  works much better than the full frame, but a COCO knife is still often missed on CCTV and a phone or pole can
  occasionally be mistaken for one. A weapon is only flagged after `WEAPON_CONFIRM_HITS` checks on the same person.
* The Live Monitoring tile shows what is looking for weapons, e.g. `COCO knife/bat + NO gun model loaded`.

## To detect guns (and knives properly)
Train a model on weapon images with `scripts/train_weapon_model.py` (on a free Colab/Kaggle GPU), then set
`WEAPON_MODEL_PATH` / `WEAPON_MODEL_SIZE` / `WEAPON_CLASS_NAMES` in `.env`. The app then runs your model on the
person crops every `WEAPON_CROP_EVERY_N_PASSES` checks and on the full frame, and the tile will read
`custom weapon model`.

Possible data sources (check each licence yourself before using it): weapon datasets on Roboflow Universe, and the
Open Images dataset (it has Handgun / Rifle / Knife / Sword classes). The best data is frames from your own
cameras, labelled with a tool such as Roboflow or CVAT.

## Tuning without training
`WEAPON_COCO_THRESHOLD` / `WEAPON_CROP_THRESHOLD` (lower = more detections *and* more false alarms),
`WEAPON_CROP_EVERY_N_PASSES` (1 = check every pass, slower), `WEAPON_CROP_MAX_PEOPLE`.


# Database choice, viewing the data, and working with little disk space

## Which database?
**Stay on SQLite for now.** It is already what the app uses (`backend/storage/app.db`): one file, nothing to
install, no server, no username/password. Every event is a row in the `events` table with its camera, zone,
severity, confidence, tracked people, snapshot/clip paths and the AI's details (`meta`, JSON). When you later need
many users / many cameras / a central server, switch to **PostgreSQL** from Settings -> Database (the app already
supports postgres/mysql/oracle/mongodb); the tables are the same. SQLite is the wrong choice only for several
machines writing at once - not a concern for a POC.

## Looking at the data (no tools to install)
```
cd backend
uv run python scripts/db_viewer.py tables
uv run python scripts/db_viewer.py summary
uv run python scripts/db_viewer.py events --limit 30
uv run python scripts/db_viewer.py events --kind snatch_flee
uv run python scripts/db_viewer.py event <first characters of an event id>
uv run python scripts/db_viewer.py sql "SELECT camera_name, severity, COUNT(*) FROM events GROUP BY 1,2"
uv run python scripts/db_viewer.py export events.csv      (open in Excel)
```
It opens the database read-only, so it is safe while the server is running. If you prefer a window, the free
"DB Browser for SQLite" (portable, ~20 MB) opens `backend/storage/app.db` directly.
Each event also has a printable report: Alerts Dashboard -> open an event -> "Incident report".

## Start with a clean event list
Your database contains old events from the earlier rule-based version (thousands of false "weapon"/"fighting"
rows). For a clean demo: stop the server and delete `backend/storage/app.db` (you lose drawn zones), or use
"Clear events" on the Alerts Dashboard. Then run `scripts/cleanup_storage.py --apply` to remove leftover media.

## C: drive is nearly full - put the big stuff on another drive
The heavy parts are PyTorch + libraries (roughly 1-2 GB, my estimate) and model files (tens of MB). Run these ONCE in
PowerShell (use any drive/folder you have, here D:), then CLOSE and reopen the terminal:
```
setx UV_CACHE_DIR      D:\bx\uv-cache
setx UV_PROJECT_ENVIRONMENT D:\bx\venv
setx HF_HOME           D:\bx\hf-cache
setx TORCH_HOME        D:\bx\torch-cache
```
If a `.venv` folder already exists inside `backend` on C:, delete it, then run `uv sync` again. After a successful
`uv sync` you can free the download cache with `uv cache clean`. The RTMPose model downloads to
`C:\Users\<you>\.cache\rtmlib` (small); the RF-DETR weights are saved in the `backend` folder.
In the app, set Settings -> "Hard storage cap" to about 500 MB so snapshots/clips can never fill the disk.


# Getting real weapon detection

## What the app does today (no training)
* RF-DETR (COCO) can only recognise **knife** and **baseball bat** - there is no gun class.
* To find hand-held objects the app re-checks a zoomed crop around each person (`WEAPON_CROP_*`), which
  works much better than the full frame, but a COCO knife is still often missed on CCTV and a phone or pole can
  occasionally be mistaken for one. A weapon is only flagged after `WEAPON_CONFIRM_HITS` checks on the same person.
* The Live Monitoring tile shows what is looking for weapons, e.g. `COCO knife/bat + NO gun model loaded`.

## To detect guns (and knives properly)
Train a model on weapon images with `scripts/train_weapon_model.py` (on a free Colab/Kaggle GPU), then set
`WEAPON_MODEL_PATH` / `WEAPON_MODEL_SIZE` / `WEAPON_CLASS_NAMES` in `.env`. The app then runs your model on the
person crops every `WEAPON_CROP_EVERY_N_PASSES` checks and on the full frame, and the tile will read
`custom weapon model`.

Possible data sources (check each licence yourself before using it): weapon datasets on Roboflow Universe, and the
Open Images dataset (it has Handgun / Rifle / Knife / Sword classes). The best data is frames from your own
cameras, labelled with a tool such as Roboflow or CVAT.

## Tuning without training
`WEAPON_COCO_THRESHOLD` / `WEAPON_CROP_THRESHOLD` (lower = more detections *and* more false alarms),
`WEAPON_CROP_EVERY_N_PASSES` (1 = check every pass, slower), `WEAPON_CROP_MAX_PEOPLE`.


# Database choice, viewing the data, and working with little disk space

## Which database?
**Stay on SQLite for now.** It is already what the app uses (`backend/storage/app.db`): one file, nothing to
install, no server, no username/password. Every event is a row in the `events` table with its camera, zone,
severity, confidence, tracked people, snapshot/clip paths and the AI's details (`meta`, JSON). When you later need
many users / many cameras / a central server, switch to **PostgreSQL** from Settings -> Database (the app already
supports postgres/mysql/oracle/mongodb); the tables are the same. SQLite is the wrong choice only for several
machines writing at once - not a concern for a POC.

## Looking at the data (no tools to install)
```
cd backend
uv run python scripts/db_viewer.py tables
uv run python scripts/db_viewer.py summary
uv run python scripts/db_viewer.py events --limit 30
uv run python scripts/db_viewer.py events --kind snatch_flee
uv run python scripts/db_viewer.py event <first characters of an event id>
uv run python scripts/db_viewer.py sql "SELECT camera_name, severity, COUNT(*) FROM events GROUP BY 1,2"
uv run python scripts/db_viewer.py export events.csv      (open in Excel)
```
It opens the database read-only, so it is safe while the server is running. If you prefer a window, the free
"DB Browser for SQLite" (portable, ~20 MB) opens `backend/storage/app.db` directly.
Each event also has a printable report: Alerts Dashboard -> open an event -> "Incident report".

## Start with a clean event list
Your database contains old events from the earlier rule-based version (thousands of false "weapon"/"fighting"
rows). For a clean demo: stop the server and delete `backend/storage/app.db` (you lose drawn zones), or use
"Clear events" on the Alerts Dashboard. Then run `scripts/cleanup_storage.py --apply` to remove leftover media.

## C: drive is nearly full - put the big stuff on another drive
The heavy parts are PyTorch + libraries (roughly 1-2 GB, my estimate) and model files (tens of MB). Run these ONCE in
PowerShell (use any drive/folder you have, here D:), then CLOSE and reopen the terminal:
```
setx UV_CACHE_DIR      D:\bx\uv-cache
setx UV_PROJECT_ENVIRONMENT D:\bx\venv
setx HF_HOME           D:\bx\hf-cache
setx TORCH_HOME        D:\bx\torch-cache
```
If a `.venv` folder already exists inside `backend` on C:, delete it, then run `uv sync` again. After a successful
`uv sync` you can free the download cache with `uv cache clean`. The RTMPose model downloads to
`C:\Users\<you>\.cache\rtmlib` (small); the RF-DETR weights are saved in the `backend` folder.
In the app, set Settings -> "Hard storage cap" to about 500 MB so snapshots/clips can never fill the disk.


# What the system detects, how, and how to see it

Every detection is an AI-assisted INDICATION that a person must verify. Reliability depends on picture quality,
camera angle and distance - the tables say what each one needs.

## Seeing the picture-quality features (Live Monitoring, under the video)
| Feature | What you see | What it does |
|---|---|---|
| Black-bar crop | chip "Picture crop: black bars removed" | removes unused black areas (e.g. a landscape CCTV clip inside a portrait phone video) so people are bigger |
| Tiled scan | chip "Tiled scan 2x2: running..." and "+ TILES" in the video's top bar | also scans wide pictures (900 px+) in 2x2 pieces so tiny people reach the AI bigger. Shows "standing by" on narrow pictures |
| Body pose | chip "Body pose (RTMPose): on" + skeleton lines on people | needed by fight / lookout / climbing / violent-action checks |
| AI detections button | grey/blue/red boxes with class + confidence | shows EVERYTHING the model returns - if a person is not boxed there, the model did not see them |

## Detections ("What the AI watches for" panel on Live Monitoring shows a counter for each)
| Detection | How it works | Needs |
|---|---|---|
| Weapon-like object | RF-DETR knife / bat classes on the full frame and zoomed person crops, confirmed over 3 checks | a trained model for guns (see WEAPON_TRAINING.md) |
| Fighting | two people in close contact with violent arm movement | body pose; people at least ~56 px tall |
| Violent action | one person swinging / striking for 2+ s (hammer, rod) | body pose |
| Snatch and flee | close contact, then one person runs while the other stays | people tracked |
| Escape on a bike | someone gets onto a motorbike after a snatch / weapon / fight / run | motorbike detected |
| Parked bike taken | a bike parked 8+ s is boarded by someone who arrived on foot and rides off (could be the owner) | motorbike detected |
| Climbing | feet rise while body size stays the same, arms up | tracking (pose makes it stricter and better) |
| Jump down from height | fast one-way drop of the feet at constant size | tracking |
| Person down / running / jumping | posture / speed / feet leaving the ground | tracking (pose for posture) |
| Lookout behaviour | repeated head turns left/right while standing | body pose, face toward camera |
| Gate tampering | lingering 8+ s at an entrance / restricted zone while scanning or working with the hands | an entrance or restricted zone drawn |
| Unattended bag | backpack / handbag / suitcase alone for 20 s with nobody near | bag visible |
| Group at ATM / group together | 3+ people together | an ATM zone (or no zones drawn) |
| Zone breach / near zone | a person touches / enters / comes near a zone | a zone with an alert rule |

## Zones
Regions & Zones: pick a video, let it play, press Draw new zone, click points around the area, press **Finish zone**, fill
in the form. "Immediate alert on screen" decides what happens when somebody is at that zone: the zone flashes red, a red
bar and a beep appear on Live Monitoring, and an event with a snapshot + clip is saved (for high / critical severity).
Use **Live test** to watch your zones react while the video plays.

## Where everything is stored
Every incident is a row in the `events` table of `backend/storage/app.db` (camera, zone, severity, confidence, people,
snapshot / clip paths, and the AI's details as JSON in `meta`). Look at it with `scripts/db_viewer.py` and print any event
from the Alerts Dashboard -> open an event -> "Incident report".

## Known limits
* Guns are not detected without your own trained model; knives / bats are weak on CCTV.
* People smaller than about 40 px, very dark footage and footage of a screen filmed by a phone are unreliable.
* Rules are heuristics: they can miss events and raise false alarms. Tune them on your own footage.


# Models used (current state)

| Job | Model / method | Licence | Where |
|---|---|---|---|
| Person / vehicle / weapon-like object detection | RF-DETR (COCO-pretrained, Nano..Large) | Apache-2.0 | `services/detection/rfdetr_detector.py` |
| Tracking | ByteTrack (own numpy/scipy implementation) | MIT algorithm | `services/detection/bytetrack.py` |
| Body keypoints | RTMPose via `rtmlib` + onnxruntime | Apache-2.0 | `services/detection/pose_estimator.py` |
| Fall / fight / run | Rules on keypoints + track speed | own code | `services/detection/action_recognizer.py` |
| Guard face match | OpenCV Haar + LBPH (needs opencv-contrib) | Apache-2.0 | `services/detection/face_recognizer.py` |
| Fallback detectors | Motion (MOG2), HOG+SVM | Apache-2.0 | `motion_detector.py`, `hog_detector.py` |

Do not use RF-DETR XL / 2XL checkpoints (different licence).

## Real weapon detection
COCO only knows "knife" and "baseball bat" (no guns), so it will miss weapons and sometimes false-alarm.
For real accuracy fine-tune RF-DETR on your own labelled weapon images, then set `WEAPON_MODEL_PATH=/path/to/checkpoint.pth`
(and `WEAPON_CLASS_NAMES` if the checkpoint has no class names).

## Tuning fall / fight
Starting thresholds in `action_recognizer.py` were checked on synthetic skeletons only. Every fighting event stores
`agitation_a`, `agitation_b`, `strikes_3s`, `close_seconds` in its details - use them to tune on your footage.



# Getting real weapon detection

## What the app does today (no training)
* RF-DETR (COCO) can only recognise **knife** and **baseball bat** - there is no gun class.
* To find hand-held objects the app re-checks a zoomed crop around each person (`WEAPON_CROP_*`), which
  works much better than the full frame, but a COCO knife is still often missed on CCTV and a phone or pole can
  occasionally be mistaken for one. A weapon is only flagged after `WEAPON_CONFIRM_HITS` checks on the same person.
* The Live Monitoring tile shows what is looking for weapons, e.g. `COCO knife/bat + NO gun model loaded`.

## To detect guns (and knives properly)
Train a model on weapon images with `scripts/train_weapon_model.py` (on a free Colab/Kaggle GPU), then set
`WEAPON_MODEL_PATH` / `WEAPON_MODEL_SIZE` / `WEAPON_CLASS_NAMES` in `.env`. The app then runs your model on the
person crops every `WEAPON_CROP_EVERY_N_PASSES` checks and on the full frame, and the tile will read
`custom weapon model`.

Possible data sources (check each licence yourself before using it): weapon datasets on Roboflow Universe, and the
Open Images dataset (it has Handgun / Rifle / Knife / Sword classes). The best data is frames from your own
cameras, labelled with a tool such as Roboflow or CVAT.

## Tuning without training
`WEAPON_COCO_THRESHOLD` / `WEAPON_CROP_THRESHOLD` (lower = more detections *and* more false alarms),
`WEAPON_CROP_EVERY_N_PASSES` (1 = check every pass, slower), `WEAPON_CROP_MAX_PEOPLE`.



# What the system detects, how, and how to see it

Every detection is an AI-assisted INDICATION that a person must verify. Reliability depends on picture quality,
camera angle and distance - the tables say what each one needs.

## Seeing the picture-quality features (Live Monitoring, under the video)
| Feature | What you see | What it does |
|---|---|---|
| Black-bar crop | chip "Picture crop: black bars removed" | removes unused black areas (e.g. a landscape CCTV clip inside a portrait phone video) so people are bigger |
| Tiled scan | chip "Tiled scan 2x2: running..." and "+ TILES" in the video's top bar | also scans wide pictures (900 px+) in 2x2 pieces so tiny people reach the AI bigger. Shows "standing by" on narrow pictures |
| Body pose | chip "Body pose (RTMPose): on" + skeleton lines on people | needed by fight / lookout / climbing / violent-action checks |
| AI detections button | grey/blue/red boxes with class + confidence | shows EVERYTHING the model returns - if a person is not boxed there, the model did not see them |

## Detections ("What the AI watches for" panel on Live Monitoring shows a counter for each)
| Detection | How it works | Needs |
|---|---|---|
| Weapon-like object | RF-DETR knife / bat classes on the full frame and zoomed person crops, confirmed over 3 checks | a trained model for guns (see WEAPON_TRAINING.md) |
| Fighting | two people in close contact with violent arm movement | body pose; people at least ~56 px tall |
| Violent action | one person swinging / striking for 2+ s (hammer, rod) | body pose |
| Snatch and flee | close contact, then one person runs while the other stays | people tracked |
| Escape on a bike | someone gets onto a motorbike after a snatch / weapon / fight / run | motorbike detected |
| Parked bike taken | a bike parked 8+ s is boarded by someone who arrived on foot and rides off (could be the owner) | motorbike detected |
| Climbing | feet rise while body size stays the same, arms up | tracking (pose makes it stricter and better) |
| Jump down from height | fast one-way drop of the feet at constant size | tracking |
| Person down / running / jumping | posture / speed / feet leaving the ground | tracking (pose for posture) |
| Lookout behaviour | repeated head turns left/right while standing | body pose, face toward camera |
| Gate tampering | lingering 8+ s at an entrance / restricted zone while scanning or working with the hands | an entrance or restricted zone drawn |
| Unattended bag | backpack / handbag / suitcase alone for 20 s with nobody near | bag visible |
| Group at ATM / group together | 3+ people together | an ATM zone (or no zones drawn) |
| Group / staring / running toward / hands on a zone | see the Zones section | an armed zone; pose for staring and hands |
| Restricted zone breach | someone touches / enters / comes near a zone set to Restricted | a zone set to Restricted |

## Zones - alerts only for SUSPICIOUS activity
Being in a zone is normal, so a zone does NOT alarm just because somebody walks in or stands there (that only creates
false alarms). Each zone has an alert rule:

| Rule | What alerts |
|---|---|
| **Suspicious activity only** (recommended) | something suspicious happens IN or AT the zone (list below) |
| **Restricted - touch / enter** | the above, PLUS the moment anyone touches or enters it |
| **Restricted - near** | the above, PLUS when anyone comes close to it |
| **Off** | nothing (the zone is only used by the background rules) |

"Suspicious at a zone" means any of:
* a weapon-like object, fighting, violent action (hammer / rod swinging), person down
* **3+ people gathered at the zone for 15+ seconds** (`ZONE_GROUP_MIN_PEOPLE`, `ZONE_GROUP_SECONDS`)
* **repeatedly looking toward the zone** - 3 glances in 12 s, or one 4 s stare, while standing about (needs body pose)
* **running toward the zone**
* jumping, climbing, jumping down from a wall, snatch-and-flee, escape on a bike
* **hands on the zone with vigorous arm movement** - prying / hammering (needs body pose)
* lookout / scanning behaviour, gate tampering, an unattended bag, loitering, an unusual-movement or group rule firing
  for someone in or at the zone

When one of these happens at a zone: the zone flashes red, a red ZONE ALERT bar (naming the zone and the reason) and a beep
appear on Live Monitoring, the event is recorded WITH the zone and raised to the zone's alert severity, and for high /
critical severity a snapshot + clip are saved. The same detections away from any armed zone are still reported, just at
their normal severity.

Editing a zone you already drew: Regions & Zones -> **Edit zone** next to it. Drag a white dot to move it, click on an edge to
add a dot, right-click a dot to remove it ("Reset shape" undoes your changes, "Redraw from scratch" starts the outline
again). Press **Finish zone** and the details form opens pre-filled - change the name, type, the alert rule (one of the 4
rules above) and severity, then **Save changes** ("Back to the outline" returns to the shape without saving).

How to use: Regions & Zones -> pick a video, let it play -> **Draw new zone**, click points, press **Finish zone** -> fill
in the form (new zones default to "Suspicious activity only"; restricted / rear-access zones default to restricted).
Existing zones show a button "Turn on suspicious-activity alerts for all". Use **Live test** to watch it.

## Showcase pages and tools
* **Security Brief** (sidebar): a one-page summary for the last 6 h / 24 h / 3 days / 7 days / 30 days - headline sentences,
  incident counts by type, camera and zone, an hourly timeline, and the most serious incidents with links to their incident
  reports. "Print / Save as PDF" makes a document you can hand to a manager or client.
* **Heatmap** button on Live Monitoring: shows where people spend time in this video (hot = most time); the AI keeps
  collecting it in the background and about the last 2-3 minutes count most.
* **AI detections** button: every raw detection with its class and confidence - shows what the model really sees.
* **Sound on/off** button: mutes the zone-alert beep (remembered by the browser).
* `/pages/check.html`: a system check you can screenshot when something does not work.

## Where everything is stored
Every incident is a row in the `events` table of `backend/storage/app.db` (camera, zone, severity, confidence, people,
snapshot / clip paths, and the AI's details as JSON in `meta`). Look at it with `scripts/db_viewer.py` and print any event
from the Alerts Dashboard -> open an event -> "Incident report".

## Known limits
* Guns are not detected without your own trained model; knives / bats are weak on CCTV.
* People smaller than about 40 px, very dark footage and footage of a screen filmed by a phone are unreliable.
* Rules are heuristics: they can miss events and raise false alarms. Tune them on your own footage.
