"""Transactional lifecycle publication using the existing Vault audit outbox."""
import logging
from datetime import datetime, timezone, timedelta
from uuid import uuid5, NAMESPACE_URL
from sqlalchemy import select
from app.db.models.vault_room import VaultAuditEvent, VaultEvidence

logger=logging.getLogger(__name__)
ENTITY = 'vault_alert_lifecycle'
PENDING, DELIVERED = 'VAULT_LIFECYCLE_PENDING', 'VAULT_LIFECYCLE_DELIVERED'

def stage_lifecycle(db, row):
    from app.services.vault_alert_service_adapter import build_payload
    identity = str(uuid5(NAMESPACE_URL, f'vault-lifecycle:{row.id}:{row.row_version}'))
    if db.get(VaultAuditEvent, identity): return
    payload = build_payload(row)
    evidence = db.scalars(select(VaultEvidence).where(VaultEvidence.alert_id == row.id, VaultEvidence.available.is_(True))).all()
    payload.update(source_event_version=row.row_version, source_status=row.status,
        evidence_refs=[{'provider':'vault_monitoring','id':item.id,'type':'snapshot'} for item in evidence])
    payload['domain_data'].update(lifecycle_owner='source', lifecycle_actor_type='operator',
        source_status_changed_at=row.updated_at.replace(tzinfo=timezone.utc).isoformat() if row.updated_at.tzinfo is None else row.updated_at.isoformat(),
        resolution_note=row.resolution_note, evidence_status=row.evidence_status,
        lifecycle_actor_id=row.acknowledged_by if row.status=='ACKNOWLEDGED' else row.resolved_by if row.status=='RESOLVED' else row.dismissed_by)
    db.add(VaultAuditEvent(id=identity,entity_type=ENTITY,entity_id=row.id,action=PENDING,
        details={'payload':payload,'attempt':0,'due_at':datetime.now(timezone.utc).isoformat()}))

def dispatch_lifecycle(adapter, limit=25):
    if not adapter.enabled: return 0
    with adapter._session_factory() as db:
        rows=db.scalars(select(VaultAuditEvent).where(VaultAuditEvent.entity_type==ENTITY,VaultAuditEvent.action==PENDING)
            .order_by(VaultAuditEvent.created_at,VaultAuditEvent.id)).all()
        pending=[(row.id,dict(row.details)) for row in rows]
    attempted=0
    for identity,state in pending:
        if attempted >= limit: break
        due=datetime.fromisoformat(state['due_at'])
        if due > adapter._clock(): continue
        attempted+=1; delivered=False
        try:
            with adapter._client_factory(timeout=adapter._timeout,follow_redirects=False) as client:
                payload=state['payload']; headers={'Authorization':f'Bearer {adapter.token}'}
                url=f"{adapter.base_url}/api/v1/alerts/source-events/{payload['source_event_id']}"
                response=client.get(url,headers=headers)
                response.raise_for_status()
                current=response.json()['source_event_version']
                if current >= payload['source_event_version']: delivered=True
                else:
                    response=client.put(url,headers={**headers,'If-Match':str(current)},json=payload)
                    response.raise_for_status(); delivered=True
        except Exception as exc:
            logger.warning('Vault lifecycle publication retained for retry: delivery=%s error=%s', identity, type(exc).__name__)
            # Source mutation is already committed. Retain the same immutable command for retry.
            state['attempt']=state.get('attempt',0)+1
            state['due_at']=(adapter._clock()+timedelta(seconds=min(300,2**min(state['attempt'],8)))).isoformat()
        with adapter._session_factory() as db:
            row=db.get(VaultAuditEvent,identity)
            if row is not None and row.action==PENDING:
                row.details=state
                if delivered: row.action=DELIVERED
                db.commit()
    return attempted
