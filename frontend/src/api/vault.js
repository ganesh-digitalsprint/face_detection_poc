import client from './client.js';

const enc = encodeURIComponent;

// Starts one dual-control authorization session (shared by both custodians).
// -> { session_id, challenge, status, required_persons, authenticated_count,
//      started_at, expires_at, remaining_seconds, expires_in_seconds }
export const startLivenessSession = () =>
  client.post('/api/v1/vault-authentication/start').then((r) => r.data);

// Backend field name is `frame`.
// -> { liveness: {passed, challenge, status, reason, completed_challenges, required_challenges, score},
//      recognition: {matched, employee_id, distance}|null, authorization: {active}|null,
//      access_granted, reason, status, authenticated_count, required_count, remaining_seconds,
//      next_challenge }
export const submitLivenessFrame = (sessionId, blob) => {
  const data = new FormData();
  data.append('frame', blob, 'frame.jpg');
  return client
    .post(`/api/v1/vault-authentication/sessions/${enc(sessionId)}/frames`, data)
    .then((r) => r.data);
};
