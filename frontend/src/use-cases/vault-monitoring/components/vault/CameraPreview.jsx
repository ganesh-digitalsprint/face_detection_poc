import { VideoOff } from 'lucide-react';
import { resolveStreamUrl } from '../../../../api/streams.js';
import { CAMERA_KINDS } from '../../hooks/useCameraSource.js';
import ErrorMessage from '../../../../components/common/ErrorMessage.jsx';

const FRAME_CLASSES = {
  default: 'aspect-video rounded-lg bg-slate-900',
  // Vault stage: tall, dark ground; overlays are positioned over it by `children`.
  stage: 'min-h-[360px] rounded-xl bg-[#0B1224] lg:min-h-[560px]',
  room: 'min-h-[560px] rounded-xl bg-[#0B1224]',
};

/**
 * Renders the active source. Frames for verification are read from these elements by the hook.
 * `children` are drawn above the video (face guide, prompts) and never affect captured frames.
 */
export default function CameraPreview({
  camera,
  errorHint = 'Unable to continue until the camera is available.',
  variant = 'default',
  children,
}) {
  const { kind, status, error, cctvSession, videoRef, imgRef } = camera;
  const showWebcam = kind === CAMERA_KINDS.WEBCAM && status === 'ready' && !cctvSession;
  const showCctv = (kind === CAMERA_KINDS.CCTV || cctvSession) && cctvSession && status !== 'error' && status !== 'stopped';
  const fit = variant === 'stage' || variant === 'room' ? 'object-cover' : 'object-contain';
  const media = variant === 'stage' || variant === 'room' ? 'absolute inset-0' : '';

  return (
    <div className="space-y-3">
      <div className={`relative flex items-center justify-center overflow-hidden ${FRAME_CLASSES[variant]}`}>
        {/* Mirror is presentation-only: frames sent to the backend are captured from the raw
            video via canvas, so CSS transforms never reach liveness head-pose analysis. */}
        {showWebcam && (
          <video ref={videoRef} autoPlay playsInline muted className={`${media} h-full w-full -scale-x-100 ${fit}`} />
        )}
        {showCctv && (
          <img
            ref={imgRef}
            key={cctvSession.session_id}
            crossOrigin="anonymous"
            src={resolveStreamUrl(cctvSession)}
            alt={`${cctvSession.name || (kind === CAMERA_KINDS.WEBCAM ? 'Webcam' : 'CCTV camera')} live stream`}
            className={`${media} h-full w-full ${cctvSession.source_type === 'webcam' ? '-scale-x-100' : ''} ${fit}`}
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
        {children}
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
