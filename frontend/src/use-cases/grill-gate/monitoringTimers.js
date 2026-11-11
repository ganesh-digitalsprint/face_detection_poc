const isoTime = (value) => {
  if (typeof value !== 'string' || !value) return NaN;
  return Date.parse(/(Z|[+-]\d{2}:?\d{2})$/i.test(value) ? value : `${value}Z`);
};

export function timerTimestamp(value, timebase = 'wall') {
  if (Number.isFinite(value)) return value;
  const timestamp = timebase === 'wall' ? isoTime(value) : NaN;
  return Number.isFinite(timestamp) ? timestamp : null;
}

export function elapsedSeconds(startAt, now) {
  const start = timerTimestamp(startAt);
  return Number.isFinite(start) && Number.isFinite(now) ? Math.max(0, (now - start) / 1000) : null;
}

export function latestFullyOpenTimestamp(transitions, timebase = 'wall') {
  for (let index = (transitions?.length ?? 0) - 1; index >= 0; index -= 1) {
    const transition = transitions[index];
    if (transition.toState !== 'FULLY_OPEN' && transition.to_state !== 'FULLY_OPEN') continue;
    if (transition.timebase !== timebase) return null;
    const value = transition.timerAt ?? transition.at ?? transition.video_time_seconds;
    return Number.isFinite(transition.video_time_seconds) && timebase === 'video'
      ? transition.video_time_seconds * 1000 : timerTimestamp(value);
  }
  return null;
}

export function latestConfirmedOpenTimestamp(transitions, timebase = 'wall') {
  if (!Array.isArray(transitions) || !transitions.length) return null;
  const latest = transitions[transitions.length - 1];
  const destination = latest.toState ?? latest.to_state;
  if (destination !== 'FULLY_OPEN') return null;
  if (timebase === 'video') {
    return Number.isFinite(latest.video_time_seconds) ? latest.video_time_seconds * 1000 : null;
  }
  const timestamp = timerTimestamp(latest.at, 'wall');
  return Number.isFinite(timestamp) ? timestamp : null;
}

export function crossingTimestamp(events, timebase = 'wall') {
  let newest = null;
  for (const event of events ?? []) {
    const value = timebase === 'video'
      ? (Number.isFinite(event.video_time_seconds) ? event.video_time_seconds * 1000 : NaN)
      : isoTime(event.occurred_at);
    if (Number.isFinite(value) && (newest == null || value > newest)) newest = value;
  }
  return newest;
}

export function openWithoutCrossingSeconds({ gateState, openedAt, lastCrossingAt, now }) {
  if (gateState !== 'FULLY_OPEN' || !Number.isFinite(openedAt) || !Number.isFinite(now)) return null;
  const start = Number.isFinite(lastCrossingAt) && lastCrossingAt > openedAt ? lastCrossingAt : openedAt;
  return Math.max(0, (now - start) / 1000);
}

export function projectVideoClock(videoSeconds, receivedAt, now, processing) {
  if (!Number.isFinite(videoSeconds)) return null;
  const base = videoSeconds * 1000;
  return processing && Number.isFinite(receivedAt) && Number.isFinite(now)
    ? base + Math.max(0, now - receivedAt) : base;
}

/** Keep a processing media clock from moving backward when a new poll trails its 1x projection. */
export function advanceVideoClock(previousBase, previousReceivedAt, videoSeconds, receivedAt) {
  const projectedPrevious = Number.isFinite(previousBase) && Number.isFinite(previousReceivedAt)
    ? previousBase + Math.max(0, receivedAt - previousReceivedAt) : null;
  const reported = Number.isFinite(videoSeconds) ? videoSeconds * 1000 : null;
  if (reported == null) return projectedPrevious;
  return projectedPrevious == null ? reported : Math.max(reported, projectedPrevious);
}
