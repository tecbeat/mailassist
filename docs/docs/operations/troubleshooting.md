# Troubleshooting

## OIDC Login Fails

- Verify `OIDC_ISSUER_URL` ends with the correct path (e.g. `/application/o/mailassist/` for Authentik)
- Verify `OIDC_REDIRECT_URI` matches exactly what's configured in your OIDC provider
- Check that the OIDC provider is reachable from the Docker network

## IMAP Connection Fails

- Use **Test Connection** on the Mail Accounts page
- Verify host, port, and SSL/TLS settings
- For Gmail: enable "Less secure app access" or use an App Password
- Check firewall rules between Docker and the IMAP server

## AI Provider Not Responding

- Use **Test Connection** on the AI Providers page
- For Ollama: verify the model is pulled (`ollama pull model-name`)
- Check that the provider URL is reachable from the Docker network
- Providers are auto-paused after repeated failures — click **Resume** to retry

## Mails Not Being Processed

1. Check the Dashboard for **Failed Mails** or **Unhealthy Accounts**
2. Check worker logs: `docker compose logs -f worker`
3. Verify at least one AI provider is healthy and assigned to plugins
4. Verify plugins are not all set to **Off**

## Database Connection Issues

- Verify `DATABASE_URL` or individual `POSTGRES_*` variables
- Check that PostgreSQL is running: `docker compose ps postgres`
- Check PostgreSQL logs: `docker compose logs postgres`

## High Memory Usage

- Reduce `CONCURRENT_PROCESSING_SLOTS` (default: 3)
- Use smaller LLM models
- Increase Docker memory limits if needed
