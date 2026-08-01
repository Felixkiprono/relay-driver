# Relay

A lightweight, vendor-neutral network access service.

Relay translates a stable REST API into vendor-specific network operations —
daloRADIUS, MikroTik, UniFi, OpenWISP, and future backends — so business
systems (like Laravel) can create users, activate packages, and disconnect
sessions without knowing which vendor sits underneath.

```
Laravel
    │
    ▼
 Relay
    │
    ├── daloRADIUS
    ├── MikroTik
    └── Future Drivers
```

## Run

```bash
cp .env.example .env
uv run python main.py
```

Or with Docker:

```bash
docker compose up
```

## API

```
GET  /health
GET  /version
GET  /drivers
GET  /online
GET  /statistics

POST /user/create
POST /user/delete
POST /package/activate
POST /user/disconnect
POST /voucher/create
```

## Drivers

Every driver implements `BaseDriver` ([app/drivers/base.py](app/drivers/base.py)).
Switching backends is a config change:

```
DRIVER=mikrotik
```

No other code changes.
