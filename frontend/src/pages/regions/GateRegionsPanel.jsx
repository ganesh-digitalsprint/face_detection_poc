import { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import * as gateApi from '../../use-cases/grill-gate/api/grillGate.js';
import { workerForAssignment } from '../../use-cases/grill-gate/grillGateModel.js';
import { useAssignmentZones, useGrillGateRegistry, useGrillGateWorkers } from '../../use-cases/grill-gate/hooks/useGrillGate.js';
import ZonesSection from '../../use-cases/grill-gate/components/ZonesSection.jsx';
import { describeError } from '../../utils/errors.js';
import { SERVICE_START } from './regionsModel.js';
import { listAllGateJobs } from './gateRegionsAdapter.js';

/** Reuses the exact Gate editor, including calibration, rules, polygons and video configurations. */
export default function GateRegionsPanel() {
  const [params, setParams] = useSearchParams();
  const registry = useGrillGateRegistry();
  const assignmentId = params.get('assignment') || registry.items[0]?.assignment.id || '';
  const assignmentItem = registry.items.find((item) => item.assignment.id === assignmentId) || null;
  const [jobs, setJobs] = useState([]);
  const jobId = params.get('job') || (!assignmentId ? jobs[0]?.job_id : '') || '';
  const [job, setJob] = useState(null);
  const [jobError, setJobError] = useState('');
  const [jobsLoading, setJobsLoading] = useState(true);
  const zones = useAssignmentZones(assignmentId);
  const workers = useGrillGateWorkers(assignmentId);
  const worker = workerForAssignment(workers.workers, assignmentId);
  const apply = params.get('apply') || (jobId ? 'video' : 'live');

  const setSelection = (changes) => setParams((current) => {
    const next = new URLSearchParams(current);
    for (const [key, value] of Object.entries(changes)) {
      if (value) next.set(key, value); else next.delete(key);
    }
    return next;
  });

  const loadJobs = useCallback(async () => {
    setJobsLoading(true);
    try {
      const items = await listAllGateJobs(gateApi);
      setJobs(items); setJobError('');
    } catch (error) { setJobError(describeError(error).message); }
    finally { setJobsLoading(false); }
  }, []);

  const loadJob = useCallback(async () => {
    if (!jobId) { setJob(null); return; }
    try { setJob(await gateApi.getGrillGateVideoJob(jobId)); setJobError(''); }
    catch (error) { setJob(null); setJobError(describeError(error).message); }
  }, [jobId]);

  useEffect(() => { loadJobs(); }, [loadJobs]);
  useEffect(() => { loadJob(); }, [loadJob]);
  const announceChange = () => window.dispatchEvent(new Event('fedbank:gate-zones-changed'));
  const reloadLiveZones = async () => { const result = await zones.reload(); announceChange(); return result; };
  const onVideoConfigSaved = () => { loadJob(); announceChange(); };
  const onZoneConfigurationsChanged = () => { loadJobs(); announceChange(); };

  if (registry.loading && !registry.items.length) return <p className="bx-muted" role="status">Loading Gate Monitoring zones…</p>;
  if (registry.error) return <div className="bx-diag" role="alert">Gate Monitoring service unavailable: {registry.error}. Start it in <code>{SERVICE_START.grill_gate.dir}</code> with <code>{SERVICE_START.grill_gate.cmd}</code>. <button type="button" className="bx-btn bx-btn-sm" onClick={registry.reload}>Retry</button></div>;

  return <div className="space-y-4 rounded-lg border border-slate-200 bg-white p-4 text-[#1C2B4D] dark:border-slate-700 dark:bg-slate-900 sm:p-5">
    <div className="flex flex-wrap gap-3">
      <label className="min-w-56 flex-1 text-sm font-medium">Gate camera
        <select className="bx-input mt-1 w-full" value={assignmentId} onChange={(event) => setSelection({ assignment: event.target.value, apply: 'live' })}>
          {!registry.items.length && <option value="">No Gate cameras yet</option>}
          {registry.items.map((item) => <option key={item.assignment.id} value={item.assignment.id}>{item.camera?.name || item.assignment.camera_id}</option>)}
        </select>
      </label>
      <label className="min-w-56 flex-1 text-sm font-medium">Uploaded video
        <select className="bx-input mt-1 w-full" value={jobId} onChange={(event) => setSelection({ job: event.target.value, apply: event.target.value ? 'video' : 'live' })}>
          <option value="">Choose a video</option>
          {jobs.map((item) => <option key={item.job_id} value={item.job_id}>{item.filename}</option>)}
        </select>
      </label>
    </div>
    {jobsLoading && <p role="status" className="bx-muted">Loading Gate videos…</p>}
    {jobError && <div role="alert" className="bx-diag">Gate videos: {jobError} <button type="button" className="bx-btn bx-btn-sm" onClick={loadJobs}>Retry</button></div>}
    {zones.error && <div role="alert" className="bx-diag">Gate camera zones: {zones.error} <button type="button" className="bx-btn bx-btn-sm" onClick={zones.reload}>Retry</button></div>}
    {!assignmentItem && !job && <p className="bx-muted">No zones for Gate Monitoring yet. Add a camera or upload a video on its own page.</p>}
    <ZonesSection apply={apply} onApplyChange={(value) => setSelection({ apply: value })}
      assignmentItem={assignmentItem} job={job} otherJobs={jobs.filter((item) => item.job_id !== jobId)}
      liveZones={zones.zones} zoneTypes={registry.zoneTypes} worker={worker}
      reloadLiveZones={reloadLiveZones} onLiveCalibrationSaved={registry.replaceAssignment}
      onVideoConfigSaved={onVideoConfigSaved} onZoneConfigurationsChanged={onZoneConfigurationsChanged} />
  </div>;
}
