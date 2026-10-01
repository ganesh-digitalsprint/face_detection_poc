import { useCallback, useEffect, useRef, useState } from 'react';
import { stopStream } from '../api/streams.js';
import { describeError } from '../utils/errors.js';

const START_ERRORS = {
  404: 'Configured camera not found.',
  503: 'Camera/CCTV stream could not be started.',
};

/**
 * Start/stop lifecycle shared by webcam and CCTV panels.
 * `start` is the API call returning { session_id, stream_url, stop_url }.
 */
export default function useStreamSession(start) {
  const [session, setSession] = useState(null);
  const [phase, setPhase] = useState('idle'); // idle | starting | live | stopping | stopped
  const [error, setError] = useState(null);
  const busy = useRef(false);
  const sessionRef = useRef(null);
  sessionRef.current = session;

  const begin = useCallback(async (...args) => {
    if (busy.current) return;
    busy.current = true;
    setPhase('starting');
    setError(null);
    try {
      setSession(await start(...args));
      setPhase('live');
    } catch (err) {
      setError(describeError(err, START_ERRORS));
      setPhase('idle');
    } finally {
      busy.current = false;
    }
  }, [start]);

  const end = useCallback(async () => {
    const current = sessionRef.current;
    if (!current || busy.current) return;
    busy.current = true;
    setPhase('stopping');
    setError(null);
    try {
      await stopStream(current.session_id);
      setSession(null); // clear viewer so the browser stops requesting the MJPEG URL
      setPhase('stopped');
    } catch (err) {
      if (err?.response?.status === 404) {
        // Backend already ended the session (e.g. stream client disconnected).
        setSession(null);
        setPhase('stopped');
      } else {
        setError(describeError(err));
        setPhase('live');
      }
    } finally {
      busy.current = false;
    }
  }, []);

  // Best-effort stop when leaving the page so the camera is released.
  useEffect(() => () => {
    if (sessionRef.current) stopStream(sessionRef.current.session_id).catch(() => {});
  }, []);

  return { session, phase, error, begin, end };
}
