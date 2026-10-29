"""Task 5 - AI-based anomaly identification: turns the weapon-holding and
action-recognition flags already attached to each `Track` (by the weapon
detector and action recognizer in the per-camera pipeline) into scenario
signals, and applies the hard override rule from the workflow document's
fusion engine (5.5): a weapon held by a person forces the incident to
CRITICAL regardless of what the rule-based engines alone would have said.
"""
from __future__ import annotations

from app.schemas.event import SEVERITY_ORDER, Severity
from app.schemas.settings import ThresholdConfig
from app.services.analytics.signals import ScenarioSignal
from app.services.analytics.zone_engine import Zone
from app.services.detection.tracker import Track


def build_anomaly_signals(
    tracks: dict[int, Track],
    zone_of_track: dict[int, Zone | None],
    thresholds: ThresholdConfig,
) -> list[ScenarioSignal]:
    signals: list[ScenarioSignal] = []
    for tid, trk in tracks.items():
        zone = zone_of_track.get(tid)

        if trk.weapon_flag and trk.weapon_confidence >= thresholds.weapon_confidence_threshold:
            signals.append(
                ScenarioSignal(
                    scenario="anomaly",
                    track_ids=[tid],
                    zone=zone,
                    confidence=trk.weapon_confidence,
                    severity_hint="critical",
                    message=(
                        f"Track #{tid} appears to be holding a weapon-like object "
                        f"({trk.weapon_label or 'unclassified'}, {trk.weapon_method or 'detector'} "
                        f"{trk.weapon_confidence:.0%}) - verify by a person."
                    ),
                    meta={"kind": "weapon", "label": trk.weapon_label, "method": trk.weapon_method or "rfdetr"},
                    # Deliberately NOT keyed by track_id: this heuristic
                    # detector and the tracker it runs on are both prone to ID
                    # churn, which previously meant every ID change produced
                    # a brand-new "critical" event - a real flooding bug found
                    # in testing. One camera has, at most, one open "weapon
                    # present" incident at a time; every track involved is
                    # still recorded in the merged track_ids list.
                    dedupe_key="anomaly-weapon",
                )
            )

        if trk.action_label == "fighting" and trk.action_confidence >= thresholds.fight_confidence_threshold:
            signals.append(
                ScenarioSignal(
                    scenario="anomaly",
                    track_ids=[tid],
                    zone=zone,
                    confidence=trk.action_confidence,
                    severity_hint="high",
                    message=f"Track #{tid} shows pose/movement consistent with fighting/struggling - verify by a person.",
                    meta={"kind": "fighting", "method": trk.action_method or "pose", **trk.action_debug},
                    dedupe_key="anomaly-fighting",  # camera-scoped, not track-scoped - see weapon comment above
                )
            )
        elif trk.action_label == "running" and trk.action_confidence >= 0.5:
            signals.append(
                ScenarioSignal(
                    scenario="anomaly", track_ids=[tid], zone=zone, confidence=trk.action_confidence,
                    severity_hint="low",
                    message=f"Track #{tid} is running.",
                    meta={"kind": "running", "method": "track_speed"},
                    dedupe_key="anomaly-running",
                )
            )
        elif trk.action_label == "jumping" and trk.action_confidence >= 0.5:
            signals.append(
                ScenarioSignal(
                    scenario="anomaly", track_ids=[tid], zone=zone, confidence=trk.action_confidence,
                    severity_hint="low",
                    message=f"Track #{tid} jumped (feet left the ground).",
                    meta={"kind": "jumping", "method": "track_motion"},
                    dedupe_key="anomaly-jumping",
                )
            )
        elif trk.action_label == "fallen" and trk.action_confidence >= 0.5:
            signals.append(
                ScenarioSignal(
                    scenario="anomaly",
                    track_ids=[tid],
                    zone=zone,
                    confidence=trk.action_confidence,
                    severity_hint="medium",
                    message=f"Track #{tid} may have fallen (lying posture held) - verify by a person.",
                    meta={"kind": "fallen", "method": trk.action_method or "box"},
                    dedupe_key="anomaly-fallen",  # camera-scoped, not track-scoped - see weapon comment above
                )
            )
    return signals


def apply_weapon_override(signal: ScenarioSignal, weapon_track_ids: set[int], thresholds: ThresholdConfig) -> ScenarioSignal:
    """Task 5.5's hard override: any signal that shares a track with an
    active weapon-holding flag is forced to CRITICAL severity."""
    if not thresholds.critical_override_on_weapon:
        return signal
    if weapon_track_ids.intersection(signal.track_ids):
        signal.severity_hint = "critical"
        signal.meta = {**signal.meta, "override": "weapon_present"}
    return signal


def highest_severity(severities: list[Severity]) -> Severity:
    if not severities:
        return "info"
    return max(severities, key=lambda s: SEVERITY_ORDER[s])