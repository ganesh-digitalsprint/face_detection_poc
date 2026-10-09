import { ShieldCheck, ShieldX } from 'lucide-react';

// Backend `reason` codes -> user-safe text. Unlisted codes fall back to a generic message.
const REASONS = {
  UNKNOWN_EMPLOYEE: 'Unknown employee',
  AUTHORIZATION_INACTIVE: 'Authorization is not active',
  IDENTITY_AUTHORIZATION_MISMATCH: 'Identity and authorization records do not match',
  DUAL_AUTHENTICATION_TIMEOUT: 'The two-person authorization window expired. Start a new verification.',
  DUPLICATE_EMPLOYEE_REJECTED: 'A different employee must complete the second verification.',
  FIRST_PERSON_VERIFIED: 'First custodian verified. A different employee must verify next.',
  NEXT_PERSON_READY: 'Second custodian verification started.',
};

export function denialReason(result, liveness) {
  if (result?.reason === 'DUAL_AUTHENTICATION_TIMEOUT') return REASONS.DUAL_AUTHENTICATION_TIMEOUT;
  if (result?.reason === 'LIVENESS_FAILED' || liveness?.status === 'FAILED') {
    return liveness?.reason || 'Liveness verification failed';
  }
  if (liveness?.status === 'EXPIRED') return 'Liveness session expired';
  return REASONS[result?.reason] ?? 'Verification could not be completed';
}

/** Final banner. `granted` is exactly the backend's `access_granted`; the UI never infers it. */
export default function AccessDecision({ result, liveness, ended }) {
  const granted = result?.access_granted === true;
  const Icon = granted ? ShieldCheck : ShieldX;
  const tone = granted
    ? 'border-emerald-600 bg-emerald-50 text-emerald-800'
    : 'border-red-600 bg-red-50 text-red-800';

  let title = granted ? 'ACCESS GRANTED' : 'ACCESS DENIED';
  let detail;
  if (granted) {
    detail = 'DUAL CONTROL VERIFIED';
  } else if (ended === 'SESSION_EXPIRED') {
    title = 'SESSION EXPIRED';
    detail = 'Two authorized custodians were not authenticated within the authorization window.';
  } else if (ended === 'CANCELLED') {
    title = 'SESSION CANCELLED';
    detail = 'The vault access session was cancelled.';
  } else {
    detail = `Reason: ${denialReason(result, liveness)}`;
  }

  return (
    <div role="alert" className={`rounded-md border-2 p-4 text-center ${tone}`}>
      <Icon className="mx-auto h-8 w-8" aria-hidden />
      <p className="mt-1 text-lg font-bold tracking-wide">{title}</p>
      <p className="text-sm">{detail}</p>
      {!granted && ended !== 'DENIED' && <p className="mt-1 text-sm font-bold tracking-wide">ACCESS DENIED</p>}
    </div>
  );
}
