import { useCallback, useEffect, useMemo, useState } from 'react';
import { api, bxApiUrl } from '../api/index.js';
import { api as fmApi } from '../../face-mask/api/index.js';
import FaceMaskBriefSection from '../../face-mask/components/FaceMaskSummary.jsx';
import { serviceById, unavailableMessage } from '../../../config/serviceRegistry.js';
import BriefFilterBar from '../components/BriefFilterBar.jsx';
import { downloadBriefCsv } from '../briefDownload.js';
import {
  branchBriefParams, cameraValue, DEFAULT_FILTERS, describeFilters, includesUseCase, resolveRange,
} from '../briefFilters.js';

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

const toQuery = (params) => `?${new URLSearchParams(params).toString()}`;

export default function SecurityBriefPage() {
  const [filters, setFilters] = useState(DEFAULT_FILTERS);
  const [format, setFormat] = useState('pdf');
  const [cameras, setCameras] = useState([]);
  const [b, setB] = useState(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(false);
  const range = useMemo(() => resolveRange(filters), [filters]);
  const showBranch = includesUseCase(filters, 'branch_exterior');
  const showFaceMask = includesUseCase(filters, 'face_mask');
  const showVault = filters.useCase === 'vault_access';
  const cameraNames = useMemo(() => Object.fromEntries(cameras.map((c) => [cameraValue(c.useCase, c.id), c.label])), [cameras]);
  const filterKey = JSON.stringify(filters);

  useEffect(() => {
    let alive = true;
    const load = (useCase, label, promise) => promise
      .then((list) => list.map((c) => ({ useCase, id: c.id, name: c.name, label: `${label}: ${c.name}` })))
      .catch(() => []);
    Promise.all([load('branch_exterior', 'Branch', api.get('/cameras')), load('face_mask', 'Face Mask', fmApi.get('/cameras'))])
      .then((lists) => { if (alive) setCameras(lists.flat()); });
    return () => { alive = false; };
  }, []);

  const load = useCallback(async () => {
    if (!showBranch || range.error) { setB(null); setError(''); return; }
    try {
      const { params } = branchBriefParams(filters);
      setB(await api.get(`/brief${toQuery(params)}`)); setError('');
    } catch (e) { setB(null); setError(e.message); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterKey, showBranch, range.error]);
  useEffect(() => { load(); }, [load]);

  const download = async () => {
    if (format === 'pdf') { window.print(); return; }
    setBusy(true); setNotice(null);
    try {
      const result = await downloadBriefCsv(filters, cameraNames);
      setNotice(result.fileName
        ? { kind: 'ok', text: `Downloaded ${result.fileName}.`, skipped: result.skipped }
        : { kind: 'warn', text: 'Nothing was downloaded.', skipped: result.skipped });
    } catch (e) { setNotice({ kind: 'warn', text: `Download failed: ${e.message}`, skipped: [] }); } finally { setBusy(false); }
  };

  // A stopped service must never break the whole brief: the Branch part shows its own message and every other
  // section (controls, Face Mask) still renders. With all services up the output is unchanged.
  const t = b?.totals;
  const kp = t ? [['Incidents', t.events, ''], ['High / critical', t.high_critical, t.high_critical ? '#dc2626' : ''], ['Critical', t.critical, t.critical ? '#dc2626' : ''],
    ['With evidence saved', t.with_evidence, ''], ['Cameras involved', t.cameras, ''], ['Marked false positive', t.false_positive, '']] : [];
  const maxH = b ? Math.max(1, ...b.by_hour.map((x) => x.count)) : 1;

  return (
    <>
      <BriefFilterBar value={filters} onChange={(next) => { setFilters(next); setNotice(null); }} cameras={cameras} />
      <div className="bx-row bx-gap-8 bx-wrap bx-mb-16 bx-no-print" style={{ alignItems: 'flex-end' }}>
        <button type="button" className="bx-btn" onClick={() => { load(); setFilters((f) => ({ ...f })); }}>↻ Refresh</button>
        <label className="bx-field" style={{ margin: 0 }}>Format
          <select className="bx-input" value={format} onChange={(e) => setFormat(e.target.value)} aria-label="Download format">
            <option value="pdf">PDF</option><option value="csv">CSV</option>
          </select>
        </label>
        <button type="button" className="bx-btn bx-btn-primary" onClick={download} disabled={busy || Boolean(range.error)}>
          {busy ? 'Preparing…' : 'Download'}
        </button>
      </div>
      <p className="bx-print-only" style={{ margin: '0 0 12px' }}><b>Security Brief</b> · {describeFilters(filters, cameraNames)} · generated {new Date().toLocaleString()}</p>
      {range.error && <div className="bx-diag bx-no-print" role="alert">{range.error}</div>}
      {notice && (
        <div className={`bx-${notice.kind === 'ok' ? 'hint' : 'diag'} bx-no-print`} role="status">
          {notice.text}
          {notice.skipped.length > 0 && (
            <ul style={{ margin: '6px 0 0 18px' }}>{notice.skipped.map((x) => <li key={x.label}><b>Skipped {x.label}:</b> {x.reason}</li>)}</ul>
          )}
        </div>
      )}
      {showVault && <div className="bx-card" role="status"><b>Vault Access</b> has no section or export on this page yet: it is not connected to the brief.</div>}
      {showBranch && branchBriefParams(filters).capped && (
        <p className="bx-muted bx-no-print" style={{ fontSize: 12 }}>The Branch Exterior summary covers at most the last 30 days.</p>
      )}

      {error && (
        <div className="bx-card" role="alert"><ul className="bx-headline"><li style={{ color: '#dc2626' }}>
          {unavailableMessage(serviceById('branch'))} ({error})
        </li></ul></div>
      )}
      {showBranch && !b && !error && !range.error && <div className="bx-row bx-gap-8 bx-muted" style={{ padding: 30, justifyContent: 'center' }}><span className="bx-spinner" /> Loading…</div>}
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
                <thead><tr><th>Time</th><th>Severity</th><th>Type</th><th>Camera / zone</th><th>AI observation</th><th /></tr></thead>
                <tbody>
                  {b.top_incidents.length === 0 && <tr><td colSpan={6} className="bx-muted">No incidents in this period.</td></tr>}
                  {b.top_incidents.map((i) => (
                    <tr key={i.id}>
                      <td>{new Date(i.time).toLocaleString()}</td>
                      <td><span style={{ color: SEV_COLOR[i.severity] || '#888', fontWeight: 700 }}>{i.severity.toUpperCase()}</span></td>
                      <td>{i.title || i.label}</td>
                      <td>{i.camera}{i.zone ? ` / ${i.zone}` : ''}</td>
                      <td style={{ maxWidth: 420 }}>
                        {i.observation || i.message}
                        {i.caution ? <div className="bx-muted" style={{ marginTop: 4 }}>{i.caution}</div> : null}
                        {i.verification ? <div className="bx-muted" style={{ marginTop: 4, fontSize: 12 }}>Status: {i.verification}</div> : null}
                      </td>
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
      {showFaceMask && !range.error && <FaceMaskBriefSection filters={filters} />}
    </>
  );
}
