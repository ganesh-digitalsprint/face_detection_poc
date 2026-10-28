// Client for the Branch Exterior Monitoring backend (runs as its own micro-service).
// Base URL comes from VITE_BRANCH_EXTERIOR_API_BASE_URL (default http://localhost:8001).
export const BX_BASE = (import.meta.env.VITE_BRANCH_EXTERIOR_API_BASE_URL || 'http://localhost:8001').replace(/\/+$/, '');

/** Absolute URL on the branch-exterior server for any path (e.g. "/storage/x.mp4"). */
export const bxUrl = (path) => `${BX_BASE}${path}`;
/** Absolute URL for an API path (e.g. "/streams/1/processed" -> BASE/api/streams/1/processed). */
export const bxApiUrl = (path) => `${BX_BASE}/api${path}`;
/** Saved snapshot / clip / guard photo path as returned by the API. */
export const bxStorageUrl = (rel) => `${BX_BASE}/storage/${rel}`;
export const bxWsUrl = () => `${BX_BASE.replace(/^http/, 'ws')}/api/ws/alerts`;

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
    res = await fetch(bxApiUrl(path), opts);
  } catch {
    throw new Error(`Cannot reach the Branch Exterior server at ${BX_BASE}. Is it running? (uv run uvicorn app.main:app --reload --port 8001)`);
  }
  if (!res.ok) {
    let detail = res.statusText;
    try { const j = await res.json(); detail = j.detail ? formatErrorDetail(j.detail) : JSON.stringify(j); } catch { /* not json */ }
    throw new Error(`${res.status} ${detail}`);
  }
  const ct = res.headers.get('content-type') || '';
  if (ct.includes('application/json')) return res.json();
  return res.text();
}

export const api = {
  get: (path) => apiRequest('GET', path),
  post: (path, body) => apiRequest('POST', path, body ?? {}),
  patch: (path, body) => apiRequest('PATCH', path, body ?? {}),
  del: (path) => apiRequest('DELETE', path),
  postForm: (path, formData) => apiRequest('POST', path, formData, true),
};

export function fmtTime(iso) {
  if (!iso) return '-';
  const d = new Date(iso);
  return d.toLocaleString(undefined, { month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' });
}
export function timeAgo(iso) {
  const s = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}
