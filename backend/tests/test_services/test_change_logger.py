"""Tests for app.services.change_logger."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.change_logger import (
    _deduplicate,
    extract_new_folders,
    extract_new_labels,
    save_new_folders,
    save_new_labels,
)

# ---------------------------------------------------------------------------
# _deduplicate
# ---------------------------------------------------------------------------


class TestDeduplicate:
    def test_empty(self):
        assert _deduplicate([]) == []

    def test_no_duplicates(self):
        assert _deduplicate(["a", "b", "c"]) == ["a", "b", "c"]

    def test_case_insensitive(self):
        assert _deduplicate(["Work", "work", "WORK"]) == ["Work"]

    def test_preserves_first_occurrence(self):
        assert _deduplicate(["Important", "important", "Urgent", "IMPORTANT"]) == [
            "Important",
            "Urgent",
        ]


# ---------------------------------------------------------------------------
# extract_new_labels
# ---------------------------------------------------------------------------


class TestExtractNewLabels:
    def test_empty_list(self):
        assert extract_new_labels([]) == []

    def test_log_new_labels_single(self):
        result = extract_new_labels(["log_new_labels:important"])
        assert result == ["important"]

    def test_log_new_labels_comma_separated(self):
        result = extract_new_labels(["log_new_labels:important, work, personal"])
        assert result == ["important", "work", "personal"]

    def test_create_and_apply_label(self):
        result = extract_new_labels(["create_and_apply_label:Receipts"])
        assert result == ["Receipts"]

    def test_mixed_actions(self):
        result = extract_new_labels(
            [
                "log_new_labels:important",
                "create_and_apply_label:Receipts",
                "apply_label:existing",
                "move_to:Archive",
            ]
        )
        assert result == ["important", "Receipts"]

    def test_deduplicates_case_insensitive(self):
        result = extract_new_labels(
            [
                "log_new_labels:Work",
                "create_and_apply_label:work",
            ]
        )
        assert result == ["Work"]

    def test_strips_whitespace(self):
        result = extract_new_labels(["log_new_labels: important , work "])
        assert result == ["important", "work"]

    def test_ignores_empty_values(self):
        result = extract_new_labels(["log_new_labels:"])
        assert result == []


# ---------------------------------------------------------------------------
# extract_new_folders
# ---------------------------------------------------------------------------


class TestExtractNewFolders:
    def test_empty_list(self):
        assert extract_new_folders([]) == []

    def test_log_new_folder(self):
        result = extract_new_folders(["log_new_folder:Receipts"])
        assert result == ["Receipts"]

    def test_create_folder(self):
        result = extract_new_folders(["create_folder:Projects/2024"])
        assert result == ["Projects/2024"]

    def test_mixed_actions(self):
        result = extract_new_folders(
            [
                "log_new_folder:Receipts",
                "create_folder:Archive",
                "apply_label:work",
            ]
        )
        assert result == ["Receipts", "Archive"]

    def test_deduplicates(self):
        result = extract_new_folders(
            [
                "log_new_folder:Receipts",
                "create_folder:receipts",
            ]
        )
        assert result == ["Receipts"]

    def test_ignores_empty_values(self):
        result = extract_new_folders(["log_new_folder:"])
        assert result == []


# ---------------------------------------------------------------------------
# save_new_labels
# ---------------------------------------------------------------------------


class TestSaveNewLabels:
    @pytest.mark.asyncio
    async def test_no_labels_skips_db(self):
        """When actions produce no labels, no DB session is opened."""
        with patch("app.services.change_logger.get_session_ctx") as mock_ctx:
            await save_new_labels(uuid4(), uuid4(), ["apply_label:existing"])
            mock_ctx.assert_not_called()

    @pytest.mark.asyncio
    async def test_saves_labels(self):
        user_id = uuid4()
        account_id = uuid4()
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()

        @asynccontextmanager
        async def fake_session_ctx():
            yield mock_db

        with patch("app.services.change_logger.get_session_ctx", fake_session_ctx):
            await save_new_labels(user_id, account_id, ["log_new_labels:important, work"])

        assert mock_db.add.call_count == 2
        mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_commit_failure_logs_exception(self):
        user_id = uuid4()
        account_id = uuid4()
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock(side_effect=Exception("db error"))

        @asynccontextmanager
        async def fake_session_ctx():
            yield mock_db

        with patch("app.services.change_logger.get_session_ctx", fake_session_ctx):
            # Should not raise
            await save_new_labels(user_id, account_id, ["create_and_apply_label:Test"])


# ---------------------------------------------------------------------------
# save_new_folders
# ---------------------------------------------------------------------------


class TestSaveNewFolders:
    @pytest.mark.asyncio
    async def test_no_folders_skips_db(self):
        with patch("app.services.change_logger.get_session_ctx") as mock_ctx:
            await save_new_folders(uuid4(), uuid4(), ["apply_label:work"])
            mock_ctx.assert_not_called()

    @pytest.mark.asyncio
    async def test_saves_folders(self):
        user_id = uuid4()
        account_id = uuid4()
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()

        @asynccontextmanager
        async def fake_session_ctx():
            yield mock_db

        with patch("app.services.change_logger.get_session_ctx", fake_session_ctx):
            await save_new_folders(
                user_id,
                account_id,
                [
                    "log_new_folder:Receipts",
                    "create_folder:Archive",
                ],
            )

        assert mock_db.add.call_count == 2
        mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_commit_failure_logs_exception(self):
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock(side_effect=Exception("db error"))

        @asynccontextmanager
        async def fake_session_ctx():
            yield mock_db

        with patch("app.services.change_logger.get_session_ctx", fake_session_ctx):
            await save_new_folders(uuid4(), uuid4(), ["create_folder:Test"])
