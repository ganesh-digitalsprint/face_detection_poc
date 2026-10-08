import { challengeUI } from './challengeUI.js';

/** Large arrow showing the user's physical direction; animation only for directional challenges. */
export default function DirectionArrow({ challenge }) {
  const { arrow, direction, instruction } = challengeUI(challenge);
  if (!arrow) return null;
  return (
    <div className="my-2 flex h-20 items-center justify-center text-brand" aria-hidden="true">
      <span
        className="direction-arrow select-none text-7xl font-bold leading-none"
        data-direction={direction ?? undefined}
        title={instruction}
      >
        {arrow}
      </span>
    </div>
  );
}
