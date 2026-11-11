import { videoAlertSession } from '../grillAlertFeed.js';
import { store } from '../../../store/index.js';
import { evaluateOpenTimer } from '../openTimerRuntime.js';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useSearchParams } from 'react-router-dom';
import { describeError } from '../../../utils/errors.js';
import { connectGrillGateAssignment, disconnectGrillGateAssignment } from '../api/grillGate.js';
import { connectionView, formatClock, workerForAssignment, workerIsActive } from '../grillGateModel.js';
import { useAssignmentZones, useGrillGateRegistry, useGrillGateWorkers } from '../hooks/useGrillGate.js';
import { useLiveMonitoring, useVideoJobList } from '../hooks/useSourceData.js';
import { useVideoJob, useVideoUpload } from '../hooks/useVideoJob.js';
import { liveMonitoring } from '../liveMonitoringModel.js';
import { jobErrorMessage, jobIsActive, jobPillLabel, jobProgressPercent, videoJobStatus, videoMonitoring } from '../videoJobModel.js';
import LiveCameraSection from '../components/LiveCameraSection.jsx';
import UploadedVideoSection from '../components/UploadedVideoSection.jsx';
import ZonesSection from '../components/ZonesSection.jsx';
import { ErrorNote, Pill } from '../components/ui.jsx';
import { gateSession, restoreGateMonitoring, selectGateMonitoring } from '../../../store/slices/gateMonitoringSlice.js';

const TABS = [['live', 'Live monitoring'], ['video', 'Uploaded Video Processing'], ['zones', 'Zones & Regions']];
// Old links keep working: each earlier ?view= value lands on the tab that now holds its content.
const LEGACY_VIEWS = { monitor: 'live', camera: 'live', alerts: 'live', events: 'live', calibration: 'zones' };

