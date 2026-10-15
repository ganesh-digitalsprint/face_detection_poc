import { DETECTOR_COLORS, DETECTOR_LABELS, notVisibleText, shortLandmarkLabel } from './format.js';

const LABEL_STROKE = '#0B1224';

/**
 * Mirroring is done on the coordinates (not with a CSS transform) so text stays readable.
 * `slice` matches the video's `object-fit: cover`, so image-space points land on the face.
 */
function DetectorLayer({ result, width, height, mirrored, toggles, color, scale }) {
  if (!result?.visible) return null;
  const mx = (x) => (mirrored ? width - x : x);
  const { bbox, landmarks = {} } = result;
  const points = Object.entries(landmarks).filter(([, p]) => p && Number.isFinite(p.x) && Number.isFinite(p.y));
  const nose = landmarks.nose;
  const font = 12 * scale;
  const pad = 20 * scale;

  return (
    <g>
      {toggles.faceBox && bbox && (
        <>
          <rect
            x={mirrored ? width - bbox.x - bbox.width : bbox.x} y={bbox.y} width={bbox.width} height={bbox.height}
            fill="none" stroke={color} strokeWidth={2.5 * scale} rx={4 * scale}
          />
          {toggles.labels && (
            <text x={mirrored ? width - bbox.x - bbox.width : bbox.x} y={bbox.y - 6 * scale} fill={color} fontSize={font}
              fontFamily="ui-monospace, monospace" fontWeight="700" stroke={LABEL_STROKE} strokeWidth={3 * scale}
              paintOrder="stroke">
              {`box ${Math.round(bbox.x)},${Math.round(bbox.y)} · ${Math.round(bbox.width)}×${Math.round(bbox.height)}`}
            </text>
          )}
        </>
      )}
      {toggles.axes && nose && bbox && (
        <g stroke="white" strokeOpacity="0.7" strokeWidth={1.2 * scale} strokeDasharray={`${4 * scale} ${3 * scale}`}>
          <line x1={mx(nose.x)} x2={mx(nose.x)} y1={bbox.y - pad} y2={bbox.y + bbox.height + pad} />
          <line
            x1={mirrored ? width - bbox.x - bbox.width - pad : bbox.x - pad}
            x2={mirrored ? width - bbox.x + pad : bbox.x + bbox.width + pad}
            y1={nose.y} y2={nose.y}
          />
        </g>
      )}
      {toggles.landmarks && points.map(([name, p]) => {
        const x = mx(p.x);
        // Labels point away from the face's vertical axis so left/right pairs never collide.
        const axisX = nose ? mx(nose.x) : width / 2;
        const outward = x < axisX - 2 * scale ? -1 : 1;
        return (
          <g key={name}>
            <circle cx={x} cy={p.y} r={5 * scale} fill={color} stroke={LABEL_STROKE} strokeWidth={1.5 * scale} />
            {toggles.labels && (
              <text
                x={x + outward * 8 * scale} y={p.y - 7 * scale} textAnchor={outward < 0 ? 'end' : 'start'}
                fill="white" fontSize={font} fontFamily="ui-monospace, monospace" fontWeight="700"
                stroke={LABEL_STROKE} strokeWidth={3 * scale} paintOrder="stroke"
              >
                {`${shortLandmarkLabel(name, mirrored)} ${Math.round(p.x)},${Math.round(p.y)}`}
              </text>
            )}
          </g>
        );
      })}
    </g>
  );
}

function summary(results) {
  if (!results.length) return 'No analysis yet';
  return results.map((r) => {
    const name = DETECTOR_LABELS[r.detector] ?? r.detector;
    if (r.error) return `${name}: error`;
    if (!r.visible) return `${name}: ${notVisibleText(r.not_visible_reason)}`;
    return `${name}: face detected${r.pose?.direction ? `, direction ${r.pose.direction}` : ''}`;
  }).join('. ');
}

/** Face box, landmarks, labels and axes drawn in image space over the video. */
export default function AnalysisOverlay({ analysis, mirrored, toggles, compare }) {
  const width = analysis?.image_width;
  const height = analysis?.image_height;
  if (!width || !height) return null;
  const results = analysis.results ?? [];
  // Sizes are authored for a 640px-wide frame and scale with the actual capture size.
  const scale = width / 640;

  return (
    <>
      <svg role="img" aria-label={summary(results)} className="pointer-events-none absolute inset-0 h-full w-full"
        viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="xMidYMid slice">
        {/* Compare mode: only the first detector carries text, so the two label sets never overprint. */}
        {results.map((result, index) => (
          <DetectorLayer key={result.detector} result={result} width={width} height={height} mirrored={mirrored}
            toggles={index === 0 ? toggles : { ...toggles, labels: false }} scale={scale}
            color={DETECTOR_COLORS[result.detector] ?? DETECTOR_COLORS.mediapipe} />
        ))}
      </svg>
      {compare && (
        <ul aria-label="Overlay legend" className="absolute left-3 top-14 z-10 flex gap-3 sm:left-4 sm:top-16 rounded-md bg-black/60 px-3 py-1.5 text-xs font-semibold text-white">
          {['mediapipe', 'deepface'].map((detector) => (
            <li key={detector} className="flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-full" style={{ background: DETECTOR_COLORS[detector] }} aria-hidden />
              {DETECTOR_LABELS[detector]}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
