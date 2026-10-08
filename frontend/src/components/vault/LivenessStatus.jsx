import { AlertTriangle, Hourglass } from 'lucide-react';
import DirectionArrow from './DirectionArrow.jsx';
import StageRow from './StageRow.jsx';
import { challengeUI } from './challengeUI.js';

/** Simple user-facing feedback; raw pose values are never shown. */
function feedbackText(liveness) {
  const reason = liveness?.reason ?? '';
  if (reason === 'No face detected') return 'No face detected. Please position your face inside the camera frame.';
  if (/timed out/i.test(reason)) return 'Challenge timed out. Please try again.';
  switch (liveness?.feedback) {
    case 'WRONG_DIRECTION': return 'Wrong direction. Please follow the arrow.';
    case 'HOLDING': return 'Good! Hold...';
    case 'DETECTING': return 'Detecting...';
    default: return liveness ? 'Get ready...' : 'Waiting for action...';
  }
}

/** Prominent prompt for the challenge the backend currently wants performed. */
export function ChallengePrompt({ challenge, liveness }) {
  if (!challenge) return null;
  const { instruction } = challengeUI(challenge);
  const done = liveness?.completed_challenges ?? 0;
  const total = liveness?.required_challenges;
  const wrong = liveness?.feedback === 'WRONG_DIRECTION';
  return (
    <div role="status" aria-live="polite" className="rounded-md border border-brand/30 bg-blue-50 p-4 text-center">
      <p className="text-xs font-semibold uppercase tracking-wide text-brand">Liveness Verification</p>
      {total ? <p className="mt-1 text-xs text-slate-500">Step {Math.min(done + 1, total)} of {total}</p> : null}
      <p className="mt-1 text-xl font-semibold text-navy">{instruction}</p>
      <DirectionArrow challenge={challenge} />
      <p className={`flex items-center justify-center gap-1.5 text-sm ${wrong ? 'font-semibold text-amber-700' : 'text-slate-600'}`}>
        {wrong ? <AlertTriangle className="h-4 w-4" aria-hidden /> : <Hourglass className="h-4 w-4" aria-hidden />}
        {feedbackText(liveness)}
      </p>
    </div>
  );
}

/** Liveness checklist row derived purely from backend status. */
export default function LivenessStatus({ phase, liveness }) {
  const status = liveness?.status;
  if (status === 'PASSED') return <StageRow tone="pass" label="Liveness verified" />;
  if (status === 'EXPIRED') return <StageRow tone="fail" label="Liveness session expired" />;
  if (status === 'FAILED') {
    return <StageRow tone="fail" label="Liveness verification failed" detail={liveness.reason} />;
  }
  if (phase === 'liveness') return <StageRow tone="pending" label="Liveness verification in progress" />;
  return <StageRow tone="idle" label="Liveness verification" />;
}
