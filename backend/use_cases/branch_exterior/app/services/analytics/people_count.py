"""People counting: how many people are in view, and are they alone or in groups?

Counts only *confirmed, currently visible* person tracks (see bytetrack.py).

Grouping (v2 - stable and scale-aware)
  Two people are "close" when EITHER
     * their box centres are within `distance_factor` x their average body height, OR
     * their boxes touch / overlap or the gap between them is under 25% of body height
  (people at clearly different depths - one far, one near - never count as close).
  To stop groups flickering from frame to frame:
     * two people must stay close for `form_seconds` (default 1 s) before they are grouped, and
     * a group only breaks after the pair has been apart for `break_seconds` (default 2 s).

  individuals : people not in any group
  groups      : list of group sizes (a pair counts as a group of 2)
  largest     : size of the largest group
  unique_seen : distinct people (track IDs) seen since the video started/looped
  peak        : highest number of people in view at once in this session
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

from app.services.detection.tracker import Track


@dataclass
class PeopleStats:
    people_now: int = 0
    individuals: int = 0
    groups: list[int] = field(default_factory=list)
    largest_group: int = 0
    unique_seen: int = 0
    peak: int = 0
    group_of_track: dict[int, int] = field(default_factory=dict)  # track_id -> group index (-1 = individual)
    group_members: list[list[int]] = field(default_factory=list)  # member track ids per group

    def summary(self) -> str:
        if self.people_now == 0:
            return "no people"
        parts = []
        if self.individuals:
            parts.append(f"{self.individuals} alone")
        if self.groups:
            parts.append("groups: " + "+".join(str(g) for g in sorted(self.groups, reverse=True)))
        return f"{self.people_now} people ({', '.join(parts)})"


def _close(da, db, factor: float) -> bool:
    (ax, ay), (bx, by) = da.centroid, db.centroid
    avg_h = (da.height + db.height) / 2.0
    max_h = float(max(da.height, db.height))
    if abs(da.y2 - db.y2) > 0.6 * max_h:
        return False  # very different distance from the camera
    if math.hypot(ax - bx, ay - by) <= factor * avg_h:
        return True
    gx = max(0.0, max(da.x1, db.x1) - min(da.x2, db.x2))
    gy = max(0.0, max(da.y1, db.y1) - min(da.y2, db.y2))
    return math.hypot(gx, gy) <= 0.25 * avg_h


class PeopleCounter:
    def __init__(self, distance_factor: float = 0.9, form_seconds: float = 1.0, break_seconds: float = 2.0) -> None:
        self._factor = distance_factor
        self._form = form_seconds
        self._break = break_seconds
        self._seen: set[int] = set()
        self._peak = 0
        # (a, b) -> {"since": first time close (None when apart), "apart": first time apart, "linked": bool}
        self._pairs: dict[tuple[int, int], dict] = {}

    def reset_session(self) -> None:
        self._seen.clear()
        self._peak = 0
        self._pairs.clear()

    def update(self, person_tracks: dict[int, Track], distance_factor: float | None = None, now: float | None = None) -> PeopleStats:
        now = time.time() if now is None else now
        factor = self._factor if distance_factor is None else distance_factor
        ids = sorted(person_tracks.keys())

        # --- update pair state ---------------------------------------------------------
        live_pairs = set()
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                key = (ids[i], ids[j])
                live_pairs.add(key)
                st = self._pairs.setdefault(key, {"since": None, "apart": now, "linked": False})
                if _close(person_tracks[ids[i]].detection, person_tracks[ids[j]].detection, factor):
                    st["apart"] = None
                    if st["since"] is None:
                        st["since"] = now
                    if now - st["since"] >= self._form:
                        st["linked"] = True
                else:
                    st["since"] = None
                    if st["apart"] is None:
                        st["apart"] = now
                    if st["linked"] and now - st["apart"] >= self._break:
                        st["linked"] = False
        for key in [k for k in self._pairs if k not in live_pairs]:
            del self._pairs[key]

        # --- union-find over linked pairs -------------------------------------------------
        parent = {i: i for i in ids}

        def find(i: int) -> int:
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        for (a, b), st in self._pairs.items():
            if st["linked"]:
                ra, rb = find(a), find(b)
                if ra != rb:
                    parent[ra] = rb

        clusters: dict[int, list[int]] = {}
        for i in ids:
            clusters.setdefault(find(i), []).append(i)

        stats = PeopleStats(people_now=len(ids))
        gi = 0
        for members in clusters.values():
            if len(members) == 1:
                stats.individuals += 1
                stats.group_of_track[members[0]] = -1
            else:
                stats.groups.append(len(members))
                stats.group_members.append(sorted(members))
                for m in members:
                    stats.group_of_track[m] = gi
                gi += 1
        stats.largest_group = max(stats.groups) if stats.groups else (1 if ids else 0)

        self._seen.update(ids)
        self._peak = max(self._peak, len(ids))
        stats.unique_seen = len(self._seen)
        stats.peak = self._peak
        return stats
