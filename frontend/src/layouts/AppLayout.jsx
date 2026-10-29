import { useEffect, useRef } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { ChevronsLeft, ChevronsRight, Menu, PanelLeftClose, PanelLeftOpen, X } from 'lucide-react';
import HeaderControls from '../use-cases/branch-exterior/components/HeaderControls.jsx';
import StatusBadge from '../components/common/StatusBadge.jsx';
import useHealth from '../hooks/useHealth.js';
import useSidebar from '../hooks/useSidebar.js';
import Sidebar from './Sidebar.jsx';
import { showsBranchChrome } from './routes.js';

const TITLES = [
  ['/branch-exterior/live', 'Live Monitoring'],
  ['/branch-exterior/regions', 'Regions & Zones'],
  ['/branch-exterior/brief', 'Security Brief'],
  ['/branch-exterior/guards', 'Guard Roster'],
  ['/branch-exterior/settings', 'Settings'],
  ['/branch-exterior/system-check', 'System Check'],
  ['/branch-exterior', 'Branch Exterior Monitoring'],
  ['/registration/authorized', 'Authorized Employee Registration'],
  ['/registration/employees', 'Employee Registration'],
  ['/vault-alerts/incidents', 'Incident detail'],
  ['/alerts', 'Alerts'],
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
const PRODUCT_NAME = 'Fedbank Vision';
// TODO: pass { alerts: <open count> } as `badges` to <Sidebar> once a lightweight shared alerts-count source exists
// (useServiceAlerts is a full list+poll hook; mounting it here would add a second poller).

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
  const onBranchChrome = showsBranchChrome(pathname);
  const title = TITLES.find(([p]) => (p === '/' ? pathname === '/' : pathname.startsWith(p)))?.[1] ?? PRODUCT_NAME;

  useEffect(() => { document.title = `${title} · ${PRODUCT_NAME}`; }, [title]);
  useEffect(() => { closeDrawer(); }, [pathname, closeDrawer]);
  useDrawerFocus(drawerOpen, drawerRef, toggleRef, closeDrawer);

  const toggleLabel = expanded ? 'Collapse sidebar' : 'Expand sidebar';
  const ToggleIcon = isDesktop ? (collapsed ? PanelLeftOpen : PanelLeftClose) : (drawerOpen ? X : Menu);

  return (
    <div className="min-h-screen lg:flex">
      <aside
        id={SIDEBAR_ID}
        className={`app-aside hidden shrink-0 transition-[width] duration-200 motion-reduce:transition-none lg:block ${
          collapsed ? 'w-[72px]' : 'w-64'
        }`}
      >
        <div className="sticky top-0 flex h-screen flex-col bg-navy">
          <div className="min-h-0 flex-1"><Sidebar collapsed={collapsed} devEnabled={LIVENESS_TEST_MENU_ENABLED} onExpand={toggleCollapsed} /></div>
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
      <div className={`app-drawer fixed inset-0 z-40 lg:hidden ${drawerOpen ? '' : 'pointer-events-none'}`} inert={!drawerOpen}>
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
          <Sidebar devEnabled={LIVENESS_TEST_MENU_ENABLED} onNavigate={closeDrawer} />
        </div>
      </div>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="app-header sticky top-0 z-30 flex items-center gap-3 border-b border-slate-200 bg-white px-4 py-3 sm:px-6">
          <button
            ref={toggleRef}
            type="button"
            className="app-icon-btn inline-flex h-11 w-11 items-center justify-center rounded-md text-slate-600 hover:bg-slate-100"
            aria-label={toggleLabel}
            aria-expanded={expanded}
            aria-controls={isDesktop ? SIDEBAR_ID : DRAWER_ID}
            title={toggleLabel}
            onClick={toggle}
          >
            <ToggleIcon className="h-5 w-5" aria-hidden />
          </button>
          <h1 className="app-title text-lg font-semibold text-navy">{title}</h1>
          <div className="ml-auto flex items-center gap-3">
            {onBranchChrome && <HeaderControls />}
            <div className="app-muted flex items-center gap-2 text-xs text-slate-500">
              API <StatusBadge status={BADGE[status]} />
            </div>
          </div>
        </header>
        <main className="flex-1 p-4 sm:p-6"><Outlet /></main>
      </div>
    </div>
  );
}
