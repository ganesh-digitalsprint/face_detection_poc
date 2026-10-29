import { Suspense, useCallback, useEffect, useState } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import Loading from '../../../components/common/Loading.jsx';
import { api } from '../api/index.js';
import { bxPageKey } from '../../../layouts/routes.js';
import { useFeedConnection } from '../feed.js';
import { useBxTheme } from '../theme.js';
import Toasts from './Toasts.jsx';
import '../branchExterior.css';

export const BX_PAGES = {
  live: ['Live Monitoring', 'Pick one video - only the selected video is analysed'],
  regions: ['Regions & Zones', 'Pick a video or camera, draw a region on it, and choose what happens the moment someone touches or comes near it'],
  dashboard: ['Alerts Dashboard', 'Every detected event across all five scenarios, ready for human review'],
  brief: ['Security Brief', 'A one-page summary of what the system saw - ready to print or save as a PDF'],
  guards: ['Guard Roster', 'Enroll on-duty guards so the system can tell staff apart from an unidentified person near a sensitive zone'],
  settings: ['Settings', 'Database connection, detection thresholds, operating hours and notifications'],
  'system-check': ['System check', 'Open this page when something does not work'],
};

/** Route layout for every /branch-exterior/* page and the /alerts/branch tab: theme, shared websocket, toasts and the status chips. */
export default function BxLayout() {
  const theme = useBxTheme();
  const { pathname } = useLocation();
  const [stats, setStats] = useState(null);
  useFeedConnection();

  const refreshStats = useCallback(async () => {
    try { setStats(await api.get('/dashboard/summary')); } catch { /* backend still starting up */ }
  }, []);
  useEffect(() => {
    refreshStats();
    const id = setInterval(refreshStats, 15000);
    return () => clearInterval(id);
  }, [refreshStats]);

  const key = bxPageKey(pathname);
  const sub = BX_PAGES[key]?.[1] || '';

  // Dark / bright is scoped to this container; the app shell and other pages never change.
  return (
    <div className="bx-page" data-theme={theme}>
      <div className="bx-subbar">
        <p className="sub" style={{ margin: 0, maxWidth: 760 }}>{sub}</p>
        <div className="bx-chips bx-no-print">
          <span className="bx-chip">Database <b>{stats ? stats.db_engine : '-'}</b></span>
          <span className="bx-chip">Cameras online <b>{stats ? `${stats.cameras_online} / ${stats.cameras_total}` : '-'}</b></span>
          <span className="bx-chip">Open alerts <b>{stats ? stats.open_events : '-'}</b></span>
        </div>
      </div>
      <Suspense fallback={<Loading message="Loading…" />}><Outlet /></Suspense>
      <Toasts onEvent={refreshStats} />
    </div>
  );
}
