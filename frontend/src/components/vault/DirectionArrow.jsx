import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Eye, Smile, UserRound } from 'lucide-react';
import { challengeUI } from './challengeUI.js';

const ARROWS = { left: ArrowLeft, right: ArrowRight, up: ArrowUp, down: ArrowDown };
const ACTION_ICONS = { BLINK: Eye, SMILE: Smile };

/**
 * Head silhouette with a large animated arrow on the side the user must move toward.
 * Directions are the user's own (left = their left). The webcam preview is mirrored, so the
 * arrow also points the same way the face should travel on screen.
 */
export default function DirectionArrow({ challenge, wrong = false }) {
  const { direction, instruction } = challengeUI(challenge);
  const Arrow = direction ? ARROWS[direction] : null;
  const ActionIcon = ACTION_ICONS[challenge];
  if (!Arrow && !ActionIcon) return null;

  const vertical = direction === 'up' || direction === 'down';
  const layout = direction === 'left' ? 'flex-row' : direction === 'right' ? 'flex-row-reverse'
    : direction === 'up' ? 'flex-col' : direction === 'down' ? 'flex-col-reverse' : 'flex-col';
  const tone = wrong ? 'text-amber-600' : 'text-brand';

  return (
    <div
      className={`mx-auto my-3 flex w-fit items-center justify-center gap-3 rounded-2xl bg-white px-6 py-4 shadow-sm ring-2 ${
        wrong ? 'ring-amber-400' : 'ring-brand/30'
      } ${layout}`}
      role="img"
      aria-label={instruction}
    >
      {Arrow ? (
        <span className={`direction-arrow ${tone}`} data-direction={direction}>
          <Arrow className={vertical ? 'h-14 w-14' : 'h-16 w-16'} strokeWidth={3} aria-hidden />
        </span>
      ) : (
        <ActionIcon className={`h-16 w-16 ${tone}`} strokeWidth={2.5} aria-hidden />
      )}
      {Arrow && <UserRound className="h-16 w-16 text-navy" strokeWidth={1.75} aria-hidden />}
    </div>
  );
}
