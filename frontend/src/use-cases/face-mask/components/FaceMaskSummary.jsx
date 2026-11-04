import { Link } from 'react-router-dom';
import { faceMaskParams, resolveRange } from '../../branch-exterior/briefFilters.js';
import { faceMaskEventLink } from '../../../layouts/routes.js';
import { api, coveringLabel, fmApiUrl, qs } from '../api/index.js';
import usePolling from '../hooks/usePolling.js';
import { ServiceDown } from './ui.jsx';

/**
 * Security Brief section for the Face Mask use case, driven by the brief's filter bar.
 * It loads its own data and, when the Face Mask service is stopped, shows the "service unavailable + start command"
 * panel for this section only: it can never break the page it is placed on.
 */
export default function FaceMaskBriefSection({ filters }) {
  const key = JSON.stringify(filters);
  const { data, error, loading, reload } = usePolling(async () => {
    const now = new Date();
    const range = resolveRange(filters, now);
    const params = faceMaskParams(filters, now);
    // Entries / unable-to-assess come from the stats summary, which only looks back from now.
    const statsQuery = range.hours == null && filters.period === 'all' ? 'period=all' : `hours=${range.hours ?? 24 * 30}`;
    const entriesApply = !range.until;
    const [stats, events, cameras] = await Promise.all([
      api.get(`/stats/summary?${statsQuery}`), api.get(`/events${qs({ ...params, limit: 200 })}`), api.get('/cameras')]);
    const names = Object.fromEntries(cameras.map((c) => [c.id, c.name]));
    const perCamera = {};
    events.items.forEach((e) => { perCamera[e.camera_id] = (perCamera[e.camera_id] || 0) + 1; });
    return {
      stats, entriesApply, total: events.total,
      confirmed: events.items.filter((e) => e.status === 'CONFIRMED').length,
      falsePositive: events.items.filter((e) => e.status === 'FALSE_POSITIVE').length,
      topCameras: Object.entries(perCamera).sort((a, b) => b[1] - a[1]).slice(0, 5).map(([id, n]) => ({ name: names[id] || id.slice(0, 8), n })),
      thumbs: events.items.filter((e) => e.snapshot_path).slice(0, 3),
    };
  }, 0, [key]);

  return (
    <div className="bx-card bx-mt-16" style={{ marginTop: 16 }} aria-label="Face Mask">
      <div className="bx-card-title">Face Mask - entrances <span className="bx-muted" style={{ fontWeight: 400 }}>(visible vs concealed face; never identifies anyone)</span></div>
      {loading && !data && !error && <div className="bx-muted">Loading…</div>}
      {error && !data && <ServiceDown error={error} onRetry={reload} />}
      {data && (
        <>
          <div className="bx-kpis">
            {[['Entries evaluated', data.entriesApply ? data.stats.entries : 'n/a'], ['Concealed events', data.total, data.total > 0], ['Confirmed', data.confirmed],
              ['False positives', data.falsePositive], ['Unable to assess', data.entriesApply ? data.stats.unable_to_assess : 'n/a'], ['Open reviews', data.stats.open_reviews]]
              .map(([l, v, hot]) => <div key={l}><div className="v" style={hot ? { color: '#dc2626' } : undefined}>{v}</div><div className="l">{l}</div></div>)}
          </div>
          {!data.entriesApply && <p className="bx-muted" style={{ fontSize: 12 }}>Entries and unable-to-assess are counted up to now, so they are not shown for a range that ends in the past.</p>}
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
                    <Link to={faceMaskEventLink(e.id)} aria-label={`Open event ${e.id.slice(0, 8)}`}>
                      <img src={fmApiUrl(`/events/${e.id}/evidence/snapshot`)} alt={`${coveringLabel(e.covering_type)} event, track ${e.track_id}`}
                        style={{ width: '100%', borderRadius: 6, background: '#000' }} />
                    </Link>
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

export { FaceMaskBriefSection };
