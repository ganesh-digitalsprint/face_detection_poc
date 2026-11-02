import { useState } from 'react';
import { Cctv, ClipboardCopy, Crosshair, Pause, Play, Square, Video, Webcam } from 'lucide-react';
import { CAMERA_KINDS } from '../../hooks/useCameraSource.js';
import { DETECTORS } from '../../hooks/useLivenessTest.js';
import { DETECTOR_LABELS } from './format.js';

const base = 'inline-flex min-h-11 items-center justify-center gap-2 rounded-md px-4 text-sm font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-50';
const segment = (active) => `${base} ${active ? 'bg-[#34479B] text-white' : 'text-[#55607A] hover:bg-white'}`;
const secondary = `${base} border border-[#E3E7F0] bg-white text-[#0F1B3D] hover:bg-slate-50`;
const danger = `${base} bg-[#B3261E] text-white hover:bg-[#931F18]`;
const primary = `${base} bg-[#34479B] text-white hover:bg-brand-dark`;

const SOURCES = [
  { kind: CAMERA_KINDS.WEBCAM, label: 'Webcam', icon: Webcam },
  { kind: CAMERA_KINDS.CCTV, label: 'CCTV', icon: Cctv },
];

function Segmented({ label, options, value, onChange, disabled }) {
  return (
    <div role="group" aria-label={label} className="inline-flex rounded-lg bg-[#F4F6FB] p-1">
      {options.map((option) => (
        <button key={option.value} type="button" aria-pressed={value === option.value} disabled={disabled}
          className={segment(value === option.value)} onClick={() => onChange(option.value)}>
          {option.icon && <option.icon className="h-4 w-4" aria-hidden />} {option.label}
        </button>
      ))}
    </div>
  );
}

export default function LivenessTestControls({ camera, test, onStopCamera }) {
  const [source, setSource] = useState(camera.kind ?? CAMERA_KINDS.WEBCAM);
  const cameraOn = camera.status === 'starting' || camera.status === 'ready';
  const selected = camera.kind ?? source;
  const live = test.phase === 'running' || test.phase === 'frozen';
  const frozen = test.phase === 'frozen';

  const chooseSource = (kind) => {
    setSource(kind);
    if (cameraOn && kind !== camera.kind) camera.start(kind);
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-3">
        <Segmented label="Detector" value={test.detector} onChange={test.changeDetector}
          options={Object.values(DETECTORS).map((value) => ({ value, label: DETECTOR_LABELS[value] }))} />
        <Segmented label="Camera source" value={selected} onChange={chooseSource} disabled={camera.status === 'starting'}
          options={SOURCES.map(({ kind, label, icon }) => ({ value: kind, label, icon }))} />
      </div>
      <div className="flex flex-wrap gap-2">
        {cameraOn ? (
          <>
            <button type="button" className={secondary} disabled={!live || (!frozen && !test.analysis)}
              onClick={frozen ? test.unfreeze : test.freeze}>
              {frozen ? <Play className="h-4 w-4" aria-hidden /> : <Pause className="h-4 w-4" aria-hidden />}
              {frozen ? 'Resume' : 'Freeze frame'}
            </button>
            <button type="button" className={secondary} disabled={!test.analysis} onClick={test.copyAnalysisJson}>
              <ClipboardCopy className="h-4 w-4" aria-hidden />
              {test.copyStatus === 'copied' ? 'Copied' : test.copyStatus === 'failed' ? 'Copy failed' : 'Copy analysis JSON'}
            </button>
            <button type="button" className={secondary} disabled={test.phase !== 'running'} onClick={test.resetBaseline}>
              <Crosshair className="h-4 w-4" aria-hidden /> Recalibrate baseline
            </button>
            <button type="button" className={danger} onClick={onStopCamera}>
              <Square className="h-4 w-4" aria-hidden /> Stop camera
            </button>
          </>
        ) : (
          <button type="button" className={primary} onClick={() => camera.start(source)}>
            <Video className="h-4 w-4" aria-hidden /> {camera.status === 'error' ? 'Retry camera' : 'Start camera'}
          </button>
        )}
        <span className="sr-only" role="status" aria-live="polite">
          {test.copyStatus === 'copied' ? 'Analysis JSON copied' : test.copyStatus === 'failed' ? 'Copy failed' : ''}
        </span>
      </div>
    </div>
  );
}
