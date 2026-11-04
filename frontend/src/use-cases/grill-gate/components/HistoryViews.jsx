import { Link } from 'react-router-dom';
import { BellOff, History } from 'lucide-react';
import { btnGhost, Card } from './ui.jsx';

/**
 * Grill Gate alert and event-history screens. No backend stage produces Grill Gate alerts or monitoring events
 * yet, so both show their empty state; nothing is queried from the Vault-only /api/v1/alerts store.
 */

export function AlertsView() {
  return (
    <Card title="Grill Gate alerts" aside={<Link to="/alerts" className={btnGhost}>Open Alerts center</Link>}>
      <div className="flex flex-col items-center gap-2 py-12 text-center">
        <BellOff size={26} className="text-slate-500" aria-hidden />
        <p className="font-semibold text-slate-200">No active alerts</p>
        <p className="max-w-md text-sm text-slate-400">Grill Gate alerts will appear here once the backend raises them. Filtering and acknowledgement become available with that service.</p>
      </div>
    </Card>
  );
}

export function EventHistoryView() {
  return (
    <Card title="Event history">
      <div className="flex flex-col items-center gap-2 py-12 text-center">
        <History size={26} className="text-slate-500" aria-hidden />
        <p className="font-semibold text-slate-200">No monitoring events available</p>
        <p className="max-w-md text-sm text-slate-400">Gate, ENTRY/EXIT and mesh events will be listed here once the backend records them.</p>
      </div>
    </Card>
  );
}
