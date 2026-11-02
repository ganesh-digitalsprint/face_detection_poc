import { Camera, RotateCcw, ShieldAlert, XCircle } from 'lucide-react';
import Button from '../../../../components/common/Button.jsx';
import ErrorMessage from '../../../../components/common/ErrorMessage.jsx';
import AuthorizationStatus from './AuthorizationStatus.jsx';
import IdentityStatus from './IdentityStatus.jsx';
import LivenessStatus from './LivenessStatus.jsx';
import StageRow from './StageRow.jsx';

const FACE_MISSING = 'No face detected';

function faceStage(vault) {
  const { liveness, phase } = vault;
  if (!liveness) return phase === 'liveness' ? 'pending' : 'idle';
  if (liveness.reason === FACE_MISSING) return 'pending';
  if (liveness.status === 'FAILED' && /more than one face/i.test(liveness.reason ?? '')) return 'fail';
  return 'pass';
}

/**
 * Security checklist for the current custodian, composed from backend-reported state.
 * Challenge prompts and the final decision are drawn over the camera instead.
 */
function VaultRoomAccessNotice({ info, onGoRoom }) {
  const state = info?.state;
  let liveLine = null;
  if (state === 'ACTIVE' && Number.isFinite(info.remaining_seconds)) {
    const seconds = Math.max(0, info.remaining_seconds);
    const mmss = `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
    liveLine = `Session ends in ${mmss}`;
  } else if (state === 'ENTRY_BUFFER') {
    liveLine = `Entry window: ${info.entry_buffer_remaining_seconds ?? 0}s`;
  } else if (state === 'EXPIRED_OPEN') {
    liveLine = 'Session expired · door still unlocked. Close the vault to allow a new access.';
  }

  return (
    <div role="status" aria-live="polite" aria-atomic="false"
      className="mt-4 rounded-xl border border-blue-200 bg-blue-50 p-4 text-blue-950">
      <p className="font-bold">Vault room session is active</p>
      <p className="mt-1 text-sm">A new vault access can be started after the current session ends.</p>
      {liveLine && <p className="mt-2 text-sm font-semibold tabular-nums">{liveLine}</p>}
      <Button variant="secondary" icon={Camera} onClick={onGoRoom} className="mt-3 min-h-11">
        Go to Vault Room Camera
      </Button>
    </div>
  );
}

export default function SecurityVerificationPanel({ vault, slot, onRetry, onGoRoom }) {
  const { phase, liveness, result, error, custodians, requiredCount, testMode } = vault;
  const idle = phase === 'idle';
  const face = faceStage(vault);
  const matchedName = custodians.find((c) => c.employee_id === result?.recognition?.employee_id)?.name;

  return (
    <section aria-labelledby="vault-security-title" className="vault-card p-5">
      <h2 id="vault-security-title" className="vault-heading text-base">
        Security verification{slot ? ` · Custodian ${slot}` : ''}
      </h2>
      {vault.roomBlocked && <VaultRoomAccessNotice info={vault.roomBlockInfo} onGoRoom={onGoRoom} />}
      {testMode && <p className="mt-2 inline-flex rounded-full bg-amber-100 px-3 py-1 text-xs font-bold tracking-wide text-amber-900">TEST MODE · 1 person</p>}

      {idle && (
        <p className="mt-2 text-sm text-[#55607A]">
          Start a camera, then begin vault access. {requiredCount == null
            ? 'Loading authorization requirements.'
            : requiredCount === 1
              ? 'One authorized custodian must pass face, liveness, identity and authorization checks within 3 minutes.'
              : `${requiredCount} authorized custodians must each pass face, liveness, identity and authorization checks within 3 minutes before access is granted.`}
        </p>
      )}

      {phase !== 'error' && (
        <ul className="mt-3 space-y-3" aria-label="Verification stages">
          <StageRow
            tone={face}
            label={face === 'pass' ? 'Face detected' : face === 'fail' ? 'Face check failed' : 'Detecting face'}
            detail={face === 'pending' && liveness?.reason === FACE_MISSING ? 'Position your face in view' : undefined}
          />
          <LivenessStatus phase={phase} liveness={liveness} />
          <IdentityStatus liveness={liveness} recognition={result?.recognition} name={matchedName} />
          <AuthorizationStatus recognition={result?.recognition} authorization={result?.authorization} />
        </ul>
      )}

      {phase === 'liveness' && (
        <Button variant="secondary" icon={XCircle} onClick={vault.cancel} className="mt-4 min-h-11">
          Cancel session
        </Button>
      )}

      {phase === 'error' && (
        <div className="mt-3 space-y-3">
          <p className="flex items-center gap-2 text-sm font-semibold text-[#B3261E]">
            <ShieldAlert className="h-5 w-5" aria-hidden />
            {error?.camera ? 'Camera unavailable' : 'Verification could not be completed'}
          </p>
          <ErrorMessage error={error} />
          <Button variant="secondary" icon={RotateCcw} onClick={onRetry} disabled={vault.roomBlocked}
            title={vault.roomBlocked ? 'Vault room session is active' : undefined}
            aria-describedby={vault.roomBlocked ? 'vault-room-retry-disabled' : undefined}
            className="min-h-11">Retry</Button>
          {vault.roomBlocked && <p id="vault-room-retry-disabled" className="text-sm text-[#55607A]">Vault room session is active</p>}
        </div>
      )}
    </section>
  );
}
