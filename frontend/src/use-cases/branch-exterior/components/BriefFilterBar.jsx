import { cameraValue, coveringApplies, PERIODS, STATUSES, USE_CASES } from '../briefFilters.js';

const COVERINGS = [
  ['', 'Any covering'], ['lower_face_covering', 'Mask / scarf'], ['head_covering', 'Cap / helmet'], ['full_face_covering', 'Full face'],
  ['surgical_mask', 'Surgical mask'], ['scarf', 'Scarf'], ['cap_concealing', 'Cap'], ['helmet', 'Helmet'], ['other_mask', 'Other'],
];

// One compact row at laptop width (>= 1366 px); the flex row wraps only when the screen is narrower.
const ROW = { display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'flex-end' };
const FIELD = { margin: 0, minWidth: 0 };

/**
 * Filter bar of the Security Brief. `cameras` = [{ useCase, id, name, label }].
 * Controlled: `value` is the filters object, `onChange(next)` receives a new object (never mutated).
 */
export default function BriefFilterBar({ value, onChange, cameras }) {
  const set = (key) => (event) => {
    const next = { ...value, [key]: event.target.value };
    if (key === 'useCase') {
      next.camera = '';
      if (!coveringApplies(next)) next.covering = '';
    }
    onChange(next);
  };
  const custom = value.period === 'custom';
  const visibleCameras = cameras.filter((c) => value.useCase === 'all' || c.useCase === value.useCase);
  return (
    <div className="bx-card bx-mb-16 bx-no-print" role="search" aria-label="Security Brief filters">
      <div style={ROW}>
        <label className="bx-field" style={{ ...FIELD, flex: '1 1 130px' }}>Use case
          <select className="bx-input" value={value.useCase} onChange={set('useCase')}>
            {USE_CASES.map((u) => <option key={u.id} value={u.id}>{u.label}</option>)}
          </select>
        </label>
        <label className="bx-field" style={{ ...FIELD, flex: '1 1 130px' }}>Period
          <select className="bx-input" value={value.period} onChange={set('period')}>
            {PERIODS.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
          </select>
        </label>
        <label className="bx-field" style={{ ...FIELD, flex: '1.3 1 160px' }}>From
          <input className="bx-input" type="datetime-local" value={value.from} onChange={set('from')} disabled={!custom} />
        </label>
        <label className="bx-field" style={{ ...FIELD, flex: '1.3 1 160px' }}>To
          <input className="bx-input" type="datetime-local" value={value.to} onChange={set('to')} disabled={!custom} />
        </label>
        <label className="bx-field" style={{ ...FIELD, flex: '1 1 140px' }}>Camera
          <select className="bx-input" value={value.camera} onChange={set('camera')}>
            <option value="">All cameras</option>
            {visibleCameras.map((c) => <option key={cameraValue(c.useCase, c.id)} value={cameraValue(c.useCase, c.id)}>{c.label}</option>)}
          </select>
        </label>
        <label className="bx-field" style={{ ...FIELD, flex: '1 1 120px' }}>Status
          <select className="bx-input" value={value.status} onChange={set('status')}>
            <option value="">Any status</option>
            {STATUSES.map((s) => <option key={s} value={s}>{s.replace('_', ' ')}</option>)}
          </select>
        </label>
        <label className="bx-field" style={{ ...FIELD, flex: '1 1 120px' }}>Covering
          <select className="bx-input" value={value.covering} onChange={set('covering')} disabled={!coveringApplies(value)}
            title={coveringApplies(value) ? undefined : 'Covering applies to Face Mask only'}>
            {COVERINGS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
      </div>
    </div>
  );
}
