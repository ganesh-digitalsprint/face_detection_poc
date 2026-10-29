import { AlertTriangle } from 'lucide-react';
import { clamp01, fixed, notVisibleText } from './format.js';
import { Badge, DetectorError, LabCard } from './ui.jsx';

const QUALITY_TONE = { GOOD: 'success', FAIR: 'warning', POOR: 'danger' };

/** Bar scaled so the minimum sits at one third; below the minimum it turns amber and says so. */
function Bar({ label, value, ratio, ok, detail }) {
  return (
    <div className="py-2">
      <div className="flex items-center justify-between gap-2 text-sm">
        <span className="text-[#0F1B3D]">{label}</span>
        <span className="font-mono tabular-nums text-[#0F1B3D]">
          {value} {detail && <span className="text-[#55607A]">{detail}</span>}
          {ok === false && <span className="ml-1 font-sans text-xs font-semibold text-[#6B4500]">below min</span>}
        </span>
      </div>
      <div className="mt-1.5 h-2 rounded-full bg-[#E3E7F0]" aria-hidden>
        <div className={`h-2 rounded-full ${ok === false ? 'bg-[#C98A00]' : 'bg-[#0B7A4B]'}`} style={{ width: `${clamp01(ratio) * 100}%` }} />
      </div>
    </div>
  );
}

export default function ClarityCard({ result }) {
  const clarity = result?.clarity;
  const hidden = result && !result.visible;
  const quality = clarity?.quality;
  const badge = hidden
    ? <Badge tone="warning">FACE NOT VISIBLE</Badge>
    : quality ? <Badge tone={QUALITY_TONE[quality] ?? 'neutral'}>{quality}</Badge> : <Badge>WAITING</Badge>;
  const minSharp = clarity?.min_sharpness;
  const minFace = clarity?.min_face_px;
  const smallestSide = clarity ? Math.min(clarity.face_width ?? 0, clarity.face_height ?? 0) : 0;

  return (
    <LabCard title="Image clarity" labelledBy="lt-clarity" badge={badge} tone={hidden ? 'warning' : undefined}>
      {hidden && (
        <p role="status" className="mb-2 flex items-start gap-2 rounded-lg bg-[#FFF4DC] p-3 text-sm font-semibold text-[#6B4500]">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          {notVisibleText(result.not_visible_reason)}
        </p>
      )}
      {result?.error && <DetectorError detector={result.detector} error={result.error} />}
      {clarity ? (
        <>
          <Bar label="Sharpness" value={fixed(clarity.sharpness)} detail={minSharp != null ? `(min ${fixed(minSharp)})` : null}
            ratio={minSharp ? clarity.sharpness / (minSharp * 3) : 0} ok={minSharp != null ? clarity.sharpness >= minSharp : undefined} />
          <Bar label="Brightness" value={`${fixed(clarity.brightness)} / 255`} ratio={(clarity.brightness ?? 0) / 255} />
          <Bar label="Face size" value={`${fixed(clarity.face_width)} × ${fixed(clarity.face_height)} px`}
            detail={minFace != null ? `(min ${fixed(minFace)})` : null}
            ratio={minFace ? smallestSide / (minFace * 3) : 0} ok={minFace != null ? smallestSide >= minFace : undefined} />
        </>
      ) : (
        !hidden && <p className="text-sm text-[#55607A]">Clarity appears once a frame is analysed.</p>
      )}
    </LabCard>
  );
}
