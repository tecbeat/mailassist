"""Service layer for business logic.

Error-handling conventions
--------------------------
All service functions follow one of these patterns:

* **Raise on error** (default) -- Functions raise exceptions on failure.
  Workers and API endpoints decide whether to catch or propagate.
  Use ``core.exceptions`` types (``ExternalServiceError``, ``NotFoundError``,
  etc.) for actionable errors; let unexpected exceptions propagate as-is.

* **Return result object** -- Connection-test functions return a
  ``ConnectionTestResult`` dataclass with ``success``, ``message``, and
  optional ``details``.  They never raise.

* **Return bool** -- Low-level IMAP helpers (``store_flags``,
  ``move_message``, ``create_folder``) return ``True``/``False`` because
  partial success is expected (e.g. a single flag store failing should not
  abort the whole action batch).

* **Return None / empty collection** -- Pure lookup functions
  (``match_sender_to_contact``, ``parse_vcard``, ``resolve_folder``) return
  ``None`` or ``{}``/``[]`` when there is nothing to find.  This is *not*
  an error.

Do **not** return ``{"success": False, ...}`` dicts from service functions.
"""
