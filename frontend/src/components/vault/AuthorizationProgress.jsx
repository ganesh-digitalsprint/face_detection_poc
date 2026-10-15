/** "N of M" plus one bar segment per required custodian. Filled segments are also counted in text. */
export default function AuthorizationProgress({ authenticatedCount, requiredCount }) {
  const segments = Array.from({ length: requiredCount }, (_, index) => index < authenticatedCount);
  return (
    <section aria-labelledby="vault-progress-title" className="vault-card p-5">
      <div className="flex items-baseline justify-between gap-3">
        <h2 id="vault-progress-title" className="vault-heading text-base">Authorization progress</h2>
        <p className="text-[#0F1B3D]" aria-live="polite">
          <span className="text-3xl font-bold tabular-nums">{authenticatedCount}</span>
          <span className="ml-1 text-base font-semibold text-[#55607A]">of {requiredCount}</span>
          <span className="sr-only"> custodians verified</span>
        </p>
      </div>
      <div className="mt-3 flex gap-2" aria-hidden>
        {segments.map((filled, index) => (
          <span key={index} className={`h-2 flex-1 rounded-full ${filled ? 'bg-[#0B7A4B]' : 'bg-[#D9DEEB]'}`} />
        ))}
      </div>
      <p className="mt-3 text-sm text-[#55607A]">Two different authorized employees must verify within 3 minutes.</p>
    </section>
  );
}
