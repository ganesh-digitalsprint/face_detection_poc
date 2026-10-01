import { useState } from 'react';

/**
 * Image + proportional bounding boxes.
 * Backend bbox = { x, y, width, height } in ORIGINAL image pixels (top-left origin),
 * so boxes are positioned in percentages of the image's natural size and scale with it.
 * `faces`: [{ bbox, label?, tone? }]
 */
export default function FaceBoundingBoxViewer({ src, alt, faces = [] }) {
  const [size, setSize] = useState(null);

  return (
    <div className="relative inline-block max-w-full leading-none">
      <img
        src={src}
        alt={alt}
        className="block max-h-[28rem] max-w-full rounded-md"
        onLoad={(e) => setSize({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })}
      />
      {size &&
        faces.map(({ bbox, label, tone = 'brand' }, i) => (
          <div
            key={i}
            className={`pointer-events-none absolute border-2 ${tone === 'unknown' ? 'border-amber-400' : tone === 'match' ? 'border-emerald-400' : 'border-accent'}`}
            style={{
              left: `${(bbox.x / size.w) * 100}%`,
              top: `${(bbox.y / size.h) * 100}%`,
              width: `${(bbox.width / size.w) * 100}%`,
              height: `${(bbox.height / size.h) * 100}%`,
            }}
          >
            <span
              className={`absolute -top-5 left-[-2px] whitespace-nowrap px-1 text-[11px] font-semibold leading-4 text-white ${
                tone === 'unknown' ? 'bg-amber-500' : tone === 'match' ? 'bg-emerald-600' : 'bg-accent'
              }`}
            >
              {label ?? `Face #${i + 1}`}
            </span>
          </div>
        ))}
    </div>
  );
}
