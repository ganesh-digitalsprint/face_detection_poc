import { Loader2 } from 'lucide-react';

export default function Loading({ message = 'Loading...', hint }) {
  return (
    <div role="status" aria-live="polite" className="flex flex-col items-center gap-2 py-8 text-slate-500">
      <Loader2 className="h-6 w-6 animate-spin text-brand" aria-hidden />
      <p className="text-sm font-medium">{message}</p>
      {hint && <p className="text-xs">{hint}</p>}
    </div>
  );
}
