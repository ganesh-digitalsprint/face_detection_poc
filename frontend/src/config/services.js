// Single place that reads backend service URLs from the environment (Vite VITE_* variables).
// Components and API modules import these constants; nothing else hardcodes a host or port.
const env = import.meta.env ?? {};
const trimSlash = (value) => String(value ?? '').trim().replace(/\/+$/, '');

/** Vault Monitoring backend. VITE_API_BASE_URL is still honoured for existing local .env files. */
export const VAULT_BASE_URL = trimSlash(env.VITE_VAULT_API_BASE_URL || env.VITE_API_BASE_URL) || 'http://localhost:8010';

/** Branch Exterior Monitoring backend. */
export const BRANCH_BASE_URL = trimSlash(env.VITE_BRANCH_EXTERIOR_API_BASE_URL) || 'http://localhost:8011';

/**
 * Alert Service, reached through the Vite dev/preview proxy at this same-origin path. The proxy adds
 * the operator bearer token on the server side, so no Alert Service credential is in the browser bundle.
 * Point this at a full URL only if a reverse proxy in front of the Alert Service injects the credential.
 */
export const ALERT_SERVICE_BASE_URL = trimSlash(env.VITE_ALERT_SERVICE_BASE_URL) || '/alert-service';

/**
 * Show acknowledge/resolve/dismiss on Alert Service alerts. Off by default: during the shadow-ingestion
 * period Vault and Branch remain the lifecycle authority for their own alerts, and a second writer would
 * make the two stores diverge (see docs/alert-service-contract.md section 6).
 */
export const ALERT_SERVICE_ACTIONS_ENABLED = String(env.VITE_ALERT_SERVICE_ACTIONS_ENABLED ?? '') === 'true';

/** Alert Service list refresh interval in milliseconds. */
export const ALERT_POLL_MS = Math.max(3000, Number(env.VITE_ALERT_POLL_MS) || 10000);
