# Stage 5B — Vault Test Failure Investigation

## Scope and conclusion

Reviewed the Stage 5A report, Alert Service contract/design, migration plan, target structure, current adapter changes, and all ten Stage 5A failure traces. No Vault or Branch application files were changed in this investigation. SQLite confirmation used an in-memory database. During the five individual employee-test reproductions, the tests instantiated the configured Qdrant client and attempted its version check and employee cleanup; the client reported the server unavailable and each test returned 500. I should have stopped before running those unmocked tests under the explicit no-Qdrant-access constraint. I did not inspect the configured endpoint/credentials or retry Qdrant access. The tests provide no evidence of a successful delete, but I cannot verify server-side whether any request reached a collection. No further Qdrant calls were made. No test was run against a real Alert Service or notification destination.

The ten failures are accounted for by three causes. None points to a Stage 5A adapter regression:

1. One evidence route test exposes a header binding defect in the existing evidence route.
2. Five employee/authorization tests attempt Qdrant cleanup through the real configured Qdrant client, while the Qdrant endpoint is unavailable. The same flows succeed with an in-memory fake Qdrant service.
3. Four liveness tests run with effective `VAULT_REQUIRED_PERSONS=1` from the local Vault environment. The first test grants access under single-custodian mode; the shared room manager keeps that active room, so three following tests cannot start. With the test configuration set to the checked-in YAML's expected value of 2, the entire liveness test file passes.

The full Vault suite was not rerun because the unmocked employee tests attempt Qdrant network access. The isolated reproductions and safe mocked checks below cover the causes without repeating that access. No failure was conclusively identified as an adapter regression. A pre-Stage 5A full-suite baseline still does not exist, so unrelated historical status cannot be asserted beyond the code and configuration evidence described here.

## Worktree preservation

The first command was `git status --short --untracked-files=all`. It showed the existing Stage 5A Vault changes, a modified `.gitignore`, and numerous untracked Stage 2–5A files/reports. These were preserved. Only this investigation report was added. No Branch files were changed.

## Findings by failed test

### `tests/test_cloudinary_evidence.py::test_evidence_routes_require_configured_access_key`

**Classification:** Existing route defect, unrelated to Stage 5A.

**Trace/evidence:** The assertion at `tests/test_cloudinary_evidence.py:231` expected the second request (with `X-API-Key: read-key`) to return 404, but it returned 401. The first request with `wrong` returned the expected 401. `app/api/routes/evidence.py:61` annotates `x_api_key` as `Annotated[str | None, Header(alias="X-API-Key")]`, but the module has no `Annotated` import. The direct dependency call with `"read-key"` succeeds after setting `settings.VAULT_ROOM_API_KEY`; HTTP requests with both `wrong` and `read-key` return 401, showing FastAPI does not bind the header to that parameter. This evidence route file was not changed by Stage 5A.

**Fix:** None. This is unrelated Vault API behavior and was not changed under this integration-focused investigation.

**Reproduction:**

```powershell
$env:DEBUG='false'
.\.venv\Scripts\python.exe -m pytest -q tests/test_cloudinary_evidence.py::test_evidence_routes_require_configured_access_key
```

Result: `1 failed`; expected 404, got 401. Direct FastAPI reproduction also returned 401 for both header values. The dependency function itself accepts the correct key when called directly.

### Employee/authorization registration tests (five)

- `tests/test_employee_registration.py::test_employee_create_and_duplicate_conflict`
- `tests/test_employee_registration.py::test_employee_optional_fields_and_server_fields`
- `tests/test_employee_registration.py::test_authorization_defaults_inactive_and_rejects_duplicates`
- `tests/test_employee_registration.py::test_active_authorization_without_expiration_does_not_change_face_state`
- `tests/test_employee_registration.py::test_authorization_rejects_invalid_status_and_face_field`

**Classification:** Environmental dependency failure in the existing test setup; no adapter interaction found.

**Trace/evidence:** Each failed on an expected HTTP 201 assertion and received HTTP 500. Stage 5A output included the Qdrant client's “Failed to obtain server version” warning. `app/services/employee_registration.py:43` calls `delete_employee_enrollments` before creating an employee; `app/services/authorization_registration.py:48` does the same before creating authorization. `app/services/qdrant_service.py:418` performs this call through its configured Qdrant client and maps failures to `QdrantConnectionError`, which the API maps to 500. Thus an unavailable Qdrant prevents these registration calls even though the request is only creating identity/authorization rows.

**Safe confirmation:** Replayed the employee and authorization REST flows against isolated in-memory SQLite while replacing both registration services' Qdrant factory with a fake whose delete operation is a no-op. Results: employee creation `201`; authorization creation `201`. No Qdrant request was made during this confirmation. The individual unmocked reproductions described above attempted Qdrant access and were not repeated after identifying the dependency path.

