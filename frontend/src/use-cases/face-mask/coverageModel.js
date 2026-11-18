export const COVERAGE_STATES = {
  PARTIALLY_COVERED: 'Partial',
  FULLY_COVERED: 'Full',
};

export const coverageLabel = (state) => COVERAGE_STATES[state] || 'Legacy / unknown';

export const coverageTitle = (state) => state === 'PARTIALLY_COVERED'
  ? 'Partially covered face detected' : 'Masked person detected';

export const coverageSeverity = (event, incidentSeverity) =>
  event?.coverage_state === 'PARTIALLY_COVERED' ? 'MEDIUM'
    : event?.coverage_state === 'FULLY_COVERED' ? 'HIGH'
      : incidentSeverity || event?.severity || null;

export const coverageOfAlert = (alert) => alert?.domainData?.coverage_state || alert?.coverage_state || null;

export function partialCount(stats) {
  for (const key of ['partially_covered', 'partial_count', 'partial_events']) {
    if (Number.isFinite(stats?.[key])) return stats[key];
  }
  return null;
}
