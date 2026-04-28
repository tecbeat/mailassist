# Configuration

All configuration is via environment variables. Copy `.env.example` as your starting point.

## Required Variables

| Variable | Description |
|---|---|
| `APP_SECRET_KEY` | Master encryption key (min 32 characters). Used for envelope encryption of all stored credentials. |
| `POSTGRES_PASSWORD` | PostgreSQL password |
| `VALKEY_PASSWORD` | Valkey password |
| `OIDC_ISSUER_URL` | OIDC discovery endpoint (e.g. `https://auth.example.com/application/o/mailassist/`) |
| `OIDC_CLIENT_ID` | OIDC client identifier |
| `OIDC_CLIENT_SECRET` | OIDC client secret |
| `OIDC_REDIRECT_URI` | OIDC callback URL (e.g. `http://localhost:8000/auth/callback`) |

## Optional Variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | Built from PG vars | Full async database URL |
| `VALKEY_URL` | `redis://valkey:6379/0` | Valkey connection URL |
| `APP_LOG_LEVEL` | `info` | Logging level (`debug`, `info`, `warning`, `error`) |
| `APP_CORS_ORIGINS` | `[]` | Allowed CORS origins (JSON array) |
| `APP_TRUSTED_PROXIES` | `[]` | Trusted proxy IPs for X-Forwarded-For |

## Key Rotation

To rotate the master encryption key:

1. Set `APP_SECRET_KEY_OLD` to the current key
2. Set `APP_SECRET_KEY` to the new key
3. Restart the application

mailassist re-encrypts all stored credentials on the fly. See [Key Rotation](../operations/key-rotation.md) for details.
