import client from '../../../api/client.js';

// Developer test tool. Nothing here creates, reads or advances a vault session.
const BASE = '/api/v1/liveness-test';
const session = (sessionId) => `${BASE}/sessions/${encodeURIComponent(sessionId)}`;

// -> { thresholds, detectors?, ... }; 404 means the feature is disabled on the backend.
export const getTestConfig = () => client.get(`${BASE}/config`).then((r) => r.data);

// -> { session_id, ... }
export const startTestSession = () => client.post(`${BASE}/sessions`).then((r) => r.data);

// -> analysis (see useLivenessTest for the fields the UI reads)
export const analyzeTestFrame = (sessionId, blob, { detector, challenge } = {}) => {
  const data = new FormData();
  data.append('frame', blob, 'frame.jpg');
  data.append('detector', detector);
  if (challenge) data.append('challenge', challenge);
  return client.post(`${session(sessionId)}/analyze`, data).then((r) => r.data);
};

export const resetTestBaseline = (sessionId) =>
  client.post(`${session(sessionId)}/reset`).then((r) => r.data);

export const setTestChallenge = (sessionId, challenge) =>
  client.post(`${session(sessionId)}/challenge`, { challenge }).then((r) => r.data);

export const endTestSession = (sessionId) => client.delete(session(sessionId)).then((r) => r.data);
