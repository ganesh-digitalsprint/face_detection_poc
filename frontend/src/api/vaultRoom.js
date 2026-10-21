import client, { API_BASE_URL } from './client.js';

const key = import.meta.env.VITE_VAULT_ROOM_API_KEY;
const headers = key ? { 'X-API-Key': key } : {};

export const getVaultRoomState = () => client.get('/api/v1/vault-room/state', { headers }).then((r) => r.data);
export const closeVault = () => client.post('/api/v1/vault-room/close', undefined, { headers }).then((r) => r.data);
export const getVaultSessions = (limit = 20) => client.get('/api/v1/vault-room/sessions', { params: { limit }, headers }).then((r) => r.data);
export const analyzeVaultFrame = (blob, signal) => {
  const body = new FormData();
  body.append('frame', blob, 'vault-room.jpg');
  return client.post('/api/v1/vault-room/frames', body, { headers, signal, timeout: 10000 }).then((r) => r.data);
};
export const getSessionAlerts = (sessionId) => client.get(`/api/v1/vault-room/sessions/${encodeURIComponent(sessionId)}/alerts`, { headers }).then((r) => r.data);

/** Fetch-based SSE is used because EventSource cannot send the configured API-key header. */
export async function openVaultEvents(onSnapshot, onEvent, onState, signal) {
  const response = await fetch(`${String(API_BASE_URL || '').replace(/\/$/, '')}/api/v1/vault-room/events`, { headers, signal });
  if (!response.ok) throw new Error(`Vault event stream returned HTTP ${response.status}`);
  if (!response.body) throw new Error('Streaming is unavailable in this browser.');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let eventName = 'message';
  let data = [];
  const dispatch = () => {
    if (!data.length) { eventName = 'message'; return; }
    let payload;
    try { payload = JSON.parse(data.join('\n')); } catch { data = []; eventName = 'message'; return; }
    if (eventName === 'snapshot') onSnapshot(payload);
    else if (eventName === 'vault_event') onEvent(payload);
    else if (eventName === 'state') onState(payload);
    data = [];
    eventName = 'message';
  };
  try {
    while (!signal?.aborted) {
      let timeout;
      let chunk;
      try {
        chunk = await Promise.race([
          reader.read(),
          new Promise((_, reject) => { timeout = window.setTimeout(() => reject(new Error('Vault event stream timed out.')), 5000); }),
        ]);
      } finally { window.clearTimeout(timeout); }
      const { value, done } = chunk;
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let newline;
      while ((newline = buffer.indexOf('\n')) >= 0) {
        let line = buffer.slice(0, newline).replace(/\r$/, '');
        buffer = buffer.slice(newline + 1);
        if (line === '') dispatch();
        else if (line.startsWith(':')) continue;
        else if (line.startsWith('event:')) eventName = line.slice(6).trim();
        else if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''));
      }
    }
  } finally {
    await reader.cancel().catch(() => {});
  }
}
