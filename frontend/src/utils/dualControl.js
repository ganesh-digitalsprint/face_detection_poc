// Display helpers for the dual-custodian vault session. The backend decides every outcome;
// these functions only format and classify what it reports.

export const DUAL_STATE = Object.freeze({
  WAITING_FOR_FIRST_PERSON: 'WAITING_FOR_FIRST_PERSON',
  WAITING_FOR_SECOND_PERSON: 'WAITING_FOR_SECOND_PERSON',
  AUTHENTICATING_SECOND_PERSON: 'AUTHENTICATING_SECOND_PERSON',
  ACCESS_GRANTED: 'ACCESS_GRANTED',
  SESSION_EXPIRED: 'SESSION_EXPIRED',
  DENIED: 'DENIED',
  CANCELLED: 'CANCELLED',
});

export const WARNING_SECONDS = 60;
export const URGENT_SECONDS = 10;
export const BACKEND_TIMEOUT_STATUS = 'DUAL_AUTHENTICATION_TIMEOUT';
export const DUPLICATE_REASON = 'DUPLICATE_EMPLOYEE_REJECTED';

/** Whole seconds until `expiresAt` (ISO string), rounded up so 00:00 only shows at expiry. */
export function secondsRemaining(expiresAt, now = Date.now()) {
  const expiry = Date.parse(expiresAt);
  if (Number.isNaN(expiry)) return 0;
  return Math.max(0, Math.ceil((expiry - now) / 1000));
}

/** 180 -> "03:00". */
export function formatMmSs(totalSeconds) {
  const safe = Math.max(0, Math.floor(totalSeconds));
  const mm = String(Math.floor(safe / 60)).padStart(2, '0');
  const ss = String(safe % 60).padStart(2, '0');
  return `${mm}:${ss}`;
}

/** Visual-only urgency; never affects the authorization logic. */
export function timerTone(seconds) {
  if (seconds <= URGENT_SECONDS) return 'urgent';
  if (seconds <= WARNING_SECONDS) return 'warning';
  return 'normal';
}

/** Single UI state from the hook's backend-derived fields. */
export function deriveDualState({ ended, authenticatedCount, secondActive }) {
  if (ended) return DUAL_STATE[ended] ?? DUAL_STATE.DENIED;
  if (authenticatedCount >= 1) {
    return secondActive ? DUAL_STATE.AUTHENTICATING_SECOND_PERSON : DUAL_STATE.WAITING_FOR_SECOND_PERSON;
  }
  return DUAL_STATE.WAITING_FOR_FIRST_PERSON;
}
