import { useRef } from 'react';
import { polygonPoints, zoneColor } from '../grillGateModel.js';

/** Configured zone polygons and the calibration line, in normalized raw-frame coordinates. */
export function ZoneOverlay({ zones = [], line = null }) {
  return (
    <>
      <svg className="pointer-events-none absolute inset-0 h-full w-full" viewBox="0 0 1 1" preserveAspectRatio="none" aria-hidden>
        {zones.map((zone) => {
          const points = polygonPoints(zone.polygon);
          if (points.length < 3) return null;
          const color = zoneColor(zone.zone_type);
          return (
            <polygon key={zone.id} points={points.map(({ x, y }) => `${x},${y}`).join(' ')}
              fill={`${color}${zone.enabled === false ? '0d' : '1f'}`} stroke={color} strokeOpacity={zone.enabled === false ? 0.4 : 1}
              strokeWidth="2" vectorEffect="non-scaling-stroke" />
          );
        })}
        {line && (
          <line x1={line.start.x} y1={line.start.y} x2={line.end.x} y2={line.end.y} stroke="#f8fafc"
            strokeWidth="2" strokeDasharray="8 6" vectorEffect="non-scaling-stroke" />
        )}
      </svg>
      {zones.map((zone) => {
        const points = polygonPoints(zone.polygon);
        if (points.length < 3) return null;
        return (
          <span key={zone.id} className="pointer-events-none absolute -translate-y-full pb-0.5 text-[11px] font-semibold uppercase"
            style={{ left: `${Math.min(...points.map((p) => p.x)) * 100}%`, top: `${Math.min(...points.map((p) => p.y)) * 100}%`, color: zoneColor(zone.zone_type) }}>
            {zone.name}
          </span>
        );
      })}
      {line && (
        <span className="pointer-events-none absolute translate-x-2 text-[11px] font-bold text-white"
          style={{ left: `${line.end.x * 100}%`, top: `${line.end.y * 100}%` }}>Virtual line</span>
      )}
    </>
  );
}

/**
 * Dark camera viewport. `streamUrl` renders a real stream when a backend one exists (none does today);
 * otherwise it stays blank. `onPick` turns clicks into normalized points for calibration.
 */
export default function CameraStage({ aspect = 16 / 9, caption, streamUrl = null, onPick = null, label, children }) {
  const ref = useRef(null);
  const pick = (event) => {
    if (!onPick || !ref.current) return;
    const rect = ref.current.getBoundingClientRect();
    const clamp = (value) => Math.round(Math.max(0, Math.min(1, value)) * 10000) / 10000;
    onPick({ x: clamp((event.clientX - rect.left) / rect.width), y: clamp((event.clientY - rect.top) / rect.height) });
  };
  return (
    <div ref={ref} onClick={onPick ? pick : undefined} role="img" aria-label={label}
      className={`relative overflow-hidden rounded-lg border border-[#E3E7F0] bg-[#18202E] ${onPick ? 'cursor-crosshair' : ''}`}
      style={{ aspectRatio: String(aspect) }}>
      {streamUrl && <img src={streamUrl} alt="" className="absolute inset-0 h-full w-full object-fill" />}
      {caption && <div className="absolute left-3 top-2 font-mono text-[11px] text-slate-200">{caption}</div>}
      {children}
    </div>
  );
}
