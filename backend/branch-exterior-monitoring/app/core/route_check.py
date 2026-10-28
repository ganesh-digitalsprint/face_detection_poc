"""Version-proof helpers for the server's self-checks (no web-framework imports, so they are easy to test).

registered_routes(app)   every (METHOD, path) the running app really serves
missing_routes(app, required)
format_validation_errors(errors)   turns a FastAPI/pydantic 422 into one readable sentence

Why not just loop over `app.routes`? Newer FastAPI versions can nest included routers instead of flattening them,
and that made an earlier version of this check report EVERY route as missing even though the app worked. This
version walks nested routes AND asks the app's OpenAPI description (which is the same in every version).
"""
from __future__ import annotations

from collections.abc import Iterable, Iterator


def _walk(routes: Iterable, prefix: str = "", depth: int = 0) -> Iterator[tuple[str, str]]:
    if depth > 6:
        return
    for r in routes or []:
        path = prefix + (getattr(r, "path", "") or "")
        methods = getattr(r, "methods", None)
        if methods:
            for m in methods:
                yield (str(m).upper(), path)
        sub = getattr(r, "routes", None)
        if sub is None:
            inner = getattr(r, "app", None) or getattr(r, "router", None)
            sub = getattr(inner, "routes", None)
        if sub:
            yield from _walk(sub, path, depth + 1)


def registered_routes(app) -> set[tuple[str, str]]:
    have = set(_walk(getattr(app, "routes", [])))
    try:
        spec = app.openapi()
        for path, ops in (spec.get("paths") or {}).items():
            for method in ops:
                have.add((str(method).upper(), path))
    except Exception:
        pass   # the walk above is still enough on most versions
    return have


def missing_routes(app, required: list[tuple[str, str]]) -> list[str]:
    have = registered_routes(app)
    return [f"{m} {p}" for m, p in required if (m, p) not in have]


def format_validation_errors(errors) -> str:
    """[{'loc': ('body','alert_mode'), 'msg': "Input should be 'off' ..."}] -> "Invalid input - alert_mode: Input should be ..." """
    parts = []
    for err in errors or []:
        try:
            loc = [str(x) for x in (err.get("loc") or ()) if x not in ("body", "query", "path")]
            msg = str(err.get("msg", "invalid value"))
        except AttributeError:
            parts.append(str(err))
            continue
        parts.append((".".join(loc) + ": " if loc else "") + msg)
    return ("Invalid input - " + "; ".join(parts)) if parts else "Invalid input"
