/** Processed footage seconds only. Never infer progress from receipt or processing time. */
export function processedVideoTimestamp({ job, monitoring } = {}) {
  const reported = { ...(job?.monitoring ?? {}), ...(monitoring ?? {}) };
  const valid = (value) => Number.isFinite(value) && value >= 0 ? value : null;
  if (reported.video_timestamp != null) return valid(reported.video_timestamp);
  // frame_index is a zero-based source frame index, not processed frame count.
  if (reported.frame_index != null) {
    const index = valid(reported.frame_index);
    const fps = job?.fps;
    return index != null && Number.isFinite(fps) && fps > 0 ? index / fps : null;
  }
  if (Object.hasOwn(reported, 'video_timestamp')) return null;
  return valid(job?.video_time_seconds ?? job?.progress_seconds);
}

export const videoIsFinal = (status) => ['COMPLETED', 'FAILED', 'CANCELLED'].includes(status);
