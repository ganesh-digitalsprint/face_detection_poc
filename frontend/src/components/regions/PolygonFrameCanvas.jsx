import { useRef } from 'react';
import { isPolygonClosingClick } from '../../utils/zonePolygons.js';
const clamp = (value) => Math.max(0, Math.min(1, value));
const polygonPoints = (polygon) => (polygon ?? []).map((point) => Array.isArray(point) ? { x: point[0], y: point[1] } : point);

export default function PolygonFrameCanvas({ frame, imageUrl, emptyMessage, zones, editId, drawing, line, lineDraft, readOnly, onPoint, onFinishPolygon, onMoveZone, zoneColor, overlayOnly = false, preserveAspectRatio = 'none', mirrored = false }) {
  const svgRef = useRef(null);
  const dragRef = useRef(null);

  const pointFrom = (event) => {
    const svg = svgRef.current;
    const matrix = svg?.getScreenCTM();
    if (!matrix) return null;
    const point = svg.createSVGPoint();
    point.x = event.clientX;
    point.y = event.clientY;
    const raw = point.matrixTransform(matrix.inverse());
    if (raw.x < 0 || raw.y < 0 || raw.x > frame.width || raw.y > frame.height) return null;
    return { x: mirrored ? 1 - raw.x / frame.width : raw.x / frame.width, y: raw.y / frame.height };
  };
  const onCanvasDown = (event) => {
    if (!drawing || readOnly) return;
    const point = pointFrom(event);
    if (point) {
      const matrix = svgRef.current.getScreenCTM();
      const rect = overlayOnly ? { width: frame.width * Math.abs(matrix.a), height: frame.height * Math.abs(matrix.d) } : svgRef.current.getBoundingClientRect();
      if (drawing.kind === 'polygon' && isPolygonClosingClick(drawing.points, point, rect)) onFinishPolygon();
      else onPoint(point);
    }
  };
  const startDrag = (event, zone, kind, index = -1) => {
    if (drawing || readOnly) return;
    event.stopPropagation();
    const point = pointFrom(event);
    if (!point) return;
    event.currentTarget.setPointerCapture?.(event.pointerId);
    dragRef.current = { zoneId: zone.id, kind, index, origin: point, polygon: zone.polygon.map((p) => ({ ...p })) };
  };
  const onDrag = (event) => {
    const drag = dragRef.current;
    if (!drag) return;
    const point = pointFrom(event);
    if (!point) return;
    onMoveZone(drag.zoneId, drag.polygon.map((vertex, index) => {
      if (drag.kind === 'point') return index === drag.index ? point : vertex;
      return { x: clamp(vertex.x + point.x - drag.origin.x), y: clamp(vertex.y + point.y - drag.origin.y) };
    }));
  };

  const displayX = (x) => mirrored ? 1 - x : x;
  const width = frame?.width ?? 16;
  const height = frame?.height ?? 9;
  const fontSize = Math.max(14, width * 0.016);
  return (
    <div className={overlayOnly ? "absolute inset-0 z-20" : "relative overflow-hidden rounded-lg bg-[#18202E]"} style={overlayOnly ? { pointerEvents: 'none' } : { aspectRatio: String(width / height) }}>
      {imageUrl && <img src={imageUrl} alt="Reference frame for drawing zones" className="absolute inset-0 h-full w-full object-fill" />}
      {!imageUrl && !overlayOnly && <p className="absolute inset-0 flex items-center justify-center p-6 text-center text-sm text-slate-200">{emptyMessage}</p>}
      {frame && (
        <svg ref={svgRef} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio={preserveAspectRatio} aria-label="Zones on the frame"
          className={`absolute inset-0 h-full w-full touch-none ${drawing ? 'cursor-crosshair' : ''}`} style={{ pointerEvents: overlayOnly && !drawing && !editId ? 'none' : 'auto' }}
          onPointerDown={onCanvasDown} onPointerMove={onDrag} onPointerUp={() => { dragRef.current = null; }}>
          {zones.map((zone) => {
            const points = polygonPoints(zone.polygon);
            if (points.length < 3) return null;
            const color = zoneColor(zone.zone_type);
            const selected = editId === zone.id;
            return (
              <g key={zone.id} opacity={zone.enabled === false ? 0.3 : 1}>
                <polygon points={points.map(({ x, y }) => `${displayX(x) * width},${y * height}`).join(' ')} fill={`${color}33`} stroke={color}
                  strokeWidth={selected ? 3 : 2} vectorEffect="non-scaling-stroke"
                  className={selected && !readOnly ? 'cursor-move' : ''}
                  onPointerDown={selected ? (event) => startDrag(event, zone, 'move') : undefined} />
                {selected && !readOnly && points.map((point, index) => (
                  <circle key={index} cx={displayX(point.x) * width} cy={point.y * height} r={Math.max(6, width * 0.006)} fill="white" stroke={color} strokeWidth="3"
                    vectorEffect="non-scaling-stroke" className="cursor-grab" onPointerDown={(event) => startDrag(event, zone, 'point', index)} />
                ))}
                <text x={Math.min(...points.map((p) => displayX(p.x))) * width + fontSize * 0.5} y={(points.reduce((sum, p) => sum + p.y, 0) / points.length) * height}
                  fill="white" stroke="#18202E" strokeWidth="3" paintOrder="stroke" fontSize={fontSize} pointerEvents="none">{zone.name}</text>
              </g>
            );
          })}
          {drawing?.kind === 'polygon' && drawing.points.length > 0 && (
            <g>
              <polyline points={drawing.points.map((p) => `${displayX(p.x) * width},${p.y * height}`).join(' ')} fill="none" stroke={zoneColor(drawing.zoneType)} strokeWidth="3" vectorEffect="non-scaling-stroke" />
              {drawing.points.map((p, index) => <circle key={index} cx={displayX(p.x) * width} cy={p.y * height} r={Math.max(5, width * 0.005)} fill="white" stroke={zoneColor(drawing.zoneType)} strokeWidth="2" vectorEffect="non-scaling-stroke" />)}
            </g>
          )}
          {lineDraft && <circle cx={lineDraft.x * width} cy={lineDraft.y * height} r={Math.max(6, width * 0.006)} fill="white" />}
          {line && (
            <g pointerEvents="none">
              <line x1={line.start.x * width} y1={line.start.y * height} x2={line.end.x * width} y2={line.end.y * height} stroke="white" strokeWidth="3" strokeDasharray="10 7" vectorEffect="non-scaling-stroke" />
              <text x={line.start.x * width + fontSize * 0.6} y={line.start.y * height + fontSize} fill="white" stroke="#18202E" strokeWidth="3" paintOrder="stroke" fontSize={fontSize}>ENTRY / EXIT line</text>
            </g>
          )}
        </svg>
      )}
    </div>
  );
}

