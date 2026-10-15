import { useEffect } from 'react';
import { FlaskConicalOff, RotateCcw, ScanFace, ShieldAlert } from 'lucide-react';
import Button from '../components/common/Button.jsx';
import ErrorMessage from '../components/common/ErrorMessage.jsx';
import Loading from '../components/common/Loading.jsx';
import CameraAnalysisView from '../components/livenessTest/CameraAnalysisView.jsx';
import ChallengeCard from '../components/livenessTest/ChallengeCard.jsx';
import ClarityCard from '../components/livenessTest/ClarityCard.jsx';
import DetectorPerformanceCard from '../components/livenessTest/DetectorPerformanceCard.jsx';
import HeadPoseCard from '../components/livenessTest/HeadPoseCard.jsx';
import LandmarkTable from '../components/livenessTest/LandmarkTable.jsx';
import LivenessTestControls from '../components/livenessTest/LivenessTestControls.jsx';
import OverlayToggles from '../components/livenessTest/OverlayToggles.jsx';
import YawPitchSparkline from '../components/livenessTest/YawPitchSparkline.jsx';
import useCameraSource from '../hooks/useCameraSource.js';
import useLivenessTest, { primaryResult } from '../hooks/useLivenessTest.js';
import useLivenessTestFeature from '../hooks/useLivenessTestFeature.js';
import useOverlayToggles from '../hooks/useOverlayToggles.js';

const ground = '-m-4 min-h-full bg-[#F4F6FB] p-4 sm:-m-6 sm:p-6';

function PageHeader() {
  return (
    <div className="mx-auto mb-6 flex max-w-[1360px] flex-wrap items-center justify-between gap-3">
      <div className="flex items-center gap-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#34479B] text-white" aria-hidden>
          <ScanFace className="h-5 w-5" />
        </span>
        <div>
          <h2 className="vault-heading text-lg">Liveness Test Lab</h2>
          <p className="text-sm text-[#55607A]">Try challenges and inspect face analysis without opening a vault session</p>
        </div>
      </div>
      <span className="rounded-full bg-[#EAF0FF] px-4 py-2 text-sm font-medium text-[#1F2F6B]">
        Test mode · nothing is saved or authorized
      </span>
    </div>
  );
}

function FeatureGate({ feature }) {
  if (feature.status === 'checking') return <Loading message="Checking whether the test tool is enabled…" />;
  if (feature.status === 'disabled') {
    return (
      <section className="vault-card mx-auto max-w-lg p-8 text-center">
        <FlaskConicalOff className="mx-auto h-10 w-10 text-[#55607A]" aria-hidden />
        <h2 className="vault-heading mt-3 text-lg">This tool is disabled</h2>
        <p className="mt-1 text-sm text-[#55607A]">The backend has the liveness test feature turned off.</p>
      </section>
    );
  }
  return (
    <section className="vault-card mx-auto max-w-lg space-y-3 p-6">
      <ErrorMessage error={feature.error} />
      <Button variant="secondary" icon={RotateCcw} onClick={feature.retry} className="min-h-11">Retry</Button>
    </section>
  );
}

function LivenessLab({ config }) {
  const camera = useCameraSource();
  const test = useLivenessTest(camera, { initialThresholds: config?.thresholds ?? null });
  const [toggles, setToggle] = useOverlayToggles();
  const { phase, start, stop } = test;
  const cameraReady = camera.status === 'ready';

  // Analysis follows the camera: start when it is ready, stop when it goes away or switches source.
  useEffect(() => {
    if (cameraReady && phase === 'idle') start();
    if (!cameraReady && phase !== 'idle' && phase !== 'error') stop();
  }, [cameraReady, phase, start, stop]);

  const handleStopCamera = () => { stop(); camera.stop(); };
  const results = test.analysis?.results ?? [];
  const primary = primaryResult(test.analysis, test.detector);

  return (
    <div className="mx-auto grid max-w-[1360px] gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(400px,540px)]">
      <div className="min-w-0 space-y-6">
        <section aria-label="Camera" className="vault-card space-y-4 p-4">
          <CameraAnalysisView camera={camera} test={test} toggles={toggles} />
          {phase === 'idle' && !cameraReady && (
            <p className="text-sm text-[#55607A]">
              Start a camera to see live face analysis. Frames are analysed one at a time and never stored.
            </p>
          )}
          <LivenessTestControls camera={camera} test={test} onStopCamera={handleStopCamera} />
          {phase === 'error' && (
            <div className="space-y-3">
              <p className="flex items-center gap-2 text-sm font-semibold text-[#B3261E]">
                <ShieldAlert className="h-5 w-5" aria-hidden /> Analysis stopped
              </p>
              <ErrorMessage error={test.error} />
              <Button variant="secondary" icon={RotateCcw} onClick={start} disabled={!cameraReady} className="min-h-11">Retry</Button>
            </div>
          )}
        </section>
        <OverlayToggles toggles={toggles} onChange={setToggle} />
      </div>

      <div className="min-w-0 space-y-6">
        <ChallengeCard selected={test.challenge} analysis={test.analysis} thresholds={test.thresholds}
          onSelect={test.changeChallenge} />
        <HeadPoseCard result={primary} analysis={test.analysis} thresholds={test.thresholds} />
        <ClarityCard result={primary} />
        <LandmarkTable results={results} />
        <DetectorPerformanceCard detector={test.detector} results={results} stats={test.stats} />
        {test.history.length > 1 && <YawPitchSparkline history={test.history} />}
      </div>
    </div>
  );
}

/** Developer tool: live liveness analysis. Never creates or touches a vault session. */
export default function LivenessTestPage() {
  const feature = useLivenessTestFeature();
  return (
    <div className={ground}>
      <PageHeader />
      {feature.status === 'enabled' ? <LivenessLab config={feature.config} /> : <FeatureGate feature={feature} />}
    </div>
  );
}
