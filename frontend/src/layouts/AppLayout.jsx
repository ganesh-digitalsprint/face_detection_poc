import { useEffect, useRef } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import {
  Cctv, ChevronsLeft, ChevronsRight, Film, LayoutDashboard, LockKeyhole, Menu, PanelLeftClose, PanelLeftOpen,
  Radio, ScanFace, ScanSearch, ScanEye, ShieldCheck, UserPlus, Users, Webcam, X,
} from 'lucide-react';
import StatusBadge from '../components/common/StatusBadge.jsx';
import useHealth from '../hooks/useHealth.js';
import useSidebar from '../hooks/useSidebar.js';

const TITLES = [
  ['/registration/authorized', 'Authorized Employee Registration'],
  ['/registration/employees', 'Employee Registration'],
  ['/vault-access', 'Vault Access'],
  ['/liveness-test', 'Liveness Test'],
  ['/detection', 'Face Detection'],
  ['/registration', 'Person Registration'],
  ['/identification', 'Face Identification'],
  ['/verification', 'Face Verification'],
  ['/live', 'Live Monitoring'],
  ['/video', 'Video Recognition'],
  ['/', 'Dashboard'],
];
const BADGE = { ok: 'CONNECTED', degraded: 'DEGRADED', offline: 'OFFLINE', checking: 'CHECKING' };
const SIDEBAR_ID = 'app-sidebar';
const DRAWER_ID = 'app-sidebar-drawer';
const FOCUSABLE = 'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])';
const LIVENESS_TEST_MENU_ENABLED = import.meta.env.VITE_LIVENESS_TEST_ENABLED == null
  ? import.meta.env.DEV
  : import.meta.env.VITE_LIVENESS_TEST_ENABLED === 'true';

const link = ({ isActive }) =>
  `flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium ${
    isActive ? 'bg-white/15 text-white' : 'text-slate-300 hover:bg-white/10 hover:text-white'
  }`;
const subLink = ({ isActive }) => `${link({ isActive })} ml-6 py-1.5`;

/** Collapsed: icon only, label kept for screen readers and shown as a tooltip. */
function Item({ to, end, icon: Icon, label, badge, sub = false, collapsed }) {
  const base = sub ? subLink : link;
  const className = (state) => (collapsed ? `${link(state)} min-h-11 justify-center px-0` : base(state));
  return (
    <NavLink to={to} end={end} className={className} title={collapsed ? label : undefined}>
      <Icon className="h-4 w-4 shrink-0" aria-hidden />
      <span className={collapsed ? 'sr-only' : undefined}>{label}</span>
      {badge && !collapsed && <span className="ml-auto rounded bg-white/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-slate-300">{badge}</span>}
    </NavLink>
  );
}

function Section({ label, collapsed }) {
  return collapsed
    ? <hr className="mx-2 my-2 border-white/10" aria-hidden />
    : <p className="mt-3 px-3 text-xs uppercase tracking-wide text-slate-400">{label}</p>;
}

function Sidebar({ onNavigate, collapsed = false }) {
  const props = { collapsed };
  return (
    <nav
      aria-label="Main"
      className={`flex h-full flex-col gap-1 overflow-y-auto bg-navy ${collapsed ? 'p-3' : 'p-4'}`}
      onClick={onNavigate}
    >
      <div className={`mb-4 flex items-center gap-2 text-white ${collapsed ? 'justify-center' : 'px-3'}`}>
        <ScanEye className="h-6 w-6 shrink-0 text-accent" aria-hidden />
        <span className={collapsed ? 'sr-only' : 'text-lg font-semibold'}>Face AI POC</span>
      </div>
      <Item to="/" end icon={LayoutDashboard} label="Dashboard" {...props} />
      <Section label="Registration" {...props} />
      <Item to="/registration/employees" icon={Users} label="Employee Registration" {...props} />
      <Section label="Vault Access" {...props} />
      <Item to="/vault-access" icon={LockKeyhole} label="Vault Access" {...props} />
      <Section label="Images" {...props} />
      <Item to="/detection" icon={ScanFace} label="Face Detection" {...props} />
      <Item to="/registration" end icon={UserPlus} label="Person Registration" {...props} />
      <Item to="/identification" icon={ScanSearch} label="Face Identification" {...props} />
      <Item to="/verification" icon={ShieldCheck} label="Face Verification" {...props} />
      <Section label="Security" {...props} />
      {LIVENESS_TEST_MENU_ENABLED && <Item to="/liveness-test" icon={ScanFace} label="Liveness Test" badge="Dev" {...props} />}
      <Section label="Live &amp; Video" {...props} />
      <Item to="/live" end icon={Radio} label="Live Monitoring" {...props} />
      <Item to="/live/webcam" icon={Webcam} label="Webcam" sub {...props} />
      <Item to="/live/cctv" icon={Cctv} label="CCTV" sub {...props} />
      <Item to="/video" icon={Film} label="Video Recognition" {...props} />
    </nav>
  );
}

