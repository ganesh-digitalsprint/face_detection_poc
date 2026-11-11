import { ServiceDownError } from '../api/index.js';
import { Badge, Empty } from '../../branch-exterior/components/ui.jsx';

export { Badge, Empty };

/** The honest privacy note shown on every Face Mask page. */
export function PrivacyNote() {
  return (
    <div className="bx-hint" role="note" style={{ margin: '0 0 14px' }}>
      <b>Privacy:</b> this feature only checks whether a face is <b>visible</b> or <b>concealed</b>. It never identifies anyone:
      no face recognition, no names and no face database. A Track ID is a temporary number for one visit.
    </div>
  );
}

/** Friendly panel instead of a blank page when the Face Mask backend does not answer. */
export function ServiceDown({ error, onRetry }) {
  const down = error instanceof ServiceDownError;
  return (
    <div className="bx-diag" role="alert">
      <b>{down ? 'Face Mask service is not running.' : 'Something went wrong.'}</b>
      <div style={{ marginTop: 6 }}>{error?.message}</div>
      {down && (
        <div style={{ marginTop: 6 }} className="bx-muted">
          In <code>backend/use_cases/face_mask</code>: <code>uv run uvicorn app.main:app --reload --port 8014</code>.
          The other use cases keep working while this is stopped.
        </div>
      )}
      {onRetry && <button type="button" className="bx-btn bx-btn-sm" style={{ marginTop: 8 }} onClick={onRetry}>Retry</button>}
    </div>
  );
}

/**
 * Loading / error / empty / content in one place, so no page is ever blank.
 * `data` is what the page loaded; `isEmpty(data)` decides the empty state.
 */
export function PageState({ loading, error, data, isEmpty, emptyIcon = '🗂', emptyText = 'Nothing here yet.', onRetry, children }) {
  if (error && !data) return <ServiceDown error={error} onRetry={onRetry} />;
  if (loading && !data) return <Empty icon="⏳" bare>Loading…</Empty>;
  if (data && isEmpty?.(data)) return <Empty icon={emptyIcon}>{emptyText}</Empty>;
  return (
    <>
      {error && <ServiceDown error={error} onRetry={onRetry} />}
      {children}
    </>
  );
}

const STREAM_KIND = { ONLINE: 'low', PROCESSING: 'low', DONE: 'info', RECONNECTING: 'medium', OFFLINE: 'critical', ERROR: 'critical', STOPPED: 'info' };

/** ONLINE / RECONNECTING / OFFLINE / PROCESSING / DONE chip for a camera stream. */
export function StreamBadge({ status }) {
  return <Badge kind="sev" value={STREAM_KIND[status] || 'info'} text={status || 'STOPPED'} />;
}

export const EventStatusBadge = ({ status }) => <Badge kind="status" value={String(status).toLowerCase()} text={String(status).replace('_', ' ')} />;

export const STATE_COLORS = { VISIBLE: '#16a34a', CONCEALED: '#dc2626', UNABLE: '#94a3b8', EVALUATING: '#f59e0b', NOT_ENTERING: '#64748b' };

export function StateDot({ state }) {
  return <span style={{ display: 'inline-block', width: 9, height: 9, borderRadius: 99, background: STATE_COLORS[state] || '#64748b', marginRight: 6 }} />;
}
