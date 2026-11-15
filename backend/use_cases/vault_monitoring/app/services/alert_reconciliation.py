"""Explicit, bounded reconciliation using the existing Vault/Gate audit outboxes."""
from datetime import datetime, timezone
from urllib.parse import quote
from sqlalchemy import select
from fedbank_core.events.reconciliation import differs


def reconcile_alerts(db, adapter, *, use_case, dry_run=True, limit=25, offset=0):
    if not adapter.enabled:
        raise ValueError('Common Alerts publication is not configured')
    if use_case == 'vault_monitoring':
        from app.db.models.vault_room import VaultRoomAlert as Model
        from app.services.vault_alert_lifecycle import current_payload as build, stage_lifecycle
        base, token = adapter.base_url, adapter.token
    else:
        from grill_gate_monitoring.models.alert import GrillGateAlert as Model
        from grill_gate_monitoring.services.alert_delivery import public_payload, stage_publication, PENDING
        build = lambda db, row: public_payload(row)
        base, token = adapter._base, adapter._token
    rows = db.scalars(select(Model).order_by(Model.created_at, Model.id).offset(offset).limit(limit+1)).all()
    more = len(rows) > limit
    result = dict(dry_run=dry_run, scanned=min(limit,len(rows)), missing=0, outdated=0,
        unchanged=0, skipped=0, conflicts=0, failed=0, queued=0, source_event_ids=[],
        next_offset=offset+limit if more else None)
    headers = {'Authorization':f'Bearer {token}'}
    with adapter._client_factory(timeout=adapter._timeout, follow_redirects=False) as client:
        identity = client.get(f'{base}/api/v1/producer', headers=headers)
        identity.raise_for_status()
        if identity.json().get('use_case') != use_case:
            raise ValueError('Producer identity does not match source use case')
        for row in rows[:limit]:
            metadata = getattr(row, 'metadata_json', None) or {}
            if str(getattr(row, 'source', '')).lower().startswith('replay') or any(
                    metadata.get(key) is True for key in ('replay', 'replay_mode')):
                result['skipped'] += 1
                continue
            if not dry_run:
                row = db.get(Model, row.id, populate_existing=True, with_for_update=True)
                if row is None:
                    result['skipped'] += 1
                    continue
            payload = build(db, row)
            try:
                response = client.get(f'{base}/api/v1/alerts/source-events/{quote(payload["source_event_id"],safe="")}', headers=headers)
                if response.status_code != 404:
                    response.raise_for_status()
                    remote = response.json()
                    if remote['source_event_version'] > payload['source_event_version'] or (
                        remote['status'] in {'RESOLVED','DISMISSED'} and remote['status'] != payload['source_status']):
                        result['conflicts'] += 1
                        continue
                state = 'missing' if response.status_code == 404 else 'outdated' if (
                    remote['source_event_version'] < payload['source_event_version'] or differs(remote, payload)) else 'unchanged'
                result[state] += 1
                if state == 'unchanged':
                    continue
                result['source_event_ids'].append(payload['source_event_id'])
                if not dry_run:
                    with db.begin_nested():
                        if state == 'outdated' and remote['source_event_version'] == payload['source_event_version']:
                            row.row_version += 1
                            if use_case == 'grill_gate':
                                row.source_event_version += 1
                        if use_case == 'vault_monitoring':
                            stage_lifecycle(db, row, requeue=True)
                        else:
                            delivery = stage_publication(db, row)
                            delivery.action = PENDING
                            delivery.details = {'payload':build(db,row), 'attempt':0,
                                'due_at':datetime.now(timezone.utc).isoformat()}
                    result['queued'] += 1
            except Exception:
                result['failed'] += 1
    if not dry_run:
        db.commit()
    return result
