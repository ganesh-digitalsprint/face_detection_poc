"""Turns a raw detection event into plain-language text for the Security Brief and incident reports.

The analytics engines keep emitting technical messages ("track #1 ... path-to-displacement ratio 3.5"); those stay
in `Event.message` and `Event.meta` for developers. This module builds the operator-facing wording from the same
structured data, using one template per event kind. It is deterministic (same event -> same text), has no model
or network dependency, and never runs inside the live video loop's critical path beyond a few string operations.

Wording rules: describe only what the data supports, say "may" / "appears similar to" where the system is
inferring, never state an intention or identity, and say so when the evidence is too weak for a conclusion.
"""
from __future__ import annotations

import re
from typing import Any, Callable

EXPLANATION_VERSION = 1

VERIFICATION_LABEL = {
    "open": "AI Detected - Not Yet Verified",
    "under_review": "Under Security Review",
    "confirmed": "Confirmed",
    "false_positive": "False Alarm",
    "closed": "Resolved",
}

_LOW_CONFIDENCE = 0.5
_GOOD_CONFIDENCE = 0.75
_BAND_LABEL = {"business_hours": "business hours", "after_hours": "after hours"}


def _get(event: Any, name: str, default: Any = None) -> Any:
    value = event.get(name, default) if isinstance(event, dict) else getattr(event, name, default)
    return default if value is None else value


def _minutes(seconds: float) -> str:
    s = int(seconds)
    if s < 90:
        return f"{s} seconds"
    m = round(s / 60)
    return f"about {m} minute{'s' if m != 1 else ''}"


def _count(n: int, noun: str = "people") -> str:
    return f"{n} {noun}"


class _Ctx:
    """Everything a template needs, pre-digested from the event."""

    def __init__(self, event: Any) -> None:
        self.meta: dict = _get(event, "meta", {}) or {}
        self.scenario: str = str(_get(event, "scenario", ""))
        self.kind: str = str(self.meta.get("kind") or self.scenario)
        self.severity: str = str(_get(event, "severity", "info"))
        self.confidence: float = float(_get(event, "confidence", 0.0) or 0.0)
        self.zone: str = str(_get(event, "zone_name", "") or "")
        self.camera: str = str(_get(event, "camera_name", "") or "")
        self.zone_type: str = str(self.meta.get("zone_type") or "")
        self.band: str = _BAND_LABEL.get(str(self.meta.get("time_band") or ""), "")
        self.people: int = max(1, len(_get(event, "track_ids", []) or []))

    @property
    def place(self) -> str:
        if self.zone:
            return f"the “{self.zone}” zone"
        if self.camera:
            return f"the area covered by {self.camera}"
        return "the monitored area"

    @property
    def low_confidence(self) -> bool:
        return self.confidence < _LOW_CONFIDENCE


def _t(title: str, observation: str, reason: str, risk: str, action: str) -> dict[str, str]:
    return {"title": title, "observation": observation, "reason": reason, "risk": risk, "action": action}


# --- templates ---------------------------------------------------------------------------------------------

def _movement(c: _Ctx) -> dict[str, str]:
    reasons = [str(r) for r in (c.meta.get("reasons") or [])]
    patterns = set(c.meta.get("patterns") or [])
    if any("pacing" in r for r in reasons):
        patterns.add("pacing")
    approaches = c.meta.get("approaches")
    for r in reasons:
        m = re.search(r"approached .* (\d+) times", r)
        if m:
            patterns.add("repeated_approach")
            approaches = approaches or int(m.group(1))
    verify = "Security staff should verify the person's activity."
    if "repeated_approach" in patterns and "pacing" not in patterns:
        n = f"{approaches} times" if approaches else "several times"
        return _t(
            "Repeated Visits To A Sensitive Area",
            f"A person walked up to {c.place} {n} within a short period, leaving and coming back.",
            "Flagged because the same area was approached repeatedly in a short time, which differs from passing through once.",
            "Repeated visits may be routine (for example, waiting or looking for something), but they can also warrant a closer look. The footage does not show the reason.",
            "Review the footage, and check whether the person has a legitimate reason to be at this location.",
        )
    obs = f"A person was observed repeatedly walking back and forth in {c.place} instead of moving through the branch normally."
    if "repeated_approach" in patterns:
        obs += " The same person also returned to the area several times."
    return _t(
        "Repeated Back-And-Forth Movement",
        obs,
        "Flagged because the person covered a lot of ground without getting anywhere, staying within a small area.",
        f"This repeated activity may indicate loitering, but it can also have an ordinary explanation (for example, waiting for someone). The footage does not show the reason. {verify}",
        "Ask nearby security staff to check on the area, and review the footage to see what the person was doing.",
    )


