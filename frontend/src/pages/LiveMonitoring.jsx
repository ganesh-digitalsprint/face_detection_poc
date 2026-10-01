import { NavLink, Navigate, Route, Routes } from 'react-router-dom';
import Card from '../components/common/Card.jsx';
import CCTVPanel from '../components/streams/CCTVPanel.jsx';
import WebcamPanel from '../components/streams/WebcamPanel.jsx';

const tabCls = ({ isActive }) =>
  `rounded-md px-4 py-1.5 text-sm font-medium ${isActive ? 'bg-brand text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'}`;

/** Nested routes (/live/webcam, /live/cctv) so the sidebar sub-links and tabs share one source. */
export default function LiveMonitoring() {
  return (
    <div className="space-y-4">
      <nav aria-label="Live monitoring source" className="flex gap-2">
        <NavLink to="/live/webcam" className={tabCls}>Webcam</NavLink>
        <NavLink to="/live/cctv" className={tabCls}>CCTV</NavLink>
      </nav>
      <Card>
        <Routes>
          <Route index element={<Navigate to="webcam" replace />} />
          <Route path="webcam" element={<WebcamPanel />} />
          <Route path="cctv" element={<CCTVPanel />} />
        </Routes>
      </Card>
    </div>
  );
}
