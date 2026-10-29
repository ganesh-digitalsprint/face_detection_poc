import { useCallback, useEffect, useState } from 'react';
import { api, bxApiUrl } from '../api/index.js';

const SEV_COLOR = { critical: '#dc2626', high: '#ea580c', medium: '#ca8a04', low: '#16a34a', info: '#64748b' };
const when = (iso) => new Date(iso).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });

function Bars({ rows, labelKey }) {
  const max = Math.max(1, ...rows.map((r) => r.count));
  if (!rows.length) return <div className="bx-muted">Nothing recorded.</div>;
  return rows.map((r) => (
    <div className="bx-bar-row" key={r[labelKey]}>
      <div title={r[labelKey]} style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{r[labelKey]}</div>
      <div className="bx-bar-track">
        <div className="bx-bar-fill" style={{ width: `${(r.count / max) * 100}%` }} />
        {r.high_critical ? <div className="bx-bar-hi" style={{ width: `${(r.high_critical / max) * 100}%` }} /> : null}
      </div>
      <div><b>{r.count}</b>{r.high_critical ? <span style={{ color: '#dc2626' }}> ({r.high_critical})</span> : null}</div>
    </div>
  ));
}

export default function SecurityBriefPage() {
  const [hours, setHours] = useState('24');
  const [b, setB] = useState(null);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    try { setB(await api.get(`/brief?hours=${hours}`)); setError(''); } catch (e) { setError(e.message); }
  }, [hours]);
  useEffect(() => { load(); }, [load]);

  if (error) return <div className="bx-card"><ul className="bx-headline"><li style={{ color: '#dc2626' }}>Could not load the brief: {error}. Copy the latest backend files and restart the server.</li></ul></div>;

  const t = b?.totals;
  const kp = t ? [['Incidents', t.events, ''], ['High / critical', t.high_critical, t.high_critical ? '#dc2626' : ''], ['Critical', t.critical, t.critical ? '#dc2626' : ''],
    ['With evidence saved', t.with_evidence, ''], ['Cameras involved', t.cameras, ''], ['Marked false positive', t.false_positive, '']] : [];
  const maxH = b ? Math.max(1, ...b.by_hour.map((x) => x.count)) : 1;

  return (
    <>
      <div className="bx-section-title bx-no-print">
        <div className="bx-row bx-gap-12">
          <label className="bx-field" style={{ margin: 0 }}>Period
            <select className="bx-input" value={hours} onChange={(e) => setHours(e.target.value)}>
              <option value="6">Last 6 hours</option><option value="24">Last 24 hours</option><option value="72">Last 3 days</option>
              <option value="168">Last 7 days</option><option value="720">Last 30 days</option>
            </select>
          </label>
          <button type="button" className="bx-btn" style={{ alignSelf: 'flex-end' }} onClick={load}>↻ Refresh</button>
        </div>
        <button type="button" className="bx-btn bx-btn-primary" onClick={() => window.print()}>🖨 Print / Save as PDF</button>
      </div>

      {!b && <div className="bx-row bx-gap-8 bx-muted" style={{ padding: 30, justifyContent: 'center' }}><span className="bx-spinner" /> Loading…</div>}
      {b && (
        <>
          <div className="bx-card bx-mb-16">
            <div className="bx-card-title">Summary - {new Date(b.from).toLocaleString()} to {new Date(b.to).toLocaleString()}</div>
            <ul className="bx-headline">{b.headline.map((l) => <li key={l}>{l}</li>)}</ul>
            <div className="bx-kpis">
              {kp.map(([l, v, c]) => <div key={l}><div className="v" style={c ? { color: c } : undefined}>{v}</div><div className="l">{l}</div></div>)}
            </div>
          </div>

          <div className="bx-two-col">
            <div className="bx-card"><div className="bx-card-title">What happened (by type)</div><Bars rows={b.by_kind} labelKey="label" /></div>
            <div className="bx-card">
              <div className="bx-card-title">By camera</div><Bars rows={b.by_camera} labelKey="camera" />
              <div className="bx-card-title" style={{ marginTop: 18 }}>By zone</div>
              <Bars rows={b.by_zone.map((z) => ({ zone: z.zone, count: z.count, high_critical: 0 }))} labelKey="zone" />
            </div>
          </div>

          <div className="bx-card bx-mt-16">
            <div className="bx-card-title">Timeline <span className="bx-muted" style={{ fontWeight: 400 }}>(blue = all incidents, red = high / critical)</span></div>
            <div className="bx-timeline">
              {b.by_hour.map((x) => (
                <div className="col" key={x.hour} title={`${when(x.hour)}: ${x.count} incident(s), ${x.high_critical} high/critical`}>
                  <div className="a" style={{ height: `${((x.count - x.high_critical) / maxH) * 100}px` }} />
                  <div className="b" style={{ height: `${(x.high_critical / maxH) * 100}px` }} />
                </div>
              ))}
            </div>
            {b.by_hour.length > 0 && <div className="bx-axis"><span>{when(b.by_hour[0].hour)}</span><span>{when(b.by_hour[b.by_hour.length - 1].hour)}</span></div>}
          </div>

          <div className="bx-card bx-mt-16">
            <div className="bx-card-title">Most serious incidents</div>
            <div className="bx-scroll-x">
              <table className="bx-table">
                <thead><tr><th>Time</th><th>Severity</th><th>Type</th><th>Camera / zone</th><th>What the AI saw</th><th /></tr></thead>
                <tbody>
                  {b.top_incidents.length === 0 && <tr><td colSpan={6} className="bx-muted">No incidents in this period.</td></tr>}
                  {b.top_incidents.map((i) => (
                    <tr key={i.id}>
                      <td>{new Date(i.time).toLocaleString()}</td>
                      <td><span style={{ color: SEV_COLOR[i.severity] || '#888', fontWeight: 700 }}>{i.severity.toUpperCase()}</span></td>
                      <td>{i.label}</td>
                      <td>{i.camera}{i.zone ? ` / ${i.zone}` : ''}</td>
                      <td style={{ maxWidth: 380 }}>{i.message}</td>
                      <td className="bx-no-print"><a className="bx-btn bx-btn-sm" href={bxApiUrl(`/events/${i.id}/report`)} target="_blank" rel="noreferrer">Report</a></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
          <p className="bx-hint" style={{ marginTop: 12 }}>AI-assisted indications - every incident must be verified by a person before any action is taken.</p>
        </>
      )}
    </>
  );
}
