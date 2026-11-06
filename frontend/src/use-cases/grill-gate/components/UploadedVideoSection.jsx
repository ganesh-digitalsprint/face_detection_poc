import { useRef, useState } from 'react';
import { Upload } from 'lucide-react';
import { describeError } from '../../../utils/errors.js';
import {
  acknowledgeGrillGateAlert, cancelGrillGateVideoJob, deleteGrillGateVideoJob, getVideoJobFrame, getVideoJobPreview,
  resolveGrillGateAlert, startGrillGateVideoJob,
} from '../api/grillGate.js';
import { formatClock } from '../grillGateModel.js';
import { useAuthorizedJpeg } from '../hooks/useSourceData.js';
import {
  jobCanCancel, jobCanStart, jobErrorMessage, jobIsActive, validateVideoFile, videoJobStatus,
} from '../videoJobModel.js';
import { AlertsPanel, CrossingEventsPanel, GateStatePanel, MeshPanel, MonitoringStats, PreviewStage, TimelinePanel } from './MonitoringPanels.jsx';
import { btnGhost, btnPrimary, Card, ErrorNote, Pill } from './ui.jsx';

const ACCEPT = 'video/mp4,video/x-msvideo,video/avi,.mp4,.avi';
const stamp = (iso) => (iso ? new Date(iso).toLocaleString() : '—');

function FilePicker({ label, className, disabled, onFile }) {
  const inputRef = useRef(null);
  return (
    <>
      <button type="button" className={className} disabled={disabled} onClick={() => inputRef.current?.click()}>{label}</button>
      <input ref={inputRef} className="sr-only" type="file" accept={ACCEPT} aria-label={`${label}: choose an MP4 or AVI file`} tabIndex={-1}
        onChange={(event) => { const file = event.target.files?.[0]; event.target.value = ''; if (file) onFile(file); }} />
    </>
  );
}

function SavedVideoCard({ job, busy, disabled, onReplace, onDelete, onOpenZones }) {
  const facts = [
    job.width && job.height ? `${job.width} × ${job.height}` : null,
    job.fps ? `${Number(job.fps.toFixed(2))} fps` : null,
    job.duration_seconds != null ? formatClock(job.duration_seconds) : null,
    job.total_frames ? `${job.total_frames} frames` : null,
  ].filter(Boolean);
  const readiness = job.readiness ?? {};
  const checks = [
    ['video_saved', 'Video saved on the server', false],
    ['gate_zone_defined', 'Gate zone drawn (Sliding gate leaf)', true],
    ['calibration_matches_frame', job.width ? `Calibration matches the ${job.width} × ${job.height} frame` : 'Calibration matches the frame', true],
  ];
  const active = jobIsActive(job);
  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="flex flex-wrap items-center gap-2 text-[15px] font-semibold text-[#0F1B3D]">
            <span className="min-w-0 truncate" title={job.filename}>{job.filename}</span>
            <Pill tone={job.video_available ? 'ok' : 'idle'} className="!rounded-full">{job.video_available ? 'Saved' : 'Video removed'}</Pill>
          </p>
          <p className="mt-0.5 text-xs text-[#55607A]">{facts.join(' · ')}</p>
        </div>
        <div className="flex shrink-0 gap-2">
          <FilePicker label="Replace" className={btnGhost} disabled={disabled || active} onFile={onReplace} />
          <button type="button" className={btnGhost} disabled={busy || active} onClick={onDelete}>{busy ? 'Deleting…' : 'Delete'}</button>
        </div>
      </div>
      <ul className="mt-3 space-y-1.5 text-sm">
        {checks.map(([key, text, linked]) => (
          <li key={key} className={readiness[key] ? 'text-[#55607A]' : 'text-amber-800'}>
            {readiness[key] ? '✓ ' : '○ '}{text}
            {!readiness[key] && linked && job.editable && <button type="button" className="ml-2 text-xs font-semibold text-[#34479B] underline" onClick={onOpenZones}>Set up in Zones &amp; Regions</button>}
          </li>
        ))}
      </ul>
    </Card>
  );
}

