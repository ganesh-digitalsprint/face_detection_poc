import { NavLink, Outlet } from 'react-router-dom';
import { ALERT_TABS } from '../../layouts/routes.js';

const tabClass = ({ isActive }) =>
  `-mb-px inline-flex min-h-11 items-center border-b-2 px-4 text-sm font-semibold ${
    isActive ? 'border-accent text-navy' : 'border-transparent text-slate-500 hover:text-navy'
  }`;

/** Shell for /alerts/*: one set of tabs; each tab is its own route and keeps its own query string. */
export default function AlertsLayout() {
  return (
    <div>
      <nav aria-label="Alerts views" className="mb-4 flex gap-1 overflow-x-auto border-b border-slate-200">
        {ALERT_TABS.map((tab) => (
          <NavLink key={tab.id} to={tab.to} className={tabClass}>{tab.label}</NavLink>
        ))}
      </nav>
      <Outlet />
    </div>
  );
}
