from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.applied_label import (
    AppliedLabelCreate,
    AppliedLabelListResponse,
    AppliedLabelResponse,
    LabelSummary,
    LabelSummaryListResponse,
)
from app.schemas.assigned_folder import (
    AssignedFolderResponse,
    FolderSummary,
    SmartFolderReprocessResponse,
    SmartFolderResetAccountResult,
    SmartFolderResetResponse,
)
from app.schemas.auto_reply import AutoReplyRecordResponse, AutoReplyRecordUpdate
from app.schemas.calendar import (
    CalDAVConfigResponse,
    CalDAVConfigUpdate,
    CalDAVTestRequest,
    CalDAVTestResponse,
)
from app.schemas.calendar_event import CalendarEventResponse, CalendarEventUpdate
from app.schemas.contacts import (
    AssignEmailRequest,
    CardDAVConfigCreate,
    CardDAVConfigResponse,
    CardDAVConfigUpdate,
    CardDAVTestRequest,
    ContactAssignmentResponse,
    ContactCreateRequest,
    ContactExtractedData,
    ContactExtractRequest,
    ContactResponse,
    SyncResult,
    UnmatchedSenderResponse,
)
from app.schemas.coupon import CouponUpdate, ExtractedCouponResponse
from app.schemas.newsletter import DetectedNewsletterResponse
from app.schemas.notification import (
    NotificationChannelCreate,
    NotificationChannelResponse,
    NotificationConfigResponse,
    NotificationEventInfo,
    NotificationPreviewRequest,
    NotificationTestRequest,
    mask_apprise_url,
)
from app.schemas.otp import ExtractedOtpCodeResponse
from app.schemas.pipeline import (
    PipelineTestRequest,
    PipelineTestResponse,
    PluginTestResult,
)
from app.schemas.prompt import (
    PromptPreviewRequest,
    PromptResponse,
    PromptUpdate,
    TemplateVariable,
)
from app.schemas.spam import (
    BlocklistEntryCreate,
    BlocklistEntryResponse,
    SpamReportRequest,
    SpamReportResult,
)

NOW = datetime.now(UTC)
UID = uuid4()


# ── applied_label ──────────────────────────────────────────────────────────


class TestAppliedLabel:
    def test_response(self) -> None:
        obj = AppliedLabelResponse(id=UID, label="Important", is_new_label=False, created_at=NOW)
        assert obj.label == "Important"
        assert obj.mail_subject is None

    def test_list_response(self) -> None:
        item = AppliedLabelResponse(id=UID, label="X", is_new_label=True, created_at=NOW)
        obj = AppliedLabelListResponse(items=[item], total=1, page=1, per_page=10, pages=1)
        assert obj.total == 1

    def test_label_summary(self) -> None:
        obj = LabelSummary(label="X", count=5)
        assert obj.count == 5

    def test_label_summary_list(self) -> None:
        obj = LabelSummaryListResponse(items=[LabelSummary(label="X", count=1)], total=1)
        assert obj.total == 1

    def test_create_valid(self) -> None:
        obj = AppliedLabelCreate(label="ok")
        assert obj.label == "ok"

    def test_create_empty_label(self) -> None:
        with pytest.raises(ValidationError):
            AppliedLabelCreate(label="")

    def test_create_too_long(self) -> None:
        with pytest.raises(ValidationError):
            AppliedLabelCreate(label="x" * 201)


# ── assigned_folder ────────────────────────────────────────────────────────


class TestAssignedFolder:
    def test_response(self) -> None:
        obj = AssignedFolderResponse(id=UID, folder="Inbox", is_new_folder=False, created_at=NOW)
        assert obj.folder == "Inbox"

    def test_folder_summary(self) -> None:
        obj = FolderSummary(folder="Archive", count=3)
        assert obj.count == 3

    def test_reset_account_result(self) -> None:
        obj = SmartFolderResetAccountResult(account_id="a1", account_name="Main")
        assert obj.moved_to_inbox is None

    def test_reset_response(self) -> None:
        acct = SmartFolderResetAccountResult(account_id="a", account_name="A")
        obj = SmartFolderResetResponse(
            folder="X",
            accounts=[acct],
            deleted_assigned_folders=1,
            deleted_folder_change_logs=2,
            reset_tracked_emails=3,
        )
        assert obj.deleted_assigned_folders == 1

    def test_reprocess_response(self) -> None:
        obj = SmartFolderReprocessResponse(folder="X", requeued_emails=5)
        assert obj.requeued_emails == 5


