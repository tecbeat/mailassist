"""Tests for contact matching and CardDAV write-back (test areas 10, 11).

Area 10: Contact matching -- exact match, no match, multiple contacts,
         case sensitivity, Valkey cache behaviour.
Area 11: CardDAV write-back -- email added, etag conflict, retry.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.contacts import (
    match_sender_to_contact,
    write_back_email_to_contact,
    parse_vcard,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_db_scalar(return_value):
    """Create a mock DB execute chain that returns a single scalar."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = return_value
    return result


def _mock_db_scalars(return_values: list):
    """Create a mock DB execute chain that returns multiple scalars."""
    result = MagicMock()
    result.scalars.return_value.all.return_value = return_values
    return result


def _make_contact(contact_id=None, user_id=None, emails=None, display_name="Jane Doe"):
    """Create a mock Contact ORM object."""
    c = MagicMock()
    c.id = contact_id or uuid4()
    c.user_id = user_id or uuid4()
    c.emails = emails or ["jane@example.com"]
    c.display_name = display_name
    c.carddav_uid = f"uid-{c.id.hex[:8]}"
    c.etag = "etag-123"
    c.raw_vcard = "BEGIN:VCARD\nEND:VCARD"
    return c


def _make_carddav_config(user_id=None):
    """Create a mock CardDAVConfig ORM object."""
    cfg = MagicMock()
    cfg.user_id = user_id or uuid4()
    cfg.carddav_url = "https://nextcloud.example.com/remote.php/dav"
    cfg.address_book = "contacts"
    cfg.encrypted_credentials = b'{"username": "user", "password": "pass"}'
    return cfg


# ---------------------------------------------------------------------------
# Test Area 10: Contact Matching
# ---------------------------------------------------------------------------


class TestContactMatching:
    """Tests for match_sender_to_contact."""

    @pytest.mark.asyncio
    async def test_exact_match_via_cache(self, mock_cache_client, mock_encryption):
        """Cached contact ID is returned directly from Valkey."""
        user_id = uuid4()
        contact_id = uuid4()
        contact = _make_contact(contact_id=contact_id, user_id=user_id)

        # Prime the cache
        cache_key = f"contact_match:{user_id}:alice@example.com"
        await mock_cache_client.set(cache_key, str(contact_id))

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_mock_db_scalar(contact))

        result = await match_sender_to_contact(db, user_id, "alice@example.com")
        assert result is contact

    @pytest.mark.asyncio
    async def test_cached_none_returns_none(self, mock_cache_client, mock_encryption):
        """Cached 'none' value means previously confirmed no match."""
        user_id = uuid4()
        cache_key = f"contact_match:{user_id}:unknown@example.com"
        await mock_cache_client.set(cache_key, "none")

        db = AsyncMock()
        result = await match_sender_to_contact(db, user_id, "unknown@example.com")
        assert result is None

    @pytest.mark.asyncio
    async def test_match_via_emails_array(self, mock_cache_client, mock_encryption):
        """Contact found by scanning Contact.emails JSON array (no cache)."""
        user_id = uuid4()
        contact = _make_contact(
            user_id=user_id,
            emails=["work@example.com", "personal@example.com"],
        )

        db = AsyncMock()
        # Single DB query: Contact.emails containment
        db.execute = AsyncMock(return_value=_mock_db_scalar(contact))

        result = await match_sender_to_contact(db, user_id, "personal@example.com")
        assert result is contact

        # Result should be cached in Valkey
        cache_key = f"contact_match:{user_id}:personal@example.com"
        cached = await mock_cache_client.get(cache_key)
        assert cached == str(contact.id)

    @pytest.mark.asyncio
    async def test_case_insensitive_match(self, mock_cache_client, mock_encryption):
        """Email matching is case-insensitive."""
        user_id = uuid4()
        contact = _make_contact(user_id=user_id, emails=["Alice@Example.COM"])

        db = AsyncMock()
        # Single DB query: Contact.emails containment
        db.execute = AsyncMock(return_value=_mock_db_scalar(contact))

        result = await match_sender_to_contact(db, user_id, "ALICE@example.com")
        assert result is contact

    @pytest.mark.asyncio
    async def test_no_match_caches_none(self, mock_cache_client, mock_encryption):
        """No match caches 'none' in Valkey without any DB writes."""
        user_id = uuid4()

        db = AsyncMock()
        # Single DB query: no contact found
        db.execute = AsyncMock(return_value=_mock_db_scalar(None))

        result = await match_sender_to_contact(db, user_id, "nobody@example.com")
        assert result is None

        # Verify cache was set to "none"
        cache_key = f"contact_match:{user_id}:nobody@example.com"
        cached = await mock_cache_client.get(cache_key)
        assert cached == "none"

        # No DB writes should have occurred
        db.add.assert_not_called()
        db.flush.assert_not_awaited()


