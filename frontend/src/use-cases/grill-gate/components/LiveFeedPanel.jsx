import { Camera, Plug, PlugZap, Upload } from 'lucide-react';
import { previewState, workerIsActive } from '../grillGateModel.js';
import CameraStage from './CameraStage.jsx';
import VideoTestPanel from './VideoTestPanel.jsx';
import { btnDanger, btnPrimary, Card, ErrorNote, Pill } from './ui.jsx';

/** Dashboard camera preview: blank until a real stream exists, with connect/disconnect driven by worker status. */
export default function LiveFeedPanel({ item, worker, connection, statusError, busy, actionError, onConnect, onDisconnect,
  sourceMode, onSourceModeChange, testFile, onTestFileChange, zones, zoneTypes, reloadZones, onCalibrationSaved }) {
  const preview = previewState(connection);
  const active = workerIsActive(worker) && !statusError;
  const width = item?.assignment?.calibration?.reference_frame?.width ?? worker?.width;
  const height = item?.assignment?.calibration?.reference_frame?.height ?? worker?.height;
  const name = item?.camera?.name ?? 'No camera selected';
  const code = item?.camera?.code?.toUpperCase();

  return (
    <Card title={`Live feed · ${code ? `${code} – ` : ''}${name}`} aside={<Pill tone={connection.tone} dot>{connection.label}</Pill>}>
      <div className="mb-3 flex gap-2" role="group" aria-label="Camera source">
        <button type="button" aria-pressed={sourceMode === 'live'} onClick={() => onSourceModeChange('live')} className="rounded-md bg-[#34479B] px-3 py-2 text-xs font-semibold text-white">Live Camera</button>
        <button type="button" aria-pressed={sourceMode === 'video'} onClick={() => onSourceModeChange('video')} className="rounded-md border border-[#D0D7E6] bg-white px-3 py-2 text-xs font-semibold text-[#34479B]"><Upload size={13} className="mr-1 inline" />Upload / Test Video</button>
      </div>
      {sourceMode === 'video' ? <VideoTestPanel item={item} zones={zones ?? []} zoneTypes={zoneTypes ?? []} reloadZones={reloadZones} onCalibrationSaved={onCalibrationSaved} file={testFile} onFile={onTestFileChange} /> : <CameraStage
        aspect={width && height ? width / height : 16 / 9}
        caption={code ? `${code}${item?.location ? ` · ${item.location.name}` : ''}` : null}
        label={`Camera preview for ${name}: ${preview.title}`}
      >
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 p-6 text-center">
          <span className="flex h-14 w-14 items-center justify-center rounded-full bg-white/10 text-white ring-1 ring-white/20"><Camera size={26} aria-hidden /></span>
          <b className="text-base text-white">{preview.title}</b>
          {preview.detail && <span className="max-w-md text-sm text-slate-200">{preview.detail}</span>}
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
      </CameraStage>}
      {actionError && <div className="mt-3"><ErrorNote>{actionError}</ErrorNote></div>}
    </Card>
  );
}
