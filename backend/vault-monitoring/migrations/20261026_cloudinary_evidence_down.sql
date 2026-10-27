-- Rollback Stage 2 metadata additions. Cloudinary assets are not deleted.
ALTER TABLE vault_evidence
    DROP CONSTRAINT uq_vault_evidence_storage_public_id,
    DROP CONSTRAINT ck_vault_evidence_delivery_type,
    DROP COLUMN storage_delivery_type;
