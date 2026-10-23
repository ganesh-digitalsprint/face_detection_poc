# Backend services

Backend microservices live in this directory. Each service is an independent Python
project with its own `pyproject.toml`, lock file, dependencies, environment file,
configuration, and application package. Run commands from that service's directory.

## Services

| Service | Directory | Local setup and API details |
|---|---|---|
| Vault Monitoring | [`vault-monitoring/`](vault-monitoring/) | [`README.md`](vault-monitoring/README.md) |

For a new service, create a sibling directory with its own app, `pyproject.toml`,
`uv.lock`, `.env.example`, and README. Keep service imports rooted in that service's
package and configure a distinct port when running multiple services at once.
