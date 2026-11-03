// Pure helpers for the entry-ROI canvas (no React, no DOM) so they can be unit-tested with `node --test`.

/** Click position (CSS pixels inside the canvas) -> normalised 0..1 point, clamped to the image. */
export function toNormalised(clientX, clientY, rect) {
  const x = (clientX - rect.left) / rect.width;
  const y = (clientY - rect.top) / rect.height;
  return { x: Math.min(1, Math.max(0, x)), y: Math.min(1, Math.max(0, y)) };
}

/** Is point `p` within `radiusPx` of `target` on a canvas of the given size? (used to close the polygon) */
export function isNear(p, target, size, radiusPx = 12) {
  return Math.hypot((p.x - target.x) * size.width, (p.y - target.y) * size.height) <= radiusPx;
}

/**
 * Direction of the drawn arrow as the backend wants it: movement in PIXEL space, not in 0..1 space.
 * dx is scaled by the image aspect ratio (width / height), so a 45-degree arrow on a 4:3 picture stays 45 degrees.
 * Returns null for a zero-length arrow.
 */
export function arrowToVector(arrow, aspect) {
  if (!arrow) return null;
  const dx = (arrow.x2 - arrow.x1) * aspect;
  const dy = arrow.y2 - arrow.y1;
  const length = Math.hypot(dx, dy);
  if (length < 1e-6) return null;
  return { x: Number((dx / length).toFixed(4)), y: Number((dy / length).toFixed(4)) };
}

/** Inverse of arrowToVector, used to draw a saved ROI's arrow: a vector in pixel space -> end point in 0..1 space. */
export function vectorToArrow(origin, vector, aspect, length = 0.14) {
  const len = Math.hypot(vector.x, vector.y) || 1;
  return {
    x1: origin.x, y1: origin.y,
    x2: origin.x + ((vector.x / len) * length) / aspect,
    y2: origin.y + (vector.y / len) * length,
  };
}

/** Centre of a polygon (mean of its points), where saved arrows are drawn from. */
export function centroid(points) {
  if (!points.length) return { x: 0.5, y: 0.5 };
  return {
    x: points.reduce((s, p) => s + p.x, 0) / points.length,
    y: points.reduce((s, p) => s + p.y, 0) / points.length,
  };
}

/** A usable polygon has at least 3 distinct, finite points inside 0..1. */
export function isValidPolygon(points) {
  if (!Array.isArray(points) || points.length < 3) return false;
  if (!points.every((p) => Number.isFinite(p.x) && Number.isFinite(p.y) && p.x >= 0 && p.x <= 1 && p.y >= 0 && p.y <= 1)) return false;
  return new Set(points.map((p) => `${p.x.toFixed(3)},${p.y.toFixed(3)}`)).size >= 3;
}

/** Human description of the inward direction for the ROI list ("up", "down-left", ...). */
export function describeDirection(v) {
  if (!v) return '-';
  const vertical = Math.abs(v.y) > 0.38 ? (v.y < 0 ? 'up' : 'down') : '';
  const horizontal = Math.abs(v.x) > 0.38 ? (v.x < 0 ? 'left' : 'right') : '';
  return [vertical, horizontal].filter(Boolean).join('-') || '-';
}