/** The selected video job's progress on every tab. Numbers come only from the backend's job status. */
function ProcessingBar({ job, fps }) {
  if (!job) return null;
  const percent = jobProgressPercent(job);
  const active = jobIsActive(job);
  const headline = job.status === 'PROCESSING' ? `Processing ${job.filename}` : `${videoJobStatus(job.status).label}: ${job.filename}`;
  const parts = [
    job.total_frames ? `${job.processed_frames} / ${job.total_frames} frames` : `${job.processed_frames} frames`,
    (job.processing_fps ?? fps) != null && job.processed_frames > 0 ? `${Number((job.processing_fps ?? fps).toFixed(1))} fps` : null,
    job.duration_seconds != null ? `video time ${formatClock(job.video_time_seconds)} of ${formatClock(job.duration_seconds)}` : null,
    active ? 'the live camera keeps running while the video is processed' : null,
  ].filter(Boolean);
  const failure = job.status === 'FAILED' ? (jobErrorMessage(job.error_code) || job.error) : '';
  return (
    <div className="mt-3">
      <p className="flex items-center justify-between gap-3 text-sm font-semibold text-[#0F1B3D]">
        <span className="min-w-0 truncate" title={job.filename}>{headline}</span>
        {percent != null && <span className="shrink-0 tabular-nums">{percent}%</span>}
      </p>
      <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-[#E3E7F0]" role="progressbar" aria-label="Video processing"
        {...(percent != null ? { 'aria-valuenow': percent, 'aria-valuemin': 0, 'aria-valuemax': 100 } : {})}>
        <div className={`h-full rounded-full ${job.status === 'FAILED' ? 'bg-rose-500' : 'bg-[#34479B]'} ${percent == null && active ? 'w-full animate-pulse opacity-40' : ''}`}
          style={percent != null ? { width: `${percent}%` } : undefined} />
      </div>
      <p className="mt-1.5 text-xs text-[#55607A]">{parts.join(' · ')}</p>
      {failure && <p role="alert" className="mt-1 text-xs text-rose-800">{failure}</p>}
    </div>
  );
}

export default function GrillGatePage() {
  const [timerNow, setTimerNow] = useState(() => Date.now());
  const [params, setParams] = useSearchParams();
  const dispatch = useDispatch();
  const gateMonitoring = useSelector(selectGateMonitoring);
  useEffect(() => {
    const tick = () => setTimerNow(Date.now());
    const interval = window.setInterval(tick, 1000);
    document.addEventListener('visibilitychange', tick);
    return () => {
      window.clearInterval(interval);
      document.removeEventListener('visibilitychange', tick);
    };
  }, []);
  const registry = useGrillGateRegistry();
  const requested = params.get('assignment');
  const item = registry.items.find((entry) => entry.assignment.id === requested) ?? registry.items[0] ?? null;
  const assignmentId = item?.assignment.id ?? '';
  const rawView = params.get('view');
  const view = rawView === 'video' || rawView === 'zones' ? rawView : LEGACY_VIEWS[rawView] ?? 'live';

  const setParam = (name, value) => setParams((current) => {
    const next = new URLSearchParams(current);
    if (value == null || (name === 'view' && value === 'live')) next.delete(name); else next.set(name, value);
    return next;
  }, { replace: name !== 'view' });

  useEffect(() => {
    if (rawView && LEGACY_VIEWS[rawView]) setParam('view', LEGACY_VIEWS[rawView]);
  }, [rawView]); // eslint-disable-line react-hooks/exhaustive-deps

  // Two independent sources, each with its own store. A tab only ever reads its own.
  const workers = useGrillGateWorkers(assignmentId);
  const zones = useAssignmentZones(assignmentId);
  const worker = workerForAssignment(workers.workers, assignmentId);
  const live = useLiveMonitoring(assignmentId, workerIsActive(worker));
  const connection = connectionView(worker, { statusError: workers.error, loaded: workers.loaded });

  const upload = useVideoUpload();
  const [listKey, setListKey] = useState(0);
  const requestedJob = params.get('job');
  const selectionList = useVideoJobList(listKey);
  // Without a choice in the URL, the newest saved video is selected so the top bar can follow it.
  const selectedJobId = requestedJob ?? selectionList.jobs[0]?.job_id ?? null;
  const videoJob = useVideoJob(selectedJobId);
  const { job, monitoring: resultMonitoring, events, transitions, alerts, alertsAvailable } = videoJob;
  // Alert source selection survives tab changes and monitoring/timer resets.
  const [videoAlertJobId, setVideoAlertJobId] = useState(null);
  useEffect(() => {
    if (job?.job_id === selectedJobId) setVideoAlertJobId((previous) => videoAlertSession(previous, job));
  }, [selectedJobId, job?.job_id, job?.status, job?.started_at]);

  const liveSessionId = assignmentId ? `live:${assignmentId}` : null;
  const videoSessionId = selectedJobId ? `video:${selectedJobId}` : null;
  const activeSessionId = view === 'live' ? liveSessionId : view === 'video' ? videoSessionId : null;
  useEffect(() => {
    if (activeSessionId) dispatch(restoreGateMonitoring({ sessionId: activeSessionId }));
  }, [activeSessionId, dispatch]);

  const liveClassification = gateSession(gateMonitoring, liveSessionId);
  const videoClassification = gateSession(gateMonitoring, videoSessionId);
  const liveView = useMemo(() => liveMonitoring({ ...live, now: timerNow }, liveClassification), [live, timerNow,
    liveClassification.gateState, liveClassification.direction, liveClassification.sessionId,
    liveClassification.transitions, liveClassification.cycleStartedAt, liveClassification.lastCrossingAt]);
  const videoView = useMemo(() => videoMonitoring({ job, monitoring: resultMonitoring, gateClassification: videoClassification,
    events, transitions, alerts, alertsAvailable }), [job, resultMonitoring,
    videoClassification.gateState, videoClassification.direction, videoClassification.sessionId,
    videoClassification.transitions, videoClassification.cycleStartedAt, videoClassification.lastCrossingAt,
    videoClassification.videoTimestampSeconds, videoClassification.videoProcessingStatus,
    videoClassification.gateOpenedAt, videoClassification.videoGateOpenStoppedSeconds,
    events, transitions, alerts, alertsAvailable]);
  useEffect(() => {
    evaluateOpenTimer(liveView).then(() => {
      const cycle = `${liveView.gateSessionId}:${liveView.cycleStartedAt}`;
      if (gateSession(store.getState().gateMonitoring, liveView.gateSessionId).alertRequests?.[cycle]?.status === 'ALERT_RAISED'
          && !liveView.alerts.some((a) => a.type === 'GATE_OPEN_TOO_LONG')) live.refresh();
    });
    evaluateOpenTimer(videoView).then(() => {
      const cycle = `${videoView.gateSessionId}:${videoView.cycleStartedAt}`;
      if (gateSession(store.getState().gateMonitoring, videoView.gateSessionId).alertRequests?.[cycle]?.status === 'ALERT_RAISED'
          && !videoView.alerts.some((a) => a.type === 'GATE_OPEN_TOO_LONG')) videoJob.refresh();
    });
  }, [liveView, videoView]);
  const jobStatus = job?.status;
  useEffect(() => { setListKey((value) => value + 1); }, [selectedJobId, jobStatus]);
  useEffect(() => { if (videoJob.notFound && requestedJob) setParam('job', null); }, [videoJob.notFound, requestedJob]); // eslint-disable-line react-hooks/exhaustive-deps

  const [busy, setBusy] = useState(null);
  const [actionError, setActionError] = useState('');
  const selectedRef = useRef(assignmentId);
  selectedRef.current = assignmentId;
  useEffect(() => { setActionError(''); }, [assignmentId]);

  /** Results for an assignment the operator has since moved away from are dropped. */
  const runAction = async (kind, call) => {
    const target = assignmentId;
    if (!target || busy) return;
    setBusy(kind); setActionError('');
    try {
      await call(target);
    } catch (exception) {
      if (selectedRef.current === target) setActionError(describeError(exception).message);
    } finally {
      setBusy(null);
      workers.refresh();
      live.refresh();
    }
  };

  const liveTone = connection.key === 'connected' ? 'ok' : connection.tone;
  const liveLabel = item ? connection.label.toUpperCase() : 'NOT CONNECTED';

  return (
    <div className="-m-4 min-h-[calc(100vh-4.5rem)] bg-[#F4F6FB] p-4 text-[#1C2B4D] sm:-m-6 sm:p-6">
      <header className="rounded-xl border border-[#E3E7F0] bg-white p-4 sm:p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-xl font-bold text-[#0F1B3D]">Grill Gate Monitoring</h2>
          <div className="flex flex-wrap items-center gap-2">
            <Pill tone={liveTone} className="!rounded-full">Live camera · {liveLabel}</Pill>
            <Pill tone={job ? videoJobStatus(job.status).tone : 'idle'} className="!rounded-full">Video job · {jobPillLabel(job)}</Pill>
          </div>
        </div>
        <ProcessingBar job={job} fps={videoJob.fps} />
      </header>

      <nav className="my-4 flex flex-wrap gap-2" aria-label="Grill Gate sections">
        {TABS.map(([id, text]) => (
          <button key={id} type="button" aria-current={view === id ? 'page' : undefined} onClick={() => setParam('view', id)}
            className={`min-h-10 rounded-lg px-4 text-sm font-semibold transition ${view === id ? 'bg-[#34479B] text-white' : 'bg-white text-[#34479B] ring-1 ring-[#E3E7F0] hover:bg-[#F4F6FB]'}`}>
            {text}
          </button>
        ))}
      </nav>

      {registry.error && <div className="mb-4"><ErrorNote>Could not load Grill Gate camera assignments: {registry.error}</ErrorNote></div>}
      {registry.loading && !registry.items.length && <p className="mb-4 text-sm text-[#55607A]">Loading Grill Gate camera assignments…</p>}

      {view === 'live' && (
        <LiveCameraSection items={registry.items} item={item} worker={worker} connection={connection} statusError={workers.error}
          busy={busy} actionError={actionError} monitoring={liveView} live={live}
          onConnect={() => runAction('connect', connectGrillGateAssignment)}
          onDisconnect={() => runAction('disconnect', disconnectGrillGateAssignment)}
          onSelect={(id) => setParam('assignment', id)} onRegistryChanged={registry.reload} />
      )}
      {view === 'video' && (
        <UploadedVideoSection alertJobId={videoAlertJobId} videoJob={videoJob} jobs={selectionList.jobs} jobsError={selectionList.error} selectedJobId={selectedJobId}
          onSelectJob={(id) => setParam('job', id)} onJobsChanged={() => setListKey((value) => value + 1)} upload={upload} monitoring={videoView}
          assignmentItem={item}
          onOpenZones={() => setParams((current) => { const next = new URLSearchParams(current); next.set('view', 'zones'); next.set('apply', 'video'); return next; })} />
      )}
      {view === 'zones' && (
        <ZonesSection apply={params.get('apply')} onApplyChange={(value) => setParam('apply', value)} assignmentItem={item} job={job}
          otherJobs={selectionList.jobs.filter((row) => row.job_id !== job?.job_id)} liveZones={zones.zones} zoneTypes={registry.zoneTypes} worker={worker}
          reloadLiveZones={zones.reload} onLiveCalibrationSaved={registry.replaceAssignment} onVideoConfigSaved={() => videoJob.refresh()}
          onZoneConfigurationsChanged={() => setListKey((value) => value + 1)} />
      )}
    </div>
  );
}
