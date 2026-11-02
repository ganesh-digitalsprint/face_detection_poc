# Testing notes - what was actually verified, and what wasn't

This POC was built in a sandboxed environment with **no internet access**,
which means `uv sync` could not be run there and the application could not
be started end-to-end. This file is a transparent account of exactly what
was and wasn't checked, so you know where to look first if something doesn't
work on your machine.

## Verified by actually running the code

- **Every Python file compiles** (`python -m py_compile` across all 69
  files) and a custom static checker confirmed every `from app.X import Y`
  resolves to something that actually exists - no typos in cross-module
  references.
- **Every JavaScript file passes `node --check`** (syntax-valid), and a
  script cross-checked that every asset path (`<script src>`, `<link
  href>`) referenced in the HTML actually exists on disk, and that
  `getElementById` targets used by each page's script exist in that page's
  markup.
- **The motion-based person detector and tracker**, exercised directly with
  synthetic frames: confirmed a moving object keeps one stable track ID,
  confirmed a *stationary* object's track survives the background
  subtractor's natural tendency to absorb it (this was found to be a real
  bug during development and fixed - see `motion_detector.py` and
  `tracker.py`'s comments for the full explanation).
- **The scripted synthetic demo scene**, run through the real detector and
  tracker: confirmed the loitering, and gathering acts produce the expected
  number of simultaneous tracks.
- **The four rule-based scenario engines** (loitering, gathering,
  after-hours, and the zone point-in-polygon lookup they all depend on),
  exercised with synthetic tracks against real zone polygons: confirmed
  correct behaviour in both directions - e.g. the after-hours engine does
  **not** fire during business hours, and correctly fires on a closed
  Sunday after the configured minimum dwell.
- **The demo video generator script**, run end-to-end: produced a real,
  readable `.mp4` file.
- **OpenCV's face cascade and LBPH face recognizer** (`cv2.face`), confirmed
  available and importable in this environment - both ship inside
  `opencv-contrib-python` with no extra download, which the guard
  recognition feature depends on.

## Not verified (could not install dependencies offline)

- `fastapi`, `pydantic`, `pydantic-settings`, `sqlalchemy`, `motor`,
  `asyncpg`, `aiomysql`, `oracledb`, `httpx`, `aiofiles`, `uvicorn` are **not
  installed** in the sandbox this was built in, so:
  - The API layer (every route in `app/api/routes/`) has been reviewed
    carefully but never actually invoked.
  - The full FastAPI app has never been started; `app/main.py`'s lifespan,
    router wiring, and static mounts are unverified beyond manual review.
  - No real database connection (SQLite, PostgreSQL, MySQL, Oracle, or
    MongoDB) has been exercised - the SQL/Mongo repository implementations
    were reviewed line-by-line against the SQLAlchemy 2.0 / Motor APIs as
    documented, but not run.
  - The MJPEG streaming endpoints, the WebSocket alert feed, and the
    frontend-to-backend integration as a whole have not been exercised.
  - File uploads, guard photo uploads, and the CSV export endpoint have not
    been exercised.
- **The frontend has never been rendered in a real browser** against a live
  backend - only statically checked as described above.

## What this means for you, practically

Run `uv sync` and start the server as the first thing you do, before
customising anything, so any environment-specific issue (a missing system
library for one of the database drivers, a port conflict, etc.) surfaces
immediately against a known-good starting point. If something in the API
layer doesn't behave as documented, that's the most likely place for a bug
to have slipped through, precisely because it's the layer that couldn't be
exercised here - please report it rather than assuming it's a known
limitation.
