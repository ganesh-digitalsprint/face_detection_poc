import asyncio
from copy import deepcopy
from pathlib import Path
import sys

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "shared"))
from fedbank_core.events.source_sync import deliver_current
from app.main import create_app
from app.settings import Settings


@pytest.mark.parametrize("use_case", ["branch_exterior", "face_mask"])
def test_latest_source_state_retry_and_review_mapping(tmp_path, use_case):
    app = create_app(Settings(database_url=f"sqlite:///{(tmp_path/'common.db').as_posix()}",
        producer_credentials={"source": {"use_case": use_case, "producer": "test-producer"}},
        operator_credentials={"operator": {"actor_id": "op", "use_cases": [use_case], "branch_ids": ["*"]}},
        notification_webhook_url=""), start_notification_worker=False)
    current = dict(schema_version=1, source_event_id="source-1", source_event_type="movement" if use_case == 'branch_exterior' else 'FACE_CONCEALMENT',
        source_event_version=1, category="security", occurred_at="2026-11-13T01:00:00Z",
        first_seen_at="2026-11-13T01:00:00Z", last_seen_at="2026-11-13T01:00:00Z",
        severity="high", title="Source alert", summary="Review source",
        source_status="open" if use_case == "branch_exterior" else "OPEN",
        resource_refs={"camera_id": "cam-1"}, domain_data={"lifecycle_owner": "source", "confidence": .5},
        evidence_refs=[], deduplication_key="test")
    state = {"payload": deepcopy(current)}

    async def load(_):
        return deepcopy(current) if current else None

    with TestClient(app) as operator:
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
                async def sync():
                    await deliver_current(client, "http://test", "source", state, load)
                await sync()
                first = operator.get('/api/v1/alerts', headers={"Authorization": "Bearer operator"}).json()['items'][0]
                await sync()
                unchanged = operator.get('/api/v1/alerts/'+first['id'], headers={"Authorization": "Bearer operator"}).json()
                assert unchanged['row_version'] == first['row_version']
                for source_status, mapped in [("under_review", "ACKNOWLEDGED"), ("confirmed", "ACKNOWLEDGED"),
                                               ("false_positive", "DISMISSED"), ("closed", "RESOLVED")]:
                    current['source_status'] = source_status if use_case == 'branch_exterior' else source_status.upper()
                    current['domain_data']['confidence'] = .95
                    current['domain_data']['occurrence_count'] = 3
                    current['evidence_refs'] = [{"provider": use_case, "id": "snapshot-1", "type": "snapshot"}]
                    await sync()  # retries use latest committed payload, never state['payload']
                    response = operator.get('/api/v1/alerts/'+first['id'], headers={"Authorization": "Bearer operator"}).json()
                    assert response['status'] == mapped
                    assert response['source_status'] == current['source_status']
                    assert response['domain_data']['confidence'] == .95
                    assert response['occurrence_count'] == 3
                    assert response['evidence_refs'] == current['evidence_refs']
                    assert response['allowed_actions'] == []
                    assert operator.post('/api/v1/alerts/'+first['id']+'/resolution',
                        headers={"Authorization": "Bearer operator"},
                        json={"expected_version": response['row_version'], "note": "competing writer"}).status_code == 409
                # A delayed optimistic write cannot overwrite the last source version.
                stale = deepcopy(state['payload']); stale['source_event_version'] = 2
                assert (await client.put('http://test/api/v1/alerts/source-events/source-1',
                    headers={"Authorization": "Bearer source", "If-Match": "1"}, json=stale)).status_code == 409
                rows = operator.get('/api/v1/alerts', headers={"Authorization": "Bearer operator"}).json()['items']
                assert len(rows) == 1
        asyncio.run(run())


def test_delete_retains_history_and_missing_source_cannot_resurrect(tmp_path):
    app = create_app(Settings(database_url=f"sqlite:///{(tmp_path/'delete.db').as_posix()}",
        producer_credentials={"source": {"use_case": "branch_exterior", "producer": "branch"}},
        operator_credentials={"operator": {"actor_id": "op", "use_cases": ["branch_exterior"], "branch_ids": ["*"]}},
        notification_webhook_url=""), start_notification_worker=False)
    payload = dict(schema_version=1, source_event_id="deleted", source_event_type="movement",
        source_event_version=1, category="security", occurred_at="2026-11-13T01:00:00Z",
        severity="high", title="Alert", summary="Review", source_status="open",
        resource_refs={}, domain_data={"lifecycle_owner": "source"}, evidence_refs=[])
    current = deepcopy(payload)
    async def load(_):
        return deepcopy(current)
    with TestClient(app) as operator:
        async def run():
            nonlocal current
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
                state = {"payload": payload}
                await deliver_current(client, "http://test", "source", state, load)
                current = None
                await deliver_current(client, "http://test", "source", {**state, "deleted": True}, load)
                await deliver_current(client, "http://test", "source", state, load)
                row = operator.get('/api/v1/alerts', headers={"Authorization": "Bearer operator"}).json()['items'][0]
                assert row['status'] == 'RESOLVED' and row['source_status'] == 'open'
                assert row['domain_data']['source_deleted'] is True
        asyncio.run(run())
