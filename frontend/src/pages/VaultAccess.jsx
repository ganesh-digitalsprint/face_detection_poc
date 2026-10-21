import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Camera, Info, RotateCcw, X } from 'lucide-react';
import AuthorizationProgress from '../components/vault/AuthorizationProgress.jsx';
import CameraPreview from '../components/vault/CameraPreview.jsx';
import CustodianList from '../components/vault/CustodianList.jsx';
import SecurityVerificationPanel from '../components/vault/SecurityVerificationPanel.jsx';
import ErrorMessage from '../components/common/ErrorMessage.jsx';
import Button from '../components/common/Button.jsx';
import VaultCameraControls from '../components/vault/VaultCameraControls.jsx';
import VaultCameraOverlay from '../components/vault/VaultCameraOverlay.jsx';
import VaultRoomPanel, { VaultRoomCloseAction, VaultRoomVideoOverlay } from '../components/vault/VaultRoomPanel.jsx';
import VaultStatusCard from '../components/vault/VaultStatusCard.jsx';
import useCameraSource from '../hooks/useCameraSource.js';
import useVaultAccess from '../hooks/useVaultAccess.js';
import useVaultRoom from '../hooks/useVaultRoom.js';
import useVaultCounting from '../hooks/useVaultCounting.js';
import { CAMERA_KINDS } from '../hooks/useCameraSource.js';
import { VAULT_VIEW, activeSlot, deriveVaultView, handoffSubject } from '../utils/vaultView.js';

const RUNNING_VIEWS = [VAULT_VIEW.STARTING, VAULT_VIEW.LIVENESS, VAULT_VIEW.IDENTITY, VAULT_VIEW.HANDOFF];
const segment = (active) => `inline-flex min-h-11 items-center justify-center gap-2 rounded-lg px-4 text-sm font-semibold focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand ${active ? 'bg-[#34479B] text-white' : 'text-[#55607A] hover:bg-white'}`;

