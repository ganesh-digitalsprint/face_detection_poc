import { lazy, Suspense } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import Loading from './components/common/Loading.jsx';
import AppLayout from './layouts/AppLayout.jsx';
import Dashboard from './pages/Dashboard.jsx';
import Detection from './pages/Detection.jsx';
import Identification from './pages/Identification.jsx';
import LiveMonitoring from './pages/LiveMonitoring.jsx';
import Registration from './pages/Registration.jsx';
import VaultAccess from './pages/VaultAccess.jsx';
import VaultAlerts from './pages/VaultAlerts.jsx';
import VaultIncident from './pages/VaultIncident.jsx';
import AuthorizedEmployeeRegistration from './pages/registration/AuthorizedEmployeeRegistration.jsx';
import EmployeeRegistration from './pages/registration/EmployeeRegistration.jsx';
import FaceEnrollment from './pages/registration/FaceEnrollment.jsx';
import Verification from './pages/Verification.jsx';
import VideoRecognition from './pages/VideoRecognition.jsx';

const LivenessTestPage = lazy(() => import('./pages/LivenessTestPage.jsx'));

// Branch Exterior Monitoring (separate micro-service backend) - loaded on demand.
const BxLayout = lazy(() => import('./branch-exterior/components/BxLayout.jsx'));
const BxLive = lazy(() => import('./branch-exterior/pages/LiveMonitoringPage.jsx'));
const BxRegions = lazy(() => import('./branch-exterior/pages/RegionsZonesPage.jsx'));
const BxDashboard = lazy(() => import('./branch-exterior/pages/AlertsDashboardPage.jsx'));
const BxBrief = lazy(() => import('./branch-exterior/pages/SecurityBriefPage.jsx'));
const BxGuards = lazy(() => import('./branch-exterior/pages/GuardRosterPage.jsx'));
const BxSettings = lazy(() => import('./branch-exterior/pages/SettingsPage.jsx'));
const BxSystemCheck = lazy(() => import('./branch-exterior/pages/SystemCheckPage.jsx'));
const bxFallback = <Loading message="Loading Branch Exterior Monitoring…" />;

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
        <Route path="vault-alerts" element={<VaultAlerts />} />
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
          <Route path="dashboard" element={<BxDashboard />} />
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
