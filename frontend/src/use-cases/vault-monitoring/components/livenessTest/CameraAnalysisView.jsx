import { Loader2, Snowflake } from 'lucide-react';
import { CAMERA_KINDS } from '../../hooks/useCameraSource.js';
import { primaryResult } from '../../hooks/useLivenessTest.js';
import CameraPreview from '../vault/CameraPreview.jsx';
import AnalysisOverlay from './AnalysisOverlay.jsx';
import { CHALLENGE_AXIS, DETECTOR_LABELS, directionHint, grouped, notVisibleText } from './format.js';

// Chips sit in one wrapping row so they stack instead of overlapping on narrow screens.
const chip = 'inline-flex min-w-0 max-w-full items-center gap-2 rounded-full px-3 py-1.5 text-xs font-semibold sm:text-sm';

function StatusChip({ test }) {
  const result = primaryResult(test.analysis, test.detector);
  const fps = Math.round(test.stats.fps);
  const name = DETECTOR_LABELS[test.detector];
  if (!result) return null;
  if (result.error && !result.visible) {
    return <span className={`${chip} bg-[#B3261E] text-white`}>Detector error · {name}</span>;
  }
  if (!result.visible) {
    return (
      <span className={`${chip} bg-[#B3261E] text-white`}>
        <span className="h-2 w-2 shrink-0 rounded-full bg-white" aria-hidden />
        <span className="truncate">No face · {notVisibleText(result.not_visible_reason)}</span>
      </span>
    );
  }
  return (
    <span className={`${chip} bg-black/55 text-white`}>
      <span className="h-2 w-2 shrink-0 rounded-full bg-[#5EE6A8]" aria-hidden />
      <span className="truncate">Face detected · {name} · <span className="tabular-nums">{fps}</span> fps</span>
    </span>
  );
}

function hintText(test) {
  const result = primaryResult(test.analysis, test.detector);
  if (!result?.visible) return 'Position your face inside the frame';
  const base = directionHint(result.pose?.direction);
  const target = CHALLENGE_AXIS[test.challenge]?.direction;
  if (test.challenge && test.analysis?.challenge?.passed) return `${base} · passed`;
  if (target && result.pose?.direction === target) return `${base} · hold it`;
  return base;
}

/** Live video plus everything drawn over it. Frozen mode shows the last analysed frame instead. */
export default function CameraAnalysisView({ camera, test, toggles }) {
  const mirrored = camera.kind === CAMERA_KINDS.WEBCAM; // CameraPreview mirrors the webcam only
  const running = test.phase === 'running' || test.phase === 'frozen';
  const elapsed = test.stats.lastElapsed;

  return (
    <CameraPreview camera={camera} variant="stage">
      {test.frozenFrame && (
        <img src={test.frozenFrame} alt="Frozen analysed frame"
          className={`absolute inset-0 h-full w-full object-cover ${mirrored ? '-scale-x-100' : ''}`} />
      )}
      {running && <AnalysisOverlay analysis={test.analysis} mirrored={mirrored} toggles={toggles} compare={test.detector === 'both'} />}
      {running && (
        <div className="absolute inset-x-3 top-3 z-10 flex flex-wrap items-start justify-between gap-2 sm:inset-x-4 sm:top-4">
          <StatusChip test={test} />
          {test.analysis && (
        <span className={`${chip} ml-auto font-mono tabular-nums bg-black/55 text-white`}>
          {test.phase === 'frozen' && <Snowflake className="h-3.5 w-3.5" aria-hidden />}
          {test.phase === 'frozen' ? 'Frozen · ' : ''}frame {grouped(test.analysis.frame_number)} · {elapsed == null ? '—' : Math.round(elapsed)} ms
        </span>
          )}
        </div>
      )}
      {test.phase === 'starting' && (
        <div role="status" className="absolute inset-0 z-20 flex flex-col items-center justify-center gap-3 bg-[#0B1224]/70 text-white">
          <Loader2 className="h-10 w-10 animate-spin motion-reduce:animate-none" aria-hidden />
          <p className="text-sm font-medium">Starting test session…</p>
        </div>
      )}
      {running && test.analysis && (
        <div className="absolute inset-x-4 bottom-4 z-10 mx-auto max-w-md rounded-xl bg-white px-5 py-3 text-center shadow-lg sm:bottom-6">
          <p className="text-[11px] font-bold uppercase tracking-[0.12em] text-[#34479B]">
            {test.challenge ? `Challenge · ${test.challenge.replaceAll('_', ' ')}` : 'No challenge selected'}
          </p>
          {/* Text only changes when direction or pass state changes, so it is not announced per frame. */}
          <p role="status" aria-live="polite" className="mt-1 text-lg font-bold text-[#0F1B3D] sm:text-2xl">{hintText(test)}</p>
        </div>
      )}
    </CameraPreview>
  );
}
