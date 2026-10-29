import { Shuffle } from 'lucide-react';
import { CHALLENGE_AXIS, CHALLENGE_LABELS, DEFAULT_CHALLENGES, signed } from './format.js';
import { Badge, LabCard, Row } from './ui.jsx';

const button = (active) => `inline-flex min-h-11 items-center justify-center gap-1.5 rounded-lg px-4 text-sm font-semibold transition-colors ${
  active ? 'bg-[#34479B] text-white' : 'border border-[#E3E7F0] bg-white text-[#0F1B3D] hover:bg-[#F4F6FB]'
}`;

function statusBadge(analysis, selected) {
  if (!selected) return <Badge>NO CHALLENGE</Badge>;
  if (!analysis?.baseline_ready) return <Badge tone="warning">WAITING FOR BASELINE</Badge>;
  return analysis.challenge?.passed ? <Badge tone="success">PASSING</Badge> : <Badge tone="danger">FAILING</Badge>;
}

function thresholdText(threshold) {
  if (typeof threshold !== 'number') return '—';
  return `${threshold < 0 ? '≤' : '≥'} ${signed(threshold)}`;
}

/** Challenge picker plus the backend's verdict. PASSING is shown only when the backend says `passed`. */
export default function ChallengeCard({ selected, analysis, thresholds, onSelect }) {
  const available = (thresholds?.available_challenges ?? DEFAULT_CHALLENGES).filter((code) => CHALLENGE_LABELS[code]);
  const result = analysis?.challenge;
  const axis = CHALLENGE_AXIS[selected]?.axis;
  const movementLabel = axis ? `Change in ${axis} vs baseline` : 'Movement vs baseline';

  const pickRandom = () => {
    const pool = available.filter((code) => code !== selected);
    if (pool.length) onSelect(pool[Math.floor(Math.random() * pool.length)]);
  };

  return (
    <LabCard title="Challenge test" labelledBy="lt-challenge" badge={statusBadge(analysis, selected)}>
      <div role="group" aria-label="Challenge" className="flex flex-wrap gap-2">
        {available.map((code) => (
          <button key={code} type="button" aria-pressed={selected === code} className={button(selected === code)}
            onClick={() => onSelect(code)}>
            {CHALLENGE_LABELS[code]}
          </button>
        ))}
        <button type="button" className={button(false)} onClick={pickRandom} disabled={available.length < 2}>
          <Shuffle className="h-4 w-4" aria-hidden /> Random
        </button>
      </div>
      {selected ? (
        <dl className="mt-3">
          <Row label={movementLabel}>{signed(result?.movement)}</Row>
          <Row label="Pass threshold">{thresholdText(result?.threshold)}</Row>
          <Row label="Held for">
            {result ? `${result.hits} of ${result.required_hits ?? thresholds?.required_hits ?? '—'} frames` : '—'}
          </Row>
        </dl>
      ) : (
        <p className="mt-3 text-sm text-[#55607A]">Pick a challenge to test it against the live head pose.</p>
      )}
      {selected && result?.reason && !result.passed && (
        <p className="mt-2 text-xs text-[#55607A]">Backend: {result.reason}</p>
      )}
    </LabCard>
  );
}
