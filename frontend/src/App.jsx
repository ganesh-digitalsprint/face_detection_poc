import { lazy, Suspense } from 'react';
import { Navigate, Route, Routes, useLocation } from 'react-router-dom';
import Loading from './components/common/Loading.jsx';
import AppLayout from './layouts/AppLayout.jsx';
import { LEGACY_REDIRECTS } from './layouts/routes.js';
import AlertsLayout from './pages/alerts/AlertsLayout.jsx';
import AlertCenter from './pages/AlertCenter.jsx';
import Dashboard from './pages/Dashboard.jsx';
import Detection from './pages/Detection.jsx';
import Identification from './pages/Identification.jsx';
import LiveMonitoring from './pages/LiveMonitoring.jsx';
import Registration from './use-cases/vault-monitoring/pages/Registration.jsx';
import VaultAccess from './use-cases/vault-monitoring/pages/VaultAccess.jsx';
import VaultAlerts from './use-cases/vault-monitoring/pages/VaultAlerts.jsx';
import VaultIncident from './use-cases/vault-monitoring/pages/VaultIncident.jsx';
import AuthorizedEmployeeRegistration from './use-cases/vault-monitoring/pages/registration/AuthorizedEmployeeRegistration.jsx';
import EmployeeRegistration from './use-cases/vault-monitoring/pages/registration/EmployeeRegistration.jsx';
import FaceEnrollment from './use-cases/vault-monitoring/pages/registration/FaceEnrollment.jsx';
import Verification from './pages/Verification.jsx';
import VideoRecognition from './pages/VideoRecognition.jsx';

const LivenessTestPage = lazy(() => import('./use-cases/vault-monitoring/pages/LivenessTestPage.jsx'));

// Branch Exterior Monitoring (separate micro-service backend) - loaded on demand.
const BxLayout = lazy(() => import('./use-cases/branch-exterior/components/BxLayout.jsx'));
const BxLive = lazy(() => import('./use-cases/branch-exterior/pages/LiveMonitoringPage.jsx'));
const BxRegions = lazy(() => import('./use-cases/branch-exterior/pages/RegionsZonesPage.jsx'));
const BxDashboard = lazy(() => import('./use-cases/branch-exterior/pages/AlertsDashboardPage.jsx'));
const BxBrief = lazy(() => import('./use-cases/branch-exterior/pages/SecurityBriefPage.jsx'));
const BxGuards = lazy(() => import('./use-cases/branch-exterior/pages/GuardRosterPage.jsx'));
const BxSettings = lazy(() => import('./use-cases/branch-exterior/pages/SettingsPage.jsx'));
const BxSystemCheck = lazy(() => import('./use-cases/branch-exterior/pages/SystemCheckPage.jsx'));
const bxFallback = <Loading message="Loading Branch Exterior Monitoring…" />;

/** Old URL -> new URL, keeping the query string and hash (a bare <Navigate to> would drop them). */
function LegacyRedirect({ to }) {
  const { search, hash } = useLocation();
  return <Navigate to={{ pathname: to, search, hash }} replace />;
}

export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<Dashboard />} />
        <Route path="detection" element={<Detection />} />
        <Route path="registration" element={<Registration />} />
        <Route path="registration/employees" element={<EmployeeRegistration />} />
        <Route path="registration/authorized/:employeeId" element={<AuthorizedEmployeeRegistration />} />
        <Route path="registration/authorized/:employeeId/face" element={<FaceEnrollment />} />
        <Route path="vault-access" element={<VaultAccess />} />
        <Route path="alerts" element={<AlertsLayout />}>
          <Route index element={<Navigate to="vault" replace />} />
          <Route path="vault" element={<VaultAlerts />} />
          <Route path="all" element={<AlertCenter />} />
          <Route path="branch" element={<Suspense fallback={bxFallback}><BxLayout /></Suspense>}>
            <Route index element={<BxDashboard />} />
          </Route>
        </Route>
        {LEGACY_REDIRECTS.map(([from, to]) => (
          <Route key={from} path={from.slice(1)} element={<LegacyRedirect to={to} />} />
        ))}
        <Route path="vault-alerts/incidents/:incidentId" element={<VaultIncident />} />
        <Route
          path="liveness-test"
          element={<Suspense fallback={<Loading message="Loading Liveness Test…" />}><LivenessTestPage /></Suspense>}
        />
        <Route path="identification" element={<Identification />} />
        <Route path="verification" element={<Verification />} />
        <Route path="live/*" element={<LiveMonitoring />} />
        <Route path="video" element={<VideoRecognition />} />
        <Route path="branch-exterior" element={<Suspense fallback={bxFallback}><BxLayout /></Suspense>}>
          <Route index element={<Navigate to="live" replace />} />
          <Route path="live" element={<BxLive />} />
          <Route path="regions" element={<BxRegions />} />
          <Route path="brief" element={<BxBrief />} />
          <Route path="guards" element={<BxGuards />} />
          <Route path="settings" element={<BxSettings />} />
          <Route path="system-check" element={<BxSystemCheck />} />
        </Route>
        <Route path="*" element={<Dashboard />} />
      </Route>
    </Routes>
  );
}
