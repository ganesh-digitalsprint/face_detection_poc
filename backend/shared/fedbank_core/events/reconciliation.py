"""Bounded, explicitly invoked inspection of persisted source alerts using Contract v1."""
from urllib.parse import quote
from fedbank_core.events.source_sync import _comparable


def differs(remote, payload):
    comparison = {key: remote.get(key) for key in payload}
    comparison['severity'] = remote.get('source_severity')
    return _comparable(comparison) != _comparable(payload)


async def reconcile_events(client, base, token, use_case, events, load_payload, enqueue, *, dry_run=True):
    headers = {'Authorization':f'Bearer {token}'}
    identity = await client.get(f'{base}/api/v1/producer', headers=headers)
    identity.raise_for_status()
    if identity.json().get('use_case') != use_case:
        raise ValueError('Producer identity does not match source use case')
    result = dict(dry_run=dry_run, scanned=len(events), missing=0, outdated=0, unchanged=0,
        skipped=0, failed=0, queued=0, source_event_ids=[])
    for event in events:
        try:
            response = await client.get(f'{base}/api/v1/alerts/source-events/{quote(event.id, safe="")}', headers=headers)
            if response.status_code != 404:
                response.raise_for_status()
            payload = await load_payload(event.id)
            if payload is None:
                result['skipped'] += 1
                continue
            state = 'missing' if response.status_code == 404 else 'outdated' if differs(response.json(), payload) else 'unchanged'
            result[state] += 1
            if state != 'unchanged':
                result['source_event_ids'].append(event.id)
                if not dry_run:
                    if await enqueue(event):
                        result['queued'] += 1
                    else:
                        result['failed'] += 1
        except Exception:
            result['failed'] += 1
    return result