# ── auto_reply ─────────────────────────────────────────────────────────────


class TestAutoReply:
    def test_response(self) -> None:
        obj = AutoReplyRecordResponse(
            id=UID,
            draft_body="Hi",
            created_at=NOW,
            updated_at=NOW,
        )
        assert obj.draft_body == "Hi"

    def test_update_valid(self) -> None:
        obj = AutoReplyRecordUpdate(draft_body="hello", tone="formal")
        assert obj.tone == "formal"

    def test_update_empty_body(self) -> None:
        with pytest.raises(ValidationError):
            AutoReplyRecordUpdate(draft_body="")

    def test_update_body_too_long(self) -> None:
        with pytest.raises(ValidationError):
            AutoReplyRecordUpdate(draft_body="x" * 5001)

    def test_update_tone_too_long(self) -> None:
        with pytest.raises(ValidationError):
            AutoReplyRecordUpdate(tone="x" * 51)

    def test_update_none_defaults(self) -> None:
        obj = AutoReplyRecordUpdate()
        assert obj.draft_body is None
        assert obj.tone is None


# ── calendar ───────────────────────────────────────────────────────────────


class TestCalDAV:
    def test_config_response(self) -> None:
        obj = CalDAVConfigResponse(
            id=UID,
            caldav_url="https://cal.example.com",
            default_calendar="Personal",
            include_past_events=False,
            is_active=True,
            created_at=NOW,
            updated_at=NOW,
        )
        assert obj.is_active is True

    def test_config_update_valid(self) -> None:
        obj = CalDAVConfigUpdate(
            caldav_url="https://cal.example.com",
            username="u",
            password="p",
            default_calendar="cal",
        )
        assert obj.include_past_events is False

    def test_config_update_http_rejected(self) -> None:
        with pytest.raises(ValidationError, match="HTTPS"):
            CalDAVConfigUpdate(
                caldav_url="http://cal.example.com",
                username="u",
                password="p",
                default_calendar="cal",
            )

    def test_test_request_none_url(self) -> None:
        obj = CalDAVTestRequest()
        assert obj.caldav_url is None

    def test_test_request_valid_url(self) -> None:
        obj = CalDAVTestRequest(caldav_url="https://cal.example.com")
        assert obj.caldav_url == "https://cal.example.com"

    def test_test_request_http_rejected(self) -> None:
        with pytest.raises(ValidationError, match="HTTPS"):
            CalDAVTestRequest(caldav_url="http://bad.com")

    def test_test_response(self) -> None:
        obj = CalDAVTestResponse(success=True, message="ok")
        assert obj.calendars == []
        assert obj.details is None


# ── calendar_event ─────────────────────────────────────────────────────────


class TestCalendarEvent:
    def test_response(self) -> None:
        obj = CalendarEventResponse(
            id=UID,
            title="Meeting",
            is_all_day=False,
            caldav_synced=True,
            created_at=NOW,
            updated_at=NOW,
        )
        assert obj.title == "Meeting"

    def test_update_valid(self) -> None:
        obj = CalendarEventUpdate(title="New", location="Room A")
        assert obj.title == "New"

    def test_update_empty_title(self) -> None:
        with pytest.raises(ValidationError):
            CalendarEventUpdate(title="")


# ── coupon ─────────────────────────────────────────────────────────────────


class TestCoupon:
    def test_response(self) -> None:
        obj = ExtractedCouponResponse(id=UID, is_used=False, created_at=NOW, updated_at=NOW)
        assert obj.code is None

    def test_update(self) -> None:
        obj = CouponUpdate(is_used=True)
        assert obj.is_used is True


# ── newsletter ─────────────────────────────────────────────────────────────


class TestNewsletter:
    def test_response(self) -> None:
        obj = DetectedNewsletterResponse(
            id=UID,
            newsletter_name="Weekly",
            sender_address="news@example.com",
            has_unsubscribe=True,
            created_at=NOW,
        )
        assert obj.has_unsubscribe is True


# ── otp ────────────────────────────────────────────────────────────────────


class TestOtp:
    def test_response(self) -> None:
        obj = ExtractedOtpCodeResponse(
            id=UID,
            code="123456",
            code_type="totp",
            is_expired=False,
            created_at=NOW,
            updated_at=NOW,
        )
        assert obj.code == "123456"


# ── pipeline ──────────────────────────────────────────────────────────────


