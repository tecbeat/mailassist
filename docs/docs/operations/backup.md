# Backup & Restore

## What to Back Up

| Component | Method |
|---|---|
| PostgreSQL database | `pg_dump` |
| `.env` file | File copy |
| `APP_SECRET_KEY` | Secure storage (required to decrypt credentials) |

## Backup

```bash
# Database
docker compose exec postgres pg_dump -U mailassist mailassist > backup.sql

# Environment
cp .env .env.backup
```

## Restore

```bash
# Stop the stack
docker compose down

# Restore database
docker compose up -d postgres
docker compose exec -T postgres psql -U mailassist mailassist < backup.sql

# Restore environment
cp .env.backup .env

# Start everything
docker compose up -d
```

!!! warning
    Without the correct `APP_SECRET_KEY`, encrypted credentials cannot be decrypted. Always back up your key separately and securely.
