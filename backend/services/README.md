# Independently deployable services

- `alert_service/` contains the independent common Alert Service v1 implementation. Its contract is documented at `docs/alert-service-contract.md`; it has no Vault or Branch adapters yet.
- `evidence_service/` remains a planned boundary marker. Provider ownership and compatibility decisions are still open in the repository migration plan.
- The optional Stream Service remains deferred because the audit did not justify extracting either current stream pipeline.