/** Both panels keep one CameraPreview/video mounted, so switching views never touches the stream. */
export default function VaultAccess() {
  const camera = useCameraSource();
  const [cameraView, setCameraView] = useState('entrance');
  const [demoNoticeVisible, setDemoNoticeVisible] = useState(true);
  const room = useVaultRoom();
  const vault = useVaultAccess(camera, cameraView === 'room', room);
  const counting = useVaultCounting(camera.videoRef, room.roomState, cameraView === 'room', camera.status === 'ready' && camera.kind === CAMERA_KINDS.WEBCAM, room.refreshState);
  const view = deriveVaultView(vault);
  const slot = activeSlot(vault, view);
  const running = RUNNING_VIEWS.includes(view);
  const handoff = view === VAULT_VIEW.HANDOFF;
  const granted = vault.result?.access_granted === true;

  const handleStop = () => { vault.reset(); camera.stop(); };
  const handleReady = () => { vault.reset(); setCameraView('entrance'); };
  const securitySlot = slot ?? (view === VAULT_VIEW.GRANTED ? vault.requiredCount : null);
  const requiredCount = vault.requiredCount ?? vault.config?.required_persons;

  return (
    <div className="-m-4 min-h-full bg-[#F4F6FB] p-4 sm:-m-6 sm:p-6">
      <div className="mx-auto mb-5 flex max-w-[1360px] items-center justify-between gap-3">
        <h2 className="vault-heading text-xl">Vault Access</h2>
        {vault.testMode && <span className="rounded-full bg-amber-100 px-3 py-1.5 text-xs font-bold tracking-wide text-amber-900">TEST MODE · 1 person</span>}
      </div>
      {vault.configError && <div className="mx-auto mb-5 max-w-[1360px] space-y-2" role="alert"><ErrorMessage error={vault.configError} /><Button variant="secondary" icon={RotateCcw} onClick={vault.loadConfig} className="min-h-11">Retry configuration</Button></div>}

      <div className="mx-auto grid max-w-[1360px] gap-6 lg:grid-cols-[minmax(0,1.6fr)_minmax(380px,1fr)]">
        <div className="min-w-0 space-y-6">
          <section aria-label={cameraView === 'entrance' ? 'Entrance camera' : 'Vault room camera'} className="vault-card space-y-4 p-4">
            <div role="group" aria-label="Camera view" className="inline-flex flex-wrap rounded-xl bg-[#F4F6FB] p-1">
              <button type="button" aria-pressed={cameraView === 'entrance'} className={segment(cameraView === 'entrance')} onClick={() => setCameraView('entrance')}><Camera className="h-4 w-4" aria-hidden />Entrance Camera</button>
              <button type="button" aria-pressed={cameraView === 'room'} className={segment(cameraView === 'room')} onClick={() => setCameraView('room')}><Camera className="h-4 w-4" aria-hidden />Vault Room Camera</button>
            </div>
            {cameraView === 'room' && demoNoticeVisible && <div className="flex items-start gap-2 rounded-lg border border-blue-200 bg-blue-50 p-3 text-sm text-blue-950"><Info className="mt-0.5 h-4 w-4 shrink-0" aria-hidden /><p className="flex-1">Demo mode: the vault room view is using this same webcam. In production this will be the vault room's own camera.</p><button type="button" aria-label="Dismiss demo mode notice" className="min-h-11 min-w-11 rounded-md hover:bg-blue-100" onClick={() => setDemoNoticeVisible(false)}><X className="mx-auto h-4 w-4" aria-hidden /></button></div>}
            {cameraView === 'room' && !granted && <span className="inline-flex min-h-8 items-center rounded-full bg-amber-100 px-3 text-xs font-bold text-[#6B4500]">Authentication paused</span>}
            {cameraView === 'entrance' && granted && room.roomState?.state === 'ENTRY_BUFFER' && <div role="status" aria-live="polite" className="rounded-lg bg-blue-100 px-4 py-3 text-sm font-semibold text-blue-950">Entry window: {room.roomState.entry_buffer_remaining_seconds}s</div>}

            <CameraPreview camera={camera} variant={cameraView === 'room' ? 'room' : 'stage'}>
              {cameraView === 'room'
                ? <VaultRoomVideoOverlay roomState={room.roomState} connection={room.connection} counting={counting} mirrored={camera.kind === CAMERA_KINDS.WEBCAM} />
                : <VaultCameraOverlay camera={camera} vault={vault} view={view} onStart={vault.start} onReady={handleReady} onGoRoom={() => setCameraView('room')} />}
            </CameraPreview>
            {cameraView === 'room' && <div className={`flex flex-wrap items-center justify-between gap-2 text-xs ${counting.slow ? 'text-[#8A5A00]' : 'text-[#55607A]'}`} aria-live="off">
              <span>detect · round-trip {counting.medianRequestMs == null ? '—' : `${Math.round(counting.medianRequestMs)} ms median`} · measured {counting.measuredFps == null ? '—' : `${counting.measuredFps.toFixed(1)} fps`} / target {room.roomState?.recommended_fps == null ? '—' : `${room.roomState.recommended_fps} fps`} · processing {counting.processingMs == null ? '—' : `${Math.round(counting.processingMs)} ms`} · detector {room.roomState?.detector_status ?? 'loading'}</span>
              {counting.status === 'error' && <span className="inline-flex items-center gap-2" role="status">{counting.error?.message || 'Counting paused after repeated errors.'}<button type="button" className="min-h-11 rounded px-2 font-semibold text-[#34479B] underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand" onClick={counting.retry}>Retry</button></span>}
            </div>}
            <VaultCameraControls camera={camera} vault={vault} sessionActive={running} sessionStarted={view !== VAULT_VIEW.IDLE} onRestart={vault.start} onStop={handleStop} />
            {cameraView === 'room' && <VaultRoomCloseAction room={room} />}
          </section>

          {cameraView === 'entrance' && <section aria-label="Tips" className="vault-card px-5 py-4 text-sm text-[#55607A]">
            <p><span className="font-semibold text-[#0F1B3D]">Tips:</span> Face the camera in good light, remove glasses or masks, hold still after the challenge.</p>
            <Link to="/live" className="mt-2 inline-flex min-h-11 items-center font-medium text-[#34479B] hover:underline">Live monitoring · annotated streams</Link>
          </section>}
        </div>

        {cameraView === 'entrance' ? <div className="min-w-0 space-y-6">
          <AuthorizationProgress authenticatedCount={vault.authenticatedCount} requiredCount={requiredCount} />
          <SecurityVerificationPanel vault={vault} slot={securitySlot} onRetry={vault.start} onGoRoom={() => setCameraView('room')} />
          <CustodianList custodians={vault.custodians} requiredCount={vault.requiredCount} activeSlot={slot} handoff={handoff} handoffName={handoff ? handoffSubject(vault) : null} />
          <VaultStatusCard result={vault.result} requiredCount={requiredCount} />
        </div> : <aside className="min-w-0 space-y-4" aria-label="Vault room information"><VaultRoomPanel room={room} onRetry={room.retry} /></aside>}
      </div>
    </div>
  );
}
