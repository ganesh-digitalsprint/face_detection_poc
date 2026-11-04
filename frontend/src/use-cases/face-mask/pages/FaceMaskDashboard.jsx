import { Link } from 'react-router-dom';
import { BarChart } from '../../branch-exterior/components/Charts.jsx';
import { api, coveringLabel, fmtTime } from '../api/index.js';
import { EventStatusBadge, PageState, StreamBadge } from '../components/ui.jsx';
import usePolling from '../hooks/usePolling.js';

const HOURS = Array.from({ length: 24 }, (_, i) => String(i).padStart(2, '0'));

export default function FaceMaskDashboard() {
  const stats = usePolling(() => api.get('/stats/summary?period=today'), 10000);
  const events = usePolling(() => api.get('/events?limit=6'), 10000);
  const cams = usePolling(() => api.get('/cameras'), 5000);
  const s = stats.data;
  const tiles = s ? [
    ['Entries today', s.entries], ['Visible', s.visible], ['Concealed', s.concealed, s.concealed > 0],
    ['Unable to assess', s.unable_to_assess], ['Open reviews', s.open_reviews, s.open_reviews > 0],
  ] : [];

  return (
    <>
      <PageState loading={stats.loading} error={stats.error} data={s} onRetry={stats.reload}>
        <div className="bx-kpis">
          {tiles.map(([label, value, hot]) => (
            <div key={label} style={hot ? { borderColor: '#dc2626', background: 'rgba(220,38,38,.12)' } : undefined}>
              <div className="v">{value}</div><div className="l">{label}</div>
            </div>
          ))}
        </div>
        <div className="bx-grid bx-grid-2">
          <div className="bx-card">
            <div className="bx-card-title">Entries by hour (UTC, today)</div>
            {s && s.entries === 0
              ? <div className="bx-muted" style={{ padding: 24, textAlign: 'center' }}>No entries evaluated today yet.</div>
              : <BarChart labels={HOURS} values={s?.by_hour || []} color="#3c5ba4" />}
          </div>
          <div className="bx-card">
            <div className="bx-card-title">Cameras</div>
            <PageState loading={cams.loading} error={cams.error} data={cams.data} onRetry={cams.reload}
              isEmpty={(d) => d.length === 0} emptyIcon="📷" emptyText="No cameras yet. Add one on the Live monitoring page.">
              {(cams.data || []).map((c) => (
                <div key={c.id} className="bx-zone-item">
                  <div><b>{c.name}</b><div className="bx-muted" style={{ fontSize: 12 }}>{c.location || c.cam_type}</div></div>
                  <StreamBadge status={c.stream.status} />
                </div>
              ))}
            </PageState>
          </div>
        </div>
      </PageState>

      <div className="bx-card bx-mt-16" style={{ marginTop: 16 }}>
        <div className="bx-card-title">Latest concealment events <Link to="/face-mask/events" style={{ fontWeight: 400, fontSize: 12 }}>(all)</Link></div>
        <PageState loading={events.loading} error={events.error} data={events.data} onRetry={events.reload}
          isEmpty={(d) => d.items.length === 0} emptyIcon="🛡" emptyText="No concealment events yet.">
          <table className="bx-table">
            <thead><tr><th>Time</th><th>Track</th><th>Covering</th><th>Score</th><th>Status</th></tr></thead>
            <tbody>
              {(events.data?.items || []).map((e) => (
                <tr key={e.id}>
                  <td><Link to={`/face-mask/events/${e.id}`}>{fmtTime(e.first_seen)}</Link></td><td>#{e.track_id}</td>
                  <td>{coveringLabel(e.covering_type)}</td><td>{e.score.toFixed(2)}</td><td><EventStatusBadge status={e.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </PageState>
      </div>
    </>
  );
}
