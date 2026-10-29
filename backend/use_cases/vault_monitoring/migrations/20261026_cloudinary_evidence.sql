-- Stage 2: authenticated Cloudinary delivery and idempotent metadata identity.
ALTER TABLE vault_evidence
    ADD COLUMN storage_delivery_type VARCHAR(24) NOT NULL DEFAULT 'authenticated';
ALTER TABLE vault_evidence
    ADD CONSTRAINT ck_vault_evidence_delivery_type
        CHECK (storage_delivery_type IN ('authenticated'));
ALTER TABLE vault_evidence
    ADD CONSTRAINT uq_vault_evidence_storage_public_id
        UNIQUE (storage_provider, storage_public_id);
