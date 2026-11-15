import { useCallback, useEffect, useRef, useState } from 'react';
import { controlRoomReplay, deleteRoomReplay, getRoomReplay, getRoomReplayFrame, startRoomReplay, uploadRoomVideo } from '../api/vaultRoom.js';
import { describeError } from '../../../utils/errors.js';
import { readReplayContext, restoredReplay, saveReplayContext } from '../utils/replayStorage.js';

const ACTIVE = ['starting', 'processing', 'paused'];
const message = (error) => error?.response ? describeError(error).message : error?.message || 'Video replay could not be completed.';

/** Owns only file replay state. No live camera, room state, or production alert mutation. */
export default function useVaultRoomReplay(profileId, configurationReady = true) {
  const [restored] = useState(readReplayContext);
  const [enabled, setEnabled] = useState(false);
  const [file, setFile] = useState(null);
  const [localUrl, setLocalUrl] = useState('');
  const [duration, setDuration] = useState(null);
  const [session, setSession] = useState(() => restoredReplay(restored));
  const [sourceId, setSourceId] = useState(restored?.sourceId || null);
  const [prepared, setPrepared] = useState(null);
  const preparedRef = useRef(null);
  const fileRef = useRef(null);
  const [previewingFile, setPreviewingFile] = useState(false);
  const [notice, setNotice] = useState('');
  const [frameUrl, setFrameUrl] = useState('');
  const [showPoseDebug, setShowPoseDebug] = useState(false);
  const togglePoseDebug = useCallback((value) => { pollRevision.current += 1; setFrameUrl(''); setShowPoseDebug(value); }, []);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [requiredPersons, setRequiredPersons] = useState(2);
  const [clearedEvents, setClearedEvents] = useState(new Set());
  const idRef = useRef(restored?.sessionId || null);
  const generation = useRef(0);
  const requestRef = useRef(null);
  const actionBusy = useRef(false);
  const pollRevision = useRef(0);

  const detach = useCallback(() => {
    generation.current += 1;
    pollRevision.current += 1;
    requestRef.current?.abort();
  }, []);

  // Navigation releases browser requests, never the worker or durable history.
  useEffect(() => () => { detach(); }, [detach]);
  useEffect(() => {
    if (!file) { setLocalUrl(''); return undefined; }
    const url = URL.createObjectURL(file); setLocalUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);
  useEffect(() => () => { if (frameUrl) URL.revokeObjectURL(frameUrl); }, [frameUrl]);

  const select = useCallback((value) => setEnabled(value), []);

  const chooseFile = useCallback(async (nextFile) => {
    if (!nextFile) return;
    if (!/\.(mp4|avi|mov|mkv|webm)$/i.test(nextFile.name)) {
      setError('Choose an MP4, AVI, MOV, MKV, or WebM video.'); return;
    }
    if (actionBusy.current) return;
    const candidate = preparedRef.current; preparedRef.current = null; setPrepared(null);
    if (candidate) deleteRoomReplay(candidate.session_id).catch(() => {});
    fileRef.current = nextFile;
    setFile(nextFile); setDuration(null); setPreviewingFile(true); setError(''); setUploadProgress(0);
    // Keep the committed replay and its events until a new start succeeds.
  }, []);

  const prepare = useCallback(async () => {
    if (!file || actionBusy.current) return null;
    if (preparedRef.current) return preparedRef.current;
    actionBusy.current = true; setBusy(true); setError('');
    const current = generation.current;
    const controller = new AbortController(); requestRef.current = controller;
    let uploaded;
    try {
      uploaded = await uploadRoomVideo(file, controller.signal, (event) => {
        if (generation.current === current) setUploadProgress(Math.round(event.loaded / (event.total || file.size) * 100));
      });
      if (generation.current !== current || fileRef.current !== file) { await deleteRoomReplay(uploaded.session_id); return; }
      setDuration(uploaded.metadata.duration);
      preparedRef.current = uploaded; setPrepared(uploaded); return uploaded;
    } catch (err) {
      if (generation.current === current) {
        setError(message(err));
        if (uploaded) await deleteRoomReplay(uploaded.session_id).catch(() => {});
      }
    } finally { actionBusy.current = false; setBusy(false); }
    return null;
  }, [file]);

  const process = useCallback(async () => {
    if (!file || actionBusy.current || !configurationReady) return;
    const uploaded = await prepare();
    if (!uploaded || preparedRef.current?.session_id !== uploaded.session_id) return;
    const current = generation.current;
    const controller = new AbortController(); requestRef.current = controller;
    actionBusy.current = true; setBusy(true); setError('');
    pollRevision.current += 1;
    try {
      const started = await startRoomReplay(uploaded.session_id, requiredPersons, controller.signal, profileId);
      pollRevision.current += 1;
      if (generation.current === current) {
        const previousId = idRef.current;
        generation.current += 1;
        idRef.current = started.session_id;
        saveReplayContext({ sessionId: started.session_id, sourceId: started.session_id, profileId });
        setSourceId(started.session_id); setSession(started); setFrameUrl('');
        preparedRef.current = null; setPrepared(null); setPreviewingFile(false);
        setShowPoseDebug(false); setClearedEvents(new Set()); setNotice('');
        // Only a successful explicit new start retires the previous temporary worker.
        // DELETE does not remove its PostgreSQL activities or evidence.
        if (previousId && previousId !== started.session_id) deleteRoomReplay(previousId).catch(() => {});
      }
    } catch (err) { if (generation.current === current) setError(message(err)); }
    finally { actionBusy.current = false; setBusy(false); }
  }, [file, requiredPersons, prepare, profileId, configurationReady]);

  const pollingMode = ACTIVE.includes(session?.status) || session?.finalized === false && session?.status !== 'uploaded' ? 'active' : session?.status || 'empty';

  useEffect(() => {
    const id = session?.session_id;
    if (!id || !enabled) return undefined;
    const current = generation.current;
    let disposed = false, timer, sequence = -1;
    const controller = new AbortController();
    const poll = async () => {
      if (actionBusy.current) { timer = window.setTimeout(poll, 200); return; }
      const revision = pollRevision.current;
      try {
        const next = await getRoomReplay(id, controller.signal);
        if (disposed || generation.current !== current) return;
        if (revision !== pollRevision.current) { timer = window.setTimeout(poll, 200); return; }
        setSession(next);
        setNotice(''); setError(next.error || '');
        if (session?.status === 'restoring') setRequiredPersons(next.state?.required_persons || 2);
        let url, framePending = false;
        if (next.frame_sequence > 0 && next.frame_sequence !== sequence) {
          try {
            const blob = await getRoomReplayFrame(id, controller.signal, showPoseDebug);
            framePending = !blob;
            if (blob) { url = URL.createObjectURL(blob); sequence = next.frame_sequence; if (!next.error) setError(''); }
          } catch (frameError) {
            framePending = true;
            if (!controller.signal.aborted && !disposed && revision === pollRevision.current) setError(`Processed preview could not be retrieved. ${message(frameError)}`);
          }
        }
        if (disposed || generation.current !== current) { if (url) URL.revokeObjectURL(url); return; }
        if (revision !== pollRevision.current) { if (url) URL.revokeObjectURL(url); timer = window.setTimeout(poll, 200); return; }
        if (url) setFrameUrl(url);
        // Keep terminal replays alive while their evidence and final state are being reviewed.
        timer = window.setTimeout(poll, framePending ? 1500 : ACTIVE.includes(next.status) || next.finalized === false && next.status !== 'uploaded' ? 200 : 30000);
      } catch (err) {
        if (!disposed && generation.current === current) {
          if (err?.response?.status === 404) {
            setSession((current) => current?.session_id === id ? { ...current, status: 'unavailable', finalized: true, frame_sequence: 0 } : current);
            setFrameUrl(''); setError('');
            setNotice('The replay worker is no longer available. Saved activity events and evidence remain available.');
            timer = window.setTimeout(poll, 30000); return;
          }
          setError(message(err)); timer = window.setTimeout(poll, 1500);
        }
      }
    };
    poll();
    return () => { disposed = true; controller.abort(); window.clearTimeout(timer); };
  }, [session?.session_id, enabled, pollingMode, showPoseDebug]);

  const control = useCallback(async (action) => {
    const id = idRef.current, current = generation.current;
    if (!id || actionBusy.current) return;
    actionBusy.current = true; setBusy(true);
    pollRevision.current += 1;
    try {
      const next = await controlRoomReplay(id, action);
      pollRevision.current += 1;
      if (generation.current === current) { setSession(next); setError(next.error || ''); return next; }
    } catch (err) { if (generation.current === current) setError(message(err)); }
    finally { actionBusy.current = false; setBusy(false); }
  }, []);

  const pauseForEditing = async () => {
    if (session?.status === 'processing') {
      const next = await control('pause');
      if (next?.status !== 'paused') throw new Error('Pause replay processing before editing regions.');
    }
    if (session?.status === 'starting' || busy) throw new Error('Wait for the video operation to finish.');
  };

  const events = (session?.events || []).filter((event) => !clearedEvents.has(event.id));
  const room = {
    replay: session || { alerts: [], status: file ? 'ready' : 'empty' },
    roomState: { state: 'IDLE', door: 'LOCKED', employees: [], feed: 'NONE', test_mode: true,
      required_persons: requiredPersons, expected_persons: requiredPersons, ...session?.state, replay_mode: true },
    events, alertEvents: [], connection: 'live', countdownProgress: 100, closeSummary: null,
    clearEvents: () => setClearedEvents(new Set((session?.events || []).map((event) => event.id))),
  };
  return { enabled, select, file, localUrl, duration: previewingFile ? duration : session?.metadata?.duration ?? duration,
    metadata: previewingFile ? prepared?.metadata : session?.metadata, setDuration, session, sourceId, frameUrl, previewingFile,
    showPoseDebug, togglePoseDebug, error, notice, busy,
    uploadProgress, requiredPersons, setRequiredPersons, chooseFile, prepare, process, control, room,
    active: ACTIVE.includes(session?.status), pauseForEditing };
}
