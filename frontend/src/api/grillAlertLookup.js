import { grillEvidenceRequest } from './alertServiceModel.js';
const missing = (error) => error?.response?.status === 404;
const matches = (alert, row) => row?.source_event_id === alert.sourceEventId;

// Source-event lookup is absent on older deployed backends. Read an existing detail
// endpoint using a local ID hint, then verify identity before exposing any actions.
export async function loadGrillSourceAlert(api, alert, signal) {
  let originalError;
  try { return await api.grillGet(alert.sourceEventId, signal); }
  catch (error) { if (!missing(error)) throw error; originalError = error; }
  const ids = new Set(alert.localId ? [alert.localId] : []);
  for (const ref of alert.evidenceRefs || []) {
    const request = grillEvidenceRequest(ref);
    if (request) ids.add(decodeURIComponent(request.path.split('/')[5]));
  }
  for (const id of ids) {
    try {
      const row = await api.grillById(id, signal);
      if (matches(alert, row)) return row;
    } catch (error) { if (!missing(error)) throw error; }
  }
  let rows = [];
  if (alert.videoJobId) {
    const result = await api.grillVideo(alert.videoJobId, { limit: 1, offset: 0 }, signal);
    if (result.alerts_available === false || !Array.isArray(result.alerts)) throw new Error('Persisted alerts are temporarily unavailable.');
    rows = result.alerts;
  } else if (alert.assignmentId) {
    for (const read of [api.grillActive, api.grillHistory]) {
      let offset = 0;
      do {
        const page = await read(alert.assignmentId, { limit: 100, offset }, signal);
        rows.push(...(page.items || []));
        if (rows.some((row) => matches(alert, row))) break;
        offset = page.next_offset;
      } while (offset != null);
      if (rows.some((row) => matches(alert, row))) break;
    }
  }
  const match = rows.find((row) => matches(alert, row));
  if (match) return api.grillById(match.id, signal);
  throw originalError;
}
