ALTER TABLE grill_gate_events ALTER COLUMN camera_id DROP NOT NULL;
ALTER TABLE grill_gate_events ALTER COLUMN assignment_id DROP NOT NULL;
ALTER TABLE grill_gate_events ADD COLUMN source_type VARCHAR(24) NOT NULL DEFAULT 'LIVE_CAMERA';
ALTER TABLE grill_gate_events ADD COLUMN video_job_id UUID NULL;
ALTER TABLE grill_gate_events ADD COLUMN video_time_seconds DOUBLE PRECISION NULL;
ALTER TABLE grill_gate_events ADD COLUMN template_assignment_id UUID NULL;
CREATE INDEX ix_grill_gate_events_video_job_time ON grill_gate_events (video_job_id, video_time_seconds);

CREATE TABLE grill_gate_video_jobs (
  id UUID PRIMARY KEY,
  original_filename VARCHAR(255) NOT NULL,
  storage_path TEXT NOT NULL,
  status VARCHAR(24) NOT NULL,
  template_assignment_id UUID NULL,
  config_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
  frame_count INTEGER NOT NULL DEFAULT 0,
  progress_seconds DOUBLE PRECISION NOT NULL DEFAULT 0,
  error_code VARCHAR(64) NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  started_at TIMESTAMPTZ NULL,
  completed_at TIMESTAMPTZ NULL
);
CREATE INDEX ix_grill_gate_video_jobs_status_created ON grill_gate_video_jobs (status, created_at);
