import { AlertTriangle } from 'lucide-react';

/** `error` is `{ status, message }` from describeError, or a plain string. */
export default function ErrorMessage({ error }) {
  if (!error) return null;
  const message = typeof error === 'string' ? error : error.message;
  const status = typeof error === 'string' ? null : error.status;
  return (
    <div role="alert" className="flex items-start gap-3 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      <div>
        <p className="font-medium">Error{status ? ` (HTTP ${status})` : ''}</p>
        <p>{message}</p>
      </div>
    </div>
  );
}
