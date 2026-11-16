import { playbackProgress, playbackStatus } from './playbackState.js';

export function StopButton({ status, running, stopping, onStop }) {
  const busy = stopping || status === 'STOPPING';
  const active = (running || status === 'PROCESSING') && !busy;
  return <button type="button" className={`bx-btn bx-btn-sm${active ? ' bx-btn-primary' : ''}`}
    disabled={!active} onClick={onStop} aria-label="Stop processing">
    {busy ? 'Stopping…' : 'Stop'}
  </button>;
}

export function PlaybackBadge({ status, running }) {
  const label = playbackStatus(status, running);
  return <div className="bx-live-badge" role="status" style={label === 'FINISHED' ? { color: '#16a34a' } : undefined}>
    <span className={label === 'PROCESSING' ? 'bx-dot-live' : 'bx-dot-off'} /> {label}
  </div>;
}

export function PlaybackProgress({ status }) {
  const value = playbackProgress(status);
  if (!value) return null;
  return <div style={{ padding: '4px 16px 10px' }}>
    <div className="bx-bar-track" role="progressbar" aria-valuenow={value.percent} aria-valuemin={0} aria-valuemax={100} aria-label="Video progress">
      <div className="bx-bar-fill" style={{ width: `${value.percent}%` }} />
    </div>
    <div className="bx-muted" style={{ fontSize: 12, marginTop: 4 }}>{value.label}</div>
  </div>;
}
