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
  const { phase, challenge, liveness, result, error } = vault;
  const face = faceStage(vault);
  const decided = phase === 'done';
  const identityPrompt = result?.reason === 'LOOK_AT_CAMERA'
    ? 'Liveness verified. Look straight at the camera and hold still.'
    : phase === 'liveness' && result?.reason === 'UNKNOWN_EMPLOYEE'
      ? 'Face not recognized yet. Look straight at the camera and hold still while we retry.'
      : null;

  return (
    <div className="space-y-4">
      {phase === 'liveness' && !liveness?.passed && <ChallengePrompt challenge={challenge} liveness={liveness} />}
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
