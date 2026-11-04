import { useRef } from 'react';
import { Plug, PlugZap, RefreshCw, VideoOff } from 'lucide-react';
import { formatSeconds, polygonPoints, workerIsActive, zoneColor } from '../grillGateModel.js';
import { btnDanger, btnGhost, btnPrimary, Card, ErrorNote, Pill } from './ui.jsx';

const timeOf = (iso) => (iso ? new Date(iso).toLocaleTimeString() : '—');

function ZoneOverlay({ zones, line }) {
  return (
    <>
      <svg className="pointer-events-none absolute inset-0 h-full w-full" viewBox="0 0 1 1" preserveAspectRatio="none" aria-hidden>
        {zones.map((zone) => {
          const points = polygonPoints(zone.polygon);
          if (points.length < 3) return null;
          const color = zoneColor(zone.zone_type);
          return (
            <polygon
              key={zone.id}
              points={points.map(({ x, y }) => `${x},${y}`).join(' ')}
              fill={`${color}${zone.enabled === false ? '0d' : '1f'}`}
              stroke={color}
              strokeOpacity={zone.enabled === false ? 0.4 : 1}
              strokeDasharray={zone.enabled === false ? '0.01 0.008' : undefined}
              strokeWidth="2"
              vectorEffect="non-scaling-stroke"
            />
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
        const left = Math.min(...points.map((p) => p.x));
        const top = Math.min(...points.map((p) => p.y));
        return (
          <span key={zone.id} className="pointer-events-none absolute -translate-y-full pb-0.5 text-[11px] font-semibold uppercase"
            style={{ left: `${left * 100}%`, top: `${top * 100}%`, color: zoneColor(zone.zone_type) }}>
            {zone.name}
          </span>
        );
      })}
      {line && (
        <span className="pointer-events-none absolute translate-x-2 text-[11px] font-bold text-slate-100"
          style={{ left: `${line.end.x * 100}%`, top: `${line.end.y * 100}%` }}>
          Virtual line
        </span>
      )}
    </>
  );
}

export default function CameraPanel({
  item, worker, connection, statusError, checkedAt, zones, zoneTypes, line, busy, actionError,
  onConnect, onDisconnect, onRefresh, pickTarget = null, onPick,
}) {
  const stageRef = useRef(null);
  const reference = item?.assignment?.calibration?.reference_frame;
  const width = reference?.width ?? worker?.width;
  const height = reference?.height ?? worker?.height;
  const aspect = width && height ? width / height : 16 / 9;
  const active = workerIsActive(worker) && !statusError;
  const cameraName = item?.camera?.name ?? 'No camera selected';

  const pick = (event) => {
    if (!pickTarget || !onPick || !stageRef.current) return;
    const rect = stageRef.current.getBoundingClientRect();
    const clamp = (value) => Math.round(Math.max(0, Math.min(1, value)) * 10000) / 10000;
    onPick({ x: clamp((event.clientX - rect.left) / rect.width), y: clamp((event.clientY - rect.top) / rect.height) });
  };

  const usedTypes = new Set(zones.map((zone) => zone.zone_type));
  const legend = (zoneTypes ?? []).filter((type) => usedTypes.has(type.key));

  return (
    <Card
      title={`Live feed · ${cameraName}`}
      aside={<Pill tone={connection.tone} dot>{connection.label}</Pill>}
    >
      <div className="mb-3 flex flex-wrap items-center gap-2">
        {active ? (
          <button type="button" className={btnDanger} onClick={onDisconnect} disabled={busy || !item || worker?.status === 'stopping'}>
            <Plug size={14} aria-hidden /> {busy === 'disconnect' ? 'Disconnecting…' : 'Disconnect camera'}
          </button>
        ) : (
          <button type="button" className={btnPrimary} onClick={onConnect} disabled={busy || !item}>
            <PlugZap size={14} aria-hidden /> {busy === 'connect' ? 'Connecting…' : 'Connect camera'}
          </button>
        )}
        <button type="button" className={btnGhost} onClick={onRefresh} title="Refresh worker status">
          <RefreshCw size={14} aria-hidden /> Refresh status
        </button>
        <span className="ml-auto text-xs text-slate-400">{connection.detail}</span>
      </div>
      <ErrorNote>{actionError}</ErrorNote>

      <div
        ref={stageRef}
        onClick={pick}
        className={`relative mt-3 overflow-hidden rounded-lg border border-[#22304d] bg-[radial-gradient(ellipse_at_top,#1d2944,#0d1424)] ${pickTarget ? 'cursor-crosshair' : ''}`}
        style={{ aspectRatio: String(aspect) }}
        role="img"
        aria-label={`Camera stage for ${cameraName}: configured zones only, no video stream`}
      >
        <div className="absolute left-3 top-2 font-mono text-[11px] text-slate-300">
          {item?.camera?.code?.toUpperCase() ?? '—'}{item?.location ? ` · ${item.location.name}` : ''}
          {worker?.last_frame_at ? ` · last frame ${timeOf(worker.last_frame_at)}` : ''}
        </div>
        <ZoneOverlay zones={zones} line={line} />
        <div className="pointer-events-none absolute inset-x-3 bottom-3 flex items-start gap-3 rounded-lg bg-[#0b1222]/90 p-3 ring-1 ring-white/10">
          <VideoOff size={16} className="mt-0.5 shrink-0 text-slate-300" aria-hidden />
          <span className="text-xs leading-5 text-slate-400">
            <b className="text-slate-100">Video stream not available.</b> The backend reports Grill Gate worker health only and exposes no frame or stream endpoint, so no camera image is shown.
            {zones.length ? ' Outlines are the zones configured for this assignment.' : ''}
          </span>
        </div>
        {pickTarget && <span className="pointer-events-none absolute right-3 top-2 rounded bg-white/15 px-2 py-1 text-xs font-semibold text-white">Click to set the line {pickTarget}</span>}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
        {legend.map((type) => (
          <span key={type.key} className="flex items-center gap-1.5" style={{ color: zoneColor(type.key) }}>
            <span className="h-2 w-2 rounded-sm" style={{ background: zoneColor(type.key) }} aria-hidden />{type.label}
          </span>
        ))}
        {line && <span className="text-slate-300">- - Virtual line</span>}
        {!legend.length && !line && <span className="text-slate-500">No zones configured for this assignment.</span>}
      </div>

      <dl className="mt-4 grid grid-cols-2 gap-3 border-t border-[#22304d] pt-4 text-xs sm:grid-cols-4">
        {[
          ['Worker status', worker?.status ?? (statusError ? 'unknown' : 'not started')],
          ['Last frame', timeOf(worker?.last_frame_at)],
          ['Frame age', formatSeconds(worker?.frame_age_seconds)],
          ['Resolution', worker?.width && worker?.height ? `${worker.width}×${worker.height}` : '—'],
          ['Frames captured', worker?.sequence_number ?? '—'],
          ['Reconnect attempt', worker?.reconnect_attempt ?? '—'],
          ['Consumers', worker?.consumer_count ?? '—'],
          ['Source type', worker?.source_type ?? item?.camera?.sources?.[0]?.source_type ?? '—'],
        ].map(([label, value]) => (
          <div key={label}><dt className="text-slate-400">{label}</dt><dd className="mt-0.5 font-semibold text-slate-100">{String(value)}</dd></div>
        ))}
      </dl>
      <p className="mt-3 text-[11px] text-slate-500">
        {statusError ? `Last status check failed: ${statusError}` : checkedAt ? `Status checked ${checkedAt.toLocaleTimeString()} via GET /api/v1/grill-gate/workers` : 'Checking worker status…'}
      </p>
    </Card>
  );
}
