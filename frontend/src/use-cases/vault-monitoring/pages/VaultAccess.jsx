import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Link } from 'react-router-dom';
import { Camera, Maximize2, RotateCcw, Shapes } from 'lucide-react';
import AuthorizationProgress from '../components/vault/AuthorizationProgress.jsx';
import CameraPreview from '../components/vault/CameraPreview.jsx';
import CustodianList from '../components/vault/CustodianList.jsx';
import SecurityVerificationPanel from '../components/vault/SecurityVerificationPanel.jsx';
import ErrorMessage from '../../../components/common/ErrorMessage.jsx';
import Button from '../../../components/common/Button.jsx';
import VaultCameraControls from '../components/vault/VaultCameraControls.jsx';
import VaultCameraOverlay from '../components/vault/VaultCameraOverlay.jsx';
import VaultRoomPanel, { VaultRoomCloseAction, VaultRoomVideoOverlay } from '../components/vault/VaultRoomPanel.jsx';
import VaultRoomCameraControls from '../components/vault/VaultRoomCameraControls.jsx';
import VaultRoomReplayPreview from '../components/vault/VaultRoomReplayPreview.jsx';
import useVaultRoomReplay from '../hooks/useVaultRoomReplay.js';
import useVaultRoomRegions from '../hooks/useVaultRoomRegions.js';
import VaultRoomZones from '../components/vault/VaultRoomZones.jsx';
import VaultStatusCard from '../components/vault/VaultStatusCard.jsx';
import useCameraSource from '../hooks/useCameraSource.js';
import useVaultAccess from '../hooks/useVaultAccess.js';
import useVaultRoom from '../hooks/useVaultRoom.js';
import useVaultRoomCamera from '../hooks/useVaultRoomCamera.js';
import useVaultCounting from '../hooks/useVaultCounting.js';
import { VAULT_VIEW, activeSlot, deriveVaultView, handoffSubject } from '../utils/vaultView.js';
import './VaultRoom.css';

const RUNNING_VIEWS = [VAULT_VIEW.STARTING, VAULT_VIEW.LIVENESS, VAULT_VIEW.IDENTITY, VAULT_VIEW.HANDOFF];
const segment = (active) => `inline-flex min-h-11 items-center justify-center gap-2 rounded-lg px-4 text-sm font-semibold focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand ${active ? 'bg-[#34479B] text-white' : 'text-[#55607A] hover:bg-white'}`;

