import { Hourglass } from 'lucide-react';
import StageRow from './StageRow.jsx';

export const CHALLENGE_TEXT = {
  BLINK: 'Blink your eyes',
  TURN_LEFT: 'Turn your head to YOUR LEFT',
  TURN_RIGHT: 'Turn your head to YOUR RIGHT',
  LOOK_UP: 'Tilt your head UP',
  LOOK_DOWN: 'Tilt your head DOWN',
  SMILE: 'Smile',
};

const CHALLENGE_DIRECTION = {
  TURN_LEFT: 'In the preview, move toward the RIGHT edge.',
  TURN_RIGHT: 'In the preview, move toward the LEFT edge.',
  LOOK_UP: 'Move toward the TOP of the preview.',
  LOOK_DOWN: 'Move toward the BOTTOM of the preview.',
};

/** Prominent prompt for the challenge the backend currently wants performed. */
export function ChallengePrompt({ challenge, liveness, title = 'Liveness Verification' }) {
  if (!challenge) return null;
  const done = liveness?.completed_challenges ?? 0;
  const total = liveness?.required_challenges;
  return (
    <div role="status" aria-live="polite" className="rounded-md border border-brand/30 bg-blue-50 p-4 text-center">
      <p className="text-xs font-semibold uppercase tracking-wide text-brand">{title}</p>
      <p className="mt-1 text-xl font-semibold text-navy">{CHALLENGE_TEXT[challenge] ?? challenge}</p>
      {CHALLENGE_DIRECTION[challenge] ? (
        <p className="mt-1 text-sm font-medium text-slate-700">{CHALLENGE_DIRECTION[challenge]}</p>
      ) : null}
      <p className="mt-1 flex items-center justify-center gap-1.5 text-sm text-slate-600">
        <Hourglass className="h-4 w-4" aria-hidden /> {liveness?.reason ?? 'Waiting for action...'}
      </p>
      {total ? <p className="mt-1 text-xs text-slate-500">Challenge {Math.min(done + 1, total)} of {total}</p> : null}
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
