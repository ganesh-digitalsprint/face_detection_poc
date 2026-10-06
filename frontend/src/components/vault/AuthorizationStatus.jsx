import StageRow from './StageRow.jsx';

/**
 * Renders only what the backend returned. The backend exposes just `active: boolean`
 * (no suspended/revoked/expired detail), so INACTIVE covers every non-active state.
 */
export default function AuthorizationStatus({ recognition, authorization }) {
  if (authorization) {
    return authorization.active
      ? <StageRow tone="pass" label="Authorization: ACTIVE" />
      : <StageRow tone="fail" label="Authorization: INACTIVE" />;
  }
  if (recognition && !recognition.matched) return <StageRow tone="idle" label="Authorization check skipped" />;
  return <StageRow tone="idle" label="Authorization check" />;
}
