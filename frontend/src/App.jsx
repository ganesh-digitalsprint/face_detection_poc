import { Route, Routes } from 'react-router-dom';
import AppLayout from './layouts/AppLayout.jsx';
import Dashboard from './pages/Dashboard.jsx';
import Detection from './pages/Detection.jsx';
import Identification from './pages/Identification.jsx';
import LiveMonitoring from './pages/LiveMonitoring.jsx';
import Registration from './pages/Registration.jsx';
import Verification from './pages/Verification.jsx';
import VideoRecognition from './pages/VideoRecognition.jsx';

export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<Dashboard />} />
        <Route path="detection" element={<Detection />} />
        <Route path="registration" element={<Registration />} />
        <Route path="identification" element={<Identification />} />
        <Route path="verification" element={<Verification />} />
        <Route path="live/*" element={<LiveMonitoring />} />
        <Route path="video" element={<VideoRecognition />} />
        <Route path="*" element={<Dashboard />} />
      </Route>
    </Routes>
  );
}