class TestPipeline:
    def test_request_defaults(self) -> None:
        obj = PipelineTestRequest()
        assert obj.sender == "test@example.com"
        assert obj.has_attachments is False
        assert obj.is_reply is False
        assert obj.is_forwarded is False
        assert obj.date == ""

    def test_plugin_result(self) -> None:
        obj = PluginTestResult(
            plugin_name="label",
            display_name="Labeler",
            success=True,
        )
        assert obj.actions == []
        assert obj.tokens_used == 0
        assert obj.skipped is False

    def test_pipeline_response(self) -> None:
        obj = PipelineTestResponse(success=True)
        assert obj.plugins_executed == 0
        assert obj.results == []


# ── prompt ─────────────────────────────────────────────────────────────────


class TestPrompt:
    def test_response(self) -> None:
        obj = PromptResponse(
            function_type="label",
            system_prompt="You are helpful",
            user_prompt=None,
            is_custom=False,
        )
        assert obj.id is None

    def test_update_valid(self) -> None:
        obj = PromptUpdate(system_prompt="Do stuff")
        assert obj.user_prompt is None

    def test_update_empty_system(self) -> None:
        with pytest.raises(ValidationError):
            PromptUpdate(system_prompt="")

    def test_update_too_long(self) -> None:
        with pytest.raises(ValidationError):
            PromptUpdate(system_prompt="x" * 50001)

    def test_preview_request(self) -> None:
        obj = PromptPreviewRequest(system_prompt="hi")
        assert obj.user_prompt is None

    def test_template_variable(self) -> None:
        obj = TemplateVariable(name="sender", var_type="str", description="Sender", example="a@b.com")
        assert obj.name == "sender"


# ── spam ───────────────────────────────────────────────────────────────────


class TestSpam:
    def test_report_request(self) -> None:
        obj = SpamReportRequest(mail_uid="123", mail_account_id=UID, sender_email="s@x.com")
        assert obj.subject is None

    def test_blocklist_create_valid(self) -> None:
        obj = BlocklistEntryCreate(entry_type="email", value="spam@x.com")
        assert obj.value == "spam@x.com"

    def test_blocklist_create_invalid_type(self) -> None:
        with pytest.raises(ValidationError, match="entry_type"):
            BlocklistEntryCreate(entry_type="invalid", value="x")

    def test_blocklist_create_empty_value(self) -> None:
        with pytest.raises(ValidationError, match="empty"):
            BlocklistEntryCreate(entry_type="email", value="   ")

    def test_blocklist_create_domain(self) -> None:
        obj = BlocklistEntryCreate(entry_type="domain", value="evil.com")
        assert obj.entry_type == "domain"

    def test_blocklist_create_pattern(self) -> None:
        obj = BlocklistEntryCreate(entry_type="pattern", value="free*")
        assert obj.entry_type == "pattern"

    def test_blocklist_response(self) -> None:
        obj = BlocklistEntryResponse(
            id=UID,
            entry_type="email",
            value="x@y.com",
            source="manual",
            source_mail_uid=None,
            created_at=NOW,
        )
        assert obj.source == "manual"

    def test_report_result(self) -> None:
        obj = SpamReportResult(blocked_entries_created=2, mail_moved=True, message="done")
        assert obj.mail_moved is True


# ── notification ───────────────────────────────────────────────────────────


class TestMaskAppriseUrl:
    def test_full_url_with_creds(self) -> None:
        result = mask_apprise_url("https://user:pass@example.com:8080/token/id")
        assert "user" not in result
        assert "pass" not in result
        assert "token" not in result
        assert "example.com" in result
        assert "8080" in result
        assert "***" in result

    def test_url_without_creds(self) -> None:
        result = mask_apprise_url("https://example.com/webhook/abc")
        assert "example.com" in result
        assert "abc" not in result

    def test_url_no_path(self) -> None:
        result = mask_apprise_url("https://example.com")
        assert result == "https://example.com"

    def test_invalid_url(self) -> None:
        result = mask_apprise_url("not-a-url")
        # urlparse succeeds but with empty scheme → "unknown"
        assert "unknown" in result

    def test_url_with_scheme_but_broken(self) -> None:
        result = mask_apprise_url("foo://")
        # Should not raise
        assert "foo://" in result

    def test_slash_only_path(self) -> None:
        result = mask_apprise_url("https://example.com/")
        assert "example.com" in result


