/**
 * Single source of truth for how each backend challenge is presented.
 * `direction` is the user's physical direction (their own left/right), independent of
 * whether the camera preview is mirrored. The mirror is presentation-only.
 */
export const CHALLENGE_UI = {
  TURN_LEFT: { instruction: 'Turn your head LEFT', direction: 'left', arrow: '←', done: 'LEFT detected' },
  TURN_RIGHT: { instruction: 'Turn your head RIGHT', direction: 'right', arrow: '→', done: 'RIGHT detected' },
  LOOK_UP: { instruction: 'Tilt your head UP', direction: 'up', arrow: '↑', done: 'UP detected' },
  LOOK_DOWN: { instruction: 'Tilt your head DOWN', direction: 'down', arrow: '↓', done: 'DOWN detected' },
  BLINK: { instruction: 'Blink your eyes', direction: null, arrow: '👁', done: 'Blink detected' },
  SMILE: { instruction: 'Smile', direction: null, arrow: '☺', done: 'Smile detected' },
};

export function challengeUI(challenge) {
  return CHALLENGE_UI[challenge] ?? { instruction: challenge, direction: null, arrow: '', done: 'Detected' };
}
