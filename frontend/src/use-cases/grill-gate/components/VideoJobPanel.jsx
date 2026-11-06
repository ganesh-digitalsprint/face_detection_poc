import { useEffect, useState } from 'react';
import { Ban, CheckCircle2, Play, RefreshCw, Upload, Video } from 'lucide-react';
import { describeError } from '../../../utils/errors.js';
import { cancelGrillGateVideoJob, listGrillGateVideoJobs, startGrillGateVideoJob } from '../api/grillGate.js';
import {
  formatVideoTime, jobCanCancel, jobCanStart, jobErrorMessage, jobIsActive, jobProgressPercent,
  validateVideoFile, videoJobStatus, videoUploadConfiguration,
} from '../videoJobModel.js';
import { btnDanger, btnGhost, btnPrimary, ErrorNote, Pill } from './ui.jsx';

export const videoFileKey = (file) => (file ? `${file.name}:${file.size}:${file.lastModified}` : null);
const stamp = (iso) => (iso ? new Date(iso).toLocaleString() : '—');

function Metric({ label, value }) {
  return <div><dt className="text-xs text-[#55607A]">{label}</dt><dd className="mt-0.5 font-semibold tabular-nums text-[#0F1B3D]">{value}</dd></div>;
}

/** Reports only what GET /videos/{id} returns. Without a total the bar is indeterminate, never an estimate. */
function JobProgress({ videoJob }) {
  const { job, fps, error } = videoJob;
  const percent = jobProgressPercent(job);
  const active = jobIsActive(job);
  const failure = job.status === 'FAILED' ? jobErrorMessage(job.error_code) || 'Processing failed.' : '';
  return (
    <div className="mt-3 border-t border-[#E3E7F0] pt-3">
      {(active || percent != null) && (
        <div className="mb-3 h-1.5 overflow-hidden rounded-full bg-[#E3E7F0]" role="progressbar" aria-label="Video processing"
          {...(percent != null ? { 'aria-valuenow': percent, 'aria-valuemin': 0, 'aria-valuemax': 100 } : {})}>
          {/* No total is reported, so a running job gets a full-width pulse: it must not read as a percentage. */}
          <div className={`h-full rounded-full ${percent == null ? 'w-full animate-pulse bg-[#34479B]/40' : 'bg-[#34479B]'}`} style={percent == null ? undefined : { width: `${percent}%` }} />
        </div>
      )}
      <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
        <Metric label="Progress" value={percent == null ? 'Not reported' : `${percent}%`} />
        <Metric label="Processed frames" value={job.frame_count} />
        <Metric label="Total frames" value="Not reported" />
        <Metric label="Processing FPS" value={fps == null ? '—' : fps.toFixed(1)} />
        <Metric label="Video position" value={formatVideoTime(job.progress_seconds)} />
        <Metric label="Uploaded" value={stamp(job.created_at)} />
        <Metric label="Started" value={stamp(job.started_at)} />
        <Metric label="Finished" value={stamp(job.completed_at)} />
      </dl>
      {failure && <div className="mt-3"><ErrorNote>{failure}</ErrorNote></div>}
      {error && <p role="status" className="mt-3 text-xs text-amber-800">Could not refresh this job: {error} Showing the last results; retrying.</p>}
    </div>
  );
}

