import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import numpy as np
import pytest

from app.schemas.camera import Camera
from app.schemas.settings import ThresholdConfig
from app.services import alert_service, evidence_service
from app.services.analytics.signals import ScenarioSignal
from app.services.evidence_policy import EvidenceBudget, is_suspicious


def test_medium_movement_does_not_meet_default_clip_policy():
    assert not is_suspicious('medium', '', 'high')
    allowed, reason = EvidenceBudget().decide(camera_id='cam', scenario='movement', kind='',
        severity='medium', min_severity='high', cooldown_seconds=60, max_per_day=150,
        storage_ok=True, now=1)
    assert (allowed, reason) == (False, 'not_suspicious')


class _MemoryEvents:
    def __init__(self, existing=None):
        self.created = None
        self.existing = existing
        self.touched = []

    async def find_open_by_dedupe(self, *_args): return self.existing

    async def create(self, payload):
        self.created = payload
        return SimpleNamespace(id='event-123', scenario=payload.scenario, severity=payload.severity,
            snapshot_path=payload.snapshot_path, clip_path=payload.clip_path, meta=payload.meta,
            model_dump=lambda **_kwargs: {'id': 'event-123'})

    async def touch(self, event_id, **fields):
        self.touched.append((event_id, fields))
        return self.existing


def _run_signal(monkeypatch, *, severity='low', kind='running', scenario_name='movement', storage=(True, 'ok'),
                snapshot_result='snapshots/cam_fixture.jpg', existing=None):
    async def scenario():
        repos = SimpleNamespace(events=_MemoryEvents(existing))
        camera = Camera(id='synthetic-camera', name='Fixture', cam_type='folder', source='fixture.mp4',
            enabled=True, loop_video=True, created_at=datetime.now(timezone.utc))
        signal = ScenarioSignal(scenario=scenario_name, track_ids=[3], message='synthetic alert', confidence=.8,
            severity_hint=severity, meta={'kind': kind}, dedupe_key='fixture-alert')
        monkeypatch.setattr(alert_service, '_snapshot_decision', lambda *_args: asyncio.sleep(0, result=storage))
        monkeypatch.setattr(alert_service, 'save_snapshot', snapshot_result if callable(snapshot_result)
            else lambda *_args: snapshot_result)
        monkeypatch.setattr(alert_service, '_rate_limited', lambda *_args: False)
        monkeypatch.setattr(alert_service, 'notify', lambda *_args: asyncio.sleep(0))
        monkeypatch.setattr(alert_service.ws_manager, 'broadcast', lambda *_args: asyncio.sleep(0))
        scheduled = []
        def capture_scheduled(coro):
            scheduled.append(True)
            coro.close()
        monkeypatch.setattr(alert_service, '_spawn', capture_scheduled)
        monkeypatch.setattr(alert_service, '_clip_budget', EvidenceBudget())
        event, created = await alert_service.handle_signal(repos, signal, camera,
            np.zeros((12, 12, 3), dtype=np.uint8), evidence_service.RollingClipBuffer(), ThresholdConfig(), '')
        return repos, event, created, scheduled
    return asyncio.run(scenario())


@pytest.mark.parametrize(('severity', 'kind', 'scenario'), [
    ('low', 'running', 'movement'),
    ('medium', 'fallen', 'anomaly'),
    ('medium', 'unusual_movement', 'movement'),
    ('medium', 'group', 'gathering'),
])
def test_low_and_medium_alerts_capture_one_snapshot_without_a_clip(monkeypatch, severity, kind, scenario):
    repos, event, created, scheduled = _run_signal(monkeypatch, severity=severity, kind=kind, scenario_name=scenario)
    assert created and event.snapshot_path == repos.events.created.snapshot_path == 'snapshots/cam_fixture.jpg'
    assert repos.events.created.meta['evidence'] == 'saved'
    assert scheduled == []


def test_high_alert_keeps_snapshot_and_clip_eligibility(monkeypatch):
    repos, event, created, scheduled = _run_signal(monkeypatch, severity='high', kind='loitering', scenario_name='loitering')
    assert created and event.snapshot_path == repos.events.created.snapshot_path
    assert repos.events.created.meta['clip_evidence'] == 'pending'
    assert scheduled == [True]


