// [key, label, hint, limits] - limits mirror the server's validation; the server stays the authority.
export const COMMON_FIELDS = [
  ['processing_fps', 'Processing FPS', 'Frames analysed per second per camera. Lower = less CPU.', { min: 1, max: 60, step: 1 }],
  ['clip_pre_seconds', 'Evidence clip: seconds before', 'Recorded before the event.', { min: 0, max: 60, step: 1 }],
  ['clip_post_seconds', 'Evidence clip: seconds after', 'Recorded after the event.', { min: 0, max: 60, step: 1 }],
  ['cooldown_seconds', 'Alert cooldown (seconds)', 'A track that breaks and restarts in the same spot within this time does not raise a second event.', { min: 0, max: 300, step: 1 }],
];
export const SPECIFIC_FIELDS = [
  ['visibility_threshold', 'Concealment threshold', '0 to 1. A frame counts as "concealed" when its score reaches this. Higher = fewer alerts, more missed.', { min: 0, max: 1, step: 0.05 }],
  ['frames_to_confirm', 'Frames to confirm (N)', 'Concealed frames needed, out of the window below, before an event is raised.', { min: 1, max: 60, step: 1 }],
  ['confirm_window', 'Confirmation window (M frames)', 'The last M evaluated frames considered. At least N.', { min: 1, max: 120, step: 1 }],
  ['person_confidence', 'Person detection confidence', '0 to 1. Lower finds more people and more false detections. Needs a service restart.', { min: 0, max: 1, step: 0.05 }],
  ['entering_window_frames', 'Entering movement window (frames)', 'Movement toward the inward arrow is measured over the last N frames.', { min: 2, max: 120, step: 1 }],
  ['entering_min_displacement_px', 'Minimum inward movement (px)', 'A person must move at least this far inward to count as entering.', { min: 0, max: 1000, step: 1 }],
  ['min_head_height_px', 'Minimum head height (px)', 'Smaller heads are too small to judge: wait, never alert.', { min: 1, max: 1000, step: 1 }],
  ['min_sharpness', 'Minimum sharpness', 'Blurrier heads are skipped (variance of Laplacian).', { min: 0, max: 5000, step: 5 }],
  ['min_brightness', 'Minimum brightness', 'Darker heads are skipped (0-255).', { min: 0, max: 255, step: 1 }],
  ['max_brightness', 'Maximum brightness', 'Over-exposed heads are skipped (0-255). Above the minimum.', { min: 0, max: 255, step: 1 }],
  ['max_yaw_degrees', 'Maximum head turn (degrees)', 'A head turned away more than this is not judged: wait, never alert.', { min: 1, max: 180, step: 1 }],
];
export const CHANNELS = [['alert_dashboard', 'Dashboard'], ['alert_sms', 'SMS'], ['alert_email', 'Email'], ['alert_app', 'App notification']];
export const NUMERIC = [...COMMON_FIELDS, ...SPECIFIC_FIELDS];

/** Pure: field-level problems for the current form values. Exported for unit tests. */
export function settingsErrors(v) {
  const errors = {};
  NUMERIC.forEach(([key, , , lim]) => {
    const n = Number(v[key]);
    if (v[key] === '' || v[key] == null || Number.isNaN(n)) errors[key] = 'Enter a number.';
    else if (n < lim.min || n > lim.max) errors[key] = `Must be between ${lim.min} and ${lim.max}.`;
  });
  if (!errors.frames_to_confirm && !errors.confirm_window && Number(v.frames_to_confirm) > Number(v.confirm_window)) {
    errors.frames_to_confirm = 'Cannot be larger than the confirmation window.';
  }
  if (!errors.min_brightness && !errors.max_brightness && Number(v.min_brightness) >= Number(v.max_brightness)) {
    errors.min_brightness = 'Must be below the maximum brightness.';
  }
  return errors;
}

