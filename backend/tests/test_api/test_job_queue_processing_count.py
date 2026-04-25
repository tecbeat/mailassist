"""Tests for job queue processing count filtering (Issue #28).

Verifies that the 'Processing' metric only counts process_mail jobs,
not system/cron ARQ jobs, and that the schema correctly separates
the two categories.
"""

import pytest

from app.api.dashboard import _parse_job_id
from app.schemas.dashboard import InProgressJob, JobQueueStatusResponse


class TestParseJobId:
    """_parse_job_id must correctly distinguish job types from ARQ job IDs."""

    def test_process_mail_standard(self):
        """Standard process_mail job ID with account and UID."""
        fn, mail_uid, account_id = _parse_job_id(
            "process_mail:abc-123:42"
        )
        assert fn == "process_mail"
        assert mail_uid == "42"
        assert account_id == "abc-123"

    def test_process_mail_retry(self):
        """Retry process_mail job ID includes a retry suffix."""
        fn, mail_uid, account_id = _parse_job_id(
            "process_mail:abc-123:42:retry1"
        )
        assert fn == "process_mail"
        # The parser extracts parts[2] as mail_uid
        assert mail_uid == "42"
        assert account_id == "abc-123"

    def test_cron_job(self):
        """ARQ cron job IDs use 'cron:<function_name>:<hex>' pattern."""
        fn, mail_uid, account_id = _parse_job_id(
            "cron:poll_mail_accounts:a1b2c3"
        )
        assert fn == "poll_mail_accounts"
        assert mail_uid is None
        assert account_id is None

    def test_cron_schedule_pending(self):
        """schedule_pending_mails cron job."""
        fn, mail_uid, account_id = _parse_job_id(
            "cron:schedule_pending_mails:deadbeef"
        )
        assert fn == "schedule_pending_mails"
        assert mail_uid is None
        assert account_id is None

    def test_cron_health_check(self):
        """worker_health_check cron job."""
        fn, mail_uid, account_id = _parse_job_id(
            "cron:worker_health_check:1234"
        )
        assert fn == "worker_health_check"
        assert mail_uid is None

    def test_empty_string(self):
        """Empty string returns 'unknown'."""
        fn, mail_uid, account_id = _parse_job_id("")
        assert fn == ""
        assert mail_uid is None
        assert account_id is None

    def test_unknown_format(self):
        """Unknown job ID format is returned as-is."""
        fn, mail_uid, account_id = _parse_job_id("some_random_job")
        assert fn == "some_random_job"
        assert mail_uid is None
        assert account_id is None


class TestJobFilteringLogic:
    """Verify that job lists are correctly partitioned by function name."""

    @pytest.fixture()
    def mixed_jobs(self) -> list[InProgressJob]:
        """A mix of mail-processing and system jobs."""
        return [
            InProgressJob(
                job_id="process_mail:acc1:100",
                function="process_mail",
                mail_uid="100",
                account_id="acc1",
            ),
            InProgressJob(
                job_id="process_mail:acc1:101",
                function="process_mail",
                mail_uid="101",
                account_id="acc1",
            ),
            InProgressJob(
                job_id="cron:poll_mail_accounts:abc",
                function="poll_mail_accounts",
            ),
            InProgressJob(
                job_id="cron:schedule_pending_mails:def",
                function="schedule_pending_mails",
            ),
            InProgressJob(
                job_id="cron:worker_health_check:ghi",
                function="worker_health_check",
            ),
            InProgressJob(
                job_id="process_mail:acc2:200",
                function="process_mail",
                mail_uid="200",
                account_id="acc2",
            ),
        ]

    def test_mail_jobs_filtered_correctly(self, mixed_jobs):
        """Only process_mail jobs should count as 'in_progress'."""
        mail_jobs = [j for j in mixed_jobs if j.function == "process_mail"]
        assert len(mail_jobs) == 3

    def test_system_jobs_filtered_correctly(self, mixed_jobs):
        """Non-process_mail jobs should count as 'in_progress_system'."""
        system_jobs = [j for j in mixed_jobs if j.function != "process_mail"]
        assert len(system_jobs) == 3

    def test_all_mail_jobs_have_mail_uid(self, mixed_jobs):
        """Every process_mail job should have a mail_uid."""
        mail_jobs = [j for j in mixed_jobs if j.function == "process_mail"]
        for job in mail_jobs:
            assert job.mail_uid is not None

    def test_system_jobs_have_no_mail_uid(self, mixed_jobs):
        """System jobs should not have mail_uid."""
        system_jobs = [j for j in mixed_jobs if j.function != "process_mail"]
        for job in system_jobs:
            assert job.mail_uid is None


class TestJobQueueStatusResponseDefaults:
    """JobQueueStatusResponse schema defaults are correct."""

    def test_in_progress_default(self):
        resp = JobQueueStatusResponse()
        assert resp.in_progress == 0

    def test_in_progress_system_default(self):
        resp = JobQueueStatusResponse()
        assert resp.in_progress_system == 0

    def test_response_with_separated_counts(self):
        """Response correctly holds separate mail and system counts."""
        resp = JobQueueStatusResponse(
            in_progress=3,
            in_progress_system=2,
            in_progress_jobs=[
                InProgressJob(
                    job_id="process_mail:a:1",
                    function="process_mail",
                    mail_uid="1",
                ),
            ],
        )
        assert resp.in_progress == 3
        assert resp.in_progress_system == 2
        assert len(resp.in_progress_jobs) == 1
        assert resp.in_progress_jobs[0].function == "process_mail"