/** Keeps Tab inside the open drawer, closes on Escape, and returns focus to the toggle. */
function useDrawerFocus(open, panelRef, returnFocusRef, onClose) {
  useEffect(() => {
    if (!open) return undefined;
    const panel = panelRef.current;
    const returnTo = returnFocusRef.current;
    panel?.querySelector(FOCUSABLE)?.focus();

    const onKeyDown = (event) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== 'Tab' || !panel) return;
      const items = [...panel.querySelectorAll(FOCUSABLE)];
      if (items.length === 0) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (!panel.contains(document.activeElement)) {
        event.preventDefault();
        first.focus();
      } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      returnTo?.focus();
    };
  }, [open, panelRef, returnFocusRef, onClose]);
}

export default function AppLayout() {
  const sidebar = useSidebar();
  const { isDesktop, collapsed, drawerOpen, expanded, toggle, toggleCollapsed, closeDrawer } = sidebar;
  const { pathname } = useLocation();
  const { status } = useHealth();
  const drawerRef = useRef(null);
  const toggleRef = useRef(null);
  const title = TITLES.find(([p]) => (p === '/' ? pathname === '/' : pathname.startsWith(p)))?.[1] ?? 'Face AI POC';

  useEffect(() => { document.title = `${title} · Face AI POC`; }, [title]);
  useEffect(() => { closeDrawer(); }, [pathname, closeDrawer]);
  useDrawerFocus(drawerOpen, drawerRef, toggleRef, closeDrawer);

  const toggleLabel = expanded ? 'Collapse sidebar' : 'Expand sidebar';
  const ToggleIcon = isDesktop ? (collapsed ? PanelLeftOpen : PanelLeftClose) : (drawerOpen ? X : Menu);

  return (
    <div className="min-h-screen lg:flex">
      <aside
        id={SIDEBAR_ID}
        className={`hidden shrink-0 transition-[width] duration-200 motion-reduce:transition-none lg:block ${
          collapsed ? 'w-[72px]' : 'w-64'
        }`}
      >
        <div className="sticky top-0 flex h-screen flex-col bg-navy">
          <div className="min-h-0 flex-1"><Sidebar collapsed={collapsed} /></div>
          <button
            type="button"
            onClick={toggleCollapsed}
            aria-expanded={!collapsed}
            aria-controls={SIDEBAR_ID}
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            className="flex min-h-11 items-center justify-center gap-2 border-t border-white/10 text-sm text-slate-300 hover:bg-white/10 hover:text-white"
          >
            {collapsed ? <ChevronsRight className="h-4 w-4" aria-hidden /> : <ChevronsLeft className="h-4 w-4" aria-hidden />}
            {!collapsed && <span>Collapse</span>}
          </button>
        </div>
      </aside>

      {/* Mobile drawer: kept mounted so it can slide; `inert` removes it from focus and the a11y tree when closed. */}
      <div className={`fixed inset-0 z-40 lg:hidden ${drawerOpen ? '' : 'pointer-events-none'}`} inert={!drawerOpen}>
        <button
          type="button"
          tabIndex={-1}
          aria-label="Close menu"
          className={`absolute inset-0 bg-black/40 transition-opacity duration-200 motion-reduce:transition-none ${
            drawerOpen ? 'opacity-100' : 'opacity-0'
          }`}
          onClick={closeDrawer}
        />
        <div
          id={DRAWER_ID}
          ref={drawerRef}
          role="dialog"
          aria-modal="true"
          aria-label="Main menu"
          className={`relative h-full w-64 transition-transform duration-200 motion-reduce:transition-none ${
            drawerOpen ? 'translate-x-0' : '-translate-x-full'
          }`}
        >
          <Sidebar onNavigate={closeDrawer} />
        </div>
      </div>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex items-center gap-3 border-b border-slate-200 bg-white px-4 py-3 sm:px-6">
          <button
            ref={toggleRef}
            type="button"
            className="inline-flex h-11 w-11 items-center justify-center rounded-md text-slate-600 hover:bg-slate-100"
            aria-label={toggleLabel}
            aria-expanded={expanded}
            aria-controls={isDesktop ? SIDEBAR_ID : DRAWER_ID}
            title={toggleLabel}
            onClick={toggle}
          >
            <ToggleIcon className="h-5 w-5" aria-hidden />
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
