import { useEffect, useRef } from 'react';
import { useBxTheme } from '../theme.js';

const cssVar = (name, fallback) => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;

function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

function setup(canvas) {
  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth; const h = canvas.clientHeight;
  canvas.width = w * dpr; canvas.height = h * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  return { ctx, w, h };
}

function drawBarChart(canvas, labels, values, color) {
  const { ctx, w, h } = setup(canvas);
  if (!w || !h) return;
  const max = Math.max(1, ...values);
  const padL = 26; const padB = 22; const padT = 10; const padR = 6;
  const chartW = w - padL - padR; const chartH = h - padB - padT;
  const barW = chartW / Math.max(1, values.length);
  const grid = cssVar('--bx-border-soft', '#333');
  const text = cssVar('--bx-faint', '#888');
  ctx.strokeStyle = grid; ctx.lineWidth = 1;
  for (let g = 0; g <= 3; g++) {
    const y = padT + (chartH / 3) * g;
    ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(w - padR, y); ctx.stroke();
  }
  values.forEach((v, i) => {
    const bh = (v / max) * chartH;
    const x = padL + i * barW + barW * 0.18;
    const bw = barW * 0.64;
    const y = padT + chartH - bh;
    const grad = ctx.createLinearGradient(0, y, 0, padT + chartH);
    grad.addColorStop(0, color); grad.addColorStop(1, `${color}55`);
    ctx.fillStyle = v > 0 ? grad : grid;
    roundRect(ctx, x, y, bw, Math.max(2, bh), 3);
    ctx.fill();
  });
  ctx.fillStyle = text; ctx.font = '10px system-ui, sans-serif'; ctx.textAlign = 'center';
  const step = Math.max(1, Math.floor(labels.length / 12));
  labels.forEach((l, i) => { if (i % step === 0) ctx.fillText(l, padL + i * barW + barW / 2, h - 6); });
}

function drawDonut(canvas, segments) {
  const { ctx, w, h } = setup(canvas);
  if (!w || !h) return;
  const total = segments.reduce((a, s) => a + s.value, 0);
  const cx = w / 2; const cy = h / 2; const rOuter = Math.min(w, h) / 2 - 4; const rInner = rOuter * 0.62;
  let start = -Math.PI / 2;
  if (total === 0) {
    ctx.strokeStyle = cssVar('--bx-border-soft', '#333'); ctx.lineWidth = rOuter - rInner;
    ctx.beginPath(); ctx.arc(cx, cy, (rOuter + rInner) / 2, 0, Math.PI * 2); ctx.stroke();
  } else {
    segments.forEach((s) => {
      if (s.value <= 0) return;
      const angle = (s.value / total) * Math.PI * 2;
      ctx.beginPath(); ctx.arc(cx, cy, (rOuter + rInner) / 2, start, start + angle);
      ctx.lineWidth = rOuter - rInner; ctx.strokeStyle = s.color; ctx.stroke();
      start += angle;
    });
  }
  ctx.fillStyle = cssVar('--bx-title', '#fff'); ctx.font = 'bold 18px system-ui, sans-serif';
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  ctx.fillText(String(total), cx, cy - 4);
  ctx.font = '10px system-ui, sans-serif'; ctx.fillStyle = cssVar('--bx-faint', '#888');
  ctx.fillText('events', cx, cy + 12);
}

function useCanvasDraw(draw, deps) {
  const ref = useRef(null);
  const theme = useBxTheme();
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return undefined;
    const run = () => draw(canvas);
    // wait one frame so the theme variables of the new theme are applied before reading them
    const raf = requestAnimationFrame(run);
    const ro = new ResizeObserver(run);
    ro.observe(canvas);
    return () => { cancelAnimationFrame(raf); ro.disconnect(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [theme, ...deps]);
  return ref;
}

export function BarChart({ labels, values, color }) {
  const ref = useCanvasDraw((c) => drawBarChart(c, labels, values, color), [JSON.stringify(labels), JSON.stringify(values), color]);
  return <canvas ref={ref} style={{ width: '100%', height: 150, display: 'block' }} />;
}

export function DonutChart({ segments }) {
  const ref = useCanvasDraw((c) => drawDonut(c, segments), [JSON.stringify(segments)]);
  return <canvas ref={ref} style={{ width: '100%', height: 150, display: 'block' }} />;
}
