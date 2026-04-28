# Rules Engine

**Priority:** 5 · **AI:** Optional (NL-to-rule translation)

The rules engine evaluates structured conditions against incoming mail before the AI pipeline runs.

## Conditions

Rules support nested AND/OR groups with these fields:

From, To, CC, Subject, Body, Has Attachments, Is Reply, Is Forwarded, Attachment Name, Contact Name, Contact Organization, and custom headers (X-Mailer, X-Spam-Score, List-Unsubscribe).

**Operators:** Equals, Not Equals, Contains, Not Contains, Starts With, Ends With, Matches Regex, Greater Than, Less Than, Is Empty, Is Not Empty.

## Actions

Move, Copy, Label, Remove Label, Mark Read, Mark Unread, Flag, Delete, Notify, Create Draft, Create Calendar Event.

## Natural Language Rules

Type a description in plain English and click **Generate Rule** — the AI translates it into structured conditions and actions.

## Stop Processing

Enable **Stop Processing** on a rule to prevent downstream rules and plugins from running when the rule matches.
