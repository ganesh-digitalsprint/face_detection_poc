import { useState } from 'react';
import { Cctv, RotateCcw, Square, Video, Webcam } from 'lucide-react';
import { CAMERA_KINDS } from '../../hooks/useCameraSource.js';

const SOURCES = [
  { kind: CAMERA_KINDS.WEBCAM, label: 'Webcam', icon: Webcam },
  { kind: CAMERA_KINDS.CCTV, label: 'CCTV', icon: Cctv },
];
const base = 'inline-flex min-h-11 items-center justify-center gap-2 rounded-md px-4 text-sm font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-50';
const segment = (active) => `${base} ${active ? 'bg-[#34479B] text-white' : 'text-[#55607A] hover:bg-white'}`;
const secondary = `${base} border border-[#E3E7F0] bg-white text-[#0F1B3D] hover:bg-slate-50`;
const danger = `${base} bg-[#B3261E] text-white hover:bg-[#931F18]`;
const primary = `${base} bg-[#34479B] text-white hover:bg-brand-dark`;

/** Source picker + session/camera actions. Every control is a real button with a 44px target. */
export default function VaultCameraControls({ camera, sessionActive, sessionStarted, onRestart, onStop, vault }) {
  const [source, setSource] = useState(camera.kind ?? CAMERA_KINDS.WEBCAM);
  const [streamIndex, setStreamIndex] = useState(0);
  const cameraOn = camera.status === 'starting' || camera.status === 'ready';
  const selected = camera.kind ?? source;

  const choose = (kind) => {
    setSource(kind);
    // Switching source while the camera is on (and no session is running) restarts it on the new source.
    if (cameraOn && kind !== camera.kind) camera.start(kind, { streamIndex });
  };

  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
      <div role="group" aria-label="Camera source" className="inline-flex self-start rounded-lg bg-[#F4F6FB] p-1">
        {SOURCES.map(({ kind, label, icon: Icon }) => (
          <button key={kind} type="button" className={segment(selected === kind)} aria-pressed={selected === kind}
            disabled={sessionActive || camera.status === 'starting'} onClick={() => choose(kind)}>
            <Icon className="h-4 w-4" aria-hidden /> {label}
          </button>
        ))}
      </div>

      {selected === CAMERA_KINDS.CCTV && (
        <div className="flex items-center gap-2 text-sm">
          <label htmlFor="vault_stream_index" className="text-[#55607A]">Stream index</label>
          <input id="vault_stream_index" type="number" min={0} value={streamIndex} disabled={cameraOn}
            onChange={(e) => setStreamIndex(Math.max(0, Number(e.target.value) || 0))}
            className="min-h-11 w-20 rounded-md border border-[#E3E7F0] px-2" />
        </div>
      )}

      {sessionActive && vault.config?.allow_mode_select && (
        <label className="flex min-h-11 items-center gap-2 text-sm font-medium text-[#55607A]">
          Required custodians:
          <select aria-label="Required custodians" value={vault.selectedRequiredPersons ?? vault.config.required_persons}
            disabled className="min-h-9 rounded border border-slate-300 bg-slate-100 px-2">
            <option value={1}>1</option><option value={2}>2</option>
          </select>
        </label>
      )}

      <div className="flex flex-wrap gap-2 sm:ml-auto">
        {cameraOn ? (
          <>
            <button type="button" className={secondary} disabled={!sessionStarted || vault.roomBlocked}
              title={vault.roomBlocked ? 'Vault room session is active' : undefined}
              aria-describedby={vault.roomBlocked ? 'vault-room-restart-disabled' : undefined} onClick={onRestart}>
              <RotateCcw className="h-4 w-4" aria-hidden /> Restart session
            </button>
            <button type="button" className={danger} onClick={onStop}>
              <Square className="h-4 w-4" aria-hidden /> Stop camera
            </button>
          </>
        ) : (
          <button type="button" className={primary} onClick={() => camera.start(source, { streamIndex })}>
            <Video className="h-4 w-4" aria-hidden />
            {camera.status === 'error' ? 'Retry camera' : 'Start camera'}
          </button>
        )}
      </div>
      {sessionStarted && vault.roomBlocked && <p id="vault-room-restart-disabled" className="text-sm text-[#55607A]">Vault room session is active</p>}
    </div>
  );
}
