import { Link } from 'react-router-dom';
import { BarChart } from '../../branch-exterior/components/Charts.jsx';
import { toggleTheme, useBxTheme } from '../../branch-exterior/theme.js';
import { faceMaskEventLink } from '../../../layouts/routes.js';
import { api, coveringLabel, fmtTime } from '../api/index.js';
import usePolling from '../hooks/usePolling.js';
import { EventStatusBadge, PageState, StreamBadge } from './ui.jsx';
import '../../branch-exterior/branchExterior.css';

const HOURS = Array.from({ length: 24 }, (_, i) => String(i).padStart(2, '0'));

/**
 * Face Mask block of the main Dashboard: entries today, visible / concealed / unable to assess, open reviews,
 * entries by hour, camera status and the latest events. Every sub-block degrades on its own with the
 * "service unavailable + start command" panel, so a stopped Face Mask service never breaks the Dashboard.
 */
export default function FaceMaskDashboardSection() {
  const theme = useBxTheme();
  const stats = usePolling(() => api.get('/stats/summary?period=today'), 10000);
  const events = usePolling(() => api.get('/events?limit=6'), 10000);
  const cams = usePolling(() => api.get('/cameras'), 5000);
  const s = stats.data;
  const tiles = s ? [
    ['Entries today', s.entries], ['Visible', s.visible], ['Concealed', s.concealed, s.concealed > 0],
    ['Unable to assess', s.unable_to_assess], ['Open reviews', s.open_reviews, s.open_reviews > 0],
  ] : [];

  return (
    <section className="bx-page rounded-lg border border-slate-200 shadow-sm" data-theme={theme} aria-label="Face Mask monitoring" style={{ padding: 16 }}>
      <div className="bx-row bx-gap-8 bx-wrap" style={{ justifyContent: 'space-between', marginBottom: 10 }}>
        <h3 style={{ margin: 0, fontWeight: 600 }}>Face Mask · entrances today</h3>
        <div className="bx-row bx-gap-8">
          <Link to="/face-mask/live" className="bx-btn bx-btn-sm">Live monitoring</Link>
          <Link to="/alerts/face-mask" className="bx-btn bx-btn-sm">Events &amp; review</Link>
          <button type="button" className="bx-btn bx-btn-sm" onClick={toggleTheme} aria-label="Toggle Face Mask panel theme">Theme</button>
        </div>
      </div>
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
              isEmpty={(d) => d.length === 0} emptyIcon="📷" emptyText="No cameras yet. Add one on the Face Mask Live monitoring page.">
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

      <div className="bx-card" style={{ marginTop: 16 }}>
        <div className="bx-card-title">Latest concealment events <Link to="/alerts/face-mask" style={{ fontWeight: 400, fontSize: 12 }}>(all)</Link></div>
        <PageState loading={events.loading} error={events.error} data={events.data} onRetry={events.reload}
          isEmpty={(d) => d.items.length === 0} emptyIcon="🛡" emptyText="No concealment events yet.">
          <table className="bx-table">
            <thead><tr><th>Time</th><th>Track</th><th>Covering</th><th>Score</th><th>Status</th></tr></thead>
            <tbody>
              {(events.data?.items || []).map((e) => (
                <tr key={e.id}>
                  <td><Link to={faceMaskEventLink(e.id)}>{fmtTime(e.first_seen)}</Link></td><td>#{e.track_id}</td>
                  <td>{coveringLabel(e.covering_type)}</td><td>{e.score.toFixed(2)}</td><td><EventStatusBadge status={e.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </PageState>
      </div>
    </section>
  );
}

