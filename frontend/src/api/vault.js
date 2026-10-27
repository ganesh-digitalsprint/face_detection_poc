import client from './client.js';

const enc = encodeURIComponent;

export const getVaultAuthenticationConfig = () =>
  client.get('/api/v1/vault-authentication/config').then((r) => r.data);

// -> { session_ref, challenge, status, required_persons, test_mode, expires_at, remaining_seconds }
export const startLivenessSession = (requiredPersons = null) =>
  client.post('/api/v1/vault-authentication/start',
    requiredPersons == null ? undefined : { required_persons: requiredPersons })
    .then((r) => r.data);

// Backend field name is `frame`.
// -> { liveness: {passed, challenge, status, reason, completed_challenges, required_challenges, score},
//      recognition: {matched, employee_id, distance}|null, authorization: {active}|null,
//      access_granted, reason, status, authenticated_count, required_count,
//      test_mode, remaining_seconds, next_challenge, handoff_remaining_seconds }
export const submitLivenessFrame = (sessionId, blob) => {
  const data = new FormData();
  data.append('frame', blob, 'frame.jpg');
  return client
    .post(`/api/v1/vault-authentication/sessions/${enc(sessionId)}/frames`, data)
    .then((r) => r.data);
};
