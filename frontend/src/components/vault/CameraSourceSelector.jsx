import { useState } from 'react';
import { Cctv, Radio, Square, Webcam } from 'lucide-react';
import { Link } from 'react-router-dom';
import { CAMERA_KINDS } from '../../hooks/useCameraSource.js';
import Button from '../common/Button.jsx';

const tab = (active) =>
  `inline-flex items-center gap-2 rounded-md px-4 py-1.5 text-sm font-medium disabled:opacity-50 ${
    active ? 'bg-brand text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
  }`;

/** Picks and starts the camera source. New sources only need a new entry + a branch in useCameraSource. */
export default function CameraSourceSelector({ camera, disabled }) {
  const [source, setSource] = useState(CAMERA_KINDS.WEBCAM);
  const [streamIndex, setStreamIndex] = useState(0);
  const active = camera.status === 'starting' || camera.status === 'ready';

  return (
    <div className="space-y-3">
      <div role="group" aria-label="Camera source" className="flex flex-wrap items-center gap-2">
        <button type="button" className={tab(source === CAMERA_KINDS.WEBCAM)} disabled={active} aria-pressed={source === CAMERA_KINDS.WEBCAM}
          onClick={() => setSource(CAMERA_KINDS.WEBCAM)}>
          <Webcam className="h-4 w-4" aria-hidden /> Webcam
        </button>
        <button type="button" className={tab(source === CAMERA_KINDS.CCTV)} disabled={active} aria-pressed={source === CAMERA_KINDS.CCTV}
          onClick={() => setSource(CAMERA_KINDS.CCTV)}>
          <Cctv className="h-4 w-4" aria-hidden /> CCTV
        </button>
        <Link to="/live" className="ml-auto inline-flex items-center gap-1.5 text-xs text-brand hover:underline">
          <Radio className="h-3.5 w-3.5" aria-hidden /> Live Monitoring (annotated streams)
        </Link>
      </div>

      {source === CAMERA_KINDS.CCTV && (
        <div className="flex items-center gap-2 text-sm">
          <label htmlFor="stream_index" className="text-slate-600">Stream index</label>
          <input id="stream_index" type="number" min={0} value={streamIndex} disabled={active}
            onChange={(e) => setStreamIndex(Math.max(0, Number(e.target.value) || 0))}
            className="w-20 rounded-md border border-slate-300 px-2 py-1" />
        </div>
      )}

      {active ? (
        <Button variant="danger" icon={Square} disabled={disabled} onClick={camera.stop}>Stop Camera</Button>
      ) : (
        <Button icon={source === CAMERA_KINDS.CCTV ? Cctv : Webcam} loading={camera.status === 'starting'}
          onClick={() => camera.start(source, { streamIndex })}>
          {camera.status === 'error' ? 'Retry Camera' : 'Start Camera'}
        </Button>
      )}
    </div>
  );
}