def _loitering(c: _Ctx) -> dict[str, str]:
    dwell, limit = c.meta.get("dwell_seconds"), c.meta.get("threshold_seconds")
    entrance = c.zone_type == "entrance"
    how_long = f" for {_minutes(dwell)}" if dwell else " for an unusually long period"
    limit_txt = f" (the configured limit for {c.band} is {_minutes(limit)})" if limit and c.band else ""
    return _t(
        "Possible Loitering Near Entrance" if entrance else "Possible Loitering",
        f"A person remained in {c.place}{how_long} with very little movement.",
        f"Flagged because the person stayed in one spot longer than the allowed time{limit_txt}.",
        "Staying in one place for a long time can be harmless (waiting, resting). The footage does not show the person's reason or intention.",
        "Please verify whether the person has a legitimate reason to remain in this area. Escalate to the branch security manager if it continues.",
    )


def _gathering(c: _Ctx) -> dict[str, str]:
    size = c.meta.get("group_size") or c.meta.get("people") or c.people
    held = c.meta.get("held_seconds") or c.meta.get("seconds")
    stay = f" for {_minutes(held)}" if held else ""
    when = f" ({c.band})" if c.band else ""
    return _t(
        "People Gathering In The Area",
        f"{_count(int(size))} were observed gathering and remaining together in {c.place}{stay}{when}.",
        "Flagged because a group stayed together longer than the configured time. Group size and time of day were considered.",
        "Gatherings are often normal (queues, friends meeting). The footage does not indicate that anything is wrong.",
        "Review the footage to decide whether this activity needs attention. No action is needed if it is routine.",
    )


def _intrusion(c: _Ctx) -> dict[str, str]:
    dwell = c.meta.get("dwell_seconds")
    if c.kind == "zone_near":
        return _t(
            "Person Close To A Marked Area",
            f"A person was observed close to {c.place}, an area marked for alerts.",
            "Flagged because this zone is set to alert when someone comes near it.",
            "Being near an area is not the same as entering it. The footage does not show what the person intended.",
            "Check whether the person is staff or has a reason to be there.",
        )
    if c.kind == "zone_touch":
        return _t(
            "Entry Into A Marked Area",
            f"A person was observed entering or touching {c.place}, an area marked for alerts.",
            "Flagged because this zone is set to alert on entry. The system has no access-control record, so it cannot tell whether the person was authorised.",
            "Entry may be unauthorised, or may be by someone with permission. This must be checked by a person.",
            "Please verify whether the individual had permission to access this location.",
        )
    stay = f" for {_minutes(dwell)}" if dwell else ""
    return _t(
        "Presence In Restricted Area After Hours",
        f"A person was observed in {c.place}, a restricted area, while the branch was closed{stay}.",
        "Flagged because the area is restricted, the branch was outside operating hours, and no authorised visit was on record.",
        "This may be an unauthorised presence, or a legitimate visit that was not recorded in the system.",
        "Please verify whether the individual had permission to be in this location, and check the authorised-visit records.",
    )


def _weapon(c: _Ctx) -> dict[str, str]:
    label = str(c.meta.get("label") or "").lower()
    if re.search(r"knife|blade|sharp", label):
        item = "a knife-like item"
    elif re.search(r"bat|rod|hammer|blunt|club", label):
        item = "a rod-like or bat-like item"
    else:
        item = "a handheld item"
    if c.low_confidence:
        obs = (f"The camera detected an object that may resemble {item} near a person's hand. "
               "The object is not clearly identifiable, so this alert requires visual verification by security staff.")
    else:
        obs = (f"The camera detected an object that appears similar to {item} held by a person. "
               "The system cannot confirm what the object actually is.")
    return _t(
        "Possible Handheld Object Of Concern",
        obs,
        "Flagged because an object with a shape similar to a handheld tool or weapon was detected near a person.",
        "Many ordinary objects look like this (umbrellas, tools, sports equipment). The footage alone does not establish that it is a weapon or what the person intends.",
        "Have security staff view the footage or the live camera now to identify the object. Escalate immediately if it is confirmed to be a weapon.",
    )


def _fighting(c: _Ctx) -> dict[str, str]:
    return _t(
        "Possible Physical Altercation",
        f"The camera observed body movements in {c.place} that resemble struggling or fighting.",
        "Flagged because the posture and arm movements matched a pattern the system associates with physical conflict.",
        "Energetic but harmless activity can look similar. The footage has not been confirmed as a fight.",
        "View the footage now. If a person is in danger, alert on-site security and follow the branch emergency procedure.",
    )


