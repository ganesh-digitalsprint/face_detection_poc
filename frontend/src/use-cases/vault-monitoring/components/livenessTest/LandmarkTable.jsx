import { DETECTOR_LABELS } from './format.js';
import { LabCard } from './ui.jsx';

const point = (p) => (p ? `${Math.round(p.x)}, ${Math.round(p.y)}` : '—');
const box = (b) => (b ? [b.x, b.y, b.width, b.height].map(Math.round).join(', ') : '—');

function cell(result, render) {
  if (!result) return '—';
  if (result.error) return <span className="text-[#B3261E]">error</span>;
  if (!result.visible) return <span className="text-[#6B4500]">not visible</span>;
  return render(result);
}

/** Every landmark in image pixels; one column per detector in compare mode. */
export default function LandmarkTable({ results }) {
  const names = [...new Set(results.flatMap((r) => Object.keys(r.landmarks ?? {})))];
  const compare = results.length > 1;

  return (
    <LabCard title="Landmark coordinates" labelledBy="lt-landmarks" aside="px · image space">
      {results.length === 0 ? (
        <p className="text-sm text-[#55607A]">Coordinates appear once a frame is analysed.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <caption className="sr-only">Landmark coordinates in image pixels</caption>
            {compare && (
              <thead>
                <tr className="text-xs text-[#55607A]">
                  <th scope="col" className="py-1 text-left font-medium">Point</th>
                  {results.map((r) => (
                    <th key={r.detector} scope="col" className="py-1 text-right font-medium">{DETECTOR_LABELS[r.detector] ?? r.detector}</th>
                  ))}
                </tr>
              </thead>
            )}
            <tbody>
              {[...names.map((name) => ({ key: name, label: name, render: (r) => point(r.landmarks?.[name]) })),
                { key: '__bbox', label: 'bbox x, y, w, h', render: (r) => box(r.bbox) }].map((row) => (
                <tr key={row.key} className="border-b border-[#EEF1F7] last:border-b-0">
                  <th scope="row" className="py-2 text-left font-normal text-[#55607A]">{row.label}</th>
                  {results.map((r) => (
                    <td key={r.detector} className="py-2 text-right font-mono tabular-nums text-[#0F1B3D]">
                      {cell(r, row.render)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </LabCard>
  );
}
