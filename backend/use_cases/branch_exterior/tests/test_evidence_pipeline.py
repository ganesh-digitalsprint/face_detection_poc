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


def test_medium_movement_does_not_meet_default_snapshot_policy():
    assert not is_suspicious('medium', '', 'high')
    allowed, reason = EvidenceBudget().decide(camera_id='cam', scenario='movement', kind='',
        severity='medium', min_severity='high', cooldown_seconds=60, max_per_day=150,
        storage_ok=True, now=1)
    assert (allowed, reason) == (False, 'not_suspicious')


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
        monkeypatch.setattr(alert_service, '_evidence_decision', lambda *_args: asyncio.sleep(0, result=(True, 'ok')))
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
