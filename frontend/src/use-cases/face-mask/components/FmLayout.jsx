import { Suspense } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { Moon, Sun } from 'lucide-react';
import Loading from '../../../components/common/Loading.jsx';
import { toggleTheme, useBxTheme } from '../../branch-exterior/theme.js';
import { api } from '../api/index.js';
import usePolling from '../hooks/usePolling.js';
import { FmStatusProvider, useFmStatus } from './FmStatus.jsx';
import { PrivacyNote } from './ui.jsx';
import '../../branch-exterior/branchExterior.css';

export const FM_PAGES = {
  '': 'Entries today, concealed events and open reviews at a glance',
  live: 'Pick a camera or video, watch it analysed live, add cameras and process videos',
  events: 'Review every concealment event with its snapshot, clip and details',
  roi: 'Draw where people enter, and which way is "inward", for each camera',
  reports: 'Export events and tune the thresholds that decide visible vs concealed',
};

const STATE_LABEL = { online: 'ONLINE', degraded: 'DEGRADED', offline: 'OFFLINE', checking: 'CHECKING' };
const STATE_COLOR = { online: 'var(--bx-green)', degraded: 'var(--bx-amber)', offline: 'var(--bx-red)', checking: 'var(--bx-mute)' };

function Chips() {
  const { state, online, health } = useFmStatus();
  const reviews = usePolling(async () => (state === 'offline' ? null : api.get('/stats/summary?period=all')), 15000, [state]);
  return (
    <div className="bx-chips bx-no-print">
      <span className="bx-chip" title={health ? `${health.db_engine} | analyzer ${health.models?.analyzer_active || health.models?.analyzer_configured}` : ''}>
        Face Mask service <b style={{ color: STATE_COLOR[state] }}>{STATE_LABEL[state]}</b>
      </span>
      <span className="bx-chip">Cameras online <b>{online ? `${online.cameras_online} / ${online.cameras_total}` : '-'}</b></span>
      <span className="bx-chip">Open reviews <b>{reviews.data ? reviews.data.open_reviews : '-'}</b></span>
    </div>
  );
}

function Frame() {
  const theme = useBxTheme();
  const { pathname } = useLocation();
  const key = pathname.split('/')[2] || '';
  const { state, health } = useFmStatus();
  const next = theme === 'dark' ? 'bright' : 'dark';
  return (
    <div className="bx-page" data-theme={theme}>
      <div className="bx-subbar">
        <p className="sub" style={{ margin: 0, maxWidth: 760 }}>{FM_PAGES[key] || FM_PAGES['']}</p>
        <div className="bx-row bx-gap-8 bx-wrap">
          <Chips />
          <button type="button" className="bx-btn bx-btn-sm bx-no-print" onClick={toggleTheme} aria-label={`Switch to ${next} theme`} title={`Switch to ${next} theme`}>
            {theme === 'dark' ? <Sun size={14} aria-hidden /> : <Moon size={14} aria-hidden />}
          </button>
        </div>
      </div>
      <PrivacyNote />
      {state === 'degraded' && health && (
        <div className="bx-diag" role="status">
          Face Mask is running but not fully ready: database <b>{health.db}</b>; models
          person <b>{health.models?.person_detector}</b>, face <b>{health.models?.face_detector}</b>, pose <b>{health.models?.pose}</b>.
          {' '}If models are missing, run <code>uv run python scripts/download_models.py</code> in <code>backend/use_cases/face_mask</code>.
        </div>
      )}
      <Suspense fallback={<Loading message="Loading…" />}><Outlet /></Suspense>
    </div>
  );
}

/** Route layout for every /face-mask/* page: theme, status chips, privacy note and the shared health poll. */
export default function FmLayout() {
  return <FmStatusProvider><Frame /></FmStatusProvider>;
}
