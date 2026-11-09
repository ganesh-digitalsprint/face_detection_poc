ALTER TABLE grill_gate_video_jobs
  ADD COLUMN asset_job_id UUID NULL REFERENCES grill_gate_video_jobs(id);
CREATE INDEX ix_grill_gate_video_jobs_asset_job_id ON grill_gate_video_jobs (asset_job_id);

CREATE TABLE grill_gate_zone_configurations (
  id UUID PRIMARY KEY,
  owner_id VARCHAR(128) NOT NULL,
  name VARCHAR(120) NOT NULL,
  reference_width INTEGER NOT NULL,
  reference_height INTEGER NOT NULL,
  config_json JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_grill_gate_zone_configs_owner_name UNIQUE (owner_id, name)
);
CREATE INDEX ix_grill_gate_zone_configurations_owner_id ON grill_gate_zone_configurations (owner_id);
