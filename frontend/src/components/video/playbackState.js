export function playbackStatus(status, running = false) {
  if (status === 'DONE') return 'FINISHED';
  if (status === 'ONLINE' || status === 'STARTING') return 'PROCESSING';
  if (['FINISHED', 'ERROR', 'PROCESSING', 'STOPPING'].includes(status)) return status;
  return running ? 'PROCESSING' : 'STOPPED';
}

export function playbackPlaceholder(hasSource, status, positionSeconds = 0) {
  if (!hasSource) return 'Pick a video above and press Process video';
  if (status === 'FINISHED') return 'Finished — press Process video to run it again';
  if (status === 'ERROR') return 'The source stopped with an error';
  if (positionSeconds > 0) {
    const clock = `${String(Math.floor(positionSeconds / 60)).padStart(2, '0')}:${String(Math.floor(positionSeconds % 60)).padStart(2, '0')}`;
    return `Stopped at ${clock} — press Start to continue or Process video to run from the beginning`;
  }
  return 'Stopped — pick a video above and press Process video';
}

const clock = (seconds) => `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`;

export function playbackProgress(status) {
  const total = Number(status.frames_total || 0);
  const fps = Number(status.source_fps || status.native_fps || 0);
  if (total <= 0) return null;
  const current = Math.min(total, Number(status.frames_read || 0));
  const percent = Math.min(100, Math.round(100 * current / total));
  return { percent, label: fps > 0 ? `${clock(current / fps)} / ${clock(total / fps)} · ${percent}%` : `${current} / ${total} frames · ${percent}%` };
}
