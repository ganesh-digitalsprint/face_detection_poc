import { useCallback, useEffect, useRef, useState } from 'react';
import { API_BASE_URL } from '../api/client.js';
import { getRoomCameraSession, startRoomRtspCamera, stopRoomCameraSession } from '../api/vaultRoom.js';

const INITIAL = { kind: null, status: 'idle', error: null, cctvSession: null, tracking: false, name: null };
const absoluteStreamUrl = (url) => `${String(API_BASE_URL || '').replace(/\/$/, '')}${url}`;

export default function useVaultRoomCamera() {
  const videoRef = useRef(null);
  const imgRef = useRef(null);
  const sessionRef = useRef(null);
  const streamRef = useRef(null);
  const operationRef = useRef(0);
  const connectInFlightRef = useRef(false);
  const mountedRef = useRef(true);
  const [camera, setCamera] = useState(INITIAL);

  const releaseLocalStream = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
  }, []);

  const stop = useCallback(async () => {
    operationRef.current += 1;
    releaseLocalStream();
    const session = sessionRef.current;
    if (session) {
      setCamera((current) => ({ ...current, status: 'stopping', error: null }));
      try {
        await stopRoomCameraSession(session.session_id);
      } catch (error) {
        setCamera((current) => ({ ...current, status: 'error', error: error?.message || 'Could not stop the camera session.' }));
        return false;
      }
    }
    sessionRef.current = null;
    setCamera(INITIAL);
    return true;
  }, [releaseLocalStream]);

  const startWebcam = useCallback(async (name = 'Vault Room Camera') => {
    if (connectInFlightRef.current) return;
    connectInFlightRef.current = true;
    let operation;
    try {
      if (!await stop()) return;
      operation = operationRef.current;
      setCamera({ ...INITIAL, kind: 'webcam', name, status: 'starting' });
      if (!navigator.mediaDevices?.getUserMedia) throw new Error('Camera access requires localhost or a secure HTTPS connection.');
      const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user' }, audio: false });
      if (!mountedRef.current || operation !== operationRef.current) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      streamRef.current = stream;
      setCamera({ ...INITIAL, kind: 'webcam', name, status: 'ready' });
    } catch (error) {
      if (!mountedRef.current || operation !== undefined && operation !== operationRef.current) return;
      releaseLocalStream();
      const message = error?.name === 'NotAllowedError' ? 'Camera permission was denied.'
        : error?.name === 'NotFoundError' ? 'No webcam was found on this device.'
          : error?.message || 'The webcam could not be started.';
      setCamera({ ...INITIAL, kind: 'webcam', name, status: 'error', error: message });
    } finally {
      connectInFlightRef.current = false;
    }
  }, [releaseLocalStream, stop]);

  const startRtsp = useCallback(async (name, url) => {
    if (connectInFlightRef.current) return;
    connectInFlightRef.current = true;
    let operation;
    try {
      if (!await stop()) return;
      operation = operationRef.current;
      setCamera({ ...INITIAL, kind: 'cctv', name, status: 'connecting' });
      const session = await startRoomRtspCamera(name, url);
      if (!mountedRef.current || operation !== operationRef.current) {
        await stopRoomCameraSession(session.session_id).catch(() => {});
        return;
      }
      const attached = { ...session, stream_url: absoluteStreamUrl(session.stream_url) };
      sessionRef.current = attached;
      setCamera({ ...INITIAL, kind: 'cctv', name, status: session.status, error: null, cctvSession: attached, tracking: true });
    } catch (error) {
      if (!mountedRef.current || operation !== undefined && operation !== operationRef.current) return;
      setCamera({ ...INITIAL, kind: 'cctv', name, status: 'error', error: error?.message || 'The camera could not be connected.' });
    } finally {
      connectInFlightRef.current = false;
    }
  }, [stop]);

  useEffect(() => {
    if (camera.kind !== 'webcam' || camera.status !== 'ready' || !videoRef.current || !streamRef.current) return;
    videoRef.current.srcObject = streamRef.current;
  }, [camera.kind, camera.status]);

  useEffect(() => {
    const sessionId = camera.cctvSession?.session_id;
    if (!sessionId || ['error', 'stopping'].includes(camera.status)) return undefined;
    let active = true;
    const poll = async () => {
      try {
        const result = await getRoomCameraSession(sessionId);
        if (!active) return;
        const nextStatus = result.status === 'failed' ? 'error' : result.status;
        setCamera((current) => ({ ...current, status: nextStatus,
          error: result.status === 'failed' ? (result.error || 'The camera connection failed.') : null,
          cctvSession: current.cctvSession ? { ...current.cctvSession, ...result,
            stream_url: absoluteStreamUrl(result.stream_url) } : current.cctvSession }));
      } catch (error) {
        if (active) setCamera((current) => ({ ...current, status: 'error', error: error?.message || 'Could not read camera status.' }));
      }
    };
    poll();
    const interval = ['streaming', 'connected'].includes(camera.status) ? 5000 : 1000;
    const timer = window.setInterval(poll, interval);
    return () => { active = false; window.clearInterval(timer); };
  }, [camera.cctvSession?.session_id, camera.status]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      releaseLocalStream();
      const session = sessionRef.current;
      sessionRef.current = null;
      if (session) stopRoomCameraSession(session.session_id).catch(() => {});
    };
  }, [releaseLocalStream]);

  const markCctvReady = useCallback(() => {}, []); // Status remains backend-authoritative.
  const markCctvFailed = useCallback(() => setCamera((current) => ({ ...current, status: 'error', error: 'The live camera preview could not be loaded.' })), []);
  return { ...camera, videoRef, imgRef, stop, startWebcam, startRtsp, markCctvReady, markCctvFailed };
}
