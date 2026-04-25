"""vCard parsing utility.

Extracts structured contact data from vCard text using vobject.
"""

import structlog
import vobject

logger = structlog.get_logger()


def parse_vcard(vcard_text: str) -> dict:
    """Parse a vCard string into a structured dict.

    Extracts display name, emails, phones, organization, title, and photo URL.

    Returns:
        Dict with contact fields, or empty dict if parsing fails.
    """
    try:
        card = vobject.readOne(vcard_text)
    except Exception:
        logger.warning("vcard_parse_failed")
        return {}

    result: dict = {
        "display_name": "",
        "first_name": None,
        "last_name": None,
        "emails": [],
        "phones": [],
        "organization": None,
        "title": None,
        "photo_url": None,
    }

    # Display name
    if hasattr(card, "fn"):
        result["display_name"] = str(card.fn.value)

    # Structured name
    if hasattr(card, "n"):
        n = card.n.value
        result["first_name"] = n.given or None
        result["last_name"] = n.family or None

    # Emails -- vobject exposes multiple properties via contents dict
    email_list = card.contents.get("email", [])
    result["emails"] = [str(e.value).lower() for e in email_list]

    # Phones
    tel_list = card.contents.get("tel", [])
    result["phones"] = [str(t.value) for t in tel_list]

    # Organization
    if hasattr(card, "org"):
        org_value = card.org.value
        if isinstance(org_value, list):
            result["organization"] = org_value[0] if org_value else None
        else:
            result["organization"] = str(org_value) if org_value else None

    # Title
    if hasattr(card, "title"):
        result["title"] = str(card.title.value)

    # Photo URL (only store URL, never fetch/store binary)
    if hasattr(card, "photo"):
        photo = card.photo
        if hasattr(photo, "value") and isinstance(photo.value, str) and photo.value.startswith("http"):
            result["photo_url"] = photo.value

    return result
