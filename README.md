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

Every request must include the API key from `.env`:

```
X-API-KEY: your-secret-key
```

## API

```
GET  /api/v1/health
GET  /api/v1/version
GET  /api/v1/driver

POST   /api/v1/customer
PUT    /api/v1/customer/{username}
DELETE /api/v1/customer/{username}

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
