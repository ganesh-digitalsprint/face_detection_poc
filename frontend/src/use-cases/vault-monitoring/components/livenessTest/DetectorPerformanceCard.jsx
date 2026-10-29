import { DETECTOR_LABELS, SLOW_DETECTOR_MS, fixed, grouped } from './format.js';
import { Badge, LabCard, Row } from './ui.jsx';

export default function DetectorPerformanceCard({ detector, results, stats }) {
  return (
    <LabCard title="Detector performance" labelledBy="lt-perf"
      badge={<Badge tone="success">{(DETECTOR_LABELS[detector] ?? detector).toUpperCase()}</Badge>}>
      <dl>
        {results.length === 0 && <Row label="Detection time">—</Row>}
        {results.map((r) => {
          const slow = typeof r.elapsed_ms === 'number' && r.elapsed_ms > SLOW_DETECTOR_MS;
          return (
            <Row key={r.detector} label={`${DETECTOR_LABELS[r.detector] ?? r.detector} time`} highlight={slow}>
              {r.error ? <span className="text-[#B3261E]">error</span> : `${grouped(r.elapsed_ms)} ms`}
              {slow && <span className="ml-1 font-sans text-xs">(slow)</span>}
            </Row>
          );
        })}
        <Row label="Round-trip rate">{fixed(stats.fps, 1)} fps</Row>
        <Row label="Frames processed / dropped">{grouped(stats.frames)} / {grouped(stats.dropped)}</Row>
      </dl>
    </LabCard>
  );
}
