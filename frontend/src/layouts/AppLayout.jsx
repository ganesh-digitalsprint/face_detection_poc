import { useEffect, useState } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import {
  Cctv, Film, LayoutDashboard, LockKeyhole, Menu, Radio, ScanFace, ScanSearch, ScanEye, ShieldCheck, UserPlus, Users, Webcam, X,
} from 'lucide-react';
import StatusBadge from '../components/common/StatusBadge.jsx';
import useHealth from '../hooks/useHealth.js';

const TITLES = [
  ['/registration/authorized', 'Authorized Employee Registration'],
  ['/registration/employees', 'Employee Registration'],
  ['/vault-access', 'Vault Access'],
  ['/detection', 'Face Detection'],
  ['/registration', 'Person Registration'],
  ['/identification', 'Face Identification'],
  ['/verification', 'Face Verification'],
  ['/live', 'Live Monitoring'],
  ['/video', 'Video Recognition'],
  ['/', 'Dashboard'],
];
const BADGE = { ok: 'CONNECTED', degraded: 'DEGRADED', offline: 'OFFLINE', checking: 'CHECKING' };

const link = ({ isActive }) =>
  `flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium ${
    isActive ? 'bg-white/15 text-white' : 'text-slate-300 hover:bg-white/10 hover:text-white'
  }`;
const subLink = ({ isActive }) => `${link({ isActive })} ml-6 py-1.5`;

function Sidebar({ onNavigate }) {
  return (
    <nav aria-label="Main" className="flex h-full flex-col gap-1 bg-navy p-4" onClick={onNavigate}>
      <div className="mb-4 flex items-center gap-2 px-3 text-white">
        <ScanEye className="h-6 w-6 text-accent" aria-hidden />
        <span className="text-lg font-semibold">Face AI POC</span>
      </div>
      <NavLink to="/" end className={link}><LayoutDashboard className="h-4 w-4" aria-hidden />Dashboard</NavLink>
      <p className="mt-3 px-3 text-xs uppercase tracking-wide text-slate-400">Registration</p>
      <NavLink to="/registration/employees" className={link}><Users className="h-4 w-4" aria-hidden />Employee Registration</NavLink>
      <p className="mt-3 px-3 text-xs uppercase tracking-wide text-slate-400">Vault Access</p>
      <NavLink to="/vault-access" className={link}><LockKeyhole className="h-4 w-4" aria-hidden />Vault Access</NavLink>
      <p className="mt-3 px-3 text-xs uppercase tracking-wide text-slate-400">Images</p>
      <NavLink to="/detection" className={link}><ScanFace className="h-4 w-4" aria-hidden />Face Detection</NavLink>
      <NavLink to="/registration" end className={link}><UserPlus className="h-4 w-4" aria-hidden />Person Registration</NavLink>
      <NavLink to="/identification" className={link}><ScanSearch className="h-4 w-4" aria-hidden />Face Identification</NavLink>
      <NavLink to="/verification" className={link}><ShieldCheck className="h-4 w-4" aria-hidden />Face Verification</NavLink>
      <p className="mt-3 px-3 text-xs uppercase tracking-wide text-slate-400">Live &amp; Video</p>
      <NavLink to="/live" end className={link}><Radio className="h-4 w-4" aria-hidden />Live Monitoring</NavLink>
      <NavLink to="/live/webcam" className={subLink}><Webcam className="h-4 w-4" aria-hidden />Webcam</NavLink>
      <NavLink to="/live/cctv" className={subLink}><Cctv className="h-4 w-4" aria-hidden />CCTV</NavLink>
      <NavLink to="/video" className={link}><Film className="h-4 w-4" aria-hidden />Video Recognition</NavLink>
    </nav>
  );
}

export default function AppLayout() {
  const [open, setOpen] = useState(false);
  const { pathname } = useLocation();
  const { status } = useHealth();
  const title = TITLES.find(([p]) => (p === '/' ? pathname === '/' : pathname.startsWith(p)))?.[1] ?? 'Face AI POC';

  useEffect(() => { document.title = `${title} · Face AI POC`; }, [title]);

  return (
    <div className="min-h-screen lg:flex">
      <aside className="hidden w-64 shrink-0 lg:block"><div className="sticky top-0 h-screen"><Sidebar /></div></aside>

      {open && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <button aria-label="Close menu" className="absolute inset-0 bg-black/40" onClick={() => setOpen(false)} />
          <div className="relative h-full w-64"><Sidebar onNavigate={() => setOpen(false)} /></div>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex items-center gap-3 border-b border-slate-200 bg-white px-4 py-3 sm:px-6">
          <button
            className="rounded-md p-1.5 text-slate-600 hover:bg-slate-100 lg:hidden"
            aria-label={open ? 'Close menu' : 'Open menu'}
            aria-expanded={open}
            onClick={() => setOpen((v) => !v)}
          >
            {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
          <h1 className="text-lg font-semibold text-navy">{title}</h1>
          <div className="ml-auto flex items-center gap-2 text-xs text-slate-500">
            API <StatusBadge status={BADGE[status]} />
          </div>
        </header>
        <main className="flex-1 p-4 sm:p-6"><Outlet /></main>
      </div>
    </div>
  );
}