def _simple(title: str, obs: str, reason: str, risk: str, action: str) -> Callable[[_Ctx], dict[str, str]]:
    def build(c: _Ctx) -> dict[str, str]:
        fmt = {"place": c.place}
        return _t(title, obs.format(**fmt), reason, risk, action)
    return build


def _group_kind(c: _Ctx) -> dict[str, str]:
    n = c.meta.get("people") or c.people
    secs = c.meta.get("seconds")
    stay = f" for {_minutes(secs)}" if secs else ""
    if c.kind == "atm_group":
        return _t("Several People At The ATM",
                  f"{_count(int(n))} were observed together at {c.place}.",
                  "Flagged because more people than usual were at the ATM at the same time.",
                  "Groups at an ATM can be family or friends. They can also warrant a check for tampering. The footage does not show which.",
                  "Review the footage and check the ATM area if the group stays.")
    if c.kind == "zone_group":
        return _t("People Gathering At A Marked Area",
                  f"{_count(int(n))} were observed gathering at {c.place}{stay}.",
                  "Flagged because several people stayed at an area marked for alerts.",
                  "This may be routine. The footage does not indicate intent.",
                  "Review the footage to determine whether this needs attention.")
    return _t("People Staying Together",
              f"A group of {int(n)} people was observed staying together{stay}.",
              "Flagged because the same group remained together longer than the configured time.",
              "Groups are often normal. The system does not treat a group alone as suspicious.",
              "Review the footage to decide whether this needs attention.")


_BUILDERS: dict[str, Callable[[_Ctx], dict[str, str]]] = {
    "movement": _movement,
    "loitering": _loitering,
    "gathering": _gathering,
    "intrusion": _intrusion,
    "zone_touch": _intrusion,
    "zone_near": _intrusion,
    "weapon": _weapon,
    "fighting": _fighting,
    "group": _group_kind,
    "atm_group": _group_kind,
    "zone_group": _group_kind,
    "running": _simple(
        "Person Running", "A person was observed running in {place}.",
        "Flagged because the person's speed was above normal walking pace.",
        "Running is usually harmless. It is only noted because it can accompany other events.",
        "No action needed unless other alerts appear for the same area."),
    "jumping": _simple(
        "Sudden Jump Observed", "A person was observed jumping in {place}.",
        "Flagged because the person's body moved upward sharply.",
        "This is usually harmless and is recorded for context only.",
        "No action needed unless other alerts appear for the same area."),
    "fallen": _simple(
        "Person May Have Fallen", "A person appeared to be lying down or to have fallen in {place}.",
        "Flagged because a lying posture was held for a period of time.",
        "The person may need help, or may simply be resting or bending down. The footage does not show which.",
        "Check on the person promptly, in person or via the live camera."),
    "violent_action": _simple(
        "Forceful Arm Movements", "A person was observed making repeated forceful arm movements in {place}.",
        "Flagged because sustained, vigorous arm movement matched a pattern the system associates with striking or forcing something.",
        "This can be harmless (exercise, waving). It may also indicate damage or force. The footage has not been confirmed.",
        "View the footage and check the area if the movement continues."),
    "snatch_flee": _simple(
        "Possible Snatch And Run", "Two people were observed in close contact, after which one ran away while the other stayed.",
        "Flagged because close contact followed by one person running off matched a theft-like pattern.",
        "This may be a theft, or an ordinary interaction such as a greeting. The footage does not establish what happened.",
        "Check on the person who stayed behind and review the footage now."),
    "vehicle_escape": _simple(
        "Person Left On A Vehicle After Unusual Activity", "A person was observed getting onto a vehicle shortly after unusual activity.",
        "Flagged because the person got on a vehicle soon after another alert-worthy action.",
        "The vehicle may simply belong to the person. The footage does not show a link to any wrongdoing.",
        "Review the preceding events on this camera and verify."),
    "vehicle_takeoff": _simple(
        "Parked Vehicle Taken", "A vehicle that had been parked for a while was ridden away by a person who arrived on foot.",
        "Flagged because a parked vehicle left with someone who had just walked up to it.",
        "This may well be the owner. The footage does not show ownership.",
        "Verify with the footage whether the person arrived with a key or acted unusually."),
    "scanning": _simple(
        "Person Looking Around Repeatedly", "A person was observed repeatedly looking left and right while staying in {place}.",
        "Flagged because repeated head turning while standing still matched a pattern the system calls lookout behaviour.",
        "This can be someone waiting for a person or looking for directions. The footage does not show intent.",
        "Review the footage and check whether the person has a reason to be there."),
    "gate_tampering": _simple(
        "Possible Interference With A Gate Or Entrance", "A person stayed at {place} and was observed looking around or working with their hands.",
        "Flagged because the person stayed a long time at an entrance or gate while looking around or using their hands.",
        "This may be someone waiting or fixing something. The footage does not establish tampering.",
        "Check the gate or entrance area and ask the person if appropriate."),
    "climbing": _simple(
        "Possible Climbing", "A person appeared to be climbing in or near {place}.",
        "Flagged because the person's body rose while the posture matched climbing a wall, fence or gate.",
        "This may be an attempt to enter or leave an area, or a false reading. The footage must confirm it.",
        "View the footage now and check the boundary if confirmed."),
    "drop_from_height": _simple(
        "Sudden Drop From Height", "A person appeared to drop sharply, as if jumping down from a height, in {place}.",
        "Flagged because the person's position fell quickly in under a second.",
        "This may be a fall, a jump, or a misreading by the system. The footage must confirm it.",
        "Check the area now; the person may be hurt or may have crossed a boundary."),
    "unattended_bag": _simple(
        "Possible Unattended Item", "An item appeared to be left alone with nobody nearby in {place}.",
        "Flagged because the item stayed without anyone close to it for longer than the configured time.",
        "It may belong to someone who stepped away. The footage does not show what is inside or who owns it.",
        "Check the item in person without touching it, and follow the branch procedure for unattended items."),
    "zone_watching": _simple(
        "Person Repeatedly Looking At A Marked Area", "A person repeatedly looked toward {place} while standing nearby.",
        "Flagged because the person's attention returned to an area marked for alerts several times.",
        "This may be coincidence. The footage does not show intent.",
        "Review the footage and observe the person if they stay."),
    "zone_rush": _simple(
        "Person Running Toward A Marked Area", "A person was observed running toward {place}.",
        "Flagged because a fast approach was made to an area marked for alerts.",
        "The person may be hurrying for an ordinary reason. The footage does not show intent.",
        "Check the area and the footage promptly."),
    "zone_tamper": _simple(
        "Hands Working On A Marked Area", "A person was observed with their hands on {place} and moving their arms vigorously.",
        "Flagged because hands stayed on an area marked for alerts while arm movement was vigorous.",
        "This may be a legitimate action such as cleaning or repair. The footage must show what was happening.",
        "Check the area in person and review the footage."),
    "simulated": _simple(
        "Simulated Test Alert", "This is a simulated alert created for testing. No real activity was observed.",
        "Created manually to test the alert pipeline.",
        "No real security concern.", "No action is required."),
}


