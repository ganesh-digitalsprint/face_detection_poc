# Production Compose deployment

This is a single-host production baseline for the whole Fedbank UI: Vault Monitoring, Branch Exterior Monitoring, the Alert Service, PostgreSQL, an Nginx frontend/reverse proxy, and Caddy-managed HTTPS. Qdrant and an OIDC forward-auth gateway are external; application and database ports are not published to the host.

## Provision and launch

1. Provision a DNS name that points to the Docker host and allow inbound TCP 80/443 (UDP 443 is optional for HTTP/3). Provision a managed Qdrant collection compatible with the ArcFace vector configuration, and an OIDC forward-auth endpoint (for example, an oauth2-proxy `/oauth2/auth` endpoint) reachable from Caddy. Set its host in `AUTH_GATEWAY_UPSTREAM`, the check path in `AUTH_GATEWAY_PATH`, and configure the gateway to enforce your organization's login and access policy.
2. Copy `production.env.example` to `production.env` (`Copy-Item docker/production.env.example docker/production.env`). Use separate long random URL-safe tokens for the Vault operator, each alert producer and the Alert Service operator. Use a URL-safe PostgreSQL password. Do not reuse development credentials.
3. Protect `production.env` with host file permissions or populate its values from your deployment secret manager. It is used for Compose interpolation and is never copied into an image.
4. Build images from the repository root:

   ```powershell
   docker compose --env-file docker/production.env -f docker/compose.production.yaml build
   ```

5. Start PostgreSQL. For a new, empty Vault database, bootstrap the current ORM schema:

   ```powershell
   docker compose --env-file docker/production.env -f docker/compose.production.yaml up -d --wait postgres
   docker compose --env-file docker/production.env -f docker/compose.production.yaml run --rm --no-deps vault-monitoring python -c "from app.db.database import init_db; init_db()"
   ```

   For an existing Vault database, do not run this bootstrap as a substitute for migrations. Take and verify a backup, inspect the live schema, and follow the migration plan/audit to select and order only the applicable forward migrations before starting the application services. Migration files are mounted read-only at `/migrations`; for example:

   ```powershell
   docker compose --env-file docker/production.env -f docker/compose.production.yaml exec -T postgres psql -v ON_ERROR_STOP=1 -U fedbank -d vault_monitoring -f /migrations/<reviewed-forward-migration>.sql
   ```

   The Vault migrations are hand-managed SQL with order and preconditions; do not run `*_down.sql` files as part of deployment. See the [migration plan](../docs/migration-plan.md) and [application audit](../docs/final-application-audit-report.md).

6. Start the complete stack and check the health states:

   ```powershell
   docker compose --env-file docker/production.env -f docker/compose.production.yaml up -d
   docker compose --env-file docker/production.env -f docker/compose.production.yaml ps
   ```

7. Open `https://<DOMAIN>`. The first image build downloads large Python/ML dependencies and the Google MediaPipe Face Landmarker model. The first Branch inference may also download RF-DETR weights into a persistent model-cache volume. PostgreSQL init SQL creates the Branch and Alert databases only when the PostgreSQL volume is initialized for the first time.

## Production operations

- Only Caddy publishes ports. It obtains and renews HTTPS certificates; keep the Caddy data volume backed up.
- Caddy requires successful OIDC forward-auth before it serves the UI or proxies API requests. The Compose stack deliberately fails closed if `AUTH_GATEWAY_UPSTREAM` is unset.
- The UI calls same-origin `/vault-api`, `/branch-api` and `/alert-service` routes. Nginx injects the Vault and Alert Service operator headers server-side; neither token is embedded in the Vite bundle.
- Vault/Branch/Alert APIs and PostgreSQL are on private Docker networks. Backend services also have outbound access for Qdrant, alert delivery, RTSP cameras and model downloads.
- Named volumes persist PostgreSQL, uploaded evidence, Branch storage/settings, model caches and Caddy certificates. Back up PostgreSQL and uploaded/evidence data and test restores before go-live.
- Compose on one host is not a high-availability platform. For critical production use managed PostgreSQL, managed Qdrant, an external secret manager, host monitoring, vulnerability scanning, image-digest pinning, and a tested backup/restore and disaster-recovery plan. Set resource limits appropriate to camera count and model sizes. CPU is configured as the safe default; configure Docker GPU access separately if needed.
- Keep docs and OpenAPI routes blocked at the edge. If operators require them, expose them only through an authenticated private management path.

## Updating

Build and start a release using a new immutable `IMAGE_TAG`. Before deploying, review dependency lock changes, scan image layers, test migrations and health checks in staging, then retain the previous image tag for rollback. Do not use `latest` for releases.
