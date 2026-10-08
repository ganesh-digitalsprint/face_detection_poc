import { RotateCcw, ShieldAlert } from 'lucide-react';
import Button from '../common/Button.jsx';
import ErrorMessage from '../common/ErrorMessage.jsx';
import AccessDecision from './AccessDecision.jsx';
import AuthorizationStatus from './AuthorizationStatus.jsx';
import IdentityStatus from './IdentityStatus.jsx';
import LivenessStatus, { ChallengePrompt } from './LivenessStatus.jsx';
import StageRow from './StageRow.jsx';

const FACE_MISSING = 'No face detected';

function faceStage(vault) {
  const { liveness, phase } = vault;
  if (!liveness) return phase === 'liveness' ? 'pending' : 'idle';
  if (liveness.reason === FACE_MISSING) return 'pending';
  if (liveness.status === 'FAILED' && /more than one face/i.test(liveness.reason ?? '')) return 'fail';
  return 'pass';
}

/** Security checklist for one verification attempt, composed from backend-reported state. */
export default function SecurityVerificationPanel({ vault, onRetry }) {
  const { phase, challenge, liveness, result, error, status, authenticatedCount, requiredCount, remainingSeconds, handoffRemaining, handoffPending } = vault;
  const face = faceStage(vault);
  const decided = phase === 'done';
  const waitingForSecond = status === 'WAITING_FOR_SECOND_PERSON';
  const handoff = handoffPending;
  const duplicateRejected = result?.reason === 'DUPLICATE_EMPLOYEE_REJECTED';
  const clock = remainingSeconds == null
    ? null
    : `${String(Math.floor(remainingSeconds / 60)).padStart(2, '0')}:${String(remainingSeconds % 60).padStart(2, '0')}`;
  const identityPrompt = result?.reason === 'LOOK_AT_CAMERA'
    ? 'Liveness verified. Look straight at the camera and hold still.'
    : phase === 'liveness' && result?.reason === 'UNKNOWN_EMPLOYEE'
      ? 'Face not recognized yet. Look straight at the camera and hold still while we retry.'
      : null;

  return (
    <div className="space-y-4">
      {phase === 'liveness' && !handoff && (!liveness?.passed || waitingForSecond) && (
        <ChallengePrompt
          challenge={challenge}
          liveness={waitingForSecond ? null : liveness}
          title={waitingForSecond ? 'Second Custodian Verification' : 'Liveness Verification'}
        />
      )}
      {phase === 'liveness' && handoff && (
        <div role="status" aria-live="assertive" className="rounded-md border border-emerald-400 bg-emerald-50 p-4 text-center">
          <p className="text-sm font-semibold text-emerald-900">
            ✓ First custodian verified ({authenticatedCount} of {requiredCount})
          </p>
          <p className="mt-1 text-base font-semibold text-navy">
            {duplicateRejected && <span className="block text-red-700">A different employee is required.</span>}
            First custodian: please step away.<br />
            Second custodian: step in front of the camera.
          </p>
          <p className="mt-2 text-3xl font-bold tabular-nums text-emerald-950">{handoffRemaining}</p>
          <p className="text-xs text-slate-600">
            {handoffRemaining > 0 ? 'Next verification starts automatically' : 'Starting the second challenge…'}
          </p>
        </div>
      )}
      {phase === 'liveness' && remainingSeconds != null && (
        <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-center" aria-live="polite">
          <p className="text-xs font-semibold uppercase tracking-wide text-amber-900">Vault authorization window</p>
          <p className="text-2xl font-bold tabular-nums text-amber-950">{clock}</p>
          <p className="text-sm text-amber-900">
            {waitingForSecond
              ? `First custodian authenticated · ${authenticatedCount} of ${requiredCount}. A different employee must verify.`
              : `${authenticatedCount} of ${requiredCount} custodians authenticated.`}
          </p>
        </div>
      )}
      {phase === 'liveness' && identityPrompt && (
        <div role="status" aria-live="polite" className="rounded-md border border-brand/30 bg-blue-50 p-4 text-center text-sm font-medium text-navy">
          {identityPrompt}
        </div>
      )}

      <ul className="space-y-3" aria-label="Verification stages">
        <StageRow
          tone={face}
          label={face === 'pass' ? 'Face detected' : face === 'fail' ? 'Face check failed' : 'Detecting face'}
          detail={face === 'pending' && liveness?.reason === FACE_MISSING ? 'Position your face in view' : undefined}
        />
        <LivenessStatus phase={phase} liveness={liveness} />
        <IdentityStatus liveness={liveness} recognition={result?.recognition} />
        <AuthorizationStatus recognition={result?.recognition} authorization={result?.authorization} />
      </ul>

      {phase === 'error' && (
        <div className="space-y-3">
          <p className="flex items-center gap-2 text-sm font-semibold text-red-700">
            <ShieldAlert className="h-5 w-5" aria-hidden />
            {error?.camera ? 'Camera unavailable' : 'Verification could not be completed'}
          </p>
          <ErrorMessage error={error} />
          <Button variant="secondary" icon={RotateCcw} onClick={onRetry}>Retry</Button>
        </div>
      )}

      {decided && (
        <div className="space-y-3">
          <AccessDecision result={result} liveness={liveness} />
          <Button variant="secondary" icon={RotateCcw} onClick={onRetry}>
            {liveness?.status === 'EXPIRED' ? 'Try Again' : 'Verify Again'}
          </Button>
        </div>
      )}
    </div>
  );
}