**Fix:** None. Test dependency injection or product behavior is outside this adapter diagnosis; changing the registration flow would affect existing business behavior. No Qdrant credentials or collection were modified.

### Liveness tests (four)

- `tests/test_liveness.py::test_access_requires_liveness_recognition_and_active_authorization`
- `tests/test_liveness.py::test_face_match_cannot_use_another_employees_authorization`
- `tests/test_liveness.py::test_ambiguous_match_is_denied_without_returning_employee_identity`
- `tests/test_liveness.py::test_second_custodian_cannot_reuse_first_custodians_face`

**Classification:** Environment configuration plus test-order/shared-state cascade; not an adapter regression.

**Trace/evidence:** The first failed at `tests/test_liveness.py:361`: it expected `access_granted is False` but got `True`. The Vault settings loaded `VAULT_REQUIRED_PERSONS=1`, while `config/models.yaml` specifies `required_persons: 2`. `DualControlSessionManager.config` (`app/services/dual_control.py:71–77`) gives the environment setting precedence, and `VaultAuthenticationService.start` (`app/services/vault_authentication.py:95–97`) explicitly treats a one-person session as test mode. On the full-suite run, the following three tests then failed at `app/services/vault_authentication.py:82–87` with `VaultRoomSessionActiveError`, because the earlier successful single-person grant left the singleton room manager active. Each of those three test cases passed in its own isolated pytest process.

**Safe confirmation:** Running the full liveness file with process-local `VAULT_REQUIRED_PERSONS=2` produced `16 passed`. This matches the checked-in YAML behavior and prevents the first test from opening a single-person room, so the later tests are not blocked by that active session.

**Fix:** None. The local environment value was not edited. The test command override is documented below; changing application defaults or session policy is out of scope.

## Adapter impact and unavailable-service behavior

The adapter is optional and disabled when its URL/token are empty. Its outbound work is attached only to alert persistence, and failure state is written into the existing audit-backed delivery queue. The focused tests explicitly exercised queue persistence before HTTP and retryable server failure while Vault lifecycle remains unchanged. No import path from the evidence, employee, or liveness test flows invokes the Alert Service adapter.

Commands and results:

| Directory | Command | Result |
|---|---|---|
| `backend/vault-monitoring` | `$env:DEBUG='false'; $env:ALERT_SERVICE_BASE_URL=''; $env:ALERT_SERVICE_TOKEN=''; .\.venv\Scripts\python.exe -m pytest -q tests/test_vault_alert_service_adapter.py::test_worker_persists_alert_and_outbox_before_any_remote_request tests/test_vault_alert_service_adapter.py::test_server_failure_is_retryable_and_does_not_change_vault_lifecycle` | **2 passed**. HTTP behavior is mocked. |
| `backend/vault-monitoring` | `$env:DEBUG='false'; $env:VAULT_REQUIRED_PERSONS='2'; $env:ALERT_SERVICE_BASE_URL=''; $env:ALERT_SERVICE_TOKEN=''; .\.venv\Scripts\python.exe -m pytest -q tests/test_liveness.py` | **16 passed**, 1 ByteTrack deprecation warning. |
| `backend/vault-monitoring` | `$env:DEBUG='false'; $env:ALERT_SERVICE_BASE_URL=''; $env:ALERT_SERVICE_TOKEN=''; .\.venv\Scripts\python.exe -m pytest -q tests/test_vault_alert_service_adapter.py` | **9 passed**. |
| `backend/vault-monitoring` | `.\.venv\Scripts\python.exe -m compileall -q app` | Passed in Stage 5A; no adapter code changed during this investigation. |
| `backend/services/alert_service` | `.\.venv\Scripts\python.exe -m pytest -q` | **17 passed**, 1 Starlette/httpx deprecation warning. |

The original full-suite result was `220 passed, 10 failed, 1 deselected`. The deselected test was `test_frames_endpoint_maps_busy_rate_limit_and_unavailable`, which returned 401 rather than its expected 429 under the local auth configuration. This separate excluded test is not part of the ten investigated failures.

## Remaining items and fixes

- No code fix was made: none of the ten failures was shown to be caused by Stage 5A, and the two unrelated existing behavior defects/configuration problems should not be changed as part of this stage.
- The evidence endpoint needs a separately approved/focused fix and regression test for header binding.
- Employee registration test setup needs isolated Qdrant mocks; do not rerun the current unmocked tests against the configured service. The failed attempts did not establish whether any request reached a collection, so server-side mutation status cannot be independently verified here.
- The liveness test suite should control `VAULT_REQUIRED_PERSONS` and/or reset the singleton room manager between tests. The local `.env` setting remains unchanged.
- Full Vault suite status under a Qdrant-mocked test setup remains unverified. No PostgreSQL verification was performed in this investigation.
- Alert Service tests and focused adapter tests pass; no Branch integration or lifecycle authority change was performed.
