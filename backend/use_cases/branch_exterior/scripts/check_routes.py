"""Static check: does every API call the web pages make have a matching route in the backend,
and is every route module actually registered in app/main.py?

Needs nothing installed and does not start the server:
    python scripts/check_routes.py

It reads the source code only:
  * backend/app/api/routes/*.py   - @router.get/post/patch/delete("...") with each router's prefix
  * backend/app/main.py           - which route modules are passed to app.include_router(...)
  * frontend/**/*.js, *.html      - api.get/post/patch/del("...") and fetch("/api/...") calls
Exit code 1 when something is missing (so it can also be used in a script).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTES_DIR = ROOT / "app" / "api" / "routes"
FRONTEND = ROOT.parent / "frontend"
API_PREFIX = "/api"

# Route modules that exist on purpose but are NOT registered (the old demo-alert simulator that was
# removed from the app). Listed here so the checker does not report them.
INTENTIONALLY_UNREGISTERED = {"simulate"}

METHODS = {"get": "GET", "post": "POST", "patch": "PATCH", "delete": "DELETE", "put": "PUT", "websocket": "WS"}


def load_routes() -> tuple[list[tuple[str, str, str]], dict[str, bool]]:
    routes, registered = [], {}
    main_src = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    for f in sorted(ROUTES_DIR.glob("*.py")):
        if f.name == "__init__.py":
            continue
        src = f.read_text(encoding="utf-8")
        m = re.search(r'APIRouter\(([^)]*)\)', src)
        if not m:
            continue
        pm = re.search(r'prefix\s*=\s*"([^"]*)"', m.group(1))
        prefix = pm.group(1) if pm else ""
        if f.stem in INTENTIONALLY_UNREGISTERED:
            continue
        registered[f.stem] = bool(re.search(rf'include_router\(\s*(?:\w+\.)?{re.escape(f.stem)}(?:_routes)?\.router|include_router\(\s*{re.escape(f.stem)}\.router|settings_routes\.router' if f.stem == "settings" else rf'include_router\(\s*{re.escape(f.stem)}\.router', main_src))
        for dm in re.finditer(r'@router\.(get|post|patch|delete|put|websocket)\(\s*"([^"]*)"', src):
            routes.append((METHODS[dm.group(1)], API_PREFIX + prefix + dm.group(2), f.stem))
    return routes, registered


def norm(path: str) -> str:
    path = path.split("?")[0]
    path = re.sub(r"\$\{[^}]*\}", "{}", path)      # JS template parts
    path = re.sub(r"\{[^}/]*\}", "{}", path)       # FastAPI path parameters
    return path.rstrip("/") or "/"


def frontend_calls() -> list[tuple[str, str, str]]:
    calls = []
    pat = re.compile(r'api\.(get|post|patch|del|postForm)\(\s*[`"\']([^`"\']+)[`"\']')
    fpat = re.compile(r'fetch\(\s*[`"\'](/api[^`"\']+)[`"\']')
    for f in list(FRONTEND.rglob("*.js")) + list(FRONTEND.rglob("*.html")):
        text = f.read_text(encoding="utf-8", errors="ignore")
        for m in pat.finditer(text):
            verb = {"get": "GET", "post": "POST", "patch": "PATCH", "del": "DELETE", "postForm": "POST"}[m.group(1)]
            calls.append((verb, API_PREFIX + m.group(2), f.relative_to(FRONTEND).as_posix()))
        for m in fpat.finditer(text):
            calls.append(("GET", m.group(1), f.relative_to(FRONTEND).as_posix()))
        # pictures / videos loaded straight from an /api/... URL (img src, EventSource, links)
        for m in re.finditer(r'[`"\'](/api/[^`"\'\s<>]+)[`"\']', text):
            calls.append(("GET", m.group(1), f.relative_to(FRONTEND).as_posix()))
    return calls


def main() -> int:
    routes, registered = load_routes()
    table = {(m, norm(p)) for m, p, _ in routes}
    bad = 0

    print("== route modules registered in app/main.py ==")
    for name, ok in registered.items():
        print(f"  {'OK     ' if ok else 'MISSING'}  {name}")
        bad += 0 if ok else 1

    print("\n== frontend API calls with no matching backend route ==")
    seen = set()
    for verb, path, where in frontend_calls():
        key = (verb, norm(path))
        if key in seen:
            continue
        seen.add(key)
        # a /api/streams/<id>/... call in an <img src> is a GET and is matched the same way
        if key not in table:
            print(f"  MISSING  {verb:6} {path}    (used in {where})")
            bad += 1
    if bad == 0:
        print("  none - every call has a route")
    print(f"\n{'ALL GOOD' if bad == 0 else str(bad) + ' PROBLEM(S) FOUND'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