class TestNotificationSchemas:
    def test_channel_create(self) -> None:
        obj = NotificationChannelCreate(url="https://hook.example.com/x")
        assert obj.mail_account_ids is None
        assert obj.event_types is None

    def test_channel_response(self) -> None:
        obj = NotificationChannelResponse(
            id=UID,
            url="https://***",
            mail_account_ids=None,
            event_types=None,
            created_at=NOW,
            updated_at=NOW,
        )
        assert obj.url == "https://***"

    def test_config_response(self) -> None:
        obj = NotificationConfigResponse(id=UID, templates={"key": "val"}, updated_at=NOW)
        assert obj.templates["key"] == "val"

    def test_test_request_default(self) -> None:
        obj = NotificationTestRequest()
        assert "Test" in obj.message

    def test_preview_request(self) -> None:
        obj = NotificationPreviewRequest(template="hi {{ name }}", event_type="label")
        assert obj.event_type == "label"

    def test_event_info(self) -> None:
        obj = NotificationEventInfo(
            event_type="label_applied",
            plugin_name="labeler",
            display_name="Labeler",
            execution_order=1,
        )
        assert obj.execution_order == 1


# ── contacts ───────────────────────────────────────────────────────────────


class TestContacts:
    def test_carddav_create_valid(self) -> None:
        obj = CardDAVConfigCreate(
            carddav_url="https://dav.example.com",
            username="u",
            password="p",
            address_book="default",
        )
        assert obj.sync_interval == 15

    def test_carddav_create_http_rejected(self) -> None:
        with pytest.raises(ValidationError, match="HTTPS"):
            CardDAVConfigCreate(
                carddav_url="http://dav.example.com",
                username="u",
                password="p",
                address_book="default",
            )

    def test_carddav_update_valid(self) -> None:
        obj = CardDAVConfigUpdate(carddav_url="https://new.example.com")
        assert obj.username is None

    def test_carddav_update_http_rejected(self) -> None:
        with pytest.raises(ValidationError, match="HTTPS"):
            CardDAVConfigUpdate(carddav_url="http://bad.com")

    def test_carddav_update_none_url(self) -> None:
        obj = CardDAVConfigUpdate()
        assert obj.carddav_url is None

    def test_carddav_response(self) -> None:
        obj = CardDAVConfigResponse(
            id=UID,
            carddav_url="https://dav.example.com",
            address_book="default",
            sync_interval=15,
            last_sync_at=None,
            is_active=True,
        )
        assert obj.is_active is True

    def test_carddav_test_request_valid(self) -> None:
        obj = CardDAVTestRequest(
            carddav_url="https://dav.example.com",
            username="u",
            password="p",
        )
        assert obj.address_book == ""

    def test_carddav_test_request_http_rejected(self) -> None:
        with pytest.raises(ValidationError, match="HTTPS"):
            CardDAVTestRequest(carddav_url="http://bad.com", username="u", password="p")

    def test_contact_response(self) -> None:
        obj = ContactResponse(
            id=UID,
            display_name="Alice",
            first_name="Alice",
            last_name=None,
            emails=["a@b.com"],
            phones=None,
            organization=None,
            title=None,
            photo_url=None,
            synced_at=NOW,
            created_at=NOW,
        )
        assert obj.display_name == "Alice"

    def test_unmatched_sender(self) -> None:
        obj = UnmatchedSenderResponse(email_address="x@y.com", mail_count=3)
        assert obj.mail_count == 3

    def test_assign_email_request(self) -> None:
        obj = AssignEmailRequest(email_address="a@b.com")
        assert obj.email_address == "a@b.com"

    def test_sync_result(self) -> None:
        obj = SyncResult(added=1, updated=2, deleted=0, errors=0)
        assert obj.added == 1

    def test_contact_assignment_response(self) -> None:
        obj = ContactAssignmentResponse(
            id=UID,
            contact_name="Bob",
            confidence=0.95,
            is_new_contact_suggestion=False,
            created_at=NOW,
        )
        assert obj.confidence == 0.95

    def test_contact_extract_request(self) -> None:
        obj = ContactExtractRequest(sender_email="x@y.com")
        assert obj.sender_email == "x@y.com"

    def test_contact_extracted_data(self) -> None:
        obj = ContactExtractedData(display_name="Alice")
        assert obj.emails == []

    def test_contact_create_request_valid(self) -> None:
        obj = ContactCreateRequest(display_name="Bob", emails=["b@c.com"])
        assert obj.first_name is None

    def test_contact_create_request_empty_name(self) -> None:
        with pytest.raises(ValidationError):
            ContactCreateRequest(display_name="")
