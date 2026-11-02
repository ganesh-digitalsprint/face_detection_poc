import axios from 'axios';
import { ALERT_SERVICE_BASE_URL } from '../config/services.js';
import { LIFECYCLE, normalizeServiceAlert } from './alertServiceModel.js';

// Same-origin path handled by the Vite proxy, which adds the operator bearer token server-side.
const client = axios.create({ baseURL: ALERT_SERVICE_BASE_URL, timeout: 15000 });
const root = '/api/v1';
const enc = encodeURIComponent;

/** -> { items: [normalized alert], nextCursor, hasMore } */
export const listServiceAlerts = (params, signal) =>
  client.get(`${root}/alerts`, { params, signal }).then((r) => ({
    items: (r.data.items || []).map(normalizeServiceAlert),
    nextCursor: r.data.next_cursor || null,
    hasMore: Boolean(r.data.has_more),
  }));

/** -> { total, by_status: {OPEN,...}, by_severity: {CRITICAL,...} } */
export const getServiceSummary = (params, signal) =>
  client.get(`${root}/alerts/summary`, { params, signal }).then((r) => r.data);

export const getServiceMeta = (signal) => client.get(`${root}/alerts/meta`, { signal }).then((r) => r.data);

export const getServiceAlert = (id, signal) =>
  client.get(`${root}/alerts/${enc(id)}`, { signal }).then((r) => normalizeServiceAlert(r.data));

/** -> [{ id, action, actor_type, actor_id, from_status, to_status, details, created_at }] oldest first */
export const getServiceAudit = (id, signal) =>
  client.get(`${root}/alerts/${enc(id)}/audit`, { signal }).then((r) => r.data);

/** Move an alert to ACKNOWLEDGED, RESOLVED or DISMISSED. Returns the updated normalized alert. */
export const transitionServiceAlert = (id, target, body) => {
  const rule = LIFECYCLE[target];
  if (!rule) return Promise.reject(new Error(`Unsupported lifecycle action: ${target}`));
  return client.post(`${root}/alerts/${enc(id)}/${rule.path}`, body).then((r) => normalizeServiceAlert(r.data));
};
