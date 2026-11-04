import { Link } from 'react-router-dom';
import { api, coveringLabel, fmApiUrl, qs, ServiceDownError } from '../api/index.js';
import usePolling from '../hooks/usePolling.js';

/**
 * Small self-contained blocks for pages OUTSIDE the Face Mask area (main Dashboard, Security Brief).
 * Each one loads its own data and, when the Face Mask service is stopped, shows "Face Mask service unavailable"
 * for that block only: it can never break the page it is placed on.
 */
function Unavailable({ error }) {
  const down = error instanceof ServiceDownError;
  return (
    <div className="bx-muted" role="status" style={{ fontSize: 13 }}>
      <b>Face Mask service unavailable.</b> {down ? 'It is not running on port 8014.' : error?.message}
    </div>
  );
}

/** Dashboard tiles: concealment events today and open reviews. */
export function FaceMaskDashboardTiles() {
  const startOfDay = new Date(); startOfDay.setHours(0, 0, 0, 0);
  const { data, error, loading } = usePolling(async () => {
    const [events, stats] = await Promise.all([
      api.get(`/events${qs({ date_from: startOfDay.toISOString(), limit: 1 })}`), api.get('/stats/summary?period=all')]);
    return { events: events.total, open: stats.open_reviews };
  }, 20000);
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="font-semibold text-slate-800">Face Mask · today</h3>
        <Link to="/face-mask" className="text-xs font-semibold text-brand underline">Open</Link>
      </div>
      {error && !data && <Unavailable error={error} />}
      {loading && !data && !error && <p className="text-sm text-slate-500">Loading…</p>}
      {data && (
        <div className="grid grid-cols-2 gap-3 text-center">
          <Link to="/face-mask/events" className="rounded-md border border-slate-200 p-3" style={data.events ? { borderColor: '#dc2626', background: 'rgba(220,38,38,.08)' } : undefined}>
            <div className="text-2xl font-bold text-navy">{data.events}</div><div className="text-xs text-slate-500">Concealment events</div>
          </Link>
          <Link to="/face-mask/events?status=OPEN" className="rounded-md border border-slate-200 p-3">
            <div className="text-2xl font-bold text-navy">{data.open}</div><div className="text-xs text-slate-500">Open reviews</div>
          </Link>
        </div>
      )}
    </div>
  );
}

/** Security Brief section for the last `hours` hours. */
export function FaceMaskBriefSection({ hours }) {
  const { data, error, loading } = usePolling(async () => {
    const since = new Date(Date.now() - Number(hours) * 3600 * 1000).toISOString();
    const [stats, events, cameras] = await Promise.all([
      api.get(`/stats/summary?hours=${hours}`), api.get(`/events${qs({ date_from: since, limit: 200 })}`), api.get('/cameras')]);
    const names = Object.fromEntries(cameras.map((c) => [c.id, c.name]));
    const perCamera = {};
    events.items.forEach((e) => { perCamera[e.camera_id] = (perCamera[e.camera_id] || 0) + 1; });
    return {
      stats,
      total: events.total,
      confirmed: events.items.filter((e) => e.status === 'CONFIRMED').length,
      falsePositive: events.items.filter((e) => e.status === 'FALSE_POSITIVE').length,
      topCameras: Object.entries(perCamera).sort((a, b) => b[1] - a[1]).slice(0, 5).map(([id, n]) => ({ name: names[id] || id.slice(0, 8), n })),
      thumbs: events.items.filter((e) => e.snapshot_path).slice(0, 3),
    };
  }, 0, [hours]);

  return (
    <div className="bx-card bx-mt-16" style={{ marginTop: 16 }} aria-label="Face Mask">
      <div className="bx-card-title">Face Mask - entrances <span className="bx-muted" style={{ fontWeight: 400 }}>(visible vs concealed face; never identifies anyone)</span></div>
      {loading && !data && !error && <div className="bx-muted">Loading…</div>}
      {error && !data && <Unavailable error={error} />}
      {data && (
        <>
          <div className="bx-kpis">
            {[['Entries evaluated', data.stats.entries], ['Concealed events', data.total, data.total > 0], ['Confirmed', data.confirmed],
              ['False positives', data.falsePositive], ['Unable to assess', data.stats.unable_to_assess], ['Open reviews', data.stats.open_reviews]]
              .map(([l, v, hot]) => <div key={l}><div className="v" style={hot ? { color: '#dc2626' } : undefined}>{v}</div><div className="l">{l}</div></div>)}
          </div>
          <div className="bx-two-col" style={{ gridTemplateColumns: '1fr 2fr' }}>
            <div>
              <div className="bx-card-title">Top cameras</div>
              {data.topCameras.length === 0 && <div className="bx-muted">No concealment events in this period.</div>}
              {data.topCameras.map((c) => <div key={c.name} className="bx-bar-row" style={{ gridTemplateColumns: '1fr 40px' }}><div>{c.name}</div><div><b>{c.n}</b></div></div>)}
            </div>
            <div>
              <div className="bx-card-title">Latest evidence</div>
              {data.thumbs.length === 0 && <div className="bx-muted">No evidence in this period.</div>}
              <div className="bx-row bx-gap-8 bx-wrap">
                {data.thumbs.map((e) => (
                  <figure key={e.id} style={{ margin: 0, width: 170 }}>
                    <img src={fmApiUrl(`/events/${e.id}/evidence/snapshot`)} alt={`${coveringLabel(e.covering_type)} event, track ${e.track_id}`}
                      style={{ width: '100%', borderRadius: 6, background: '#000' }} />
                    <figcaption className="bx-muted" style={{ fontSize: 11 }}>{coveringLabel(e.covering_type)} · {new Date(e.first_seen).toLocaleString()}</figcaption>
                  </figure>
                ))}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