def test_storage_cap_prevents_snapshot_with_reason_but_keeps_event(monkeypatch):
    repos, _event, created, scheduled = _run_signal(monkeypatch,
        storage=(False, 'storage_cap_reached'), snapshot_result='')
    assert created and repos.events.created.snapshot_path == ''
    assert repos.events.created.meta['evidence'] == 'not_saved:storage_cap_reached'
    assert scheduled == []


def test_duplicate_event_does_not_capture_or_overwrite_existing_snapshot(monkeypatch):
    existing = SimpleNamespace(id='event-existing', severity='low', confidence=.7, message='old', track_ids=[3],
        meta={'kind': 'running', 'evidence': 'saved'}, scenario='movement', camera_name='Fixture', zone_name='',
        snapshot_path='snapshots/existing.jpg')
    capture_calls = []
    repos, event, created, _scheduled = _run_signal(monkeypatch, existing=existing,
        snapshot_result=lambda *_args: capture_calls.append(1) or 'snapshots/new.jpg')
    assert not created and event.id == 'event-existing'
    assert capture_calls == []
    assert repos.events.touched[0][1].get('snapshot_path') is None


def test_snapshot_saves_only_a_nonempty_synthetic_frame_under_existing_owner_folder(tmp_path, monkeypatch):
    root = tmp_path / 'storage'
    folder = root / 'screenshots' / 'branch_exterior'
    folder.mkdir(parents=True)
    monkeypatch.setenv('FEDBANK_STORAGE_ROOT', str(root))
    monkeypatch.setattr(evidence_service, 'SNAPSHOT_DIR', folder)
    monkeypatch.setattr(evidence_service, 'ensure_directories', lambda: None)

    relative = evidence_service.save_snapshot(np.zeros((24, 32, 3), dtype=np.uint8), 'cam/unsafe')

    assert relative.startswith('snapshots/cam_unsafe_')
    saved = folder / relative.rsplit('/', 1)[1]
    assert saved.is_file() and saved.stat().st_size > 0


def test_snapshot_write_failure_keeps_the_source_incident(monkeypatch):
    class Events:
        created = None
        async def find_open_by_dedupe(self, *_args): return None
        async def create(self, payload):
            self.created = payload
            return SimpleNamespace(id='new-event', scenario=payload.scenario, severity=payload.severity,
                model_dump=lambda **_kwargs: {'id': 'new-event'})

    class Repos:
        def __init__(self): self.events = Events()

    async def scenario():
        repos = Repos()
        camera = Camera(id='synthetic-camera', name='Fixture', cam_type='folder', source='fixture.mp4',
            enabled=True, loop_video=True, created_at=datetime.now(timezone.utc))
        signal = ScenarioSignal(scenario='anomaly', track_ids=[3], message='fixture threat', confidence=.8,
            severity_hint='high', meta={'kind': 'weapon'}, dedupe_key='fixture-alert')
        monkeypatch.setattr(alert_service, '_snapshot_decision', lambda *_args: asyncio.sleep(0, result=(True, 'ok')))
        monkeypatch.setattr(alert_service, '_evidence_decision', lambda *_args, **_kwargs: asyncio.sleep(0, result=(True, 'ok')))
        monkeypatch.setattr(alert_service, 'save_snapshot', lambda *_args: (_ for _ in ()).throw(OSError('disk full')))
        monkeypatch.setattr(alert_service, 'notify', lambda *_args: asyncio.sleep(0))
        monkeypatch.setattr(alert_service.ws_manager, 'broadcast', lambda *_args: asyncio.sleep(0))

        event, created = await alert_service.handle_signal(repos, signal, camera,
            np.zeros((12, 12, 3), dtype=np.uint8), evidence_service.RollingClipBuffer(),
            ThresholdConfig(), '', event_context={'branch_id': 'branch-1'})

        assert created and event.id == 'new-event'
        assert repos.events.created.snapshot_path == ''
        assert repos.events.created.meta['evidence'] == 'failed:snapshot_write_failed'
        assert repos.events.created.meta['branch_id'] == 'branch-1'

    asyncio.run(scenario())
