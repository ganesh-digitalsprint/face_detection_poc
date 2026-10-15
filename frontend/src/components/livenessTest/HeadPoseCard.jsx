import { POSE_GAUGE_RANGE, directionBadge, fixed, signed } from './format.js';
import { Badge, DetectorError, LabCard, Row } from './ui.jsx';

/** Read-only gauge: centre tick = baseline, ±POSE_GAUGE_RANGE reaches the ends. */
function Gauge({ label, value, degrees, estimate, levelWord }) {
  const ratio = typeof value === 'number' ? Math.max(-1, Math.min(1, value / POSE_GAUGE_RANGE)) : 0;
  const left = `${50 + ratio * 50}%`;
  return (
    <div className="py-2">
      <div className="flex items-center justify-between gap-2 text-sm">
        <span className="text-[#0F1B3D]">{label}</span>
        <span className="font-mono tabular-nums text-[#0F1B3D]">
          {signed(value)}
          {typeof degrees === 'number' && (
            <span title={estimate ? 'Estimate, not a calibrated angle' : undefined}>
              {' · '}{estimate ? '~' : ''}{fixed(Math.abs(degrees))}°
            </span>
          )}
          {typeof value === 'number' && Math.abs(value) < 0.02 && levelWord && ` · ${levelWord}`}
        </span>
      </div>
      <div className="relative mt-2 h-2 rounded-full bg-[#E3E7F0]" aria-hidden>
        <span className="absolute left-1/2 top-1/2 h-4 w-0.5 -translate-x-1/2 -translate-y-1/2 bg-[#55607A]" />
        <span className="absolute top-1/2 h-5 w-5 -translate-x-1/2 -translate-y-1/2 rounded-full border-[3px] border-white bg-[#34479B] shadow ring-1 ring-[#34479B] transition-[left] duration-150 motion-reduce:transition-none"
          style={{ left }} />
      </div>
    </div>
  );
}

export default function HeadPoseCard({ result, analysis, thresholds }) {
  const pose = result?.pose;
  const useDelta = analysis?.baseline_ready;
  const yaw = useDelta ? pose?.yaw_delta : pose?.yaw;
  const pitch = useDelta ? pose?.pitch_delta : pose?.pitch;
  const estimate = analysis?.angles_are_estimates !== false;
  const bbox = result?.bbox;
  const centre = bbox && analysis?.image_width
    ? `${((bbox.x + bbox.width / 2) / analysis.image_width).toFixed(2)}, ${((bbox.y + bbox.height / 2) / analysis.image_height).toFixed(2)}`
    : '—';

  const badge = pose?.direction !== undefined && result?.visible
    ? <Badge tone={directionBadge(pose.direction) === 'CENTRED' ? 'success' : 'warning'}>{directionBadge(pose.direction)}</Badge>
    : <Badge>NO POSE</Badge>;

  return (
    <LabCard title="Head pose" labelledBy="lt-pose" badge={badge}>
      {result?.error && <DetectorError detector={result.detector} error={result.error} />}
      <Gauge label="Yaw (left ◂ ▸ right)" value={yaw} degrees={pose?.yaw_degrees} estimate={estimate} levelWord="centred" />
      <Gauge label="Pitch (up ◂ ▸ down)" value={pitch} degrees={pose?.pitch_degrees} estimate={estimate} levelWord="level" />
      <p className="text-xs text-[#55607A]">{useDelta ? 'Relative to the calibrated baseline.' : 'Raw values; baseline not ready yet.'}</p>
      <dl className="mt-2">
        <div className="flex items-center justify-between gap-3 border-b border-[#EEF1F7] py-2 text-sm">
          <dt className="text-[#55607A]">
            Frontal check (limits {fixed(thresholds?.frontal_yaw_max, 2)} / {fixed(thresholds?.frontal_pitch_max, 2)})
          </dt>
          <dd>
            {typeof pose?.is_frontal === 'boolean'
              ? <Badge tone={pose.is_frontal ? 'success' : 'warning'}>{pose.is_frontal ? 'FRONTAL' : 'NOT FRONTAL'}</Badge>
              : <span className="font-mono">—</span>}
          </dd>
        </div>
        <Row label="Face centre (normalized)">{centre}</Row>
      </dl>
    </LabCard>
  );
}
