DROP TABLE grill_gate_video_jobs;
DROP INDEX ix_grill_gate_events_video_job_time;
ALTER TABLE grill_gate_events DROP COLUMN template_assignment_id;
ALTER TABLE grill_gate_events DROP COLUMN video_time_seconds;
ALTER TABLE grill_gate_events DROP COLUMN video_job_id;
ALTER TABLE grill_gate_events DROP COLUMN source_type;
ALTER TABLE grill_gate_events ALTER COLUMN assignment_id SET NOT NULL;
ALTER TABLE grill_gate_events ALTER COLUMN camera_id SET NOT NULL;
