# Upgrading

## Standard Upgrade

```bash
cd mailassist
git pull
docker compose up -d --build
```

Database migrations run automatically on startup via Alembic.

## Version Pinning

To pin to a specific version:

```bash
git checkout v0.1.20
docker compose up -d --build
```

## Pre-Upgrade Checklist

1. **Back up** the database and `.env` (see [Backup](backup.md))
2. **Read the changelog** for breaking changes
3. **Test** in a staging environment if possible
