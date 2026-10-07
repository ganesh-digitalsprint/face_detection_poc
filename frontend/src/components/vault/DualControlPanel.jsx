import { CheckCircle2, Circle, Loader2, XCircle } from 'lucide-react';
import {
  DUAL_STATE,
  DUPLICATE_REASON,
  WARNING_SECONDS,
  formatMmSs,
  timerTone,
} from '../../utils/dualControl.js';

const TIMER_CLS = {
  normal: 'text-navy',
  warning: 'text-amber-600',
  urgent: 'text-red-600 animate-pulse',
};

const WAITING_TEXT = {
  [DUAL_STATE.WAITING_FOR_FIRST_PERSON]: 'Waiting for first authorized custodian...',
  [DUAL_STATE.WAITING_FOR_SECOND_PERSON]: 'Waiting for second authorized custodian...',
  [DUAL_STATE.AUTHENTICATING_SECOND_PERSON]: 'Authenticating second custodian...',
};

function slotView(index, vault) {
  const { dualState, custodians, authenticatedCount } = vault;
  const id = custodians[index];
  if (index < authenticatedCount) {
    return { Icon: CheckCircle2, cls: 'text-emerald-700', label: 'Verified', id };
  }
  if (dualState === DUAL_STATE.SESSION_EXPIRED) {
    return { Icon: XCircle, cls: 'text-red-700', label: 'Not Verified' };
  }
  if (index === authenticatedCount && dualState === DUAL_STATE.AUTHENTICATING_SECOND_PERSON) {
    return { Icon: Loader2, cls: 'text-brand', spin: true, label: 'Authenticating' };
  }
  return { Icon: Circle, cls: 'text-slate-400', label: 'Pending' };
}

/** Dual-custodian status: countdown, per-custodian slots and guidance. Display only. */
export default function DualControlPanel({ vault }) {
  const { dualState, remainingSeconds, requiredPersons, authenticatedCount, result } = vault;
  if (!dualState) return null;

  const over = dualState === DUAL_STATE.ACCESS_GRANTED || dualState === DUAL_STATE.CANCELLED;
  const showTimer = !over;
  const tone = timerTone(remainingSeconds);
  const duplicate = result?.reason === DUPLICATE_REASON && authenticatedCount < requiredPersons;
  const slots = Array.from({ length: requiredPersons }, (_, i) => slotView(i, vault));

  return (
    <section aria-label="Dual control" className="space-y-3 rounded-md border border-slate-200 bg-slate-50 p-4 text-center">
      <p className="text-xs font-semibold uppercase tracking-wide text-brand">Dual Control Required</p>
      {showTimer && (
        <div>
          <p className="text-xs text-slate-600">Time Remaining</p>
          <p
            role="timer"
            aria-label={`Time remaining ${formatMmSs(remainingSeconds)}`}
            className={`font-mono text-5xl font-bold tabular-nums ${TIMER_CLS[tone]}`}
          >
            {formatMmSs(remainingSeconds)}
          </p>
          {remainingSeconds > 0 && remainingSeconds <= WARNING_SECONDS && (
            <p role="status" className="text-sm font-medium text-amber-700">Less than 1 minute remaining</p>
          )}
        </div>
      )}
      <ul className="inline-block space-y-1 text-left text-sm" aria-label="Custodians">
        {slots.map(({ Icon, cls, spin, label, id }, i) => (
          <li key={i} className={`flex items-center gap-2 font-medium ${cls}`}>
            <Icon className={`h-5 w-5 shrink-0 ${spin ? 'animate-spin' : ''}`} aria-hidden />
            Person {i + 1} — {label}{id ? ` (${id})` : ''}
          </li>
        ))}
      </ul>
      {duplicate && (
        <p role="alert" className="text-sm font-medium text-red-700">A different authorized custodian is required.</p>
      )}
      {!duplicate && WAITING_TEXT[dualState] && (
        <p className="text-sm text-slate-600">{WAITING_TEXT[dualState]}</p>
      )}
    </section>
  );
}
