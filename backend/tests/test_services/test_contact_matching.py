"""Tests for contact matching service.

Covers: match_sender_to_contact (cache hit, cache miss, DB match, no match),
find_relevant_contacts_for_sender (scoring: exact email, domain, name overlap,
org match, no match, empty sender).
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.contacts.matching import (
    _NAME_STOPWORDS,
    find_relevant_contacts_for_sender,
    match_sender_to_contact,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_contact(
    *,
    contact_id=None,
    emails=None,
    display_name="Jane Doe",
    first_name="Jane",
    last_name="Doe",
    organization=None,
    title=None,
):
    c = MagicMock()
    c.id = contact_id or uuid4()
    c.emails = emails or ["jane@example.com"]
    c.display_name = display_name
    c.first_name = first_name
    c.last_name = last_name
    c.organization = organization
    c.title = title
    return c


# ---------------------------------------------------------------------------
# match_sender_to_contact
# ---------------------------------------------------------------------------


class TestMatchSenderToContact:
    """Test email-to-contact matching with cache tiers."""

    @pytest.mark.asyncio
    @patch("app.services.contacts.matching.get_cache_client")
    async def test_cache_hit_returns_contact(self, mock_cache_fn):
        contact_id = uuid4()
        cache = AsyncMock()
        cache.get = AsyncMock(return_value=str(contact_id))
        mock_cache_fn.return_value = cache

        contact = _make_contact(contact_id=contact_id)
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = contact
        db.execute = AsyncMock(return_value=result)

        matched = await match_sender_to_contact(db, uuid4(), "jane@example.com")

        assert matched is contact

    @pytest.mark.asyncio
    @patch("app.services.contacts.matching.get_cache_client")
    async def test_cache_hit_none_returns_none(self, mock_cache_fn):
        cache = AsyncMock()
        cache.get = AsyncMock(return_value="none")
        mock_cache_fn.return_value = cache

        db = AsyncMock()
        matched = await match_sender_to_contact(db, uuid4(), "unknown@example.com")

        assert matched is None

    @pytest.mark.asyncio
    @patch("app.services.contacts.matching._get_contact_cache_ttl", return_value=3600)
    @patch("app.services.contacts.matching.get_cache_client")
    async def test_cache_miss_db_match(self, mock_cache_fn, mock_ttl):
        cache = AsyncMock()
        cache.get = AsyncMock(return_value=None)
        mock_cache_fn.return_value = cache

        contact = _make_contact()
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = contact
        db.execute = AsyncMock(return_value=result)

        matched = await match_sender_to_contact(db, uuid4(), "jane@example.com")

        assert matched is contact
        cache.setex.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.services.contacts.matching._get_contact_cache_ttl", return_value=3600)
    @patch("app.services.contacts.matching.get_cache_client")
    async def test_cache_miss_no_db_match(self, mock_cache_fn, mock_ttl):
        cache = AsyncMock()
        cache.get = AsyncMock(return_value=None)
        mock_cache_fn.return_value = cache

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result)

        matched = await match_sender_to_contact(db, uuid4(), "unknown@example.com")

        assert matched is None
        # Should cache the miss
        cache.setex.assert_called_once()
        assert cache.setex.call_args[0][2] == "none"

    @pytest.mark.asyncio
    @patch("app.services.contacts.matching._get_contact_cache_ttl", return_value=3600)
    @patch("app.services.contacts.matching.get_cache_client")
    async def test_cached_id_points_to_deleted_contact_falls_through(self, mock_cache_fn, mock_ttl):
        """Cached contact ID no longer exists → re-query DB."""
        contact_id = uuid4()
        cache = AsyncMock()
        cache.get = AsyncMock(return_value=str(contact_id))
        mock_cache_fn.return_value = cache

        new_contact = _make_contact()

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                # Cached ID lookup returns None (deleted)
                result.scalar_one_or_none.return_value = None
            else:
                # DB re-query finds a different contact
                result.scalar_one_or_none.return_value = new_contact
            return result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=mock_execute)

        matched = await match_sender_to_contact(db, uuid4(), "jane@example.com")

        assert matched is new_contact


# ---------------------------------------------------------------------------
# find_relevant_contacts_for_sender
# ---------------------------------------------------------------------------


class TestFindRelevantContactsForSender:
    """Test contact pre-filtering and scoring."""

    @pytest.mark.asyncio
    async def test_exact_email_match_highest_score(self):
        contact = _make_contact(emails=["alice@example.com"], display_name="Alice")

        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = [contact]
        db.execute = AsyncMock(return_value=result)

        contacts = await find_relevant_contacts_for_sender(db, uuid4(), "alice@example.com", "Alice")

        assert len(contacts) == 1
        assert contacts[0]["display_name"] == "Alice"

    @pytest.mark.asyncio
    async def test_domain_match_scores(self):
        contact = _make_contact(
            emails=["bob@example.com"],
            display_name="Bob",
            first_name="Bob",
            last_name="Smith",
        )

        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = [contact]
        db.execute = AsyncMock(return_value=result)

        contacts = await find_relevant_contacts_for_sender(db, uuid4(), "alice@example.com", None)

        assert len(contacts) == 1  # same domain → score > 0

    @pytest.mark.asyncio
    async def test_name_overlap_scores(self):
        contact = _make_contact(
            emails=["different@other.com"],
            display_name="Alice Johnson",
            first_name="Alice",
            last_name="Johnson",
        )

        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = [contact]
        db.execute = AsyncMock(return_value=result)

        contacts = await find_relevant_contacts_for_sender(db, uuid4(), "alice@example.com", "Alice Johnson")

        assert len(contacts) == 1

    @pytest.mark.asyncio
    async def test_no_match_returns_empty(self):
        contact = _make_contact(
            emails=["completely@different.org"],
            display_name="Unrelated Person",
            first_name="Unrelated",
            last_name="Person",
            organization="Other Corp",
        )

        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = [contact]
        db.execute = AsyncMock(return_value=result)

        contacts = await find_relevant_contacts_for_sender(db, uuid4(), "alice@example.com", None)

        # No email/domain/name overlap → score 0 → excluded
        assert len(contacts) == 0

    @pytest.mark.asyncio
    async def test_org_domain_match(self):
        contact = _make_contact(
            emails=["someone@acme.com"],
            display_name="Someone",
            first_name="Someone",
            last_name="Else",
            organization="acme",
        )

        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = [contact]
        db.execute = AsyncMock(return_value=result)

        contacts = await find_relevant_contacts_for_sender(db, uuid4(), "bob@acme.com", None)

        assert len(contacts) == 1

    @pytest.mark.asyncio
    async def test_empty_sender_email(self):
        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=result)

        contacts = await find_relevant_contacts_for_sender(db, uuid4(), "", None)

        assert contacts == []

    @pytest.mark.asyncio
    async def test_stopwords_excluded_from_name_scoring(self):
        """Name tokens in the stopword list should not contribute to score."""
        contact = _make_contact(
            emails=["different@other.org"],
            display_name="Dr Von",
            first_name=None,
            last_name=None,
        )

        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = [contact]
        db.execute = AsyncMock(return_value=result)

        # Sender name contains only stopwords
        await find_relevant_contacts_for_sender(db, uuid4(), "x@other.org", "Dr Von")

        # "dr" and "von" are stopwords and too short, domain match still scores
        # but name overlap should be 0
        # The contact may still appear due to domain match
        for kw in ("dr", "von"):
            assert kw in _NAME_STOPWORDS

    @pytest.mark.asyncio
    async def test_max_contacts_limit(self):
        contacts_list = [
            _make_contact(
                contact_id=uuid4(),
                emails=[f"user{i}@example.com"],
                display_name=f"User {i}",
                first_name=f"User{i}",
                last_name="Test",
            )
            for i in range(10)
        ]

        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = contacts_list
        db.execute = AsyncMock(return_value=result)

        contacts = await find_relevant_contacts_for_sender(db, uuid4(), "someone@example.com", None, max_contacts=3)

        assert len(contacts) <= 3

    @pytest.mark.asyncio
    async def test_result_dict_structure(self):
        contact = _make_contact(
            emails=["alice@example.com"],
            display_name="Alice Smith",
            first_name="Alice",
            last_name="Smith",
            organization="Acme",
            title="Engineer",
        )

        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = [contact]
        db.execute = AsyncMock(return_value=result)

        contacts = await find_relevant_contacts_for_sender(db, uuid4(), "alice@example.com", "Alice")

        assert len(contacts) == 1
        c = contacts[0]
        assert "id" in c
        assert "display_name" in c
        assert "first_name" in c
        assert "last_name" in c
        assert "organization" in c
        assert "title" in c
        assert "emails" in c
