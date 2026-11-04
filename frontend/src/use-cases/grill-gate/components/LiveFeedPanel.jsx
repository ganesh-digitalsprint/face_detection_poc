import { Camera, Plug, PlugZap } from 'lucide-react';
import { previewState, workerIsActive } from '../grillGateModel.js';
import CameraStage from './CameraStage.jsx';
import { btnDanger, btnPrimary, Card, ErrorNote, Pill } from './ui.jsx';

/** Dashboard camera preview: blank until a real stream exists, with connect/disconnect driven by worker status. */
export default function LiveFeedPanel({ item, worker, connection, statusError, busy, actionError, onConnect, onDisconnect }) {
  const preview = previewState(connection);
  const active = workerIsActive(worker) && !statusError;
  const width = item?.assignment?.calibration?.reference_frame?.width ?? worker?.width;
  const height = item?.assignment?.calibration?.reference_frame?.height ?? worker?.height;
  const name = item?.camera?.name ?? 'No camera selected';
  const code = item?.camera?.code?.toUpperCase();

  return (
    <Card title={`Live feed · ${code ? `${code} – ` : ''}${name}`} aside={<Pill tone={connection.tone} dot>{connection.label}</Pill>}>
      <CameraStage
        aspect={width && height ? width / height : 16 / 9}
        caption={code ? `${code}${item?.location ? ` · ${item.location.name}` : ''}` : null}
        label={`Camera preview for ${name}: ${preview.title}`}
      >
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 p-6 text-center">
          <span className="flex h-14 w-14 items-center justify-center rounded-full bg-white/5 text-slate-400 ring-1 ring-white/10"><Camera size={26} aria-hidden /></span>
          <b className="text-base text-slate-100">{preview.title}</b>
          {preview.detail && <span className="max-w-md text-sm text-slate-400">{preview.detail}</span>}
          {preview.canConnect && (
            <button type="button" className={`${btnPrimary} mt-1`} onClick={onConnect} disabled={Boolean(busy) || !item}>
              <PlugZap size={14} aria-hidden /> {busy === 'connect' ? 'Connecting…' : 'Connect Camera'}
            </button>
          )}
          {active && (
            <button type="button" className={`${btnDanger} mt-1`} onClick={onDisconnect} disabled={Boolean(busy) || worker?.status === 'stopping'}>
              <Plug size={14} aria-hidden /> {busy === 'disconnect' ? 'Disconnecting…' : 'Disconnect'}
            </button>
          )}
        </div>
      </CameraStage>
      {actionError && <div className="mt-3"><ErrorNote>{actionError}</ErrorNote></div>}
    </Card>
  );
}
