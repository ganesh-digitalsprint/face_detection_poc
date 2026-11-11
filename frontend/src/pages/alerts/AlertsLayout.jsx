import { Link, Outlet, useLocation } from 'react-router-dom';
import { ALERT_TABS } from '../../layouts/routes.js';

const tabClass = ({ isActive }) =>
  `inline-flex min-h-11 shrink-0 items-center border-b-2 px-4 text-sm font-semibold ${
    isActive ? 'border-accent text-navy' : 'border-transparent text-slate-500 hover:text-navy'
  }`;

/** Shell for /alerts/*: one set of tabs; each tab is its own route and keeps its own query string. */
export default function AlertsLayout() {
  const location = useLocation();
  const grill = location.pathname === '/alerts/all' && new URLSearchParams(location.search).get('use_case') === 'grill_gate';
  return (
    <div>
      <nav aria-label="Alerts views" className="mb-4 flex gap-1 overflow-x-auto border-b border-slate-200">
        {ALERT_TABS.map((tab) => (
          <Link key={tab.id} to={tab.to} aria-current={(tab.id === 'grill' ? grill : tab.id === 'all' ? location.pathname === tab.to && !grill : location.pathname.startsWith(tab.to)) ? 'page' : undefined} className={tabClass({ isActive: tab.id === 'grill' ? grill : tab.id === 'all' ? location.pathname === tab.to && !grill : location.pathname.startsWith(tab.to) })}>{tab.label}</Link>
        ))}
      </nav>
      <Outlet />
    </div>
  );
}
