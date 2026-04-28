# Notifications

**Priority:** 90 · **AI:** No

Sends alerts via [Apprise](https://github.com/caronc/apprise) when events occur. Supports Matrix, Discord, email, Slack, Telegram, and many more channels.

## Event Templates

10 configurable notification templates:

- Reply Needed, Spam Detected, Coupon Found, Calendar Event Created
- Rule Executed, Newsletter Detected, Email Summary, AI Error
- Contact Assigned, Approval Needed

Each template uses Jinja2 with variables like `{{ sender_name }}`, `{{ subject }}`, etc. Templates are editable in the Notifications page.

!!! note
    Notifications only supports **Auto** and **Off** modes (no approval queue).
