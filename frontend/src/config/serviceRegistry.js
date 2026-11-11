// One place that describes every backend the UI talks to: where it lives, how to probe it and how to start it.
// Used by the top-bar status chip and by error messages so they can name the service that actually failed.
import {
  ALERT_SERVICE_BASE_URL, BRANCH_BASE_URL, FACE_MASK_BASE_URL, VAULT_BASE_URL,
} from './services.js';

export const SERVICES = [
  {
    id: 'vault',
    label: 'Vault Access',
    baseUrl: VAULT_BASE_URL,
    healthPath: '/api/v1/health',
    envVar: 'VITE_VAULT_API_BASE_URL',
    startCommand: 'cd backend/use_cases/vault_monitoring; python -m uvicorn app.main:app --port 8010',
  },
  {
    id: 'branch',
    label: 'Branch Exterior',
    baseUrl: BRANCH_BASE_URL,
    healthPath: '/api/health',
    envVar: 'VITE_BRANCH_EXTERIOR_API_BASE_URL',
    startCommand: 'cd backend/use_cases/branch_exterior; python -m uvicorn app.main:app --port 8011',
  },
  {
    id: 'face-mask',
    label: 'Face Mask',
    baseUrl: FACE_MASK_BASE_URL,
    healthPath: '/api/health',
    envVar: 'VITE_FACE_MASK_API_BASE_URL',
    startCommand: 'cd backend/use_cases/face_mask; uv run uvicorn app.main:app --reload --port 8014',
  },
  {
    id: 'alert-service',
    label: 'Alert Service',
    baseUrl: ALERT_SERVICE_BASE_URL,
    healthPath: '/health',
    envVar: 'ALERT_SERVICE_URL',
    startCommand: 'cd backend/services/alert_service; python -m uvicorn app.main:app --host 127.0.0.1 --port 8012',
  },
];

export const serviceById = (id) => SERVICES.find((s) => s.id === id) ?? null;

const norm = (u) => String(u ?? '').replace(/[/]+$/, '');

/** Service that owns an absolute or relative request URL (longest base-URL prefix wins), or null. */
export function serviceForUrl(url) {
  const target = norm(url);
  if (!target) return null;
  return SERVICES
    .filter((s) => norm(s.baseUrl) && target.startsWith(norm(s.baseUrl)))
    .sort((a, b) => norm(b.baseUrl).length - norm(a.baseUrl).length)[0] ?? null;
}

/** Friendly "service unavailable" text that names the service and the command that starts it. */
export function unavailableMessage(service) {
  if (!service) return 'Cannot reach the service. Check that the backend is running.';
  return `${service.label} service unavailable. Start it with: ${service.startCommand}`;
}
