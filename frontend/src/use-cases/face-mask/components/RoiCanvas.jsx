import { useCallback, useEffect, useRef, useState } from 'react';
import { centroid, isNear, toNormalised, vectorToArrow } from './roiMath.js';

const SAVED = '#22d3ee';
const DRAFT = '#f59e0b';
const ARROW = '#22c55e';

function drawArrow(ctx, w, h, a, color) {
  const [x1, y1, x2, y2] = [a.x1 * w, a.y1 * h, a.x2 * w, a.y2 * h];
  const angle = Math.atan2(y2 - y1, x2 - x1);
  ctx.strokeStyle = color; ctx.fillStyle = color; ctx.lineWidth = 3;
  ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(x2, y2);
  ctx.lineTo(x2 - 14 * Math.cos(angle - 0.4), y2 - 14 * Math.sin(angle - 0.4));
  ctx.lineTo(x2 - 14 * Math.cos(angle + 0.4), y2 - 14 * Math.sin(angle + 0.4));
  ctx.closePath(); ctx.fill();
}

function drawPolygon(ctx, w, h, points, color, { closed = true, fill = true, label } = {}) {
  if (!points.length) return;
  ctx.strokeStyle = color; ctx.lineWidth = 2;
  ctx.beginPath();
  points.forEach((p, i) => (i ? ctx.lineTo(p.x * w, p.y * h) : ctx.moveTo(p.x * w, p.y * h)));
  if (closed) ctx.closePath();
  if (closed && fill) { ctx.globalAlpha = 0.16; ctx.fillStyle = color; ctx.fill(); ctx.globalAlpha = 1; }
  ctx.stroke();
  ctx.fillStyle = color;
  points.forEach((p, i) => { ctx.beginPath(); ctx.arc(p.x * w, p.y * h, i === 0 ? 6 : 4, 0, Math.PI * 2); ctx.fill(); });
  if (label) { ctx.font = '600 13px sans-serif'; ctx.fillText(label, points[0].x * w + 8, points[0].y * h - 8); }
}

/**
 * A camera still with the entry ROIs drawn over it. In "polygon" mode clicks add polygon points (click the first
 * point, or press Enter, to close); in "arrow" mode two clicks set the inward direction. Everything is stored
 * normalised 0..1, so the ROI does not depend on the resolution. Backspace removes the last point.
 *
 * @param {{ imageUrl: string, saved: Array, draft: {points: Array, closed: boolean, arrow: object|null},
 *   mode: 'view'|'polygon'|'arrow', onDraft: Function, onAspect: Function, onImageError: Function }} props
 */
export default function RoiCanvas({ imageUrl, saved, draft, mode, onDraft, onAspect, onImageError }) {
  const imgRef = useRef(null);
  const canvasRef = useRef(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [aspect, setAspect] = useState(4 / 3);

  const redraw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas || !size.width) return;
    canvas.width = size.width; canvas.height = size.height;
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, size.width, size.height);
    (saved || []).forEach((roi) => {
      drawPolygon(ctx, size.width, size.height, roi.polygon, SAVED, { label: roi.name });
      const c = centroid(roi.polygon);
      drawArrow(ctx, size.width, size.height, vectorToArrow(c, roi.inward_vector, aspect), SAVED);
    });
    if (draft.points.length) drawPolygon(ctx, size.width, size.height, draft.points, DRAFT, { closed: draft.closed, fill: draft.closed });
    if (draft.arrow) drawArrow(ctx, size.width, size.height, draft.arrow, ARROW);
  }, [saved, draft, size, aspect]);

  useEffect(redraw, [redraw]);

  const measure = useCallback(() => {
    const img = imgRef.current;
    if (!img) return;
    setSize({ width: img.clientWidth, height: img.clientHeight });
    if (img.naturalWidth && img.naturalHeight) {
      const a = img.naturalWidth / img.naturalHeight;
      setAspect(a); onAspect?.(a);
    }
  }, [onAspect]);

  useEffect(() => {
    window.addEventListener('resize', measure);
    return () => window.removeEventListener('resize', measure);
  }, [measure]);

  useEffect(() => {
    const onKey = (e) => {
      if (mode !== 'polygon' || ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName)) return;
      if (e.key === 'Backspace') { e.preventDefault(); onDraft({ ...draft, points: draft.points.slice(0, -1), closed: false }); }
      if (e.key === 'Enter' && draft.points.length >= 3) onDraft({ ...draft, closed: true });
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [mode, draft, onDraft]);

  const onClick = (e) => {
    if (mode === 'view') return;
    const p = toNormalised(e.clientX, e.clientY, canvasRef.current.getBoundingClientRect());
    if (mode === 'polygon') {
      if (draft.closed) return;
      if (draft.points.length >= 3 && isNear(p, draft.points[0], size)) onDraft({ ...draft, closed: true });
      else onDraft({ ...draft, points: [...draft.points, p] });
    } else if (mode === 'arrow') {
      const a = draft.arrow;
      if (!a || a.done) onDraft({ ...draft, arrow: { x1: p.x, y1: p.y, x2: p.x, y2: p.y, done: false } });
      else onDraft({ ...draft, arrow: { ...a, x2: p.x, y2: p.y, done: true } });
    }
  };

  const onMove = (e) => {
    if (mode !== 'arrow' || !draft.arrow || draft.arrow.done) return;
    const p = toNormalised(e.clientX, e.clientY, canvasRef.current.getBoundingClientRect());
    onDraft({ ...draft, arrow: { ...draft.arrow, x2: p.x, y2: p.y } });
  };

  return (
    <div className="bx-canvas-wrap" style={{ minHeight: 160 }}>
      <img
        ref={imgRef} src={imageUrl} alt="Camera view" onLoad={measure} onError={onImageError}
        style={{ display: 'block', width: '100%', height: 'auto' }}   /* natural aspect: no letterboxing, so canvas and picture line up */
      />
      <canvas
        ref={canvasRef} onClick={onClick} onMouseMove={onMove}
        style={{ cursor: mode === 'view' ? 'default' : 'crosshair', width: size.width, height: size.height }}
        aria-label="Draw the entry region on the camera view"
      />
    </div>
  );
}
