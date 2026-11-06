"""Upload a clip through the Grill Gate API, process it, and print the detected gate transitions.

  python run_video_demo.py path/to/clip.mp4 --config video_demo_config.json --closed-t 0.5 --open-t 5.1

The config file holds "calibration", "zones" and optionally "alert_configuration". A calibration without
"reference_frame" uses the clip's decoded size; one with a different size is rejected by the API.
--closed-t/--open-t measure the gate endpoints on two frames and store them on the gate zone before processing.
The operator key is read from the VAULT_ROOM_API_KEY environment variable.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

BASE = "/api/v1/grill-gate/videos"
TERMINAL = {"COMPLETED", "FAILED", "CANCELLED"}


def _checked(response):
    if response.status_code >= 400:
        raise SystemExit(f"{response.request.method} {response.request.url.path} failed ({response.status_code}): {response.text}")
    return response


def run_demo(client, clip: Path, config: dict, *, closed_t=None, open_t=None, poll_seconds=2.0, out=print) -> dict:
    """Run one job from upload to a terminal status and return its results."""
    with clip.open("rb") as stream:
        job_id = _checked(client.post(BASE, files={"video": (clip.name, stream, "video/mp4")})).json()["job_id"]
    job = _checked(client.get(f"{BASE}/{job_id}")).json()
    out(f"Job {job_id}: {job['width']}x{job['height']}, {job['fps']} fps, {job['duration_seconds']} s, {job['total_frames']} frames")
    config = json.loads(json.dumps(config))
    if config.get("calibration"):
        config["calibration"].setdefault("reference_frame", {"width": job["width"], "height": job["height"]})
    _checked(client.put(f"{BASE}/{job_id}/config", json=config))
    if closed_t is not None and open_t is not None:
        endpoints = _checked(client.post(f"{BASE}/{job_id}/measure-endpoints", json={"closed_t": closed_t, "open_t": open_t})).json()["endpoints"]
        out(f"Measured endpoints: {endpoints}")
        gate_zone = next(zone for zone in config["zones"] if zone.get("zone_type") == "gate_leaf_roi")
        properties = gate_zone.setdefault("properties", {}) or {}
        gate_zone["properties"] = {**properties, "gate_geometry": {**properties.get("gate_geometry", {}), **endpoints}}
        _checked(client.put(f"{BASE}/{job_id}/config", json=config))
    _checked(client.post(f"{BASE}/{job_id}/start"))
    while True:
        job = _checked(client.get(f"{BASE}/{job_id}")).json()
        progress = "?" if job["progress"] is None else f"{job['progress'] * 100:.0f}%"
        out(f"{job['status']:<12} {progress:>5}  {job['processed_frames']}/{job['total_frames']} frames  {job['processing_fps']} fps")
        if job["status"] in TERMINAL:
            break
        time.sleep(poll_seconds)
    results = _checked(client.get(f"{BASE}/{job_id}/results", params={"limit": 500})).json()
    if job["error"]:
        out(f"Error: {job['error']}")
    out("\nGate transitions (video time):")
    for item in results["transitions"]:
        out(f"  {item.get('video_time_seconds') or 0:8.2f} s  {item['from_state']} -> {item['to_state']}  ({item.get('reason')})")
    if not results["transitions"]:
        out("  none")
    crossings = [item for item in results["items"] if item["event_type"] == "CROSSING_COMPLETED"]
    out(f"\nCrossings: {len(crossings)}")
    for item in crossings:
        out(f"  {item['video_time_seconds']:8.2f} s  {item['direction']}  track {item['track_id']}")
    out(f"Mesh events: {len(results['items']) - len(crossings)}")
    out(f"Alerts: {len(results['alerts']) if results['alerts_available'] else 'Alert Service unavailable'}")
    return {"job": job, "results": results}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("clip", type=Path)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--closed-t", type=float)
    parser.add_argument("--open-t", type=float)
    parser.add_argument("--base-url", default="http://localhost:8010")
    args = parser.parse_args()
    key = os.environ.get("VAULT_ROOM_API_KEY", "")
    if not key:
        sys.exit("Set VAULT_ROOM_API_KEY to the server's operator key")

    import httpx

    with httpx.Client(base_url=args.base_url, headers={"X-API-Key": key}, timeout=300) as client:
        outcome = run_demo(client, args.clip, json.loads(args.config.read_text(encoding="utf-8")),
                           closed_t=args.closed_t, open_t=args.open_t)
    sys.exit(0 if outcome["job"]["status"] == "COMPLETED" else 1)


if __name__ == "__main__":
    main()
