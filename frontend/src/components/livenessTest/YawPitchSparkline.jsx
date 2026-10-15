import { POSE_GAUGE_RANGE } from './format.js';
import { LabCard } from './ui.jsx';

const W = 300;
const H = 60;

function line(values) {
  if (values.length < 2) return '';
  const step = W / (values.length - 1);
  return values.map((v, i) => {
    const y = H / 2 - (Math.max(-1, Math.min(1, v / POSE_GAUGE_RANGE)) * H) / 2;
    return `${(i * step).toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
}

/** Last 60 raw yaw/pitch samples (memory only). */
export default function YawPitchSparkline({ history }) {
  return (
    <LabCard title="Yaw / pitch history" labelledBy="lt-history" aside={`last ${history.length}`}>
      <svg viewBox={`0 0 ${W} ${H}`} className="h-16 w-full" role="img"
        aria-label={`Yaw and pitch over the last ${history.length} frames`} preserveAspectRatio="none">
        <line x1="0" x2={W} y1={H / 2} y2={H / 2} stroke="#D9DEEB" strokeDasharray="4 3" />
        <polyline points={line(history.map((h) => h.yaw))} fill="none" stroke="#34479B" strokeWidth="2" vectorEffect="non-scaling-stroke" />
        <polyline points={line(history.map((h) => h.pitch))} fill="none" stroke="#C98A00" strokeWidth="2" vectorEffect="non-scaling-stroke" />
      </svg>
      <p className="mt-1 flex gap-4 text-xs text-[#55607A]">
        <span><span className="mr-1 inline-block h-0.5 w-4 bg-[#34479B] align-middle" aria-hidden />Yaw</span>
        <span><span className="mr-1 inline-block h-0.5 w-4 bg-[#C98A00] align-middle" aria-hidden />Pitch</span>
      </p>
    </LabCard>
  );
}
