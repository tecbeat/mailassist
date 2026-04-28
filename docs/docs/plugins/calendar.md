# Calendar Extraction

**Priority:** 60 · **AI:** Yes

Extracts calendar events from incoming mail and optionally syncs them to a CalDAV server.

## CalDAV Integration

Configure your CalDAV server (Nextcloud, Radicale, etc.) in the Calendar page settings:

- **CalDAV URL**: Server endpoint
- **Calendar name**: Target calendar
- **Username / Password**: Credentials (stored with envelope encryption)

Extracted events are created on the CalDAV server automatically (in Auto mode) or after approval.
