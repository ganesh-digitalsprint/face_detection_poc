import { useEffect, useState } from 'react';
import { Camera, Cctv, Link2, Square, Webcam } from 'lucide-react';
import useCameraSource, { CAMERA_KINDS } from '../../hooks/useCameraSource.js';
import useCctvCameras from '../../hooks/useCctvCameras.js';
import Button from '../common/Button.jsx';
import ErrorMessage from '../common/ErrorMessage.jsx';
import CameraPreview from '../vault/CameraPreview.jsx';
import CapturedGallery from './CapturedGallery.jsx';

const tab = (active) =>
  `inline-flex items-center gap-2 rounded-md px-4 py-1.5 text-sm font-medium disabled:opacity-50 ${
    active ? 'bg-brand text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
  }`;

const STATUS_TEXT = {
  idle: 'Camera is off',
  starting: 'Connecting...',
  ready: 'Connected',
  error: 'Connection failed',
};

/**
 * Webcam / CCTV frame capture for enrollment. Frames are only collected here;
 * the parent submits them explicitly. Unmounting releases every track and stream session.
 */
export default function VideoEnrollmentPanel({ source, onSourceChange, frames, maxFrames, disabled, onCapture, onRemove }) {
  const camera = useCameraSource();
  const [cctvIndex, setCctvIndex] = useState('');
  const [captureError, setCaptureError] = useState(null);
  const [capturing, setCapturing] = useState(false);
  const isCctv = source === CAMERA_KINDS.CCTV;
  const cctv = useCctvCameras(isCctv);
  const sourceFrames = frames[source] ?? [];
  const live = camera.status === 'ready';
  const busy = camera.status === 'starting';

  // Stop streaming while an enrollment request is in flight or finished; captured blobs are kept.
  const { stop } = camera;
  useEffect(() => { if (disabled) stop(); }, [disabled, stop]);

  const chooseSource = (next) => {
    if (next === source) return;
    camera.stop(); // release the previous webcam stream / CCTV session first
    setCaptureError(null);
    onSourceChange(next);
  };

  const capture = async () => {
    setCaptureError(null);
    setCapturing(true);
    try {
      onCapture(source, await camera.captureFrame());
    } catch (err) {
      setCaptureError(err.message);
    } finally {
      setCapturing(false);
    }
  };

  const connect = () => camera.start(source, { streamIndex: Number(cctvIndex) });
  const full = sourceFrames.length >= maxFrames;
  const noCameras = isCctv && cctv.cameras?.length === 0;

  return (
    <div className="space-y-4">
      <div role="group" aria-label="Video source" className="flex flex-wrap gap-2">
        <button type="button" className={tab(!isCctv)} aria-pressed={!isCctv} disabled={disabled}
          onClick={() => chooseSource(CAMERA_KINDS.WEBCAM)}>
          <Webcam className="h-4 w-4" aria-hidden /> Webcam
        </button>
        <button type="button" className={tab(isCctv)} aria-pressed={isCctv} disabled={disabled}
          onClick={() => chooseSource(CAMERA_KINDS.CCTV)}>
          <Cctv className="h-4 w-4" aria-hidden /> CCTV Camera
        </button>
      </div>

      {isCctv && (
        <div className="max-w-xs">
          <label htmlFor="enroll_cctv" className="mb-1 block text-sm font-medium text-slate-700">Select CCTV Camera</label>
          <select
            id="enroll_cctv"
            value={cctvIndex}
            disabled={disabled || live || busy || !cctv.cameras?.length}
            onChange={(e) => setCctvIndex(e.target.value)}
            className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm"
          >
            <option value="" disabled>{cctv.loading ? 'Loading cameras...' : 'Choose a camera'}</option>
            {(cctv.cameras ?? []).map((c) => (
              <option key={c.stream_index} value={c.stream_index}>{c.label}</option>
            ))}
          </select>
          {noCameras && (
            <p className="mt-2 text-sm text-slate-500">No CCTV cameras are configured on the server.</p>
          )}
          <ErrorMessage error={cctv.error} />
        </div>
      )}

      <CameraPreview camera={camera} errorHint="Fix the camera issue and try again." />
      <p role="status" className="text-xs text-slate-500">Status: {STATUS_TEXT[camera.status]}</p>
      <ErrorMessage error={captureError} />

      <div className="flex flex-wrap gap-3">
        {isCctv ? (
          <Button icon={Link2} loading={busy} disabled={disabled || live || cctvIndex === ''} onClick={connect}>
            {camera.status === 'error' ? 'Retry Connection' : 'Connect Camera'}
          </Button>
        ) : (
          <Button icon={Webcam} loading={busy} disabled={disabled || live} onClick={connect}>
            {camera.status === 'error' ? 'Retry Camera' : 'Start Camera'}
          </Button>
        )}
        <Button icon={Camera} loading={capturing} disabled={disabled || !live || full} onClick={capture}>
          Capture Frame
        </Button>
        <Button variant="danger" icon={Square} disabled={disabled || (!live && !busy)} onClick={camera.stop}>
          {isCctv ? 'Stop Capture' : 'Stop Camera'}
        </Button>
      </div>
      {full && (
        <p className="text-xs text-amber-700">
          Maximum of {maxFrames} images per enrollment reached. Remove one to capture another.
        </p>
      )}

      <CapturedGallery
        frames={sourceFrames}
        max={maxFrames}
        disabled={disabled}
        onRemove={(id) => onRemove(source, id)}
      />
    </div>
  );
}
