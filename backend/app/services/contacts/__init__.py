"""Contacts service package.

Re-exports all public symbols so existing ``from app.services.contacts import X``
statements continue to work after the split.
"""

from app.services.contacts.matching import match_sender_to_contact
from app.services.contacts.sync import sync_contacts, test_carddav_connection
from app.services.contacts.vcard import parse_vcard
from app.services.contacts.writeback import remove_email_from_contact, write_back_email_to_contact

__all__ = [
    "match_sender_to_contact",
    "parse_vcard",
    "remove_email_from_contact",
    "sync_contacts",
    "test_carddav_connection",
    "write_back_email_to_contact",
]
