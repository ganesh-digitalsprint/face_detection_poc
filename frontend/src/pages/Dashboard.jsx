import { Link } from 'react-router-dom';
import { Film, Radio, ScanFace, ScanSearch, ShieldCheck, UserPlus } from 'lucide-react';
import StatusBadge from '../components/common/StatusBadge.jsx';
import useHealth from '../hooks/useHealth.js';

const FEATURES = [
  { to: '/detection', icon: ScanFace, title: 'Face Detection', text: 'Detect faces from images' },
  { to: '/registration', icon: UserPlus, title: 'Person Registration', text: 'Enroll a new person' },
  { to: '/identification', icon: ScanSearch, title: 'Face Identification', text: 'Identify unknown faces' },
  { to: '/verification', icon: ShieldCheck, title: 'Face Verification', text: 'Verify a specific person' },
  { to: '/live', icon: Radio, title: 'Live Monitoring', text: 'Webcam / CCTV' },
  { to: '/video', icon: Film, title: 'Video Recognition', text: 'Process recorded video' },
];

const BADGE = { ok: 'CONNECTED', degraded: 'DEGRADED', offline: 'OFFLINE', checking: 'CHECKING' };

export default function Dashboard() {
  const { status, detail } = useHealth();
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-4 rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <div>
          <h2 className="text-lg font-semibold text-navy">Face AI POC</h2>
          <p className="text-sm text-slate-500">Face detection &amp; recognition proof of concept.</p>
        </div>
        <div className="ml-auto text-right text-sm">
          <p className="mb-1 text-xs font-medium uppercase tracking-wide text-slate-400">API Status</p>
          <StatusBadge status={BADGE[status]} />
          {detail && (
            <p className="mt-1 text-xs text-slate-500">database: {detail.database} · qdrant: {detail.qdrant}</p>
          )}
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {FEATURES.map(({ to, icon: Icon, title, text }) => (
          <Link
            key={to}
            to={to}
            className="group rounded-lg border border-slate-200 bg-white p-5 shadow-sm transition-colors hover:border-brand"
          >
            <Icon className="mb-3 h-6 w-6 text-brand group-hover:text-accent" aria-hidden />
            <h3 className="font-semibold text-slate-800">{title}</h3>
            <p className="text-sm text-slate-500">{text}</p>
          </Link>
        ))}
      </div>
    </div>
  );
}