function SavedVideoList({ jobs, error, selectedId, onSelect }) {
  if (!jobs.length && !error) return null;
  return (
    <Card title="Saved videos">
      {error && <ErrorNote>{error}</ErrorNote>}
      <ul className="max-h-48 space-y-1 overflow-y-auto">
        {jobs.map((row) => {
          const status = videoJobStatus(row.status);
          return (
            <li key={row.job_id}>
              <button type="button" aria-pressed={row.job_id === selectedId} onClick={() => onSelect(row.job_id)}
                className={`flex w-full flex-wrap items-center gap-x-3 gap-y-1 rounded-md px-2 py-1.5 text-left text-xs ring-1 ${row.job_id === selectedId ? 'bg-[#EEF1FA] ring-[#34479B]' : 'bg-white ring-[#E3E7F0] hover:bg-[#F7F8FC]'}`}>
                <span className="min-w-0 flex-1 truncate font-semibold text-[#0F1B3D]" title={row.filename}>{row.filename}</span>
                <span className="text-[#55607A]">{stamp(row.created_at)}</span>
                <Pill tone={status.tone}>{status.label}</Pill>
              </button>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

function JobPreview({ job, onProcess, onCancel, action }) {
  const processed = job.processed_frames > 0;
  // A JPEG through the authenticated client: the newest processed frame, or the first frame before processing.
  const image = useAuthorizedJpeg(
    (signal) => (processed ? getVideoJobPreview(job.job_id, signal) : getVideoJobFrame(job.job_id, 0, signal)),
    job.video_available ? `${job.job_id}:${job.processed_frames}:${job.status}` : null,
  );
  const running = jobIsActive(job);
  const ready = job.readiness?.ready;
  return (
    <Card title={processed ? (running ? 'Processed preview' : 'Last processed frame') : 'Video preview'}>
      <PreviewStage url={image.url} alt={`Frame from ${job.filename}`} aspect={job.width && job.height ? job.width / job.height : 16 / 9}
        message={!job.video_available ? 'The stored video is no longer available.' : image.error || 'Loading frame…'} />
      <p className="mt-2 text-xs text-[#55607A]">Frames shown here come from the server. Detection runs only after Process Video.</p>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {jobCanStart(job) && (
          <button type="button" className={btnPrimary} onClick={onProcess} disabled={!ready || Boolean(action)}>{action === 'start' ? 'Starting…' : 'Process Video'}</button>
        )}
        {running && <button type="button" className={btnPrimary} disabled>Processing…</button>}
        {(running || jobCanCancel(job)) && (
          <button type="button" className={btnGhost} onClick={onCancel} disabled={Boolean(action) || job.status === 'CANCEL_REQUESTED'}>
            {action === 'cancel' ? 'Cancelling…' : job.status === 'UPLOADED' ? 'Discard' : 'Cancel'}
          </button>
        )}
        {jobCanStart(job) && !ready && <span className="text-xs text-amber-800">Finish the checklist above to enable processing.</span>}
      </div>
    </Card>
  );
}

function gateNote(job, monitoring) {
  if (!job) return 'Upload a video to see its results.';
  if (jobCanStart(job)) return 'Select Process Video to start this job.';
  if (monitoring.gateState) return null;
  return jobIsActive(job) ? 'Waiting for the first gate measurement.' : 'This job reported no gate state.';
}

export default function UploadedVideoSection({ videoJob, jobs, jobsError, selectedJobId, onSelectJob, onJobsChanged, upload, monitoring, onOpenZones }) {
  const { job } = videoJob;
  const [action, setAction] = useState(null);
  const [actionError, setActionError] = useState('');
  const [fileError, setFileError] = useState('');
  const [busyAlertId, setBusyAlertId] = useState(null);
  const [alertError, setAlertError] = useState('');
  const uploading = upload.phase === 'uploading';

  const send = async (file, replacing) => {
    const problem = validateVideoFile(file);
    setFileError(problem);
    if (problem) return;
    setActionError('');
    const saved = await upload.upload(file, null, `${file.name}:${file.size}:${file.lastModified}`);
    if (!saved) return;
    if (replacing) {
      try { await deleteGrillGateVideoJob(replacing); } catch (exception) { setActionError(describeError(exception).message); }
    }
    onSelectJob(saved.job_id);
    onJobsChanged();
  };

  const replace = (file) => {
    if (window.confirm(`Replace “${job.filename}” with “${file.name}”? The current video, its zones and its results are deleted.`)) send(file, job.job_id);
  };

  const run = async (kind, call) => {
    if (action || !job) return;
    setAction(kind); setActionError('');
    try {
      await call(job.job_id);
    } catch (exception) {
      setActionError(describeError(exception).message);
    } finally {
      setAction(null);
      videoJob.refresh();
    }
  };

  const remove = async () => {
    if (!window.confirm(`Delete “${job.filename}”, its zones and its results?`)) return;
    setAction('delete'); setActionError('');
    try {
      await deleteGrillGateVideoJob(job.job_id);
      onSelectJob(null);
      onJobsChanged();
    } catch (exception) {
      setActionError(describeError(exception).message);
    } finally {
      setAction(null);
    }
  };

  const actOnAlert = async (alert, kind) => {
    const note = kind === 'resolve' ? window.prompt('Resolution note (required):') : null;
    if (kind === 'resolve' && !note?.trim()) return;
    setBusyAlertId(alert.id); setAlertError('');
    try {
      if (kind === 'acknowledge') await acknowledgeGrillGateAlert(alert.id, alert.version);
      else await resolveGrillGateAlert(alert.id, alert.version, note.trim());
    } catch (exception) {
      setAlertError(describeError(exception).message);
    } finally {
      setBusyAlertId(null);
      videoJob.refresh();
    }
  };

  const failure = job?.status === 'FAILED' ? (jobErrorMessage(job.error_code) || job.error || 'Processing failed.') : '';
  return (
    <div className="space-y-4">
      {uploading && (
        <div className="rounded-xl border border-[#E3E7F0] bg-white p-4">
          <p className="text-sm font-semibold text-[#0F1B3D]">Uploading{upload.progress == null ? '…' : ` ${Math.round(upload.progress * 100)}%`}</p>
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-[#E3E7F0]"><div className="h-full rounded-full bg-[#34479B]" style={{ width: `${Math.round((upload.progress ?? 0) * 100)}%` }} /></div>
        </div>
      )}
      {upload.phase === 'failed' && <ErrorNote>Upload failed: {upload.error}</ErrorNote>}
      {fileError && <ErrorNote>{fileError}</ErrorNote>}
      {actionError && <ErrorNote>{actionError}</ErrorNote>}
      {failure && <ErrorNote>{failure}</ErrorNote>}
      {videoJob.notFound && <ErrorNote>{videoJob.error}</ErrorNote>}
      {videoJob.error && !videoJob.notFound && <p role="status" className="text-xs text-amber-800">Could not refresh this job: {videoJob.error} Showing the last results; retrying.</p>}

      {!selectedJobId && !uploading && (
        <Card>
          <div className="flex min-h-32 flex-col items-center justify-center gap-2 text-center">
            <Upload size={24} className="text-[#34479B]" aria-hidden />
            <p className="font-semibold text-[#0F1B3D]">No video uploaded</p>
            <p className="text-xs text-[#55607A]">Upload an MP4 or AVI file. Uploading only saves it; processing starts when you choose Process Video.</p>
            <FilePicker label="Upload video" className={`${btnPrimary} mt-1`} disabled={uploading} onFile={(file) => send(file, null)} />
          </div>
        </Card>
      )}
      {selectedJobId && !job && !videoJob.notFound && !videoJob.error && <p className="text-sm text-[#55607A]">Loading video job…</p>}

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.7fr)_minmax(320px,1fr)]">
        <div className="min-w-0 space-y-4">
          {job && <SavedVideoCard job={job} busy={action === 'delete'} disabled={uploading} onReplace={replace} onDelete={remove} onOpenZones={onOpenZones} />}
          <MonitoringStats monitoring={monitoring} />
          <TimelinePanel monitoring={monitoring} note="Video time, not clock time." />
          <div className="flex justify-end">
            {selectedJobId && <FilePicker label="Upload another video" className={btnGhost} disabled={uploading} onFile={(file) => send(file, null)} />}
          </div>
          <SavedVideoList jobs={jobs} error={jobsError} selectedId={selectedJobId} onSelect={onSelectJob} />
        </div>
        <div className="min-w-0 space-y-4">
          <GateStatePanel monitoring={monitoring} note={gateNote(job, monitoring)} />
          <CrossingEventsPanel monitoring={monitoring} />
          <AlertsPanel monitoring={monitoring} onAction={actOnAlert} busyAlertId={busyAlertId} error={alertError} />
          <MeshPanel monitoring={monitoring} />
        </div>
      </div>
      {job && (
        <JobPreview job={job} action={action}
          onProcess={() => run('start', startGrillGateVideoJob)} onCancel={() => run('cancel', cancelGrillGateVideoJob)} />
      )}
    </div>
  );
}
