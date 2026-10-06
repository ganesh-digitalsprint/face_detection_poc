import { useCallback, useEffect, useRef, useState } from 'react';
import { startCCTV, stopStream } from '../api/streams.js';
import { describeError } from '../utils/errors.js';

const MAX_FRAME_WIDTH = 640;
const JPEG_QUALITY = 0.85;

export const CAMERA_KINDS = { WEBCAM: 'webcam', CCTV: 'cctv' };

function mediaErrorMessage(err) {
  if (err?.name === 'NotAllowedError') return 'Camera permission was denied.';
  if (err?.name === 'NotFoundError') return 'No camera was found on this device.';
  return 'The camera could not be started.';
}

function toJpegBlob(source, width, height) {
  const scale = Math.min(1, MAX_FRAME_WIDTH / width);
  const canvas = document.createElement('canvas');
  canvas.width = Math.round(width * scale);
  canvas.height = Math.round(height * scale);
  canvas.getContext('2d').drawImage(source, 0, 0, canvas.width, canvas.height);
  return new Promise((resolve, reject) => {
    try {
      canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error('Frame capture failed.'))), 'image/jpeg', JPEG_QUALITY);
    } catch {
      reject(new Error('This camera source does not allow frame capture (cross-origin).'));
    }
  });
}

/**
 * One camera abstraction for Vault Access. Whatever the source, it exposes
 * `captureFrame()` so verification logic never depends on where frames come from.
 *  - webcam: browser getUserMedia rendered in a <video>
 *  - cctv:   backend MJPEG stream rendered in an <img crossOrigin>, frames read via canvas
 */
export default function useCameraSource() {
  const videoRef = useRef(null);
  const imgRef = useRef(null);
  const streamRef = useRef(null);
  const sessionRef = useRef(null);
  const [kind, setKind] = useState(null);
  const [status, setStatus] = useState('idle'); // idle | starting | ready | error
  const [error, setError] = useState(null);
  const [cctvSession, setCctvSession] = useState(null);

  const release = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    if (sessionRef.current) stopStream(sessionRef.current.session_id).catch(() => {});
    sessionRef.current = null;
    setCctvSession(null);
  }, []);

  const stop = useCallback(() => {
    release();
    setKind(null);
    setStatus('idle');
    setError(null);
  }, [release]);

  const start = useCallback(async (nextKind, { streamIndex = 0 } = {}) => {
    release();
    setKind(nextKind);
    setStatus('starting');
    setError(null);
    try {
      if (nextKind === CAMERA_KINDS.WEBCAM) {
        if (!navigator.mediaDevices?.getUserMedia) throw new Error('unsupported');
        const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user' }, audio: false });
        streamRef.current = stream;
        setStatus('ready'); // <video> attaches the stream via the effect below
      } else {
        const session = await startCCTV(streamIndex);
        sessionRef.current = session;
        setCctvSession(session);
      }
    } catch (err) {
      release();
      setStatus('error');
      setError(
        nextKind === CAMERA_KINDS.WEBCAM
          ? mediaErrorMessage(err)
          : describeError(err, { 404: 'Configured CCTV stream not found.', 503: 'The CCTV stream could not be opened.' }).message,
      );
    }
  }, [release]);

  // Attach the webcam stream once the <video> element exists.
  useEffect(() => {
    if (kind === CAMERA_KINDS.WEBCAM && status === 'ready' && videoRef.current) {
      videoRef.current.srcObject = streamRef.current;
    }
  }, [kind, status]);

  const markCctvReady = useCallback(() => setStatus('ready'), []);
  const markCctvFailed = useCallback(() => {
    release();
    setStatus('error');
    setError('The CCTV stream failed to load.');
  }, [release]);

  const captureFrame = useCallback(async () => {
    if (kind === CAMERA_KINDS.WEBCAM) {
      const video = videoRef.current;
      if (!video || video.readyState < 2 || !video.videoWidth) throw new Error('Camera is not ready yet.');
      return toJpegBlob(video, video.videoWidth, video.videoHeight);
    }
    const img = imgRef.current;
    if (!img || !img.naturalWidth) throw new Error('CCTV stream is not ready yet.');
    return toJpegBlob(img, img.naturalWidth, img.naturalHeight);
  }, [kind]);

  useEffect(() => release, [release]);

  return {
    kind, status, error, cctvSession, videoRef, imgRef,
    start, stop, captureFrame, markCctvReady, markCctvFailed,
  };
}
