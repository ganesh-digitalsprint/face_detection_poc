import { api as bxApi } from '../../use-cases/branch-exterior/api/index.js';
import { Empty } from '../../use-cases/branch-exterior/components/ui.jsx';
import { api as fmApi } from '../../use-cases/face-mask/api/index.js';
import usePolling from '../../use-cases/face-mask/hooks/usePolling.js';
import { filterZones, fromBranchZone, fromFaceMaskRoi, SERVICE_START, ZONE_TYPE_LABELS } from './regionsModel.js';

const USE_CASE_LABEL = { branch_exterior: 'Branch Exterior', face_mask: 'Face Mask', vault_access: 'Vault Access' };

async function settle(load) {
  try { return { ok: true, value: await load() }; } catch (error) { return { ok: false, error }; }
}

async function loadAll() {
  const [bxZones, bxCams, fmRois, fmCams] = await Promise.all([
    settle(() => bxApi.get('/zones')), settle(() => bxApi.get('/cameras')),
    settle(() => fmApi.get('/roi')), settle(() => fmApi.get('/cameras')),
  ]);
  const names = (res) => Object.fromEntries((res.ok ? res.value : []).map((c) => [c.id, c.name]));
  const bxNames = names(bxCams);
  const fmNames = names(fmCams);
  const zones = [
    ...(bxZones.ok ? bxZones.value.map(fromBranchZone).map((z) => ({ ...z, camera: bxNames[z.camera_id] || z.camera_id })) : []),
    ...(fmRois.ok ? fmRois.value.map(fromFaceMaskRoi).map((z) => ({ ...z, camera: fmNames[z.camera_id] || z.camera_id })) : []),
  ];
  const unavailable = [];
  if (!bxZones.ok) unavailable.push('branch_exterior');
  if (!fmRois.ok) unavailable.push('face_mask');
  return { zones, unavailable };
}

/** Read-only list of every zone across use cases. A stopped service only hides its own rows. */
export default function ZonesOverview({ useCase, onOpen }) {
  const { data, loading, reload } = usePolling(loadAll, 15000);
  if (loading && !data) return <Empty icon="⏳" bare>Loading zones…</Empty>;
  const rows = filterZones(data?.zones || [], useCase);
  return (
    <div>
      {(data?.unavailable || []).map((id) => (
        <div key={id} className="bx-diag" role="alert" style={{ marginBottom: 10 }}>
          <b>{SERVICE_START[id].name} service unavailable.</b> Its zones are not listed. In <code>{SERVICE_START[id].dir}</code>: <code>{SERVICE_START[id].cmd}</code>
          <button type="button" className="bx-btn bx-btn-sm" style={{ marginLeft: 8 }} onClick={reload}>Retry</button>
        </div>
      ))}
      {rows.length === 0 ? (
        <Empty icon="🗺">No zones yet. Pick a use case above, then a camera, and draw one.</Empty>
      ) : (
        <div className="bx-card" style={{ overflowX: 'auto' }}>
          <table className="bx-table" style={{ width: '100%' }}>
            <thead>
              <tr>
                <th scope="col">Use case</th><th scope="col">Camera</th><th scope="col">Zone</th><th scope="col">Type</th>
                <th scope="col">Points</th><th scope="col">Status</th><th scope="col"><span className="sr-only">Open</span></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((z) => (
                <tr key={`${z.use_case}:${z.id}`}>
                  <td>{USE_CASE_LABEL[z.use_case]}</td><td>{z.camera}</td><td>{z.name}</td>
                  <td>{ZONE_TYPE_LABELS[z.zone_type] || z.zone_type}{z.direction ? ' + direction' : ''}</td>
                  <td>{z.points}</td><td>{z.enabled ? 'Enabled' : 'Disabled'}</td>
                  <td><button type="button" className="bx-btn bx-btn-sm" onClick={() => onOpen(z.use_case, z.camera_id)}>Edit</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
