# Relay

A small standalone service that talks to network infrastructure.

Relay has one responsibility: receive requests from Laravel, execute them
against the configured network driver, and return the result. It holds no
business logic — customers, billing, packages and auth stay in Laravel.

```
Laravel
    │
    ▼
 Relay
    │
    └── daloRADIUS
```

## Run

```bash
cp .env.example .env
uv run python main.py
```

Or with Docker:

```bash
docker compose up -d
```

## Auth

Every request except `/api/v1/health` must include the API key from `.env`:

```
X-API-KEY: your-secret-key
```

## API

Interactive docs (Swagger UI) at `/docs`, raw OpenAPI spec at `/openapi.json`.
Click **Authorize** in `/docs` to set the API key once for every request on
the page.

```
GET  /api/v1/health                       (no auth)
GET  /api/v1/version
GET  /api/v1/driver

POST   /api/v1/customer
PUT    /api/v1/customer/{username}
DELETE /api/v1/customer/{username}
POST   /api/v1/customer/{username}/resume

POST /api/v1/package/activate
POST /api/v1/package/deactivate

POST /api/v1/session/disconnect
GET  /api/v1/sessions

GET  /api/v1/statistics
```

## Drivers

Every driver implements `BaseDriver` ([app/drivers/base.py](app/drivers/base.py)).
Only daloRADIUS is implemented today. The active driver is selected from `.env`:

```
DRIVER=daloradius
```

Adding a new driver means adding a file under `app/drivers/` — no API changes.

## Deploying via NanoDeploi

This repo deploys as a **repo-compose** site (`docker-compose.yml` lives at the
repo root and NanoDeploi reads it directly — no generated stack).

When creating the site:

- `use_repo_compose` — enabled
- `repo_compose_web_service` — `relay`
- `runtime_port` — `8080` (the port the app listens on inside the container;
  Traefik routes to this over the internal `nanodeploi_web` network)

NanoDeploi clones the repo into `src/`, rewrites `build.context: .` → `./src`
and `env_file: .env` → `./src/.env`, and injects Traefik labels/network —
no changes needed in `docker-compose.yml` for that. If no env is configured
for the site yet, NanoDeploi seeds `src/.env` from `.env.example` on first
deploy.

The `127.0.0.1:8082:8080` port binding in `docker-compose.yml` is for local
`docker compose up` only — production traffic reaches the container through
Traefik, not that host port.

`DALO_DB_HOST=host.docker.internal` (plus the `extra_hosts: host-gateway`
entry in `docker-compose.yml`) lets Relay reach a daloRADIUS MariaDB bound to
the host's loopback interface, on both local Docker Desktop and a Linux
droplet.
