# Configuration migration

The approved structure reserves root configuration files. Stage 2 does not add placeholder YAML: the existing model configuration remains under `backend/vault-monitoring/config/models.yaml`, and no canonical root inputs were identified for alerts, evidence, branches, or shared app settings. Copy and split existing values only in a later reviewed migration step.
