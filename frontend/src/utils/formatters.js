export const formatConfidence = (value) =>
  value === null || value === undefined ? 'N/A' : `${(value * 100).toFixed(1)}%`;

// similarity / distance are NOT probabilities: show raw scores only.
export const formatScore = (value, digits = 3) =>
  value === null || value === undefined ? 'N/A' : Number(value).toFixed(digits);

export const formatBytes = (bytes) => {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
};
