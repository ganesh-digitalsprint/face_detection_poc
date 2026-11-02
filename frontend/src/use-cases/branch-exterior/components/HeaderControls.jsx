import { useEffect, useState } from 'react';
import { Moon, Sun } from 'lucide-react';
import { useFeedConnected } from '../feed.js';
import { toggleTheme, useBxTheme } from '../theme.js';

/** Clock + live-feed status + dark/bright switch, shown in the app header on Branch Exterior pages. */
export default function HeaderControls() {
  const theme = useBxTheme();
  const connected = useFeedConnected();
  const [now, setNow] = useState(() => new Date());
  useEffect(() => { const id = setInterval(() => setNow(new Date()), 1000); return () => clearInterval(id); }, []);
  const next = theme === 'dark' ? 'bright' : 'dark';
  return (
    <div className="flex items-center gap-3 text-xs">
      <span className="hidden tabular-nums sm:inline app-muted text-slate-500">{now.toLocaleTimeString()}</span>
      <span
        className={`hidden items-center gap-1.5 rounded-full border px-2.5 py-0.5 font-semibold sm:inline-flex ${
          connected ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-red-200 bg-red-50 text-red-700'
        }`}
      >
        <span className={`h-2 w-2 rounded-full ${connected ? 'bg-emerald-500' : 'bg-red-500'}`} />
        {connected ? 'LIVE FEED' : 'RECONNECTING'}
      </span>
      <button
        type="button"
        onClick={toggleTheme}
        aria-label={`Switch to ${next} theme`}
        title={`Switch to ${next} theme`}
        className="app-icon-btn inline-flex h-9 w-9 items-center justify-center rounded-md border border-slate-300 text-slate-600 hover:bg-slate-100"
      >
        {theme === 'dark' ? <Sun className="h-4 w-4" aria-hidden /> : <Moon className="h-4 w-4" aria-hidden />}
      </button>
    </div>
  );
}
