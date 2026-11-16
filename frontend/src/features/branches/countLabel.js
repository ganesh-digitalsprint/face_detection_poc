const irregular = { city: 'cities', branch: 'branches' };

export function countLabel(count, singular) {
  const number = Number(count) || 0;
  const plural = irregular[singular] || `${singular}s`;
  return `${number} ${number === 1 ? singular : plural}`;
}
