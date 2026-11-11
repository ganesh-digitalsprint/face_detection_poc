import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { toggleTheme, useBxTheme } from '../../branch-exterior/theme.js';
import { api, coveringLabel, fmtTime, qs } from '../api/index.js';
import FaceMaskEventDetail from '../components/FaceMaskEventDetail.jsx';
import { EventStatusBadge, PageState, PrivacyNote } from '../components/ui.jsx';
import usePolling from '../hooks/usePolling.js';
import '../../branch-exterior/branchExterior.css';

const PAGE_SIZE = 15;
const VIEWS = { active: 'OPEN,UNDER_REVIEW', history: 'CONFIRMED,FALSE_POSITIVE,CLOSED', all: '' };
const COVERINGS = [
  ['', 'All coverings'], ['lower_face_covering', 'Mask / scarf'], ['head_covering', 'Cap / helmet'],
  ['full_face_covering', 'Full face covering'], ['surgical_mask', 'Surgical mask'], ['scarf', 'Scarf'],
  ['cap_concealing', 'Cap'], ['helmet', 'Helmet'], ['other_mask', 'Other'],
];
const EMPTY = { from: '', to: '', camera_id: '', covering_type: '' };
const toIso = (local) => (local ? new Date(local).toISOString() : '');

/** Alerts > Face Mask events: summary cards, filters, list and the review/evidence panel on the right. */
export default function FaceMaskEventsTab() {
  const theme = useBxTheme();
  const [search, setSearch] = useSearchParams();
  const selected = search.get('event') || '';
  const [view, setView] = useState('active');
  const [sort, setSort] = useState('desc');
  const [filters, setFilters] = useState(EMPTY);
  const [page, setPage] = useState(0);
  const set = (k) => (ev) => { setFilters((f) => ({ ...f, [k]: ev.target.value })); setPage(0); };

  const cams = usePolling(() => api.get('/cameras'), 15000);
  const base = { date_from: toIso(filters.from), date_to: toIso(filters.to), camera_id: filters.camera_id, covering_type: filters.covering_type };
  const list = usePolling(() => api.get(`/events${qs({
    ...base, statuses: VIEWS[view], sort, limit: PAGE_SIZE, offset: page * PAGE_SIZE })}`), 5000, [filters, view, sort, page]);
  const cards = usePolling(async () => {
    const count = async (statuses) => (await api.get(`/events${qs({ ...base, statuses, limit: 1 })}`)).total;
    const [total, active, confirmed, falsePositive] = await Promise.all([
      count(''), count('OPEN,UNDER_REVIEW'), count('CONFIRMED'), count('FALSE_POSITIVE')]);
    return { total, active, confirmed, falsePositive };
  }, 10000, [filters]);

  const cameras = cams.data || [];
  const nameOf = (id) => cameras.find((c) => c.id === id)?.name || id.slice(0, 8);
  const total = list.data?.total || 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  useEffect(() => { if (page > pages - 1) setPage(0); }, [pages, page]);

  const select = (id) => {
    const next = new URLSearchParams(search);
    if (id) next.set('event', id); else next.delete('event');
    setSearch(next, { replace: true });
  };
  const refresh = () => { list.reload(); cards.reload(); };
  const c = cards.data;

  return (
    <div className="bx-page" data-theme={theme} style={{ padding: 0 }}>
      <PrivacyNote />
      {c && (
        <div className="bx-kpis">
          {[['Events', c.total], ['Active', c.active, c.active > 0], ['Confirmed', c.confirmed], ['False positives', c.falsePositive]].map(([l, v, hot]) => (
            <div key={l} style={hot ? { borderColor: '#dc2626', background: 'rgba(220,38,38,.12)' } : undefined}><div className="v">{v}</div><div className="l">{l}</div></div>
          ))}
        </div>
      )}
      <div className="bx-card bx-mb-16">
        <div className="bx-row bx-gap-8 bx-wrap" role="group" aria-label="Event view" style={{ marginBottom: 8 }}>
          {Object.keys(VIEWS).map((v) => (
            <button key={v} type="button" aria-pressed={view === v} className={`bx-btn bx-btn-sm${view === v ? ' bx-btn-primary' : ''}`}
              onClick={() => { setView(v); setPage(0); }}>{v[0].toUpperCase() + v.slice(1)}</button>
          ))}
          <button type="button" className="bx-btn bx-btn-sm" onClick={refresh}>Refresh</button>
          <button type="button" className="bx-btn bx-btn-sm" onClick={toggleTheme} aria-label="Toggle theme">Theme</button>
        </div>
        <div className="bx-field-row" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))' }}>
          <label className="bx-field">From <input className="bx-input" type="datetime-local" value={filters.from} onChange={set('from')} /></label>
          <label className="bx-field">To <input className="bx-input" type="datetime-local" value={filters.to} onChange={set('to')} /></label>
          <label className="bx-field">Camera
            <select className="bx-input" value={filters.camera_id} onChange={set('camera_id')}>
              <option value="">All cameras</option>{cameras.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
            </select>
          </label>
          <label className="bx-field">Covering
            <select className="bx-input" value={filters.covering_type} onChange={set('covering_type')}>
              {COVERINGS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </label>
          <label className="bx-field">Sort
            <select className="bx-input" value={sort} onChange={(e) => { setSort(e.target.value); setPage(0); }}>
              <option value="desc">Newest first</option><option value="asc">Oldest first</option>
            </select>
          </label>
        </div>
        <button type="button" className="bx-btn bx-btn-sm" onClick={() => { setFilters(EMPTY); setPage(0); }}>Clear filters</button>
      </div>

      <div className="bx-two-col" style={{ gridTemplateColumns: selected ? 'minmax(0,1.2fr) minmax(0,1fr)' : '1fr', alignItems: 'start' }}>
        <div className="bx-card">
          <PageState loading={list.loading} error={list.error} data={list.data} onRetry={list.reload}
            isEmpty={(d) => d.total === 0} emptyIcon="🛡" emptyText="No Face Mask events match these filters.">
            <div className="bx-scroll-x">
              <table className="bx-table">
                <thead><tr><th>Time</th><th>Camera</th><th>Track</th><th>Covering</th><th>Score</th><th>Status</th></tr></thead>
                <tbody>
                  {(list.data?.items || []).map((e) => (
                    <tr key={e.id} className="clickable" tabIndex={0} aria-selected={e.id === selected}
                      style={e.id === selected ? { outline: '2px solid #3c5ba4' } : undefined}
                      onClick={() => select(e.id)} onKeyDown={(k) => { if (k.key === 'Enter') select(e.id); }}>
                      <td>{fmtTime(e.first_seen)}</td><td>{nameOf(e.camera_id)}</td><td>#{e.track_id}</td>
                      <td>{coveringLabel(e.covering_type)}</td><td>{e.score.toFixed(2)}</td><td><EventStatusBadge status={e.status} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="bx-row bx-gap-8" style={{ justifyContent: 'space-between', marginTop: 12 }}>
              <span className="bx-muted" style={{ fontSize: 13 }}>{total} event{total === 1 ? '' : 's'} · page {page + 1} of {pages}</span>
              <span className="bx-row bx-gap-8">
                <button type="button" className="bx-btn bx-btn-sm" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>Previous</button>
                <button type="button" className="bx-btn bx-btn-sm" disabled={page >= pages - 1} onClick={() => setPage((p) => p + 1)}>Next</button>
              </span>
            </div>
          </PageState>
        </div>
        {selected && <FaceMaskEventDetail eventId={selected} cameras={cameras} onClose={() => select('')} onChanged={refresh} />}
      </div>
    </div>
  );
}
