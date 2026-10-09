import { VideoOff } from 'lucide-react';
import { resolveStreamUrl } from '../../api/streams.js';
import { CAMERA_KINDS } from '../../hooks/useCameraSource.js';
import ErrorMessage from '../common/ErrorMessage.jsx';

/** Renders the active source. Frames for verification are read from these elements by the hook. */
export default function CameraPreview({ camera, errorHint = 'Unable to continue until the camera is available.' }) {
  const { kind, status, error, cctvSession, videoRef, imgRef } = camera;
  const showWebcam = kind === CAMERA_KINDS.WEBCAM && status === 'ready';
  const showCctv = kind === CAMERA_KINDS.CCTV && cctvSession;

  return (
    <div className="space-y-3">
      <div className="flex aspect-video items-center justify-center overflow-hidden rounded-lg bg-slate-900">
        {/* Mirror is presentation-only: frames sent to the backend are captured from the raw
            video via canvas, so CSS transforms never reach liveness head-pose analysis. */}
        {showWebcam && (
          <video ref={videoRef} autoPlay playsInline muted className="h-full w-full -scale-x-100 object-contain" />
        )}
        {showCctv && (
          <img
            ref={imgRef}
            key={cctvSession.session_id}
            crossOrigin="anonymous"
            src={resolveStreamUrl(cctvSession)}
            alt="CCTV camera stream"
            className="h-full w-full object-contain"
            onLoad={camera.markCctvReady}
            onError={camera.markCctvFailed}
          />
        )}
        {!showWebcam && !showCctv && (
          <div className="flex flex-col items-center gap-2 text-slate-400">
            <VideoOff className="h-8 w-8" aria-hidden />
            <p className="text-sm">{status === 'starting' ? 'Starting camera...' : 'Camera is off'}</p>
          </div>
        )}
      </div>
      {status === 'error' && (
        <div className="space-y-1">
          <p className="text-sm font-semibold text-red-700">Camera unavailable</p>
          <ErrorMessage error={error} />
          <p className="text-xs text-slate-500">{errorHint}</p>
        </div>
      )}
    </div>
  );
}
