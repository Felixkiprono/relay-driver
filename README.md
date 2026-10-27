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
PUT    /api/v1/customer/{username}/expiration   date after which RADIUS refuses the user

POST /api/v1/package/activate      (vendor-aware; see "Router vendors" below)
POST /api/v1/package/deactivate
POST /api/v1/package/sync          rewrite a package's attributes after an edit
POST /api/v1/package/preview       show the attributes a package would produce
GET  /api/v1/vendors               supported router vendors and what each honours

POST /api/v1/session/disconnect
GET  /api/v1/sessions
GET  /api/v1/accounting/usage?since=&until=&group_by=username|nas
GET  /api/v1/accounting/daily?since=&until=

GET  /api/v1/statistics

GET  /api/v1/dns-log
```

## DNS query logging (top-level browsed domains)

Relay also runs a small UDP syslog listener (`app/dns_listener.py`, started
alongside the HTTP API) that captures which top-level domain each hotspot
client resolved, straight from a MikroTik's own DNS server — no proxy, no
packet inspection. Point a router at it:

```
/system logging add topics=dns action=remote
/system logging action set remote remote-address=<relay-host> remote-port=5140 remote-protocol=udp
```

`DNS_LOG_UDP_PORT` in `.env` controls the listening port (default `5140`).
Unlike the HTTP API, this is raw UDP and can't be proxied through Traefik —
the port must be published directly (see `docker-compose.yml`) and reachable
from the router's network. Laravel polls `GET /api/v1/dns-log?since_id=...`
to pull new rows and attribute them to a customer by IP.

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

## Router vendors

Packages are written as vendor-neutral policy (session/idle timeout, interim
interval, upload/download kbit/s, data cap in bytes, optional router-side
profile). `app/vendors.py` turns that into each manufacturer's RADIUS reply
attributes. Pass `vendors` (LumaNet's router vendor keys) on activate/sync so
a mixed fleet gets every family it needs; without it MikroTik is assumed.

| Vendors | Speed | Data cap | Profile |
|---|---|---|---|
| MikroTik | `Mikrotik-Rate-Limit` | `Mikrotik-Total-Limit` (+ gigawords) | `Mikrotik-Group` |
| Huawei | `Huawei-Input/Output-Average-Rate` | `Huawei-Remanent-Volume` | `Filter-Id` |
| TP-Link Omada, Ubiquiti, Cambium, Ruijie, pfSense | `WISPr-Bandwidth-Max-Up/Down` | — | — |
| OpenWrt / CoovaChilli | `ChilliSpot-Bandwidth-Max-Up/Down` | `ChilliSpot-Max-Total-Octets` | — |
| Aruba / Cisco / Nokia | via the named profile | — | `Aruba-User-Role` / `Filter-Id` / `Alc-SLA-Prof-Str` |

`max_devices` on activate/sync becomes the group's `Simultaneous-Use` check
(FreeRADIUS's `sql` session tracking must be enabled for it to count open
sessions). `expires_at` writes the user's own `Expiration`, which on-site
(PPPoE) subscriptions use so RADIUS refuses them after their paid date.

Every activation replaces the attributes Relay manages for that group, so
edited packages take effect; rows added by hand for other attributes stay.
FreeRADIUS needs each family's dictionary loaded (stock FreeRADIUS has them).

## API key

`API_KEY` is only enforced when `REQUIRE_API_KEY=true`. Turn it on once
LumaNet's `RELAY_API_KEY` matches; until then Relay logs a warning at startup.

## Tests

```bash
uv run pytest
```

The daloRADIUS driver runs against an in-memory SQLite copy of the
FreeRADIUS tables (see `tests/conftest.py`), so no database is needed.
