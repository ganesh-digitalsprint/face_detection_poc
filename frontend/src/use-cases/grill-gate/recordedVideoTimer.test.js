import assert from 'node:assert/strict';
import { test } from 'node:test';
import { recordedVideoTimer } from './recordedVideoTimer.js';
import { videoMonitoring } from './videoJobModel.js';
import { createOpenTimerController } from './openTimerController.js';

const job={job_id:'job-1',status:'COMPLETED',alert_configuration:{max_gate_open_seconds:3}};
const incident=(more={})=>({id:'saved-incident',video_job_id:'job-1',source_event_type:'GATE_OPEN_TOO_LONG',status:'RESOLVED',triggered_at:'2026-11-11T14:02:18Z',gate_open_duration_seconds:336.341,configured_threshold_seconds:3,domain_data:{video_time_seconds:19.7},...more});

test('restores the persisted 336.341-second incident duration for completed jobs without a Redux cycle',()=>{
  const view=videoMonitoring({job,alerts:[incident()]});
  assert.equal(view.recordedTimerDisplay.elapsedSeconds,336.341);
  assert.equal(view.recordedTimerDisplay.thresholdSeconds,3);
  assert.equal(view.recordedTimerDisplay.source,'alert');
  assert.equal(view.openWithoutCrossingSeconds,null);
  assert.equal(view.cycleStartedAt,null);
  assert.equal(view.timerRecorded,false);
});

test('restored presentation never starts a cycle or triggers another threshold request',async()=>{
  let calls=0,writes=0;
  const evaluate=createOpenTimerController({read:()=>null,write:()=>writes++,request:async()=>calls++});
  const view=videoMonitoring({job,alerts:[incident()],gateClassification:{gateState:'FULLY_OPEN',sessionId:'video:job-1'}});
  await evaluate(view);
  assert.equal(calls,0);assert.equal(writes,0);
});

test('saved final monitoring is preferred over a historical incident, including a legitimate zero',()=>{
  const result=recordedVideoTimer({job,monitoring:{open_without_crossing_seconds:0,video_timestamp:40},alerts:[incident()]});
  assert.equal(result.elapsedSeconds,0);assert.equal(result.source,'monitoring');
});

test('uses the most recent incident, never the largest earlier duration',()=>{
  const latest=incident({id:'later',gate_open_duration_seconds:8,domain_data:{video_time_seconds:30}});
  assert.equal(recordedVideoTimer({job,alerts:[incident(),latest]}).elapsedSeconds,8);
});

test('ignores other jobs, other alert types and invalid persisted durations',()=>{
  for(const row of [incident({video_job_id:'other'}),incident({source_event_type:'MESH_OCCUPANCY_LIMIT_EXCEEDED'}),incident({gate_open_duration_seconds:-1}),incident({gate_open_duration_seconds:NaN})]) {
    assert.equal(recordedVideoTimer({job,alerts:[row]}),null);
  }
});

test('does not change active processing presentation and tolerates old records without persistence',()=>{
  assert.equal(recordedVideoTimer({job:{...job,status:'PROCESSING'},alerts:[incident()]}),null);
  assert.equal(recordedVideoTimer({job,alerts:[]}),null);
  const domainRecord=incident({video_job_id:null,gate_open_duration_seconds:null,configured_threshold_seconds:null,domain_data:{video_job_id:'job-1',gate_open_duration_seconds:336.341,configured_threshold_seconds:3}});
  assert.equal(recordedVideoTimer({job,alerts:[domainRecord]}).elapsedSeconds,336.341);
});