/** Both panels keep one CameraPreview/video mounted, so switching views never touches the stream. */
export default function VaultAccess() {
  const camera = useCameraSource();
  const [cameraView, setCameraView] = useState('entrance');
  const isRoom = cameraView !== 'entrance';
  const roomPreviewRef = useRef(null);
  const roomPreviewSlotRef = useRef(null);
  const zonesPreviewSlotRef = useRef(null);
  const [previewHost] = useState(() => document.createElement('div'));
  const [fullscreenError, setFullscreenError] = useState('');
  const room = useVaultRoom();
  const roomCamera = useVaultRoomCamera();
  const regions = useVaultRoomRegions(isRoom);
  const replay = useVaultRoomReplay(regions.profileId, regions.ready);
  const roomCounting = useVaultCounting(roomCamera.videoRef, room.roomState, isRoom && roomCamera.kind === 'webcam',
    roomCamera.status === 'ready', room.refreshState, roomCamera.posePreview);
  const vault = useVaultAccess(camera, isRoom, room);
  const view = deriveVaultView(vault);
  const slot = activeSlot(vault, view);
  const running = RUNNING_VIEWS.includes(view);
  const handoff = view === VAULT_VIEW.HANDOFF;
  const granted = vault.result?.access_granted === true;

  const handleStop = () => { vault.reset(); camera.stop(); };
  const handleReady = () => { vault.reset(); setCameraView('entrance'); };
  const securitySlot = slot ?? (view === VAULT_VIEW.GRANTED ? vault.requiredCount : null);
  const requiredCount = vault.requiredCount ?? vault.config?.required_persons;
  useEffect(() => { if (!isRoom) replay.select(false); }, [isRoom, replay.select]);
  useLayoutEffect(() => {
    if (!isRoom) return undefined;
    const slot = cameraView === 'zones' ? zonesPreviewSlotRef.current : roomPreviewSlotRef.current;
    slot?.appendChild(previewHost);
    return () => previewHost.remove();
  }, [cameraView, isRoom, previewHost]);
  const openRoomFullscreen = async () => {
    try {
      await roomPreviewRef.current?.requestFullscreen();
      setFullscreenError('');
    } catch {
      setFullscreenError('Full screen is unavailable in this browser.');
    }
  };

  return (
    <div className={`${isRoom ? 'vault-room-page ' : ''}${cameraView === 'zones' ? 'vault-zones-page ' : ''}-m-4 min-h-full bg-[#F4F6FB] p-4 sm:-m-6 sm:p-6`}>
      {vault.testMode && <div className="mx-auto mb-5 max-w-[1360px]"><span className="inline-flex rounded-full bg-amber-100 px-3 py-1.5 text-xs font-bold tracking-wide text-amber-900">TEST MODE · 1 person</span></div>}
      {vault.configError && <div className="mx-auto mb-5 max-w-[1360px] space-y-2" role="alert"><ErrorMessage error={vault.configError} /><Button variant="secondary" icon={RotateCcw} onClick={vault.loadConfig} className="min-h-11">Retry configuration</Button></div>}

      <div className={`mx-auto grid max-w-[1360px] gap-6 ${cameraView === 'entrance'
        ? 'lg:grid-cols-[minmax(0,1fr)_300px] xl:grid-cols-[minmax(0,1fr)_340px]'
        : 'room-page-layout'}`}>
        <div className="min-w-0 space-y-6">
          <section aria-label={cameraView === 'entrance' ? 'Entrance camera' : 'Vault room camera'} className={`vault-card space-y-4 p-4 ${isRoom ? 'room-camera-card' : ''}`}>
            <div className={isRoom ? 'room-camera-heading' : ''}>
            <div role="group" aria-label="Camera view" className="inline-flex flex-wrap rounded-xl bg-[#F4F6FB] p-1">
              <button type="button" aria-pressed={cameraView === 'entrance'} className={segment(cameraView === 'entrance')} onClick={() => setCameraView('entrance')}><Camera className="h-4 w-4" aria-hidden />Entrance Camera</button>
              <button type="button" aria-pressed={cameraView === 'room'} className={segment(cameraView === 'room')} onClick={() => setCameraView('room')}><Camera className="h-4 w-4" aria-hidden />Vault Room Camera</button>
              <button type="button" aria-pressed={cameraView === 'zones'} className={segment(cameraView === 'zones')} onClick={() => setCameraView('zones')}><Shapes className="h-4 w-4" aria-hidden />Zones &amp; Regions</button>
            </div>
            {isRoom && !granted && <span className="inline-flex min-h-8 items-center rounded-full bg-amber-100 px-3 text-xs font-bold text-[#6B4500]">Authentication paused</span>}
            {isRoom && <button type="button" onClick={openRoomFullscreen} className="room-fullscreen-button"><Maximize2 className="h-4 w-4" aria-hidden />Full screen</button>}
            </div>
            {isRoom && fullscreenError && <p role="status" className="text-sm text-amber-800">{fullscreenError}</p>}
            {cameraView === 'entrance' && granted && room.roomState?.state === 'ENTRY_BUFFER' && <div role="status" aria-live="polite" className="rounded-lg bg-blue-100 px-4 py-3 text-sm font-semibold text-blue-950">Entry window: {room.roomState.entry_buffer_remaining_seconds}s</div>}

            {isRoom ? <>
              <VaultRoomCameraControls camera={roomCamera} counting={roomCounting} replay={replay} regions={regions} zonesLayout={cameraView === 'zones'} closeAction={<VaultRoomCloseAction room={room} />}>
              <div ref={roomPreviewSlotRef} hidden={cameraView === 'zones'} className="room-preview-shell-slot" />
              {createPortal(<div ref={roomPreviewRef} className="room-preview-shell">
              {replay.enabled ? <VaultRoomReplayPreview replay={replay} zonesLayout={cameraView === 'zones'} /> : <CameraPreview camera={roomCamera} variant="room" errorHint="Check browser camera permission or the RTSP URL and network reachability.">
                <VaultRoomVideoOverlay roomState={room.roomState} connection={room.connection}
                  counting={roomCamera.kind === 'webcam' ? roomCounting : { tracks: [] }}
                  poses={roomCamera.kind === 'webcam' ? roomCounting.poses : []}
                  mirrored={roomCamera.kind === 'webcam'} />
              </CameraPreview>}
              </div>, previewHost)}
              </VaultRoomCameraControls>
            </> : <CameraPreview camera={camera} variant="stage">
              <VaultCameraOverlay camera={camera} vault={vault} view={view} onStart={vault.start} onReady={handleReady} onGoRoom={() => setCameraView('room')} />
            </CameraPreview>}
            {isRoom && (roomCamera.status === 'streaming' || roomCounting.status === 'running') && <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-[#55607A]" aria-live="off">
              <span>Vault Room tracking · processing {room.roomState?.rolling_median_ms == null ? '—' : `${Math.round(room.roomState.rolling_median_ms)} ms median`} · measured {room.roomState?.measured_fps == null ? '—' : `${room.roomState.measured_fps.toFixed(1)} fps`} / target {room.roomState?.recommended_fps == null ? '—' : `${room.roomState.recommended_fps} fps`} · detector {room.roomState?.detector_status ?? 'loading'}</span>
            </div>}
            {isRoom && roomCamera.posePreview && (() => {
              const metrics = roomCamera.kind === 'webcam' ? roomCounting.poseMetrics : roomCamera.poseMetrics;
              return <div className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-xs text-blue-950" aria-live="polite">
                Pose model {metrics?.model_status ?? metrics?.status ?? 'loading'} · {metrics?.pose_count ?? 0} pose(s) · inference {metrics?.inference_ms == null ? '—' : `${metrics.inference_ms} ms`} · avg {metrics?.average_inference_ms == null ? '—' : `${metrics.average_inference_ms} ms`} · {metrics?.processing_fps == null ? '—' : `${metrics.processing_fps} fps`}{metrics?.initialization_ms != null ? ` · init ${Math.round(metrics.initialization_ms)} ms` : ''}{metrics?.error ? ` · ${metrics.error}` : ''}
              </div>;
            })()}
            {cameraView === 'entrance' && <VaultCameraControls camera={camera} vault={vault} sessionActive={running} sessionStarted={view !== VAULT_VIEW.IDLE} onRestart={vault.start} onStop={handleStop} />}
          </section>
          {isRoom && <VaultRoomZones active={cameraView === 'zones'} regions={regions} previewRef={roomPreviewRef} previewSlotRef={zonesPreviewSlotRef} replay={replay} camera={roomCamera} />}

          {cameraView === 'entrance' && <section aria-label="Tips" className="vault-card px-5 py-4 text-sm text-[#55607A]">
            <p><span className="font-semibold text-[#0F1B3D]">Tips:</span> Face the camera in good light, remove glasses or masks, hold still after the challenge.</p>
            <Link to="/live" className="mt-2 inline-flex min-h-11 items-center font-medium text-[#34479B] hover:underline">Live monitoring · annotated streams</Link>
          </section>}
        </div>

        {cameraView === 'entrance' ? <div className="min-w-0 space-y-4 [&>.vault-card]:p-4 [&_.text-base]:text-sm [&_.text-sm]:text-[13px] [&_.text-lg]:text-base [&_.text-3xl]:text-2xl [&_ul]:space-y-2 [&_li.border]:p-3">
          <AuthorizationProgress authenticatedCount={vault.authenticatedCount} requiredCount={requiredCount} />
          <SecurityVerificationPanel vault={vault} slot={securitySlot} onRetry={vault.start} onGoRoom={() => setCameraView('room')} />
          <CustodianList custodians={vault.custodians} requiredCount={vault.requiredCount} activeSlot={slot} handoff={handoff} handoffName={handoff ? handoffSubject(vault) : null} />
          <VaultStatusCard result={vault.result} requiredCount={requiredCount} />
        </div> : <aside hidden={cameraView === 'zones'} className="min-w-0 space-y-4" aria-label="Vault room information"><VaultRoomPanel room={replay.enabled ? replay.room : room} onRetry={room.retry}
          activityContext={{ enabled: cameraView === 'room', source: regions.source, sourceId: replay.enabled ? replay.session?.session_id : regions.profileId }} /></aside>}
      </div>
    </div>
  );
}
