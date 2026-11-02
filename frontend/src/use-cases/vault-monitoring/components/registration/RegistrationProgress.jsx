import { Check } from 'lucide-react';

export const REGISTRATION_STEPS = ['Employee', 'Authorization', 'Face Enrollment', 'Complete'];

/** `current` is the 0-based active step; earlier steps are done, later steps pending. */
export default function RegistrationProgress({ current }) {
  return (
    <ol aria-label="Registration progress" className="flex flex-wrap items-center gap-x-2 gap-y-2">
      {REGISTRATION_STEPS.map((label, index) => {
        const done = index < current;
        const active = index === current;
        const circle = done
          ? 'border-emerald-600 bg-emerald-600 text-white'
          : active
            ? 'border-brand bg-brand text-white'
            : 'border-slate-300 bg-white text-slate-400';
        const text = active ? 'font-semibold text-navy' : done ? 'text-emerald-700' : 'text-slate-400';
        return (
          <li key={label} aria-current={active ? 'step' : undefined} className="flex items-center gap-2">
            <span className={`flex h-7 w-7 items-center justify-center rounded-full border text-xs font-semibold ${circle}`}>
              {done ? <Check className="h-4 w-4" aria-hidden /> : index + 1}
            </span>
            <span className={`text-sm ${text}`}>{label}</span>
            {index < REGISTRATION_STEPS.length - 1 && <span className="mx-1 hidden h-px w-6 bg-slate-300 sm:block" aria-hidden />}
          </li>
        );
      })}
    </ol>
  );
}