def _generic(c: _Ctx) -> dict[str, str]:
    return _t(
        "Unusual Activity Flagged",
        f"The monitoring system flagged unusual activity in {c.place}, but the available information is not enough to describe it in detail.",
        "The activity matched an alert rule. The system did not record a more specific reason.",
        "The available footage is insufficient to confirm what happened.",
        "Please review the saved footage or live camera and verify the activity.",
    )


# --- public API --------------------------------------------------------------------------------------------

def _severity_basis(c: _Ctx) -> str:
    parts = [f"the type of activity ({c.kind.replace('_', ' ')})"]
    if c.meta.get("dwell_seconds") or c.meta.get("held_seconds"):
        parts.append("how long it lasted")
    if c.band == "after hours":
        parts.append("that it happened after hours")
    if c.zone:
        parts.append("the zone where it happened")
    parts.append(f"detection reliability ({_reliability(c.confidence)})")
    return f"Rated {c.severity.upper()} based on " + ", ".join(parts[:-1]) + f" and {parts[-1]}."


def _reliability(conf: float) -> str:
    return "low" if conf < _LOW_CONFIDENCE else "moderate" if conf < _GOOD_CONFIDENCE else "good"


def explain_event(event: Any) -> dict[str, Any]:
    """Structured, human-readable interpretation of one event (an `Event` or a dict with the same fields)."""
    c = _Ctx(event)
    try:
        body = _BUILDERS.get(c.kind, _generic)(c)
    except Exception:  # never let wording break event handling; fall back to a safe generic text
        body = _generic(c)
    caution = ""
    if c.low_confidence:
        caution = "The available evidence is not strong enough for a reliable conclusion, so this alert needs verification."
    return {
        "version": EXPLANATION_VERSION,
        "category": c.kind,
        **body,
        "reliability": _reliability(c.confidence),
        "caution": caution,
        "severity_basis": _severity_basis(c),
    }


def verification_label(status: str) -> str:
    return VERIFICATION_LABEL.get(status, VERIFICATION_LABEL["open"])


def get_explanation(event: Any) -> dict[str, Any]:
    """Stored explanation if present and current, otherwise a freshly generated one (older events have none)."""
    stored = (_get(event, "meta", {}) or {}).get("explanation")
    if isinstance(stored, dict) and stored.get("version") == EXPLANATION_VERSION and stored.get("title"):
        return stored
    return explain_event(event)
