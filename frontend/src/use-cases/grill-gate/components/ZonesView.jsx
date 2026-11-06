/* Unused: replaced by the three-section Grill Gate page. Kept on disk, no longer linked. */
import { Link } from 'react-router-dom';
import { ExternalLink } from 'lucide-react';
import { zoneColor, zoneCoverage } from '../grillGateModel.js';
import CameraStage, { ZoneOverlay } from './CameraStage.jsx';
import { btnPrimary, Card, ErrorNote, Pill } from './ui.jsx';

/** Read-only zone coverage; editing stays in the common Regions & Zones editor (no second zone system). */
export default function ZonesView({ item, zones, loading, error, zoneTypes }) {
  const rows = zoneCoverage(zoneTypes, zones);
  const reference = item.assignment.calibration?.reference_frame;
  const editorHref = `/regions?use_case=grill_gate&location_id=${encodeURIComponent(item.camera?.location_id ?? '')}&camera_id=${encodeURIComponent(item.assignment.camera_id)}`;

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(340px,480px)]">
      <Card title="Configured zones" aside={<Link to={editorHref} className={btnPrimary}>Open zone editor <ExternalLink size={13} aria-hidden /></Link>}>
        <CameraStage aspect={reference ? reference.width / reference.height : 16 / 9} label="Configured Grill Gate zone outlines">
          <ZoneOverlay zones={zones} />
          {!zones.length && <p className="absolute inset-0 flex items-center justify-center text-sm text-slate-500">{loading ? 'Loading zones…' : 'No zones configured'}</p>}
        </CameraStage>
        <p className="mt-3 text-xs leading-5 text-[#55607A]">
          Polygons use normalized raw-frame coordinates. The gate_crossing polygon is the corridor; the directional virtual line is set under Calibration.
        </p>
      </Card>
      <Card title="Zone types">
        {error && <div className="mb-3"><ErrorNote>{error}</ErrorNote></div>}
        <ul className="divide-y divide-[#E3E7F0]">
          {rows.map((row) => (
            <li key={row.key} className="flex items-start justify-between gap-3 py-2.5">
              <span className="min-w-0">
                <span className="flex items-center gap-2 text-sm font-semibold text-[#0F1B3D]">
                  <span className="h-2.5 w-2.5 rounded-sm" style={{ background: zoneColor(row.key) }} aria-hidden />{row.label}
                </span>
                <span className="mt-0.5 block text-xs text-[#55607A]">
                  {row.zones.length ? row.zones.map((zone) => `${zone.name}${zone.enabled === false ? ' (disabled)' : ''}`).join(', ') : row.description}
                </span>
              </span>
              <Pill tone={row.zones.some((zone) => zone.enabled !== false) ? 'ok' : 'idle'}>{loading ? '…' : row.zones.length ? `${row.zones.length} configured` : 'none'}</Pill>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}
