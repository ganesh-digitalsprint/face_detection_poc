import client, { apiUrl } from './client.js';

// Backend: StreamStartedResponse { session_id, stream_url, stop_url } (relative URLs).
export const startWebcam = () => client.post('/api/v1/streams/webcam').then((r) => r.data);

export const startCCTV = (streamIndex) =>
  client.post('/api/v1/streams/cctv', { stream_index: streamIndex }).then((r) => r.data);

export const stopStream = (sessionId) =>
  client.post(`/api/v1/streams/${encodeURIComponent(sessionId)}/stop`).then((r) => r.data);

/** MJPEG URL for <img src>. Accepts a relative or absolute stream_url from the backend. */
export const resolveStreamUrl = (session) => {
  const url = session.stream_url || `/api/v1/streams/${session.session_id}/stream`;
  return /^https?:\/\//.test(url) ? url : apiUrl(url);
};

// -> [{ stream_index, label }] for configured CCTV sources (no RTSP URL or credentials).
export const listCCTVCameras = () =>
  client.get('/api/v1/streams/cctv/cameras').then((r) => r.data);