function JobHistory({ jobs, error, loading, selectedId, selectedJob, onSelect, onRefresh }) {
  return (
    <div className="mt-3 border-t border-[#E3E7F0] pt-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <p className="text-sm font-semibold text-[#0F1B3D]">Saved videos</p>
        <button type="button" className={btnGhost} onClick={onRefresh} disabled={loading}><RefreshCw size={13} aria-hidden /> Refresh</button>
      </div>
      {error && <ErrorNote>{error}</ErrorNote>}
      {!error && !jobs.length && <p className="text-xs text-[#55607A]">{loading ? 'Loading saved videos…' : 'No saved videos yet.'}</p>}
      <ul className="max-h-56 space-y-1 overflow-y-auto">
        {jobs.map((row) => {
          // The list refreshes on status changes; the selected row can use the fresher polled job.
          const job = row.job_id === selectedJob?.job_id ? selectedJob : row;
          const status = videoJobStatus(job.status);
          return (
            <li key={job.job_id}>
              <button type="button" aria-pressed={job.job_id === selectedId} onClick={() => onSelect(job.job_id)}
                className={`flex w-full flex-wrap items-center gap-x-3 gap-y-1 rounded-md px-2 py-1.5 text-left text-xs ring-1 ${job.job_id === selectedId ? 'bg-[#EEF1FA] ring-[#34479B]' : 'bg-white ring-[#E3E7F0] hover:bg-[#F7F8FC]'}`}>
                <span className="min-w-0 flex-1 truncate font-semibold text-[#0F1B3D]" title={job.filename}>{job.filename}</span>
                <span className="text-[#55607A]">{stamp(job.created_at)}</span>
                <span className="tabular-nums text-[#55607A]">{job.frame_count} frames</span>
                <Pill tone={status.tone}>{status.label}</Pill>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/** Save the selected file as a job, start it explicitly, and choose which job the dashboard shows. */
export default function VideoJobPanel({ file, item, zones, upload, videoJob, selectedJobId, onSelectJob }) {
  const { job } = videoJob;
  const [action, setAction] = useState(null);
  const [startedId, setStartedId] = useState(null);
  const [actionError, setActionError] = useState('');
  const [history, setHistory] = useState({ jobs: [], error: '', loading: true });

  const fileKey = videoFileKey(file);
  const fileError = file ? validateVideoFile(file) : '';
  const uploadConfiguration = file && !fileError ? videoUploadConfiguration(item, zones, file) : { value: null, blocker: '' };
  const blocker = uploadConfiguration.blocker;
  const uploading = upload.phase === 'uploading';
  const savedThisFile = upload.phase === 'saved' && upload.fileKey === fileKey;
  const uploadFailed = upload.phase === 'failed' && upload.fileKey === fileKey;
  const starting = action === 'start' || (startedId === job?.job_id && jobCanStart(job));
  const canProcess = jobCanStart(job) && !uploading && !starting && !action;

  const loadHistory = async () => {
    setHistory((current) => ({ ...current, loading: true }));
    try {
      const page = await listGrillGateVideoJobs();
      setHistory({ jobs: page.items, error: '', loading: false });
    } catch (exception) {
      setHistory((current) => ({ ...current, error: describeError(exception).message, loading: false }));
    }
  };
  // Re-read the list whenever the selected job changes status, so saved rows do not show a stale state.
  useEffect(() => { loadHistory(); }, [selectedJobId, job?.status]);
  useEffect(() => { setActionError(''); }, [selectedJobId]);

  const save = async () => {
    if (uploading || fileError || blocker) return;
    const saved = await upload.upload(file, uploadConfiguration.value, fileKey);
    if (!saved) return;
    onSelectJob(saved.job_id);
    setAction('start'); setActionError('');
    try {
      await startGrillGateVideoJob(saved.job_id);
      setStartedId(saved.job_id);
    } catch (exception) {
      setActionError(describeError(exception).message);
    } finally {
      setAction(null);
      videoJob.refresh();
    }
  };
  const run = async (kind, call) => {
    if (action || !job) return;
    setAction(kind); setActionError('');
    try {
      await call(job.job_id);
      if (kind === 'start') setStartedId(job.job_id);
    } catch (exception) {
      setActionError(describeError(exception).message);
    } finally {
      setAction(null);
      videoJob.refresh();
    }
  };

  const status = job ? videoJobStatus(job.status) : null;
  return (
    <div className="mb-4 rounded-lg border border-[#E3E7F0] bg-white p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-sm font-semibold text-[#0F1B3D]">Video processing</p>
          <p className="text-xs text-[#55607A]">Runs on the server and never connects or changes a camera.</p>
        </div>
        {status && <Pill tone={status.tone} dot>{status.label}</Pill>}
      </div>

      {!file && !selectedJobId && <p className="mt-3 text-sm text-[#55607A]">No video uploaded. Choose an MP4 or AVI file below, or select a saved video.</p>}

      {file && !savedThisFile && (
        <div className="mt-3 flex flex-wrap items-center gap-2 rounded-md bg-[#F7F8FC] p-2">
          <Video size={15} className="shrink-0 text-[#34479B]" aria-hidden />
          <span className="min-w-0 flex-1 truncate text-sm text-[#0F1B3D]" title={file.name}>{file.name}</span>
          <button type="button" className={btnPrimary} onClick={save} disabled={uploading || Boolean(fileError) || Boolean(blocker)}>
            <Upload size={13} aria-hidden /> {uploading ? `Uploading${upload.progress == null ? '…' : ` ${Math.round(upload.progress * 100)}%`}` : action === 'start' ? 'Starting…' : 'Upload & process'}
          </button>
          {(fileError || blocker) && <p className="w-full text-xs text-amber-800">{fileError || blocker}</p>}
          {!fileError && !blocker && !uploading && !uploadFailed && <p className="w-full text-xs text-[#55607A]">{uploadConfiguration.source === 'assignment'
            ? `Saving copies the zones and calibration currently saved on ${item?.camera?.name ?? 'this assignment'}. Later edits do not change this video.`
            : 'Saving sends this video’s locally saved zones, line, and a provisional gate calibration. You do not need to assign a camera.'} Save configuration changes before uploading.</p>}
        </div>
      )}
      {uploadFailed && <div className="mt-3"><ErrorNote>Upload failed: {upload.error}</ErrorNote></div>}

      {selectedJobId && !job && !videoJob.notFound && !videoJob.error && <p className="mt-3 text-sm text-[#55607A]">Loading video job…</p>}
      {videoJob.notFound && <div className="mt-3"><ErrorNote>{videoJob.error}</ErrorNote></div>}
      {!job && videoJob.error && !videoJob.notFound && <div className="mt-3"><ErrorNote>Could not load this video job: {videoJob.error}</ErrorNote></div>}

      {job && (
        <>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <span className="flex min-w-0 flex-1 items-center gap-1.5 text-sm font-semibold text-[#0F1B3D]">
              <CheckCircle2 size={15} className="shrink-0 text-emerald-600" aria-hidden />
              <span className="truncate" title={job.filename}>{job.filename}</span>
              <span className="shrink-0 text-xs font-normal text-[#55607A]">Saved</span>
            </span>
            {jobCanStart(job) && (
              <button type="button" className={btnPrimary} onClick={() => run('start', startGrillGateVideoJob)} disabled={!canProcess}>
                <Play size={13} aria-hidden /> {starting ? 'Starting…' : 'Process Video'}
              </button>
            )}
            {jobCanCancel(job) && (
              <button type="button" className={btnDanger} onClick={() => run('cancel', cancelGrillGateVideoJob)} disabled={Boolean(action)}>
                <Ban size={13} aria-hidden /> {action === 'cancel' ? 'Cancelling…' : jobCanStart(job) ? 'Discard' : 'Cancel job'}
              </button>
            )}
          </div>
          {actionError && <div className="mt-3"><ErrorNote>{actionError}</ErrorNote></div>}
          {jobCanStart(job) ? <p className="mt-2 text-xs text-[#55607A]">Ready to process. A video can be processed once, because the server deletes its copy afterwards.</p> : <JobProgress videoJob={videoJob} />}
        </>
      )}

      <JobHistory {...history} selectedId={selectedJobId} selectedJob={job} onSelect={onSelectJob} onRefresh={loadHistory} />
    </div>
  );
}
