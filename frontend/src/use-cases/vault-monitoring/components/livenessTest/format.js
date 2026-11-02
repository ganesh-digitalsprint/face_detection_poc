// Display helpers for the Liveness Test Lab. No thresholds live here: they come from the backend.

export const DETECTOR_LABELS = { mediapipe: 'MediaPipe', deepface: 'DeepFace', both: 'Compare' };
export const DETECTOR_COLORS = { mediapipe: '#5EE6A8', deepface: '#FFB454' };
export const SLOW_DETECTOR_MS = 300;
export const POSE_GAUGE_RANGE = 0.3;

// Button label per backend challenge code. Only codes in `available_challenges` are shown.
export const CHALLENGE_LABELS = {
  TURN_LEFT: 'Left',
  TURN_RIGHT: 'Right',
  LOOK_UP: 'Up',
  LOOK_DOWN: 'Down',
  BLINK: 'Blink',
};
export const DEFAULT_CHALLENGES = Object.keys(CHALLENGE_LABELS);

// The axis each challenge moves, and the pose direction that counts as "the right way".
export const CHALLENGE_AXIS = {
  TURN_LEFT: { axis: 'yaw', direction: 'TURNED_LEFT' },
  TURN_RIGHT: { axis: 'yaw', direction: 'TURNED_RIGHT' },
  LOOK_UP: { axis: 'pitch', direction: 'LOOKING_UP' },
  LOOK_DOWN: { axis: 'pitch', direction: 'LOOKING_DOWN' },
  BLINK: { axis: null, direction: null },
};

export const NOT_VISIBLE_REASONS = {
  NO_FACE: 'No face found',
  MULTIPLE_FACES: 'More than one face',
  TOO_DARK: 'Too dark, add light',
  TOO_BRIGHT: 'Too bright or backlit',
  TOO_SMALL: 'Too far, move closer',
  BLURRY: 'Image is blurry, hold still',
  LANDMARKS_UNAVAILABLE: 'Detector could not find landmarks',
};

export const notVisibleText = (reason) => NOT_VISIBLE_REASONS[reason] ?? (reason ? String(reason) : 'Face not visible');

const isNumber = (value) => typeof value === 'number' && Number.isFinite(value);

/** +0.152 / -0.040; em dash when missing. */
export function signed(value, digits = 3) {
  if (!isNumber(value)) return '—';
  return `${value >= 0 ? '+' : ''}${value.toFixed(digits)}`;
}

export function fixed(value, digits = 0) {
  return isNumber(value) ? value.toFixed(digits) : '—';
}

export function grouped(value) {
  return isNumber(value) ? Math.round(value).toLocaleString() : '—';
}

/** "left_eye" -> "L eye", "mouth_right" -> "mouth R"; swapped when the preview is mirrored. */
export function shortLandmarkLabel(name, mirrored) {
  const side = (word) => {
    if (word === 'left') return mirrored ? 'R' : 'L';
    if (word === 'right') return mirrored ? 'L' : 'R';
    return word;
  };
  return name.split('_').map(side).join(' ');
}

// Backend pose.direction (subject's own direction) -> short word.
const DIRECTION_WORDS = {
  TURNED_LEFT: 'LEFT', TURNED_RIGHT: 'RIGHT', LOOKING_UP: 'UP', LOOKING_DOWN: 'DOWN',
};

/** "TURNED_RIGHT" -> "Face tilted RIGHT"; FRONTAL/unknown reads as centred. */
export function directionHint(direction) {
  const word = DIRECTION_WORDS[direction];
  return word ? `Face tilted ${word}` : 'Face centred';
}

export function directionBadge(direction) {
  const word = DIRECTION_WORDS[direction];
  return word ? `TILTED ${word}` : 'CENTRED';
}

export const clamp01 = (value) => Math.min(1, Math.max(0, value));
