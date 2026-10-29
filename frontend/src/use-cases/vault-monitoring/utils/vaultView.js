// Single UI view for the Vault Access page, derived only from backend-reported hook state.

export const VAULT_VIEW = Object.freeze({
  IDLE: 'idle',
  STARTING: 'starting',
  LIVENESS: 'liveness',
  IDENTITY: 'identity',
  HANDOFF: 'handoff',
  GRANTED: 'granted',
  DENIED: 'denied',
  TIMEOUT: 'timeout',
  CANCELLED: 'cancelled',
  ERROR: 'error',
});

export const WINDOW_WARNING_SECONDS = 30;

/** @param {object} vault state returned by useVaultAccess */
export function deriveVaultView(vault) {
  const { phase, ended, result, handoffPending } = vault;
  if (phase === 'idle') return VAULT_VIEW.IDLE;
  if (phase === 'starting') return VAULT_VIEW.STARTING;
  if (phase === 'error') return VAULT_VIEW.ERROR;
  if (phase === 'done') {
    if (ended === 'ACCESS_GRANTED' && result?.access_granted === true) return VAULT_VIEW.GRANTED;
    if (ended === 'SESSION_EXPIRED') return VAULT_VIEW.TIMEOUT;
    if (ended === 'CANCELLED') return VAULT_VIEW.CANCELLED;
    return VAULT_VIEW.DENIED;
  }
  if (handoffPending) return VAULT_VIEW.HANDOFF;
  if (result?.reason === 'LOOK_AT_CAMERA') return VAULT_VIEW.IDENTITY;
  return VAULT_VIEW.LIVENESS;
}

/** 1-based slot being verified now; null when no slot is in progress. */
export function activeSlot(vault, view) {
  const live = [VAULT_VIEW.STARTING, VAULT_VIEW.LIVENESS, VAULT_VIEW.IDENTITY, VAULT_VIEW.HANDOFF].includes(view);
  if (!live) return null;
  // During handoff the next slot is the one about to start.
  return Math.min(vault.custodians.length + 1, vault.requiredCount);
}

/** Name of whoever the latest handoff refers to (duplicate match or newest custodian). */
export function handoffSubject(vault) {
  const matchedId = vault.result?.recognition?.employee_id;
  const matched = matchedId && vault.custodians.find((c) => c.employee_id === matchedId);
  const latest = vault.custodians[vault.custodians.length - 1];
  return (matched ?? latest)?.name ?? null;
}

/** ISO timestamp -> local "HH:MM:SS". */
export function formatClockTime(iso) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
}
