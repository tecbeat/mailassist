# Contacts

**Priority:** 80 · **AI:** Yes

Extracts contact information from incoming mail and syncs with a CardDAV server (Nextcloud, etc.).

## CardDAV Integration

Configure in the Contacts page settings:

- **CardDAV URL**: Server endpoint (auto-discovery supported — just provide the server URL)
- **Address Book**: Target address book (auto-filled by Test Connection)
- **Username / Password**: Credentials (stored with envelope encryption)
- **Sync Interval**: How often to sync (default: 60 minutes)

## Features

- Incremental sync with change detection
- Contact-to-email matching
- Write-back of new contacts to CardDAV
- Manual sync via **Sync Now** button