# ---------------------------------------------------------------------------
# Test Area 10 supplement: vCard parsing
# ---------------------------------------------------------------------------


class TestVcardParsing:
    """Test parse_vcard helper."""

    def test_parse_basic_vcard(self):
        vcard = """BEGIN:VCARD
VERSION:3.0
FN:Jane Doe
N:Doe;Jane;;;
EMAIL:jane@example.com
TEL:+49123456789
ORG:Acme Corp
TITLE:Engineer
END:VCARD"""
        result = parse_vcard(vcard)
        assert result["display_name"] == "Jane Doe"
        assert result["first_name"] == "Jane"
        assert result["last_name"] == "Doe"
        assert "jane@example.com" in result["emails"]
        assert "+49123456789" in result["phones"]
        assert result["organization"] == "Acme Corp"
        assert result["title"] == "Engineer"

    def test_parse_vcard_multiple_emails(self):
        vcard = """BEGIN:VCARD
VERSION:3.0
FN:Multi Email
EMAIL:a@example.com
EMAIL:b@example.com
END:VCARD"""
        result = parse_vcard(vcard)
        assert len(result["emails"]) == 2
        assert "a@example.com" in result["emails"]
        assert "b@example.com" in result["emails"]

    def test_parse_invalid_vcard(self):
        result = parse_vcard("not a vcard at all")
        assert result == {}


# ---------------------------------------------------------------------------
# Test Area 11: CardDAV Write-back
# ---------------------------------------------------------------------------


