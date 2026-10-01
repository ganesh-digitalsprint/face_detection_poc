import { ScanFace } from 'lucide-react';
import EmptyState from '../common/EmptyState.jsx';
import StatusBadge from '../common/StatusBadge.jsx';
import { formatConfidence } from '../../utils/formatters.js';

export default function DetectionResults({ result }) {
  if (!result.faces_detected) {
    return <EmptyState icon={ScanFace} title="No faces detected" description="Try another image with a clearly visible face." />;
  }
  return (
    <div>
      <p className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-700">
        Faces Detected: {result.faces_detected} <StatusBadge status="DETECTED" />
      </p>
      <ul className="space-y-2">
        {result.faces.map((face, i) => (
          <li key={i} className="rounded-md border border-slate-200 p-3 text-sm">
            <p className="font-medium">Face #{i + 1}</p>
            <p className="text-slate-600">Confidence: {formatConfidence(face.detection_confidence)}</p>
            <p className="text-xs text-slate-400">
              x {face.bbox.x}, y {face.bbox.y}, {face.bbox.width}×{face.bbox.height}px
            </p>
          </li>
        ))}
      </ul>
    </div>
  );
}
