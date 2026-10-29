"""Live local service-to-service check: Vault + Branch publishers -> a real Alert Service process.

Starts the real Alert Service (uvicorn, temporary SQLite database, fixed test tokens), then runs the
real Branch publisher and the real Vault adapter in their own interpreters against it over HTTP, and
verifies the result through the Alert Service operator API.

Not covered: Vault's and Branch's full applications, PostgreSQL, Qdrant, cameras. Nothing here touches
real databases or vector stores. Run with any Python that has httpx (the Alert Service environment):

    python live_alert_integration.py --branch-python <py3.11> --vault-python <py3.12> [--port 8012]
Optional: --branch-pythonpath / --vault-pythonpath for extra import directories.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
ALERT_DIR = BACKEND / "services" / "alert_service"
BRANCH_DIR = BACKEND / "use_cases" / "branch_exterior"
VAULT_DIR = BACKEND / "use_cases" / "vault_monitoring"

BRANCH_TOKEN = "live-branch-producer-token"
VAULT_TOKEN = "live-vault-producer-token"
OPERATOR_ALL = "live-operator-all-token"
OPERATOR_VAULT_ONLY = "live-operator-vault-only-token"

results: list[tuple[bool, str]] = []


def check(condition: bool, label: str) -> None:
    results.append((bool(condition), label))
    print(("PASS " if condition else "FAIL ") + label, flush=True)


def free(port: int) -> bool:
    with socket.socket() as sock:
        return sock.connect_ex(("127.0.0.1", port)) != 0


def run_driver(python: str, cwd: Path, script: str, scenario: dict, extra_path: str = "") -> dict:
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(p for p in (str(cwd), extra_path) if p), "DEBUG": "false"}
    out = subprocess.run([python, str(HERE / script), json.dumps(scenario)], cwd=cwd, env=env,
                         capture_output=True, text=True, timeout=180)
    if out.returncode != 0:
        print(out.stderr[-2000:])
        raise SystemExit(f"{script} failed")
    return json.loads(out.stdout.strip().splitlines()[-1])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8012)
    parser.add_argument("--branch-python", required=True)
    parser.add_argument("--vault-python", required=True)
    parser.add_argument("--branch-pythonpath", default="")
    parser.add_argument("--vault-pythonpath", default="")
    args = parser.parse_args()
    if not free(args.port):
        raise SystemExit(f"port {args.port} is in use; choose another with --port")
    base = f"http://127.0.0.1:{args.port}"
    dead = f"http://127.0.0.1:{args.port + 1}"  # nothing listens here: simulates an Alert Service outage
    if not free(args.port + 1):
        raise SystemExit(f"port {args.port + 1} must be free for the outage simulation")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        env = {
            **os.environ,
            "PYTHONPATH": str(ALERT_DIR),
            "ALERT_DATABASE_URL": f"sqlite:///{(tmp_path / 'alert.db').as_posix()}",
            "ALERT_PRODUCER_CREDENTIALS": json.dumps({
                BRANCH_TOKEN: {"use_case": "branch_exterior", "producer": "branch-exterior-monitoring"},
                VAULT_TOKEN: {"use_case": "vault_monitoring", "producer": "vault-monitoring"},
            }),
            "ALERT_OPERATOR_CREDENTIALS": json.dumps({
                OPERATOR_ALL: {"actor_id": "live-operator", "use_cases": ["*"]},
                OPERATOR_VAULT_ONLY: {"actor_id": "vault-operator", "use_cases": ["vault_monitoring"]},
            }),
            "ALERT_NOTIFICATION_WEBHOOK_URL": "",
        }
        server = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
                                   "--port", str(args.port)], cwd=ALERT_DIR, env=env,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(60):
                try:
                    if httpx.get(f"{base}/health", timeout=1).status_code == 200:
                        break
                except httpx.HTTPError:
                    time.sleep(0.5)
            else:
                raise SystemExit("Alert Service did not become healthy")
            check(True, "Alert Service process started and /health is 200")
            exercise(base, dead, tmp_path, args)
        finally:
            server.terminate()
            try:
                server.wait(10)
            except subprocess.TimeoutExpired:
                server.kill()

    failed = [label for ok, label in results if not ok]
    print(f"\n{len(results) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0


def exercise(base: str, dead: str, tmp: Path, args) -> None:
    op = {"Authorization": f"Bearer {OPERATOR_ALL}"}
    branch = lambda scenario: run_driver(args.branch_python, BRANCH_DIR, "_branch_driver.py", scenario,
                                         args.branch_pythonpath)
    vault = lambda scenario: run_driver(args.vault_python, VAULT_DIR, "_vault_driver.py", scenario,
                                        args.vault_pythonpath)

    # --- Branch -> Alert Service ------------------------------------------------------------------
    outbox = str(tmp / "branch-outbox-1")
    r = branch({"base_url": base, "token": BRANCH_TOKEN, "outbox": outbox,
                "events": [{"id": "b-1", "severity": "medium"}, {"id": "b-2", "severity": "critical",
                                                                 "scenario": "intrusion"}]})
    check(r["pending"] == 0 and r["failed"] == 0, "Branch: two new events delivered, outbox empty")
    r = branch({"base_url": base, "token": BRANCH_TOKEN, "outbox": str(tmp / "branch-outbox-2"),
                "events": [{"id": "b-1", "severity": "medium"}]})
    check(r["pending"] == 0 and r["failed"] == 0, "Branch: redelivery of the same event (new outbox) accepted as replay")

    listed = httpx.get(f"{base}/api/v1/alerts", params={"use_case": "branch_exterior"}, headers=op).json()
    items = {a["source_event_id"]: a for a in listed["items"]}
    check(set(items) == {"b-1", "b-2"}, "Alert Service holds exactly one alert per Branch event (no duplicate from redelivery)")
    check(items["b-1"]["severity"] == "WARNING" and items["b-1"]["source_severity"] == "medium",
          "Branch severity medium -> WARNING, raw value preserved")
    check(items["b-2"]["severity"] == "CRITICAL" and items["b-2"]["status"] == "OPEN", "Branch critical -> CRITICAL, status OPEN")
    check(items["b-1"]["use_case"] == "branch_exterior" and items["b-1"]["producer"] == "branch-exterior-monitoring",
          "Source identity comes from the token, not the body")
    audit = httpx.get(f"{base}/api/v1/alerts/{items['b-1']['id']}/audit", headers=op).json()
    check(len(audit["items"] if isinstance(audit, dict) else audit) == 1, "Replay did not add a second audit/creation entry")

    r = branch({"base_url": base, "token": "wrong-token", "outbox": str(tmp / "branch-outbox-3"),
                "events": [{"id": "b-3"}]})
    check(r["failed"] == 1 and r["pending"] == 0, "Branch: wrong token -> 401 held in failed/, not retried")
    r = branch({"base_url": base, "token": BRANCH_TOKEN, "outbox": str(tmp / "branch-outbox-3"), "recover": True})
    check(r["failed"] == 0 and r["pending"] == 0, "Branch: after token fix, restart recovery delivers the held alert")

    r = branch({"base_url": dead, "then_url": base, "token": BRANCH_TOKEN, "outbox": str(tmp / "branch-outbox-4"),
                "events": [{"id": "b-4", "severity": "high"}]})
    check(r["pending_after_outage"] == 1 and r["pending"] == 0 and r["failed"] == 0,
          "Branch: alert survives an Alert Service outage and is delivered after recovery")

    listed = httpx.get(f"{base}/api/v1/alerts", params={"use_case": "branch_exterior"}, headers=op).json()
    ids = sorted(a["source_event_id"] for a in listed["items"])
    check(ids == ["b-1", "b-2", "b-3", "b-4"], "Branch alerts after failure/recovery: exactly b-1..b-4, no loss, no duplicates")

    # --- Vault -> Alert Service -------------------------------------------------------------------
    r = vault({"base_url": base, "token": VAULT_TOKEN,
               "alerts": [{"id": "v-1", "severity": "WARNING"}, {"id": "v-2", "severity": "CRITICAL"}]})
    check(r["attempted"] == 2 and r["actions"]["ALERT_SERVICE_PUBLICATION_SUCCEEDED"] == 2,
          "Vault: existing adapter published two alerts (2xx recorded)")
    r = vault({"base_url": base, "token": VAULT_TOKEN, "alerts": [{"id": "v-1", "severity": "WARNING"}]})
    check(r["actions"]["ALERT_SERVICE_PUBLICATION_SUCCEEDED"] == 1, "Vault: redelivery of v-1 accepted as replay")
    r = vault({"base_url": base, "token": "wrong-token", "alerts": [{"id": "v-3"}]})
    check(r["actions"]["ALERT_SERVICE_PUBLICATION_FAILED"] == 1, "Vault: wrong token -> FAILED recorded, no retry")
    r = vault({"base_url": dead, "then_url": base, "token": VAULT_TOKEN, "alerts": [{"id": "v-4"}]})
    check(r["actions"]["ALERT_SERVICE_PUBLICATION_RETRY"] >= 1 and r["actions"]["ALERT_SERVICE_PUBLICATION_SUCCEEDED"] == 1,
          "Vault: alert survives an outage (RETRY recorded) and is delivered afterwards")

    listed = httpx.get(f"{base}/api/v1/alerts", params={"use_case": "vault_monitoring"}, headers=op).json()
    ids = sorted(a["source_event_id"] for a in listed["items"])
    check(ids == ["v-1", "v-2", "v-4"], "Vault alerts: exactly v-1, v-2, v-4 (v-3 rejected for auth, no duplicates)")
    vault_items = {a["source_event_id"]: a for a in listed["items"]}
    check(vault_items["v-2"]["severity"] == "CRITICAL" and vault_items["v-1"]["severity"] == "WARNING",
          "Vault severities map identically")

    # --- Authorization, validation, lifecycle -----------------------------------------------------
    check(httpx.get(f"{base}/api/v1/alerts").status_code == 401, "Operator API without credentials -> 401")
    check(httpx.get(f"{base}/api/v1/alerts", headers={"Authorization": f"Bearer {BRANCH_TOKEN}"}).status_code == 401,
          "A producer token is not accepted on the operator API")
    scoped = httpx.get(f"{base}/api/v1/alerts", headers={"Authorization": f"Bearer {OPERATOR_VAULT_ONLY}"})
    seen = {a["use_case"] for a in scoped.json().get("items", [])} if scoped.status_code == 200 else {"error"}
    check(scoped.status_code in (200, 403) and "branch_exterior" not in seen,
          "Vault-scoped operator cannot see Branch alerts")
    branch_alert = items["b-1"]["id"]
    check(httpx.get(f"{base}/api/v1/alerts/{branch_alert}",
                    headers={"Authorization": f"Bearer {OPERATOR_VAULT_ONLY}"}).status_code in (403, 404),
          "Vault-scoped operator cannot read a Branch alert by id")

    body = {"schema_version": 1, "source_event_id": "x-1", "source_event_type": "loitering", "source_event_version": 1,
            "occurred_at": "2026-10-28T12:00:00Z", "severity": "medium", "title": "t", "summary": "s"}
    post = lambda payload, key="k-1", token=BRANCH_TOKEN: httpx.post(
        f"{base}/api/v1/alerts", json=payload, headers={"Authorization": f"Bearer {token}", "Idempotency-Key": key})
    check(post({**body, "use_case": "vault_monitoring"}).status_code == 422, "Body cannot override use_case (unknown field -> 422)")
    check(post({**body, "severity": "catastrophic"}, key="k-2").status_code == 422, "Unknown severity -> 422")
    check(httpx.post(f"{base}/api/v1/alerts", json=body, headers={"Authorization": f"Bearer {BRANCH_TOKEN}"}).status_code
          in (400, 422), "Missing Idempotency-Key is rejected")
    first = post(body, key="k-3")
    same = post(body, key="k-3")
    changed = post({**body, "title": "changed"}, key="k-3")
    check((first.status_code, same.status_code, changed.status_code) == (201, 200, 409),
          "Idempotency: 201 create, 200 replay, 409 for same key with a different body")

    ack = httpx.post(f"{base}/api/v1/alerts/{branch_alert}/acknowledgements", headers=op,
                     json={"expected_version": items["b-1"]["row_version"], "note": "seen"})
    check(ack.status_code == 200 and ack.json()["status"] == "ACKNOWLEDGED", "Operator acknowledgement moves b-1 to ACKNOWLEDGED")
    r = branch({"base_url": base, "token": BRANCH_TOKEN, "outbox": str(tmp / "branch-outbox-5"),
                "events": [{"id": "b-1", "severity": "medium"}]})
    after = httpx.get(f"{base}/api/v1/alerts/{branch_alert}", headers=op).json()
    check(r["failed"] == 0 and after["status"] == "ACKNOWLEDGED" and after["occurrence_count"] == items["b-1"]["occurrence_count"],
          "A late retry of b-1 does not reopen or duplicate the acknowledged alert")


if __name__ == "__main__":
    sys.exit(main())