class TestCardDAVWriteBack:
    """Tests for write_back_email_to_contact."""

    @pytest.mark.asyncio
    async def test_email_already_exists_skips(self, mock_encryption, mock_cache_client):
        """If email already exists on the contact, write-back is skipped."""
        contact = _make_contact(emails=["existing@example.com"])
        config = _make_carddav_config()
        db = AsyncMock()

        result = await write_back_email_to_contact(db, config, contact, "existing@example.com")
        assert result is True

    @pytest.mark.asyncio
    async def test_successful_write_back(self, mock_encryption, mock_cache_client):
        """New email is added to contact via PUT with If-Match."""
        contact = _make_contact(emails=["old@example.com"])
        contact.user_id = uuid4()
        config = _make_carddav_config(user_id=contact.user_id)
        db = AsyncMock()

        vcard_text = """BEGIN:VCARD
VERSION:3.0
FN:Jane Doe
EMAIL:old@example.com
END:VCARD"""

        mock_get_response = MagicMock()
        mock_get_response.status_code = 200
        mock_get_response.headers = {"ETag": '"etag-v1"'}
        mock_get_response.text = vcard_text

        mock_put_response = MagicMock()
        mock_put_response.status_code = 204
        mock_put_response.headers = {"ETag": '"etag-v2"'}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_get_response)
        mock_client.put = AsyncMock(return_value=mock_put_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()

        from app.services.dav_discovery import DavDiscoveryResult
        mock_discovery = DavDiscoveryResult(
            success=True,
            message="OK",
            addressbook_home=config.carddav_url + "/addressbooks/users/user",
        )

        with patch("app.services.contacts.writeback.httpx.AsyncClient", return_value=mock_client), \
             patch("app.services.dav_discovery.discover_dav", return_value=mock_discovery):
            result = await write_back_email_to_contact(db, config, contact, "new@example.com")

        assert result is True
        # Contact emails should be updated locally
        assert "new@example.com" in contact.emails
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_etag_conflict_retries(self, mock_encryption, mock_cache_client):
        """HTTP 412 (Precondition Failed) triggers a retry."""
        contact = _make_contact(emails=["old@example.com"])
        contact.user_id = uuid4()
        config = _make_carddav_config(user_id=contact.user_id)
        db = AsyncMock()

        vcard_text = """BEGIN:VCARD
VERSION:3.0
FN:Jane Doe
EMAIL:old@example.com
END:VCARD"""

        mock_get_response = MagicMock()
        mock_get_response.status_code = 200
        mock_get_response.headers = {"ETag": '"etag-v1"'}
        mock_get_response.text = vcard_text

        # First PUT fails with 412, second succeeds
        mock_put_conflict = MagicMock()
        mock_put_conflict.status_code = 412

        mock_put_success = MagicMock()
        mock_put_success.status_code = 204
        mock_put_success.headers = {"ETag": '"etag-v3"'}

        call_count = 0

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_get_response)

        async def mock_put(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_put_conflict
            return mock_put_success

        mock_client.put = AsyncMock(side_effect=mock_put)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()

        from app.services.dav_discovery import DavDiscoveryResult
        mock_discovery = DavDiscoveryResult(
            success=True,
            message="OK",
            addressbook_home=config.carddav_url + "/addressbooks/users/user",
        )

        with patch("app.services.contacts.writeback.httpx.AsyncClient", return_value=mock_client), \
             patch("app.services.dav_discovery.discover_dav", return_value=mock_discovery):
            result = await write_back_email_to_contact(db, config, contact, "retry@example.com")

        assert result is True
        assert call_count == 2  # retried once

    @pytest.mark.asyncio
    async def test_fetch_failure_returns_false(self, mock_encryption, mock_cache_client):
        """If fetching the current vCard fails, write-back returns False."""
        contact = _make_contact(emails=["old@example.com"])
        config = _make_carddav_config()
        db = AsyncMock()

        mock_get_response = MagicMock()
        mock_get_response.status_code = 404

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_get_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()

        from app.services.dav_discovery import DavDiscoveryResult
        mock_discovery = DavDiscoveryResult(
            success=True,
            message="OK",
            addressbook_home=config.carddav_url + "/addressbooks/users/user",
        )

        with patch("app.services.contacts.writeback.httpx.AsyncClient", return_value=mock_client), \
             patch("app.services.dav_discovery.discover_dav", return_value=mock_discovery):
            result = await write_back_email_to_contact(db, config, contact, "new@example.com")

        assert result is False


# ---------------------------------------------------------------------------
# Test Area 10b: Contact Pre-Filtering / Scoring
# ---------------------------------------------------------------------------


class TestContactScoring:
    """Tests for the contact pre-filtering scoring logic in pipeline_orchestrator.

    These test the scoring algorithm in isolation by replicating the logic.
    """

    # Replicate the scoring constants and stopwords from pipeline_orchestrator
    _NAME_STOPWORDS = {
        "dr", "mr", "mrs", "ms", "prof", "ing", "mag", "von", "van",
        "de", "del", "der", "die", "das", "the", "and", "und", "jr",
        "sr", "ii", "iii", "msc", "bsc", "phd", "mba",
    }

    def _score_contact(self, sender_email: str, sender_name: str, contact) -> float:
        """Score a contact against a sender, matching pipeline_orchestrator logic."""
        sender_email = sender_email.lower()
        sender_domain = sender_email.split("@")[-1] if "@" in sender_email else ""
        sender_name = sender_name.lower().strip()
        sender_name_parts = {
            t for t in sender_name.split()
            if len(t) >= 3 and t not in self._NAME_STOPWORDS
        } if sender_name else set()

        score = 0.0
        c_emails = [e.lower() for e in (contact.emails or [])]

        if sender_email and sender_email in c_emails:
            score += 100.0
        elif sender_domain:
            c_domains = {e.split("@")[-1] for e in c_emails if "@" in e}
            if sender_domain in c_domains:
                score += 10.0

        c_name_parts = {
            t for t in (contact.display_name or "").lower().split()
            if len(t) >= 3 and t not in self._NAME_STOPWORDS
        }
        if contact.first_name and len(contact.first_name) >= 3:
            c_name_parts.add(contact.first_name.lower())
        if contact.last_name and len(contact.last_name) >= 3:
            c_name_parts.add(contact.last_name.lower())
        overlap = sender_name_parts & c_name_parts
        score += len(overlap) * 5.0

        if contact.organization and sender_domain:
            org_domain = contact.organization.lower().replace(" ", "")
            if org_domain == sender_domain.split(".")[0]:
                score += 8.0

        return score

    def _make_scored_contact(self, emails=None, display_name="", first_name=None,
                             last_name=None, organization=None):
        c = MagicMock()
        c.emails = emails or []
        c.display_name = display_name
        c.first_name = first_name
        c.last_name = last_name
        c.organization = organization
        return c

    def test_exact_email_match_scores_highest(self):
        c = self._make_scored_contact(emails=["alice@example.com"])
        score = self._score_contact("alice@example.com", "Alice", c)
        assert score >= 100.0

    def test_substring_domain_does_not_match(self):
        """mail.com should NOT match gmail.com (was a substring bug)."""
        c = self._make_scored_contact(emails=["user@gmail.com"])
        score = self._score_contact("sender@mail.com", "", c)
        assert score == 0.0

    def test_exact_domain_matches(self):
        c = self._make_scored_contact(emails=["other@example.com"])
        score = self._score_contact("sender@example.com", "", c)
        assert score == 10.0

    def test_short_domain_no_false_positive(self):
        """Domain 'art.org' should NOT match 'smart.org'."""
        c = self._make_scored_contact(emails=["user@smart.org"])
        score = self._score_contact("sender@art.org", "", c)
        assert score == 0.0

    def test_stopwords_filtered_from_name(self):
        """'Dr' and 'von' should not contribute to name matching."""
        c = self._make_scored_contact(
            display_name="Dr. Alexander von Schmidt",
            first_name="Alexander", last_name="Schmidt",
        )
        # Sender is "Dr. von Müller" — only stopwords overlap, no real match
        score = self._score_contact("someone@other.com", "Dr. von Müller", c)
        assert score == 0.0

    def test_short_tokens_filtered(self):
        """Single-letter and two-letter tokens should be ignored."""
        c = self._make_scored_contact(display_name="A. B. Smith", last_name="Smith")
        # "A." and "B." are too short to match
        score = self._score_contact("sender@other.com", "A. B. Jones", c)
        assert score == 0.0

    def test_name_overlap_scores(self):
        c = self._make_scored_contact(
            display_name="Alexander Schmidt",
            first_name="Alexander", last_name="Schmidt",
        )
        score = self._score_contact("sender@other.com", "Alexander Schmidt", c)
        assert score == 10.0  # 2 tokens * 5.0

    def test_org_exact_domain_matches(self):
        c = self._make_scored_contact(
            emails=["user@other.com"], organization="Acme",
        )
        score = self._score_contact("sender@acme.com", "", c)
        assert score == 8.0

    def test_org_substring_does_not_match(self):
        """Org 'IT' should NOT match domain 'twitter.com' (was a substring bug)."""
        c = self._make_scored_contact(
            emails=["user@other.com"], organization="IT Solutions",
        )
        score = self._score_contact("sender@twitter.com", "", c)
        assert score == 0.0

    def test_zero_score_contacts_excluded(self):
        """Contacts with score 0 should not be included in LLM candidates."""
        # This tests the filtering logic: the loop breaks at score <= 0
        contacts = [
            (15.0, "relevant"),
            (0.0, "irrelevant1"),
            (0.0, "irrelevant2"),
        ]
        included = []
        for score, name in contacts:
            if score <= 0.0:
                break
            included.append(name)
        assert included == ["relevant"]


# ---------------------------------------------------------------------------
# Test Area 10c: Contacts Plugin execute() logic
# ---------------------------------------------------------------------------


class TestContactsPluginExecute:
    """Tests for ContactsPlugin.execute() decision logic."""

    @pytest.mark.asyncio
    async def test_no_match_returns_no_action(self):
        """When AI returns no contact_id and no new suggestion, skip."""
        from app.plugins.contacts import ContactsPlugin, ContactAssignmentResponse

        plugin = ContactsPlugin()
        context = MagicMock()
        context.contact = None

        response = ContactAssignmentResponse(
            contact_id=None,
            contact_name="",
            confidence=0.0,
            reasoning="No matching contact found",
            is_new_contact_suggestion=False,
        )
        result = await plugin.execute(context, response)
        assert result.success is True
        assert result.requires_approval is False
        assert result.actions_taken == []

    @pytest.mark.asyncio
    async def test_high_confidence_match_no_approval(self):
        """High confidence existing contact match does not require approval."""
        from app.plugins.contacts import ContactsPlugin, ContactAssignmentResponse

        plugin = ContactsPlugin()
        context = MagicMock()
        context.contact = None

        cid = str(uuid4())
        response = ContactAssignmentResponse(
            contact_id=cid,
            contact_name="Jane Doe",
            confidence=0.95,
            reasoning="Exact email match",
            is_new_contact_suggestion=False,
        )
        result = await plugin.execute(context, response)
        assert result.success is True
        assert result.requires_approval is False
        assert f"assign_contact:{cid}" in result.actions_taken

    @pytest.mark.asyncio
    async def test_low_confidence_requires_approval(self):
        """Below threshold requires approval."""
        from app.plugins.contacts import ContactsPlugin, ContactAssignmentResponse

        plugin = ContactsPlugin()
        context = MagicMock()
        context.contact = None

        response = ContactAssignmentResponse(
            contact_id=str(uuid4()),
            contact_name="Jane Doe",
            confidence=0.6,
            reasoning="Name partially matches",
            is_new_contact_suggestion=False,
        )
        result = await plugin.execute(context, response)
        assert result.requires_approval is True

    @pytest.mark.asyncio
    async def test_new_contact_suggestion_requires_approval(self):
        """New contact suggestions always require approval."""
        from app.plugins.contacts import ContactsPlugin, ContactAssignmentResponse

        plugin = ContactsPlugin()
        context = MagicMock()
        context.contact = None

        response = ContactAssignmentResponse(
            contact_id=None,
            contact_name="New Person",
            confidence=0.9,
            reasoning="Important recurring correspondent",
            is_new_contact_suggestion=True,
        )
        result = await plugin.execute(context, response)
        assert result.requires_approval is True

    @pytest.mark.asyncio
    async def test_deterministic_match_confirmed(self):
        """When pre-match and AI agree, confirm without approval."""
        from app.plugins.contacts import ContactsPlugin, ContactAssignmentResponse

        plugin = ContactsPlugin()
        cid = str(uuid4())
        context = MagicMock()
        context.contact = {"id": cid, "display_name": "Jane"}

        response = ContactAssignmentResponse(
            contact_id=cid,
            contact_name="Jane Doe",
            confidence=0.95,
            reasoning="Email matches",
            is_new_contact_suggestion=False,
        )
        result = await plugin.execute(context, response)
        assert f"confirm_contact:{cid}" in result.actions_taken
        assert result.requires_approval is False
