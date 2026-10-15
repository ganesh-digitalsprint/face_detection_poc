import { ImageOff, X } from 'lucide-react';
import EmptyState from '../common/EmptyState.jsx';

/** Reviewable gallery of captured frames; every listed image is submitted on enroll. */
export default function CapturedGallery({ frames, max, disabled, onRemove }) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-slate-700">Captured Face Images</h3>
        <span className="text-xs text-slate-500">{frames.length} of {max} will be submitted</span>
      </div>
      {frames.length === 0 ? (
        <EmptyState
          icon={ImageOff}
          title="No images captured yet."
          description="Start the camera and capture a few face images from different angles."
        />
      ) : (
        <ul className="grid gap-3 sm:grid-cols-3">
          {frames.map((frame, index) => (
            <li key={frame.id} className="relative overflow-hidden rounded-lg border border-slate-200 bg-slate-900">
              <img src={frame.url} alt={`Captured image ${index + 1}`} className="aspect-video w-full object-contain" />
              <span className="absolute left-2 top-2 rounded-full bg-white/90 px-2 py-0.5 text-xs font-medium text-slate-700">
                Image {index + 1}
              </span>
              <button
                type="button"
                disabled={disabled}
                onClick={() => onRemove(frame.id)}
                aria-label={`Remove captured image ${index + 1}`}
                className="absolute right-2 top-2 rounded-full bg-white/90 p-1 text-slate-700 shadow hover:bg-white disabled:opacity-50"
              >
                <X className="h-4 w-4" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
