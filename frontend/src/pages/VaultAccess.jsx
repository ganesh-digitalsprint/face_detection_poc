import { Link } from 'react-router-dom';
import AuthorizationProgress from '../components/vault/AuthorizationProgress.jsx';
import CameraPreview from '../components/vault/CameraPreview.jsx';
import CustodianList from '../components/vault/CustodianList.jsx';
import SecurityVerificationPanel from '../components/vault/SecurityVerificationPanel.jsx';
import VaultCameraControls from '../components/vault/VaultCameraControls.jsx';
import VaultCameraOverlay from '../components/vault/VaultCameraOverlay.jsx';
import VaultStatusCard from '../components/vault/VaultStatusCard.jsx';
import useCameraSource from '../hooks/useCameraSource.js';
import useVaultAccess from '../hooks/useVaultAccess.js';
import { VAULT_VIEW, activeSlot, deriveVaultView, handoffSubject } from '../utils/vaultView.js';

const RUNNING_VIEWS = [VAULT_VIEW.STARTING, VAULT_VIEW.LIVENESS, VAULT_VIEW.IDENTITY, VAULT_VIEW.HANDOFF];

/** Vault Access: any camera source -> backend liveness -> recognition -> authorization -> decision. */
export default function VaultAccess() {
  const camera = useCameraSource();
  const vault = useVaultAccess(camera);
  const view = deriveVaultView(vault);
  const slot = activeSlot(vault, view);
  const running = RUNNING_VIEWS.includes(view);
  const handoff = view === VAULT_VIEW.HANDOFF;

  const handleStop = () => { vault.reset(); camera.stop(); };
  // After a decision, return to the ready state so the next pair can start a fresh session.
  const handleReady = () => { vault.reset(); };
  // The granted card set stays visible after a grant until a new session starts.
  const securitySlot = slot ?? (view === VAULT_VIEW.GRANTED ? vault.requiredCount : null);

  return (
    <div className="-m-4 min-h-full bg-[#F4F6FB] p-4 sm:-m-6 sm:p-6">
      <div className="mx-auto grid max-w-[1360px] gap-6 lg:grid-cols-[minmax(0,1.6fr)_minmax(380px,1fr)]">
        <div className="min-w-0 space-y-6">
          <section aria-label="Camera" className="vault-card space-y-4 p-4">
            <CameraPreview camera={camera} variant="stage">
              <VaultCameraOverlay
                camera={camera}
                vault={vault}
                view={view}
                onStart={vault.start}
                onReady={handleReady}
              />
            </CameraPreview>
            <VaultCameraControls
              camera={camera}
              sessionActive={running}
              sessionStarted={view !== VAULT_VIEW.IDLE}
              onRestart={vault.start}
              onStop={handleStop}
            />
          </section>
          <section aria-label="Tips" className="vault-card px-5 py-4 text-sm text-[#55607A]">
            <p>
              <span className="font-semibold text-[#0F1B3D]">Tips:</span> Face the camera in good light, remove
              glasses or masks, hold still after the challenge.
            </p>
            <Link to="/live" className="mt-2 inline-flex min-h-11 items-center font-medium text-[#34479B] hover:underline">
              Live monitoring · annotated streams
            </Link>
          </section>
        </div>

        <div className="min-w-0 space-y-6">
          <AuthorizationProgress authenticatedCount={vault.authenticatedCount} requiredCount={vault.requiredCount} />
          <SecurityVerificationPanel vault={vault} slot={securitySlot} onRetry={vault.start} />
          <CustodianList
            custodians={vault.custodians}
            requiredCount={vault.requiredCount}
            activeSlot={slot}
            handoff={handoff}
            handoffName={handoff ? handoffSubject(vault) : null}
          />
          <VaultStatusCard result={vault.result} requiredCount={vault.requiredCount} />
        </div>
      </div>
    </div>
  );
}
