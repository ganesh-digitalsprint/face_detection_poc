import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Pause, Play, StepBack, StepForward } from 'lucide-react';

const clock = (seconds) => {
  const tenths = Math.max(0, Math.floor((Number.isFinite(seconds) ? seconds : 0) * 10 + .0001));
  return `${Math.floor(tenths / 600)}:${String(Math.floor(tenths / 10) % 60).padStart(2, '0')}.${tenths % 10}`;
};

export default function VaultVideoScrubber({ previewRef, replay, editing, active }) {
  const [video, setVideo] = useState(null);
  const [target, setTarget] = useState(null);
  const [time, setTime] = useState(0);
  const [frameTime, setFrameTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState('');
  const attemptedFile = useRef(null);
  const fps = replay.session?.metadata?.fps;

  useEffect(() => {
    if (active && replay.enabled && replay.file && !replay.session?.metadata && !replay.busy && attemptedFile.current !== replay.file) {
      attemptedFile.current = replay.file;
      replay.prepare();
    }
  }, [active, replay.enabled, replay.file, replay.busy, replay.session?.metadata, replay.prepare]);

  useEffect(() => {
    const root = previewRef.current;
    if (!root || !active) return undefined;
    const refresh = () => {
      setTarget(root.querySelector('.room-camera-frame'));
      setVideo(replay.enabled ? root.querySelector('video') : null);
    };
    refresh();
    const observer = new MutationObserver(refresh);
    observer.observe(root, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, [previewRef, replay.enabled, replay.localUrl, active]);

  useEffect(() => {
    setTime(0); setFrameTime(0); setDuration(0); setPlaying(false); setReady(false); setError('');
    if (!video || !active) return undefined;
    let callback;
    const update = () => {
      setTime(video.currentTime || 0);
      setDuration(Number.isFinite(video.duration) ? video.duration : 0);
      setPlaying(!video.paused && !video.ended);
      setReady(video.readyState >= 2 && video.videoWidth > 0 && Number.isFinite(video.duration));
      if (!video.requestVideoFrameCallback) setFrameTime(video.currentTime || 0);
    };
    const presented = (_now, metadata) => {
      setFrameTime(metadata.mediaTime);
      callback = video.requestVideoFrameCallback(presented);
    };
    const events = ['loadedmetadata', 'loadeddata', 'durationchange', 'timeupdate', 'seeking', 'seeked', 'play', 'pause', 'ended', 'error'];
    events.forEach((event) => video.addEventListener(event, update));
    update();
    setFrameTime(video.currentTime || 0);
    if (video.requestVideoFrameCallback) callback = video.requestVideoFrameCallback(presented);
    return () => {
      events.forEach((event) => video.removeEventListener(event, update));
      if (callback != null) video.cancelVideoFrameCallback(callback);
    };
  }, [video, active]);

  const disabled = !replay.enabled || !replay.file || !ready || editing;
  const seek = (value) => {
    if (disabled) return;
    video.pause();
    const next = Math.max(0, Math.min(duration, value));
    video.currentTime = next; setTime(next);
  };
  const step = (direction) => {
    if (!Number.isFinite(fps) || fps <= 0) return;
    const index = Math.floor(video.currentTime * fps + .0001);
    seek(Math.min(Math.max(0, duration - 1 / fps), (index + direction) / fps));
  };
  const toggle = async () => {
    if (disabled) return;
    try {
      if (video.paused) { if (video.ended) video.currentTime = 0; await video.play(); }
      else video.pause();
      setError('');
    } catch { setError('This video could not be played by the browser.'); }
  };

  return <div className={`zone-video-scrubber ${disabled ? 'is-disabled' : ''}`} aria-label="Video frame controls">
    {active && replay.enabled && replay.file && target && createPortal(<span className="zone-frame-time-tag">Frame · {clock(frameTime)}</span>, target)}
    <div className="zone-scrubber-row">
      <button type="button" aria-label={playing ? 'Pause video' : 'Play video'} onClick={toggle} disabled={disabled} className="zone-scrubber-button zone-scrubber-play">{playing ? <Pause size={16} /> : <Play size={16} />}</button>
      <button type="button" aria-label="Previous frame" title="Previous frame" onClick={() => step(-1)} disabled={disabled || !fps || time <= 0} className="zone-scrubber-button"><StepBack size={17} /></button>
      <button type="button" aria-label="Next frame" title="Next frame" onClick={() => step(1)} disabled={disabled || !fps || time >= duration - 1 / fps} className="zone-scrubber-button"><StepForward size={17} /></button>
      <time className="zone-scrubber-time">{clock(time)}</time>
      <input type="range" aria-label="Video frame slider" aria-valuetext={`${clock(time)} of ${clock(duration)}`} min={0} max={duration || 1} step="any" value={Math.min(time, duration || 1)} onChange={(event) => seek(Number(event.target.value))} disabled={disabled} className="zone-frame-slider" />
      <time className="zone-scrubber-time">{clock(duration)}</time>
    </div>
    {(!replay.enabled || !replay.file) && <p className="zone-scrubber-hint">Choose a video file to scrub through frames and draw on any frame.</p>}
    {replay.enabled && replay.file && !fps && <p className="zone-scrubber-hint">{replay.busy ? 'Reading video frame information…' : 'Frame stepping will be available when video frame information is loaded.'}</p>}
    {editing && <p className="zone-scrubber-hint">Finish or cancel drawing to move to another frame.</p>}
    {error && <p role="alert" className="zone-scrubber-hint text-red-700">{error}</p>}
  </div>;
}
