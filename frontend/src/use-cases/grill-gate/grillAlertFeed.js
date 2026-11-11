import { matchesStatus, mergeById, normalizeGrillGateAlert } from '../../api/alertServiceModel.js';

/** Only persisted incident responses feed this adapter; monitoring counters never do. */
export function createGrillAlertApi({ assignmentId, jobId, api }) {
  // View cache of persisted records for this source, independent of timer/gate state.
  // An omitted row is not a lifecycle transition or a deletion.
  const records = new Map();
  const applyUpdate = (row) => {
    const key = row.sourceEventId || row.id;
    const previous = records.get(key);
    if (previous && (row.rowVersion ?? 0) < (previous.rowVersion ?? 0)) return;
    records.set(key, row);
  };
  const assertCurrent = (signal) => {
    if (signal?.aborted) { const error = new Error('Alert source changed'); error.name = 'AbortError'; throw error; }
  };
  return {
    applyUpdate,
    count: (status) => jobId ? [...records.values()].filter((row) => matchesStatus(row, status)).length : null,
    summary: async () => null,
    list: async (params, signal) => {
      if (jobId) {
        const result = await api.video(jobId, { limit: 1, offset: 0 }, signal);
        if (result.alerts_available === false || !Array.isArray(result.alerts)) throw new Error('Persisted video alerts are temporarily unavailable.');
        assertCurrent(signal);
        const rows = result.alerts.filter((row) => {
          const source = row.video_job_id || row.resource_refs?.video_job_id || row.domain_data?.video_job_id;
          return !source || String(source) === String(jobId);
        }).map(normalizeGrillGateAlert);
        const present = new Set(rows.map((row) => row.sourceEventId || row.id));
        const omitted = [...records.values()].filter((row) => !present.has(row.sourceEventId || row.id));
        // Reconcile omitted incidents against their persisted detail records when possible.
        // A temporary empty result must neither erase them nor keep a resolved incident Active.
        const reconciled = api.detail ? await Promise.allSettled(omitted.map((row) => api.detail(row.localId, signal))) : [];
        assertCurrent(signal);
        rows.forEach(applyUpdate);
        reconciled.forEach((result) => {
          if (result.status === 'fulfilled') applyUpdate(normalizeGrillGateAlert(result.value));
        });
        return { items: [...records.values()].filter((row) => matchesStatus(row, params.status)), hasMore: false, nextCursor: null };
      }
      const history = params.status === 'HISTORY';
      const request = history ? api.history : api.active;
      const page = await request(assignmentId, { limit: 100, offset: Number(params.cursor || 0) }, signal);
      if (!Array.isArray(page.items)) throw new Error('Persisted alerts are temporarily unavailable.');
      // The existing history endpoint also includes ACKNOWLEDGED; it stays Active in the UI.
      return { items: mergeById([], page.items.map(normalizeGrillGateAlert), false).filter((a) => matchesStatus(a, params.status)),
        hasMore: page.next_offset != null, nextCursor: page.next_offset == null ? null : String(page.next_offset) };
    },
  };
}


/** Merely uploading/queuing a replacement does not clear the previous processing session. */
export function videoAlertSession(previousJobId, job) {
  if (!job?.job_id) return previousJobId;
  const started = ['PROCESSING', 'CANCEL_REQUESTED', 'COMPLETED'].includes(job.status)
    || (['FAILED', 'CANCELLED'].includes(job.status) && Boolean(job.started_at));
  return started ? job.job_id : previousJobId;
}
