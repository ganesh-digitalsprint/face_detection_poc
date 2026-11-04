// Client for the Face Mask backend (its own micro-service). Same fetch-based style as the Branch Exterior client.
// Base URL comes from VITE_FACE_MASK_API_BASE_URL via src/config/services.js (default http://localhost:8014).
import { FACE_MASK_BASE_URL } from '../../../config/services.js';

export const FM_BASE = FACE_MASK_BASE_URL;

/** Absolute URL for an API path (e.g. "/streams/1/processed" -> BASE/api/streams/1/processed). */
export const fmApiUrl = (path) => `${FM_BASE}/api${path}`;

export const SERVICE_DOWN_MESSAGE = 'Face Mask service is not running on port 8014. Start it with: uv run uvicorn app.main:app --reload --port 8014';

/** Thrown for every network failure, so pages can show the friendly "service is down" panel instead of a blank screen. */
export class ServiceDownError extends Error {
  constructor() {
    super(SERVICE_DOWN_MESSAGE);
    this.name = 'ServiceDownError';
  }
}

// FastAPI reports validation problems as a LIST of objects; turn any error detail into one readable sentence.
function formatErrorDetail(d) {
  if (typeof d === 'string') return d;
  if (Array.isArray(d)) {
    return d.map((e) => {
      if (e && typeof e === 'object' && e.msg) {
        const where = (e.loc || []).filter((x) => x !== 'body' && x !== 'query' && x !== 'path').join('.');
        return (where ? `${where}: ` : '') + e.msg;
      }
      return typeof e === 'string' ? e : JSON.stringify(e);
    }).join('; ');
  }
  if (d && typeof d === 'object') return d.message || JSON.stringify(d);
  return String(d);
}

async function apiRequest(method, path, body, isForm) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    if (isForm) {
      opts.body = body;
    } else {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
  }
  let res;
  try {
    res = await fetch(fmApiUrl(path), opts);
  } catch {
    throw new ServiceDownError();
  }
  if (!res.ok) {
    let detail = res.statusText;
    try { const j = await res.json(); detail = j.detail ? formatErrorDetail(j.detail) : JSON.stringify(j); } catch { /* not json */ }
    const error = new Error(detail);
    error.status = res.status;
    throw error;
  }
  if (res.status === 204) return null;
  const ct = res.headers.get('content-type') || '';
  return ct.includes('application/json') ? res.json() : res.text();
}

export const api = {
  get: (path) => apiRequest('GET', path),
  post: (path, body) => apiRequest('POST', path, body ?? {}),
  put: (path, body) => apiRequest('PUT', path, body ?? {}),
  patch: (path, body) => apiRequest('PATCH', path, body ?? {}),
  del: (path) => apiRequest('DELETE', path),
  postForm: (path, formData) => apiRequest('POST', path, formData, true),
};

/** Query string from an object, skipping empty values. */
export function qs(params) {
  const q = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => { if (v !== '' && v != null) q.set(k, String(v)); });
  const s = q.toString();
  return s ? `?${s}` : '';
}

export function fmtTime(iso) {
  if (!iso) return '-';
  return new Date(iso).toLocaleString(undefined, { month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

export function timeAgo(iso) {
  const s = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export const COVERING_LABELS = {
  lower_face_covering: 'Mask / scarf', full_face_covering: 'Full face covering', head_covering: 'Cap / helmet',
  surgical_mask: 'Surgical mask', scarf: 'Scarf', cap_concealing: 'Cap', helmet: 'Helmet', other_mask: 'Other mask',
};
export const coveringLabel = (c) => COVERING_LABELS[c] || (c ? c.replace(/_/g, ' ') : '-');
